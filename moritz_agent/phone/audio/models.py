# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Model files for the phone voice (downloaded from Hugging Face, never stored in git).

Groups:
    stt     Whisper small (faster-whisper / CTranslate2)                       ≈ 0.5 GB
    piper   Piper voice "Thorsten-Voice Hessisch" (high quality, CC0, ADR-027)  ≈ 0.11 GB

Integrity: sizes are checked against the manifest (warning on change); SHA-256 values are
recorded on first download in models/.checksums.json and compared on every later check.

    python -m moritz_agent.phone.audio.models status
    python -m moritz_agent.phone.audio.models fetch [--groups stt,piper] [--yes]
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
HESSISCH_PIPER = "Thorsten-Voice/Hessisch"
HESSISCH_PIPER_MODEL = "Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx"


@dataclass(frozen=True)
class RemoteFile:
    repo: str
    path: str  # path inside the repository
    size: int  # bytes, as listed on 2026-10-16
    target: str  # relative to the models directory


def _files() -> dict[str, list[RemoteFile]]:
    whisper = "Systran/faster-whisper-small"
    return {
        "stt": [
            RemoteFile(whisper, "model.bin", 483_546_902, "stt/faster-whisper-small/model.bin"),
            RemoteFile(whisper, "config.json", 2_370, "stt/faster-whisper-small/config.json"),
            RemoteFile(
                whisper, "tokenizer.json", 2_203_239, "stt/faster-whisper-small/tokenizer.json"
            ),
            RemoteFile(
                whisper, "vocabulary.txt", 459_861, "stt/faster-whisper-small/vocabulary.txt"
            ),
        ],
        "piper": [
            RemoteFile(
                HESSISCH_PIPER,
                HESSISCH_PIPER_MODEL,
                113_800_453,
                f"tts/piper/{HESSISCH_PIPER_MODEL}",
            ),
            RemoteFile(
                HESSISCH_PIPER,
                f"{HESSISCH_PIPER_MODEL}.json",
                6_856,
                f"tts/piper/{HESSISCH_PIPER_MODEL}.json",
            ),
        ],
    }


GROUPS = _files()


def models_dir(root: Path = REPO_ROOT) -> Path:
    return root / "models"


def files_for(groups: list[str]) -> list[RemoteFile]:
    selected: list[RemoteFile] = []
    for group in groups:
        if group not in GROUPS:
            raise ValueError(f"unbekannte Gruppe '{group}' (erlaubt: {', '.join(GROUPS)})")
        selected.extend(GROUPS[group])
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


def fetch(groups: list[str], root: Path = REPO_ROOT, assume_yes: bool = False) -> int:
    todo = [f for f in files_for(groups) if not (models_dir(root) / f.target).is_file()]
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
    # no question before the download (Moritz, 21.10.2026); ``assume_yes`` stays for old callers
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("FEHLER: huggingface_hub fehlt (Python-Umgebung einrichten).", file=sys.stderr)
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
    problems = verify(files_for(groups), root)
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
                f"{group:8s} FEHLT   ({len(absent)} von {len(GROUPS[group])} Dateien, {size / 1e9:.2f} GB gesamt)"
            )
        else:
            print(f"{group:8s} vorhanden")
    for problem in verify(files_for(groups), root, record=False):
        print(f"WARNUNG: {problem}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Modelle für Antons Stimme verwalten")
    parser.add_argument("command", choices=["status", "fetch"])
    parser.add_argument("--groups", default="stt,piper", help="Komma-getrennt: stt,piper")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--yes", action="store_true", help="(ohne Wirkung – es wird nie gefragt)")
    args = parser.parse_args(argv)
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    if args.command == "status":
        return status(groups, args.root)
    return fetch(groups, args.root, args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
