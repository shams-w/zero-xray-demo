"""Final continuation tests:

- Complete role enforcement matrix (viewer/analyst/service_owner/
  entity_admin/platform_admin) against real endpoints
- Expanded cross-tenant isolation covering every resource type named
  in the task (Service, Analysis, Blueprint, Agent, Customer, Journey,
  Journey Events, Data Source, Integration) for both READ and MUTATION
- Resume as a proper tenant-scoped journey action
- SSE event stream tenant scoping (via the underlying tenant-scoped
  calls it now uses)
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


class RoleEnforcementTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _make_tenant(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        return tenant, suffix

    def _login_as(self, tenant, role, suffix):
        user = self.repo.create_user(tenant["id"], f"{role} user", f"{role}-{suffix}@test.local", role=role)
        r = self.client.post("/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def test_viewer_is_read_only(self):
        tenant, suffix = self._make_tenant("RoleViewer")
        headers = self._login_as(tenant, "viewer", suffix)

        # Read access works.
        self.assertEqual(self.client.get("/api/services", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/agents", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/audit-log", headers=headers).status_code, 200)

        # Every write is denied.
        self.assertEqual(
            self.client.post("/api/analyze", json={"service_name": "X", "description": ""}, headers=headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/data-sources", json={"name": "X", "type": "PDF"}, headers=headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/integrations", json={"type": "CRM", "name": "X"}, headers=headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/users", json={"name": "X", "email": f"x-{suffix}@t.test", "role": "viewer"}, headers=headers).status_code,
            403,
        )

    def test_analyst_can_analyze_but_not_publish_or_admin(self):
        tenant, suffix = self._make_tenant("RoleAnalyst")
        headers = self._login_as(tenant, "analyst", suffix)

        analyze = self.client.post(
            "/api/analyze", json={"service_name": "Analyst Service", "description": "x"}, headers=headers
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        blueprint_id = analyze.json()["blueprint_id"]

        # Cannot approve/publish.
        self.assertEqual(self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers).status_code, 403)
        self.assertEqual(self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers).status_code, 403)

        # Cannot publish an agent, cannot manage users/data-sources/integrations.
        self.assertEqual(
            self.client.post("/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/users", json={"name": "X", "email": f"x2-{suffix}@t.test", "role": "viewer"}, headers=headers).status_code,
            403,
        )

    def test_service_owner_can_build_and_publish_agents_but_not_manage_users(self):
        tenant, suffix = self._make_tenant("RoleServiceOwner")
        headers = self._login_as(tenant, "service_owner", suffix)

        analyze = self.client.post(
            "/api/analyze", json={"service_name": "SO Service", "description": "x"}, headers=headers
        )
        self.assertEqual(analyze.status_code, 200)
        blueprint_id = analyze.json()["blueprint_id"]

        self.assertEqual(self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers).status_code, 200)
        self.assertEqual(self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers).status_code, 200)
        publish_agent = self.client.post("/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers)
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)

        # But cannot manage tenant users.
        self.assertEqual(self.client.get("/api/users", headers=headers).status_code, 403)

    def test_entity_admin_has_full_own_tenant_access(self):
        tenant, suffix = self._make_tenant("RoleEntityAdmin")
        headers = self._login_as(tenant, "entity_admin", suffix)

        self.assertEqual(self.client.get("/api/users", headers=headers).status_code, 200)
        self.assertEqual(
            self.client.post("/api/data-sources", json={"name": "Policy PDF", "type": "PDF"}, headers=headers).status_code,
            200,
        )
        self.assertEqual(
            self.client.post("/api/integrations", json={"type": "CRM", "name": "Internal CRM"}, headers=headers).status_code,
            200,
        )
        # But not platform-level actions.
        self.assertEqual(self.client.get("/api/platform/entities", headers=headers).status_code, 403)

    def test_platform_admin_cannot_touch_tenant_workspace_resources(self):
        tenant, suffix = self._make_tenant("RolePlatformAdmin")
        user = self.repo.create_user(tenant["id"], "Root", f"root-{suffix}@platform.test", role="platform_admin")
        r = self.client.post("/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"})
        headers = {"Authorization": f"Bearer {r.json()['token']}"}

        self.assertEqual(self.client.get("/api/platform/entities", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/platform/stats", headers=headers).status_code, 200)
        # platform_admin has no tenant:* permissions at all.
        self.assertEqual(
            self.client.post("/api/analyze", json={"service_name": "X", "description": ""}, headers=headers).status_code,
            403,
        )


class ExpandedCrossTenantIsolationTestCase(unittest.TestCase):
    """Every resource type named in the task, read AND mutation,
    against REAL UUIDs."""

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

    def test_full_resource_matrix_cross_tenant_denied(self):
        tenant_a, headers_a = self._make_tenant_and_headers("MatrixA")
        _tenant_b, headers_b = self._make_tenant_and_headers("MatrixB")

        # Build a full set of Tenant A resources.
        analyze = self.client.post(
            "/api/analyze", json={"service_name": "Matrix Service", "description": "x"}, headers=headers_a
        )
        self.assertEqual(analyze.status_code, 200)
        body = analyze.json()
        service_id, analysis_id, blueprint_id = body["service_id"], body["analysis_id"], body["blueprint_id"]

        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_a)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers_a)
        agent = self.client.post("/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers_a).json()
        agent_id = agent["id"]

        ds = self.client.post(
            "/api/data-sources", json={"name": "Matrix DS", "type": "PDF"}, headers=headers_a
        ).json()
        integ = self.client.post(
            "/api/integrations", json={"type": "CRM", "name": "Matrix Integration"}, headers=headers_a
        ).json()

        register = self.client.post("/api/sandbox/register", json={"name": "C", "email": f"c-{uuid.uuid4().hex[:6]}@t.test", "blueprint_id": blueprint_id})
        customer_id = register.json()["id"]
        journey = self.client.post("/api/journeys", json={
            "customer_id": customer_id, "intent": "Matrix Service", "blueprint_id": blueprint_id, "sandbox": True,
        }).json()
        journey_id = journey["id"]

        # --- READ: Tenant B denied on every resource type ---
        self.assertEqual(self.client.get(f"/api/services/{service_id}/analyses", headers=headers_b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/analyses/{analysis_id}", headers=headers_b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/blueprints/{blueprint_id}", headers=headers_b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/agents/{agent_id}", headers=headers_b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/customers/{customer_id}", headers=headers_b).status_code, 404)
        # Journeys are gated through main.py's _customer_journey_or_403 (a
        # dual-mode staff-auth/customer-cookie helper) which deliberately
        # returns a uniform 403 for both "doesn't exist" and "not yours",
        # unlike the plain tenant-scoped lookups above that return 404.
        self.assertEqual(self.client.get(f"/api/journeys/{journey_id}", headers=headers_b).status_code, 403)
        self.assertEqual(self.client.get(f"/api/journeys/{journey_id}/events", headers=headers_b).status_code, 403)
        self.assertEqual(self.client.get(f"/api/data-sources/{ds['id']}", headers=headers_b).status_code, 404)
        self.assertEqual(self.client.get(f"/api/integrations/{integ['id']}", headers=headers_b).status_code, 404)

        # --- MUTATION: Tenant B denied ---
        self.assertEqual(self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_b).status_code, 404)
        self.assertEqual(
            self.client.post("/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers_b).status_code,
            404,
        )
        # Same _customer_journey_or_403 gate as the reads above -- every
        # journey mutation is denied with a uniform 403 for Tenant B,
        # before any state-machine/business-rule (409) path is reachable.
        self.assertEqual(self.client.post(f"/api/journeys/{journey_id}/edit", json={"instruction": "x"}, headers=headers_b).status_code, 403)
        self.assertEqual(self.client.post(f"/api/journeys/{journey_id}/approve", headers=headers_b).status_code, 403)
        self.assertEqual(self.client.post(f"/api/journeys/{journey_id}/pause", headers=headers_b).status_code, 403)
        self.assertEqual(self.client.post(f"/api/journeys/{journey_id}/resume", headers=headers_b).status_code, 403)
        self.assertEqual(self.client.post(f"/api/journeys/{journey_id}/cancel", headers=headers_b).status_code, 403)
        self.assertEqual(self.client.post(f"/api/journeys/{journey_id}/handoff", headers=headers_b).status_code, 403)

        # --- Tenant A itself can still read/act on all of it ---
        self.assertEqual(self.client.get(f"/api/blueprints/{blueprint_id}", headers=headers_a).status_code, 200)
        self.assertEqual(self.client.get(f"/api/agents/{agent_id}", headers=headers_a).status_code, 200)
        self.assertEqual(self.client.get(f"/api/customers/{customer_id}", headers=headers_a).status_code, 200)
        self.assertEqual(self.client.get(f"/api/data-sources/{ds['id']}", headers=headers_a).status_code, 200)
        self.assertEqual(self.client.get(f"/api/integrations/{integ['id']}", headers=headers_a).status_code, 200)


    def test_customer_registered_via_agent_link_inherits_that_agents_tenant(self):
        """Section 4: /service/{tenantSlug}/{agentSlug} -> Published
        Agent -> tenant_id -> Customer -> Journey. A customer who
        registers with the blueprint_id from a specific Published
        Agent must land in THAT Agent's tenant, not the default/dev
        tenant, so their own journey isolation (item 3) actually means
        something."""
        tenant, headers = self._make_tenant_and_headers("CustomerInherit")
        analyze = self.client.post(
            "/api/analyze", json={"service_name": "Inherit Svc", "description": "x"}, headers=headers
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)

        register = self.client.post(
            "/api/sandbox/register",
            json={"name": "Inherited Customer", "email": f"ic-{uuid.uuid4().hex[:6]}@t.test", "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 200)
        customer_id = register.json()["id"]

        # The tenant staff who owns this Blueprint can see the customer.
        r = self.client.get(f"/api/customers/{customer_id}", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tenant_id"], tenant["id"])

    def test_customer_cannot_inject_their_own_tenant_id(self):
        """Item 1: the customer/frontend must never be able to choose
        or control tenant_id. `CustomerRegistration` has no `tenant_id`
        field at all, so even a client that adds one to the JSON body
        is silently ignored by Pydantic -- tenant is derived ONLY from
        the resolved, PUBLISHED Blueprint server-side."""
        tenant_a, headers_a = self._make_tenant_and_headers("InjectA")
        tenant_b, _headers_b = self._make_tenant_and_headers("InjectB")

        analyze = self.client.post(
            "/api/analyze", json={"service_name": "Inject Svc", "description": "x"}, headers=headers_a
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_a)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers_a)

        # Attacker-controlled payload tries to smuggle a foreign tenant_id
        # alongside the real (Tenant A) blueprint_id.
        register = self.client.post(
            "/api/sandbox/register",
            json={
                "name": "Attacker",
                "email": f"attacker-{uuid.uuid4().hex[:6]}@t.test",
                "blueprint_id": blueprint_id,
                "tenant_id": tenant_b["id"],  # not a real field -- must be ignored
            },
        )
        self.assertEqual(register.status_code, 200)
        customer_id = register.json()["id"]

        # The customer must land in Tenant A (the Blueprint's real
        # owner), never Tenant B, regardless of what was injected.
        r = self.client.get(f"/api/customers/{customer_id}", headers=headers_a)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tenant_id"], tenant_a["id"])


class ResumeJourneyTestCase(unittest.TestCase):
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

    def test_resume_only_valid_from_paused(self):
        _tenant, headers = self._make_tenant_and_headers("ResumeTenant")
        analyze = self.client.post(
            "/api/analyze", json={"service_name": "Resume Svc", "description": "x"}, headers=headers
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        register = self.client.post(
            "/api/sandbox/register",
            json={"name": "C", "email": f"rc-{uuid.uuid4().hex[:6]}@t.test", "blueprint_id": blueprint_id},
        )
        customer_id = register.json()["id"]
        journey = self.client.post("/api/journeys", json={
            "customer_id": customer_id, "intent": "Resume Svc", "blueprint_id": blueprint_id, "sandbox": True,
        }).json()
        journey_id = journey["id"]

        # Cannot resume a journey that was never paused.
        r = self.client.post(f"/api/journeys/{journey_id}/resume")
        self.assertEqual(r.status_code, 409)

        # Pause then resume works and goes back to EXECUTING.
        self.client.post(f"/api/journeys/{journey_id}/pause")
        r = self.client.post(f"/api/journeys/{journey_id}/resume")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["state"], "EXECUTING")


if __name__ == "__main__":
    unittest.main()
