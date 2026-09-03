import os
import sqlite3
from pathlib import Path

import pytest

from core.database import resolve_database_target, is_postgresql
from core.runtime_store import RuntimeStore
from core.service_store import ServiceStore
from tenants.repository import TenantRepository


def test_explicit_sqlite_path_preserves_current_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://ignored.example/db")
    db = tmp_path / "runtime.db"
    store = RuntimeStore(database_path=db)
    assert store.database_path == db
    assert db.exists()


def test_database_url_sqlite_is_supported(tmp_path, monkeypatch):
    db = tmp_path / "configured.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    store = RuntimeStore()
    assert store.database_path == db
    assert db.exists()


def test_postgresql_url_is_selected_without_opening_connection(monkeypatch):
    url = "postgresql://user:password@db.example:5432/zero_xray"
    monkeypatch.setenv("DATABASE_URL", url)
    target = resolve_database_target(None, Path("unused.db"))
    assert target == url
    assert is_postgresql(target)


def test_requested_indexes_are_created_for_tenant_scoped_tables(tmp_path):
    runtime = RuntimeStore(tmp_path / "runtime.db")
    ServiceStore(runtime.database_path)
    with sqlite3.connect(runtime.database_path) as connection:
        names = {row[1] for row in connection.execute("PRAGMA index_list('analyses')")}
        assert "idx_analyses_tenant_id" in names
        assert "idx_analyses_service_id" in names
        assert "idx_analyses_blueprint_id" in names
        assert "idx_analyses_created_at" in names


def test_database_blocks_cross_tenant_service_reference(tmp_path):
    runtime = RuntimeStore(tmp_path / "runtime.db")
    services = ServiceStore(runtime.database_path)
    tenants = TenantRepository(runtime.database_path)
    tenant_a = tenants.create_tenant("A", "tenant-a")
    tenant_b = tenants.create_tenant("B", "tenant-b")
    service_a = services.create_service(tenant_a["id"], "Service A")

    with pytest.raises(sqlite3.IntegrityError):
        with runtime._connect() as connection:
            connection.execute(
                """
                INSERT INTO analyses
                (id, tenant_id, service_id, blueprint_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("bad-analysis", tenant_b["id"], service_a["id"], "bp-x", "RUNNING", "now", "now"),
            )
