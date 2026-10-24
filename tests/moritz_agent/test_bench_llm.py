# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""scripts/bench_llm.py (ticket P1-02): --moecpu search and the 40 phone questions."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from moritz_agent.config.settings import Settings
from moritz_agent.setup import files

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("bench_llm", ROOT / "scripts" / "bench_llm.py")
assert _spec and _spec.loader
bench = importlib.util.module_from_spec(_spec)
sys.modules["bench_llm"] = bench
_spec.loader.exec_module(bench)


def _config(tmp_path: Path) -> tuple[Path, Path]:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    text = (ROOT / "config" / "moritz-agent.example.toml").read_text(encoding="utf-8")
    for section, key, value in [
        ("inference", "koboldcpp_script", '"tests/moritz_agent/fake_koboldcpp.py"'),
        ("inference", "python", f'"{sys.executable}"'),
        ("inference", "model", f'"{model}"'),
        ("inference", "use_cuda", "false"),
        ("inference", "startup_timeout_s", "20"),
        ("storage", "database", f'"{tmp_path / "db.sqlite3"}"'),
        ("skills", "online", "false"),
    ]:
        text = files.set_value(text, section, key, value, keep_comment=True)
    config = tmp_path / "config.toml"
    config.write_text(text, encoding="utf-8")
    passwords = tmp_path / "passwords.txt"
    passwords.write_text(
        (ROOT / "config" / "passwords.template.txt").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return config, passwords


def test_the_questions_are_forty_phone_questions_with_known_tools():
    lines = (ROOT / "tests/moritz_agent/data/phone_questions.de.jsonl").read_text().splitlines()
    items = [json.loads(line) for line in lines]
    assert len(items) == 40 and all(item["q"].strip() for item in items)
    tools = {tool for item in items for tool in item["tools"]}
    example = (ROOT / "config" / "moritz-agent.example.toml").read_text()
    assert all(f'"{tool}"' in example for tool in tools)  # only tools the phone profile has


def test_against_a_koboldcpp_process_it_writes_the_table(tmp_path):
    config, passwords = _config(tmp_path)
    out = tmp_path / "out"
    code = bench.main(
        ["--config", str(config), "--passwords", str(passwords), "--out", str(out), "--limit", "4"]
    )
    data = json.loads((out / "llm-bench.json").read_text())
    table = (out / "llm-bench.md").read_text()
    assert code in (0, 1) and data["summary"]["questions"] == 4
    assert data["summary"]["answered"] == 4 and "get_current_time" in data["answers"][0]["tools"]
    assert "--moecpu 24" in table and "Wie viel Uhr ist es gerade?" in table


def test_the_search_goes_up_until_it_fits_and_down_while_there_is_room(monkeypatch):
    def fake(free_by_n):
        async def start(settings, n):
            free = free_by_n.get(n)
            load = bench.Load(n, free is not None, 1.0)
            if free is not None:
                load.vram_total_mb, load.vram_used_mb = 8192, 8192 - free
            return None, load

        return start

    settings = Settings()
    monkeypatch.setattr(bench, "start", fake({24: 100, 28: 400, 32: 900}))
    best, loads = asyncio.run(bench.tune(settings))
    assert best == 32 and [x.moe_cpu_layers for x in loads] == [24, 28, 32]
    monkeypatch.setattr(bench, "start", fake({24: 2500, 20: 1900, 16: 300}))
    best, loads = asyncio.run(bench.tune(settings))
    assert best == 20 and [x.moe_cpu_layers for x in loads] == [24, 20, 16]


def test_tokens_per_second_from_koboldcpps_numbers():
    """Seen on Sophie-1: "0.6 Tokens/s" – last_eval is milliseconds per token, not seconds."""
    assert bench.generation_speed({"last_eval_speed": 24.4, "last_eval": 41.0}) == 24.4
    assert bench.generation_speed({"last_eval": 40.0, "last_token_count": 25}) == 25.0
    assert bench.generation_speed({}) is None
