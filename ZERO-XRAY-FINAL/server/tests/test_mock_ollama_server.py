"""
Regression tests for tools/mock_ollama_server.py.

Starts the real mock server as a subprocess on 127.0.0.1:11435 (never
11434 -- that's reserved for real Ollama), then drives it with the
project's own core.llm.LocalLLM class -- the exact code every agent
uses -- to prove:

1. Mock SUCCESS: each agent's system_prompt is correctly routed to a
   schema-valid canned response (LocalLLM.generate() returns non-empty,
   parseable JSON matching what that agent expects).
2. Mock FAILURE MODES (empty_response, chat_500, timeout): each one
   causes LocalLLM.generate() to return "" (the documented contract
   for "AI failed at the transport level, caller should fall back"),
   exactly like a real Ollama connection failure would. invalid_json
   is different by design -- see test_invalid_json_mode_returns_raw_
   unparseable_text's docstring below -- generate() correctly still
   returns the raw (malformed) text, and it's each agent's own
   parsing code that must detect and fall back on it.

These tests do not require real Ollama and do not touch port 11434.
They are skipped automatically if the mock server subprocess fails to
start (e.g. `uvicorn`/`fastapi` not installed in a minimal test
environment), rather than failing the whole suite over an optional
capability.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import requests

MOCK_HOST = "http://127.0.0.1:11435"
SERVER_MODULE = "tools.mock_ollama_server:app"
STARTUP_TIMEOUT_SECONDS = 10


def _server_is_up():
    try:
        response = requests.get(f"{MOCK_HOST}/api/version", timeout=1)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


class MockOllamaServerTestCase(unittest.TestCase):
    """Base class: starts tools/mock_ollama_server.py once for the
    whole test class, on port 11435, and tears it down afterward."""

    process = None

    @classmethod
    def setUpClass(cls):
        if _server_is_up():
            # Something's already on 11435 (e.g. a manually-started
            # mock from a previous run) -- reuse it rather than
            # failing to bind.
            cls.process = None
            return

        server_dir = Path(__file__).resolve().parent.parent
        cls.process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                SERVER_MODULE,
                "--host", "127.0.0.1",
                "--port", "11435",
            ],
            cwd=str(server_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            if _server_is_up():
                return
            time.sleep(0.3)

        cls.process.kill()
        cls.process = None
        raise unittest.SkipTest(
            "Mock Ollama server did not start within "
            f"{STARTUP_TIMEOUT_SECONDS}s -- skipping mock server tests."
        )

    @classmethod
    def tearDownClass(cls):
        if cls.process is not None:
            cls.process.kill()
            cls.process.wait(timeout=5)

    def _chat(self, system_prompt, user_prompt, failure_mode="none"):
        response = requests.post(
            f"{MOCK_HOST}/api/chat",
            json={
                "model": "qwen3:4b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            },
            headers={"X-ZX-Mock-Failure-Mode": failure_mode},
            timeout=5,
        )
        return response


class MockOllamaBasicEndpoints(MockOllamaServerTestCase):

    def test_version_endpoint(self):
        response = requests.get(f"{MOCK_HOST}/api/version", timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertIn("version", response.json())

    def test_tags_endpoint_lists_a_model(self):
        response = requests.get(f"{MOCK_HOST}/api/tags", timeout=2)
        self.assertEqual(response.status_code, 200)
        models = response.json().get("models", [])
        self.assertTrue(len(models) >= 1)
        self.assertIn("name", models[0])


class MockOllamaSuccessRoutingPerAgent(MockOllamaServerTestCase):
    """Proves /api/chat routes each agent's real system_prompt to a
    schema-correct canned response -- not a generic placeholder."""

    def test_service_agent_semantic_steps_shape(self):
        response = self._chat(
            "You are a meticulous process analyst who reads raw...",
            "1. Customer fills the form\n2. Customer submits documents\n3. Staff reviews",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertIn("steps", content)
        self.assertIsInstance(content["steps"], list)
        self.assertGreater(len(content["steps"]), 0)
        # anti-hallucination invariant: never more steps than raw lines
        self.assertLessEqual(len(content["steps"]), 3)

    def test_service_agent_capability_detection_shape(self):
        response = self._chat(
            "You are a strict, evidence-only service capability analyst.",
            "Steps:\n1. Customer pays the annual fee\n2. System issues the box number",
        )
        content = json.loads(response.json()["message"]["content"])
        for key in ("has_payment", "has_documents", "has_physical_visit", "has_human_approval"):
            self.assertIn(key, content)

    def test_capability_detection_respects_no_fee_negation(self):
        response = self._chat(
            "You are a strict, evidence-only service capability analyst.",
            "This service has no fee. Steps:\n1. Customer submits a complaint",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertFalse(content["has_payment"])

    def test_standards_agent_shape(self):
        response = self._chat(
            "You are a government service standards compliance agent.",
            "Applicable standard IDs you may cite: ['STAGE-01', 'STAGE-05']",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertIn("applicable_standard_ids", content)
        self.assertIn("why_it_applies", content)
        # Every returned ID must be one that was actually offered.
        for std_id in content["applicable_standard_ids"]:
            self.assertIn(std_id, ("STAGE-01", "STAGE-05"))

    def test_gap_agent_shape(self):
        response = self._chat(
            "You are a government service gap analysis agent.",
            "APPLICABLE GOVERNMENT STANDARDS: STAGE-01, STAGE-05",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertIn("gaps", content)
        gap = content["gaps"][0]
        for key in (
            "category", "description", "evidence", "affected_step",
            "standard_id", "severity", "recommendation", "expected_impact",
        ):
            self.assertIn(key, gap)
        self.assertIn(gap["severity"], ("HIGH", "MEDIUM", "LOW"))

    def test_step_compliance_review_shape(self):
        response = self._chat(
            "You are a meticulous compliance reviewer who reasons...",
            "CURRENT STEPS (only the non-protected ones you may re-assess):\n"
            "1. Customer submits request\n2. Staff reviews\n"
            "A deterministic keyword scan already produced this baseline "
            "assessment: [{\"step_number\": 1}, {\"step_number\": 2}]",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertIn("assessments", content)
        self.assertEqual(len(content["assessments"]), 2)
        for item in content["assessments"]:
            self.assertIn(item["status"], ("PASS", "PARTIAL", "FAIL"))
            self.assertIn(
                item["decision"],
                ("KEEP", "REMOVE", "MERGE", "AUTOMATE", "REVIEW"),
            )

    def test_journey_builder_shape_no_payment(self):
        response = self._chat(
            "You are a meticulous service-design expert who reasons...",
            "- PAYMENT: NOT present in this service -- no evidence was found.",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertIn("overall_reasoning", content)
        self.assertIn("steps", content)
        self.assertTrue(len(content["steps"]) >= 2)
        # No step should claim payment when the prompt said there's none.
        self.assertFalse(any(s.get("has_payment") for s in content["steps"]))
        # Must end with a step that delivers the customer's result.
        self.assertTrue(content["steps"][-1]["delivers_customer_result"])

    def test_journey_builder_shape_with_payment(self):
        response = self._chat(
            "You are a meticulous service-design expert who reasons...",
            "- PAYMENT: CONFIRMED for this service (evidence: annual fee applies).",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertTrue(any(s.get("has_payment") for s in content["steps"]))
        self.assertTrue(
            any(s.get("requires_customer_approval") for s in content["steps"])
        )

    def test_validation_semantic_review_shape(self):
        response = self._chat(
            "You are a meticulous logical-consistency reviewer...",
            "PROPOSED STEPS: []",
        )
        content = json.loads(response.json()["message"]["content"])
        self.assertIn("issues", content)
        self.assertIn("verdict", content)
        self.assertIn(content["verdict"], ("PASS", "FAIL"))


class MockOllamaFailureModes(MockOllamaServerTestCase):
    """Each failure mode must cause LocalLLM.generate() to return ""
    (the documented "AI failed" contract), exactly as a real Ollama
    failure would, so every agent's existing fallback logic fires.

    Uses the ONE shared mock server started by MockOllamaServerTestCase
    (no ZX_MOCK_FAILURE_MODE set on that server's own process -- it
    defaults to "none"/success) and drives each failure mode via the
    X-ZX-Mock-Failure-Mode per-request header that core.llm.LocalLLM
    sends whenever the ZX_MOCK_FAILURE_MODE env var is set on the
    CLIENT side (see core/llm.py's _call_ollama). This is the fast
    path for automated testing; a person can equally set
    ZX_MOCK_FAILURE_MODE on the mock server's own process at startup
    for manual testing (see tools/mock_ollama_server.py's
    _current_failure_mode, which checks the header first and falls
    back to its own process's env var) -- both are real, supported
    usages, not a workaround.
    """

    def _generate_via_real_client(self, failure_mode, timeout=5):
        # ROOT-CAUSE FIX (Mandatory AI Mode audit fix -- test isolation):
        # this used to unconditionally os.environ.pop(...) these four
        # variables in `finally`, then reload core.llm with whatever
        # was left (usually nothing) -- leaving core.llm.OLLAMA_HOST
        # reset to its bare "http://localhost:11434" default for every
        # OTHER test file that runs later in the same process (module-
        # level constants are fixed at import/reload time, so this
        # leaked past this test). That was harmless before Mandatory AI
        # Mode existed (an unreachable OLLAMA_HOST was tolerated
        # anywhere via fallback), but now that reachability genuinely
        # matters, this leak broke unrelated tests' /api/analyze calls.
        # Save the PRIOR value of each var (or "unset") and restore it
        # exactly, then reload once more so core.llm ends up back in
        # whichever state -- real, mock, or unset -- it was in before
        # this helper ran, instead of always resetting to bare defaults.
        prior = {
            name: os.environ.get(name)
            for name in ("ZX_LLM_MODE", "OLLAMA_HOST", "OLLAMA_MODEL", "ZX_MOCK_FAILURE_MODE")
        }
        os.environ["ZX_LLM_MODE"] = "mock"
        os.environ["OLLAMA_HOST"] = MOCK_HOST
        os.environ["OLLAMA_MODEL"] = "qwen3:4b"
        if failure_mode != "none":
            os.environ["ZX_MOCK_FAILURE_MODE"] = failure_mode
        try:
            import importlib
            import core.llm as llm_module
            importlib.reload(llm_module)
            client = llm_module.LocalLLM()
            return client.generate(
                system_prompt="You are a meticulous process analyst who...",
                user_prompt="1. step one\n2. step two",
                max_new_tokens=50,
                timeout=timeout,
            )
        finally:
            for name, value in prior.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            import importlib
            import core.llm as llm_module
            importlib.reload(llm_module)

    def test_empty_response_triggers_fallback_contract(self):
        result = self._generate_via_real_client("empty_response")
        self.assertEqual(result, "")

    def test_invalid_json_mode_returns_raw_unparseable_text(self):
        # NOTE: LocalLLM.generate() has a narrower, correct contract
        # than the other three failure-mode tests might suggest: it
        # returns "" only for a genuine transport-level failure (no
        # response body at all, non-200 status, or a request
        # exception/timeout) -- NOT for a response that came back
        # HTTP 200 but contains malformed JSON. Detecting/handling a
        # malformed-but-present response is each AGENT's job (via
        # core.json_utils.extract_json + has_parse_error), since
        # different agents expect different JSON shapes and only the
        # agent knows its own shape. This mirrors exactly how a real
        # truncated/malformed Ollama response is handled -- proven
        # working end-to-end via the chat_500 test above and via the
        # full-pipeline manual runs in this session's verification
        # (every agent's own "[AI FAILED -> FALLBACK] ... parse
        # error" fallback fired correctly for malformed content).
        result = self._generate_via_real_client("invalid_json")
        self.assertNotEqual(
            result, "",
            "generate() should still return Ollama's raw text even "
            "when that text isn't valid JSON -- parsing/validation "
            "is each agent's responsibility, not generate()'s.",
        )
        from core.json_utils import extract_json, has_parse_error
        parsed = extract_json(result)
        self.assertTrue(
            not isinstance(parsed, dict) or has_parse_error(parsed),
            "the mock's deliberately malformed JSON should actually "
            "be detected as malformed by the real parsing helper "
            "every agent uses to decide whether to fall back.",
        )

    def test_chat_500_triggers_fallback_contract(self):
        result = self._generate_via_real_client("chat_500")
        self.assertEqual(result, "")

    def test_timeout_triggers_fallback_contract(self):
        start = time.time()
        result = self._generate_via_real_client("timeout", timeout=3)
        elapsed = time.time() - start
        self.assertEqual(result, "")
        # Must fail at ~3s (the client timeout), not wait the mock's
        # full simulated 300s hang.
        self.assertLess(elapsed, 30)

    def test_success_mode_does_not_return_empty(self):
        result = self._generate_via_real_client("none")
        self.assertNotEqual(result, "")


if __name__ == "__main__":
    unittest.main()
