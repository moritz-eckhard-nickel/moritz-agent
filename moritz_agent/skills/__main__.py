# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""``python -m moritz_agent.skills`` – try the instant answers without a phone (SKILL-29).

ask "Wie spät ist es?" [--at 2026-10-18T19:12] [--offline] [--explain] [--chat]
help                      list all skills with examples
corpus [FILE]             run the utterance corpus and report mistakes
providers                 ask every data service once and report the state
prefetch                  warm the cache for the home place
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from moritz_agent.config.settings import REPO_ROOT, SettingsError, load_settings
from moritz_agent.skills.clock import FixedClock
from moritz_agent.skills.providers import Providers
from moritz_agent.skills.registry import groups
from moritz_agent.skills.responder import SkillResponder
from moritz_agent.skills.router import Router, new_context
from moritz_agent.skills.services import build_services
from moritz_agent.skills.text.normalize import prepare


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m moritz_agent.skills", description=__doc__)
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="answer one or more sentences (follow-ups share the context)")
    ask.add_argument("text", nargs="+")
    ask.add_argument("--at", help="pretend it is this time, e.g. 2026-10-18T19:12")
    ask.add_argument("--offline", action="store_true", help="no network access")
    ask.add_argument("--explain", action="store_true", help="show how the sentence was understood")
    ask.add_argument(
        "--chat", action="store_true", help="chat surface (Discord/web) instead of spoken"
    )
    sub.add_parser("help", help="list the skills")
    sub.add_parser("providers", help="ask every data service once")
    sub.add_parser("prefetch", help="warm the cache for the home place")
    corpus = sub.add_parser("corpus", help="run an utterance corpus (JSON lines)")
    corpus.add_argument(
        "file", nargs="?", default=str(REPO_ROOT / "tests/moritz_agent/data/skills.de.jsonl")
    )
    corpus.add_argument("--at", default="2026-10-18T19:12")
    return parser


async def _ask(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    if args.offline:
        settings.skills.online = False
    clock = FixedClock(datetime.fromisoformat(args.at)) if args.at else None
    svc = build_services(settings, clock=clock, seed=1, providers=Providers)
    router = Router(svc)
    ctx = new_context(svc, seed=1)
    try:
        return await _ask_all(args, svc, router, ctx)
    finally:
        if isinstance(svc.providers, Providers):
            await svc.providers.aclose()


async def _ask_all(args: argparse.Namespace, svc, router: Router, ctx) -> int:
    for sentence in args.text:
        surface = "chat" if args.chat else "spoken"
        outcome = await router.route(sentence, ctx, surface=surface)
        print(f"> {sentence}")
        if args.explain:
            utt = prepare(sentence)
            print(f"  verstanden als: {utt.text!r}")
            for cand in router.candidates(utt, surface)[:4]:
                print(f"  Kandidat {cand.skill.id}: {cand.score:.2f}")
            print(f"  Ergebnis: {outcome.reason} {outcome.skill_id or ''} {outcome.ms:.1f} ms")
        if outcome.result is None:
            print("  (keine Sofortauskunft – das ginge an das Sprachmodell)")
            continue
        print(f"  {outcome.result.text or outcome.result.prompt}")
        if outcome.result.clarify:
            print("  Optionen: " + " | ".join(o.label for o in outcome.result.clarify.options))
    return 0


def _help() -> int:
    for group, skills in sorted(groups().items()):
        print(f"\n[{group}]")
        for item in sorted(skills, key=lambda s: s.id):
            example = f"   z. B. „{item.examples[0]}“" if item.examples else ""
            print(f"  {item.id}{example}")
    return 0


async def _providers(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    svc = build_services(settings, providers=Providers)
    assert isinstance(svc.providers, Providers)
    from moritz_agent.skills.slots.where import home_place

    home = home_place(svc)
    print(f"Heimatort: {home.name} {home.postal_codes[:1]} ({home.lat:.2f}, {home.lon:.2f})")
    if not settings.skills.online:
        print("skills.online = false – es wird nichts abgerufen.")
        return 0
    failed = 0
    try:
        for name, ok, ms, detail in await svc.providers.check_all():
            print(f"{'✓' if ok else '✗'} {name:<36} {ms:6.0f} ms  {detail}")
            failed += 0 if ok else 1
    finally:
        await svc.providers.aclose()
    return 1 if failed else 0


async def _prefetch(args: argparse.Namespace) -> int:
    svc = build_services(load_settings(args.config), providers=Providers)
    assert isinstance(svc.providers, Providers)
    try:
        for name, state in (await svc.providers.prefetch_once()).items():
            print(f"{name}: {state}")
    finally:
        await svc.providers.aclose()
    return 0


async def _corpus(args: argparse.Namespace) -> int:
    svc = build_services(clock=FixedClock(datetime.fromisoformat(args.at)), seed=1)
    router = Router(svc)
    wrong = total = 0
    for line in Path(args.file).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        item = json.loads(line)
        ctx = new_context(svc, seed=1)
        for prior in item.get("prior", []):
            await router.route(prior, ctx)
        outcome = await router.route(item["say"], ctx)
        total += 1
        expected = item.get("skill")
        if (outcome.skill_id if outcome.result else None) != expected:
            wrong += 1
            print(f"✗ {item['say']!r}: erwartet {expected}, bekommen {outcome.skill_id}")
    print(f"{total - wrong}/{total} richtig")
    return 1 if wrong else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "ask":
            return asyncio.run(_ask(args))
        if args.command == "help":
            return _help()
        if args.command == "providers":
            return asyncio.run(_providers(args))
        if args.command == "prefetch":
            return asyncio.run(_prefetch(args))
        return asyncio.run(_corpus(args))
    except SettingsError as exc:
        print(f"Konfiguration ungültig: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SkillResponder", "main"]
