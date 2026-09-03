"""The request-scoped context every tenant-owned endpoint resolves to:

    Request -> Authentication -> Resolve User -> Resolve Tenant ->
    Check Tenant Status -> Check Subscription -> Check Permission -> Execute

See `auth/dependencies.py` for the FastAPI dependency that builds this.
Critical rule the whole platform layer rests on: NO TENANT CONTEXT = NO
ACCESS. tenant_id here is never read from a query parameter or request
body -- it is only ever derived from the authenticated session/token.
"""

from dataclasses import dataclass

from tenants.models import has_permission


@dataclass(frozen=True)
class TenantContext:
    user_id: str
    tenant_id: str
    role: str
    tenant: dict  # full tenant row, for status/subscription checks

    def require(self, permission: str):
        if not has_permission(self.role, permission):
            raise PermissionError(
                f"Role '{self.role}' does not have permission '{permission}'."
            )
