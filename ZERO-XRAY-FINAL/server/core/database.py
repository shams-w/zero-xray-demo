"""Database configuration and DB-API compatibility helpers.

SQLite remains the zero-configuration local/demo backend.  When DATABASE_URL
uses a PostgreSQL URL, the same store classes can use psycopg without changing
their public API or query call sites.
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path


def resolve_database_target(database_path=None, default_path=None):
    """Return a SQLite Path or PostgreSQL URL.

    Explicit ``database_path`` always wins. This preserves every existing test
    and local caller that passes a temporary SQLite path. When no explicit path
    is provided, DATABASE_URL is honored; otherwise the existing local path is
    used unchanged.
    """
    if database_path is not None:
        if isinstance(database_path, str) and database_path.startswith("sqlite:///"):
            return Path(database_path[len("sqlite:///"):]).expanduser()
        if isinstance(database_path, str) and database_path.startswith(("postgresql://", "postgres://")):
            return database_path
        return Path(database_path)

    configured = (os.getenv("DATABASE_URL") or "").strip()
    if configured:
        if configured.startswith("sqlite:///"):
            return Path(configured[len("sqlite:///"):]).expanduser()
        if configured.startswith(("postgresql://", "postgres://")):
            return configured
        raise ValueError("DATABASE_URL must use sqlite:/// or postgresql://")

    if default_path is None:
        raise ValueError("A default SQLite database path is required")
    return Path(default_path)


def is_postgresql(target) -> bool:
    return isinstance(target, str) and target.startswith(("postgresql://", "postgres://"))


def is_sqlite(target) -> bool:
    return not is_postgresql(target)


def _split_sql_script(script: str):
    # Project schema scripts are simple DDL with no semicolons inside quoted
    # strings/functions, so splitting on statement terminators is sufficient.
    return [statement.strip() for statement in script.split(";") if statement.strip()]


def _postgres_sql(sql: str) -> str:
    # The existing stores use SQLite/qmark DB-API placeholders. Psycopg uses %s.
    sql = sql.replace("?", "%s")
    # The two SQLite conflict forms used by the project are normalized here.
    match = re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\s+(.+)", sql, flags=re.I | re.S)
    if match:
        sql = "INSERT INTO " + match.group(1) + " ON CONFLICT DO NOTHING"
    return sql


class _PostgresConnectionCompat:
    """Tiny wrapper preserving the subset of sqlite3.Connection API used here."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        return self._raw.execute(_postgres_sql(sql), params or ())

    def executescript(self, script):
        cursor = None
        for statement in _split_sql_script(script):
            cursor = self.execute(statement)
        return cursor

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()


@contextlib.contextmanager
def connect_database(target):
    """Yield a transactional connection with dict-like rows for either backend."""
    if is_postgresql(target):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on production extra
            raise RuntimeError(
                "PostgreSQL DATABASE_URL requires psycopg. Install server requirements."
            ) from exc
        raw = psycopg.connect(target, row_factory=dict_row)
        connection = _PostgresConnectionCompat(raw)
    else:
        import sqlite3

        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(path)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        connection = raw

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def table_columns(connection, table_name: str, target) -> set[str]:
    """Portable additive-migration introspection."""
    if is_postgresql(target):
        rows = connection.execute(
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table_name,),
        ).fetchall()
    else:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def index_exists(connection, index_name: str, target) -> bool:
    if is_postgresql(target):
        row = connection.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND indexname = ?",
            (index_name,),
        ).fetchone()
        return bool(row)
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name = ?", (index_name,)
    ).fetchone()
    return bool(row)


def table_exists(connection, table_name: str, target) -> bool:
    if is_postgresql(target):
        row = connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?",
            (table_name,),
        ).fetchone()
        return bool(row)
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)
    ).fetchone()
    return bool(row)


_INDEX_COLUMNS = (
    "tenant_id", "service_id", "user_id", "analysis_id", "blueprint_id",
    "customer_id", "journey_id", "created_at",
)

# child table, FK column, parent table. These are the tenant-scoped references
# already represented by the application's data model.
_TENANT_REFERENCES = (
    # Relationships whose parent row is guaranteed to exist before the child
    # is written in the current ZERO X-RAY flows. Deferred/link-later fields
    # (for example blueprints.analysis_id) are intentionally not constrained.
    ("analyses", "service_id", "services"),
    ("service_user_assignments", "service_id", "services"),
    ("service_user_assignments", "user_id", "platform_users"),
    ("service_data_sources", "service_id", "services"),
    ("service_data_sources", "data_source_id", "data_sources"),
    ("service_integrations", "service_id", "services"),
    ("service_integrations", "integration_id", "integrations"),
    ("agents", "service_id", "services"),
    ("journeys", "blueprint_id", "blueprints"),
    ("journeys", "customer_id", "customers"),
    ("journey_events", "journey_id", "journeys"),
    ("journey_capabilities", "journey_id", "journeys"),
    ("journey_capabilities", "customer_id", "customers"),
    ("monitoring_schedules", "service_id", "services"),
)


def ensure_database_safety(connection, target):
    """Idempotent, non-destructive indexes and tenant-reference guards.

    Existing rows are never rewritten or deleted. PostgreSQL FKs are added
    NOT VALID so legacy data cannot block startup while all new writes are
    enforced. SQLite uses BEFORE INSERT/UPDATE triggers because SQLite cannot
    add a foreign key to an existing table with ALTER TABLE.
    """
    existing = {}
    candidate_tables = {
        "tenants", "platform_users", "services", "analyses", "service_user_assignments",
        "service_data_sources", "service_integrations", "data_sources", "integrations",
        "agents", "predictions", "scenarios", "challenges", "evolutions", "preventions",
        "alerts", "blueprints", "customers", "journeys", "journey_events",
        "journey_capabilities", "audit_log", "demo_sessions", "monitoring_schedules",
    }
    for table in candidate_tables:
        if table_exists(connection, table, target):
            existing[table] = table_columns(connection, table, target)

    # Useful single-column indexes requested for common tenant/service/query keys.
    for table, columns in existing.items():
        for column in _INDEX_COLUMNS:
            if column in columns:
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_{column} ON {table} ({column})"
                )

    # Composite uniqueness is required for a tenant-aware FK target. id remains
    # globally unique too; this adds no change to existing lookup behavior.
    for parent in {item[2] for item in _TENANT_REFERENCES}:
        columns = existing.get(parent, set())
        if {"tenant_id", "id"}.issubset(columns):
            connection.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{parent}_tenant_id_id "
                f"ON {parent} (tenant_id, id)"
            )

    for child, fk_column, parent in _TENANT_REFERENCES:
        child_columns = existing.get(child, set())
        parent_columns = existing.get(parent, set())
        if not {"tenant_id", fk_column}.issubset(child_columns):
            continue
        if not {"tenant_id", "id"}.issubset(parent_columns):
            continue

        safe_name = f"fk_{child}_{fk_column}_tenant"
        if is_postgresql(target):
            found = connection.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = ?", (safe_name,)
            ).fetchone()
            if not found:
                connection.execute(
                    f"ALTER TABLE {child} ADD CONSTRAINT {safe_name} "
                    f"FOREIGN KEY (tenant_id, {fk_column}) "
                    f"REFERENCES {parent} (tenant_id, id) NOT VALID"
                )
        else:
            insert_trigger = f"trg_{child}_{fk_column}_tenant_ins"
            update_trigger = f"trg_{child}_{fk_column}_tenant_upd"
            condition = (
                f"NEW.tenant_id IS NOT NULL AND NEW.{fk_column} IS NOT NULL AND NOT EXISTS ("
                f"SELECT 1 FROM {parent} p WHERE p.id = NEW.{fk_column} "
                f"AND p.tenant_id = NEW.tenant_id)"
            )
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {insert_trigger} BEFORE INSERT ON {child} "
                f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'cross-tenant reference'); END"
            )
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {update_trigger} "
                f"BEFORE UPDATE OF tenant_id, {fk_column} ON {child} "
                f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'cross-tenant reference'); END"
            )
