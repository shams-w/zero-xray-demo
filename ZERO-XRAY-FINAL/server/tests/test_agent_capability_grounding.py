"""Phase 2 focused tests: Build Agent grounding in Service-linked Data
Sources and Integrations (core/agent_capability_mapper.py).

Part 1 -- pure unit tests against core/agent_capability_mapper.py directly
(no server, no Ollama): capability derivation, step mapping, "never invent
an Integration", NOT_CONNECTED never executable, SANDBOX stays identifiable,
secrets never leak.

Part 2 -- live API tests over the real FastAPI app (same TestClient pattern
as tests/test_service_owner_scoping.py / tests/test_multi_tenant_phase3_
agents.py), using the repo's stdlib mock Ollama server so /api/analyze
actually completes: Service-linked Data Sources/Integrations reach
`agent_capability_map`, unlinked and cross-tenant resources never do,
Service Owner scoping still applies, and analyses with no Data
Sources/Integrations at all still succeed.
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
    build_data_source_grounding,
    build_integration_capabilities,
    map_future_steps_to_capabilities,
)


# ---------------------------------------------------------------------------
# Part 1: pure unit tests
# ---------------------------------------------------------------------------


class DataSourceGroundingTestCase(unittest.TestCase):
    def test_only_safe_fields_are_kept(self):
        source = {
            "id": "ds-1",
            "name": "Fee Schedule",
            "type": "TEXT",
            "status": "READY",
            "classification": "TENANT_PRIVATE_SOURCE",
            "configuration": {"content": "internal document text"},
            "storage_path": "/mnt/tenant-files/secret/path.pdf",
        }
        grounding = build_data_source_grounding([source])
        self.assertEqual(len(grounding), 1)
        entry = grounding[0]
        self.assertEqual(entry["id"], "ds-1")
        self.assertEqual(entry["name"], "Fee Schedule")
        self.assertNotIn("configuration", entry)
        self.assertNotIn("storage_path", entry)

    def test_empty_input_is_empty_output(self):
        self.assertEqual(build_data_source_grounding([]), [])
        self.assertEqual(build_data_source_grounding(None), [])


class IntegrationCapabilityTestCase(unittest.TestCase):
    def test_connected_is_available_not_sandbox(self):
        cap = build_integration_capabilities([
            {"id": "int-1", "name": "Licence Verification API", "type": "VERIFICATION",
             "status": "CONNECTED", "secret_reference": "vault://should-not-leak",
             "config": {"api_key": "should-not-leak"}}
        ])[0]
        self.assertTrue(cap["available"])
        self.assertFalse(cap["sandbox"])
        self.assertNotIn("secret_reference", cap)
        self.assertNotIn("config", cap)

    def test_sandbox_is_identifiable_but_not_available(self):
        cap = build_integration_capabilities([
            {"id": "int-2", "name": "Payment Gateway", "type": "PAYMENT", "status": "SANDBOX"}
        ])[0]
        self.assertFalse(cap["available"])
        self.assertTrue(cap["sandbox"])

    def test_not_connected_is_neither_available_nor_sandbox(self):
        cap = build_integration_capabilities([
            {"id": "int-3", "name": "Document Store", "type": "DOCUMENTS", "status": "NOT_CONNECTED"}
        ])[0]
        self.assertFalse(cap["available"])
        self.assertFalse(cap["sandbox"])

    def test_never_hardcodes_a_capability_catalog(self):
        # The capability label must come straight from the stored
        # Integration metadata, not a fixed internal list.
        cap = build_integration_capabilities([
            {"id": "int-4", "name": "Totally Custom Thing", "type": "CUSTOM_TYPE_XYZ", "status": "CONNECTED"}
        ])[0]
        self.assertEqual(cap["capability_type"], "CUSTOM_TYPE_XYZ")
        self.assertEqual(cap["name"], "Totally Custom Thing")


class StepCapabilityMappingTestCase(unittest.TestCase):
    def test_system_step_matched_to_connected_integration_is_automate(self):
        future_steps = [{
            "step_number": 1, "name": "Verify driving licence",
            "type": "SYSTEM", "action": "Call licence verification",
            "change_type": "AUTOMATED", "reason": "",
        }]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Licence Verification", "type": "VERIFICATION", "status": "CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        self.assertEqual(mapping[0]["capability_status"], "AUTOMATE")
        self.assertEqual(mapping[0]["mapped_integration"]["id"], "int-1")

    def test_system_step_with_no_matching_integration_is_integration_required(self):
        future_steps = [{
            "step_number": 1, "name": "Verify driving licence",
            "type": "SYSTEM", "action": "Call licence verification",
            "change_type": "AUTOMATED", "reason": "",
        }]
        mapping = map_future_steps_to_capabilities(future_steps, [])
        self.assertEqual(mapping[0]["capability_status"], "INTEGRATION_REQUIRED")
        self.assertIsNone(mapping[0]["mapped_integration"])

    def test_not_connected_integration_is_never_treated_as_executable(self):
        # Step text matches the integration's own name, but its status is
        # NOT_CONNECTED -- must still be reported as INTEGRATION_REQUIRED.
        future_steps = [{
            "step_number": 1, "name": "Retrieve Document Store record",
            "type": "SYSTEM", "action": "", "change_type": "AUTOMATED", "reason": "",
        }]
        integrations = build_integration_capabilities([
            {"id": "int-3", "name": "Document Store", "type": "DOCUMENTS", "status": "NOT_CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        self.assertEqual(mapping[0]["capability_status"], "INTEGRATION_REQUIRED")
        self.assertIsNone(mapping[0]["mapped_integration"])

    def test_sandbox_integration_can_be_mapped_but_flagged_sandbox(self):
        future_steps = [{
            "step_number": 1, "name": "Authorize Payment Gateway charge",
            "type": "SYSTEM", "action": "", "change_type": "AUTOMATED", "reason": "",
        }]
        integrations = build_integration_capabilities([
            {"id": "int-2", "name": "Payment Gateway", "type": "PAYMENT", "status": "SANDBOX"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        self.assertEqual(mapping[0]["capability_status"], "AUTOMATE")
        self.assertTrue(mapping[0]["mapped_integration"]["sandbox"])

    def test_human_and_customer_steps_are_not_applicable_never_automated(self):
        future_steps = [
            {"step_number": 1, "name": "Committee review", "type": "HUMAN", "change_type": "KEPT"},
            {"step_number": 2, "name": "Customer uploads photo", "type": "CUSTOMER", "change_type": "KEPT"},
        ]
        integrations = build_integration_capabilities([
            {"id": "int-1", "name": "Committee review", "type": "REVIEW", "status": "CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        self.assertTrue(all(m["capability_status"] == "NOT_APPLICABLE" for m in mapping))
        self.assertTrue(all(m["mapped_integration"] is None for m in mapping))

    def test_never_invents_an_integration_not_in_the_provided_list(self):
        future_steps = [{
            "step_number": 1, "name": "Some completely unrelated step",
            "type": "SYSTEM", "action": "", "change_type": "AUTOMATED", "reason": "",
        }]
        integrations = build_integration_capabilities([
            {"id": "int-9", "name": "Unrelated Integration", "type": "OTHER", "status": "CONNECTED"}
        ])
        mapping = map_future_steps_to_capabilities(future_steps, integrations)
        # No textual overlap -> must not fabricate a match.
        self.assertEqual(mapping[0]["capability_status"], "INTEGRATION_REQUIRED")

    def test_non_dict_steps_are_skipped_without_raising(self):
        mapping = map_future_steps_to_capabilities(["not-a-dict", 42, None], [])
        self.assertEqual(mapping, [])


class BuildAgentCapabilityMapTestCase(unittest.TestCase):
    def test_full_map_shape_with_empty_inputs(self):
        result = build_agent_capability_map(
            service_id="svc-1", data_sources=[], integrations=[], future_steps=[]
        )
        self.assertEqual(result["service_id"], "svc-1")
        self.assertEqual(result["data_sources_used"], [])
        self.assertEqual(result["integration_capabilities"], [])
        self.assertEqual(result["step_capability_mapping"], [])

    def test_does_not_mutate_inputs(self):
        sources = [{"id": "ds-1", "name": "DS", "type": "TEXT", "status": "READY", "classification": "X"}]
        integrations = [{"id": "int-1", "name": "Int", "type": "PAYMENT", "status": "CONNECTED"}]
        future_steps = [{"step_number": 1, "name": "Step", "type": "SYSTEM", "change_type": "AUTOMATED"}]
        sources_copy = [dict(s) for s in sources]
        integrations_copy = [dict(i) for i in integrations]
        future_steps_copy = [dict(f) for f in future_steps]
        build_agent_capability_map("svc-1", sources, integrations, future_steps)
        self.assertEqual(sources, sources_copy)
        self.assertEqual(integrations, integrations_copy)
        self.assertEqual(future_steps, future_steps_copy)


# ---------------------------------------------------------------------------
# Part 2: live API tests
# ---------------------------------------------------------------------------


class AgentCapabilityGroundingApiTestCase(unittest.TestCase):
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

    def _create_data_source(self, headers, name, content):
        r = self.client.post(
            "/api/data-sources", headers=headers,
            json={
                "name": name, "type": "TEXT", "status": "READY",
                "classification": "TENANT_PRIVATE_SOURCE",
                "configuration": {"content": content},
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _create_integration(self, headers, name, itype, status):
        r = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": itype, "name": name, "status": status, "config": {}},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_service_linked_data_sources_and_integrations_reach_capability_map(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("Ground")
        ds = self._create_data_source(headers, "Linked DS", "eligibility rules")
        integ = self._create_integration(headers, "Linked Integration", "GOVERNMENT_API", "CONNECTED")

        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={
                "service_name": "Grounded Service", "description": "test service",
                "data_source_ids": [ds["id"]], "integration_ids": [integ["id"]],
            },
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        body = analyze.json()
        self.assertIn("agent_capability_map", body)
        cap_map = body["agent_capability_map"]

        used_ids = {item["id"] for item in cap_map["data_sources_used"]}
        self.assertIn(ds["id"], used_ids)

        integ_ids = {item["id"] for item in cap_map["integration_capabilities"]}
        self.assertIn(integ["id"], integ_ids)
        self.assertEqual(cap_map["service_id"], body["service_id"])

    def test_unlinked_data_source_from_same_tenant_is_not_included(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("Unlinked")
        linked_ds = self._create_data_source(headers, "Linked", "a")
        unlinked_ds = self._create_data_source(headers, "Unlinked", "b")

        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={
                "service_name": "Partial Link Service", "description": "test",
                "data_source_ids": [linked_ds["id"]], "integration_ids": [],
            },
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        used_ids = {item["id"] for item in analyze.json()["agent_capability_map"]["data_sources_used"]}
        self.assertIn(linked_ds["id"], used_ids)
        self.assertNotIn(unlinked_ds["id"], used_ids)

    def test_cross_tenant_data_source_id_is_rejected_not_grounded(self):
        _tenant_a, _admin_a, headers_a = self._tenant_and_admin_headers("XTenantA")
        _tenant_b, _admin_b, headers_b = self._tenant_and_admin_headers("XTenantB")

        ds_b = self._create_data_source(headers_b, "Tenant B Source", "secret to tenant B")

        # Tenant A attempts to analyze a service referencing Tenant B's
        # Data Source id directly -- must be rejected before any grounding
        # happens (existing _validate_service_resources tenant-scoping).
        analyze = self.client.post(
            "/api/analyze", headers=headers_a,
            json={
                "service_name": "Cross Tenant Attempt", "description": "test",
                "data_source_ids": [ds_b["id"]], "integration_ids": [],
            },
        )
        self.assertEqual(analyze.status_code, 404)

    def test_cross_tenant_integration_id_is_rejected_not_grounded(self):
        _tenant_a, _admin_a, headers_a = self._tenant_and_admin_headers("XIntA")
        _tenant_b, _admin_b, headers_b = self._tenant_and_admin_headers("XIntB")

        integ_b = self._create_integration(headers_b, "Tenant B Integration", "PAYMENT_GATEWAY", "CONNECTED")

        analyze = self.client.post(
            "/api/analyze", headers=headers_a,
            json={
                "service_name": "Cross Tenant Integration Attempt", "description": "test",
                "data_source_ids": [], "integration_ids": [integ_b["id"]],
            },
        )
        self.assertEqual(analyze.status_code, 404)

    def test_analysis_without_data_sources_or_integrations_still_succeeds(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("Bare")
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Bare Service", "description": "no linked resources at all"},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        cap_map = analyze.json()["agent_capability_map"]
        self.assertEqual(cap_map["data_sources_used"], [])
        self.assertEqual(cap_map["integration_capabilities"], [])

    def test_service_owner_cannot_generate_agent_for_unassigned_service(self):
        tenant, admin_headers_tuple = None, None
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"OwnerScope {suffix}", f"ownerscope-{suffix}", status="ACTIVE")
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

        # Entity Admin creates a service and does NOT assign it to the
        # Service Owner.
        service = self.client.post(
            "/api/services", headers=admin_headers,
            json={"service_name": "Not Assigned To Owner", "description": "x", "language": "en"},
        ).json()

        # The Service Owner tries to re-analyze it directly by service_id --
        # must be blocked by the existing _require_service_access check,
        # unchanged by the new grounding code path.
        analyze = self.client.post(
            "/api/analyze", headers=owner_headers,
            json={"service_name": "Not Assigned To Owner", "description": "x", "service_id": service["id"]},
        )
        self.assertEqual(analyze.status_code, 404)

    def test_entity_admin_analysis_unaffected_by_grounding_change(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("AdminOK")
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Entity Admin Flow Service", "description": "renew a licence"},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        body = analyze.json()
        # Existing fields untouched.
        for key in ("blueprint_id", "blueprint_status", "service_id", "analysis_id", "redesign"):
            self.assertIn(key, body)

    def test_build_agent_flow_still_succeeds_end_to_end(self):
        """Regression: analyze -> approve -> publish blueprint -> publish
        agent still works with the new additive field present."""
        _tenant, _admin, headers = self._tenant_and_admin_headers("EndToEnd")
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "End To End Service", "description": "test"},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
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
        # The new internal grounding field must never reach the public,
        # anonymous customer-facing payload.
        self.assertNotIn("agent_capability_map", public.json()["result"])


if __name__ == "__main__":
    unittest.main()
