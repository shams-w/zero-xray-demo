"""
Backend API integration test -- exercises the real FastAPI app end to
end via TestClient (no mocked routes, no monkeypatching of main.py):
/api/health, /api/analyze, blueprint creation/retrieval/approve/
publish, customer registration, journey creation/retrieval/edit/
approve, payment-assessment/payment, execution, journey events,
pause/cancel/handoff.

Runs against the repo's stdlib mock Ollama server (see
tools/test_mock_env.py) rather than a real model -- this file's job is
to prove the API CONTRACTS -- field names, required-field presence,
HTTP status codes, state transitions -- hold, using a real, reachable
AI engine so /api/analyze (gated by Mandatory AI Mode / REQUIRE_OLLAMA)
actually completes. The AI-path-specific behavior (MOCK_AI labeling,
zero fallback on mock success, [AI FAILED -> FALLBACK] on genuine
failure, and the AI_ENGINE_UNAVAILABLE contract itself) is covered
separately by tests/test_mock_ollama_server.py and
tests/test_ai_engine_unavailable.py.
"""

import os
import unittest

from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env

# Mandatory AI Mode audit fix: this file exercises /api/analyze only as a
# fixture for UNRELATED functionality, so it needs a completed analysis --
# point core.llm at the repo's real, reachable stdlib mock Ollama server for
# the duration of THIS module's tests only (never a deliberately unreachable
# host), then restore whatever was there before. See tools/test_mock_env.py
# for why this is scoped via setUpModule/tearDownModule rather than a plain
# module-level call.
_ollama_patch = None


def setUpModule():
    global _ollama_patch
    _ollama_patch = patch_ollama_env()


def tearDownModule():
    unpatch_ollama_env(_ollama_patch)

from fastapi.testclient import TestClient

import main as main_module


class ApiEndpointsTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        # /api/analyze and /api/blueprints/* now require a strict,
        # authenticated tenant context (soft/anonymous fallback was
        # removed) -- this test file exercises the API CONTRACT, so it
        # authenticates like any real tenant staff caller would rather
        # than relying on the anonymous fallback that used to exist.
        import uuid
        suffix = uuid.uuid4().hex[:8]
        tenant = main_module.tenant_repository.create_tenant(
            f"API Test Tenant {suffix}", f"api-test-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "API Test Admin", f"api-test-{suffix}@test.local", role="entity_admin"
        )
        login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": user["email"], "credential": "zxr-demo-2026"},
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    def test_root_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def _analyze_a_service(self):
        response = self.client.post("/api/analyze", json={
            "service_name": "API Integration Test Service",
            "description": "A service used only to exercise the API contract.",
            "steps": [
                "Customer submits a request",
                "Staff reviews the request",
                "System issues the result",
            ],
            "lang": "en",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_analyze_returns_all_required_top_level_sections(self):
        result = self._analyze_a_service()
        for key in (
            "service_analysis", "relevant_standards", "gaps",
            "zero_bureaucracy_findings", "redesign", "simulation",
            "validation", "metrics", "blueprint_id", "blueprint_status",
        ):
            self.assertIn(key, result, f"/api/analyze response missing '{key}'")

    def test_analyze_preserves_semantic_and_audit_fields(self):
        result = self._analyze_a_service()
        service_analysis = result["service_analysis"]
        for key in (
            "steps", "raw_steps", "steps_analysis_source",
            "analysis_source", "capabilities",
        ):
            self.assertIn(
                key, service_analysis,
                f"service_analysis missing semantic/audit field '{key}'",
            )
        redesign = result["redesign"]
        self.assertIn("future_steps", redesign)
        self.assertIn("analysis_source", redesign)

    def test_analyze_does_not_invent_capabilities_for_plain_request(self):
        result = self._analyze_a_service()
        capabilities = result["service_analysis"]["capabilities"]
        self.assertFalse(capabilities["has_payment"])

    # -----------------------------------------------------------
    # Blueprint lifecycle
    # -----------------------------------------------------------

    def test_blueprint_creation_retrieval_approve_publish(self):
        analyzed = self._analyze_a_service()
        blueprint_id = analyzed["blueprint_id"]
        self.assertEqual(analyzed["blueprint_status"], "DRAFT")

        get_response = self.client.get(f"/api/blueprints/{blueprint_id}", headers=self.headers)
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["id"], blueprint_id)

        approve_response = self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=self.headers)
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["status"], "APPROVED")

        publish_response = self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=self.headers)
        self.assertEqual(publish_response.status_code, 200)
        self.assertEqual(publish_response.json()["status"], "PUBLISHED")

    def test_blueprint_not_found_returns_404(self):
        response = self.client.get("/api/blueprints/does-not-exist", headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_publish_without_approval_is_rejected(self):
        analyzed = self._analyze_a_service()
        blueprint_id = analyzed["blueprint_id"]
        response = self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=self.headers)
        self.assertNotEqual(response.status_code, 200)

    # -----------------------------------------------------------
    # Customer registration + full journey lifecycle
    # -----------------------------------------------------------

    def _register_customer(self, blueprint_id=None):
        # /api/sandbox/register derives the customer's tenant server-side
        # from blueprint_id (anonymous callers only accept a PUBLISHED
        # Blueprint -- see main.py's register_customer). Passing it here
        # matches the real frontend, which always includes blueprint_id
        # (see client/src/components/LiveAgentPage.jsx's handleRegister),
        # so the customer lands in the SAME tenant as the journey's
        # Blueprint instead of an unrelated default tenant.
        payload = {"name": "API Test Customer", "email": "api-test@example.com"}
        if blueprint_id:
            payload["blueprint_id"] = blueprint_id
        response = self.client.post("/api/sandbox/register", json=payload)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _published_blueprint_id(self):
        analyzed = self._analyze_a_service()
        blueprint_id = analyzed["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=self.headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=self.headers)
        return blueprint_id

    def test_customer_registration_required_fields(self):
        response = self.client.post("/api/sandbox/register", json={
            "name": "", "email": "",
        })
        self.assertEqual(response.status_code, 422)

    def test_full_journey_lifecycle(self):
        blueprint_id = self._published_blueprint_id()
        customer = self._register_customer(blueprint_id)
        customer_id = customer.get("id") or customer.get("customer_id")
        self.assertIsNotNone(customer_id)

        create_response = self.client.post("/api/journeys", json={
            "customer_id": customer_id,
            "intent": "I need this service completed.",
            "blueprint_id": blueprint_id,
            "lang": "en",
            "sandbox": True,
        })
        self.assertEqual(create_response.status_code, 200)
        journey = create_response.json()
        journey_id = journey["id"]

        get_response = self.client.get(f"/api/journeys/{journey_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["id"], journey_id)

        edit_response = self.client.post(
            f"/api/journeys/{journey_id}/edit",
            json={"instruction": "Please proceed as planned.", "selections": None},
        )
        self.assertEqual(edit_response.status_code, 200)

        approve_response = self.client.post(f"/api/journeys/{journey_id}/approve")
        self.assertEqual(approve_response.status_code, 200)
        plan = approve_response.json().get("plan", {})
        requires_payment = bool(plan.get("requires_payment"))
        payment_timing = plan.get("payment_timing", "BEFORE_EXECUTION")

        # prepare_payment_assessment is deliberately conditional business
        # logic (core/runtime_store.py): it only applies to services with
        # a genuinely deferred (AFTER_EXECUTION) payment, e.g. a
        # weight-based shipment quote. Calling it for a service that
        # doesn't need one is CORRECTLY rejected with 409 -- not a bug --
        # so only assert success when the plan actually calls for it.
        if requires_payment and payment_timing == "AFTER_EXECUTION":
            assessment_response = self.client.post(
                f"/api/journeys/{journey_id}/payment-assessment"
            )
            self.assertEqual(assessment_response.status_code, 200)

        if requires_payment:
            payment_response = self.client.post(
                f"/api/journeys/{journey_id}/payment",
                json={"payment_method": "SANDBOX_CARD", "approved": True},
            )
            self.assertEqual(payment_response.status_code, 200)

        execute_response = self.client.post(f"/api/journeys/{journey_id}/execute")
        self.assertEqual(execute_response.status_code, 200)

        events_response = self.client.get(f"/api/journeys/{journey_id}/events")
        self.assertEqual(events_response.status_code, 200)

    def test_journey_not_found_returns_403(self):
        # An unauthenticated caller with no valid journey-capability cookie
        # gets the same 403 "Journey session is invalid or expired" for a
        # nonexistent journey as for one it simply isn't authorized to see
        # (main.py's _customer_journey_or_403) -- this deliberately never
        # confirms or denies that a given journey ID exists.
        response = self.client.get("/api/journeys/does-not-exist")
        self.assertEqual(response.status_code, 403)

    def test_live_execution_disabled_without_sandbox_flag(self):
        customer = self._register_customer()
        customer_id = customer.get("id") or customer.get("customer_id")
        response = self.client.post("/api/journeys", json={
            "customer_id": customer_id,
            "intent": "Try live execution.",
            "sandbox": False,
        })
        self.assertEqual(response.status_code, 409)

    def test_pause_cancel_handoff_actions(self):
        blueprint_id = self._published_blueprint_id()
        customer = self._register_customer(blueprint_id)
        customer_id = customer.get("id") or customer.get("customer_id")

        for action, expected_state in (
            ("pause", "PAUSED"),
            ("cancel", "CANCELLED"),
            ("handoff", "HUMAN_HANDOFF"),
        ):
            create_response = self.client.post("/api/journeys", json={
                "customer_id": customer_id,
                "intent": f"Testing {action} action.",
                "blueprint_id": blueprint_id,
                "lang": "en",
                "sandbox": True,
            })
            journey_id = create_response.json()["id"]

            action_response = self.client.post(f"/api/journeys/{journey_id}/{action}")
            self.assertEqual(action_response.status_code, 200)
            self.assertEqual(action_response.json()["state"], expected_state)

    def test_unknown_journey_action_returns_404(self):
        blueprint_id = self._published_blueprint_id()
        customer = self._register_customer(blueprint_id)
        customer_id = customer.get("id") or customer.get("customer_id")
        create_response = self.client.post("/api/journeys", json={
            "customer_id": customer_id,
            "intent": "Testing an invalid action.",
            "blueprint_id": blueprint_id,
            "lang": "en",
            "sandbox": True,
        })
        journey_id = create_response.json()["id"]
        response = self.client.post(f"/api/journeys/{journey_id}/not-a-real-action")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
