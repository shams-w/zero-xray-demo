"""Authentication provider abstraction for ZERO X-RAY.

`DemoAuthProvider` remains the default local-development provider and keeps
existing `/api/auth/demo-login` behaviour.

`ExternalOIDCAuthProvider` is the production-ready boundary for standards-
compliant OIDC / SSO providers such as Microsoft Entra ID. It validates the
provider-issued access/ID token server-side (signature, issuer, audience and
expiration), then maps verified claims to an existing ZERO X-RAY platform user
and role. MFA is intentionally NOT implemented here: when required, MFA is an
identity-provider policy and ZERO X-RAY trusts only the resulting verified
OIDC token.

UAE PASS is not emulated. Its connection status remains NOT_CONNECTED unless
an actual UAE PASS integration is explicitly configured separately.
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import hmac
import secrets


from tenants.models import ROLES
from tenants.repository import TenantRepository

AUTH_PROVIDER_ENV = "ZX_AUTH_PROVIDER"


def _demo_passphrase() -> str:
    """Read the local demo credential from server-side configuration only."""
    value = (os.getenv("ZX_DEMO_DEV_PASSPHRASE") or "").strip()
    if not value or value.startswith("<"):
        raise ValueError("Demo authentication is not configured. Set ZX_DEMO_DEV_PASSPHRASE in .env.")
    return value


def _employee_session_ttl_seconds() -> int:
    # New generic name, while honoring the previous demo-specific variable.
    raw = os.getenv(
        "ZX_EMPLOYEE_SESSION_TTL_SECONDS",
        os.getenv("ZX_DEMO_SESSION_TTL_SECONDS", "28800"),
    )
    try:
        ttl = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Employee session TTL must be a positive integer.") from exc
    if ttl <= 0:
        raise ValueError("Employee session TTL must be greater than zero.")
    return ttl


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _json_env(name: str, default):
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must contain valid JSON.") from exc
    return value


class AuthProvider(ABC):
    """Common authentication contract used by FastAPI dependencies."""

    provider_name = "abstract"

    def authenticate(self, email: str, credential: str) -> dict:
        """Interactive credential flow used by the existing demo login.

        Production OIDC providers normally authenticate at the external IdP,
        so they may reject this method and accept only provider-issued bearer
        tokens through :meth:`resolve_session`.
        """
        raise ValueError("Interactive credential authentication is not supported by this provider.")

    @abstractmethod
    def resolve_session(self, token: str) -> dict:
        """Resolve a bearer token to a validated local user/tenant session."""
        raise NotImplementedError

    def revoke_session(self, token: str) -> None:
        """Optional local session invalidation hook."""
        return None

    def public_status(self) -> dict:
        return {"provider": self.provider_name}


class DemoAuthProvider(AuthProvider):
    """Development-only provider backed by local platform users."""

    provider_name = "demo"

    def __init__(self, repository: TenantRepository = None):
        self.repository = repository or TenantRepository()

    def authenticate(self, email: str, credential: str) -> dict:
        expected_credential = _demo_passphrase()
        if not hmac.compare_digest(str(credential), expected_credential):
            raise ValueError("Invalid demo credentials.")
        matches = self.repository.get_user_by_email_any_tenant(email)
        if not matches:
            raise ValueError("No platform user found for that email.")
        if len(matches) > 1:
            raise ValueError(
                "This email is registered in multiple tenants; demo login cannot "
                "disambiguate. Use a tenant-unique email."
            )
        user = matches[0]
        token = secrets.token_urlsafe(32)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=_employee_session_ttl_seconds())
        ).isoformat()

        self.repository.save_demo_session(
            token, user["id"], user["tenant_id"], expires_at=expires_at
        )
        return {
            "token": token,
            "user_id": user["id"],
            "tenant_id": user["tenant_id"],
            "expires_at": expires_at,
        }

    def resolve_session(self, token: str) -> dict:
        if self.repository.is_employee_token_revoked(token):
            raise ValueError("Invalid or expired session.")
        session = self.repository.get_demo_session(token)
        if not session:
            raise ValueError("Invalid or expired session.")
        expires_at = session.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError as exc:
                self.repository.delete_demo_session(token)
                raise ValueError("Invalid or expired session.") from exc
            if expiry <= datetime.now(timezone.utc):
                self.repository.delete_demo_session(token)
                raise ValueError("Invalid or expired session.")
        return {
            "user_id": session["user_id"],
            "tenant_id": session["tenant_id"],
        }

    def revoke_session(self, token: str) -> None:
        self.repository.revoke_employee_session(token)

    def public_status(self) -> dict:
        return {
            "provider": self.provider_name,
            "mode": "DEMO",
            "oidc": "NOT_CONNECTED",
            "uae_pass": "NOT_CONNECTED",
        }


class ExternalOIDCAuthProvider(AuthProvider):
    """OIDC bearer-token provider for production SSO / Microsoft Entra ID.

    Required environment variables:
      ZX_OIDC_ISSUER
      ZX_OIDC_AUDIENCE
      ZX_OIDC_JWKS_URL

    Optional mapping variables:
      ZX_OIDC_EMAIL_CLAIM          (default: preferred_username)
      ZX_OIDC_ROLE_CLAIM           (default: roles)
      ZX_OIDC_ROLE_MAPPING_JSON    e.g. {"ZXR.Analyst":"analyst"}
      ZX_OIDC_REQUIRE_MAPPED_ROLE  (default: true)

    Users must already exist in `platform_users`; authentication never creates
    a tenant/user implicitly. This preserves tenant isolation and makes identity
    onboarding an explicit Entity Admin / platform process.
    """

    provider_name = "external_oidc"

    def __init__(self, repository: TenantRepository = None):
        self.repository = repository or TenantRepository()
        self.issuer = os.getenv("ZX_OIDC_ISSUER", "").strip().rstrip("/")
        self.audience = os.getenv("ZX_OIDC_AUDIENCE", "").strip()
        self.jwks_url = os.getenv("ZX_OIDC_JWKS_URL", "").strip()
        self.email_claim = os.getenv("ZX_OIDC_EMAIL_CLAIM", "preferred_username").strip()
        self.role_claim = os.getenv("ZX_OIDC_ROLE_CLAIM", "roles").strip()
        self.role_mapping = _json_env("ZX_OIDC_ROLE_MAPPING_JSON", {})
        self.require_mapped_role = _env_bool("ZX_OIDC_REQUIRE_MAPPED_ROLE", True)

    @property
    def configured(self) -> bool:
        return bool(self.issuer and self.audience and self.jwks_url)

    def authenticate(self, email: str, credential: str) -> dict:
        raise ValueError(
            "External OIDC authentication must be completed by the configured identity provider."
        )

    def _decode_and_validate(self, token: str) -> dict:
        if not self.configured:
            raise ValueError("External OIDC provider is not configured.")
        try:
            import jwt
        except ImportError as exc:
            raise ValueError(
                "External OIDC support requires the PyJWT cryptography dependency."
            ) from exc

        try:
            signing_key = jwt.PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except Exception as exc:
            raise ValueError("Invalid or expired OIDC session.") from exc

    def _mapped_role(self, claims: dict):
        raw_roles = claims.get(self.role_claim, [])
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        if not isinstance(raw_roles, (list, tuple)):
            raw_roles = []
        for external_role in raw_roles:
            local_role = self.role_mapping.get(str(external_role))
            if local_role in ROLES:
                return local_role
        return None

    def resolve_session(self, token: str) -> dict:
        if self.repository.is_employee_token_revoked(token):
            raise ValueError("Invalid or expired OIDC session.")
        claims = self._decode_and_validate(token)
        email = str(claims.get(self.email_claim) or claims.get("email") or "").strip().lower()
        if not email:
            raise ValueError("OIDC token does not contain the configured user email claim.")

        matches = self.repository.get_user_by_email_any_tenant(email)
        if not matches:
            raise ValueError("OIDC identity is not provisioned in ZERO X-RAY.")
        if len(matches) != 1:
            raise ValueError("OIDC identity maps to multiple ZERO X-RAY tenants.")
        user = matches[0]

        mapped_role = self._mapped_role(claims)
        if self.require_mapped_role and not mapped_role:
            raise ValueError("OIDC identity has no mapped ZERO X-RAY role.")
        # When role mapping is optional, preserve the provisioned local role.
        role = mapped_role or user["role"]

        return {
            "user_id": user["id"],
            "tenant_id": user["tenant_id"],
            "role": role,
            "expires_at": claims.get("exp"),
            "provider": self.provider_name,
        }

    def revoke_session(self, token: str) -> None:
        # Local deny-list guarantees a logged-out provider token cannot be reused
        # against ZERO X-RAY even if the external IdP token itself is still valid.
        expires_at = None
        try:
            claims = self._decode_and_validate(token)
            exp = claims.get("exp")
            if exp is not None:
                expires_at = datetime.fromtimestamp(float(exp), tz=timezone.utc).isoformat()
        except ValueError:
            pass
        self.repository.revoke_employee_session(token, expires_at=expires_at)

    def public_status(self) -> dict:
        return {
            "provider": self.provider_name,
            "mode": "PRODUCTION",
            "oidc": "CONNECTED" if self.configured else "NOT_CONNECTED",
            # Never infer or fake UAE PASS from generic OIDC configuration.
            "uae_pass": "CONNECTED" if _env_bool("ZX_UAE_PASS_CONNECTED", False) else "NOT_CONNECTED",
        }


_default_provider = None
_default_provider_key = None


def get_auth_provider() -> AuthProvider:
    """Return the configured provider without changing auth call sites.

    `demo` remains the default to preserve local development behaviour.
    Supported production aliases deliberately resolve to the same standards-
    based provider: external_oidc, oidc, sso, entra, entra_id.
    """
    global _default_provider, _default_provider_key
    provider_key = os.getenv(AUTH_PROVIDER_ENV, "demo").strip().lower()
    if _default_provider is not None and _default_provider_key == provider_key:
        return _default_provider

    if provider_key == "demo":
        provider = DemoAuthProvider()
    elif provider_key in {"external_oidc", "oidc", "sso", "entra", "entra_id"}:
        provider = ExternalOIDCAuthProvider()
    else:
        raise RuntimeError(f"Unsupported {AUTH_PROVIDER_ENV} value: {provider_key}")

    _default_provider = provider
    _default_provider_key = provider_key
    return provider


def reset_auth_provider_for_tests():
    global _default_provider, _default_provider_key
    _default_provider = None
    _default_provider_key = None
