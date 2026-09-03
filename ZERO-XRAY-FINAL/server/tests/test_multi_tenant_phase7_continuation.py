"""Continuation-request tests: user management endpoints, complete
journey/journey-event tenant isolation across every mutation (edit,
approve, pay, execute, pause/cancel/handoff), and real Service/Analysis
linkage replacing the Blueprint-ID-as-both-IDs shortcut.
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


class TenantUserManagementTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _make_tenant_and_headers(self, label, role="entity_admin"):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        user = self.repo.create_user(tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role=role)
        r = self.client.post("/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        return tenant, {"Authorization": f"Bearer {r.json()['token']}"}, user

    def test_entity_admin_can_add_list_and_manage_users_in_own_tenant(self):
        tenant, headers, _admin = self._make_tenant_and_headers("UserMgmtA")

        create = self.client.post(
            "/api/users",
            json={"name": "New Analyst", "email": f"analyst-{uuid.uuid4().hex[:6]}@test.local", "role": "analyst"},
            headers=headers,
        )
        self.assertEqual(create.status_code, 200, create.text)
        new_user = create.json()
        self.assertEqual(new_user["tenant_id"], tenant["id"])

        listing = self.client.get("/api/users", headers=headers)
        self.assertEqual(listing.status_code, 200)
        self.assertGreaterEqual(len(listing.json()["users"]), 2)

        role_change = self.client.post(f"/api/users/{new_user['id']}/role", json={"role": "viewer"}, headers=headers)
        self.assertEqual(role_change.status_code, 200)
        self.assertEqual(role_change.json()["role"], "viewer")

        deactivate = self.client.post(f"/api/users/{new_user['id']}/status", json={"status": "SUSPENDED"}, headers=headers)
        self.assertEqual(deactivate.status_code, 200)
        self.assertEqual(deactivate.json()["status"], "SUSPENDED")

    def test_cannot_create_a_platform_admin_from_tenant_workspace(self):
        _tenant, headers, _admin = self._make_tenant_and_headers("UserMgmtNoEscalate")
        r = self.client.post(
            "/api/users",
            json={"name": "Sneaky", "email": f"sneaky-{uuid.uuid4().hex[:6]}@test.local", "role": "platform_admin"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 422)

    def test_viewer_cannot_manage_users(self):
        _tenant, headers, _admin = self._make_tenant_and_headers("UserMgmtViewer", role="viewer")
        r = self.client.get("/api/users", headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_entity_admin_cannot_manage_users_in_another_tenant(self):
        tenant_a, headers_a, _ = self._make_tenant_and_headers("UserMgmtCrossA")
        _tenant_b, headers_b, user_b = self._make_tenant_and_headers("UserMgmtCrossB")

        # Tenant A's admin tries to change Tenant B's admin's role by real ID.
        r = self.client.post(f"/api/users/{user_b['id']}/role", json={"role": "viewer"}, headers=headers_a)
        self.assertEqual(r.status_code, 404)


class JourneyFullTenantIsolationTestCase(unittest.TestCase):
    """Live over the real API: builds a full journey (Tenant A) then
    proves Tenant B, authenticated with their own valid token, is
    denied at every single mutation step by real UUID -- not just
    read access."""

    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _make_tenant_and_headers(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        user = self.repo.create_user(tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin")
        r = self.client.post("/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        return tenant, {"Authorization": f"Bearer {r.json()['token']}"}

    def _build_published_journey(self, headers):
        analyze = self.client.post(
            "/api/analyze",
            json={"service_name": "Renew Individual PO Box", "description": "x"},
            headers=headers,
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)

        # blueprint_id lets /api/sandbox/register derive the customer's
        # tenant server-side from the (now PUBLISHED) Blueprint, matching
        # the real frontend (client/src/components/LiveAgentPage.jsx's
        # handleRegister) -- without it the customer would land in the
        # anonymous-default tenant instead of Tenant A's, and journey
        # creation's tenant-isolation check would correctly reject it.
        register = self.client.post(
            "/api/sandbox/register",
            json={"name": "Customer", "email": f"c-{uuid.uuid4().hex[:6]}@test.local", "blueprint_id": blueprint_id},
        )
        customer_id = register.json()["id"]
        journey = self.client.post(
            "/api/journeys",
            json={"customer_id": customer_id, "intent": "Renew Individual PO Box", "blueprint_id": blueprint_id, "sandbox": True},
        )
        self.assertEqual(journey.status_code, 200, journey.text)
        return journey.json()["id"]

    def test_anonymous_customer_can_still_reach_their_own_journey(self):
        tenant_a, headers_a = self._make_tenant_and_headers("JourneyAnonA")
        journey_id = self._build_published_journey(headers_a)

        # No Authorization header at all -- the genuinely anonymous
        # customer flow -- must still work exactly as before.
        anon = self.client.get(f"/api/journeys/{journey_id}")
        self.assertEqual(anon.status_code, 200)

    def test_tenant_b_staff_denied_read_and_every_mutation_on_tenant_as_journey(self):
        tenant_a, headers_a = self._make_tenant_and_headers("JourneyMutA")
        _tenant_b, headers_b = self._make_tenant_and_headers("JourneyMutB")
        journey_id = self._build_published_journey(headers_a)

        # Every one of these routes through main.py's _customer_journey_or_403
        # FIRST, before any ValueError/409 business-rule path can be
        # reached -- so a cross-tenant request always gets the same 403
        # "Journey session is invalid or expired" it would get for a
        # nonexistent journey, uniformly across every mutation.

        # Read
        r = self.client.get(f"/api/journeys/{journey_id}", headers=headers_b)
        self.assertEqual(r.status_code, 403)

        # Edit
        r = self.client.post(f"/api/journeys/{journey_id}/edit", json={"instruction": "x"}, headers=headers_b)
        self.assertEqual(r.status_code, 403)

        # Approve
        r = self.client.post(f"/api/journeys/{journey_id}/approve", headers=headers_b)
        self.assertEqual(r.status_code, 403)

        # Payment-assessment
        r = self.client.post(f"/api/journeys/{journey_id}/payment-assessment", headers=headers_b)
        self.assertEqual(r.status_code, 403)

        # Payment
        r = self.client.post(f"/api/journeys/{journey_id}/payment", json={"payment_method": "SANDBOX_CARD", "approved": True}, headers=headers_b)
        self.assertEqual(r.status_code, 403)

        # Execute
        r = self.client.post(f"/api/journeys/{journey_id}/execute", headers=headers_b)
        self.assertEqual(r.status_code, 403)

        # Pause / cancel / handoff
        for action in ("pause", "cancel", "handoff"):
            r = self.client.post(f"/api/journeys/{journey_id}/{action}", headers=headers_b)
            self.assertEqual(r.status_code, 403, f"action={action}")

        # Events
        r = self.client.get(f"/api/journeys/{journey_id}/events", headers=headers_b)
        self.assertEqual(r.status_code, 403)

        # Meanwhile Tenant A itself can still read its own journey.
        own = self.client.get(f"/api/journeys/{journey_id}", headers=headers_a)
        self.assertEqual(own.status_code, 200)


class ServiceAnalysisLinkageTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _make_tenant_and_headers(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        user = self.repo.create_user(tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin")
        r = self.client.post("/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        return tenant, {"Authorization": f"Bearer {r.json()['token']}"}

    def test_analyze_creates_distinct_service_and_analysis_ids(self):
        _tenant, headers = self._make_tenant_and_headers("SvcLinkage")
        r = self.client.post(
            "/api/analyze", json={"service_name": "Rent Corporate PO Box", "description": "x"}, headers=headers
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("service_id", body)
        self.assertIn("analysis_id", body)
        self.assertNotEqual(body["service_id"], body["blueprint_id"])
        self.assertNotEqual(body["analysis_id"], body["blueprint_id"])
        self.assertNotEqual(body["service_id"], body["analysis_id"])

        services = self.client.get("/api/services", headers=headers)
        self.assertEqual(services.status_code, 200)
        self.assertTrue(any(s["id"] == body["service_id"] for s in services.json()["services"]))

        analyses = self.client.get(f"/api/services/{body['service_id']}/analyses", headers=headers)
        self.assertEqual(analyses.status_code, 200)
        self.assertTrue(any(a["id"] == body["analysis_id"] for a in analyses.json()["analyses"]))

    def test_reanalyzing_same_blueprint_reuses_service_but_new_analysis(self):
        _tenant, headers = self._make_tenant_and_headers("SvcLinkageReanalyze")
        first = self.client.post(
            "/api/analyze", json={"service_name": "Rent Individual PO Box", "description": "x"}, headers=headers
        ).json()
        second = self.client.post(
            "/api/analyze",
            json={"service_name": "Rent Individual PO Box", "description": "x", "blueprint_id": first["blueprint_id"]},
            headers=headers,
        ).json()
        self.assertEqual(first["service_id"], second["service_id"])
        self.assertNotEqual(first["analysis_id"], second["analysis_id"])


if __name__ == "__main__":
    unittest.main()
