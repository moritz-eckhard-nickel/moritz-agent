# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import pytest

from moritz_agent.phone.audio import pcm
from moritz_agent.phone.audio.announcements import AnnouncementStore, Prompt, load_catalog
from moritz_agent.phone.audio.tts import TtsCancelled, TtsService, TtsUnavailable

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
    original = collect(tts, "Hallo Moritz.", persist=True)
    assert len(first.calls) == 1
    assert list((tmp_path / "cache" / "fake").glob("*.wav"))
    again = FakeEngine()
    tts2 = service(tmp_path, again)
    assert collect(tts2, "Hallo Moritz.", persist=True) == original
    assert again.calls == []
    assert tts2.cached("Hallo Moritz.", "fake") == b"".join(original)


def test_live_answers_are_not_written_to_disk(tmp_path):
    tts = service(tmp_path, FakeEngine())
    collect(tts, "Das ist eine geheime Antwort.")
    assert not (tmp_path / "cache").exists() or not list((tmp_path / "cache").rglob("*.wav"))


def test_cache_key_depends_on_voice(tmp_path):
    a, b = FakeEngine(voice_id="eins"), FakeEngine(voice_id="zwei")
    collect(service(tmp_path, a), "Hallo.", persist=True)
    collect(service(tmp_path, b), "Hallo.", persist=True)
    assert len(b.calls) == 1  # new voice id → no stale cache hit


def test_speech_always_uses_the_best_available_voice(tmp_path):
    main, fast = FakeEngine("piper"), FakeEngine("espeak")
    tts = service(tmp_path, main, fast)
    collect(tts, "Hallo.", persist=True)
    assert main.calls and not fast.calls
    main.ready = False  # model vanished → emergency voice
    collect(tts, "Noch ein Satz.")
    assert fast.calls


def test_falls_back_when_chosen_voice_fails_midway(tmp_path):
    main, fast = FakeEngine("piper"), FakeEngine("espeak")
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


# -- announcements ---------------------------------------------------------------------------
def catalog() -> dict[str, Prompt]:
    return {
        "greeting": Prompt("greeting", "Hallo Moritz.", True),
        "bye": Prompt("bye", "Tschüss.", True),
        "opt": Prompt("opt", "Optional.", False),
    }


def test_announcements_follow_the_voice_that_is_ready(tmp_path):
    main, fast = FakeEngine("piper", ready=False), FakeEngine("espeak")
    store = AnnouncementStore(service(tmp_path, main, fast), catalog())
    assert store.missing_required() == ["greeting", "bye"]
    assert store.ensure() == []
    assert store.voice() == "espeak"  # Piper model missing → emergency voice
    # the real voice appears (model installed, service restarted): everything is rendered again with it
    main.ready = True
    store2 = AnnouncementStore(service(tmp_path, main, fast), catalog())
    assert store2.ensure() == []
    assert store2.voice() == "piper"
    assert main.calls  # not served from the espeak recordings


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
