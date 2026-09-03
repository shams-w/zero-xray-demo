"""Tenant/service-scoped storage for imported OpenAPI sources and operations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from core.database import connect_database, ensure_database_safety


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _read(value, default=None):
    if value in (None, ""):
        return default if default is not None else {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default if default is not None else {}


class ApiOperationStore:
    def __init__(self, database_path):
        self.database_path = database_path
        self._initialize()
        with self._connect() as connection:
            ensure_database_safety(connection, self.database_path)

    def _connect(self):
        return connect_database(self.database_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS openapi_sources (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    integration_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    api_version TEXT,
                    openapi_version TEXT NOT NULL,
                    format TEXT NOT NULL,
                    servers_json TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_openapi_sources_integration
                    ON openapi_sources (tenant_id, service_id, integration_id);
                CREATE INDEX IF NOT EXISTS idx_openapi_sources_tenant_id ON openapi_sources (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_openapi_sources_service_id ON openapi_sources (service_id);

                CREATE TABLE IF NOT EXISTS api_operations (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    integration_id TEXT NOT NULL,
                    openapi_source_id TEXT NOT NULL,
                    operation_id TEXT,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    summary TEXT,
                    description TEXT,
                    tags_json TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    request_schema_json TEXT,
                    response_schema_json TEXT,
                    security_requirements_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    discovered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_api_operations_tenant_id ON api_operations (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_api_operations_service_id ON api_operations (service_id);
                CREATE INDEX IF NOT EXISTS idx_api_operations_integration_id ON api_operations (integration_id);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_api_operations_identity
                    ON api_operations (tenant_id, integration_id, method, path);
            """)

    def upsert_source_and_operations(self, tenant_id, service_id, integration_id, metadata, operations, environment):
        now = _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM openapi_sources WHERE tenant_id = ? AND service_id = ? AND integration_id = ?",
                (tenant_id, service_id, integration_id),
            ).fetchone()
            if row:
                source_id = row["id"]
                connection.execute("""
                    UPDATE openapi_sources
                    SET source_url=?, title=?, api_version=?, openapi_version=?, format=?, servers_json=?, updated_at=?
                    WHERE id=? AND tenant_id=? AND service_id=?
                """, (metadata.get("source_url"), metadata.get("title"), metadata.get("api_version"),
                      metadata.get("openapi_version"), metadata.get("format"), _json(metadata.get("servers") or []),
                      now, source_id, tenant_id, service_id))
                connection.execute("DELETE FROM api_operations WHERE tenant_id=? AND integration_id=?", (tenant_id, integration_id))
            else:
                source_id = str(uuid4())
                connection.execute("""
                    INSERT INTO openapi_sources
                    (id, tenant_id, service_id, integration_id, source_url, title, api_version,
                     openapi_version, format, servers_json, imported_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (source_id, tenant_id, service_id, integration_id, metadata.get("source_url"),
                      metadata.get("title"), metadata.get("api_version"), metadata.get("openapi_version"),
                      metadata.get("format"), _json(metadata.get("servers") or []), now, now))

            for operation in operations:
                connection.execute("""
                    INSERT INTO api_operations
                    (id, tenant_id, service_id, integration_id, openapi_source_id, operation_id,
                     method, path, summary, description, tags_json, parameters_json,
                     request_schema_json, response_schema_json, security_requirements_json,
                     source, environment, enabled, discovered_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(uuid4()), tenant_id, service_id, integration_id, source_id,
                      operation.get("operation_id"), operation.get("method"), operation.get("path"),
                      operation.get("summary"), operation.get("description"), _json(operation.get("tags") or []),
                      _json(operation.get("parameters") or []), _json(operation.get("request_schema")) if operation.get("request_schema") is not None else None,
                      _json(operation.get("response_schema")) if operation.get("response_schema") is not None else None,
                      _json(operation.get("security_requirements") or []), operation.get("source") or "OPENAPI",
                      environment, 1 if operation.get("enabled", True) else 0, now, now))
        return self.get_source_for_integration(tenant_id, service_id, integration_id)

    def get_source_for_integration(self, tenant_id, service_id, integration_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM openapi_sources WHERE tenant_id=? AND service_id=? AND integration_id=?",
                (tenant_id, service_id, integration_id),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["servers"] = _read(item.pop("servers_json"), [])
        return item

    def list_operations_for_integration(self, tenant_id, integration_id, service_id=None):
        query = "SELECT * FROM api_operations WHERE tenant_id=? AND integration_id=?"
        params = [tenant_id, integration_id]
        if service_id is not None:
            query += " AND service_id=?"
            params.append(service_id)
        query += " ORDER BY path, method"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._public_operation(dict(row)) for row in rows]

    def list_operations_for_integrations(self, tenant_id, integration_ids, service_id=None):
        result = []
        for integration_id in list(dict.fromkeys(integration_ids or [])):
            result.extend(self.list_operations_for_integration(tenant_id, integration_id, service_id=service_id))
        return result

    @staticmethod
    def _public_operation(row):
        return {
            "id": row.get("id"),
            "tenant_id": row.get("tenant_id"),
            "service_id": row.get("service_id"),
            "integration_id": row.get("integration_id"),
            "openapi_source_id": row.get("openapi_source_id"),
            "operation_id": row.get("operation_id"),
            "method": row.get("method"),
            "path": row.get("path"),
            "summary": row.get("summary") or "",
            "description": row.get("description") or "",
            "tags": _read(row.get("tags_json"), []),
            "parameters": _read(row.get("parameters_json"), []),
            "request_schema": _read(row.get("request_schema_json"), None) if row.get("request_schema_json") else None,
            "response_schema": _read(row.get("response_schema_json"), None) if row.get("response_schema_json") else None,
            "security_requirements": _read(row.get("security_requirements_json"), []),
            "source": row.get("source"),
            "environment": row.get("environment"),
            "enabled": bool(row.get("enabled")),
        }
