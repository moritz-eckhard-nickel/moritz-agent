# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""``end_call``: the language model ends the call itself (PHONE-36).

The farewell guard only catches short goodbyes ("tschüss"); a longer "danke, das war's für heute,
leg auf" reaches the model. With this tool the model decides: it calls ``end_call``, says goodbye
in its answer, and the call ends after that answer was spoken. Only the spoken profiles (phone,
Discord voice channel) get it – in the text chat there is nothing to hang up.
"""

from __future__ import annotations

from typing import Any, ClassVar

from moritz_agent.tools.base import BaseTool, ToolContext, ToolResult

END_CALL = "end_call"


class EndCall(BaseTool):
    name = END_CALL
    description = (
        "Beendet das Gespräch, nachdem deine Antwort vorgelesen wurde. Rufe es auf, wenn Moritz "
        "sich verabschiedet oder ausdrücklich auflegen will (z. B. „leg auf“, „das war's“, „ich muss los“), "
        "und verabschiede dich in deiner Antwort kurz. Nicht aufrufen, wenn er nur über Auflegen redet."
    )
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    timeout_s = 1.0

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult.success(
            {"ends": "nach deiner Antwort"},
            speakable="Alles klar, mach's gut!",
        )
