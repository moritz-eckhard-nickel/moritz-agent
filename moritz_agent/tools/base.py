# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Tool protocol and result object of the agent (P1-07, AGENT-03).

Every tool answers with the same shape: ``{ok, data | error, sources?, speakable?}``. ``data`` holds
the facts for the language model, ``speakable`` a finished German sentence the model may read out
unchanged, ``sources`` where the facts came from (SEARCH-02, AGENT-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

if TYPE_CHECKING:
    from moritz_agent.skills.base import SkillContext


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None  # machine-readable: search_unavailable, no_answer, invalid_arguments …
    message: str | None = None  # German explanation for the model (what went wrong, what to say)
    sources: list[dict[str, str]] = field(default_factory=list)
    speakable: str | None = None
    truncated: bool = False
    args: dict[str, Any] = field(default_factory=dict, repr=False)  # the validated arguments (log)

    @classmethod
    def success(
        cls,
        data: Any = None,
        *,
        speakable: str | None = None,
        sources: list[dict[str, str]] | None = None,
    ) -> ToolResult:
        return cls(True, data=data, speakable=speakable, sources=sources or [])

    @classmethod
    def failure(cls, error: str, message: str = "") -> ToolResult:
        return cls(False, error=error, message=message or None)

    def payload(self) -> dict[str, Any]:
        """The JSON object the model gets back."""
        if not self.ok:
            body: dict[str, Any] = {"ok": False, "error": self.error}
            if self.message:
                body["message"] = self.message
            return body
        body = {"ok": True, "data": self.data}
        if self.speakable:
            body["speakable"] = self.speakable
        if self.sources:
            body["sources"] = self.sources
        if self.truncated:
            body["truncated"] = True
        return body


@dataclass
class ToolContext:
    """The conversation a tool call belongs to (never the user's words)."""

    profile: str = "phone"  # decides which tools are allowed (PHONE-45)
    channel: str = "phone"  # phone | discord | web
    call_id: str | None = None
    surface: str = "spoken"  # spoken | chat
    skills: SkillContext | None = None  # follow-ups of the instant answers continue from here
    turn_id: int | None = None


class Tool(Protocol):
    name: str
    description: str  # German, one or two sentences: when to use it
    parameters: dict[str, Any]  # JSON schema of the arguments
    timeout_s: float

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class BaseTool:
    """Convenience base: name, description and schema as class attributes."""

    name = ""
    description = ""
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    timeout_s = 10.0

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def definition(self) -> dict[str, Any]:
        """The tool in the format of the chat completions API."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
