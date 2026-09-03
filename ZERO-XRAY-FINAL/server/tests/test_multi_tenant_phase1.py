"""Phase 1 multi-tenant foundation tests (Section 38 of the platform
spec): tenant schema/migration, tenant-scoped Blueprint lookups,
demo auth + TenantContext resolution, role permissions, subscription
gating, and the atomic government-entity creation flow.

Uses a fresh temp-directory SQLite file per test, exactly like the
existing `test_runtime_and_constraints.py`, so these tests never touch
the real `server/data/runtime.db`.
"""

import tempfile
import unittest
from pathlib import Path

from auth.dependencies import get_tenant_context, require_permission
from auth.service import DemoAuthProvider
from core.runtime_store import RuntimeStore
from core.tenant_context import TenantContext
from tenants.models import has_permission
from tenants.repository import TenantRepository
from tenants.service import (
    SubscriptionExpiredError,
    TenantSuspendedError,
    TenantService,
    assert_tenant_available,
    is_tenant_workspace_available,
)


class TenantMigrationTestCase(unittest.TestCase):
    def test_legacy_blueprint_rows_backfilled_to_default_tenant_not_null(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "runtime.db"
            store = RuntimeStore(db_path)
            blueprint = store.save_blueprint(
                {"service_name": "Legacy Service"}, {"score": 1}
            )
            # save_blueprint was called with no tenant_id, matching every
            # pre-Phase-1 call site -- it must fall back to the default
            # tenant rather than leaving tenant_id NULL.
            self.assertEqual(blueprint["tenant_id"], store.default_tenant_id)
            self.assertIsNotNone(blueprint["tenant_id"])

    def test_migration_is_idempotent_on_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "runtime.db"
            store1 = RuntimeStore(db_path)
            blueprint = store1.save_blueprint({"service_name": "X"}, {})
            # Reopening (simulating a server restart) must not error and
            # must not reassign an already-tenant-owned row.
            store2 = RuntimeStore(db_path)
            reloaded = store2.get_blueprint(blueprint["id"])
            self.assertEqual(reloaded["tenant_id"], blueprint["tenant_id"])


class TenantIsolationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.store = RuntimeStore(self.db_path)
        self.repo = self.store._tenant_repository
        self.tenant_a = self.repo.create_tenant("Emirates Post", "emirates-post", status="ACTIVE")
        self.tenant_b = self.repo.create_tenant("Entity B", "entity-b", status="ACTIVE")

    def tearDown(self):
        self._tmp.cleanup()

    def test_tenant_b_cannot_fetch_tenant_a_blueprint_by_valid_uuid(self):
        blueprint = self.store.save_blueprint(
            {"service_name": "Emirates Post Renewal"}, {"score": 5},
            tenant_id=self.tenant_a["id"],
        )
        # Tenant B guessing/using Tenant A's real Blueprint UUID must
        # get nothing back -- not the record, not a distinguishing error.
        result = self.store.get_blueprint_for_tenant(blueprint["id"], self.tenant_b["id"])
        self.assertIsNone(result)
        # Tenant A can still fetch its own.
        own = self.store.get_blueprint_for_tenant(blueprint["id"], self.tenant_a["id"])
        self.assertEqual(own["id"], blueprint["id"])

    def test_set_blueprint_status_is_tenant_scoped(self):
        blueprint = self.store.save_blueprint(
            {"service_name": "Svc"}, {}, tenant_id=self.tenant_a["id"]
        )
        # Tenant B cannot change Tenant A's Blueprint status by ID.
        result = self.store.set_blueprint_status(
            blueprint["id"], "APPROVED", tenant_id=self.tenant_b["id"]
        )
        self.assertIsNone(result)
        still_draft = self.store.get_blueprint_for_tenant(blueprint["id"], self.tenant_a["id"])
        self.assertEqual(still_draft["status"], "DRAFT")

    def test_journey_inherits_tenant_from_its_blueprint(self):
        blueprint = self.store.save_blueprint(
            {"service_name": "Renew PO Box"}, {}, tenant_id=self.tenant_a["id"]
        )
        self.store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=self.tenant_a["id"])
        self.store.set_blueprint_status(blueprint["id"], "PUBLISHED", tenant_id=self.tenant_a["id"])
        customer = self.store.register_customer("Ali", "ali@example.com", tenant_id=self.tenant_a["id"])
        journey = self.store.create_journey(
            customer["id"], "Renew PO Box", blueprint_id=blueprint["id"], sandbox=True
        )
        # Confirmed via direct row check since get_journey doesn't
        # project tenant_id in Phase 1 (Phase 2 adds
        # get_journey_for_tenant alongside endpoint wiring).
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT tenant_id FROM journeys WHERE id = ?", (journey["id"],)
            ).fetchone()
        self.assertEqual(row["tenant_id"], self.tenant_a["id"])


class RolePermissionTestCase(unittest.TestCase):
    def test_viewer_cannot_manage_services(self):
        self.assertFalse(has_permission("viewer", "tenant:manage_services"))

    def test_entity_admin_can_manage_own_tenant(self):
        self.assertTrue(has_permission("entity_admin", "tenant:manage_services"))
        self.assertTrue(has_permission("entity_admin", "tenant:manage_users"))

    def test_analyst_cannot_manage_tenant_configuration(self):
        self.assertFalse(has_permission("analyst", "tenant:manage_settings"))
        self.assertTrue(has_permission("analyst", "tenant:read"))

    def test_only_platform_admin_can_manage_tenants(self):
        self.assertTrue(has_permission("platform_admin", "platform:manage_tenants"))
        for role in ("entity_admin", "service_owner", "analyst", "viewer"):
            self.assertFalse(has_permission(role, "platform:manage_tenants"))


class SubscriptionGatingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = TenantRepository(database_path=Path(self._tmp.name) / "runtime.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_active_tenant_with_no_dates_is_available(self):
        tenant = self.repo.create_tenant("Active Co", "active-co", status="ACTIVE")
        self.assertTrue(is_tenant_workspace_available(tenant))
        assert_tenant_available(tenant)  # should not raise

    def test_suspended_tenant_is_blocked(self):
        tenant = self.repo.create_tenant("Bad Co", "bad-co", status="ACTIVE")
        self.repo.set_tenant_status(tenant["id"], "SUSPENDED")
        suspended = self.repo.get_tenant(tenant["id"])
        with self.assertRaises(TenantSuspendedError):
            assert_tenant_available(suspended)

    def test_expired_subscription_end_date_blocks_but_keeps_data(self):
        tenant = self.repo.create_tenant(
            "Expired Co", "expired-co", status="ACTIVE",
            subscription_end="2020-01-01T00:00:00+00:00",
        )
        self.assertFalse(is_tenant_workspace_available(tenant))
        with self.assertRaises(SubscriptionExpiredError):
            assert_tenant_available(tenant)
        # Data is never deleted on expiry -- the tenant row itself
        # still exists and is fetchable.
        self.assertIsNotNone(self.repo.get_tenant(tenant["id"]))


class DemoAuthAndContextTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = TenantRepository(database_path=Path(self._tmp.name) / "runtime.db")
        self.provider = DemoAuthProvider(repository=self.repo)
        self.tenant = self.repo.create_tenant("Emirates Post", "ep-auth-test", status="ACTIVE")
        self.user = self.repo.create_user(
            self.tenant["id"], "Fatima", "fatima@ep.test", role="entity_admin"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_correct_credential_issues_session_resolvable_to_tenant(self):
        session = self.provider.authenticate("fatima@ep.test", "zxr-demo-2026")
        resolved = self.provider.resolve_session(session["token"])
        self.assertEqual(resolved["tenant_id"], self.tenant["id"])
        self.assertEqual(resolved["user_id"], self.user["id"])

    def test_wrong_credential_rejected(self):
        with self.assertRaises(ValueError):
            self.provider.authenticate("fatima@ep.test", "wrong-passphrase")

    def test_unknown_email_rejected(self):
        with self.assertRaises(ValueError):
            self.provider.authenticate("nobody@ep.test", "zxr-demo-2026")

    def test_invalid_token_rejected(self):
        with self.assertRaises(ValueError):
            self.provider.resolve_session("not-a-real-token")


class GovernmentEntityCreationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = TenantRepository(database_path=Path(self._tmp.name) / "runtime.db")
        self.service = TenantService(repository=self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_tenant_and_entity_admin_together(self):
        result = self.service.create_government_entity(
            entity_name="Government Entity Demo",
            slug="gov-entity-demo",
            subscription_plan="PILOT",
            subscription_start=None,
            subscription_end=None,
            admin_name="Omar",
            admin_email="omar@gov-entity-demo.test",
        )
        self.assertEqual(result["tenant"]["slug"], "gov-entity-demo")
        self.assertEqual(result["admin_user"]["role"], "entity_admin")
        self.assertEqual(result["admin_user"]["tenant_id"], result["tenant"]["id"])

    def test_duplicate_slug_rejected_without_orphaning_a_tenant(self):
        self.service.create_government_entity(
            "First", "dup-slug", "PILOT", None, None, "A", "a@dup.test"
        )
        with self.assertRaises(ValueError):
            self.service.create_government_entity(
                "Second", "dup-slug", "PILOT", None, None, "B", "b@dup.test"
            )
        tenants = self.repo.list_tenants()
        slugs = [t["slug"] for t in tenants]
        self.assertEqual(slugs.count("dup-slug"), 1)


if __name__ == "__main__":
    unittest.main()
