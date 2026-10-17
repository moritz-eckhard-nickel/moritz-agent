# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Stand-in for cosyvoice_worker.py: same command line and HTTP protocol, a sine tone as audio."""

from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RATE = 24000
cancel = threading.Event()


def tone(seconds: float) -> bytes:
    count = int(RATE * seconds)
    return b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / RATE))) for i in range(count)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("--model-dir", "--repo-root", "--speaker", "--threads", "--seed"):
        parser.add_argument(name)
    parser.add_argument("--delay", type=float, default=float(os.environ.get("FAKE_TTS_DELAY", "0")))
    args, _ = parser.parse_known_args()
    token = os.environ["MORITZ_INTERNAL_TOKEN"]
    if os.environ.get("FAKE_TTS_DIE_AT_START"):
        print(json.dumps({"event": "error", "error": "kaputt"}), flush=True)
        return 3

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            return

        def _json(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                return self._json(401, {})
            self._json(200, {"ready": True, "sample_rate": RATE})

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                return self._json(401, {})
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/cancel":
                cancel.set()
                return self._json(200, {})
            cancel.clear()
            deadline = time.monotonic() + args.delay
            while time.monotonic() < deadline:
                if cancel.is_set():
                    return self._json(499, {"error": "cancelled"})
                time.sleep(0.02)
            if "FEHLER" in request["text"]:
                return self._json(500, {"error": "RuntimeError: boom"})
            pcm = tone(0.1 + 0.02 * len(request["text"]))
            self.send_response(200)
            self.send_header("Content-Length", str(len(pcm)))
            self.send_header("X-Sample-Rate", str(RATE))
            self.end_headers()
            self.wfile.write(pcm)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(
        json.dumps(
            {
                "event": "ready",
                "port": server.server_address[1],
                "sample_rate": RATE,
                "load_seconds": 0.1,
            }
        ),
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
