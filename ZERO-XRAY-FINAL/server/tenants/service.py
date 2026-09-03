"""Tenant business rules that sit above the raw repository:
subscription-validity checks and the atomic "create government entity"
flow (Section 23 / 44 of the multi-tenant spec).
"""

from datetime import datetime, timezone

from tenants.models import TENANT_WORKSPACE_ALLOWED_STATUSES
from tenants.repository import TenantRepository


class TenantSuspendedError(Exception):
    # PHASE 7: stable, machine-readable code so a caller (the frontend)
    # can reliably identify this exact condition without parsing the
    # English message text. Additive only -- str(exc) is unchanged, so
    # any existing consumer that only reads the exception message still
    # sees exactly what it saw before.
    code = "TENANT_SUSPENDED"


class SubscriptionExpiredError(Exception):
    code = "SUBSCRIPTION_EXPIRED"


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_tenant_workspace_available(tenant: dict) -> bool:
    """ACTIVE/PILOT status + (no dates set, or dates currently valid).
    Data is never deleted on expiry -- this only gates workspace access,
    per Section 20."""
    if not tenant:
        return False
    if tenant["status"] not in TENANT_WORKSPACE_ALLOWED_STATUSES:
        return False
    now = datetime.now(timezone.utc)
    end = _parse_date(tenant.get("subscription_end"))
    if end and end.replace(tzinfo=end.tzinfo or timezone.utc) < now:
        return False
    return True


def assert_tenant_available(tenant: dict):
    if not tenant:
        raise ValueError("Tenant not found.")
    if tenant["status"] == "SUSPENDED":
        raise TenantSuspendedError("This tenant workspace has been suspended.")
    if not is_tenant_workspace_available(tenant):
        raise SubscriptionExpiredError(
            "This tenant's subscription is expired or inactive. "
            "Existing data is preserved but the workspace is restricted."
        )


class QuotaExceededError(Exception):
    pass


def assert_within_quota(tenant: dict, current_count: int, limit_field: str, label: str):
    limit = tenant.get(limit_field)
    if limit is not None and current_count >= limit:
        raise QuotaExceededError(
            f"Tenant has reached its {label} limit ({limit}) for its {tenant.get('subscription_plan')} plan."
        )


class TenantService:
    def __init__(self, repository: TenantRepository = None):
        self.repository = repository or TenantRepository()

    def create_government_entity(
        self,
        entity_name,
        slug,
        subscription_plan,
        subscription_start,
        subscription_end,
        admin_name,
        admin_email,
    ):
        """Atomic-as-practical creation flow (Section 23): create the
        tenant, then its first entity_admin user. If user creation
        fails, roll the tenant back rather than leaving an orphaned
        half-created tenant."""
        tenant = self.repository.create_tenant(
            name=entity_name,
            slug=slug,
            subscription_plan=subscription_plan,
            subscription_start=subscription_start,
            subscription_end=subscription_end,
            status="PILOT",
        )
        try:
            admin_user = self.repository.create_user(
                tenant_id=tenant["id"],
                name=admin_name,
                email=admin_email,
                role="entity_admin",
                status="ACTIVE",
            )
        except Exception:
            self.repository.set_tenant_status(tenant["id"], "ARCHIVED")
            raise
        return {"tenant": tenant, "admin_user": admin_user}
