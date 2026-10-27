# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The language model as the phone's responder, behind the instant answers (ADR-029, P1-09)."""

from __future__ import annotations

from moritz_agent.agent.loop import AgentLoop
from moritz_agent.inference import InferenceError
from moritz_agent.phone.responder import Reply, ResponderUnavailable, TurnContext
from moritz_agent.tools.base import ToolContext


class AgentResponder:
    def __init__(self, loop: AgentLoop) -> None:
        self.loop = loop

    async def respond(self, text: str, context: TurnContext) -> Reply:
        tool_ctx = ToolContext(
            profile=self.loop.profile.name,
            channel=context.extras.get("channel", "phone"),
            call_id=context.call_id,
            surface=context.extras.get("surface", "spoken"),
            skills=context.extras.get("skills"),
            on_event=context.extras.get("on_event"),
        )
        try:
            result = await self.loop.run(
                text,
                context.history,
                tool_ctx,
                on_text=context.extras.get("on_text"),
                documents=context.extras.get("files") or [],
            )
        except InferenceError as exc:
            raise ResponderUnavailable(str(exc)) from exc
        return Reply(
            text=result.text,
            hangup=result.hangup,
            meta={"tools": result.tools, "sources": result.sources},
        )
