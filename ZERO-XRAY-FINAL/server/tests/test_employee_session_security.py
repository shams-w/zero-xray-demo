import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from auth.service import DemoAuthProvider
from tenants.repository import TenantRepository


@pytest.fixture()
def repo(tmp_path):
    return TenantRepository(database_path=tmp_path / "session-security.db")


def _user(repo):
    tenant = repo.create_tenant(
        "Session Security Tenant",
        "session-security-tenant",
        status="ACTIVE",
    )
    return repo.create_user(
        tenant["id"],
        "Session User",
        "session.user@example.test",
        "entity_admin",
    )


def test_demo_session_is_random_expiring_and_not_stored_raw(repo, monkeypatch):
    monkeypatch.setenv("ZX_DEMO_DEV_PASSPHRASE", "test-only-passphrase")
    monkeypatch.setenv("ZX_EMPLOYEE_SESSION_TTL_SECONDS", "3600")
    user = _user(repo)
    provider = DemoAuthProvider(repository=repo)

    first = provider.authenticate(user["email"], "test-only-passphrase")
    second = provider.authenticate(user["email"], "test-only-passphrase")

    assert first["token"] != second["token"]
    assert first["expires_at"]
    assert provider.resolve_session(first["token"])["user_id"] == user["id"]

    with repo._connect() as connection:
        row = connection.execute(
            "SELECT token, token_hash FROM demo_sessions WHERE token_hash = ?",
            (repo._token_hash(first["token"]),),
        ).fetchone()
    assert row is not None
    assert row["token"] != first["token"]
    assert row["token_hash"] == repo._token_hash(first["token"])


def test_expired_session_is_rejected(repo, monkeypatch):
    monkeypatch.setenv("ZX_DEMO_DEV_PASSPHRASE", "test-only-passphrase")
    user = _user(repo)
    provider = DemoAuthProvider(repository=repo)
    token = "expired-test-token"
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    repo.save_demo_session(token, user["id"], user["tenant_id"], expires_at=expired_at)

    with pytest.raises(ValueError, match="Invalid or expired session"):
        provider.resolve_session(token)


def test_logout_revocation_prevents_token_reuse(repo, monkeypatch):
    monkeypatch.setenv("ZX_DEMO_DEV_PASSPHRASE", "test-only-passphrase")
    monkeypatch.setenv("ZX_EMPLOYEE_SESSION_TTL_SECONDS", "3600")
    user = _user(repo)
    provider = DemoAuthProvider(repository=repo)
    session = provider.authenticate(user["email"], "test-only-passphrase")

    provider.revoke_session(session["token"])

    assert repo.is_employee_token_revoked(session["token"]) is True
    with pytest.raises(ValueError, match="Invalid or expired session"):
        provider.resolve_session(session["token"])


def test_demo_secret_must_come_from_environment(repo, monkeypatch):
    monkeypatch.delenv("ZX_DEMO_DEV_PASSPHRASE", raising=False)
    user = _user(repo)
    provider = DemoAuthProvider(repository=repo)

    with pytest.raises(ValueError, match="Demo authentication is not configured"):
        provider.authenticate(user["email"], "anything")
