"""Dedicated tests for Mandatory AI Mode (REQUIRE_OLLAMA -- Ollama
availability audit fix): core/llm.py's centralized, cached
LocalLLM.check_available() / AIEngineUnavailableError, and main.py's
/api/analyze preflight gate + mid-run abort.

Deliberately does NOT use tools/test_mock_env.py's module-scoped
patch for the whole file -- unlike test_api_endpoints.py and the other
migrated files (which need /api/analyze to always succeed as a
fixture for unrelated functionality), THIS file's entire point is to
exercise both the unavailable AND the available paths, on purpose, so
each test applies (and cleans up) exactly the Ollama state it needs.

Covers:
  1. Ollama available -> Analyze works.
  2. Ollama unreachable -> immediate 503 AI_ENGINE_UNAVAILABLE, no
     retry loop, nothing saved.
  3. Ollama reachable but the configured model is missing -> a clear,
     distinct AI_ENGINE_UNAVAILABLE error (not confused with #2).
  4. Ollama available at the preflight check but fails DURING the
     pipeline -> the run is discarded, never saved as a successful
     analysis.
  5. check_available()/generate() use one centralized, cached check --
     no repeated network attempts once unavailability is known.
  6. REQUIRE_OLLAMA defaults to True (Mandatory AI Mode is the
     default).
  7. Deterministic Future Engine operations (Predict, Simulate AUTO)
     are NOT gated by Ollama availability -- confirms this fix did not
     touch that unrelated, already-deterministic logic.
"""

import os
import time
import unittest

os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:19999")  # deliberately unreachable by default
os.environ.setdefault("ZX_LLM_MODE", "ollama")

import core.llm as llm_module
from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env


class RequireOllamaDefaultTestCase(unittest.TestCase):
    """Mandatory AI Mode must be the default -- no env var needed."""

    def test_require_ollama_defaults_to_true(self):
        self.assertTrue(llm_module.REQUIRE_OLLAMA)

    def test_ai_engine_unavailable_error_has_stable_code(self):
        error = llm_module.AIEngineUnavailableError("some reason")
        self.assertEqual(error.code, "AI_ENGINE_UNAVAILABLE")
        self.assertIn("AI_ENGINE_UNAVAILABLE", str(error))


class CheckAvailableUnitTestCase(unittest.TestCase):
    """Pure unit tests against LocalLLM.check_available() -- no HTTP
    server for the "unreachable" cases, the real stdlib mock server
    for the "reachable" cases. No TestClient/main.py involved."""

    def setUp(self):
        self._prior = {
            name: getattr(llm_module, name)
            for name in ("OLLAMA_HOST", "OLLAMA_MODEL", "ZX_LLM_MODE", "IS_MOCK")
        }

    def tearDown(self):
        for name, value in self._prior.items():
            setattr(llm_module, name, value)

    def test_unreachable_host_is_unavailable_with_reason(self):
        llm_module.OLLAMA_HOST = "http://127.0.0.1:19998"  # nothing listens here
        client = llm_module.LocalLLM.__new__(llm_module.LocalLLM)
        client._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
        client._connectivity_failure_this_run = False

        available, reason = client.check_available(force=True)
        self.assertFalse(available)
        self.assertIsNotNone(reason)
        self.assertIn("127.0.0.1:19998", reason)

    def test_reachable_host_missing_configured_model_is_unavailable(self):
        prior_patch = patch_ollama_env()  # points at the real, reachable mock server
        try:
            llm_module.OLLAMA_MODEL = "a-model-nobody-pulled"
            client = llm_module.LocalLLM.__new__(llm_module.LocalLLM)
            client._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
            client._connectivity_failure_this_run = False

            available, reason = client.check_available(force=True)
            self.assertFalse(available)
            self.assertIn("a-model-nobody-pulled", reason)
            self.assertIn("not found", reason)
        finally:
            unpatch_ollama_env(prior_patch)

    def test_reachable_host_with_configured_model_is_available(self):
        prior_patch = patch_ollama_env()
        try:
            client = llm_module.LocalLLM.__new__(llm_module.LocalLLM)
            client._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
            client._connectivity_failure_this_run = False

            available, reason = client.check_available(force=True)
            self.assertTrue(available)
            self.assertIsNone(reason)
        finally:
            unpatch_ollama_env(prior_patch)

    def test_check_available_result_is_cached_no_repeated_network_calls(self):
        llm_module.OLLAMA_HOST = "http://127.0.0.1:19998"
        client = llm_module.LocalLLM.__new__(llm_module.LocalLLM)
        client._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
        client._connectivity_failure_this_run = False

        call_count = {"n": 0}
        real_get = llm_module.requests.get

        def counting_get(*args, **kwargs):
            call_count["n"] += 1
            return real_get(*args, **kwargs)

        llm_module.requests.get = counting_get
        try:
            client.check_available(force=True)  # 1st real network attempt
            client.check_available()             # cached -- must NOT hit the network again
            client.check_available()             # still cached
            self.assertEqual(call_count["n"], 1)
        finally:
            llm_module.requests.get = real_get

    def test_generate_skips_network_call_once_known_unavailable(self):
        llm_module.OLLAMA_HOST = "http://127.0.0.1:19998"
        client = llm_module.LocalLLM.__new__(llm_module.LocalLLM)
        client._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
        client._connectivity_failure_this_run = False
        client.check_available(force=True)  # populates the cache as unavailable

        post_call_count = {"n": 0}
        real_post = llm_module.requests.post

        def counting_post(*args, **kwargs):
            post_call_count["n"] += 1
            return real_post(*args, **kwargs)

        llm_module.requests.post = counting_post
        try:
            started = time.monotonic()
            result = client.generate("system", "user", max_new_tokens=10, timeout=5)
            elapsed = time.monotonic() - started
        finally:
            llm_module.requests.post = real_post

        self.assertEqual(result, "")
        self.assertEqual(post_call_count["n"], 0)  # no wasted network attempt at all
        self.assertLess(elapsed, 1.0)  # short-circuited, not a real 5s timeout


class AnalyzeEndpointMandatoryAITestCase(unittest.TestCase):
    """Endpoint-level tests through the real FastAPI app. Left in its
    default (unreachable-Ollama) state by design; individual tests
    apply patch_ollama_env()/unpatch_ollama_env() around themselves
    when they specifically need the available path."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import main as main_module

        main_module.startup()
        cls.main_module = main_module
        cls.client = TestClient(main_module.app)

        import uuid
        suffix = uuid.uuid4().hex[:8]
        tenant = main_module.tenant_repository.create_tenant(
            f"AI Unavailable Test Tenant {suffix}", f"ai-unavailable-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "AI Unavailable Test Admin", f"ai-unavailable-{suffix}@test.local",
            role="entity_admin",
        )
        login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": user["email"], "credential": "zxr-demo-2026"},
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

    def _analyze_payload(self, name="AI Gate Test Service"):
        return {
            "service_name": name,
            "description": "A service used only to exercise the Mandatory AI Mode gate.",
            "steps": ["Customer submits a request", "Staff reviews the request", "System issues the result"],
            "lang": "en",
        }

    def _reset_orchestrator_cache(self):
        # The orchestrator's LocalLLM instance is a long-lived
        # singleton (constructed once in setUpClass) with its own
        # cached availability state -- patch_ollama_env() changes the
        # core.llm MODULE's OLLAMA_HOST/etc, but doesn't know about
        # that instance's already-populated cache from setUpClass (or
        # an earlier test in this class). Force a fresh check against
        # whatever is currently patched, exactly like a real cache-TTL
        # expiry would eventually do on its own.
        self.main_module.orchestrator.llm._availability_cache = {
            "available": None, "reason": None, "checked_at": 0.0,
        }

    # --- 1. Ollama available -> Analyze works ----------------------------
    def test_ollama_available_analyze_succeeds(self):
        prior = patch_ollama_env()
        self._reset_orchestrator_cache()
        try:
            response = self.client.post(
                "/api/analyze", headers=self.headers, json=self._analyze_payload("Available Path Service")
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertIn("service_id", body)
            self.assertIn("analysis_id", body)
        finally:
            unpatch_ollama_env(prior)
            self._reset_orchestrator_cache()

    # --- 2. Ollama unreachable -> immediate 503 AI_ENGINE_UNAVAILABLE ----
    def test_ollama_unreachable_returns_immediate_503(self):
        before = self.main_module.service_store.list_services_for_tenant(self.tenant_id)

        started = time.monotonic()
        response = self.client.post(
            "/api/analyze", headers=self.headers, json=self._analyze_payload("Unreachable Path Service")
        )
        elapsed = time.monotonic() - started

        self.assertEqual(response.status_code, 503)
        self.assertIn("AI_ENGINE_UNAVAILABLE", response.json()["detail"])
        # A single short reachability check, not a long hang.
        self.assertLess(elapsed, 5.0)

        after = self.main_module.service_store.list_services_for_tenant(self.tenant_id)
        self.assertEqual(len(after), len(before))  # nothing was created

    # --- 3. Configured model missing -> clear, distinct error ------------
    def test_configured_model_missing_returns_503_with_model_reason(self):
        prior = patch_ollama_env()  # reachable host...
        llm_module.OLLAMA_MODEL = "a-model-nobody-pulled"  # ...but wrong model
        self._reset_orchestrator_cache()
        try:
            response = self.client.post(
                "/api/analyze", headers=self.headers, json=self._analyze_payload("Missing Model Service")
            )
            self.assertEqual(response.status_code, 503)
            detail = response.json()["detail"]
            self.assertIn("AI_ENGINE_UNAVAILABLE", detail)
            self.assertIn("a-model-nobody-pulled", detail)
        finally:
            unpatch_ollama_env(prior)
            self._reset_orchestrator_cache()

    # --- 4. Fails mid-operation -> not saved as successful ----------------
    def test_ollama_failing_mid_analysis_is_not_saved(self):
        prior = patch_ollama_env()  # available at preflight (GET /api/tags unaffected)
        self._reset_orchestrator_cache()
        before = self.main_module.service_store.list_services_for_tenant(self.tenant_id)
        os.environ["ZX_MOCK_FAILURE_MODE"] = "chat_500"  # every POST /api/chat now 500s
        try:
            response = self.client.post(
                "/api/analyze", headers=self.headers, json=self._analyze_payload("Mid Run Failure Service")
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("AI_ENGINE_UNAVAILABLE", response.json()["detail"])
            self.assertIn("discarded", response.json()["detail"])
        finally:
            os.environ.pop("ZX_MOCK_FAILURE_MODE", None)
            unpatch_ollama_env(prior)
            self._reset_orchestrator_cache()

        after = self.main_module.service_store.list_services_for_tenant(self.tenant_id)
        self.assertEqual(len(after), len(before))  # no partial/incomplete record persisted

    # --- 5. No repeated retries/timeouts once known unavailable ----------
    def test_repeated_analyze_calls_while_unavailable_do_not_each_hang(self):
        first_started = time.monotonic()
        first = self.client.post(
            "/api/analyze", headers=self.headers, json=self._analyze_payload("Repeat Call Service 1")
        )
        first_elapsed = time.monotonic() - first_started
        self.assertEqual(first.status_code, 503)

        second_started = time.monotonic()
        second = self.client.post(
            "/api/analyze", headers=self.headers, json=self._analyze_payload("Repeat Call Service 2")
        )
        second_elapsed = time.monotonic() - second_started
        self.assertEqual(second.status_code, 503)

        # The second call reuses the cached availability result instead
        # of repeating its own full reachability check.
        self.assertLess(second_elapsed, first_elapsed + 1.0)
        self.assertLess(second_elapsed, 5.0)


class DeterministicFutureEngineUnaffectedTestCase(unittest.TestCase):
    """Requirement: Predict / Simulate AUTO stay available regardless
    of Ollama, since their scoring is fully deterministic Python, not
    AI-dependent -- this fix must not have gated them. Builds its
    fixture directly via service_store (no /api/analyze call needed),
    so it works correctly with Ollama left unreachable."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import main as main_module

        main_module.startup()
        cls.main_module = main_module
        cls.client = TestClient(main_module.app)

        import uuid
        suffix = uuid.uuid4().hex[:8]
        tenant = main_module.tenant_repository.create_tenant(
            f"Deterministic Test Tenant {suffix}", f"deterministic-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Deterministic Test Admin", f"deterministic-{suffix}@test.local",
            role="entity_admin",
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

        service = main_module.service_store.create_service(
            tenant_id=cls.tenant_id, service_name="Deterministic Fixture Service"
        )
        main_module.service_store.create_analysis(
            tenant_id=cls.tenant_id, service_id=service["id"], blueprint_id="bp-deterministic",
            result={
                "redesign": {
                    "future_steps": [
                        {"step_number": 1, "name": "Customer submits request", "type": "CUSTOMER"},
                        {"step_number": 2, "name": "System processes request", "type": "SYSTEM"},
                    ],
                    "required_integrations": ["Payment Gateway"],
                },
            },
        )
        cls.service_id = service["id"]

    def test_predict_is_not_gated_by_ollama_availability(self):
        response = self.client.post(f"/api/services/{self.service_id}/predict", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    def test_simulate_auto_is_not_gated_by_ollama_availability(self):
        response = self.client.post(
            f"/api/services/{self.service_id}/scenarios",
            headers=self.headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("auto_scenarios", body)
        self.assertGreater(len(body["auto_scenarios"]), 0)
        # AI unavailable -> every description must be honestly labeled
        # template, never falsely "ai".
        for item in body["auto_scenarios"]:
            for outcome in item.get("possible_outcomes", []):
                self.assertEqual(outcome["description_source"], "template")


if __name__ == "__main__":
    unittest.main()
