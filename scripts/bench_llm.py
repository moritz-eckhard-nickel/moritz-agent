#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Measure the language model on Sophie-1 (ticket P1-02, ADR-016).

1. ``--tune``: find ``--moecpu N`` – as many expert layers on the GPU as fit while at least
   600 MB of VRAM stay free – and write N into config/moritz-agent.toml ([inference] moe_cpu_layers).
2. 40 German phone questions (tests/moritz_agent/data/phone_questions.de.jsonl) straight through the
   agent loop (no instant answers in front): time to the first words, whole answer, tokens per
   second, did the right tool run.

Results: runtime/test-3/llm-bench.md (table for ADR-016) and llm-bench.json (for the protocol).

    python scripts/bench_llm.py [--tune] [--limit N] [--out DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moritz_agent.config.reload import ConfigManager  # noqa: E402
from moritz_agent.config.settings import Settings  # noqa: E402
from moritz_agent.inference.process import InferenceService  # noqa: E402
from moritz_agent.setup import files  # noqa: E402
from moritz_agent.tools.base import ToolContext  # noqa: E402

QUESTIONS = ROOT / "tests" / "moritz_agent" / "data" / "phone_questions.de.jsonl"
MIN_FREE_MB = 600  # ADR-016: keep at least this much VRAM free
LAYERS = 48  # Qwen3-30B-A3B
STEP = 4


@dataclass
class Load:
    moe_cpu_layers: int
    ready: bool
    load_s: float = 0.0
    vram_used_mb: int | None = None
    vram_total_mb: int | None = None
    ram_mb: int | None = None

    @property
    def vram_free_mb(self) -> int | None:
        if self.vram_used_mb is None or self.vram_total_mb is None:
            return None
        return self.vram_total_mb - self.vram_used_mb

    @property
    def fits(self) -> bool:
        free = self.vram_free_mb
        return self.ready and (free is None or free >= MIN_FREE_MB)


@dataclass
class Answer:
    kind: str
    question: str
    expected_tools: list[str]
    text: str = ""
    tools: list[str] = field(default_factory=list)
    steps: int = 0
    failure: str | None = None
    guard: str | None = None
    first_ms: int | None = None
    total_ms: int = 0
    tokens_per_s: float | None = None

    @property
    def answered(self) -> bool:
        return bool(self.text.strip()) and self.failure is None

    @property
    def tool_ok(self) -> bool:
        return not self.expected_tools or bool(set(self.tools) & set(self.expected_tools))


# -- measuring -----------------------------------------------------------------------------------
def gpu_memory() -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.splitlines()[0]
        used, total = (int(v.strip()) for v in out.split(","))
        return used, total
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def rss_mb(pid: int | None) -> int | None:
    if pid is None:
        return None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def generation_speed(perf: dict[str, Any]) -> float | None:
    """Tokens per second of the last generation. KoboldCpp reports ``last_eval_speed``; older
    versions only ``last_eval`` – milliseconds per token, not seconds in total."""
    speed = perf.get("last_eval_speed")
    if not speed and perf.get("last_eval"):
        speed = 1000.0 / float(perf["last_eval"])
    return round(float(speed), 1) if speed else None


def with_layers(settings: Settings, n: int) -> Settings:
    inference = settings.inference.model_copy(update={"moe_cpu_layers": n})
    return settings.model_copy(update={"inference": inference})


async def start(settings: Settings, n: int) -> tuple[InferenceService | None, Load]:
    """KoboldCpp with ``--moecpu n``; ``None`` if it does not come up (out of memory and the like)."""
    service = InferenceService(with_layers(settings, n), ROOT)
    started = time.monotonic()
    await service.start()
    deadline = started + settings.inference.startup_timeout_s
    ready = False
    while time.monotonic() < deadline:
        status = service.process.status()
        if status.state == "ready":
            ready = True
            break
        if status.restarts or status.state == "failed":
            break  # it crashed once: this N does not work
        await asyncio.sleep(1)
    load = Load(n, ready, round(time.monotonic() - started, 1))
    if not ready:
        await service.stop()
        return None, load
    await service.client.chat([{"role": "user", "content": "Sag Hallo."}], max_tokens=8)
    memory = gpu_memory()
    if memory:
        load.vram_used_mb, load.vram_total_mb = memory
    load.ram_mb = rss_mb(service.process.status().pid)
    return service, load


async def tune(settings: Settings) -> tuple[int, list[Load]]:
    """Up from the configured N until it fits, or down while there is plenty of room."""
    n = settings.inference.moe_cpu_layers
    loads: list[Load] = []
    best: int | None = None
    for _ in range(8):
        service, load = await start(settings, n)
        loads.append(load)
        print(_load_line(load), flush=True)
        if service is not None:
            await service.stop()
        if load.fits:
            best = n
            free = load.vram_free_mb
            if free is not None and free > 3 * MIN_FREE_MB and n - STEP >= 0:
                if any(x.moe_cpu_layers == n - STEP for x in loads):
                    break
                n -= STEP  # room to spare: more experts onto the GPU (faster)
                continue
            break
        if best is not None:
            break  # going down overshot: keep the last one that fit
        n += STEP
        if n > LAYERS:
            break
    if best is None:
        raise SystemExit(
            "Kein --moecpu-Wert passt – Modell zu groß für GPU und RAM? (ADR-016 Fallbacks)"
        )
    return best, loads


def _load_line(load: Load) -> str:
    if not load.ready:
        return f"  --moecpu {load.moe_cpu_layers:2d}: startet nicht ({load.load_s:.0f} s)"
    free = load.vram_free_mb
    vram = (
        f"VRAM {load.vram_used_mb}/{load.vram_total_mb} MB (frei {free})"
        if free is not None
        else "VRAM ?"
    )
    return f"  --moecpu {load.moe_cpu_layers:2d}: {vram}, RAM {load.ram_mb} MB, geladen in {load.load_s:.0f} s"


async def ask_all(
    config: ConfigManager, service: InferenceService, questions: list[dict[str, Any]]
) -> list[Answer]:
    from moritz_agent.runtime import Runtime

    runtime = Runtime(config, ROOT, manage_processes=False, inference_client=service.client)
    await runtime.start()
    answers: list[Answer] = []
    try:
        loop = runtime.agent_loop
        if loop is None:
            raise SystemExit("Der Agent ist nicht verfügbar (Konfiguration [agent] prüfen).")
        for number, item in enumerate(questions, 1):
            answer = Answer(item["kind"], item["q"], list(item.get("tools", [])))
            started = time.monotonic()

            def first(_chunk: str, answer: Answer = answer, started: float = started) -> None:
                if answer.first_ms is None:
                    answer.first_ms = round((time.monotonic() - started) * 1000)

            ctx = ToolContext(profile="phone", channel="phone", call_id=f"bench-{number}")
            try:
                result = await loop.run(item["q"], [], ctx, on_text=first)
            except Exception as exc:  # a failing question is a result, not a crash
                answer.failure = f"{type(exc).__name__}: {exc}"[:120]
            else:
                answer.text, answer.tools, answer.steps = result.text, result.tools, result.steps
                answer.failure, answer.guard, answer.total_ms = (
                    result.failure,
                    result.guard,
                    result.ms,
                )
            answer.tokens_per_s = generation_speed(await service.client.perf())
            mark = "✔" if answer.answered and answer.tool_ok else "✘"
            print(
                f"  {mark} {number:2d}. {answer.question[:48]:48s} {answer.total_ms:5d} ms  {', '.join(answer.tools) or '–'}",
                flush=True,
            )
            answers.append(answer)
    finally:
        await runtime.stop()
    return answers


# -- report --------------------------------------------------------------------------------------
def summary(answers: list[Answer]) -> dict[str, Any]:
    def median(values: list[float]) -> float | None:
        return round(statistics.median(values), 1) if values else None

    with_tools = [a for a in answers if a.expected_tools]
    return {
        "questions": len(answers),
        "answered": sum(a.answered for a in answers),
        "tool_ok": sum(a.tool_ok for a in with_tools),
        "tool_questions": len(with_tools),
        "median_first_ms": median([a.first_ms for a in answers if a.first_ms is not None]),
        "median_total_ms": median([a.total_ms for a in answers if a.answered]),
        "median_tokens_per_s": median([a.tokens_per_s for a in answers if a.tokens_per_s]),
        "guarded": sum(a.guard is not None for a in answers),
    }


def markdown(
    settings: Settings, best: int, loads: list[Load], answers: list[Answer], total: dict[str, Any]
) -> str:
    model = Path(settings.inference.model).name
    lines = [
        "# Sprachmodell auf Sophie-1 – Messung (P1-02, ADR-016)",
        "",
        f"Stand {time.strftime('%d.%m.%Y %H:%M')} · Modell `{model}` · Kontext {settings.inference.context_size}"
        f" · Threads {settings.inference.threads} · **`--moecpu {best}`**",
        "",
        "## Speicher je `--moecpu`",
        "",
        "| --moecpu | startet | VRAM belegt / gesamt | VRAM frei | RAM (KoboldCpp) | Ladezeit |",
        "| ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for load in loads:
        lines.append(
            f"| {load.moe_cpu_layers} | {'ja' if load.ready else 'nein'} | "
            f"{load.vram_used_mb or '–'} / {load.vram_total_mb or '–'} MB | {load.vram_free_mb if load.vram_free_mb is not None else '–'} MB | "
            f"{load.ram_mb or '–'} MB | {load.load_s:.0f} s |"
        )
    lines += [
        "",
        "## 40 Telefonfragen (direkt an den Agenten)",
        "",
        f"Beantwortet **{total['answered']}/{total['questions']}** · richtiges Werkzeug "
        f"**{total['tool_ok']}/{total['tool_questions']}** · erste Worte nach {total['median_first_ms']} ms (Median) · "
        f"ganze Antwort {total['median_total_ms']} ms · {total['median_tokens_per_s']} Tokens/s · Guard griff {total['guarded']}×",
        "",
        "| # | Art | Frage | Werkzeuge | ok | erste Worte | gesamt | Tokens/s | Antwort |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for number, a in enumerate(answers, 1):
        ok = "✔" if a.answered and a.tool_ok else "✘"
        text = (a.failure or a.text).replace("|", "/").replace("\n", " ")[:90]
        lines.append(
            f"| {number} | {a.kind} | {a.question} | {', '.join(a.tools) or '–'} | {ok} | "
            f"{a.first_ms if a.first_ms is not None else '–'} | {a.total_ms} | {a.tokens_per_s or '–'} | {text} |"
        )
    return "\n".join(lines) + "\n"


def save_inference(config_file: Path, key: str, value: int) -> None:
    files.update_file(
        config_file,
        lambda text: files.set_value(text, "inference", key, str(value), keep_comment=True),
        default_mode=0o640,
    )


async def main_async(args: argparse.Namespace) -> int:
    config_file = Path(args.config)
    config = ConfigManager(config_file, Path(args.passwords), ROOT)
    config.load()
    settings = config.settings
    if not settings.resolve(settings.inference.model, ROOT).is_file():
        print(f"Modelldatei fehlt: {settings.inference.model} (./test-3.sh setup)", file=sys.stderr)
        return 2
    loads: list[Load] = []
    if args.context and args.context != settings.inference.context_size:
        # the conversation needs room: the system prompt and the tools alone take ≈ 3100 tokens
        save_inference(config_file, "context_size", args.context)
        print(
            f"→ context_size = {args.context} in config/moritz-agent.toml gespeichert", flush=True
        )
        config.load()
        settings = config.settings
    best = settings.inference.moe_cpu_layers
    if args.tune:
        print("Suche --moecpu (mindestens 600 MB VRAM frei) …", flush=True)
        best, loads = await tune(settings)
        if best != settings.inference.moe_cpu_layers:
            save_inference(config_file, "moe_cpu_layers", best)
            print(f"→ moe_cpu_layers = {best} in config/moritz-agent.toml gespeichert", flush=True)
            config.load()
            settings = config.settings
    questions = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        questions = questions[: args.limit]
    service, load = await start(settings, best)
    if service is None:
        print(f"KoboldCpp startet nicht mit --moecpu {best} (Log: data/logs/)", file=sys.stderr)
        return 1
    if not loads:
        loads = [load]
        print(_load_line(load), flush=True)
    print(f"{len(questions)} Fragen an den Agenten …", flush=True)
    try:
        answers = await ask_all(config, service, questions)
    finally:
        await service.stop()
    total = summary(answers)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm-bench.md").write_text(
        markdown(settings, best, loads, answers, total), encoding="utf-8"
    )
    (out / "llm-bench.json").write_text(
        json.dumps(
            {
                "moe_cpu_layers": best,
                "model": settings.inference.model,
                "loads": [asdict(x) | {"vram_free_mb": x.vram_free_mb} for x in loads],
                "summary": total,
                "answers": [asdict(a) for a in answers],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(
        f"Beantwortet {total['answered']}/{total['questions']}, Werkzeug richtig {total['tool_ok']}/{total['tool_questions']}, "
        f"erste Worte {total['median_first_ms']} ms, {total['median_tokens_per_s']} Tokens/s → {out / 'llm-bench.md'}"
    )
    good = total["answered"] >= 0.9 * total["questions"] and (
        not total["tool_questions"] or total["tool_ok"] >= 0.75 * total["tool_questions"]
    )
    return 0 if good else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tune", action="store_true", help="--moecpu suchen und speichern")
    parser.add_argument("--limit", type=int, default=0, help="nur die ersten N Fragen")
    parser.add_argument("--context", type=int, default=0, help="Kontextgröße setzen (z. B. 8192)")
    parser.add_argument("--out", default=str(ROOT / "runtime" / "test-3"))
    parser.add_argument("--config", default=str(ROOT / "config" / "moritz-agent.toml"))
    parser.add_argument("--passwords", default=str(ROOT / "passwords.txt"))
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
