"""Tenant / user domain models for the ZERO X-RAY multi-tenant platform layer.

Phase 1 (foundation). These are plain dataclasses used by the repository
and service layers -- no ORM is introduced here, matching the existing
project's direct-SQLite style in `core/runtime_store.py`.
"""

from dataclasses import dataclass, field
from typing import Optional


# --- Tenant status -----------------------------------------------------

TENANT_STATUSES = {"ACTIVE", "PILOT", "SUSPENDED", "EXPIRED", "ARCHIVED"}

# A tenant workspace is usable when it is in one of these statuses AND
# its subscription dates (if set) are currently valid. See
# `tenants.service.is_tenant_workspace_available`.
TENANT_WORKSPACE_ALLOWED_STATUSES = {"ACTIVE", "PILOT"}

DEFAULT_TENANT_SLUG = "default-dev"
DEFAULT_TENANT_NAME = "Default Development Tenant"

# --- Roles ---------------------------------------------------------------

ROLES = {"platform_admin", "entity_admin", "service_owner", "analyst", "viewer"}

# Permission -> roles allowed. Enforced server-side in auth/dependencies.py.
# This is intentionally coarse for Phase 1; Phase 6 refines per-resource
# permission checks.
ROLE_PERMISSIONS = {
    "platform_admin": {
        "platform:manage_tenants",
        "platform:view_metadata",
    },
    "entity_admin": {
        "tenant:manage_users",
        "tenant:manage_services",
        "tenant:manage_agents",
        "tenant:manage_data_sources",
        "tenant:manage_integrations",
        "tenant:manage_settings",
        "tenant:analyze",
        "tenant:publish",
        "tenant:write",
        "tenant:read",
        "future:predict",
        "future:simulate",
        "future:challenge",
        "future:evolve",
        "future:prevent",
        "future:monitor",
    },
    "service_owner": {
        "tenant:manage_services",
        "tenant:manage_agents",
        "tenant:analyze",
        "tenant:publish",
        "tenant:write",
        "tenant:read",
        "future:predict",
        "future:simulate",
        "future:challenge",
        "future:evolve",
        "future:prevent",
        "future:monitor",
    },
    "analyst": {
        "tenant:analyze",
        "tenant:read",
        "future:predict",
        "future:simulate",
        "future:challenge",
    },
    "viewer": {
        "tenant:read",
    },
}

USER_STATUSES = {"ACTIVE", "SUSPENDED", "INVITED"}


@dataclass
class Tenant:
    id: str
    name: str
    slug: str
    status: str = "PILOT"
    subscription_plan: str = "PILOT"
    subscription_start: Optional[str] = None
    subscription_end: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class PlatformUser:
    id: str
    tenant_id: str
    name: str
    email: str
    role: str
    status: str = "ACTIVE"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
