# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A fake KoboldCpp *process* (stdlib only): started like koboldcpp.py, answers like it.

For tests of the process side (InferenceService, scripts/bench_llm.py). Questions with "Uhr" or
"spät" get a get_current_time tool call, everything else a short sentence.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def chunk(delta: dict[str, Any], finish: str | None = None) -> bytes:
    body = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(body)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return None

    def _json(self, data: Any) -> None:
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/api/v1/model":
            self._json({"result": "fake/qwen3"})
        elif self.path == "/api/extra/perf":
            self._json({"last_eval": 0.5, "last_token_count": 12, "last_process": 0.1})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/extra/tokencount":
            self._json({"value": len(str(body.get("prompt", ""))) // 4})
            return
        if self.path == "/api/extra/abort":
            self._json({"success": True})
            return
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        messages = body.get("messages") or []
        last = messages[-1] if messages else {}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        question = str(last.get("content", "")).lower()
        if (
            last.get("role") == "user"
            and body.get("tools")
            and ("uhr" in question or "spät" in question)
        ):
            call = {
                "index": 0,
                "id": "call_1",
                "function": {"name": "get_current_time", "arguments": "{}"},
            }
            self.wfile.write(chunk({"tool_calls": [call]}))
            self.wfile.write(chunk({}, "tool_calls"))
        else:
            for piece in ("Das ist ", "eine kurze ", "Antwort."):
                self.wfile.write(chunk({"content": piece}))
                time.sleep(0.01)
            self.wfile.write(chunk({}, "stop"))
        self.wfile.write(b"data: [DONE]\n\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args, _ = parser.parse_known_args()  # every other KoboldCpp flag is accepted and ignored
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
