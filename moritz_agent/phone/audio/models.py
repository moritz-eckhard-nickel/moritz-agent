# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Model files for the phone voice (downloaded from Hugging Face, never stored in git).

Groups:
    stt        Whisper small (faster-whisper / CTranslate2)        ≈ 0.5 GB
    piper      Piper voice "Thorsten" (fast fallback voice)         ≈ 0.06 GB
    cosyvoice  Thorsten-Voice CosyVoice3 Hessisch = base model files + fine-tuned llm/flow ≈ 4.4 GB

The files of CosyVoice are laid out as the model card describes: the base model
FunAudioLLM/Fun-CosyVoice3-0.5B-2512 (vocoder, text tokenizer, configs) with the fine-tuned
llm.pt, flow.pt and spk2info.pt of Thorsten-Voice/CosyVoice3-Hessisch on top. The 1 GB speech
tokenizer is only needed for voice cloning and is skipped by default.

Integrity: sizes are checked against the manifest (warning on change); SHA-256 values are
recorded on first download in models/.checksums.json and compared on every later check.

    python -m moritz_agent.phone.audio.models status
    python -m moritz_agent.phone.audio.models fetch [--groups stt,piper,cosyvoice] [--yes]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
HESSISCH = "Thorsten-Voice/CosyVoice3-Hessisch"


@dataclass(frozen=True)
class RemoteFile:
    repo: str
    path: str  # path inside the repository
    size: int  # bytes, as listed on 2026-10-16
    target: str  # relative to the models directory


def _files() -> dict[str, list[RemoteFile]]:
    cosy = "tts/cosyvoice3-hessisch"
    return {
        "stt": [
            RemoteFile(
                "Systran/faster-whisper-small",
                "model.bin",
                483_546_902,
                "stt/faster-whisper-small/model.bin",
            ),
            RemoteFile(
                "Systran/faster-whisper-small",
                "config.json",
                2_370,
                "stt/faster-whisper-small/config.json",
            ),
            RemoteFile(
                "Systran/faster-whisper-small",
                "tokenizer.json",
                2_203_239,
                "stt/faster-whisper-small/tokenizer.json",
            ),
            RemoteFile(
                "Systran/faster-whisper-small",
                "vocabulary.txt",
                459_861,
                "stt/faster-whisper-small/vocabulary.txt",
            ),
        ],
        "piper": [
            RemoteFile(
                "rhasspy/piper-voices",
                "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx",
                63_201_294,
                "tts/piper/de_DE-thorsten-medium.onnx",
            ),
            RemoteFile(
                "rhasspy/piper-voices",
                "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json",
                4_819,
                "tts/piper/de_DE-thorsten-medium.onnx.json",
            ),
        ],
        "cosyvoice": [
            RemoteFile(BASE, "cosyvoice3.yaml", 6_934, f"{cosy}/cosyvoice3.yaml"),
            RemoteFile(BASE, "hift.pt", 83_202_622, f"{cosy}/hift.pt"),
            RemoteFile(BASE, "campplus.onnx", 28_303_423, f"{cosy}/campplus.onnx"),
            RemoteFile(
                BASE, "CosyVoice-BlankEN/config.json", 659, f"{cosy}/CosyVoice-BlankEN/config.json"
            ),
            RemoteFile(
                BASE,
                "CosyVoice-BlankEN/generation_config.json",
                242,
                f"{cosy}/CosyVoice-BlankEN/generation_config.json",
            ),
            RemoteFile(
                BASE,
                "CosyVoice-BlankEN/merges.txt",
                1_402_109,
                f"{cosy}/CosyVoice-BlankEN/merges.txt",
            ),
            RemoteFile(
                BASE,
                "CosyVoice-BlankEN/tokenizer_config.json",
                1_287,
                f"{cosy}/CosyVoice-BlankEN/tokenizer_config.json",
            ),
            RemoteFile(
                BASE,
                "CosyVoice-BlankEN/vocab.json",
                2_776_833,
                f"{cosy}/CosyVoice-BlankEN/vocab.json",
            ),
            RemoteFile(
                BASE,
                "CosyVoice-BlankEN/model.safetensors",
                988_097_824,
                f"{cosy}/CosyVoice-BlankEN/model.safetensors",
            ),
            RemoteFile(HESSISCH, "llm.pt", 2_024_669_194, f"{cosy}/llm.pt"),
            RemoteFile(HESSISCH, "flow.pt", 1_329_116_148, f"{cosy}/flow.pt"),
            RemoteFile(HESSISCH, "spk2info.pt", 2_062, f"{cosy}/spk2info.pt"),
        ],
    }


GROUPS = _files()
SPEECH_TOKENIZER = RemoteFile(
    BASE,
    "speech_tokenizer_v3.onnx",
    969_451_503,
    "tts/cosyvoice3-hessisch/speech_tokenizer_v3.onnx",
)


def models_dir(root: Path = REPO_ROOT) -> Path:
    return root / "models"


def files_for(groups: list[str], with_speech_tokenizer: bool = False) -> list[RemoteFile]:
    selected: list[RemoteFile] = []
    for group in groups:
        if group not in GROUPS:
            raise ValueError(f"unbekannte Gruppe '{group}' (erlaubt: {', '.join(GROUPS)})")
        selected.extend(GROUPS[group])
    if with_speech_tokenizer and "cosyvoice" in groups:
        selected.append(SPEECH_TOKENIZER)
    return selected


def missing(groups: list[str], root: Path = REPO_ROOT) -> list[RemoteFile]:
    base = models_dir(root)
    return [f for f in files_for(groups) if not (base / f.target).is_file()]


def _checksums_path(root: Path) -> Path:
    return models_dir(root) / ".checksums.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(files: list[RemoteFile], root: Path = REPO_ROOT, record: bool = True) -> list[str]:
    """Check present files; return human readable problems (empty = fine)."""
    problems: list[str] = []
    base = models_dir(root)
    store = _checksums_path(root)
    known: dict[str, str] = json.loads(store.read_text()) if store.is_file() else {}
    changed = False
    for item in files:
        path = base / item.target
        if not path.is_file():
            continue
        if path.stat().st_size != item.size:
            problems.append(
                f"{item.target}: Größe {path.stat().st_size} statt erwartet {item.size} (Upstream geändert oder Download unvollständig)"
            )
        digest = _sha256(path)
        if item.target in known and known[item.target] != digest:
            problems.append(f"{item.target}: Prüfsumme weicht von der ersten Installation ab")
        elif item.target not in known and record:
            known[item.target] = digest
            changed = True
    if changed:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(known, indent=1, sort_keys=True))
    return problems


def fetch(
    groups: list[str],
    root: Path = REPO_ROOT,
    with_speech_tokenizer: bool = False,
    assume_yes: bool = False,
) -> int:
    todo = [
        f
        for f in files_for(groups, with_speech_tokenizer)
        if not (models_dir(root) / f.target).is_file()
    ]
    if not todo:
        print("Alle Modelldateien sind bereits vorhanden.")
        return 0
    total = sum(f.size for f in todo)
    base = models_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(base).free
    print(f"Zu laden: {len(todo)} Dateien, {total / 1e9:.2f} GB (frei: {free / 1e9:.1f} GB)")
    if free < total * 1.1:
        print("FEHLER: zu wenig freier Speicherplatz.", file=sys.stderr)
        return 1
    if not assume_yes and (
        not sys.stdin.isatty()
        or input("Jetzt von huggingface.co herunterladen? [j/N] ").strip().lower() not in ("j", "y")
    ):
        print("Abgebrochen (mit --yes ohne Rückfrage).")
        return 1
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("FEHLER: huggingface_hub fehlt (./test-1.sh setup).", file=sys.stderr)
        return 1
    for item in todo:
        target = base / item.target
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"→ {item.repo}/{item.path} ({item.size / 1e6:.0f} MB)")
        # hf_hub_download resumes interrupted downloads and verifies the transfer size.
        downloaded = Path(
            hf_hub_download(
                repo_id=item.repo,
                filename=item.path,
                local_dir=str(base / ".hf" / item.repo.replace("/", "__")),
            )
        )
        shutil.move(str(downloaded), target)
    problems = verify(files_for(groups, with_speech_tokenizer), root)
    for problem in problems:
        print(f"WARNUNG: {problem}", file=sys.stderr)
    print("Fertig.")
    return 0


def status(groups: list[str], root: Path = REPO_ROOT) -> int:
    code = 0
    for group in groups:
        absent = missing([group], root)
        size = sum(f.size for f in files_for([group]))
        if absent:
            code = 1
            print(
                f"{group:10s} FEHLT   ({len(absent)} von {len(GROUPS[group])} Dateien, {size / 1e9:.2f} GB gesamt)"
            )
        else:
            print(f"{group:10s} vorhanden")
    for problem in verify(files_for(groups), root, record=False):
        print(f"WARNUNG: {problem}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Modelle für Nikitas Stimme verwalten")
    parser.add_argument("command", choices=["status", "fetch"])
    parser.add_argument(
        "--groups", default="stt,piper,cosyvoice", help="Komma-getrennt: stt,piper,cosyvoice"
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--yes", action="store_true", help="ohne Rückfrage laden")
    parser.add_argument(
        "--with-speech-tokenizer",
        action="store_true",
        help="1 GB Sprach-Tokenizer (nur für Stimmenklonen)",
    )
    args = parser.parse_args(argv)
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    if args.command == "status":
        return status(groups, args.root)
    return fetch(groups, args.root, args.with_speech_tokenizer, args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
