#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A scripted caller for testing Nikita without a real phone (ticket P1-11).

It places a SIP call, listens to the agent, speaks the given sentences (synthesized with
espeak-ng or taken from WAV files) whenever the agent has finished talking, measures how long
the agent needs to answer and records everything the agent said into a WAV file.

Direct call (no PBX):   scripts/sip_testcall.py --to sip:agent@127.0.0.1:5060 --say "Wie viel Uhr haben wir?"
Through the PBX:        scripts/sip_testcall.py --to sip:999@192.168.1.176 --registrar 192.168.1.176 \
                            --user 20 --password '…' --say "Wie viel Uhr haben wir?"
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

from moritz_agent.phone.audio import pcm as pcmtools

VOICE_RMS = 400  # int16 RMS that counts as "someone is talking"


def synthesize(text: str) -> bytes:
    espeak = shutil.which("espeak-ng")
    if espeak is None:
        raise SystemExit("espeak-ng fehlt (apt install espeak-ng) – oder --wav verwenden")
    wav = subprocess.run(
        [espeak, "-v", "de", "-s", "145", "--stdout", text], capture_output=True, check=True
    ).stdout
    tmp = Path("/tmp") / f"sip_testcall_{abs(hash(text))}.wav"
    tmp.write_bytes(wav)
    samples, rate = pcmtools.read_wav(tmp)
    tmp.unlink(missing_ok=True)
    samples = pcmtools.resample(samples, rate, pcmtools.SAMPLE_RATE)
    samples = pcmtools.normalize_loudness(
        pcmtools.trim_silence(samples, pcmtools.SAMPLE_RATE), -18.0
    )
    return pcmtools.float_to_pcm16(samples).tobytes()


def load_wav(path: str) -> bytes:
    samples, rate = pcmtools.read_wav(Path(path))
    return pcmtools.float_to_pcm16(pcmtools.resample(samples, rate, pcmtools.SAMPLE_RATE)).tobytes()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--to", required=True, help="SIP-URI des Agents, z. B. sip:agent@127.0.0.1:5060"
    )
    parser.add_argument(
        "--say", action="append", default=[], help="Satz, der gesprochen wird (mehrfach möglich)"
    )
    parser.add_argument(
        "--wav", action="append", default=[], help="WAV-Datei statt Text (mehrfach möglich)"
    )
    parser.add_argument("--out", default="anruf.wav", help="Aufnahme dessen, was der Agent sagt")
    parser.add_argument("--local-port", type=int, default=5070)
    parser.add_argument(
        "--registrar", help="an dieser Telefonanlage registrieren (sonst Direktanruf)"
    )
    parser.add_argument("--user", default="caller")
    parser.add_argument("--password", default="")
    parser.add_argument(
        "--timeout", type=float, default=90.0, help="Gesamtdauer des Tests in Sekunden"
    )
    parser.add_argument(
        "--end-after",
        type=float,
        default=2.5,
        help="Sekunden Stille nach der letzten Antwort bis zum Auflegen",
    )
    parser.add_argument(
        "--hangup-after-greeting", action="store_true", help="direkt nach der Begrüßung auflegen"
    )
    args = parser.parse_args()

    import pjsua2 as pj

    utterances = [synthesize(text) for text in args.say] + [load_wav(path) for path in args.wav]

    lock = threading.Lock()
    rx = bytearray()
    tx = bytearray()
    voice = {"last": 0.0, "first_after_speech": None}

    class Port(pj.AudioMediaPort):
        def onFrameRequested(self, frame):
            size = frame.size or 640
            with lock:
                chunk = bytes(tx[:size])
                del tx[:size]
            chunk += bytes(size - len(chunk))
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
            frame.buf = pj.ByteVector(list(chunk))
            frame.size = len(chunk)

        def onFrameReceived(self, frame):
            data = bytes(frame.buf)
            samples = np.frombuffer(data, dtype="<i2")
            if (
                samples.size
                and float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) > VOICE_RMS
            ):
                now = time.monotonic()
                with lock:
                    voice["last"] = now
                    if voice["first_after_speech"] is None:
                        voice["first_after_speech"] = now
            with lock:
                rx.extend(data)

    state = {"connected": False, "disconnected": False, "code": 0}

    class Call(pj.Call):
        def onCallState(self, prm):
            info = self.getInfo()
            if info.state == pj.PJSIP_INV_STATE_CONFIRMED:
                state["connected"] = True
            if info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                state["disconnected"], state["code"] = True, info.lastStatusCode

        def onCallMediaState(self, prm):
            info = self.getInfo()
            for index, media in enumerate(info.media):
                if (
                    media.type == pj.PJMEDIA_TYPE_AUDIO
                    and media.status == pj.PJSUA_CALL_MEDIA_ACTIVE
                ):
                    audio = self.getAudioMedia(index)
                    audio.startTransmit(caller_port[0])
                    caller_port[0].startTransmit(audio)
                    holder.append(audio)

    holder: list = []
    caller_port: list = []  # filled once the port exists; Call.onCallMediaState needs it
    endpoint = pj.Endpoint()
    endpoint.libCreate()
    cfg = pj.EpConfig()
    cfg.uaConfig.threadCnt = 0
    cfg.uaConfig.mainThreadOnly = True
    cfg.logConfig.level = 2
    cfg.logConfig.consoleLevel = 2
    cfg.medConfig.clockRate = 16000
    cfg.medConfig.sndClockRate = 16000
    cfg.medConfig.channelCount = 1
    cfg.medConfig.ecTailLen = 0
    cfg.medConfig.noVad = True
    endpoint.libInit(cfg)
    transport = pj.TransportConfig()
    transport.port = args.local_port
    endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, transport)
    endpoint.libStart()
    endpoint.audDevManager().setNullDev()
    for info in endpoint.codecEnum2():
        wanted = info.codecId.lower().startswith(("g722", "pcma", "pcmu"))
        endpoint.codecSetPriority(
            info.codecId, 200 if info.codecId.lower().startswith("g722") else (100 if wanted else 0)
        )

    fmt = pj.MediaFormatAudio()
    fmt.init(pj.PJMEDIA_FORMAT_PCM, 16000, 1, 20000, 16)
    port = Port()
    port.createPort("caller", fmt)
    caller_port.append(port)

    acc_cfg = pj.AccountConfig()
    if args.registrar:
        acc_cfg.idUri = f"sip:{args.user}@{args.registrar}"
        acc_cfg.regConfig.registrarUri = f"sip:{args.registrar}"
        acc_cfg.sipConfig.authCreds.append(
            pj.AuthCredInfo("digest", "*", args.user, 0, args.password)
        )
    else:
        acc_cfg.idUri = f"sip:{args.user}@127.0.0.1"
        acc_cfg.regConfig.registerOnAdd = False
    account = pj.Account()
    account.create(acc_cfg)
    if args.registrar:
        end = time.monotonic() + 10
        while time.monotonic() < end and not account.getInfo().regIsActive:
            endpoint.libHandleEvents(50)
        if not account.getInfo().regIsActive:
            print("FEHLER: Registrierung an der Telefonanlage fehlgeschlagen", file=sys.stderr)
            return 2
        print(f"registriert als {args.user}@{args.registrar}")

    call = Call(account)
    started = time.monotonic()
    call.makeCall(args.to, pj.CallOpParam(True))
    print(f"rufe {args.to} an …")

    turn = 0
    phase = "listen"  # listen | speaking
    heard_in_phase = False
    t_speech_end = 0.0
    latencies: list[float] = []
    greeted_at = None
    result = 1
    while time.monotonic() - started < args.timeout and not state["disconnected"]:
        endpoint.libHandleEvents(20)
        now = time.monotonic()
        with lock:
            last_voice = voice["last"]
            first_voice = voice["first_after_speech"]
            pending_tx = len(tx)
        if phase == "listen":
            if not heard_in_phase and first_voice is not None:
                heard_in_phase = True
                if turn > 0:
                    latencies.append(first_voice - t_speech_end)
                    print(
                        f"  Antwort {turn}: erster Ton {first_voice - t_speech_end:.2f} s nach dem Ende meines Satzes"
                    )
                else:
                    greeted_at = now - started
                    print(f"  Begrüßung nach {greeted_at:.2f} s")
            if heard_in_phase and now - last_voice > 1.0:
                if args.hangup_after_greeting and turn == 0:
                    break
                if turn < len(utterances):
                    with lock:
                        tx.extend(utterances[turn])
                        voice["first_after_speech"] = None
                    print(f"  spreche Satz {turn + 1} ({len(utterances[turn]) / 32000:.1f} s)")
                    phase = "speaking"
                elif now - last_voice > args.end_after:
                    result = 0
                    break
            elif not heard_in_phase and now - started > 20 and turn == 0:
                print("FEHLER: keine Begrüßung gehört", file=sys.stderr)
                break
        elif phase == "speaking" and pending_tx == 0:
            time.sleep(0.15)
            t_speech_end = time.monotonic()
            turn += 1
            phase = "listen"
            heard_in_phase = False
            with lock:
                voice["first_after_speech"] = None
    if turn >= len(utterances) and not (args.hangup_after_greeting and turn == 0):
        result = 0 if heard_in_phase or result == 0 else result
    if args.hangup_after_greeting and greeted_at is not None:
        result = 0

    if not state["disconnected"]:
        call.hangup(pj.CallOpParam(True))
        for _ in range(25):
            endpoint.libHandleEvents(20)
    with lock:
        audio = bytes(rx)
    with wave.open(args.out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(audio)
    print(
        f"Aufnahme: {args.out} ({len(audio) / 32000:.1f} s), Gespräch beendet mit SIP {state['code'] or 'BYE von mir'}"
    )
    if latencies:
        print(f"Antwortzeiten: {', '.join(f'{v:.2f} s' for v in latencies)}")
    del call, account, port
    endpoint.libDestroy()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
