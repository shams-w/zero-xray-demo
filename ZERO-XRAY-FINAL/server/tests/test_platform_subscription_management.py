import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tenants.models import has_permission
from tenants.repository import TenantRepository
from tenants.service import is_tenant_workspace_available


def test_only_platform_admin_has_platform_tenant_management_permission():
    assert has_permission("platform_admin", "platform:manage_tenants")
    for role in ("entity_admin", "service_owner", "analyst", "viewer"):
        assert not has_permission(role, "platform:manage_tenants")


def test_platform_can_suspend_and_reactivate_without_deleting_tenant_data():
    with tempfile.TemporaryDirectory() as directory:
        repo = TenantRepository(database_path=Path(directory) / "runtime.db")
        tenant = repo.create_tenant("Demo Entity", "demo-entity", status="ACTIVE")
        user = repo.create_user(tenant["id"], "Admin", "admin@demo.test", "entity_admin")

        suspended = repo.update_tenant_subscription(tenant["id"], status="SUSPENDED")
        assert suspended["status"] == "SUSPENDED"
        assert not is_tenant_workspace_available(suspended)
        assert repo.get_user(user["id"])["tenant_id"] == tenant["id"]

        active = repo.update_tenant_subscription(tenant["id"], status="ACTIVE")
        assert active["status"] == "ACTIVE"
        assert is_tenant_workspace_available(active)
        assert repo.get_user(user["id"])["tenant_id"] == tenant["id"]


def test_expired_date_blocks_workspace_and_future_date_restores_access():
    with tempfile.TemporaryDirectory() as directory:
        repo = TenantRepository(database_path=Path(directory) / "runtime.db")
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        tenant = repo.create_tenant(
            "Subscription Entity", "subscription-entity", status="ACTIVE", subscription_end=past
        )
        assert not is_tenant_workspace_available(tenant)

        renewed = repo.update_tenant_subscription(
            tenant["id"], status="ACTIVE", subscription_end=future
        )
        assert renewed["subscription_end"] == future
        assert is_tenant_workspace_available(renewed)


def test_subscription_plan_and_end_date_update_are_additive_only():
    with tempfile.TemporaryDirectory() as directory:
        repo = TenantRepository(database_path=Path(directory) / "runtime.db")
        tenant = repo.create_tenant("Plan Entity", "plan-entity", status="ACTIVE")
        updated = repo.update_tenant_subscription(
            tenant["id"], subscription_plan="ENTERPRISE", subscription_end="2030-01-01T00:00:00+00:00"
        )
        assert updated["subscription_plan"] == "ENTERPRISE"
        assert updated["subscription_end"] == "2030-01-01T00:00:00+00:00"
        assert updated["name"] == "Plan Entity"
        assert updated["slug"] == "plan-entity"



def test_platform_context_does_not_lock_platform_admin_out_on_suspended_host(monkeypatch):
    from auth import dependencies as auth_dependencies

    with tempfile.TemporaryDirectory() as directory:
        repo = TenantRepository(database_path=Path(directory) / "runtime.db")
        tenant = repo.create_tenant("Platform Ops", "platform-ops-suspended", status="SUSPENDED")
        user = repo.create_user(tenant["id"], "Root", "root@platform.test", "platform_admin")

        class FakeProvider:
            def resolve_session(self, token):
                assert token == "platform-token"
                return {"user_id": user["id"], "tenant_id": tenant["id"]}

        monkeypatch.setattr(auth_dependencies, "_tenant_repository", repo)
        monkeypatch.setattr(auth_dependencies, "get_auth_provider", lambda: FakeProvider())

        context = auth_dependencies.get_platform_context("Bearer platform-token")
        assert context.user_id == user["id"]
        assert context.role == "platform_admin"
        assert context.tenant["status"] == "SUSPENDED"
        auth_dependencies.require_permission(context, "platform:manage_tenants")


def test_platform_context_does_not_grant_platform_permission_to_entity_admin(monkeypatch):
    from fastapi import HTTPException
    from auth import dependencies as auth_dependencies

    with tempfile.TemporaryDirectory() as directory:
        repo = TenantRepository(database_path=Path(directory) / "runtime.db")
        tenant = repo.create_tenant("Entity", "entity-admin-protected", status="ACTIVE")
        user = repo.create_user(tenant["id"], "Admin", "admin@entity.test", "entity_admin")

        class FakeProvider:
            def resolve_session(self, token):
                return {"user_id": user["id"], "tenant_id": tenant["id"]}

        monkeypatch.setattr(auth_dependencies, "_tenant_repository", repo)
        monkeypatch.setattr(auth_dependencies, "get_auth_provider", lambda: FakeProvider())

        context = auth_dependencies.get_platform_context("Bearer entity-token")
        try:
            auth_dependencies.require_permission(context, "platform:manage_tenants")
            assert False, "entity_admin must not receive platform tenant-management permission"
        except HTTPException as exc:
            assert exc.status_code == 403
