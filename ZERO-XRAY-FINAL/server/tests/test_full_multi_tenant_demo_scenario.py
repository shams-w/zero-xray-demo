"""Codifies the exact end-to-end demo scenario the multi-tenant spec
requires (Section 44 / the "Final demo must work" requirement), live
over the real FastAPI app, so a future change can't silently break the
scripted walkthrough without a test failing:

Platform Admin -> Create Emirates Post tenant -> Create Entity Admin ->
Login as Emirates Post -> Add Service -> Run ZERO X-RAY -> Future
Journey -> Approve -> Publish -> Publish Agent -> Open Public URL (from
an unrelated client) -> Complete customer journey -> Create a second
Government Entity -> confirm it sees NONE of Emirates Post's private
data (services, agents, blueprints, journeys, audit log), even by
guessing a real UUID.
"""

import os
import unittest
import uuid

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


class FullMultiTenantDemoScenarioTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def test_full_scripted_demo_scenario(self):
        suffix = uuid.uuid4().hex[:8]

        # Platform Admin
        admin_tenant = self.repo.create_tenant(f"Platform Ops {suffix}", f"platform-ops-{suffix}", status="ACTIVE")
        self.repo.create_user(admin_tenant["id"], "Root Admin", f"root-{suffix}@platform.test", role="platform_admin")
        r = self.client.post("/api/auth/demo-login", json={"email": f"root-{suffix}@platform.test", "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        platform_headers = {"Authorization": f"Bearer {r.json()['token']}"}

        # -> Create Emirates Post tenant + Entity Admin
        r = self.client.post("/api/platform/entities", json={
            "entity_name": "Emirates Post",
            "slug": f"emirates-post-{suffix}",
            "subscription_plan": "ENTERPRISE",
            "admin_name": "Fatima Al Suwaidi",
            "admin_email": f"fatima-{suffix}@emiratespost.test",
        }, headers=platform_headers)
        self.assertEqual(r.status_code, 200, r.text)

        # -> Login as Emirates Post
        r = self.client.post("/api/auth/demo-login", json={"email": f"fatima-{suffix}@emiratespost.test", "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        ep_headers = {"Authorization": f"Bearer {r.json()['token']}"}
        ep_tenant_id = self.client.get("/api/me", headers=ep_headers).json()["tenant_id"]

        # -> Add Service -> Run ZERO X-RAY -> Future Journey
        r = self.client.post("/api/analyze", json={
            "service_name": f"Renew Corporate PO Box {suffix}",
            "description": "Corporate customers renew their post office box annually.",
        }, headers=ep_headers)
        self.assertEqual(r.status_code, 200, r.text)
        analysis = r.json()
        blueprint_id = analysis["blueprint_id"]
        self.assertIn("redesign", analysis)
        self.assertNotEqual(analysis["service_id"], blueprint_id)
        self.assertNotEqual(analysis["analysis_id"], blueprint_id)

        # -> Approve -> Publish
        r = self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=ep_headers)
        self.assertEqual(r.status_code, 200)
        r = self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=ep_headers)
        self.assertEqual(r.status_code, 200)

        # -> Publish Agent
        r = self.client.post("/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=ep_headers)
        self.assertEqual(r.status_code, 200, r.text)
        agent_id = r.json()["id"]
        tenant_slug, agent_slug = r.json()["published_slug"].split("/", 1)
        self.assertTrue(tenant_slug.startswith("emirates-post"))

        # -> Add a Data Source and Integration too, so isolation of
        # those resource types is also exercised by this scenario.
        ds = self.client.post("/api/data-sources", json={"name": "Postal Policy PDF", "type": "PDF"}, headers=ep_headers)
        self.assertEqual(ds.status_code, 200)
        data_source_id = ds.json()["id"]
        integ = self.client.post("/api/integrations", json={"type": "CRM", "name": "Internal CRM"}, headers=ep_headers)
        self.assertEqual(integ.status_code, 200)
        integration_id = integ.json()["id"]

        # -> Open Public URL from a completely unrelated client
        other_client = TestClient(main_module.app)
        r = other_client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(r.status_code, 200)
        public_result = r.json()["result"]
        for internal_key in ("relevant_standards", "gap_analysis", "step_compliance", "validation"):
            self.assertNotIn(internal_key, public_result)

        # -> Complete customer journey
        r = other_client.post("/api/sandbox/register", json={"name": "Sara Ahmed", "email": f"sara-{suffix}@customer.test", "blueprint_id": blueprint_id})
        self.assertEqual(r.status_code, 200)
        customer_id = r.json()["id"]

        r = other_client.post("/api/journeys", json={
            "customer_id": customer_id,
            "intent": f"Renew Corporate PO Box {suffix}",
            "blueprint_id": blueprint_id,
            "sandbox": True,
        })
        self.assertEqual(r.status_code, 200, r.text)
        journey_id = r.json()["id"]

        r = other_client.post(f"/api/journeys/{journey_id}/approve")
        self.assertEqual(r.status_code, 200)
        requires_payment = bool(r.json()["plan"].get("requires_payment"))

        if requires_payment:
            self.assertEqual(other_client.post(f"/api/journeys/{journey_id}/payment-assessment").status_code, 200)
            self.assertEqual(
                other_client.post(
                    f"/api/journeys/{journey_id}/payment",
                    json={"payment_method": "SANDBOX_CARD", "approved": True},
                ).status_code,
                200,
            )

        r = other_client.post(f"/api/journeys/{journey_id}/execute")
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["state"], ("EXECUTING", "COMPLETED"))

        # Then login as another Government Entity.
        r = self.client.post("/api/platform/entities", json={
            "entity_name": "Government Entity Demo",
            "slug": f"gov-entity-demo-{suffix}",
            "subscription_plan": "PILOT",
            "admin_name": "Omar",
            "admin_email": f"omar-{suffix}@gov-entity-demo.test",
        }, headers=platform_headers)
        self.assertEqual(r.status_code, 200)

        r = self.client.post("/api/auth/demo-login", json={"email": f"omar-{suffix}@gov-entity-demo.test", "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        gov_headers = {"Authorization": f"Bearer {r.json()['token']}"}

        # It must see NONE of Emirates Post's private data.
        self.assertEqual(self.client.get("/api/services", headers=gov_headers).json()["services"], [])
        self.assertEqual(self.client.get("/api/agents", headers=gov_headers).json()["agents"], [])
        self.assertEqual(self.client.get(f"/api/blueprints/{blueprint_id}", headers=gov_headers).status_code, 404)
        self.assertEqual(self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=gov_headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/agents/{agent_id}", headers=gov_headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/analyses/{analysis['analysis_id']}", headers=gov_headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/customers/{customer_id}", headers=gov_headers).status_code, 404)
        # Journey access is gated through main.py's _customer_journey_or_403,
        # a dual-mode (staff-auth OR customer-capability-cookie) helper that
        # deliberately returns a uniform 403 "Journey session is invalid or
        # expired" for both "doesn't exist" and "not yours" -- unlike the
        # tenant-scoped resources above, which use a plain lookup that
        # returns 404 -- so cross-tenant staff access here is correctly 403.
        self.assertEqual(self.client.get(f"/api/journeys/{journey_id}", headers=gov_headers).status_code, 403)
        self.assertEqual(self.client.get(f"/api/journeys/{journey_id}/events", headers=gov_headers).status_code, 403)
        self.assertEqual(self.client.get(f"/api/data-sources/{data_source_id}", headers=gov_headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/integrations/{integration_id}", headers=gov_headers).status_code, 404)
        self.assertEqual(self.client.get("/api/data-sources", headers=gov_headers).json()["data_sources"], [])
        self.assertEqual(self.client.get("/api/integrations", headers=gov_headers).json()["integrations"], [])
        # /api/audit-log is scoped to the CALLER's own tenant (main.py's
        # get_audit_log), so it legitimately contains this gov admin's own
        # LOGIN entry from the demo-login above -- the isolation property
        # under test is that none of Emirates Post's (tenant A's) entries
        # leak in, not that this tenant's own audit log is empty.
        gov_audit_entries = self.client.get("/api/audit-log", headers=gov_headers).json()["entries"]
        self.assertTrue(all(entry["tenant_id"] != ep_tenant_id for entry in gov_audit_entries))


if __name__ == "__main__":
    unittest.main()
