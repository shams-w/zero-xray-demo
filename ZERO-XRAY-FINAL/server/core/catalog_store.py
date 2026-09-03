"""Tenant-owned Data Sources (Section 16) and Integrations (Section
18/19). Both share the same shape: a tenant-scoped catalog row with a
`config_json` blob for non-secret settings, and -- for integrations --
a `secret_reference` string that points at where a real secret would
live in a secret manager/key vault, never the secret itself (Section
19). Nothing here invents a real connection: `status` defaults to
`NOT_CONNECTED`/`SANDBOX` until an operator explicitly wires one up.
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

from core.database import connect_database, resolve_database_target, table_columns, is_postgresql, ensure_database_safety


def _now():
    return datetime.now(timezone.utc).isoformat()


def _dumps(value):
    return json.dumps(value or {}, ensure_ascii=False)


def _loads(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


DATA_SOURCE_TYPES = {
    "PDF", "EXCEL", "TEXT", "SERVICE_CATALOGUE", "API", "DATABASE",
    "POLICIES", "INTERNAL_KNOWLEDGE_BASE",
}
DATA_SOURCE_STATUSES = {"READY", "PROCESSING", "FAILED", "NOT_CONNECTED", "SANDBOX", "CONNECTED"}

INTEGRATION_TYPES = {
    "IDENTITY_PROVIDER", "UAE_PASS", "GOVERNMENT_API", "INTERNAL_API",
    "PAYMENT_GATEWAY", "CRM", "DOCUMENT_MANAGEMENT", "NOTIFICATIONS",
}
INTEGRATION_STATUSES = {"NOT_CONNECTED", "SANDBOX", "CONNECTED"}

# Every retrievable chunk/document must be classified as one or the
# other (Section 17) so tenant-private RAG content can never silently
# leak into another tenant's or the platform's shared context.
SOURCE_CLASSIFICATIONS = {"GLOBAL_STANDARD", "TENANT_PRIVATE_SOURCE"}


class CatalogStore:
    """NOTE: like AgentStore, assumes a RuntimeStore for the same
    `database_path` has already initialized the shared schema (used
    here only for the FK-style relationship to `tenants`, which lives
    in TenantRepository's tables on the same file)."""

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
                CREATE TABLE IF NOT EXISTS data_sources (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    created_by TEXT,
                    storage_path TEXT,
                    original_filename TEXT,
                    mime_type TEXT,
                    file_size INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_data_sources_tenant_id ON data_sources (tenant_id);

                CREATE TABLE IF NOT EXISTS integrations (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    secret_reference TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_integrations_tenant_id ON integrations (tenant_id);
                """
            )
            # Additive storage metadata for data-source files created by older builds.
            columns = table_columns(connection, "data_sources", self.database_path)
            for column, sql_type in (("storage_path", "TEXT"), ("original_filename", "TEXT"),
                                     ("mime_type", "TEXT"), ("file_size", "INTEGER")):
                if column not in columns:
                    connection.execute(f"ALTER TABLE data_sources ADD COLUMN {column} {sql_type}")
            # Legacy knowledge rows used integration-style statuses. Treat existing
            # successfully stored rows as READY rather than connected/disconnected.
            connection.execute(
                "UPDATE data_sources SET status = 'READY' WHERE status IN ('CONNECTED','SANDBOX','NOT_CONNECTED')"
            )

    # --- Data Sources -----------------------------------------------------

    def create_data_source(self, tenant_id, name, source_type, configuration=None,
                            classification="TENANT_PRIVATE_SOURCE", created_by=None,
                            status="NOT_CONNECTED"):
        if source_type not in DATA_SOURCE_TYPES:
            raise ValueError(f"Unsupported data source type: {source_type}")
        if classification not in SOURCE_CLASSIFICATIONS:
            raise ValueError(f"Unsupported classification: {classification}")
        if status not in DATA_SOURCE_STATUSES:
            raise ValueError(f"Unsupported data source status: {status}")
        row_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO data_sources
                (id, tenant_id, name, type, status, classification,
                 configuration_json, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, tenant_id, name, source_type, status, classification,
                 _dumps(configuration), created_by, now, now),
            )
        return self.get_data_source_for_tenant(row_id, tenant_id)

    def get_data_source_for_tenant(self, data_source_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM data_sources WHERE id = ? AND tenant_id = ?",
                (data_source_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["configuration"] = _loads(result.pop("configuration_json"))
        return result

    def list_data_sources_for_tenant(self, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM data_sources WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["configuration"] = _loads(item.pop("configuration_json"))
            results.append(item)
        return results

    def attach_file_metadata(self, data_source_id, tenant_id, storage_path,
                             original_filename=None, mime_type=None, file_size=None):
        """Persist the tenant-owned file location after bytes are safely written.
        The lookup and update both include tenant_id so a source UUID alone never
        grants access to another tenant's file metadata.
        """
        with self._connect() as connection:
            current = connection.execute(
                "SELECT id FROM data_sources WHERE id = ? AND tenant_id = ?",
                (data_source_id, tenant_id),
            ).fetchone()
            if not current:
                return None
            connection.execute(
                """
                UPDATE data_sources
                   SET storage_path = ?, original_filename = ?, mime_type = ?,
                       file_size = ?, status = 'READY', updated_at = ?
                 WHERE id = ? AND tenant_id = ?
                """,
                (storage_path, original_filename, mime_type, file_size, _now(),
                 data_source_id, tenant_id),
            )
        return self.get_data_source_for_tenant(data_source_id, tenant_id)

    # --- Integrations --------------------------------------------------

    def create_integration(self, tenant_id, integration_type, name, config=None,
                            secret_reference=None, status="NOT_CONNECTED"):
        if integration_type not in INTEGRATION_TYPES:
            raise ValueError(f"Unsupported integration type: {integration_type}")
        if status not in INTEGRATION_STATUSES:
            raise ValueError(f"Unsupported integration status: {status}")
        if secret_reference and self._looks_like_a_raw_secret(secret_reference):
            # Section 19: never store plaintext production secrets.
            # This is a best-effort guard, not a substitute for a real
            # secret manager -- it only catches the obviously wrong
            # shape (e.g. someone pasting a live API key here).
            raise ValueError(
                "secret_reference must be a reference/path (e.g. "
                "'tenant/emirates-post/payment'), never a raw secret value."
            )
        row_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO integrations
                (id, tenant_id, type, name, status, config_json,
                 secret_reference, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, tenant_id, integration_type, name, status,
                 _dumps(config), secret_reference, now, now),
            )
        return self.get_integration_for_tenant(row_id, tenant_id)

    @staticmethod
    def _looks_like_a_raw_secret(value):
        # Heuristic only: long, high-entropy-looking single tokens
        # with no path separator are more likely a pasted key than a
        # 'tenant/x/y' style reference.
        return "/" not in value and len(value) > 40

    def get_integration_for_tenant(self, integration_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM integrations WHERE id = ? AND tenant_id = ?",
                (integration_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["config"] = _loads(result.pop("config_json"))
        return result

    def list_integrations_for_tenant(self, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM integrations WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["config"] = _loads(item.pop("config_json"))
            results.append(item)
        return results
