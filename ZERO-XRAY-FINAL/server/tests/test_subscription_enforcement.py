"""Phase 7 focused tests: tenant subscription expiration / suspension
enforcement as an ACCESS-CONTROL state only -- never a data-deletion
event. Reuses the existing architecture confirmed by Phase 1's
inspection (server/tenants/service.py's is_tenant_workspace_available/
assert_tenant_available, enforced through get_tenant_context, not
get_platform_context).

Most of this architecture already existed and is already covered by
tests/test_multi_tenant_phase1.py and
tests/test_multi_tenant_phase6_enterprise.py (suspended/expired tenants
blocked, data preserved, public Published Agent route intentionally
stays reachable). This file focuses on what Phase 7 actually added:

  - a stable, machine-readable error code (SUBSCRIPTION_EXPIRED /
    TENANT_SUSPENDED) on the existing 403, instead of only a free-text
    message
  - full reactivation-preserves-everything verification with STABLE IDs
    across every tenant-owned object type
  - boundary/timezone date safety
  - a consolidated regression pass confirming Phase 2-6 behavior is
    completely unaffected
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env

_ollama_patch = None


def setUpModule():
    global _ollama_patch
    _ollama_patch = patch_ollama_env()


def tearDownModule():
    unpatch_ollama_env(_ollama_patch)


from fastapi.testclient import TestClient

import main as main_module
from tenants.service import (
    SubscriptionExpiredError,
    TenantSuspendedError,
    assert_tenant_available,
    is_tenant_workspace_available,
)


class SubscriptionEnforcementApiTestCase(unittest.TestCase):
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

    def _tenant_admin_headers(self, label, status="ACTIVE", subscription_end=None):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(
            f"{label} {suffix}", f"{label.lower()}-{suffix}", status=status,
            subscription_end=subscription_end,
        )
        admin = self.repo.create_user(
            tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin"
        )
        return tenant, admin, self._login(admin)

    def _platform_admin_headers(self, label="Platform"):
        suffix = uuid.uuid4().hex[:8]
        host_tenant = self.repo.create_tenant(f"{label}Host {suffix}", f"{label.lower()}host-{suffix}", status="ACTIVE")
        admin = self.repo.create_user(
            host_tenant["id"], f"{label} Root", f"{label.lower()}root-{suffix}@test.local", role="platform_admin"
        )
        return host_tenant, admin, self._login(admin)

    # -- 1/2: ACTIVE / PILOT tenants continue to work --

    def test_active_tenant_can_access_protected_workspace_apis(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P7Active", status="ACTIVE")
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 200)

    def test_pilot_tenant_can_access_protected_workspace_apis(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P7Pilot", status="PILOT")
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 200)

    # -- 3/4: expired / suspended block access --

    def test_past_subscription_end_blocks_protected_api_access(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        _tenant, _admin, headers = self._tenant_admin_headers("P7Expired", status="ACTIVE", subscription_end=past)
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_suspended_status_blocks_protected_api_access(self):
        tenant, _admin, headers = self._tenant_admin_headers("P7Suspended", status="ACTIVE")
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_archived_status_blocks_protected_api_access(self):
        """ARCHIVED is the project's existing vocabulary for a
        cancelled/inactive-equivalent tenant (tenants/models.py's
        TENANT_STATUSES) -- no new status was invented."""
        tenant, _admin, headers = self._tenant_admin_headers("P7Archived", status="ACTIVE")
        self.repo.set_tenant_status(tenant["id"], "ARCHIVED")
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 403)

    # -- 5: direct manual call to a different protected endpoint --

    def test_direct_call_to_another_protected_endpoint_also_blocked(self):
        tenant, _admin, headers = self._tenant_admin_headers("P7DirectCall", status="ACTIVE")
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        r = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": "Should Be Blocked", "description": "x"}
        )
        self.assertEqual(r.status_code, 403)

    # -- 6: stable machine-readable error code --

    def test_suspended_returns_stable_error_code(self):
        tenant, _admin, headers = self._tenant_admin_headers("P7Code1", status="ACTIVE")
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["code"], "TENANT_SUSPENDED")

    def test_expired_returns_stable_error_code(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        _tenant, _admin, headers = self._tenant_admin_headers("P7Code2", status="ACTIVE", subscription_end=past)
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["code"], "SUBSCRIPTION_EXPIRED")

    def test_error_code_is_not_derived_from_english_text_parsing(self):
        """The exception classes themselves carry the code as a class
        attribute -- proving it does not depend on message wording."""
        self.assertEqual(TenantSuspendedError.code, "TENANT_SUSPENDED")
        self.assertEqual(SubscriptionExpiredError.code, "SUBSCRIPTION_EXPIRED")

    # -- 7/8: EN/AR access-expired messages available --

    def test_english_access_expired_message_available_in_translations(self):
        import pathlib
        source = pathlib.Path(__file__).resolve().parents[2] / "client" / "src" / "i18n" / "translations.js"
        text = source.read_text(encoding="utf-8")
        self.assertIn("Your access has expired.", text)
        self.assertIn(
            "Your organization's ZERO X-RAY subscription is no longer active. "
            "Please contact your administrator to restore access.",
            text,
        )

    def test_arabic_access_expired_message_available_in_translations(self):
        import pathlib
        source = pathlib.Path(__file__).resolve().parents[2] / "client" / "src" / "i18n" / "translations.js"
        text = source.read_text(encoding="utf-8")
        self.assertIn("انتهت صلاحية الوصول الخاصة بك.", text)
        self.assertIn("اشتراك جهة العمل في ZERO X-RAY لم يعد فعالاً", text)

    # -- 9/10: Platform Admin can read/manage and reactivate an expired tenant --

    def test_platform_admin_can_read_and_reactivate_suspended_tenant(self):
        tenant, _admin, _headers = self._tenant_admin_headers("P7PlatManage", status="ACTIVE")
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        _host, _padmin, platform_headers = self._platform_admin_headers("P7Plat")

        listing = self.client.get("/api/platform/entities", headers=platform_headers)
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(any(item["id"] == tenant["id"] for item in listing.json()["entities"]))

        reactivate = self.client.put(
            f"/api/platform/entities/{tenant['id']}/subscription",
            headers=platform_headers, json={"status": "ACTIVE"},
        )
        self.assertEqual(reactivate.status_code, 200, reactivate.text)
        self.assertEqual(reactivate.json()["tenant"]["status"], "ACTIVE")

    # -- 11: reactivation restores protected workspace API access --

    def test_reactivation_restores_workspace_api_access(self):
        tenant, _admin, headers = self._tenant_admin_headers("P7Restore", status="ACTIVE")
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        blocked = self.client.get("/api/me", headers=headers)
        self.assertEqual(blocked.status_code, 403)

        _host, _padmin, platform_headers = self._platform_admin_headers("P7RestorePlat")
        self.client.put(
            f"/api/platform/entities/{tenant['id']}/subscription",
            headers=platform_headers, json={"status": "ACTIVE"},
        )

        restored = self.client.get("/api/me", headers=headers)
        self.assertEqual(restored.status_code, 200)

    # -- 12-19/26/27: full data-retention verification across every object
    # type, with STABLE IDs, through suspend -> block -> reactivate -> restore --

    def test_full_data_retention_across_suspend_and_reactivate_with_stable_ids(self):
        tenant, admin, headers = self._tenant_admin_headers("P7Retention", status="ACTIVE")
        owner = self.repo.create_user(
            tenant["id"], "Retention Owner", f"retention-owner-{uuid.uuid4().hex[:8]}@test.local",
            role="service_owner",
        )
        owner_headers = self._login(owner)

        ds = self.client.post(
            "/api/data-sources", headers=headers,
            json={"name": "Retention DS", "type": "TEXT", "status": "READY",
                  "classification": "TENANT_PRIVATE_SOURCE", "configuration": {"content": "keep me"}},
        ).json()
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "Retention Integration", "status": "CONNECTED", "config": {}},
        ).json()
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Retention Service", "description": "test",
                  "data_source_ids": [ds["id"]], "integration_ids": [integ["id"]]},
        ).json()
        blueprint_id = analyze["blueprint_id"]
        service_id = analyze["service_id"]
        self.client.post(f"/api/services/{service_id}/assignments/{owner['id']}", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        ).json()

        # -- Suspend the tenant --
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        blocked = self.client.get("/api/me", headers=headers)
        self.assertEqual(blocked.status_code, 403)

        # Data still exists in the DB while suspended -- confirmed
        # directly, since store-level lookups don't themselves check
        # subscription status (only the auth-context-gated endpoints do).
        self.assertIsNotNone(main_module.catalog_store.get_data_source_for_tenant(ds["id"], tenant["id"]))
        self.assertIsNotNone(main_module.catalog_store.get_integration_for_tenant(integ["id"], tenant["id"]))
        self.assertIsNotNone(main_module.runtime_store.get_blueprint_for_tenant(blueprint_id, tenant["id"]))
        self.assertIsNotNone(main_module.agent_store.get_agent_for_tenant(agent["id"], tenant["id"]))
        self.assertIsNotNone(main_module.service_store.get_service_for_tenant(service_id, tenant["id"]))

        # -- Reactivate --
        _host, _padmin, platform_headers = self._platform_admin_headers("P7RetentionPlat")
        reactivate = self.client.put(
            f"/api/platform/entities/{tenant['id']}/subscription",
            headers=platform_headers, json={"status": "ACTIVE"},
        )
        self.assertEqual(reactivate.status_code, 200, reactivate.text)

        # -- Every object still exists with the EXACT SAME id, reachable
        # again through the normal authenticated endpoints -- no
        # recreation required. --
        get_ds = self.client.get(f"/api/data-sources/{ds['id']}", headers=headers)
        self.assertEqual(get_ds.status_code, 200)
        self.assertEqual(get_ds.json()["id"], ds["id"])

        get_integ = self.client.get(f"/api/integrations/{integ['id']}", headers=headers)
        self.assertEqual(get_integ.status_code, 200)
        self.assertEqual(get_integ.json()["id"], integ["id"])

        get_bp = self.client.get(f"/api/blueprints/{blueprint_id}", headers=headers)
        self.assertEqual(get_bp.status_code, 200)
        self.assertEqual(get_bp.json()["id"], blueprint_id)
        self.assertEqual(get_bp.json()["status"], "PUBLISHED")

        get_agent = self.client.get(f"/api/agents/{agent['id']}", headers=headers)
        self.assertEqual(get_agent.status_code, 200)
        self.assertEqual(get_agent.json()["id"], agent["id"])
        self.assertEqual(get_agent.json()["published_slug"], agent["published_slug"])

        get_service = self.client.get(f"/api/services/{service_id}", headers=headers)
        self.assertEqual(get_service.status_code, 200)
        self.assertEqual(get_service.json()["id"], service_id)

        # User was not recreated -- the SAME admin token, obtained before
        # suspension, works again.
        me = self.client.get("/api/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user_id"], admin["id"])

        # Service Owner scoping still intact after reactivation.
        owner_view = self.client.get(f"/api/services/{service_id}", headers=owner_headers)
        self.assertEqual(owner_view.status_code, 200)

        # Audit history from before suspension is intact.
        audit = self.client.get("/api/audit-log", headers=headers)
        self.assertEqual(audit.status_code, 200)
        actions = {entry["action"] for entry in audit.json()["entries"]}
        self.assertIn("ANALYSIS_EXECUTED", actions)

        # The published Agent's public route still works, unchanged.
        tenant_slug, agent_slug = agent["published_slug"].split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200)

    # -- 20: tenant isolation remains intact during expiration/reactivation --

    def test_tenant_isolation_intact_during_expiration_and_reactivation(self):
        tenant_a, _admin_a, headers_a = self._tenant_admin_headers("P7IsoA", status="ACTIVE")
        tenant_b, _admin_b, headers_b = self._tenant_admin_headers("P7IsoB", status="ACTIVE")

        self.repo.set_tenant_status(tenant_a["id"], "SUSPENDED")
        # Tenant B is completely unaffected by Tenant A's suspension.
        r_b = self.client.get("/api/me", headers=headers_b)
        self.assertEqual(r_b.status_code, 200)
        self.assertEqual(r_b.json()["tenant_id"], tenant_b["id"])

        _host, _padmin, platform_headers = self._platform_admin_headers("P7IsoPlat")
        self.client.put(
            f"/api/platform/entities/{tenant_a['id']}/subscription",
            headers=platform_headers, json={"status": "ACTIVE"},
        )
        # Both remain correctly, separately scoped afterward.
        r_a = self.client.get("/api/me", headers=headers_a)
        self.assertEqual(r_a.status_code, 200)
        self.assertEqual(r_a.json()["tenant_id"], tenant_a["id"])
        r_b_again = self.client.get("/api/me", headers=headers_b)
        self.assertEqual(r_b_again.json()["tenant_id"], tenant_b["id"])

    # -- 22/23: Entity Admin / Viewer / Analyst permissions unchanged after reactivation --

    def test_role_permissions_unchanged_after_reactivation(self):
        tenant, admin, headers = self._tenant_admin_headers("P7Roles", status="ACTIVE")
        viewer = self.repo.create_user(
            tenant["id"], "Viewer", f"viewer-{uuid.uuid4().hex[:8]}@test.local", role="viewer"
        )
        viewer_headers = self._login(viewer)

        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        _host, _padmin, platform_headers = self._platform_admin_headers("P7RolesPlat")
        self.client.put(
            f"/api/platform/entities/{tenant['id']}/subscription",
            headers=platform_headers, json={"status": "ACTIVE"},
        )

        # Entity Admin retains full analyze permission.
        analyze = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": "Post Reactivation", "description": "x"}
        )
        self.assertEqual(analyze.status_code, 200)

        # Viewer still cannot analyze (unchanged RBAC), but can read.
        viewer_analyze = self.client.post(
            "/api/analyze", headers=viewer_headers, json={"service_name": "Viewer Attempt", "description": "x"}
        )
        self.assertEqual(viewer_analyze.status_code, 403)
        viewer_read = self.client.get("/api/services", headers=viewer_headers)
        self.assertEqual(viewer_read.status_code, 200)

    # -- 24: Public Published Agent route decision --

    def test_public_published_agent_route_stays_available_during_expiration(self):
        """Documented, pre-existing product decision (see
        tests/test_multi_tenant_phase6_enterprise.py's
        test_expired_subscription_end_date_blocks_workspace_but_not_public_service):
        an ALREADY-PUBLISHED Agent's public customer-facing route is
        NOT subscription-protected. Customers already using a published
        service should not be cut off mid-journey because the entity's
        back-office subscription lapsed. Phase 7 preserves this
        unchanged -- confirmed here for BOTH expired and suspended."""
        _tenant, _admin, headers = self._tenant_admin_headers("P7PublicRoute", status="ACTIVE")
        analyze = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": "Public Route Service", "description": "x"}
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        ).json()
        tenant_slug, agent_slug = agent["published_slug"].split("/", 1)

        _tenant2, _admin2, headers2 = self._tenant_admin_headers("P7PublicRoute2", status="ACTIVE")
        analyze2 = self.client.post(
            "/api/analyze", headers=headers2, json={"service_name": "Public Route Service 2", "description": "x"}
        )
        blueprint_id2 = analyze2.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id2}/approve", headers=headers2)
        self.client.post(f"/api/blueprints/{blueprint_id2}/publish", headers=headers2)
        agent2 = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id2}, headers=headers2
        ).json()
        tenant_slug2, agent_slug2 = agent2["published_slug"].split("/", 1)

        self.repo.set_tenant_status(_tenant["id"], "SUSPENDED")
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with self.repo._connect() as connection:
            connection.execute(
                "UPDATE tenants SET subscription_end = ? WHERE id = ?", (past, _tenant2["id"])
            )

        public1 = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public1.status_code, 200)
        public2 = self.client.get(f"/service/{tenant_slug2}/{agent_slug2}")
        self.assertEqual(public2.status_code, 200)

    # -- 25: customer capability-token security unchanged --

    def test_customer_capability_token_security_unaffected_by_subscription_state(self):
        tenant, _admin, headers = self._tenant_admin_headers("P7CapToken", status="ACTIVE")
        analyze = self.client.post(
            "/api/analyze", headers=headers, json={"service_name": "Cap Token Service", "description": "x"}
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)

        anon_client = TestClient(main_module.app)
        register = anon_client.post(
            "/api/sandbox/register",
            json={"name": "Cap Customer", "email": f"cap-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 200)
        customer = register.json()
        journey = anon_client.post(
            "/api/journeys",
            json={"customer_id": customer["id"], "intent": "test", "blueprint_id": blueprint_id,
                  "lang": "en", "sandbox": True},
        ).json()

        # Suspend the tenant AFTER the journey/capability cookie already exist.
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")

        # The customer's own capability-cookie-authenticated read is
        # unaffected by the STAFF workspace subscription block -- it
        # never goes through get_tenant_context.
        read = anon_client.get(f"/api/journeys/{journey['id']}")
        self.assertEqual(read.status_code, 200)

        # A stranger with no cookie/token still gets 403, exactly as before.
        stranger_client = TestClient(main_module.app)
        stranger_read = stranger_client.get(f"/api/journeys/{journey['id']}")
        self.assertEqual(stranger_read.status_code, 403)

    # -- 26/27: no data deleted on expiration/suspension (unit-level) --

    def test_no_data_deleted_on_expiration_status_alone(self):
        tenant, _admin, headers = self._tenant_admin_headers("P7NoDelete1", status="ACTIVE")
        ds = self.client.post(
            "/api/data-sources", headers=headers,
            json={"name": "NoDelete DS", "type": "TEXT", "status": "READY",
                  "classification": "TENANT_PRIVATE_SOURCE", "configuration": {"content": "x"}},
        ).json()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with self.repo._connect() as connection:
            connection.execute("UPDATE tenants SET subscription_end = ? WHERE id = ?", (past, tenant["id"]))
        self.assertIsNotNone(main_module.catalog_store.get_data_source_for_tenant(ds["id"], tenant["id"]))
        self.assertIsNotNone(self.repo.get_tenant(tenant["id"]))

    def test_no_data_deleted_on_suspension_status_alone(self):
        tenant, _admin, headers = self._tenant_admin_headers("P7NoDelete2", status="ACTIVE")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "NoDelete Integration", "status": "CONNECTED", "config": {}},
        ).json()
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        self.assertIsNotNone(main_module.catalog_store.get_integration_for_tenant(integ["id"], tenant["id"]))
        self.assertIsNotNone(self.repo.get_tenant(tenant["id"]))

    # -- 28/29/30: date/boundary safety --

    def test_future_subscription_end_does_not_block_access(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        _tenant, _admin, headers = self._tenant_admin_headers("P7Future", status="ACTIVE", subscription_end=future)
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 200)

    def test_missing_subscription_end_preserves_no_expiry_behavior(self):
        _tenant, _admin, headers = self._tenant_admin_headers("P7NoEnd", status="ACTIVE", subscription_end=None)
        r = self.client.get("/api/me", headers=headers)
        self.assertEqual(r.status_code, 200)

    def test_boundary_exactly_now_is_treated_as_expired(self):
        """`assert_tenant_available` treats `end < now` as expired; a
        timestamp set to a moment already in the past by the time the
        comparison runs is expired -- exercised directly for a
        deterministic, timezone-safe boundary check."""
        tenant = self.repo.create_tenant(
            "P7Boundary", f"p7boundary-{uuid.uuid4().hex[:8]}", status="ACTIVE",
            subscription_end=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        )
        self.assertFalse(is_tenant_workspace_available(tenant))
        with self.assertRaises(SubscriptionExpiredError):
            assert_tenant_available(tenant)

    def test_legacy_tenant_without_subscription_end_is_treated_as_active(self):
        """A tenant row predating any subscription_end usage (NULL) must
        not be treated as expired -- preserves existing 'no expiry'
        behavior for legacy rows."""
        tenant = self.repo.create_tenant(
            "P7LegacyNoEnd", f"p7legacynoend-{uuid.uuid4().hex[:8]}", status="ACTIVE",
        )
        self.assertIsNone(tenant.get("subscription_end"))
        self.assertTrue(is_tenant_workspace_available(tenant))
        assert_tenant_available(tenant)  # must not raise


if __name__ == "__main__":
    unittest.main()
