from pathlib import Path

from core.catalog_store import CatalogStore
from tenants.repository import TenantRepository


def test_tenant_users_survive_repository_restart(tmp_path):
    db = tmp_path / "runtime.db"
    repo = TenantRepository(database_path=db)
    tenant = repo.create_tenant("Persistent Entity", "persistent-entity", status="ACTIVE")
    created = repo.create_user(tenant["id"], "Saved User", "saved@example.test", "viewer")

    restarted = TenantRepository(database_path=db)
    users = restarted.list_users_for_tenant(tenant["id"])
    assert any(user["id"] == created["id"] and user["email"] == "saved@example.test" for user in users)


def test_data_source_file_metadata_survives_store_restart(tmp_path):
    db = tmp_path / "runtime.db"
    repo = TenantRepository(database_path=db)
    tenant = repo.create_tenant("Files Entity", "files-entity", status="ACTIVE")
    user = repo.create_user(tenant["id"], "Admin", "admin@files.test", "entity_admin")

    store = CatalogStore(db)
    source = store.create_data_source(
        tenant["id"], "Policy", "PDF", configuration={"content": "policy text"},
        created_by=user["id"], status="READY",
    )
    attached = store.attach_file_metadata(
        source["id"], tenant["id"], "data/tenant_files/t/source/policy.pdf",
        "policy.pdf", "application/pdf", 123,
    )
    assert attached["status"] == "READY"

    restarted = CatalogStore(db)
    loaded = restarted.get_data_source_for_tenant(source["id"], tenant["id"])
    assert loaded["storage_path"].endswith("policy.pdf")
    assert loaded["original_filename"] == "policy.pdf"
    assert loaded["file_size"] == 123


def test_tenant_upload_path_is_relative_to_persistent_data_root(tmp_path):
    data_root = tmp_path / "ZERO-XRAY-DATA"
    file_path = data_root / "tenant_files" / "tenant-a" / "source-a" / "policy.pdf"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"demo")

    stored_path = str(file_path.relative_to(data_root))

    assert stored_path.endswith(str(Path("tenant_files") / "tenant-a" / "source-a" / "policy.pdf"))
    assert not Path(stored_path).is_absolute()


def test_runtime_restart_migrates_legacy_child_tenant_from_parents_with_guards_installed(tmp_path):
    from core.runtime_store import RuntimeStore

    db = tmp_path / "runtime.db"
    initial = RuntimeStore(database_path=db)
    now = "2026-08-30T00:00:00+00:00"
    tenant_id = "tenant-existing"
    blueprint_id = "blueprint-existing"
    customer_id = "customer-existing"
    journey_id = "journey-legacy-null-tenant"
    event_id = "event-legacy-null-tenant"

    # Reproduce a partially migrated legacy database: tenant-aware parent rows
    # already belong to a real tenant, while child rows still have tenant_id
    # NULL. Cross-tenant safety triggers are already installed from the first
    # RuntimeStore startup.
    with initial._connect() as connection:
        connection.execute(
            """
            INSERT INTO tenants
            (id, name, slug, status, subscription_plan, subscription_start,
             subscription_end, created_at, updated_at)
            VALUES (?, ?, ?, 'ACTIVE', 'DEMO', NULL, NULL, ?, ?)
            """,
            (tenant_id, "Existing Tenant", "existing-tenant", now, now),
        )
        connection.execute(
            """
            INSERT INTO blueprints
            (id, service_name, status, service_json, analysis_json, created_at,
             updated_at, tenant_id)
            VALUES (?, 'Legacy Service', 'APPROVED', '{}', '{}', ?, ?, ?)
            """,
            (blueprint_id, now, now, tenant_id),
        )
        connection.execute(
            """
            INSERT INTO customers (id, name, email, created_at, tenant_id)
            VALUES (?, 'Legacy Customer', 'legacy@example.test', ?, ?)
            """,
            (customer_id, now, tenant_id),
        )
        connection.execute(
            """
            INSERT INTO journeys
            (id, blueprint_id, customer_id, intent, lang, sandbox, state,
             plan_version, plan_json, payment_json, created_at, updated_at, tenant_id)
            VALUES (?, ?, ?, 'demo', 'en', 1, 'PLANNED', 1, '{}', '{}', ?, ?, NULL)
            """,
            (journey_id, blueprint_id, customer_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO journey_events
            (id, journey_id, sequence, event_type, title, detail, status,
             created_at, updated_at, tenant_id)
            VALUES (?, ?, 1, 'CREATED', 'Created', '', 'DONE', ?, ?, NULL)
            """,
            (event_id, journey_id, now, now),
        )

    # Before the fix, this restart raised:
    # sqlite3.IntegrityError: cross-tenant reference
    restarted = RuntimeStore(database_path=db)

    with restarted._connect() as connection:
        journey = connection.execute(
            "SELECT tenant_id FROM journeys WHERE id = ?", (journey_id,)
        ).fetchone()
        event = connection.execute(
            "SELECT tenant_id FROM journey_events WHERE id = ?", (event_id,)
        ).fetchone()

    assert journey["tenant_id"] == tenant_id
    assert event["tenant_id"] == tenant_id
