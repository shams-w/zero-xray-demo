"""Persistence for tenants and platform users.

Shares the same SQLite file as `core.runtime_store.RuntimeStore`
(`ZX_DATABASE_PATH`, defaulting to `server/data/runtime.db`) so the whole
platform still ships as a single self-contained database file, matching
the existing project's "keep SQLite for the demo" approach. The schema
here is additive: it only ever creates its own `tenants` / `platform_users`
tables and never touches the pre-existing `blueprints` / `journeys` /
`customers` / `journey_events` / `audit_log` tables (those are migrated
separately in `runtime_store.py`, see `_migrate_tenant_columns`).
"""

import os
import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.database import connect_database, resolve_database_target, table_columns, is_postgresql, ensure_database_safety

from core.data_paths import get_database_path

from tenants.models import (
    DEFAULT_TENANT_NAME,
    DEFAULT_TENANT_SLUG,
    TENANT_STATUSES,
    USER_STATUSES,
)


def _now():
    return datetime.now(timezone.utc).isoformat()


class TenantRepository:
    def __init__(self, database_path=None):
        packaged_path = Path(__file__).resolve().parent.parent / "data" / "runtime.db"
        if database_path is None and (os.getenv("DATABASE_URL") or "").strip():
            self.database_path = resolve_database_target(None, packaged_path)
        else:
            default_path = get_database_path(packaged_path)
            self.database_path = resolve_database_target(database_path, default_path)
        self._initialize()
        self.default_tenant_id = self._ensure_default_tenant()
        with self._connect() as connection:
            ensure_database_safety(connection, self.database_path)

    def _connect(self):
        return connect_database(self.database_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    subscription_plan TEXT NOT NULL,
                    subscription_start TEXT,
                    subscription_end TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS platform_users (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_users_email
                    ON platform_users (tenant_id, email);

                CREATE TABLE IF NOT EXISTS demo_sessions (
                    token TEXT PRIMARY KEY,
                    token_hash TEXT,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES platform_users(id),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                );

                CREATE TABLE IF NOT EXISTS employee_session_revocations (
                    token_hash TEXT PRIMARY KEY,
                    revoked_at TEXT NOT NULL,
                    expires_at TEXT
                );
                """
            )
            session_columns = table_columns(connection, "demo_sessions", self.database_path)
            if "expires_at" not in session_columns:
                connection.execute("ALTER TABLE demo_sessions ADD COLUMN expires_at TEXT")
            if "token_hash" not in session_columns:
                connection.execute("ALTER TABLE demo_sessions ADD COLUMN token_hash TEXT")
            if "revoked_at" not in session_columns:
                connection.execute("ALTER TABLE demo_sessions ADD COLUMN revoked_at TEXT")

            # One-time, non-destructive migration for legacy sessions: hash the
            # bearer token and replace the old raw-token primary-key value with
            # a non-secret record identifier. Existing browser tokens continue
            # to resolve through their hash, but plaintext credentials are no
            # longer retained at rest.
            legacy_sessions = connection.execute(
                "SELECT token FROM demo_sessions WHERE token_hash IS NULL"
            ).fetchall()
            for legacy in legacy_sessions:
                raw_token = legacy["token"]
                connection.execute(
                    "UPDATE demo_sessions SET token = ?, token_hash = ? WHERE token = ?",
                    (
                        f"session_{secrets.token_hex(16)}",
                        self._token_hash(raw_token),
                        raw_token,
                    ),
                )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_demo_sessions_token_hash ON demo_sessions (token_hash)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_demo_sessions_expires_at ON demo_sessions (expires_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_demo_sessions_user_id ON demo_sessions (user_id)"
            )

            # Section 20 subscription limits -- additive columns, same
            # backfill-safe pattern as runtime_store's tenant_id migration.
            columns = table_columns(connection, "tenants", self.database_path)
            for column, default in (("max_users", 20), ("max_services", 20), ("max_agents", 20)):
                if column not in columns:
                    connection.execute(f"ALTER TABLE tenants ADD COLUMN {column} INTEGER")
                connection.execute(
                    f"UPDATE tenants SET {column} = ? WHERE {column} IS NULL", (default,)
                )

    def _ensure_default_tenant(self):
        """Guarantees a stable dev/default tenant exists so legacy
        (pre-tenant) rows in blueprints/journeys/etc. have somewhere
        safe to be assigned during migration, instead of being left
        globally visible. Idempotent."""
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM tenants WHERE slug = ?", (DEFAULT_TENANT_SLUG,)
            ).fetchone()
            if existing:
                return existing["id"]
            tenant_id = str(uuid4())
            now = _now()
            connection.execute(
                """
                INSERT INTO tenants
                (id, name, slug, status, subscription_plan,
                 subscription_start, subscription_end, created_at, updated_at)
                VALUES (?, ?, ?, 'ACTIVE', 'DEDICATED_GOVERNMENT', NULL, NULL, ?, ?)
                """,
                (tenant_id, DEFAULT_TENANT_NAME, DEFAULT_TENANT_SLUG, now, now),
            )
            return tenant_id


    @staticmethod
    def _token_hash(raw_token):
        return hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()

    # --- Demo sessions ----------------------------------------------------

    def save_demo_session(self, token, user_id, tenant_id, expires_at=None):
        """Persist a demo employee session without storing the bearer token raw."""
        token_hash = self._token_hash(token)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO demo_sessions
                (token, token_hash, user_id, tenant_id, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    f"session_{secrets.token_hex(16)}",
                    token_hash,
                    user_id,
                    tenant_id,
                    _now(),
                    expires_at,
                ),
            )

    def get_demo_session(self, token):
        token_hash = self._token_hash(token)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, tenant_id, expires_at, revoked_at
                FROM demo_sessions
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
        if not row or row["revoked_at"]:
            return None
        return dict(row)

    def delete_demo_session(self, token):
        # Used for malformed/expired legacy sessions. Deleting by hash never
        # requires the raw bearer token to be stored or logged.
        token_hash = self._token_hash(token)
        with self._connect() as connection:
            connection.execute("DELETE FROM demo_sessions WHERE token_hash = ?", (token_hash,))

    def revoke_employee_session(self, token, expires_at=None):
        """Invalidate an employee bearer token server-side for all providers."""
        token_hash = self._token_hash(token)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE demo_sessions SET revoked_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
            connection.execute(
                """
                INSERT INTO employee_session_revocations (token_hash, revoked_at, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(token_hash) DO UPDATE SET
                    revoked_at = excluded.revoked_at,
                    expires_at = excluded.expires_at
                """,
                (token_hash, now, expires_at),
            )

    def is_employee_token_revoked(self, token):
        token_hash = self._token_hash(token)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT token_hash FROM employee_session_revocations WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return bool(row)

    # --- Tenants ---------------------------------------------------------

    def create_tenant(self, name, slug, subscription_plan="PILOT",
                       subscription_start=None, subscription_end=None,
                       status="PILOT", max_users=20, max_services=20, max_agents=20):
        if status not in TENANT_STATUSES:
            raise ValueError("Unsupported tenant status.")
        tenant_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM tenants WHERE slug = ?", (slug,)
            ).fetchone()
            if existing:
                raise ValueError(f"Tenant slug '{slug}' is already taken.")
            connection.execute(
                """
                INSERT INTO tenants
                (id, name, slug, status, subscription_plan,
                 subscription_start, subscription_end, created_at, updated_at,
                 max_users, max_services, max_agents)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, name, slug, status, subscription_plan,
                 subscription_start, subscription_end, now, now,
                 max_users, max_services, max_agents),
            )
        return self.get_tenant(tenant_id)

    def get_tenant(self, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_tenant_by_slug(self, slug):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tenants WHERE slug = ?", (slug,)
            ).fetchone()
        return dict(row) if row else None

    def list_tenants(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tenants ORDER BY created_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_tenant_subscription(
        self, tenant_id, *, status=None, subscription_plan=None,
        subscription_start=None, subscription_end=None,
    ):
        if status is not None and status not in TENANT_STATUSES:
            raise ValueError("Unsupported tenant status.")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
            ).fetchone()
            if not current:
                return None

            updates = []
            values = []
            if status is not None:
                updates.append("status = ?")
                values.append(status)
            if subscription_plan is not None:
                updates.append("subscription_plan = ?")
                values.append(subscription_plan)
            if subscription_start is not None:
                updates.append("subscription_start = ?")
                values.append(subscription_start or None)
            if subscription_end is not None:
                updates.append("subscription_end = ?")
                values.append(subscription_end or None)

            if updates:
                updates.append("updated_at = ?")
                values.append(_now())
                values.append(tenant_id)
                connection.execute(
                    f"UPDATE tenants SET {', '.join(updates)} WHERE id = ?",
                    tuple(values),
                )
        return self.get_tenant(tenant_id)

    def set_tenant_status(self, tenant_id, status):
        if status not in TENANT_STATUSES:
            raise ValueError("Unsupported tenant status.")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT id FROM tenants WHERE id = ?", (tenant_id,)
            ).fetchone()
            if not current:
                return None
            connection.execute(
                "UPDATE tenants SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), tenant_id),
            )
        return self.get_tenant(tenant_id)

    # --- Users -------------------------------------------------------------

    def create_user(self, tenant_id, name, email, role, status="ACTIVE"):
        if status not in USER_STATUSES:
            raise ValueError("Unsupported user status.")
        user_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            tenant = connection.execute(
                "SELECT id FROM tenants WHERE id = ?", (tenant_id,)
            ).fetchone()
            if not tenant:
                raise ValueError("Tenant does not exist.")
            connection.execute(
                """
                INSERT INTO platform_users
                (id, tenant_id, name, email, role, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, tenant_id, name, email.strip().lower(), role, status, now, now),
            )
        return self.get_user(user_id)

    def get_user(self, user_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_users WHERE id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, tenant_id, email):
        """Tenant-scoped lookup -- a normal user can only ever resolve
        within their own tenant. See `get_user_by_email_any_tenant` for
        the login-time exception where the tenant is not yet known."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_users WHERE tenant_id = ? AND email = ?",
                (tenant_id, email.strip().lower()),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_email_any_tenant(self, email):
        """Used only by the demo login flow to resolve which tenant a
        given demo email belongs to, before a session exists. Never
        used by tenant-owned resource endpoints."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM platform_users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_users_for_tenant(self, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM platform_users WHERE tenant_id = ? ORDER BY created_at ASC",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_user_role(self, user_id, tenant_id, role):
        """Tenant-scoped: an entity_admin can only ever change a role
        for a user inside their own tenant (never platform_admin,
        which is reserved for platform-level accounts)."""
        from tenants.models import ROLES
        if role not in ROLES or role == "platform_admin":
            raise ValueError("Unsupported role for a tenant-scoped user.")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT id FROM platform_users WHERE id = ? AND tenant_id = ?",
                (user_id, tenant_id),
            ).fetchone()
            if not current:
                return None
            connection.execute(
                "UPDATE platform_users SET role = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
                (role, _now(), user_id, tenant_id),
            )
        return self.get_user(user_id)

    def set_user_status(self, user_id, tenant_id, status):
        if status not in USER_STATUSES:
            raise ValueError("Unsupported user status.")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT id FROM platform_users WHERE id = ? AND tenant_id = ?",
                (user_id, tenant_id),
            ).fetchone()
            if not current:
                return None
            connection.execute(
                "UPDATE platform_users SET status = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
                (status, _now(), user_id, tenant_id),
            )
        return self.get_user(user_id)
