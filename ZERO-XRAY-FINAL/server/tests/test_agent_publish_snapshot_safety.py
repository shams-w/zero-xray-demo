"""Phase 6 focused tests: publishing the grounded, tested Agent from
Phases 2-5 through the EXISTING Publish Agent architecture
(server/core/agent_store.py, GET /service/{tenant_slug}/{agent_slug}).

Most of Phase 6's requirements were already satisfied by the existing
architecture (RBAC, tenant isolation, Service Owner scoping on
/api/agents/publish, allowlist-based sanitize_for_public, a
window.location.origin-derived published URL) and are covered here only
as confirmation, not as new behavior.

The one real defect this phase found and fixed: re-analyzing an already
APPROVED/PUBLISHED Blueprint in place (POST /api/analyze with an existing
blueprint_id) silently overwrote its live, already-published content,
because GET /service/{tenant_slug}/{agent_slug} resolves the Blueprint's
current analysis fresh on every request and `save_blueprint` never
touched `status` on update. `save_blueprint` now demotes an
APPROVED/PUBLISHED Blueprint back to DRAFT when it is re-analyzed, so the
existing DRAFT -> APPROVED -> PUBLISHED gate (set_blueprint_status) is
required again before the new content goes live -- the public page 404s
in between rather than silently serving unreviewed content. A DRAFT
Blueprint being re-analyzed is unaffected (stays DRAFT, exactly as
before).
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


class PublishAgentSnapshotSafetyTestCase(unittest.TestCase):
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

    def _publish_full_flow(self, headers, service_name="Publish Flow Service", integration_ids=None):
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": service_name, "description": "test",
                  "integration_ids": integration_ids or []},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        body = analyze.json()
        blueprint_id = body["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        publish_bp = self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        self.assertEqual(publish_bp.status_code, 200, publish_bp.text)
        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)
        return body, publish_agent.json()

    # -- 1/2: same grounded Blueprint is published, no regeneration --

    def test_published_agent_content_matches_the_analyzed_blueprint(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6Same")
        analysis, agent = self._publish_full_flow(headers, service_name="Grounded Publish Service")
        tenant_slug, agent_slug = agent["published_slug"].split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200, public.text)
        # Same content that /api/analyze produced -- not a fresh AI call.
        self.assertEqual(public.json()["result"]["service_name"], analysis["service_name"])
        self.assertEqual(agent["blueprint_id"], analysis["blueprint_id"])

    # -- 3/4/5: tenant_id/service_id/blueprint binding --

    def test_published_agent_retains_correct_tenant_service_blueprint_binding(self):
        tenant, _admin, headers = self._tenant_and_admin_headers("P6Bind")
        analysis, agent = self._publish_full_flow(headers)
        get_agent = self.client.get(f"/api/agents/{agent['id']}", headers=headers)
        self.assertEqual(get_agent.status_code, 200, get_agent.text)
        row = get_agent.json()
        self.assertEqual(row["tenant_id"], tenant["id"])
        self.assertEqual(row["service_id"], analysis["service_id"])
        self.assertEqual(row["blueprint_id"], analysis["blueprint_id"])

    # -- 6: Service Owner cannot publish an unassigned Service's Agent --

    def test_service_owner_cannot_publish_unassigned_service_agent(self):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"P6Owner {suffix}", f"p6owner-{suffix}", status="ACTIVE")
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

        analyze = self.client.post(
            "/api/analyze", headers=admin_headers,
            json={"service_name": "Owner Unassigned Publish", "description": "x"},
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=admin_headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=admin_headers)

        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=owner_headers
        )
        self.assertEqual(publish_agent.status_code, 404)

    # -- 7: Entity Admin can publish within their tenant (baseline) --

    def test_entity_admin_can_publish_within_tenant(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6AdminOK")
        _analysis, agent = self._publish_full_flow(headers)
        self.assertIn("published_slug", agent)

    # -- 8: cross-tenant publish fails --

    def test_cross_tenant_publish_fails(self):
        _tenant_a, _admin_a, headers_a = self._tenant_and_admin_headers("P6XA")
        _tenant_b, _admin_b, headers_b = self._tenant_and_admin_headers("P6XB")
        analyze = self.client.post(
            "/api/analyze", headers=headers_a, json={"service_name": "Tenant A Publish Only", "description": "x"}
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_a)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers_a)
        cross = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers_b
        )
        self.assertEqual(cross.status_code, 404)

    # -- 9: draft/unapproved Blueprint cannot bypass the lifecycle --

    def test_unapproved_blueprint_agent_publish_is_rejected(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6Unapproved")
        analyze = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": "Unapproved Service", "description": "x"}
        )
        blueprint_id = analyze.json()["blueprint_id"]
        # No approve/publish step at all.
        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 409)

    # -- 10/11: stable slug, URL points to correct tenant/agent slug --

    def test_published_slug_is_stable_and_matches_tenant(self):
        tenant, _admin, headers = self._tenant_and_admin_headers("P6Slug")
        _analysis, agent = self._publish_full_flow(headers, service_name="Slug Stability Service")
        slug = agent["published_slug"]
        tenant_slug, _agent_slug = slug.split("/", 1)
        self.assertEqual(tenant_slug, tenant["slug"])
        # Re-fetching the same agent returns the exact same slug.
        get_agent = self.client.get(f"/api/agents/{agent['id']}", headers=headers)
        self.assertEqual(get_agent.json()["published_slug"], slug)

    # -- 12: URL generation is not permanently hardcoded to localhost --

    def test_frontend_published_url_derives_from_window_origin_not_hardcoded_host(self):
        import pathlib
        source = pathlib.Path(__file__).resolve().parents[2] / "client" / "src" / "components" / "BuildAgentPage.jsx"
        text = source.read_text(encoding="utf-8")
        self.assertIn("window.location.origin", text)
        # The demoUrl construction itself must not embed a literal host.
        demo_url_line = next(line for line in text.splitlines() if "published_slug" in line and "demoUrl" not in line and "${window.location.origin}" in line)
        self.assertNotIn("localhost", demo_url_line)
        self.assertNotIn("127.0.0.1", demo_url_line)

    # -- 13/14: existing published Agents still resolve; only PUBLISHED --

    def test_republish_after_reanalysis_required_before_new_content_goes_live(self):
        """The core Phase 6 fix: re-analyzing an already-PUBLISHED
        Blueprint in place must not silently change what the live public
        page serves."""
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6Repub")
        analysis, agent = self._publish_full_flow(headers, service_name="Version One Service")
        blueprint_id = analysis["blueprint_id"]
        tenant_slug, agent_slug = agent["published_slug"].split("/", 1)

        public_before = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public_before.status_code, 200)
        self.assertEqual(public_before.json()["result"]["service_name"], "Version One Service")

        # Re-analyze reusing the same blueprint_id with different content.
        reanalyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Version Two Service CHANGED", "description": "different content",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(reanalyze.status_code, 200, reanalyze.text)
        # The Blueprint is demoted back to DRAFT -- not silently PUBLISHED.
        self.assertEqual(reanalyze.json()["blueprint_status"], "DRAFT")

        blueprint_row = self.client.get(f"/api/blueprints/{blueprint_id}", headers=headers)
        self.assertEqual(blueprint_row.json()["status"], "DRAFT")

        # The already-published Agent's URL must stop serving as PUBLISHED
        # rather than silently showing the unreviewed new content.
        public_during = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public_during.status_code, 404)

        # Only after an explicit re-approve + re-publish does the new
        # content go live, under the SAME existing slug (no new Agent
        # publish call required -- the existing Agent row's binding
        # already resolves the Blueprint fresh).
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        public_after = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public_after.status_code, 200)
        self.assertEqual(public_after.json()["result"]["service_name"], "Version Two Service CHANGED")

    def test_reanalyzing_a_draft_blueprint_is_unaffected(self):
        """Confirms the fix is scoped to APPROVED/PUBLISHED only -- the
        ordinary edit-before-approval loop (re-analyze a DRAFT Blueprint)
        behaves exactly as before."""
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6DraftReanalyze")
        first = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": "Draft V1", "description": "x"}
        )
        blueprint_id = first.json()["blueprint_id"]
        self.assertEqual(first.json()["blueprint_status"], "DRAFT")
        second = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Draft V2", "description": "x", "blueprint_id": blueprint_id},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["blueprint_status"], "DRAFT")

    # -- 15/16/17/18/19: public payload sanitization/security --

    def test_public_payload_excludes_secrets_and_internal_agent_capability_map(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6Secrets")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "Registry API", "status": "CONNECTED",
                  "config": {"endpoint": "https://example.test"}, "secret_reference": "vault://should-not-leak"},
        ).json()
        analysis, agent = self._publish_full_flow(headers, service_name="Secret Safety Service",
                                                    integration_ids=[integ["id"]])
        self.assertIn("agent_capability_map", analysis)  # confirms grounding was present pre-publish
        tenant_slug, agent_slug = agent["published_slug"].split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200, public.text)
        body_text = public.text.lower()
        for forbidden in ("secret_reference", "should-not-leak", "agent_capability_map",
                          "step_capability_mapping", "chain_of_thought"):
            self.assertNotIn(forbidden.lower(), body_text)

    # -- 20: published customer route remains functional --

    def test_published_customer_route_still_supports_starting_a_sandbox_journey(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6CustRoute")
        _analysis, agent = self._publish_full_flow(headers)
        tenant_slug, agent_slug = agent["published_slug"].split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        blueprint_id = public.json()["result"]["blueprint_id"]

        # Anonymous customer flow (no Authorization header at all).
        anon_client = TestClient(main_module.app)
        register = anon_client.post(
            "/api/sandbox/register",
            json={"name": "Public Customer", "email": f"public-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 200, register.text)

    # -- 25: existing Build -> Test -> Publish flow still works --

    def test_full_build_test_publish_flow_still_works(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6FullFlow")
        analyze = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": "Full Flow Service", "description": "test"}
        )
        blueprint_id = analyze.json()["blueprint_id"]

        # Test Agent (Phase 5 staff-preview path).
        register = self.client.post(
            "/api/sandbox/register", headers=headers,
            json={"name": "Flow Preview", "email": f"flow-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 200, register.text)
        customer = register.json()
        journey = self.client.post(
            "/api/journeys",
            json={"customer_id": customer["id"], "intent": "test", "blueprint_id": blueprint_id,
                  "lang": "en", "sandbox": True},
        )
        self.assertEqual(journey.status_code, 200, journey.text)

        # Publish (Phase 6).
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)

    # -- 26: legacy published Agent behavior remains safe --

    def test_legacy_blueprint_without_capability_map_publishes_and_resolves_safely(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("P6Legacy")
        service = main_module.service_store.create_service(
            tenant_id=_tenant["id"], service_name="Legacy Publish Service",
            description="", language="en", created_by=_admin["id"],
        )
        blueprint = main_module.runtime_store.save_blueprint(
            {"service_name": "Legacy Publish Service", "lang": "en"},
            {
                "service": {"service_name": "Legacy Publish Service"},
                "redesign": {
                    "future_steps": [{"step_number": 1, "name": "Legacy step", "assistant_action": "Do it"}],
                    "required_integrations": [],
                },
                # Deliberately no "agent_capability_map" key -- pre-Phase-2 shape.
            },
            tenant_id=_tenant["id"],
        )
        analysis = main_module.service_store.create_analysis(
            _tenant["id"], service["id"], blueprint["id"], created_by=_admin["id"], result={"label": "legacy"}
        )
        blueprint = main_module.runtime_store.link_blueprint_to_service_analysis(
            blueprint["id"], _tenant["id"], service["id"], analysis["id"]
        )
        main_module.runtime_store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=_tenant["id"])
        main_module.runtime_store.set_blueprint_status(blueprint["id"], "PUBLISHED", tenant_id=_tenant["id"])
        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint["id"]}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)
        tenant_slug, agent_slug = publish_agent.json()["published_slug"].split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200, public.text)
        self.assertNotIn("agent_capability_map", public.text)


if __name__ == "__main__":
    unittest.main()
