# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Language model access: KoboldCpp process, OpenAI-compatible client, priority queue (P1-05)."""

from moritz_agent.inference.client import (
    Completion,
    InferenceAborted,
    InferenceClient,
    InferenceError,
    InferenceTimeout,
    InferenceUnavailable,
    ToolCall,
)
from moritz_agent.inference.queue import InferenceQueue, Priority

__all__ = [
    "Completion",
    "InferenceAborted",
    "InferenceClient",
    "InferenceError",
    "InferenceQueue",
    "InferenceTimeout",
    "InferenceUnavailable",
    "Priority",
    "ToolCall",
]
