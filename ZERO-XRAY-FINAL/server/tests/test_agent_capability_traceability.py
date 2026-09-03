"""Phase 4 focused tests: concise, structured, audit-friendly decision
traceability on `agent_capability_map.step_capability_mapping`
(core/agent_capability_mapper.py::map_future_steps_to_capabilities).

Part 1 -- pure unit tests (no server, no Ollama): every required reason/
matched-integration/sandbox/NOT_CONNECTED-safety behavior, no secret or
chain-of-thought-like fields, no input mutation, existing Phase 2/3
semantics unchanged.

Part 2 -- a live API test confirming the traceability fields reach
`/api/analyze`, that tenant/Service-Owner isolation is unaffected, and
that the public anonymous Agent payload still never exposes
`agent_capability_map` (traceability included).
"""

import unittest
import uuid

from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env

_ollama_patch = None


def setUpModule():
    global _ollama_patch
    _ollama_patch = patch_ollama_env()


def tearDownModule():
    unpatch_ollama_env(_ollama_patch)


from fastapi.testclient import TestClient

import main as main_module
from core.agent_capability_mapper import (
    build_agent_capability_map,
    build_capability_summary,
    build_integration_capabilities,
    map_future_steps_to_capabilities,
)


# Fields that must never appear anywhere in a traceability entry, however
# it is serialized -- credentials, secrets, or anything resembling
# model chain-of-thought/internal deliberation.
_FORBIDDEN_SUBSTRINGS = (
    "secret_reference", "secret-reference", "api_key", "apikey",
    "authorization", "token", "config\":", "chain_of_thought",
    "the model thought", "internal deliberation",
)


class StepTraceabilityUnitTestCase(unittest.TestCase):
    def test_automate_step_includes_concise_reason(self):
        future_steps = [{"step_number": 1, "name": "Verify driving licence", "type": "SYSTEM",
                          "action": "Call licence verification", "change_type": "AUTOMATED"}]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Licence Verification", "type": "GOVERNMENT_API", "status": "CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        entry = mapping[0]
        self.assertEqual(entry["capability_status"], "AUTOMATE")
        self.assertIn("reason", entry)
        self.assertIsInstance(entry["reason"], str)
        self.assertLess(len(entry["reason"]), 200)  # concise, not a narrative
        self.assertIn("Licence Verification", entry["reason"])

    def test_automate_step_includes_safe_matched_integration_metadata(self):
        future_steps = [{"step_number": 1, "name": "Verify driving licence", "type": "SYSTEM",
                          "action": "Call licence verification", "change_type": "AUTOMATED"}]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Licence Verification", "type": "GOVERNMENT_API",
             "status": "CONNECTED", "secret_reference": "vault://leak", "config": {"api_key": "leak"}}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        matched = mapping[0]["mapped_integration"]
        self.assertEqual(matched["id"], "int-1")
        self.assertEqual(matched["name"], "Licence Verification")
        self.assertEqual(matched["status"], "CONNECTED")
        self.assertFalse(matched["sandbox"])
        self.assertNotIn("secret_reference", matched)
        self.assertNotIn("config", matched)

    def test_sandbox_match_is_clearly_identifiable(self):
        future_steps = [{"step_number": 1, "name": "Authorize Payment Gateway charge", "type": "SYSTEM",
                          "action": "", "change_type": "AUTOMATED"}]
        integrations = build_integration_capabilities([
            {"id": "int-2", "name": "Payment Gateway", "type": "PAYMENT_GATEWAY", "status": "SANDBOX"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        entry = mapping[0]
        self.assertEqual(entry["capability_status"], "AUTOMATE")
        self.assertTrue(entry["mapped_integration"]["sandbox"])
        self.assertEqual(entry["mapped_integration"]["status"], "SANDBOX")
        self.assertIn("SANDBOX", entry["reason"])

    def test_not_connected_integration_never_returned_as_matched(self):
        future_steps = [{"step_number": 1, "name": "Retrieve Document Store record", "type": "SYSTEM",
                          "action": "", "change_type": "AUTOMATED"}]
        integrations = build_integration_capabilities([
            {"id": "int-3", "name": "Document Store", "type": "DOCUMENT_MANAGEMENT", "status": "NOT_CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        entry = mapping[0]
        self.assertEqual(entry["capability_status"], "INTEGRATION_REQUIRED")
        self.assertIsNone(entry["mapped_integration"])
        # Optional traceability aid may point at the unavailable match,
        # but must never claim it as executable/matched.
        if entry.get("unavailable_integration_match"):
            self.assertEqual(entry["unavailable_integration_match"]["status"], "NOT_CONNECTED")

    def test_system_step_without_api_gives_integration_required_with_reason(self):
        future_steps = [{"step_number": 1, "name": "Some unmatched step", "type": "SYSTEM",
                          "action": "", "change_type": "AUTOMATED"}]
        mapping = map_future_steps_to_capabilities(future_steps, [])
        entry = mapping[0]
        self.assertEqual(entry["capability_status"], "INTEGRATION_REQUIRED")
        self.assertIn("reason", entry)
        self.assertIsInstance(entry["reason"], str)
        self.assertTrue(len(entry["reason"]) > 0)

    def test_customer_step_includes_customer_interaction_reason(self):
        future_steps = [{"step_number": 1, "name": "Customer uploads photo", "type": "CUSTOMER",
                          "change_type": "KEPT"}]
        mapping = map_future_steps_to_capabilities(future_steps, [])
        entry = mapping[0]
        self.assertEqual(entry["capability_status"], "NOT_APPLICABLE")
        self.assertIn("customer", entry["reason"].lower())

    def test_human_step_includes_manual_human_reason(self):
        future_steps = [{"step_number": 1, "name": "Committee review", "type": "HUMAN", "change_type": "KEPT"}]
        mapping = map_future_steps_to_capabilities(future_steps, [])
        entry = mapping[0]
        self.assertEqual(entry["capability_status"], "NOT_APPLICABLE")
        self.assertIn("human", entry["reason"].lower())

    def test_no_secret_config_or_credential_fields_anywhere(self):
        future_steps = [
            {"step_number": 1, "name": "Verify licence", "type": "SYSTEM", "change_type": "AUTOMATED"},
            {"step_number": 2, "name": "Unmatched step", "type": "SYSTEM", "change_type": "AUTOMATED"},
            {"step_number": 3, "name": "Customer step", "type": "CUSTOMER", "change_type": "KEPT"},
        ]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Verify licence", "type": "GOVERNMENT_API", "status": "CONNECTED",
             "secret_reference": "vault://leak", "config": {"api_key": "SHOULD_NOT_LEAK", "token": "SHOULD_NOT_LEAK"}},
            {"id": "int-4", "name": "Some Unavailable Thing", "type": "OTHER", "status": "NOT_CONNECTED",
             "secret_reference": "vault://leak2"},
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        blob = str(mapping)
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(forbidden, blob.lower(), f"forbidden content leaked: {forbidden}")
        self.assertNotIn("SHOULD_NOT_LEAK", blob)

    def test_no_chain_of_thought_like_fields_introduced(self):
        future_steps = [{"step_number": 1, "name": "Verify licence", "type": "SYSTEM", "change_type": "AUTOMATED"}]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Verify licence", "type": "GOVERNMENT_API", "status": "CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        entry = mapping[0]
        forbidden_keys = {"chain_of_thought", "thoughts", "deliberation", "raw_model_output", "prompt"}
        self.assertTrue(forbidden_keys.isdisjoint(entry.keys()))
        # The reason is a short, single, deterministic sentence -- not a
        # multi-paragraph narrative.
        self.assertLessEqual(entry["reason"].count("\n"), 0)

    def test_input_future_steps_are_not_mutated(self):
        future_steps = [
            {"step_number": 1, "name": "Verify licence", "type": "SYSTEM", "change_type": "AUTOMATED"},
            {"step_number": 2, "name": "Customer step", "type": "CUSTOMER", "change_type": "KEPT"},
        ]
        original_copy = [dict(s) for s in future_steps]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Verify licence", "type": "GOVERNMENT_API", "status": "CONNECTED"}
        ])
        map_future_steps_to_capabilities(future_steps, integrations)
        self.assertEqual(future_steps, original_copy)

    def test_existing_capability_metrics_unchanged_by_traceability(self):
        future_steps = [
            {"step_number": 1, "name": "Verify licence", "type": "SYSTEM", "change_type": "AUTOMATED"},
            {"step_number": 2, "name": "Unmatched", "type": "SYSTEM", "change_type": "AUTOMATED"},
            {"step_number": 3, "name": "Customer step", "type": "CUSTOMER", "change_type": "KEPT"},
            {"step_number": 4, "name": "Human step", "type": "HUMAN", "change_type": "KEPT"},
        ]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Verify licence", "type": "GOVERNMENT_API", "status": "CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        summary = build_capability_summary([], integrations, mapping)
        self.assertEqual(summary["automated_steps"], 1)
        self.assertEqual(summary["total_steps"], 4)
        self.assertEqual(summary["customer_steps"], 1)
        self.assertEqual(summary["manual_steps"], 1)
        self.assertEqual(summary["integration_required"], 1)

    def test_empty_future_journey_is_safe(self):
        self.assertEqual(map_future_steps_to_capabilities([], []), [])
        self.assertEqual(map_future_steps_to_capabilities(None, None), [])

    def test_malformed_step_entries_are_skipped_safely(self):
        mapping = map_future_steps_to_capabilities(["not-a-dict", 42, None, {}], [])
        # The one empty dict still gets classified (empty type -> NOT_APPLICABLE fallback path).
        self.assertTrue(all(isinstance(m, dict) for m in mapping))
        for entry in mapping:
            self.assertIn("reason", entry)


class BuildAgentCapabilityMapTraceabilityTestCase(unittest.TestCase):
    def test_full_map_includes_traceable_reasons_for_every_step(self):
        cap_map = build_agent_capability_map(
            service_id="svc-1",
            data_sources=[],
            integrations=[{"id": "int-1", "name": "Verify licence", "type": "GOVERNMENT_API", "status": "CONNECTED"}],
            future_steps=[
                {"step_number": 1, "name": "Verify licence", "type": "SYSTEM", "change_type": "AUTOMATED"},
                {"step_number": 2, "name": "Customer step", "type": "CUSTOMER", "change_type": "KEPT"},
            ],
        )
        for entry in cap_map["step_capability_mapping"]:
            self.assertIn("reason", entry)
            self.assertIsInstance(entry["reason"], str)


# ---------------------------------------------------------------------------
# Part 2: live API test
# ---------------------------------------------------------------------------


class StepTraceabilityApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _tenant_and_admin_headers(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        admin = self.repo.create_user(
            tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin"
        )
        r = self.client.post(
            "/api/auth/demo-login", json={"email": admin["email"], "credential": "zxr-demo-2026"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        return tenant, admin, {"Authorization": f"Bearer {r.json()['token']}"}

    def test_analyze_response_step_mapping_includes_reasons(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TraceE2E")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "Registry API", "status": "CONNECTED", "config": {}},
        ).json()

        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Trace Service", "description": "test service",
                  "integration_ids": [integ["id"]]},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        cap_map = analyze.json()["agent_capability_map"]
        for entry in cap_map["step_capability_mapping"]:
            self.assertIn("reason", entry)
        self.assertNotIn("secret_reference", analyze.text)

    def test_cross_tenant_isolation_unchanged(self):
        _tenant_a, _admin_a, headers_a = self._tenant_and_admin_headers("TraceIsoA")
        _tenant_b, _admin_b, headers_b = self._tenant_and_admin_headers("TraceIsoB")
        integ_b = self.client.post(
            "/api/integrations", headers=headers_b,
            json={"type": "GOVERNMENT_API", "name": "Tenant B Integration", "status": "CONNECTED", "config": {}},
        ).json()
        analyze = self.client.post(
            "/api/analyze", headers=headers_a,
            json={"service_name": "Cross Tenant Trace", "description": "x", "integration_ids": [integ_b["id"]]},
        )
        self.assertEqual(analyze.status_code, 404)

    def test_service_owner_scoping_unchanged(self):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"TraceOwner {suffix}", f"traceowner-{suffix}", status="ACTIVE")
        admin = self.repo.create_user(tenant["id"], "Admin", f"admin-{suffix}@test.local", role="entity_admin")
        owner = self.repo.create_user(tenant["id"], "Owner", f"owner-{suffix}@test.local", role="service_owner")

        def login(user):
            r = self.client.post(
                "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
            )
            self.assertEqual(r.status_code, 200)
            return {"Authorization": f"Bearer {r.json()['token']}"}

        admin_headers = login(admin)
        owner_headers = login(owner)
        service = self.client.post(
            "/api/services", headers=admin_headers,
            json={"service_name": "Not Assigned", "description": "x", "language": "en"},
        ).json()
        analyze = self.client.post(
            "/api/analyze", headers=owner_headers,
            json={"service_name": "Not Assigned", "description": "x", "service_id": service["id"]},
        )
        self.assertEqual(analyze.status_code, 404)

    def test_public_payload_still_excludes_agent_capability_map_and_traceability(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TracePublic")
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Trace Public Service", "description": "test"},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)
        slug = publish_agent.json()["published_slug"]
        tenant_slug, agent_slug = slug.split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200, public.text)
        self.assertNotIn("agent_capability_map", public.json()["result"])
        self.assertNotIn("step_capability_mapping", public.text)
        self.assertNotIn("mapped_integration", public.text)


if __name__ == "__main__":
    unittest.main()
