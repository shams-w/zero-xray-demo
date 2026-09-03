"""Phase 3 focused tests: the additive `agent_capability_map.summary`
aggregate counts (core/agent_capability_mapper.py::build_capability_summary)
that back the Build Agent capability/readiness summary in
client/src/components/BuildAgentPage.jsx.

Part 1 -- pure unit tests directly against build_capability_summary /
build_agent_capability_map (no server, no Ollama): every metric definition,
empty-input safety, and "no secret fields in the summary".

Part 2 -- a live API test confirming `/api/analyze` attaches a correct,
tenant/service-scoped `summary` object end to end, and that the existing
Build Agent flow (analyze -> approve -> publish) still succeeds with it
present.
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


# ---------------------------------------------------------------------------
# Part 1: pure unit tests
# ---------------------------------------------------------------------------


class CapabilitySummaryUnitTestCase(unittest.TestCase):
    def _sample_future_steps(self):
        return [
            {"step_number": 1, "name": "Verify licence", "type": "SYSTEM",
             "action": "Call licence verification", "change_type": "AUTOMATED"},
            {"step_number": 2, "name": "Charge Payment Gateway fee", "type": "SYSTEM",
             "action": "Charge Payment Gateway fee", "change_type": "AUTOMATED"},
            {"step_number": 3, "name": "Some step with no matching integration", "type": "SYSTEM",
             "action": "", "change_type": "AUTOMATED"},
            {"step_number": 4, "name": "Committee review", "type": "HUMAN", "change_type": "KEPT"},
            {"step_number": 5, "name": "Customer uploads photo", "type": "CUSTOMER", "change_type": "KEPT"},
            {"step_number": 6, "name": "Customer confirms details", "type": "CUSTOMER", "change_type": "KEPT"},
        ]

    def _sample_integrations(self):
        return build_integration_capabilities([
            {"id": "int-1", "name": "Licence Verification", "type": "GOVERNMENT_API", "status": "CONNECTED"},
            {"id": "int-2", "name": "Payment Gateway", "type": "PAYMENT_GATEWAY", "status": "SANDBOX"},
            {"id": "int-3", "name": "Unused Notifications", "type": "NOTIFICATIONS", "status": "NOT_CONNECTED"},
        ])

    def test_used_data_sources_counts_only_provided_sources(self):
        summary = build_capability_summary(
            data_sources_used=[{"id": "ds-1"}, {"id": "ds-2"}, {"id": "ds-3"}, {"id": "ds-4"}],
            integration_capabilities=[], step_capability_mapping=[],
        )
        self.assertEqual(summary["used_data_sources"], 4)

    def test_connected_apis_counts_connected_only_not_sandbox_or_not_connected(self):
        integrations = self._sample_integrations()  # 1 CONNECTED, 1 SANDBOX, 1 NOT_CONNECTED
        summary = build_capability_summary([], integrations, [])
        self.assertEqual(summary["connected_apis"], 1)
        self.assertEqual(summary["sandbox_apis"], 1)

    def test_automated_steps_and_total_steps(self):
        integrations = self._sample_integrations()
        mapping = map_future_steps_to_capabilities(self._sample_future_steps(), integrations)
        summary = build_capability_summary([], integrations, mapping)
        # Step 1 -> AUTOMATE (CONNECTED match), Step 2 -> AUTOMATE (SANDBOX match),
        # Step 3 -> INTEGRATION_REQUIRED (no match).
        self.assertEqual(summary["automated_steps"], 2)
        self.assertEqual(summary["total_steps"], 6)

    def test_customer_steps_count(self):
        mapping = map_future_steps_to_capabilities(self._sample_future_steps(), [])
        summary = build_capability_summary([], [], mapping)
        self.assertEqual(summary["customer_steps"], 2)

    def test_manual_steps_count(self):
        mapping = map_future_steps_to_capabilities(self._sample_future_steps(), [])
        summary = build_capability_summary([], [], mapping)
        self.assertEqual(summary["manual_steps"], 1)

    def test_integration_required_count(self):
        integrations = self._sample_integrations()
        mapping = map_future_steps_to_capabilities(self._sample_future_steps(), integrations)
        summary = build_capability_summary([], integrations, mapping)
        self.assertEqual(summary["integration_required"], 1)

    def test_empty_data_sources_is_zero(self):
        summary = build_capability_summary([], [{"status": "CONNECTED"}], [])
        self.assertEqual(summary["used_data_sources"], 0)

    def test_empty_integrations_is_zero(self):
        summary = build_capability_summary([{"id": "ds-1"}], [], [])
        self.assertEqual(summary["connected_apis"], 0)
        self.assertEqual(summary["sandbox_apis"], 0)

    def test_empty_future_journey_is_all_safe_zeros(self):
        summary = build_capability_summary([], [], [])
        self.assertEqual(summary["automated_steps"], 0)
        self.assertEqual(summary["total_steps"], 0)
        self.assertEqual(summary["customer_steps"], 0)
        self.assertEqual(summary["manual_steps"], 0)
        self.assertEqual(summary["integration_required"], 0)

    def test_none_inputs_are_safe(self):
        summary = build_capability_summary(None, None, None)
        for value in summary.values():
            self.assertEqual(value, 0)

    def test_summary_never_contains_secret_fields(self):
        integrations_raw = [
            {"id": "int-1", "name": "Licence", "type": "GOVERNMENT_API", "status": "CONNECTED",
             "secret_reference": "vault://leak", "config": {"api_key": "leak"}}
        ]
        cap_map = build_agent_capability_map(
            service_id="svc-1",
            data_sources=[{"id": "ds-1", "name": "DS", "type": "TEXT", "status": "READY",
                            "classification": "TENANT_PRIVATE_SOURCE"}],
            integrations=integrations_raw,
            future_steps=[{"step_number": 1, "name": "x", "type": "SYSTEM", "change_type": "AUTOMATED"}],
        )
        summary_text = str(cap_map["summary"])
        self.assertNotIn("secret_reference", summary_text)
        self.assertNotIn("vault://leak", summary_text)
        self.assertNotIn("api_key", summary_text)
        # And the summary is purely a dict of counts.
        self.assertTrue(all(isinstance(v, int) for v in cap_map["summary"].values()))

    def test_summary_is_attached_by_build_agent_capability_map(self):
        cap_map = build_agent_capability_map(
            service_id="svc-1", data_sources=[], integrations=[], future_steps=[]
        )
        self.assertIn("summary", cap_map)
        for field in (
            "used_data_sources", "connected_apis", "sandbox_apis", "automated_steps",
            "total_steps", "customer_steps", "manual_steps", "integration_required",
        ):
            self.assertIn(field, cap_map["summary"])


# ---------------------------------------------------------------------------
# Part 2: live API test
# ---------------------------------------------------------------------------


class CapabilitySummaryApiTestCase(unittest.TestCase):
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

    def test_analyze_response_includes_correct_summary_end_to_end(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("SummaryE2E")
        ds = self.client.post(
            "/api/data-sources", headers=headers,
            json={"name": "Fees DS", "type": "TEXT", "status": "READY",
                  "classification": "TENANT_PRIVATE_SOURCE", "configuration": {"content": "fee schedule"}},
        ).json()
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "Registry API", "status": "CONNECTED", "config": {}},
        ).json()

        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={
                "service_name": "Summary Service", "description": "test service",
                "data_source_ids": [ds["id"]], "integration_ids": [integ["id"]],
            },
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        cap_map = analyze.json()["agent_capability_map"]
        self.assertIn("summary", cap_map)
        summary = cap_map["summary"]

        self.assertEqual(summary["used_data_sources"], len(cap_map["data_sources_used"]))
        self.assertEqual(
            summary["connected_apis"],
            sum(1 for i in cap_map["integration_capabilities"] if i["status"] == "CONNECTED"),
        )
        self.assertEqual(
            summary["automated_steps"],
            sum(1 for s in cap_map["step_capability_mapping"] if s["capability_status"] == "AUTOMATE"),
        )
        self.assertEqual(summary["total_steps"], len(cap_map["step_capability_mapping"]))
        self.assertEqual(
            summary["customer_steps"],
            sum(1 for s in cap_map["step_capability_mapping"] if s["step_type"] == "CUSTOMER"),
        )
        self.assertEqual(
            summary["manual_steps"],
            sum(1 for s in cap_map["step_capability_mapping"] if s["step_type"] == "HUMAN"),
        )
        self.assertEqual(
            summary["integration_required"],
            sum(1 for s in cap_map["step_capability_mapping"] if s["capability_status"] == "INTEGRATION_REQUIRED"),
        )

        # Never leak integration secrets/config anywhere in the response.
        body_text = analyze.text
        self.assertNotIn("secret_reference", body_text)

    def test_build_agent_flow_still_succeeds_with_summary_present(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("SummaryFlow")
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Summary Flow Service", "description": "test"},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        self.assertIn("summary", analyze.json()["agent_capability_map"])
        blueprint_id = analyze.json()["blueprint_id"]

        approve = self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.assertEqual(approve.status_code, 200, approve.text)
        publish_bp = self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        self.assertEqual(publish_bp.status_code, 200, publish_bp.text)
        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)

        slug = publish_agent.json()["published_slug"]
        tenant_slug, agent_slug = slug.split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200, public.text)
        # The internal grounding/summary field must never reach the
        # public, anonymous customer-facing payload.
        self.assertNotIn("agent_capability_map", public.json()["result"])


if __name__ == "__main__":
    unittest.main()
