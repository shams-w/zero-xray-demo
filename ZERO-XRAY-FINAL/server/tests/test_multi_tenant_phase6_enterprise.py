"""Phase 6 tests: enterprise capabilities layer.

- Audit log entries carry the correct tenant_id and actor_user_id,
  and are tenant-scoped end to end (Section 21/38)
- Data Sources / Integrations are tenant-scoped, type/status validated,
  and integrations reject anything that looks like a raw pasted secret
  (Section 16/18/19)
- Subscription enforcement over the LIVE API: a suspended tenant's
  entity_admin is blocked from restricted workspace operations, but
  their data still exists and platform admins can still see the tenant
  (Section 20/38 "Expired tenant cannot perform restricted workspace
  operations. Data still exists.")
"""

import os
import tempfile
import unittest
import uuid
from pathlib import Path

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
from core.catalog_store import CatalogStore
from core.runtime_store import RuntimeStore


class AuditLogTenantScopingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RuntimeStore(Path(self._tmp.name) / "runtime.db")
        self.repo = self.store._tenant_repository
        self.tenant_a = self.repo.create_tenant("Audit Tenant A", "audit-tenant-a", status="ACTIVE")
        self.tenant_b = self.repo.create_tenant("Audit Tenant B", "audit-tenant-b", status="ACTIVE")

    def tearDown(self):
        self._tmp.cleanup()

    def test_blueprint_actions_are_recorded_under_the_correct_tenant(self):
        blueprint = self.store.save_blueprint(
            {"service_name": "Audited Service"}, {}, tenant_id=self.tenant_a["id"]
        )
        self.store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=self.tenant_a["id"])

        entries_a = self.store.list_audit_log_for_tenant(self.tenant_a["id"])
        entries_b = self.store.list_audit_log_for_tenant(self.tenant_b["id"])

        actions_a = {e["action"] for e in entries_a}
        self.assertIn("CREATED", actions_a)
        self.assertIn("APPROVED", actions_a)
        self.assertEqual(entries_b, [])  # Tenant B sees nothing of Tenant A's activity
        for entry in entries_a:
            self.assertEqual(entry["tenant_id"], self.tenant_a["id"])

    def test_journey_creation_is_recorded_under_the_blueprints_tenant(self):
        blueprint = self.store.save_blueprint(
            {"service_name": "Journey Audit Svc"}, {}, tenant_id=self.tenant_a["id"]
        )
        self.store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=self.tenant_a["id"])
        self.store.set_blueprint_status(blueprint["id"], "PUBLISHED", tenant_id=self.tenant_a["id"])
        customer = self.store.register_customer("Sara", "sara@test.local", tenant_id=self.tenant_a["id"])
        self.store.create_journey(customer["id"], "Journey Audit Svc", blueprint_id=blueprint["id"])

        entries_a = self.store.list_audit_log_for_tenant(self.tenant_a["id"])
        self.assertTrue(any(e["entity_type"] == "journey" and e["action"] == "PLAN_READY" for e in entries_a))


class CatalogStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)  # initializes shared schema first
        self.catalog = CatalogStore(database_path=self.db_path)
        self.tenant_a = self.runtime_store._tenant_repository.create_tenant(
            "Catalog Tenant A", "catalog-tenant-a", status="ACTIVE"
        )
        self.tenant_b = self.runtime_store._tenant_repository.create_tenant(
            "Catalog Tenant B", "catalog-tenant-b", status="ACTIVE"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_data_source_is_tenant_scoped(self):
        ds = self.catalog.create_data_source(
            self.tenant_a["id"], "Postal Policy PDF", "PDF", classification="TENANT_PRIVATE_SOURCE"
        )
        self.assertIsNone(self.catalog.get_data_source_for_tenant(ds["id"], self.tenant_b["id"]))
        self.assertIsNotNone(self.catalog.get_data_source_for_tenant(ds["id"], self.tenant_a["id"]))

    def test_invalid_data_source_type_rejected(self):
        with self.assertRaises(ValueError):
            self.catalog.create_data_source(self.tenant_a["id"], "X", "NOT_A_REAL_TYPE")

    def test_data_sources_default_to_not_connected(self):
        ds = self.catalog.create_data_source(self.tenant_a["id"], "Some API", "API")
        self.assertEqual(ds["status"], "NOT_CONNECTED")

    def test_integration_rejects_raw_looking_secret(self):
        raw_looking_key = "sk_live_" + ("a" * 40)
        with self.assertRaises(ValueError):
            self.catalog.create_integration(
                self.tenant_a["id"], "PAYMENT_GATEWAY", "Stripe-ish",
                secret_reference=raw_looking_key,
            )

    def test_integration_accepts_a_proper_reference_path(self):
        integration = self.catalog.create_integration(
            self.tenant_a["id"], "PAYMENT_GATEWAY", "Payment Gateway",
            secret_reference="tenant/catalog-tenant-a/payment",
        )
        self.assertEqual(integration["secret_reference"], "tenant/catalog-tenant-a/payment")

    def test_integration_is_tenant_scoped(self):
        integration = self.catalog.create_integration(self.tenant_a["id"], "CRM", "Internal CRM")
        self.assertIsNone(self.catalog.get_integration_for_tenant(integration["id"], self.tenant_b["id"]))


class SubscriptionEnforcementLiveApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _make_tenant_and_headers(self, label, status="ACTIVE", subscription_end=None):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(
            f"{label} {suffix}", f"{label.lower()}-{suffix}",
            status=status, subscription_end=subscription_end,
        )
        user = self.repo.create_user(tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin")
        r = self.client.post("/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        return tenant, {"Authorization": f"Bearer {r.json()['token']}"}

    def test_suspended_tenant_blocked_from_restricted_workspace_operation(self):
        tenant, headers = self._make_tenant_and_headers("SuspendMe")

        # Create some data while still active.
        analyze = self.client.post(
            "/api/analyze",
            json={"service_name": "Pre-suspension Service", "description": "x"},
            headers=headers,
        )
        self.assertEqual(analyze.status_code, 200)
        blueprint_id = analyze.json()["blueprint_id"]

        # Suspend the tenant.
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")

        # The SAME session token now gets 403 on a private workspace op.
        blocked = self.client.post(
            "/api/analyze",
            json={"service_name": "Should Be Blocked", "description": "x"},
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 403)

        blocked_get = self.client.get("/api/me", headers=headers)
        self.assertEqual(blocked_get.status_code, 403)

        # Data created before suspension is NOT deleted -- confirmed
        # directly (get_blueprint_for_tenant doesn't itself check
        # subscription status, only the auth-context-gated endpoints do).
        still_there = self.repo.get_tenant(tenant["id"])
        self.assertIsNotNone(still_there)
        blueprint = main_module.runtime_store.get_blueprint_for_tenant(blueprint_id, tenant["id"])
        self.assertIsNotNone(blueprint)

    def test_expired_subscription_end_date_blocks_workspace_but_not_public_service(self):
        past_date = "2000-01-01T00:00:00+00:00"
        tenant, headers = self._make_tenant_and_headers("ExpireMe")
        analyze = self.client.post(
            "/api/analyze",
            json={"service_name": "Expiring Soon Service", "description": "x"},
            headers=headers,
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        publish_agent = self.client.post("/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers)
        slug = publish_agent.json()["published_slug"]
        tenant_slug, agent_slug = slug.split("/", 1)

        # Now expire the subscription.
        with self.repo._connect() as connection:
            connection.execute(
                "UPDATE tenants SET subscription_end = ? WHERE id = ?",
                (past_date, tenant["id"]),
            )

        # Private workspace op now blocked.
        blocked = self.client.get("/api/me", headers=headers)
        self.assertEqual(blocked.status_code, 403)

        # The already-published PUBLIC customer-facing service is a
        # deliberate design choice: existing customers shouldn't be
        # cut off mid-journey just because the entity's back-office
        # subscription lapsed. It stays reachable.
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200)


if __name__ == "__main__":
    unittest.main()
