"""Phase 8 focused tests: Agent Comparison Readiness.

Part 1 -- pure unit tests against core/agent_comparison.py directly (no
server, no Ollama): the deterministic ZERO X-RAY profile adapter (reuses
Phase 2-4 data verbatim, never recalculates), the external-Agent adapter
(never invents evidence, missing fields stay UNKNOWN/NOT_PROVIDED), no
secrets/chain-of-thought, legacy-Blueprint safety.

Part 2 -- live API tests: the two new endpoints
(PUT/GET /api/services/{id}/external-agent-profile,
GET /api/blueprints/{id}/comparison), tenant/Service-Owner scoping,
Phase 7 subscription enforcement, and confirmation that the public
Published Agent payload is unaffected.
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
from core.agent_comparison import (
    build_zero_xray_comparison_profile,
    build_external_agent_profile,
    build_comparison_readiness,
    UNKNOWN,
    NOT_PROVIDED,
)


# ---------------------------------------------------------------------------
# Part 1: pure unit tests
# ---------------------------------------------------------------------------


def _grounded_blueprint(summary_overrides=None, step_mapping=None, service_analysis=None):
    summary = {
        "used_data_sources": 3,
        "connected_apis": 2,
        "sandbox_apis": 1,
        "automated_steps": 4,
        "total_steps": 6,
        "customer_steps": 1,
        "manual_steps": 1,
        "integration_required": 1,
    }
    if summary_overrides:
        summary.update(summary_overrides)
    if step_mapping is None:
        step_mapping = [
            {"step_number": 1, "name": "Verify licence", "step_type": "SYSTEM",
             "capability_status": "AUTOMATE", "reason": "A CONNECTED integration matches.",
             "mapped_integration": {"id": "int-1", "name": "Registry API", "status": "CONNECTED", "sandbox": False}},
            {"step_number": 2, "name": "Unmatched step", "step_type": "SYSTEM",
             "capability_status": "INTEGRATION_REQUIRED", "reason": "No configured Service Integration.",
             "mapped_integration": None},
            {"step_number": 3, "name": "Customer step", "step_type": "CUSTOMER",
             "capability_status": "NOT_APPLICABLE", "reason": "Requires direct customer interaction.",
             "mapped_integration": None},
        ]
    return {
        "id": "bp-1",
        "service_name": "Test Service",
        "analysis": {
            "service_analysis": service_analysis if service_analysis is not None else {"steps": ["a", "b"]},
            "agent_capability_map": {
                "service_id": "svc-1",
                "data_sources_used": [{"id": "ds-1"}, {"id": "ds-2"}, {"id": "ds-3"}],
                "integration_capabilities": [
                    {"id": "int-1", "name": "Registry API", "status": "CONNECTED", "available": True, "sandbox": False},
                ],
                "step_capability_mapping": step_mapping,
                "summary": summary,
            },
        },
    }


class ZeroXrayProfileTestCase(unittest.TestCase):
    def test_metrics_reused_verbatim_from_phase3_summary(self):
        blueprint = _grounded_blueprint()
        profile = build_zero_xray_comparison_profile("tenant-1", "svc-1", blueprint)
        self.assertEqual(profile["metrics"]["used_data_sources"], 3)
        self.assertEqual(profile["metrics"]["connected_apis"], 2)
        self.assertEqual(profile["metrics"]["sandbox_apis"], 1)
        self.assertEqual(profile["metrics"]["automated_steps"], 4)
        self.assertEqual(profile["metrics"]["total_steps"], 6)
        self.assertEqual(profile["metrics"]["customer_steps"], 1)
        self.assertEqual(profile["metrics"]["manual_steps"], 1)
        self.assertEqual(profile["metrics"]["integration_required"], 1)

    def test_source_and_binding_fields(self):
        blueprint = _grounded_blueprint()
        profile = build_zero_xray_comparison_profile("tenant-1", "svc-1", blueprint)
        self.assertEqual(profile["source"], "ZERO_XRAY")
        self.assertEqual(profile["tenant_id"], "tenant-1")
        self.assertEqual(profile["service_id"], "svc-1")
        self.assertEqual(profile["blueprint_id"], "bp-1")

    def test_connected_apis_not_combined_with_sandbox(self):
        blueprint = _grounded_blueprint(summary_overrides={"connected_apis": 0, "sandbox_apis": 2})
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        real_api = profile["capabilities"]["real_api_usage"]
        self.assertEqual(real_api["state"], "PARTIAL")
        self.assertEqual(real_api["evidence"]["connected_apis"], 0)
        self.assertEqual(real_api["evidence"]["sandbox_apis"], 2)

    def test_not_connected_never_counted_as_connected(self):
        blueprint = _grounded_blueprint(summary_overrides={"connected_apis": 0, "sandbox_apis": 0})
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        self.assertEqual(profile["capabilities"]["real_api_usage"]["state"], "NOT_SUPPORTED")

    def test_traceability_derives_from_phase4_reasons(self):
        blueprint = _grounded_blueprint()
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        trace = profile["capabilities"]["traceability"]
        self.assertEqual(trace["state"], "SUPPORTED")
        self.assertEqual(trace["evidence"]["traceable_steps"], 3)

    def test_api_limit_awareness_recognizes_integration_required(self):
        blueprint = _grounded_blueprint()
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        awareness = profile["capabilities"]["api_limit_awareness"]
        self.assertEqual(awareness["state"], "SUPPORTED")
        self.assertEqual(awareness["evidence"]["integration_required_steps"], 1)

    def test_future_journey_alignment_no_invented_score(self):
        blueprint = _grounded_blueprint()
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        alignment = profile["capabilities"]["future_journey_alignment"]
        self.assertEqual(alignment["state"], "SUPPORTED")
        self.assertNotIn("score", alignment)
        self.assertNotIn("score", alignment["evidence"])
        self.assertIn("future_step_count", alignment["evidence"])

    def test_customer_step_reduction_is_unknown_no_current_journey_classification(self):
        blueprint = _grounded_blueprint()
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        reduction = profile["capabilities"]["customer_step_reduction"]
        self.assertEqual(reduction["state"], UNKNOWN)
        self.assertEqual(reduction["evidence"]["current_customer_steps"], UNKNOWN)
        self.assertEqual(reduction["evidence"]["future_customer_steps"], 1)

    def test_missing_generated_agent_evidence_is_unknown(self):
        blueprint = {"id": "bp-2", "service_name": "Bare", "analysis": {}}
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        for value in profile["metrics"].values():
            self.assertEqual(value, UNKNOWN)
        for dim in profile["capabilities"].values():
            self.assertEqual(dim["state"], UNKNOWN)

    def test_legacy_blueprint_without_capability_map_does_not_crash(self):
        legacy_blueprint = {
            "id": "bp-legacy",
            "service_name": "Legacy",
            "analysis": {
                "redesign": {"future_steps": [{"name": "x"}], "required_integrations": []},
                # No "agent_capability_map" key at all.
            },
        }
        profile = build_zero_xray_comparison_profile("t", "s", legacy_blueprint)
        self.assertEqual(profile["source"], "ZERO_XRAY")
        for value in profile["metrics"].values():
            self.assertEqual(value, UNKNOWN)

    def test_no_chain_of_thought_or_secrets_exposed(self):
        blueprint = _grounded_blueprint()
        profile = build_zero_xray_comparison_profile("t", "s", blueprint)
        blob = str(profile).lower()
        for forbidden in ("secret_reference", "chain_of_thought", "prompt", "api_key", "token", "config"):
            self.assertNotIn(forbidden, blob)


class ExternalAgentProfileTestCase(unittest.TestCase):
    def test_supports_fully_partial_information(self):
        payload = {"name": "Legacy Portal Bot", "known_data_sources_count": 2}
        profile = build_external_agent_profile("t", "s", payload)
        self.assertEqual(profile["source"], "ENTITY_EXISTING")
        self.assertEqual(profile["name"], "Legacy Portal Bot")
        self.assertEqual(profile["metrics"]["used_data_sources"], 2)

    def test_missing_fields_stay_unknown_not_zero(self):
        profile = build_external_agent_profile("t", "s", {})
        self.assertEqual(profile["metrics"]["used_data_sources"], UNKNOWN)
        self.assertEqual(profile["metrics"]["automated_steps"], UNKNOWN)
        self.assertEqual(profile["metrics"]["customer_steps"], UNKNOWN)
        self.assertEqual(profile["capabilities"]["real_api_usage"]["state"], UNKNOWN)
        self.assertEqual(profile["capabilities"]["transaction_execution"]["state"], UNKNOWN)
        self.assertEqual(profile["name"], NOT_PROVIDED)

    def test_zero_is_distinguished_from_unknown(self):
        profile = build_external_agent_profile("t", "s", {"known_data_sources_count": 0})
        self.assertEqual(profile["metrics"]["used_data_sources"], 0)
        self.assertEqual(profile["capabilities"]["data_grounding"]["state"], "NOT_SUPPORTED")
        # Compare against the omitted-field case, which is UNKNOWN, not 0.
        omitted = build_external_agent_profile("t", "s", {})
        self.assertEqual(omitted["metrics"]["used_data_sources"], UNKNOWN)

    def test_api_evidence_is_never_invented(self):
        # Only a count/list was supplied -- never assume CONNECTED/executable.
        profile = build_external_agent_profile("t", "s", {"known_apis_count": 3, "known_apis": ["X", "Y", "Z"]})
        api_usage = profile["capabilities"]["real_api_usage"]
        self.assertEqual(api_usage["state"], "PARTIAL")
        self.assertEqual(profile["metrics"]["connected_apis"], UNKNOWN)  # never invented

    def test_transaction_execution_never_invented_from_payment_alone(self):
        profile = build_external_agent_profile("t", "s", {"payment_supported": True})
        # payment_supported alone must NOT flip transaction_execution to SUPPORTED.
        self.assertEqual(profile["capabilities"]["transaction_execution"]["state"], UNKNOWN)

    def test_explicit_tristate_is_honored_when_supplied(self):
        profile = build_external_agent_profile("t", "s", {"transaction_execution": "SUPPORTED"})
        self.assertEqual(profile["capabilities"]["transaction_execution"]["state"], "SUPPORTED")

    def test_invalid_tristate_falls_back_to_unknown_never_invented(self):
        profile = build_external_agent_profile("t", "s", {"api_limit_awareness": "GARBAGE"})
        self.assertEqual(profile["capabilities"]["api_limit_awareness"]["state"], UNKNOWN)

    def test_traceability_never_invented(self):
        profile = build_external_agent_profile("t", "s", {})
        self.assertEqual(profile["capabilities"]["traceability"]["state"], UNKNOWN)
        explicit = build_external_agent_profile("t", "s", {"traceability_available": True})
        self.assertEqual(explicit["capabilities"]["traceability"]["state"], "SUPPORTED")

    def test_future_journey_alignment_always_unknown_for_external(self):
        profile = build_external_agent_profile("t", "s", {"customer_steps": 5})
        self.assertEqual(profile["capabilities"]["future_journey_alignment"]["state"], UNKNOWN)


class ComparisonReadinessTestCase(unittest.TestCase):
    def test_no_score_or_winner_field_anywhere(self):
        zx = build_zero_xray_comparison_profile("t", "s", _grounded_blueprint())
        ext = build_external_agent_profile("t", "s", {"name": "Legacy Bot"})
        result = build_comparison_readiness(zx, ext)
        blob = str(result).lower()
        self.assertNotIn("winner", blob)
        self.assertNotIn("score", blob)
        self.assertIn("zero_xray_agent", result)
        self.assertIn("entity_agent", result)
        self.assertIn("dimensions", result)


# ---------------------------------------------------------------------------
# Part 2: live API tests
# ---------------------------------------------------------------------------


class ComparisonApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _login(self, user):
        r = self.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def _tenant_admin_headers(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        admin = self.repo.create_user(
            tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin"
        )
        return tenant, admin, self._login(admin)

    def _published_blueprint(self, headers, service_name="Comparison Service"):
        analyze = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": service_name, "description": "test"}
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        body = analyze.json()
        self.client.post(f"/api/blueprints/{body['blueprint_id']}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{body['blueprint_id']}/publish", headers=headers)
        return body

    def test_get_comparison_without_saved_external_profile(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P8NoExternal")
        analysis = self._published_blueprint(headers)
        comparison = self.client.get(f"/api/blueprints/{analysis['blueprint_id']}/comparison", headers=headers)
        self.assertEqual(comparison.status_code, 200, comparison.text)
        body = comparison.json()
        self.assertEqual(body["zero_xray_agent"]["source"], "ZERO_XRAY")
        self.assertIsNone(body["entity_agent"])
        self.assertIn("dimensions", body)

    def test_save_and_fetch_external_profile_then_comparison(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P8External")
        analysis = self._published_blueprint(headers)
        service_id = analysis["service_id"]

        save = self.client.put(
            f"/api/services/{service_id}/external-agent-profile", headers=headers,
            json={"name": "Legacy Chatbot", "known_data_sources_count": 1, "manual_steps": 2},
        )
        self.assertEqual(save.status_code, 200, save.text)

        fetch = self.client.get(f"/api/services/{service_id}/external-agent-profile", headers=headers)
        self.assertEqual(fetch.status_code, 200)
        self.assertEqual(fetch.json()["profile"]["name"], "Legacy Chatbot")

        comparison = self.client.get(f"/api/blueprints/{analysis['blueprint_id']}/comparison", headers=headers)
        self.assertEqual(comparison.status_code, 200)
        self.assertEqual(comparison.json()["entity_agent"]["name"], "Legacy Chatbot")
        self.assertEqual(comparison.json()["entity_agent"]["metrics"]["automated_steps"], "UNKNOWN")

    def test_external_profile_not_found_before_saving(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P8NotFound")
        analysis = self._published_blueprint(headers)
        r = self.client.get(f"/api/services/{analysis['service_id']}/external-agent-profile", headers=headers)
        self.assertEqual(r.status_code, 404)

    def test_external_profile_is_tenant_scoped(self):
        _tenant_a, _admin_a, headers_a = self._tenant_admin_headers("P8TenA")
        analysis_a = self._published_blueprint(headers_a, "Tenant A Service")
        self.client.put(
            f"/api/services/{analysis_a['service_id']}/external-agent-profile",
            headers=headers_a, json={"name": "Tenant A Bot"},
        )
        _tenant_b, _admin_b, headers_b = self._tenant_admin_headers("P8TenB")
        # Tenant B cannot read Tenant A's service's external profile at all
        # (the service itself is not visible cross-tenant).
        r = self.client.get(f"/api/services/{analysis_a['service_id']}/external-agent-profile", headers=headers_b)
        self.assertEqual(r.status_code, 404)

    def test_external_profile_is_service_scoped_per_tenant(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P8SvcScope")
        analysis_1 = self._published_blueprint(headers, "Service One")
        analysis_2 = self._published_blueprint(headers, "Service Two")
        self.client.put(
            f"/api/services/{analysis_1['service_id']}/external-agent-profile",
            headers=headers, json={"name": "Service One Bot"},
        )
        r2 = self.client.get(f"/api/services/{analysis_2['service_id']}/external-agent-profile", headers=headers)
        self.assertEqual(r2.status_code, 404)
        r1 = self.client.get(f"/api/services/{analysis_1['service_id']}/external-agent-profile", headers=headers)
        self.assertEqual(r1.json()["profile"]["name"], "Service One Bot")

    def test_cross_tenant_access_denied(self):
        _tenant_a, _admin_a, headers_a = self._tenant_admin_headers("P8CrossA")
        analysis_a = self._published_blueprint(headers_a, "Cross Tenant Service")
        _tenant_b, _admin_b, headers_b = self._tenant_admin_headers("P8CrossB")
        save = self.client.put(
            f"/api/services/{analysis_a['service_id']}/external-agent-profile",
            headers=headers_b, json={"name": "Should Fail"},
        )
        self.assertEqual(save.status_code, 404)
        comparison = self.client.get(
            f"/api/blueprints/{analysis_a['blueprint_id']}/comparison", headers=headers_b
        )
        self.assertEqual(comparison.status_code, 404)

    def test_service_owner_cannot_manage_profile_for_unassigned_service(self):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"P8Owner {suffix}", f"p8owner-{suffix}", status="ACTIVE")
        admin = self.repo.create_user(tenant["id"], "Admin", f"admin-{suffix}@test.local", role="entity_admin")
        owner = self.repo.create_user(tenant["id"], "Owner", f"owner-{suffix}@test.local", role="service_owner")
        admin_headers = self._login(admin)
        owner_headers = self._login(owner)

        analyze = self.client.post(
            "/api/analyze", headers=admin_headers, json={"service_name": "Owner Unassigned", "description": "x"}
        )
        service_id = analyze.json()["service_id"]

        save = self.client.put(
            f"/api/services/{service_id}/external-agent-profile",
            headers=owner_headers, json={"name": "Should Fail"},
        )
        self.assertEqual(save.status_code, 404)

    def test_entity_admin_can_manage_profile_within_tenant(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P8AdminOK")
        analysis = self._published_blueprint(headers)
        save = self.client.put(
            f"/api/services/{analysis['service_id']}/external-agent-profile",
            headers=headers, json={"name": "Admin Managed Bot"},
        )
        self.assertEqual(save.status_code, 200, save.text)

    def test_expired_tenant_cannot_bypass_via_comparison_endpoints(self):
        tenant, _admin, headers = self._tenant_admin_headers("P8Expired")
        analysis = self._published_blueprint(headers)
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")

        save = self.client.put(
            f"/api/services/{analysis['service_id']}/external-agent-profile",
            headers=headers, json={"name": "Should Fail"},
        )
        self.assertEqual(save.status_code, 403)
        self.assertEqual(save.json()["detail"]["code"], "TENANT_SUSPENDED")

        comparison = self.client.get(
            f"/api/blueprints/{analysis['blueprint_id']}/comparison", headers=headers
        )
        self.assertEqual(comparison.status_code, 403)

    def test_platform_admin_behavior_unaffected(self):
        """Platform Admin has no comparison-specific permission and is
        not expected to call these tenant-workspace endpoints -- confirms
        no new weaker parallel authorization was introduced for them."""
        suffix = uuid.uuid4().hex[:8]
        host_tenant = self.repo.create_tenant(f"P8PlatHost {suffix}", f"p8plathost-{suffix}", status="ACTIVE")
        padmin = self.repo.create_user(
            host_tenant["id"], "Platform Root", f"p8root-{suffix}@test.local", role="platform_admin"
        )
        platform_headers = self._login(padmin)
        # platform_admin has no tenant:manage_agents / tenant:read permission.
        r = self.client.get("/api/services/does-not-matter/external-agent-profile", headers=platform_headers)
        self.assertEqual(r.status_code, 403)

    def test_public_published_agent_payload_unaffected(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P8Public")
        analysis = self._published_blueprint(headers)
        self.client.put(
            f"/api/services/{analysis['service_id']}/external-agent-profile",
            headers=headers, json={"name": "Should Not Appear Publicly"},
        )
        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": analysis["blueprint_id"]}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)
        tenant_slug, agent_slug = publish_agent.json()["published_slug"].split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200)
        self.assertNotIn("Should Not Appear Publicly", public.text)
        self.assertNotIn("agent_capability_map", public.text)
        self.assertNotIn("entity_agent", public.text)


if __name__ == "__main__":
    unittest.main()
