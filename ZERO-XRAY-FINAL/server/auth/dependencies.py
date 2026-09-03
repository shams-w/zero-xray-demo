"""FastAPI dependency that implements the request pipeline:

    Request -> Authentication -> Resolve User -> Resolve Tenant ->
    Check Tenant Status -> Check Subscription -> Check Permission -> Execute

Critical rule: NO TENANT CONTEXT = NO ACCESS. tenant_id is *never*
accepted from a query param, path param, or request body for
tenant-owned resources -- it is only ever derived here, from the
authenticated session token, so a client cannot request another
tenant's data by editing a `tenant_id=` value.
"""

from fastapi import Header, HTTPException

from auth.service import get_auth_provider
from core.tenant_context import TenantContext
from tenants.repository import TenantRepository
from tenants.service import (
    SubscriptionExpiredError,
    TenantSuspendedError,
    assert_tenant_available,
)

_tenant_repository = TenantRepository()


def _resolve_authenticated_user_and_tenant(authorization: str):
    """Resolve a valid employee session without applying workspace availability.

    Platform-administration endpoints use this resolver so a platform admin can
    renew/reactivate a tenant even when the admin's host tenant is suspended or
    expired. Role/permission checks still happen server-side at each endpoint.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = authorization.split(" ", 1)[1].strip()

    try:
        session = get_auth_provider().resolve_session(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = _tenant_repository.get_user(session["user_id"])
    if not user or user["status"] != "ACTIVE":
        raise HTTPException(status_code=401, detail="User is not active.")

    tenant = _tenant_repository.get_tenant(user["tenant_id"])
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return session, user, tenant


def get_platform_context(authorization: str = Header(default=None)) -> TenantContext:
    """Authenticated context for platform-control-plane endpoints.

    Unlike tenant workspace requests, platform control operations must remain
    available to a platform admin while subscriptions/status are being repaired.
    This does not grant any permission: endpoints still require the platform
    permission explicitly through ``require_permission``.
    """
    session, user, tenant = _resolve_authenticated_user_and_tenant(authorization)
    return TenantContext(
        user_id=user["id"],
        tenant_id=tenant["id"],
        role=session.get("role") or user["role"],
        tenant=tenant,
    )


def get_tenant_context(authorization: str = Header(default=None)) -> TenantContext:
    session, user, tenant = _resolve_authenticated_user_and_tenant(authorization)
    try:
        assert_tenant_available(tenant)
    except TenantSuspendedError as exc:
        # PHASE 7: structured, stable-code detail so the frontend can
        # reliably distinguish "workspace subscription blocked" from any
        # other 403 without parsing English error text. Additive only --
        # `message` still carries the exact previous string.
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": str(exc)}) from exc
    except SubscriptionExpiredError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return TenantContext(
        user_id=user["id"],
        tenant_id=tenant["id"],
        role=session.get("role") or user["role"],
        tenant=tenant,
    )


def get_tenant_context_soft(authorization: str = Header(default=None)) -> TenantContext:
    """*** TRANSITIONAL, PHASE 2 ONLY ***
    Identical to `get_tenant_context` when a bearer token IS supplied
    (still authenticates strictly, still 401/403 on a bad/suspended/
    expired session -- a caller who presents credentials never gets a
    weaker check).

    When NO Authorization header is supplied at all, resolves to the
    default/dev tenant as an implicit entity_admin, instead of
    rejecting the request. This exists solely to satisfy Section 39
    backward compatibility while the current single-tenant frontend
    and the pre-Phase-1 test suite have not been updated to send a
    token yet -- every legacy caller was already implicitly operating
    against the one tenant that existed (`default-dev`), so this
    changes nothing about what data an unauthenticated legacy caller
    can reach. It must NOT be used to widen access for any endpoint
    that isn't already unauthenticated today, and it should be
    deleted once the frontend/tests are updated to always send a
    token (tracked as a Phase 2 cleanup item, not shipped as
    permanent platform behavior)."""
    if authorization:
        return get_tenant_context(authorization=authorization)
    default_tenant = _tenant_repository.get_tenant(_tenant_repository.default_tenant_id)
    return TenantContext(
        user_id="legacy-unauthenticated-caller",
        tenant_id=default_tenant["id"],
        role="entity_admin",
        tenant=default_tenant,
    )


def get_tenant_context_optional(authorization: str = Header(default=None)):
    """Genuinely optional -- returns None when no bearer token is
    supplied at all (used by the anonymous customer-facing journey
    endpoints, Section 42), and a real, strictly-checked TenantContext
    when one is (used to enforce tenant isolation against a logged-in
    tenant staff member trying to reach another tenant's journey by
    ID). Unlike `get_tenant_context_soft`, this NEVER falls back to
    the default tenant -- a journey can legitimately belong to ANY
    tenant, so silently substituting the default tenant here would
    incorrectly 404 a real anonymous customer's own journey."""
    if not authorization:
        return None
    return get_tenant_context(authorization=authorization)


def require_permission(context: TenantContext, permission: str):
    try:
        context.require(permission)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
