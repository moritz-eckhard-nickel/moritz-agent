# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path

import pytest

from moritz_agent.config.settings import CosyVoiceSettings
from moritz_agent.phone.audio import pcm
from moritz_agent.phone.audio.announcements import AnnouncementStore, Prompt, load_catalog
from moritz_agent.phone.audio.tts import TtsCancelled, TtsError, TtsService, TtsUnavailable
from moritz_agent.phone.audio.tts_cosyvoice import MODEL_FILES, CosyVoiceEngine

from .fakes import FakeEngine

REPO_ROOT = Path(__file__).resolve().parents[2]


def service(tmp_path, *engines: FakeEngine, **kwargs) -> TtsService:
    by_name = {e.name: e for e in engines}
    names = list(by_name)
    return TtsService(by_name, names[0], names[1:], tmp_path / "cache", **kwargs)


def collect(tts: TtsService, text: str, **kwargs) -> list[bytes]:
    async def run():
        return [chunk async for chunk in tts.stream(text, **kwargs)]

    return asyncio.run(run())


def test_stream_yields_one_chunk_per_sentence_with_german_words(tmp_path):
    engine = FakeEngine()
    chunks = collect(service(tmp_path, engine), "Es ist 19 Uhr 12. Draußen sind 21 °C!")
    assert len(chunks) == 2
    assert all(len(c) % 2 == 0 and len(c) > 0 for c in chunks)
    assert not any(re.search(r"\d", text) for text in engine.calls)
    assert "neunzehn Uhr zwölf" in engine.calls[0]


def test_output_is_normalized_16khz_pcm(tmp_path):
    chunk = collect(service(tmp_path, FakeEngine()), "Hallo Moritz.")[0]
    samples = pcm.pcm16_to_float(chunk)
    assert -22 < pcm.rms_dbfs(samples) < -18
    assert float(abs(samples).max()) <= 10 ** (-1.5 / 20) + 1e-3


def test_persist_writes_cache_and_second_run_skips_engine(tmp_path):
    first = FakeEngine()
    tts = service(tmp_path, first)
    original = collect(tts, "Hallo Moritz.", live=False, persist=True)
    assert len(first.calls) == 1
    assert list((tmp_path / "cache" / "fake").glob("*.wav"))
    again = FakeEngine()
    tts2 = service(tmp_path, again)
    assert collect(tts2, "Hallo Moritz.", live=False, persist=True) == original
    assert again.calls == []
    assert tts2.cached("Hallo Moritz.", "fake") == b"".join(original)


def test_live_answers_are_not_written_to_disk(tmp_path):
    tts = service(tmp_path, FakeEngine())
    collect(tts, "Das ist eine geheime Antwort.", live=True)
    assert not (tmp_path / "cache").exists() or not list((tmp_path / "cache").rglob("*.wav"))


def test_cache_key_depends_on_voice(tmp_path):
    a, b = FakeEngine(voice_id="eins"), FakeEngine(voice_id="zwei")
    collect(service(tmp_path, a), "Hallo.", persist=True)
    collect(service(tmp_path, b), "Hallo.", persist=True)
    assert len(b.calls) == 1  # new voice id → no stale cache hit


def test_live_uses_fallback_when_main_voice_is_too_slow(tmp_path):
    main, fast = FakeEngine("cosyvoice"), FakeEngine("piper")
    tts = service(tmp_path, main, fast, live_budget_s=3.0)
    text = "Das ist ein ziemlich langer Beispielsatz für die Schätzung."
    assert tts.pick_live(text) == "cosyvoice"  # speed unknown → trust the main voice
    tts.stats["cosyvoice"].update(synth_s=30.0, audio_s=3.0)  # RTF 10
    assert tts.pick_live(text) == "piper"
    tts.stats["cosyvoice"].rtf = 0.5
    assert tts.pick_live(text) == "cosyvoice"
    tts.live_policy = "primary"
    tts.stats["cosyvoice"].rtf = 50.0
    assert tts.pick_live(text) == "cosyvoice"


def test_announcements_use_best_available_voice_not_the_live_rule(tmp_path):
    main, fast = FakeEngine("cosyvoice"), FakeEngine("piper")
    tts = service(tmp_path, main, fast)
    tts.stats["cosyvoice"].rtf = 99.0
    collect(tts, "Hallo.", live=False, persist=True)
    assert main.calls and not fast.calls


def test_falls_back_when_chosen_voice_fails_midway(tmp_path):
    main, fast = FakeEngine("cosyvoice"), FakeEngine("piper")
    main.fail_on = "Zwei"
    chunks = collect(service(tmp_path, main, fast), "Eins ist gut. Zwei ist schlecht.")
    assert len(chunks) == 2 and len(fast.calls) == 1


def test_unavailable_when_no_voice_is_ready(tmp_path):
    tts = service(tmp_path, FakeEngine(ready=False))
    with pytest.raises(TtsUnavailable):
        collect(tts, "Hallo.")


def test_cancel_stops_a_running_live_synthesis(tmp_path):
    engine = FakeEngine(delay=5.0)
    tts = service(tmp_path, engine)

    async def run():
        task = asyncio.create_task(_drain(tts))
        await asyncio.sleep(0.2)
        tts.cancel()
        return await asyncio.wait_for(task, 3)

    async def _drain(t):
        return [c async for c in t.stream("Dieser Satz dauert lange.")]

    with pytest.raises(TtsCancelled):
        asyncio.run(run())


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng not installed")
def test_espeak_engine_speaks_german(tmp_path):
    from moritz_agent.config.settings import EspeakSettings
    from moritz_agent.phone.audio.tts_espeak import EspeakEngine

    engine = EspeakEngine(EspeakSettings())
    assert engine.available()
    chunk = b"".join(collect(service_with(tmp_path, engine), "Wie viel Uhr haben wir?"))
    assert pcm.duration_s(chunk) > 0.8


def service_with(tmp_path, engine) -> TtsService:
    return TtsService({engine.name: engine}, engine.name, [], tmp_path / "cache")


# -- CosyVoice process management against the fake worker ------------------------------------
def fake_cosy(tmp_path, delay: float = 0.0, die: bool = False, monkeypatch=None) -> CosyVoiceEngine:
    model_dir = tmp_path / "model"
    (model_dir / "CosyVoice-BlankEN").mkdir(parents=True)
    for name in MODEL_FILES:
        (model_dir / name).write_bytes(b"x")
    (model_dir / "CosyVoice-BlankEN" / "model.safetensors").write_bytes(b"x")
    settings = CosyVoiceSettings(
        python=sys.executable, model_dir=str(model_dir), startup_timeout_s=30, request_timeout_s=20
    )
    engine = CosyVoiceEngine(settings, REPO_ROOT, threads=2)
    engine.worker_script = Path(__file__).with_name("fake_cosyvoice_worker.py")
    if delay:
        monkeypatch.setenv("FAKE_TTS_DELAY", str(delay))
    if die:
        monkeypatch.setenv("FAKE_TTS_DIE_AT_START", "1")
    return engine


def test_cosyvoice_engine_starts_serves_and_stops(tmp_path):
    engine = fake_cosy(tmp_path)
    try:
        assert not engine.available()
        engine.start()
        assert engine.wait_ready(30)
        samples, rate = engine.synthesize("Hallo Moritz")
        assert rate == 24000 and samples.size > 2000
        assert engine.voice_id.startswith("thorsten-hessisch/")
    finally:
        engine.close()
    assert not engine.available()


def test_cosyvoice_engine_reports_worker_errors(tmp_path):
    engine = fake_cosy(tmp_path)
    try:
        engine.start()
        assert engine.wait_ready(30)
        with pytest.raises(TtsError, match="boom"):
            engine.synthesize("FEHLER bitte")
    finally:
        engine.close()


def test_cosyvoice_cancel_aborts_request(tmp_path, monkeypatch):
    engine = fake_cosy(tmp_path, delay=5.0, monkeypatch=monkeypatch)
    try:
        engine.start()
        assert engine.wait_ready(30)
        import threading

        threading.Timer(0.3, engine.cancel).start()
        with pytest.raises(TtsCancelled):
            engine.synthesize("Hallo")
    finally:
        engine.close()


def test_cosyvoice_not_available_without_model_files(tmp_path):
    settings = CosyVoiceSettings(python=sys.executable, model_dir=str(tmp_path / "leer"))
    engine = CosyVoiceEngine(settings, REPO_ROOT, threads=2)
    engine.start()
    assert engine.state == "failed" and "Modelldateien fehlen" in engine.last_error
    assert not engine.available()
    with pytest.raises(TtsUnavailable):
        engine.synthesize("Hallo")


def test_cosyvoice_failed_startup_is_reported(tmp_path, monkeypatch):
    engine = fake_cosy(tmp_path, die=True, monkeypatch=monkeypatch)
    try:
        engine.start()
        assert not engine.wait_ready(5)
        assert "kaputt" in engine.last_error or engine.state in ("failed", "starting")
    finally:
        engine.close()


# -- announcements ---------------------------------------------------------------------------
def catalog() -> dict[str, Prompt]:
    return {
        "greeting": Prompt("greeting", "Hallo Moritz.", True),
        "bye": Prompt("bye", "Tschüss.", True),
        "opt": Prompt("opt", "Optional.", False),
    }


def test_announcements_render_provisionally_then_upgrade(tmp_path):
    main, fast = FakeEngine("cosyvoice", ready=False), FakeEngine("piper")
    tts = service(tmp_path, main, fast)
    store = AnnouncementStore(tts, catalog())
    assert store.missing_required() == ["greeting", "bye"]
    assert store.ensure() == []
    assert sorted(store.provisional()) == ["bye", "greeting", "opt"]
    assert store.upgrade_once() is False  # main voice not ready yet
    main.ready = True
    assert store.upgrade_once(idle=lambda: False) is False  # a call is running: leave the CPU alone
    while store.upgrade_once():
        pass
    assert store.provisional() == []
    assert tts.cached("Hallo Moritz.", "cosyvoice")


def test_announcements_reuse_disk_cache_after_restart(tmp_path):
    first = FakeEngine()
    AnnouncementStore(service(tmp_path, first), catalog()).ensure()
    second = FakeEngine()
    store = AnnouncementStore(service(tmp_path, second), catalog())
    assert store.ensure() == []
    assert second.calls == []


def test_announcements_missing_without_any_voice(tmp_path):
    store = AnnouncementStore(service(tmp_path, FakeEngine(ready=False)), catalog())
    assert store.ensure() == ["greeting", "bye"]


def test_shipped_catalog_formats_with_assistant_values():
    cat = load_catalog(
        REPO_ROOT / "assets/audio/prompts.de.toml",
        {
            "greeting_text": "Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?",
            "assistant_name": "Nikita",
        },
    )
    assert cat["greeting"].text.startswith("Hallo Moritz, hier ist Nikita")
    assert cat["greeting"].required
