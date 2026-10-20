# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""From a core answer to Discord messages (docs/plan/14 §8): text, card, buttons, selection, file.

Everything here is plain data (``OutMessage``); ``client.py`` turns it into discord.py objects. So
splitting, limits, secret filter and the style are tested without Discord.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from moritz_agent.core.turn import TurnResult
from moritz_agent.discord import components
from moritz_agent.discord.style import Styler, StyleState

MESSAGE_LIMIT = 2000
EMBED_DESCRIPTION = 4096
EMBED_FIELD_NAME = 256
EMBED_FIELD_VALUE = 1024
EMBED_FIELDS = 25
EMBED_TOTAL = 6000
EMBED_FOOTER = 2048
MAX_MESSAGES = 3
MAX_BUTTONS = 5
MAX_OPTIONS = 25
COLORS = {
    "neutral": 0x6B7280,
    "good": 0x2ECC71,
    "info": 0x3498DB,
    "warn": 0xF1C40F,
    "alert": 0xE67E22,
    "danger": 0xE74C3C,
    "violet": 0x9B59B6,
}
LEVEL_COLORS = {1: "info", 2: "warn", 3: "alert", 4: "violet"}
_FENCE = re.compile(r"^```", re.MULTILINE)


@dataclass
class Button:
    label: str
    custom_id: str = ""
    style: str = "secondary"  # primary | secondary | success | danger | link
    url: str = ""


@dataclass
class Select:
    placeholder: str
    custom_id: str
    options: list[str]


@dataclass
class OutMessage:
    content: str = ""
    embed: dict[str, Any] | None = None
    buttons: list[Button] = field(default_factory=list)
    select: Select | None = None
    file: tuple[str, bytes] | None = None
    ephemeral: bool = False


# -- secrets and length ---------------------------------------------------------------------------------
def redact(text: str, secrets: list[str]) -> str:
    """Every known secret of eight or more characters is replaced (LOG-02, docs/plan/14 §5.3)."""
    for secret in secrets:
        if len(secret) >= 8:
            text = text.replace(secret, "***")
    return text


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Pieces of at most ``limit`` characters, cut at paragraphs, lines, then words – and never in
    the middle of a code block (an open block is closed and opened again in the next piece)."""
    pieces: list[str] = []
    rest = text.strip()
    reopen = ""
    while rest:
        room = limit - len(reopen) - 4  # room for a closing fence
        if len(rest) <= limit - len(reopen):
            pieces.append(reopen + rest)
            break
        cut = _cut_point(rest, room)
        piece, rest = rest[:cut].rstrip(), rest[cut:].lstrip("\n ")
        body = reopen + piece
        open_block = len(_FENCE.findall(body)) % 2 == 1
        if open_block:
            body += "\n```"
            reopen = "```\n"
        else:
            reopen = ""
        pieces.append(body)
    return pieces


def _cut_point(text: str, room: int) -> int:
    for separator in ("\n\n", "\n", ". ", " "):
        index = text.rfind(separator, 0, room)
        if index > room // 3:
            return index + (len(separator) if separator == ". " else 0)
    return room


# -- cards ---------------------------------------------------------------------------------------------------
def build_embed(card: dict[str, Any], *, color: str | None = None) -> dict[str, Any]:
    """A card dict as a Discord embed within all limits."""
    fields = [
        {
            "name": str(f["name"])[:EMBED_FIELD_NAME] or "·",
            "value": str(f["value"])[:EMBED_FIELD_VALUE] or "·",
            "inline": bool(f.get("inline", False)),
        }
        for f in card.get("fields", [])[:EMBED_FIELDS]
    ]
    embed: dict[str, Any] = {
        "title": str(card.get("title", ""))[:EMBED_FIELD_NAME],
        "description": str(card.get("description", ""))[:EMBED_DESCRIPTION],
        "color": COLORS.get(color or card.get("color", "neutral"), COLORS["neutral"]),
    }
    if fields:
        embed["fields"] = fields
    if card.get("footer"):
        embed["footer"] = {"text": str(card["footer"])[:EMBED_FOOTER]}

    # the sum of all texts must stay below 6000 characters
    def total() -> int:
        return (
            len(embed["title"])
            + len(embed["description"])
            + sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
            + len(embed.get("footer", {}).get("text", ""))
        )

    while total() > EMBED_TOTAL and embed.get("fields"):
        embed["fields"].pop()
    excess = total() - EMBED_TOTAL
    if excess > 0:
        keep = max(0, len(embed["description"]) - excess - 2)
        embed["description"] = embed["description"][:keep] + " …"
    return embed


def _buttons(result: TurnResult, user_id: str) -> list[Button]:
    buttons = [
        Button(a["label"][:80], components.encode_action(user_id, a["say"]))
        for a in result.actions[:MAX_BUTTONS]
    ]
    links = [s for s in result.sources if s.get("url", "").startswith("https://")]
    for source in links[: max(0, MAX_BUTTONS - len(buttons))]:
        buttons.append(Button(f"Quelle: {source['name']}"[:80], style="link", url=source["url"]))
    return buttons


def _source_line(result: TurnResult) -> str:
    """Model answers carry their sources as links under the text."""
    links = [s for s in result.sources if s.get("url")]
    if not links or any(s["url"] in result.markdown for s in links):
        return ""
    return "\n\n" + "Quellen: " + " · ".join(f"[{s['name']}]({s['url']})" for s in links[:5])


# -- the answer -----------------------------------------------------------------------------------------------------
def render_result(
    result: TurnResult,
    *,
    user_id: str,
    styler: Styler,
    state: StyleState,
    seed: int,
    secrets: list[str],
    limit: int = MESSAGE_LIMIT,
    ephemeral: bool = False,
) -> list[OutMessage]:
    """The messages for one answer: a card for data, text otherwise, then buttons or a menu."""
    if result.clarify is not None:
        question = redact(result.clarify["question"], secrets)
        options = [str(o)[:100] for o in result.clarify["options"][:MAX_OPTIONS]]
        menu = Select("Welches meinst du?", components.encode_pick(user_id), options)
        return [OutMessage(content=question[:limit], select=menu, ephemeral=ephemeral)]

    text = result.markdown or result.text or ""
    if result.skill_id or result.prompt:
        text = styler.decorate(
            text, skill_id=result.skill_id, serious=result.serious, seed=seed, state=state
        )
    text = redact(text, secrets)
    if result.card is not None:
        card = {
            **result.card,
            "description": redact(
                styler.decorate(
                    result.card.get("description", ""),
                    skill_id=result.skill_id,
                    serious=result.serious,
                    seed=seed,
                    state=state,
                ),
                secrets,
            ),
            "fields": [
                {**f, "value": redact(str(f["value"]), secrets)}
                for f in result.card.get("fields", [])
            ],
        }
        message = OutMessage(
            embed=build_embed(card), buttons=_buttons(result, user_id), ephemeral=ephemeral
        )
        return [message]
    text += redact(_source_line(result), secrets)
    pieces = split_text(text, limit)
    if len(pieces) > MAX_MESSAGES:
        note = redact(styler.error("too_long"), secrets)
        return [
            OutMessage(
                content=f"{pieces[0][: limit // 2].rstrip()} …\n\n{note}",
                file=("antwort.md", text.encode("utf-8")),
                buttons=_buttons(result, user_id),
                ephemeral=ephemeral,
            )
        ]
    messages = [OutMessage(content=piece, ephemeral=ephemeral) for piece in pieces] or [
        OutMessage(content="…", ephemeral=ephemeral)
    ]
    messages[-1].buttons = _buttons(result, user_id)
    return messages


# -- messages the main process sends on its own ------------------------------------------------------------
def render_notification(
    item: dict[str, Any], *, secrets: list[str], mention: str | None = None
) -> OutMessage:
    """Reminder, warning, briefing, … from the outbox (docs/plan/14 §11)."""
    payload = item["payload"]
    kind = item["kind"]
    title = redact(str(payload.get("title", "")), secrets)
    text = redact(str(payload.get("text", "")), secrets)
    if kind in {"warning", "all_clear"}:
        level = int(payload.get("level", 0) or 0)
        fields = []
        if payload.get("instruction"):
            fields.append(
                {
                    "name": "Was tun?",
                    "value": redact(payload["instruction"], secrets),
                    "inline": False,
                }
            )
        if payload.get("until"):
            fields.append(
                {"name": "Bis", "value": str(payload["until"]).replace("T", " "), "inline": True}
            )
        card = {
            "title": title[:EMBED_FIELD_NAME],
            "description": text,
            "color": LEVEL_COLORS.get(level, "good" if kind == "all_clear" else "warn"),
            "fields": fields,
            "footer": str(payload.get("source", "")),
        }
        return OutMessage(content=mention or "", embed=build_embed(card))
    colors = {
        "reminder": "good",
        "briefing": "info",
        "waste": "good",
        "system": "neutral",
        "call": "neutral",
    }
    card = {"title": title, "description": text, "color": colors.get(kind, "neutral")}
    return OutMessage(content=mention or "", embed=build_embed(card))


def mention_for(item: dict[str, Any]) -> str | None:
    """ "<@id>" for a message to the default channel that is meant for one person."""
    user = item["payload"].get("mention") or item.get("user_id")
    return f"<@{user}>" if user and str(user).isdigit() else None


def stamp(moment: datetime) -> str:
    return moment.strftime("%d.%m.%Y %H:%M")
