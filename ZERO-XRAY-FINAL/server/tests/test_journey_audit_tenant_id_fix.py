"""Regression tests for the journey-lifecycle audit-log tenant_id fix.

Previously, `PAYMENT_CONFIRMED`, `EXECUTION_STARTED`, and `COMPLETED`
audit entries were written via `_audit(...)` with no `tenant_id`
argument, so `_audit`'s own fallback (`tenant_id or
self.default_tenant_id`) silently attributed them to the default/dev
tenant instead of the Journey's real owning tenant. The same bug was
found (while confirming no other calls were missing it) in
`PLAN_EDITED`, `PLAN_APPROVED`, and `PAYMENT_ASSESSMENT_READY`, and
fixed identically.

The relationship enforced here: Journey -> tenant_id -> Audit Entry,
for every lifecycle action, with no default-tenant fallback whenever
the Journey already has an owning tenant.
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


class JourneyLifecycleAuditTenantIdTestCase(unittest.TestCase):
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

    def test_full_journey_lifecycle_audit_entries_use_owning_tenant(self):
        tenant_a, headers_a = self._make_tenant_and_headers("AuditFixA")
        tenant_b, headers_b = self._make_tenant_and_headers("AuditFixB")
        default_tenant_id = main_module.runtime_store.default_tenant_id

        # Build a paid, executable service under Tenant A so the full
        # PAYMENT_CONFIRMED / EXECUTION_STARTED / COMPLETED sequence
        # actually fires (not every service requires payment).
        analyze = self.client.post(
            "/api/analyze",
            json={
                "service_name": "Audit Fix Corporate PO Box Renewal",
                "description": "Corporate customers renew their post office box and pay an annual fee.",
            },
            headers=headers_a,
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_a)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers_a)

        register = self.client.post(
            "/api/sandbox/register",
            json={"name": "Audit Customer", "email": f"auditfix-{uuid.uuid4().hex[:6]}@t.test", "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 200)
        customer_id = register.json()["id"]

        journey = self.client.post("/api/journeys", json={
            "customer_id": customer_id,
            "intent": "Audit Fix Corporate PO Box Renewal",
            "blueprint_id": blueprint_id,
            "sandbox": True,
        })
        self.assertEqual(journey.status_code, 200, journey.text)
        journey_id = journey.json()["id"]

        # 1. Approve
        approve = self.client.post(f"/api/journeys/{journey_id}/approve")
        self.assertEqual(approve.status_code, 200, approve.text)
        requires_payment = bool(approve.json()["plan"].get("requires_payment"))

        # 2. Pay (only if this service requires it)
        if requires_payment:
            assessment = self.client.post(f"/api/journeys/{journey_id}/payment-assessment")
            self.assertEqual(assessment.status_code, 200, assessment.text)
            payment = self.client.post(
                f"/api/journeys/{journey_id}/payment",
                json={"payment_method": "SANDBOX_CARD", "approved": True},
            )
            self.assertEqual(payment.status_code, 200, payment.text)

        # 3. Start execution
        execute = self.client.post(f"/api/journeys/{journey_id}/execute")
        self.assertEqual(execute.status_code, 200, execute.text)

        # 4. Complete (directly via the store -- mirrors what the SSE
        # stream's final step does; exercised independently of SSE
        # timing here so the test is deterministic).
        main_module.runtime_store.complete_journey(journey_id)

        # --- Verify: every lifecycle audit entry landed under Tenant A ---
        entries_a = main_module.runtime_store.list_audit_log_for_tenant(tenant_a["id"])
        actions_a = {e["action"] for e in entries_a if e["entity_id"] == journey_id}

        expected_actions = {"PLAN_READY", "PLAN_APPROVED", "EXECUTION_STARTED", "COMPLETED"}
        if requires_payment:
            expected_actions |= {"PAYMENT_ASSESSMENT_READY", "PAYMENT_CONFIRMED"}
        self.assertTrue(
            expected_actions.issubset(actions_a),
            f"Missing expected actions in Tenant A's audit log: {expected_actions - actions_a}",
        )

        for entry in entries_a:
            if entry["entity_id"] == journey_id:
                self.assertEqual(entry["tenant_id"], tenant_a["id"])
                self.assertNotEqual(entry["tenant_id"], default_tenant_id)

        # --- Verify: none of these entries leak into Tenant B's audit log ---
        entries_b = main_module.runtime_store.list_audit_log_for_tenant(tenant_b["id"])
        self.assertFalse(any(e["entity_id"] == journey_id for e in entries_b))

        # --- Verify: none of these entries were mis-filed under the
        # default/dev tenant either. ---
        entries_default = main_module.runtime_store.list_audit_log_for_tenant(default_tenant_id)
        self.assertFalse(any(e["entity_id"] == journey_id for e in entries_default))

        # --- Verify over the live API too (Tenant B genuinely cannot
        # see any of it, Tenant A genuinely can). ---
        api_entries_b = self.client.get("/api/audit-log", headers=headers_b).json()["entries"]
        self.assertFalse(any(e["entity_id"] == journey_id for e in api_entries_b))

        api_entries_a = self.client.get("/api/audit-log", headers=headers_a).json()["entries"]
        api_actions_a = {e["action"] for e in api_entries_a if e["entity_id"] == journey_id}
        self.assertTrue(expected_actions.issubset(api_actions_a))

    def test_edit_plan_audit_entry_uses_owning_tenant_not_default(self):
        tenant_a, headers_a = self._make_tenant_and_headers("AuditFixEditA")
        default_tenant_id = main_module.runtime_store.default_tenant_id

        analyze = self.client.post(
            "/api/analyze",
            json={"service_name": "Audit Fix Edit Service", "description": "x"},
            headers=headers_a,
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_a)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers_a)

        register = self.client.post(
            "/api/sandbox/register",
            json={"name": "Edit Customer", "email": f"editfix-{uuid.uuid4().hex[:6]}@t.test", "blueprint_id": blueprint_id},
        )
        customer_id = register.json()["id"]
        journey = self.client.post("/api/journeys", json={
            "customer_id": customer_id,
            "intent": "Audit Fix Edit Service",
            "blueprint_id": blueprint_id,
            "sandbox": True,
        })
        journey_id = journey.json()["id"]

        edit = self.client.post(f"/api/journeys/{journey_id}/edit", json={"instruction": "please adjust"})
        self.assertEqual(edit.status_code, 200, edit.text)

        entries_a = main_module.runtime_store.list_audit_log_for_tenant(tenant_a["id"])
        edit_entries = [e for e in entries_a if e["entity_id"] == journey_id and e["action"] == "PLAN_EDITED"]
        self.assertTrue(edit_entries)
        for entry in edit_entries:
            self.assertEqual(entry["tenant_id"], tenant_a["id"])
            self.assertNotEqual(entry["tenant_id"], default_tenant_id)


if __name__ == "__main__":
    unittest.main()
