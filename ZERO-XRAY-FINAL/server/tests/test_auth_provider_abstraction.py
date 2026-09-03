import os
from datetime import datetime, timedelta, timezone

import pytest

from auth.service import (
    DemoAuthProvider,
    ExternalOIDCAuthProvider,
    get_auth_provider,
    reset_auth_provider_for_tests,
)
from tenants.repository import TenantRepository


@pytest.fixture
def repo(tmp_path):
    repository = TenantRepository(tmp_path / "auth-provider.db")
    tenant = repository.create_tenant("Auth Tenant", "auth-tenant", status="ACTIVE")
    user = repository.create_user(
        tenant["id"], "Analyst User", "analyst@example.test", "analyst", status="ACTIVE"
    )
    return repository, tenant, user


def test_demo_is_default_provider(monkeypatch):
    monkeypatch.delenv("ZX_AUTH_PROVIDER", raising=False)
    reset_auth_provider_for_tests()
    assert isinstance(get_auth_provider(), DemoAuthProvider)


def test_demo_login_behavior_is_preserved(repo, monkeypatch):
    repository, tenant, user = repo
    monkeypatch.setenv("ZX_DEMO_SESSION_TTL_SECONDS", "0")
    provider = DemoAuthProvider(repository)
    session = provider.authenticate(user["email"], "zxr-demo-2026")
    resolved = provider.resolve_session(session["token"])
    assert resolved["user_id"] == user["id"]
    assert resolved["tenant_id"] == tenant["id"]


def test_demo_optional_session_expiration(repo, monkeypatch):
    repository, tenant, user = repo
    provider = DemoAuthProvider(repository)
    repository.save_demo_session(
        "expired-demo-token",
        user["id"],
        tenant["id"],
        expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    with pytest.raises(ValueError, match="Invalid or expired session"):
        provider.resolve_session("expired-demo-token")


def test_external_oidc_requires_real_configuration(repo, monkeypatch):
    repository, _, _ = repo
    for key in ("ZX_OIDC_ISSUER", "ZX_OIDC_AUDIENCE", "ZX_OIDC_JWKS_URL"):
        monkeypatch.delenv(key, raising=False)
    provider = ExternalOIDCAuthProvider(repository)
    assert provider.public_status()["oidc"] == "NOT_CONNECTED"
    assert provider.public_status()["uae_pass"] == "NOT_CONNECTED"
    with pytest.raises(ValueError, match="not configured"):
        provider.resolve_session("not-a-token")


def test_external_oidc_claims_map_to_existing_user_and_role(repo, monkeypatch):
    repository, tenant, user = repo
    monkeypatch.setenv("ZX_OIDC_ISSUER", "https://idp.example.test/tenant/v2.0")
    monkeypatch.setenv("ZX_OIDC_AUDIENCE", "zero-xray-api")
    monkeypatch.setenv("ZX_OIDC_JWKS_URL", "https://idp.example.test/keys")
    monkeypatch.setenv("ZX_OIDC_ROLE_MAPPING_JSON", '{"Gov.Analyst":"analyst"}')
    provider = ExternalOIDCAuthProvider(repository)
    provider._decode_and_validate = lambda token: {
        "preferred_username": user["email"],
        "roles": ["Gov.Analyst"],
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "iss": provider.issuer,
        "aud": provider.audience,
    }
    session = provider.resolve_session("verified-by-test-double")
    assert session["user_id"] == user["id"]
    assert session["tenant_id"] == tenant["id"]
    assert session["role"] == "analyst"


def test_external_oidc_unmapped_role_is_denied(repo, monkeypatch):
    repository, _, user = repo
    monkeypatch.setenv("ZX_OIDC_ISSUER", "https://idp.example.test/tenant/v2.0")
    monkeypatch.setenv("ZX_OIDC_AUDIENCE", "zero-xray-api")
    monkeypatch.setenv("ZX_OIDC_JWKS_URL", "https://idp.example.test/keys")
    monkeypatch.setenv("ZX_OIDC_ROLE_MAPPING_JSON", '{"Gov.Admin":"entity_admin"}')
    monkeypatch.setenv("ZX_OIDC_REQUIRE_MAPPED_ROLE", "true")
    provider = ExternalOIDCAuthProvider(repository)
    provider._decode_and_validate = lambda token: {
        "preferred_username": user["email"], "roles": ["Unknown.Role"], "exp": 9999999999
    }
    with pytest.raises(ValueError, match="no mapped ZERO X-RAY role"):
        provider.resolve_session("verified-by-test-double")


def test_uae_pass_never_inferred_from_generic_oidc(repo, monkeypatch):
    repository, _, _ = repo
    monkeypatch.setenv("ZX_OIDC_ISSUER", "https://login.microsoftonline.com/example/v2.0")
    monkeypatch.setenv("ZX_OIDC_AUDIENCE", "zero-xray")
    monkeypatch.setenv("ZX_OIDC_JWKS_URL", "https://login.microsoftonline.com/example/keys")
    monkeypatch.delenv("ZX_UAE_PASS_CONNECTED", raising=False)
    provider = ExternalOIDCAuthProvider(repository)
    status = provider.public_status()
    assert status["oidc"] == "CONNECTED"
    assert status["uae_pass"] == "NOT_CONNECTED"
