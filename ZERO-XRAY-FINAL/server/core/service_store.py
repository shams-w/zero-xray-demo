"""Real, tenant-aware Service and Analysis entities (Section 4).

Deliberately thin: `Blueprint.service_json` / `Blueprint.analysis_json`
in `runtime_store.py` remain the actual working representation the
ZERO X-RAY engine reads and writes -- this module does not touch the
analysis engine, the workflow, or any agent. It adds first-class
`services` and `analyses` rows so the platform's API surface stops
using a Blueprint ID as a stand-in for both `service_id` and
`analysis_id` (the specific thing Section 4 asks to fix), and so a
Service's history of Analyses can be listed independently later.

Flow: Tenant -> Service -> Analysis -> Blueprint -> Agent
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

from core.database import connect_database, resolve_database_target, table_columns, is_postgresql, ensure_database_safety


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value or {}, ensure_ascii=False)


def _read_json(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


ANALYSIS_STATUSES = {"RUNNING", "COMPLETED", "FAILED"}


class ServiceStore:
    """NOTE: like AgentStore/CatalogStore, assumes RuntimeStore has
    already initialized the shared db file (for the `tenants` FK
    relationship)."""

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
                CREATE TABLE IF NOT EXISTS services (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    description TEXT,
                    language TEXT,
                    source_info TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_services_tenant_id ON services (tenant_id);

                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    blueprint_id TEXT NOT NULL,
                    created_by TEXT,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analyses_tenant_id ON analyses (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_analyses_service_id ON analyses (service_id);

                CREATE TABLE IF NOT EXISTS service_data_sources (
                    service_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    data_source_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (service_id, data_source_id)
                );
                CREATE INDEX IF NOT EXISTS idx_service_data_sources_tenant ON service_data_sources (tenant_id);

                CREATE TABLE IF NOT EXISTS service_integrations (
                    service_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    integration_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (service_id, integration_id)
                );
                CREATE INDEX IF NOT EXISTS idx_service_integrations_tenant ON service_integrations (tenant_id);

                CREATE TABLE IF NOT EXISTS service_user_assignments (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (tenant_id, service_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_service_user_assignments_tenant ON service_user_assignments (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_service_user_assignments_service ON service_user_assignments (service_id);
                CREATE INDEX IF NOT EXISTS idx_service_user_assignments_user ON service_user_assignments (user_id);
                """
            )
            # Additive migration for analyses tables created before
            # result_json existed (Section 7) -- never destroys rows.
            analysis_columns = table_columns(connection, "analyses", self.database_path)
            if "result_json" not in analysis_columns:
                connection.execute("ALTER TABLE analyses ADD COLUMN result_json TEXT")

    # --- Services ------------------------------------------------------

    def create_service(self, tenant_id, service_name, description="", language="en",
                        source_info=None, created_by=None):
        service_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO services
                (id, tenant_id, service_name, description, language, source_info,
                 created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (service_id, tenant_id, service_name, description, language,
                 source_info, created_by, now, now),
            )
        return self.get_service_for_tenant(service_id, tenant_id)

    def get_service_for_tenant(self, service_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM services WHERE id = ? AND tenant_id = ?",
                (service_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def list_services_for_tenant(self, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM services WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_services_for_user(self, tenant_id, user_id):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.* FROM services s
                INNER JOIN service_user_assignments a
                    ON a.service_id = s.id AND a.tenant_id = s.tenant_id
                WHERE s.tenant_id = ? AND a.user_id = ?
                ORDER BY s.created_at DESC
                """,
                (tenant_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def is_user_assigned_to_service(self, tenant_id, service_id, user_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM service_user_assignments WHERE tenant_id = ? AND service_id = ? AND user_id = ?",
                (tenant_id, service_id, user_id),
            ).fetchone()
        return bool(row)

    def assign_user_to_service(self, tenant_id, service_id, user_id):
        if not self.get_service_for_tenant(service_id, tenant_id):
            return None
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM service_user_assignments WHERE tenant_id = ? AND service_id = ? AND user_id = ?",
                (tenant_id, service_id, user_id),
            ).fetchone()
            if existing:
                assignment_id = existing["id"]
            else:
                assignment_id = str(uuid4())
                connection.execute(
                    "INSERT INTO service_user_assignments (id, tenant_id, service_id, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
                    (assignment_id, tenant_id, service_id, user_id, now),
                )
            row = connection.execute(
                "SELECT * FROM service_user_assignments WHERE id = ?", (assignment_id,)
            ).fetchone()
        return dict(row) if row else None

    def unassign_user_from_service(self, tenant_id, service_id, user_id):
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM service_user_assignments WHERE tenant_id = ? AND service_id = ? AND user_id = ?",
                (tenant_id, service_id, user_id),
            )
        return cursor.rowcount > 0

    def list_assignments_for_service(self, tenant_id, service_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM service_user_assignments WHERE tenant_id = ? AND service_id = ? ORDER BY created_at",
                (tenant_id, service_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_assigned_data_source_ids(self, tenant_id, user_id):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT sds.data_source_id
                FROM service_data_sources sds
                INNER JOIN service_user_assignments a
                    ON a.service_id = sds.service_id AND a.tenant_id = sds.tenant_id
                WHERE sds.tenant_id = ? AND a.user_id = ?
                """,
                (tenant_id, user_id),
            ).fetchall()
        return [row["data_source_id"] for row in rows]


    def set_service_connections(self, service_id, tenant_id, data_source_ids=None, integration_ids=None):
        """Replace the selected knowledge/tools for one tenant-owned service."""
        if not self.get_service_for_tenant(service_id, tenant_id):
            return False
        data_source_ids = list(dict.fromkeys(data_source_ids or []))
        integration_ids = list(dict.fromkeys(integration_ids or []))
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM service_data_sources WHERE service_id = ? AND tenant_id = ?",
                (service_id, tenant_id),
            )
            connection.execute(
                "DELETE FROM service_integrations WHERE service_id = ? AND tenant_id = ?",
                (service_id, tenant_id),
            )
            for source_id in data_source_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO service_data_sources (service_id, tenant_id, data_source_id, created_at) VALUES (?, ?, ?, ?)",
                    (service_id, tenant_id, source_id, now),
                )
            for integration_id in integration_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO service_integrations (service_id, tenant_id, integration_id, created_at) VALUES (?, ?, ?, ?)",
                    (service_id, tenant_id, integration_id, now),
                )
        return True

    def get_service_connection_ids(self, service_id, tenant_id):
        with self._connect() as connection:
            source_rows = connection.execute(
                "SELECT data_source_id FROM service_data_sources WHERE service_id = ? AND tenant_id = ? ORDER BY created_at",
                (service_id, tenant_id),
            ).fetchall()
            integration_rows = connection.execute(
                "SELECT integration_id FROM service_integrations WHERE service_id = ? AND tenant_id = ? ORDER BY created_at",
                (service_id, tenant_id),
            ).fetchall()
        return {
            "data_source_ids": [row["data_source_id"] for row in source_rows],
            "integration_ids": [row["integration_id"] for row in integration_rows],
        }

    # --- Analyses --------------------------------------------------------

    def create_analysis(self, tenant_id, service_id, blueprint_id, created_by=None,
                         status="COMPLETED", result=None):
        if status not in ANALYSIS_STATUSES:
            raise ValueError(f"Unsupported analysis status: {status}")
        analysis_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO analyses
                (id, tenant_id, service_id, blueprint_id, created_by, status,
                 result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (analysis_id, tenant_id, service_id, blueprint_id, created_by,
                 status, _json(result), now, now),
            )
        return self.get_analysis_for_tenant(analysis_id, tenant_id)

    def get_analysis_for_tenant(self, analysis_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analyses WHERE id = ? AND tenant_id = ?",
                (analysis_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = _read_json(result.pop("result_json", None))
        return result

    def list_analyses_for_service(self, service_id, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM analyses WHERE service_id = ? AND tenant_id = ? ORDER BY created_at DESC",
                (service_id, tenant_id),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["result"] = _read_json(item.pop("result_json", None))
            results.append(item)
        return results

    def count_analyses_for_tenant(self, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM analyses WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        return row["count"] if row else 0

    def get_analysis_by_blueprint(self, blueprint_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analyses WHERE blueprint_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 1",
                (blueprint_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = _read_json(result.pop("result_json", None))
        return result
