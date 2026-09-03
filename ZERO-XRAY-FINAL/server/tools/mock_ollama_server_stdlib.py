"""
Zero-dependency (stdlib only) Ollama-compatible MOCK server -- for
TESTING ONLY.

tools/mock_ollama_server.py (FastAPI-based) is the primary, fully
featured mock -- prefer it when fastapi/uvicorn are installed, since
it also supports per-request failure-mode overrides via the
X-ZX-Mock-Failure-Mode header (used by tests/test_mock_ollama_server.py).

This file exists for the environments where installing fastapi/uvicorn
isn't possible (minimal containers, offline/sandboxed CI, some
restricted developer machines) but a REAL HTTP round trip through
core/llm.py's actual request/response code -- not an in-process stub
like tests/test_full_pipeline_ai_scenarios.py's ScenarioMockLLM -- is
still needed to prove the pipeline's AI-primary path genuinely works
over the network. It implements the exact same three endpoints
core/llm.py calls, using the SAME shared response logic in
tools/mock_ollama_responses.py, so both servers behave identically for
every agent's canned "success" response.

Failure-mode simulation here is coarser than the FastAPI version: only
the ZX_MOCK_FAILURE_MODE environment variable is honored (read once at
each request, so it can still be changed between calls in the same
run by a test/driver script setting os.environ before each call --
there is no per-request header override, since http.server's request
handling doesn't need one for this simpler use case).

Run standalone:

    python -m tools.mock_ollama_server_stdlib --port 11435

Or import and use programmatically (see run_local_pipeline_check.py):

    from tools.mock_ollama_server_stdlib import start_server
    httpd, thread = start_server(port=0)   # port=0 -> pick a free port
    host = f"http://127.0.0.1:{httpd.server_port}"
    ...
    httpd.shutdown()
"""

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.mock_ollama_responses import _route_response

MOCK_MODEL_NAME = os.environ.get("OLLAMA_MODEL", "qwen3:4b")

VALID_FAILURE_MODES = {
    "none",
    "empty_response",
    "invalid_json",
    "chat_500",
    "timeout",
}


def _current_failure_mode() -> str:
    env_value = os.environ.get("ZX_MOCK_FAILURE_MODE", "none").strip().lower()
    return env_value if env_value in VALID_FAILURE_MODES else "none"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        # Silence the default per-request stderr logging; the driver
        # script controls its own output.
        pass

    def _send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version":
            self._send_json(200, {"version": "0.0.0-zx-mock-stdlib"})
            return
        if self.path == "/api/tags":
            self._send_json(200, {
                "models": [
                    {"name": MOCK_MODEL_NAME, "model": MOCK_MODEL_NAME},
                ]
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except ValueError:
            body = {}

        model = body.get("model", MOCK_MODEL_NAME)
        messages = body.get("messages", [])
        mode = _current_failure_mode()

        if mode == "timeout":
            # Mirrors the FastAPI mock's behavior: sleep far longer
            # than any reasonable client timeout so the caller's own
            # requests.exceptions.Timeout fires.
            time.sleep(300)

        if mode == "chat_500":
            self._send_json(500, {"error": "MOCK_AI: simulated internal server error"})
            return

        if mode == "empty_response":
            self._send_json(200, {
                "model": model,
                "created_at": "2026-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "length",
            })
            return

        if mode == "invalid_json":
            self._send_json(200, {
                "model": model,
                "created_at": "2026-01-01T00:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": '{"steps": ["first step", "second step"',
                },
                "done": True,
                "done_reason": "stop",
            })
            return

        payload = _route_response(messages)
        self._send_json(200, {
            "model": model,
            "created_at": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": json.dumps(payload, ensure_ascii=False),
            },
            "done": True,
            "done_reason": "stop",
        })


def start_server(host="127.0.0.1", port=11435):
    """Start the stdlib mock server in a background daemon thread.

    port=0 lets the OS pick a free port -- read it back from
    httpd.server_port. Returns (httpd, thread); call httpd.shutdown()
    (and thread.join()) to stop it.
    """
    httpd = ThreadingHTTPServer((host, port), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()

    httpd, thread = start_server(host=args.host, port=args.port)
    print(
        f"ZERO X-RAY stdlib mock Ollama server running on "
        f"http://{args.host}:{httpd.server_port} (Ctrl+C to stop)."
    )
    try:
        while thread.is_alive():
            thread.join(timeout=1)
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.shutdown()
