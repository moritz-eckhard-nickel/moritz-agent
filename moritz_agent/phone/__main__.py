# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Command line of the phone part:  python -m moritz_agent.phone <command>

run      start Nikita: register at the PBX and answer calls
check    self-test of every component (config, SIP stack, VAD, Whisper, voices, ports)
speak    synthesize a sentence to a WAV file – to hear Nikita's voice without a call
prompts  render all announcements into the cache (with the main voice, waits for it)
bench    measure speech recognition and voice speed on this machine
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from moritz_agent.config.secrets import PasswordsFileError, load_passwords
from moritz_agent.config.settings import REPO_ROOT, Settings, SettingsError, load_settings
from moritz_agent.logging_setup import setup_logging
from moritz_agent.phone.audio import pcm
from moritz_agent.phone.audio.tts import TtsService

BENCH_SENTENCES = [
    "Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?",
    "Es ist neunzehn Uhr zwölf.",
    "Heute ist Freitag, der sechzehnte Oktober zweitausendsechsundzwanzig.",
    "Laut Tagesschau wird es morgen in Frankfurt regnen, bei etwa zwölf Grad.",
]


def _load(args) -> tuple[Settings, list[str]]:
    settings = load_settings(args.config)
    secrets: list[str] = []
    with contextlib.suppress(
        PasswordsFileError
    ):  # a missing passwords.txt is reported by the commands that need it
        secrets = load_passwords(
            args.passwords or REPO_ROOT / settings.general.passwords_file
        ).secret_values()
    level = "DEBUG" if getattr(args, "verbose", False) else settings.logging.level
    setup_logging(level, None, secrets)
    return settings, secrets


def _tts_for_cli(settings: Settings, args) -> TtsService:
    from moritz_agent.phone.audio.factory import build_tts

    tts_cfg = settings.phone.tts
    engines = getattr(args, "engines", None)
    if engines:
        order = [e.strip() for e in engines.split(",") if e.strip()]
        tts_cfg.engine, tts_cfg.fallback_engines = order[0], order[1:]  # type: ignore[assignment]
    return build_tts(settings, REPO_ROOT)


# -- run -------------------------------------------------------------------------------------
def cmd_run(args) -> int:
    from moritz_agent.phone.worker import PhoneWorker, WorkerOptions

    _load(args)
    options = WorkerOptions(
        config=args.config,
        passwords=args.passwords,
        stt=args.stt,
        register=not args.no_register,
        allow=args.allow,
        tts_engines=[e.strip() for e in args.engines.split(",")] if args.engines else None,
        force_start=args.force,
        sip_port=args.sip_port,
    )
    try:
        worker = PhoneWorker(options)
    except (SettingsError, PasswordsFileError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    setup_logging(
        "DEBUG" if args.verbose else worker.settings.logging.level,
        REPO_ROOT / worker.settings.logging.file,
        worker.passwords.secret_values(),
        worker.settings.logging.max_bytes,
        worker.settings.logging.backup_count,
    )
    return asyncio.run(worker.run())


# -- speak -----------------------------------------------------------------------------------
def cmd_speak(args) -> int:
    settings, _ = _load(args)
    tts = _tts_for_cli(settings, args)
    name = args.engine or settings.phone.tts.engine
    try:
        engine = tts.engines.get(name)
        if engine is None or not engine.available():
            print(f"Stimme '{name}' ist nicht bereit.", file=sys.stderr)
            reason = getattr(engine, "_error", "") if engine is not None else "nicht konfiguriert"
            if reason:
                print(f"  Grund: {reason}", file=sys.stderr)
            return 1
        started = time.monotonic()
        data = tts.render_blocking(args.text, engine_name=name)
        took = time.monotonic() - started
        out = Path(args.out)
        pcm.write_wav(out, data)
        audio = pcm.duration_s(data)
        print(
            f"{out}: {audio:.1f} s Audio in {took:.1f} s erzeugt (Faktor {took / max(audio, 0.01):.2f}) mit {name}"
        )
        if args.play:
            player = shutil.which("aplay") or shutil.which("play") or shutil.which("ffplay")
            if player:
                subprocess.run([player, str(out)], check=False)
            else:
                print("  (kein Abspielprogramm gefunden – Datei manuell abspielen)")
        return 0
    finally:
        tts.close()


# -- prompts ---------------------------------------------------------------------------------
def cmd_prompts(args) -> int:
    from moritz_agent.phone.audio.announcements import (
        AnnouncementStore,
        load_catalog,
        quarter_hour_phrases,
    )
    from moritz_agent.phone.worker import PROMPT_CATALOG

    settings, _ = _load(args)
    tts = _tts_for_cli(settings, args)
    try:
        main = tts.best_available() or ""
        if not main:
            print("Keine Stimme verfügbar.", file=sys.stderr)
            return 1
        if main != settings.phone.tts.engine:
            print(
                f"Hauptstimme '{settings.phone.tts.engine}' ist nicht bereit – Ansagen werden mit '{main}' erzeugt.",
                file=sys.stderr,
            )
        catalog = load_catalog(
            REPO_ROOT / PROMPT_CATALOG,
            {
                "greeting_text": settings.phone.greeting_text,
                "assistant_name": settings.phone.assistant_name,
            },
        )
        for prompt in catalog.values():
            started = time.monotonic()
            cached = tts.cached(prompt.text, main) is not None
            data = tts.render_blocking(prompt.text, engine_name=main, persist=True)
            note = "im Cache" if cached else f"neu erzeugt in {time.monotonic() - started:.1f} s"
            print(f"  {prompt.id:22s} {pcm.duration_s(data):4.1f} s  {note}")
        if args.warm_times:
            phrases = quarter_hour_phrases()
            print(f"Uhrzeiten vorrendern ({len(phrases)} Sätze) …")
            for index, phrase in enumerate(phrases, 1):
                tts.render_blocking(phrase, engine_name=main, persist=True)
                if index % 8 == 0:
                    print(f"  {index}/{len(phrases)}", flush=True)
        status = AnnouncementStore(tts, catalog)
        status.ensure()
        print("Ansagen:", status.status())
        return 0
    finally:
        tts.close()


# -- bench -----------------------------------------------------------------------------------
def cmd_bench(args) -> int:
    settings, _ = _load(args)
    tts = _tts_for_cli(settings, args)
    code = 0
    try:
        names = (
            [n.strip() for n in args.engine.split(",")]
            if args.engine
            else [settings.phone.tts.engine, *settings.phone.tts.fallback_engines]
        )
        print("Sprachausgabe (Faktor = Rechenzeit / Audiolänge; < 1 = schneller als Echtzeit):")
        for name in dict.fromkeys(names):
            engine = tts.engines.get(name)
            if engine is None or not engine.available():
                print(f"  {name:10s} nicht verfügbar")
                continue
            total_work = total_audio = 0.0
            first = None
            for sentence in BENCH_SENTENCES:
                started = time.monotonic()
                data = tts.render_blocking(sentence, engine_name=name)
                work = time.monotonic() - started
                audio = pcm.duration_s(data)
                first = first if first is not None else work
                total_work, total_audio = total_work + work, total_audio + audio
                print(
                    f"  {name:10s} {audio:5.1f} s Audio in {work:6.1f} s  Faktor {work / max(audio, 0.01):5.2f}  | {sentence[:48]}"
                )
            rtf = total_work / max(total_audio, 0.01)
            verdict = (
                "schneller als Echtzeit – gut fürs Telefon"
                if rtf < 0.7
                else "knapp/zu langsam – phone.tts.cpu_threads erhöhen oder kleinere Stimme wählen"
            )
            print(
                f"  {name:10s} Durchschnitt Faktor {rtf:.2f}, erster Satz nach {first:.1f} s ({verdict})"
            )
        print()
        code |= _bench_stt(settings, args)
    finally:
        tts.close()
    return code


def _speech_sample(text: str) -> bytes | None:
    espeak = shutil.which("espeak-ng")
    if espeak is None:
        return None
    wav = subprocess.run(
        [espeak, "-v", "de", "-s", "150", "--stdout", text], capture_output=True, check=True
    ).stdout
    import io
    import wave

    import numpy as np

    with wave.open(io.BytesIO(wav), "rb") as handle:
        rate, raw = handle.getframerate(), handle.readframes(handle.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return pcm.float_to_pcm16(pcm.resample(samples, rate, pcm.SAMPLE_RATE)).tobytes()


def _bench_stt(settings: Settings, args) -> int:
    from moritz_agent.phone.audio.factory import build_stt

    print("Spracherkennung (Whisper small, CPU):")
    try:
        started = time.monotonic()
        stt = build_stt(settings, REPO_ROOT)
        print(f"  Modell geladen in {time.monotonic() - started:.1f} s")
    except Exception as exc:
        print(f"  nicht verfügbar: {exc}")
        return 1
    for text in (
        "Wie viel Uhr haben wir?",
        "Hallo Nikita, wie wird das Wetter morgen in Frankfurt?",
    ):
        sample = _speech_sample(text)
        if sample is None:
            print("  (espeak-ng fehlt – kein Testsatz; apt install espeak-ng)")
            break
        result = stt.transcribe(sample)
        print(f"  {result.audio_s:4.1f} s Audio in {result.elapsed_s:4.2f} s  → {result.text!r}")
    return 0


# -- check -----------------------------------------------------------------------------------
class _Report:
    def __init__(self) -> None:
        self.failed = 0

    def ok(self, name: str, detail: str = "") -> None:
        print(f"  ✓ {name:28s} {detail}")

    def warn(self, name: str, detail: str) -> None:
        print(f"  ! {name:28s} {detail}")

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        print(f"  ✗ {name:28s} {detail}")


def cmd_check(args) -> int:
    report = _Report()
    print("moritz-agent: Telefon-Selbsttest")
    try:
        settings, _ = _load(args)
        report.ok(
            "Einstellungen",
            f"{'config/moritz-agent.toml' if (REPO_ROOT / 'config/moritz-agent.toml').is_file() else 'Beispieldatei'}",
        )
    except SettingsError as exc:
        report.fail("Einstellungen", str(exc))
        return 1
    try:
        passwords = load_passwords(args.passwords or REPO_ROOT / settings.general.passwords_file)
        sip = passwords.sip
        report.ok(
            "passwords.txt",
            f"SIP {sip.username}@{sip.registrar}:{sip.port}/{sip.transport}, Nebenstelle {sip.extension}",
        )
        if sip.password.reveal() == "agent":
            report.warn(
                "SIP-Passwort",
                "Startwert 'agent' – in Asterisk und passwords.txt ändern (empfohlen)",
            )
    except PasswordsFileError as exc:
        report.fail("passwords.txt", str(exc))
        passwords = None

    try:
        import pjsua2

        endpoint = pjsua2.Endpoint()
        endpoint.libCreate()
        version = endpoint.libVersion().full
        endpoint.libDestroy()
        report.ok("SIP-Stack (PJSIP)", version)
    except Exception as exc:
        report.fail(
            "SIP-Stack (PJSIP)",
            f"{type(exc).__name__}: {exc} – scripts/build-pjsip.sh (./test-1.sh setup)",
        )

    try:
        from moritz_agent.phone.audio.factory import build_vad

        vad = build_vad(settings, REPO_ROOT)
        sample = _speech_sample("Hallo, wie geht es dir?")
        if sample is None:
            report.ok("Sprachende-Erkennung", "Modell geladen (kein Test: espeak-ng fehlt)")
        else:
            seg = vad.new_segmenter(**{"min_silence_ms": 300})
            events = []
            for frame in pcm.chunk_frames(bytes(16000) + sample + bytes(16000)):
                events += seg.feed(frame)
            ended = [e for e in events if type(e).__name__ == "UtteranceEnd"]
            (report.ok if ended else report.fail)(
                "Sprachende-Erkennung", f"{len(ended)} Äußerung erkannt"
            )
    except Exception as exc:
        report.fail("Sprachende-Erkennung", f"{type(exc).__name__}: {exc}")

    from moritz_agent.phone.audio import models

    absent = models.missing(["stt"])
    if absent:
        report.fail(
            "Spracherkennung (Whisper)",
            "Modell fehlt – python -m moritz_agent.phone.audio.models fetch (./test-1.sh models fetch)",
        )
    else:
        try:
            from moritz_agent.phone.audio.factory import build_stt

            started = time.monotonic()
            stt = build_stt(settings, REPO_ROOT)
            loaded = time.monotonic() - started
            sample = _speech_sample("Wie viel Uhr haben wir?")
            if sample is None:
                report.ok("Spracherkennung (Whisper)", f"geladen in {loaded:.1f} s")
            else:
                result = stt.transcribe(sample)
                good = "uhr" in result.text.lower()
                (report.ok if good else report.warn)(
                    "Spracherkennung (Whisper)",
                    f"geladen in {loaded:.1f} s, Testsatz in {result.elapsed_s:.1f} s → {result.text!r}",
                )
        except Exception as exc:
            report.fail("Spracherkennung (Whisper)", f"{type(exc).__name__}: {exc}")

    tts = _tts_for_cli(settings, args)
    try:
        main = settings.phone.tts.engine
        for name in dict.fromkeys([main, *settings.phone.tts.fallback_engines]):
            engine = tts.engines.get(name)
            if engine is None or not engine.available():
                detail = getattr(engine, "_error", "") or "nicht bereit"
                (report.fail if name == main and not args.fallback_ok else report.warn)(
                    f"Stimme {name}", detail
                )
                continue
            started = time.monotonic()
            data = tts.render_blocking("Hallo Moritz, hier ist Nikita.", engine_name=name)
            work, audio = time.monotonic() - started, pcm.duration_s(data)
            report.ok(
                f"Stimme {name}",
                f"{audio:.1f} s Audio in {work:.1f} s (Faktor {work / max(audio, 0.01):.2f})",
            )
        from moritz_agent.phone.audio.announcements import AnnouncementStore, load_catalog
        from moritz_agent.phone.worker import PROMPT_CATALOG

        catalog = load_catalog(
            REPO_ROOT / PROMPT_CATALOG,
            {
                "greeting_text": settings.phone.greeting_text,
                "assistant_name": settings.phone.assistant_name,
            },
        )
        store = AnnouncementStore(tts, catalog)
        missing = store.ensure()
        info = store.status()
        if missing:
            report.fail("Ansagen", f"fehlen: {', '.join(missing)}")
        else:
            report.ok("Ansagen", f"{info['loaded']} bereit (Stimme: {info['voice']})")
    finally:
        tts.close()

    phone = settings.phone
    for label, kind, port in (
        ("SIP-Port", socket.SOCK_DGRAM, phone.local_sip_port),
        ("RTP-Port", socket.SOCK_DGRAM, phone.rtp_port_start),
    ):
        try:
            with socket.socket(socket.AF_INET, kind) as probe:
                probe.bind(("0.0.0.0", port))
            report.ok(f"{label} {port}/udp", "frei")
        except OSError as exc:
            report.fail(f"{label} {port}/udp", f"belegt oder gesperrt: {exc}")

    if args.sip and passwords is not None:
        report.failed += _check_registration(settings, passwords, args.sip_wait)

    print()
    print(
        "Alles in Ordnung." if report.failed == 0 else f"{report.failed} Problem(e) – siehe ✗ oben."
    )
    return 1 if report.failed else 0


def _check_registration(settings: Settings, passwords, wait: float) -> int:
    from moritz_agent.phone.sip import SipPhone

    async def attempt() -> int:
        loop = asyncio.get_running_loop()
        phone = SipPhone(
            passwords.sip,
            settings.phone,
            loop,
            lambda media, remote: None,
            settings.logging.pjsip_log_level,
        )  # type: ignore[arg-type]
        try:
            await asyncio.to_thread(phone.start)
            registered = await asyncio.to_thread(phone.wait_registered, wait)
            status = phone.status()
            if registered:
                print(
                    f"  ✓ {'SIP-Registrierung':28s} registriert bei {passwords.sip.registrar} ({status['code']} {status['reason']})"
                )
                return 0
            print(
                f"  ✗ {'SIP-Registrierung':28s} {status['registration']} {status['code']} {status['reason']} – docs/asterisk-konfiguration.md"
            )
            return 1
        except Exception as exc:
            print(f"  ✗ {'SIP-Registrierung':28s} {exc}")
            return 1
        finally:
            await asyncio.to_thread(phone.stop)

    return asyncio.run(attempt())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m moritz_agent.phone",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, help="Pfad zu moritz-agent.toml")
    parser.add_argument("--passwords", type=Path, help="Pfad zu passwords.txt")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-Ausgaben")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Nikita starten")
    run.add_argument(
        "--stt",
        default="whisper",
        help='"whisper" oder fake:"Text eins|Text zwei" (Testmodus ohne Spracherkennung)',
    )
    run.add_argument(
        "--no-register",
        action="store_true",
        help="nicht registrieren, Anrufe direkt annehmen (Test ohne Telefonanlage)",
    )
    run.add_argument(
        "--allow",
        action="append",
        metavar="IP",
        help="erlaubte Absenderadresse(n) statt phone.allowed_source_ips",
    )
    run.add_argument(
        "--engines", help="Stimmen in dieser Reihenfolge, z. B. espeak oder piper,espeak"
    )
    run.add_argument("--sip-port", type=int, help="lokaler SIP-Port statt phone.local_sip_port")
    run.add_argument(
        "--force", action="store_true", help="auch ohne vollständige Ansagen starten (nur Test)"
    )
    run.set_defaults(func=cmd_run)

    check = sub.add_parser("check", help="Selbsttest")
    check.add_argument(
        "--sip", action="store_true", help="auch die Registrierung an der Telefonanlage prüfen"
    )
    check.add_argument("--sip-wait", type=float, default=15.0)
    check.add_argument(
        "--fallback-ok", action="store_true", help="fehlende Hauptstimme nur als Warnung werten"
    )
    check.add_argument("--engines", help="Stimmen überschreiben, z. B. espeak")
    check.set_defaults(func=cmd_check)

    speak = sub.add_parser("speak", help="Satz in WAV-Datei sprechen")
    speak.add_argument("text")
    speak.add_argument("--out", default="nikita.wav")
    speak.add_argument("--engine", help="piper oder espeak (Standard: Hauptstimme)")
    speak.add_argument("--play", action="store_true")
    speak.add_argument("--engines", help=argparse.SUPPRESS)
    speak.set_defaults(func=cmd_speak)

    prompts = sub.add_parser("prompts", help="Ansagen vorrendern")
    prompts.add_argument(
        "--warm-times",
        action="store_true",
        help="auch alle Viertelstunden-Uhrzeiten vorrendern (dauert lange)",
    )
    prompts.add_argument("--engines", help=argparse.SUPPRESS)
    prompts.set_defaults(func=cmd_prompts)

    bench = sub.add_parser("bench", help="Geschwindigkeit messen")
    bench.add_argument("--engine", help="Komma-getrennt, Standard: alle konfigurierten")
    bench.add_argument("--engines", help=argparse.SUPPRESS)
    bench.set_defaults(func=cmd_bench)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except (SettingsError, PasswordsFileError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
