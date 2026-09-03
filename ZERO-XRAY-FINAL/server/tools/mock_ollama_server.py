"""
Standalone Ollama-compatible MOCK server -- for TESTING ONLY.

This is not a replacement for Ollama. It exists so the ZERO X-RAY
pipeline's real request/response/parsing code (core/llm.py's
LocalLLM.generate(), and every agent's JSON parsing + validation
logic) can be exercised end-to-end -- including deliberate AI-failure
scenarios -- without needing a real model loaded, and without ever
touching the real Ollama instance on port 11434.

Run it on port 11435 (never 11434 -- that's real Ollama's port):

    uvicorn tools.mock_ollama_server:app --host 127.0.0.1 --port 11435

Then point the ZERO X-RAY backend at it (no agent code changes
needed -- see .env.example's MOCK block):

    ZX_LLM_MODE=mock
    OLLAMA_HOST=http://127.0.0.1:11435
    OLLAMA_MODEL=qwen3:4b   (or any name -- the mock accepts any model)

Endpoints implemented (the exact subset core/llm.py uses):
    GET  /api/version
    GET  /api/tags
    POST /api/chat

Response routing: POST /api/chat inspects the incoming system_prompt
(the first message with role="system") to recognize which agent is
calling -- every agent's system_prompt in this codebase is a distinct,
stable opening phrase (see AGENT_SYSTEM_PROMPT_MARKERS below) -- and
returns a realistic, schema-correct canned JSON response for THAT
agent, not a generic "Hello" string. This is what lets a mock-success
run exercise the real parsing/validation path in every agent, not just
prove an HTTP round-trip works.

Failure simulation: set ZX_MOCK_FAILURE_MODE (env var, or per-request
override via the X-ZX-Mock-Failure-Mode header, which takes priority
when present -- used by the automated test suite so it doesn't need to
restart this server between failure-mode tests):

    none              (default) -- normal, realistic success response
    empty_response    -- HTTP 200, message.content == "", done_reason="length"
                         (mirrors a real truncated-generation failure)
    invalid_json      -- HTTP 200, message.content is deliberately malformed JSON
    chat_500          -- HTTP 500 from POST /api/chat only (GET endpoints still work)
    timeout           -- POST /api/chat sleeps far longer than any
                         reasonable client timeout, to trigger a real
                         requests.exceptions.Timeout on the caller's side
"""

import asyncio
import json
import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="ZERO X-RAY Mock Ollama Server (TESTING ONLY)")

MOCK_MODEL_NAME = os.environ.get("OLLAMA_MODEL", "qwen3:4b")

VALID_FAILURE_MODES = {
    "none",
    "empty_response",
    "invalid_json",
    "chat_500",
    "timeout",
}


def _current_failure_mode(request: Request) -> str:
    header_value = request.headers.get("X-ZX-Mock-Failure-Mode")
    if header_value and header_value.strip().lower() in VALID_FAILURE_MODES:
        return header_value.strip().lower()
    env_value = os.environ.get("ZX_MOCK_FAILURE_MODE", "none").strip().lower()
    return env_value if env_value in VALID_FAILURE_MODES else "none"


@app.get("/api/version")
def get_version():
    return {"version": "0.0.0-zx-mock"}


@app.get("/api/tags")
def get_tags():
    # Real Ollama returns richer metadata per model; only "name" is
    # actually read by core/llm.py's reachability check.
    return {
        "models": [
            {"name": MOCK_MODEL_NAME, "model": MOCK_MODEL_NAME},
        ]
    }


# =====================================================================
# Per-agent canned response bodies
# =====================================================================
# All response-routing logic lives in tools/mock_ollama_responses.py
# (stdlib-only, no fastapi dependency) so it can be reused by
# tools/mock_ollama_server_stdlib.py and imported directly in tests
# without requiring fastapi/uvicorn to be installed. This file is now
# just the thin FastAPI transport wrapper around that shared logic.
from tools.mock_ollama_responses import _route_response


@app.post("/api/chat")
async def post_chat(request: Request):
    mode = _current_failure_mode(request)
    body = await request.json()
    model = body.get("model", MOCK_MODEL_NAME)
    messages = body.get("messages", [])

    if mode == "timeout":
        # Uses asyncio.sleep, NOT time.sleep: a blocking time.sleep()
        # inside an async endpoint freezes uvicorn's entire event
        # loop for its whole duration -- including shutdown signal
        # handling -- which would make this mock itself hang instead
        # of just the one simulated slow request. asyncio.sleep
        # yields control back to the loop, so the server stays
        # responsive (and killable) while this one request is
        # deliberately slow, matching how a real slow/hung Ollama
        # call actually behaves from the caller's side.
        await asyncio.sleep(300)

    if mode == "chat_500":
        return JSONResponse(
            status_code=500,
            content={"error": "MOCK_AI: simulated internal server error"},
        )

    if mode == "empty_response":
        return {
            "model": model,
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "length",
        }

    if mode == "invalid_json":
        return {
            "model": model,
            "created_at": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                # Deliberately malformed / truncated JSON.
                "content": '{"steps": ["first step", "second step"',
            },
            "done": True,
            "done_reason": "stop",
        }

    # mode == "none": normal, realistic success.
    payload = _route_response(messages)
    return {
        "model": model,
        "created_at": "2026-01-01T00:00:00Z",
        "message": {
            "role": "assistant",
            "content": json.dumps(payload, ensure_ascii=False),
        },
        "done": True,
        "done_reason": "stop",
    }
