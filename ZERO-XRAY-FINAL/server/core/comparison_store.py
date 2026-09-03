"""Phase 8 -- storage for external/entity Agent comparison profiles.

Follows the exact same pattern as core/prevention_store.py /
core/evolution_store.py: its own file, its own additive table, never
touches an existing one. ZERO X-RAY's OWN generated Agent comparison
profile is NOT stored here -- it is always derived fresh from the
Blueprint (server/core/agent_comparison.py::build_zero_xray_comparison_
profile), exactly as Build Agent already does, so there is never a
second, possibly-stale copy of ZERO X-RAY's own Agent data. This table
only ever holds the employee-supplied description of an EXISTING
entity Agent, one profile per (tenant, service).
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

from core.database import connect_database, resolve_database_target, table_columns, is_postgresql, ensure_database_safety


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _read_json(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


class ComparisonStore:
    """NOTE: like PreventionStore/EvolutionStore/ChallengeStore, assumes
    RuntimeStore has already initialized the shared db file."""

    def __init__(self, database_path):
        self.database_path = database_path
        self._initialize()
        with self._connect() as connection:
            ensure_database_safety(connection, self.database_path)

    def _connect(self):
        return connect_database(self.database_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS external_agent_profiles (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_external_agent_profiles_tenant_id
                    ON external_agent_profiles (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_external_agent_profiles_service_id
                    ON external_agent_profiles (service_id);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_external_agent_profiles_tenant_service
                    ON external_agent_profiles (tenant_id, service_id);
                """
            )

    def upsert_profile(self, tenant_id, service_id, profile, created_by=None):
        """One profile per (tenant, service) -- re-saving replaces the
        prior profile for that Service, exactly like re-analyzing a
        Blueprint replaces its own analysis. Never touches any other
        tenant's/service's row (enforced by the unique index above,
        not by application logic alone)."""
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM external_agent_profiles WHERE tenant_id = ? AND service_id = ?",
                (tenant_id, service_id),
            ).fetchone()
            if existing:
                profile_id = existing["id"]
                connection.execute(
                    """
                    UPDATE external_agent_profiles
                    SET profile_json = ?, updated_at = ?
                    WHERE id = ? AND tenant_id = ?
                    """,
                    (_json(profile), now, profile_id, tenant_id),
                )
            else:
                profile_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO external_agent_profiles
                    (id, tenant_id, service_id, profile_json, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (profile_id, tenant_id, service_id, _json(profile), created_by, now, now),
                )
        return self.get_profile_for_tenant_service(tenant_id, service_id)

    def get_profile_for_tenant_service(self, tenant_id, service_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM external_agent_profiles WHERE tenant_id = ? AND service_id = ?",
                (tenant_id, service_id),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "service_id": row["service_id"],
            "profile": _read_json(row["profile_json"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
