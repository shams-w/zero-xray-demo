"""Shared test helper: makes core/llm.py's LocalLLM talk to a live,
in-process, stdlib-only mock Ollama server for the DURATION of one
test module's run, then restores whatever was there before.

WHY THIS EXISTS (Mandatory AI Mode audit fix): ZERO X-RAY now REQUIRES
a reachable AI engine for /api/analyze by default (REQUIRE_OLLAMA=true)
-- a genuinely unreachable Ollama returns 503 AI_ENGINE_UNAVAILABLE
instead of silently completing the pipeline on deterministic fallback
(see core/llm.py's LocalLLM.check_available / main.py's analyze_service
preflight check). Test files that exercise /api/analyze only to set up
fixtures for UNRELATED functionality (tenant isolation, publishing,
journeys, monitoring, Evolve/Prevent chains, ...) need the pipeline to
actually succeed, so they point at this stdlib mock server (a real,
reachable, Ollama-API-compatible stand-in -- see
tools/mock_ollama_server_stdlib.py) instead of a deliberately
unreachable host.

ROOT-CAUSE NOTE (why this patches live attributes instead of just
setting environment variables): core/llm.py reads OLLAMA_HOST/
OLLAMA_MODEL/ZX_LLM_MODE/IS_MOCK as MODULE-LEVEL constants, fixed the
first time core.llm is imported anywhere in the process -- and under
`unittest discover`, that first import can be triggered by a completely
unrelated test file (e.g. test_adaptive_service_paths.py, which only
imports agents.journey_builder_agent) before this helper ever runs, so
a plain os.environ.setdefault() here would frequently be too late to
have any effect. Directly setting attributes on the already-imported
core.llm module works regardless of import order, because every place
in core/llm.py that reads OLLAMA_HOST/IS_MOCK/etc. does so as a live
module-global lookup at call time, not a value captured once at def
time. Scoping the patch to setUpModule/tearDownModule (rather than a
permanent, unscoped reload) means it is only in effect while THIS
module's tests are actually running -- unittest discover runs one test
module's tests fully, in order, before moving to the next, so this
cannot leak into another file's tests (e.g. test_full_pipeline_ai_
scenarios.py, which uses a different, in-process mock-object
convention of its own and legitimately expects core.llm's default,
non-mock IS_MOCK state).

USAGE -- add these two module-level functions to a test file that
calls /api/analyze and needs it to succeed (unittest auto-discovers
setUpModule/tearDownModule by name):

    from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env

    _ollama_patch = None

    def setUpModule():
        global _ollama_patch
        _ollama_patch = patch_ollama_env()

    def tearDownModule():
        unpatch_ollama_env(_ollama_patch)

Tests that specifically need to prove the genuinely-unreachable-Ollama
contract (AI_ENGINE_UNAVAILABLE itself) intentionally do NOT use this
helper -- see tests/test_ai_engine_unavailable.py.
"""

import threading
import urllib.error
import urllib.request

_LOCK = threading.Lock()
_STATE = {"host": None, "port": None}

_PATCHED_ATTRS = ("OLLAMA_HOST", "OLLAMA_MODEL", "ZX_LLM_MODE", "IS_MOCK")


def _already_listening(host, port):
    try:
        urllib.request.urlopen(f"http://{host}:{port}/api/version", timeout=0.5)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _ensure_server(host="127.0.0.1", preferred_port=11435):
    with _LOCK:
        if _STATE["port"] is not None:
            return _STATE["host"], _STATE["port"]

        from tools.mock_ollama_server_stdlib import start_server

        if _already_listening(host, preferred_port):
            # Another test process (or a manually-started mock server)
            # is already serving this port -- reuse it rather than
            # failing to bind.
            _STATE["host"], _STATE["port"] = host, preferred_port
            return host, preferred_port

        try:
            httpd, _thread = start_server(host=host, port=preferred_port)
            port = httpd.server_port
        except OSError:
            # Port already taken by something that isn't answering our
            # /api/version probe (rare) -- fall back to an OS-assigned
            # free port instead of failing the whole test run.
            httpd, _thread = start_server(host=host, port=0)
            port = httpd.server_port

        _STATE["host"], _STATE["port"] = host, port
        return host, port


def patch_ollama_env():
    """Point core.llm at the shared mock server. Returns an opaque
    "prior" snapshot -- pass it to unpatch_ollama_env() to restore
    exactly what was there before. Safe to call even if core.llm
    hasn't been imported by anyone yet (imports it itself)."""
    import core.llm as llm_module

    host, port = _ensure_server()
    target_host = llm_module._normalize_host(f"http://{host}:{port}")

    prior = {name: getattr(llm_module, name) for name in _PATCHED_ATTRS}

    llm_module.OLLAMA_HOST = target_host
    llm_module.OLLAMA_MODEL = "qwen3:4b"
    llm_module.ZX_LLM_MODE = "mock"
    llm_module.IS_MOCK = True

    # tools/mock_ollama_server_stdlib.py reads OLLAMA_MODEL once, at
    # ITS OWN import time, to decide the model name its /api/tags
    # response advertises -- keep it consistent regardless of import
    # order (harmless no-op if it already matches).
    from tools import mock_ollama_server_stdlib as mock_server_module
    mock_server_module.MOCK_MODEL_NAME = "qwen3:4b"

    return prior


def unpatch_ollama_env(prior):
    """Restore exactly what patch_ollama_env() overwrote. `prior` is
    the snapshot patch_ollama_env() returned -- never None."""
    if prior is None:
        return
    import core.llm as llm_module
    for name, value in prior.items():
        setattr(llm_module, name, value)
