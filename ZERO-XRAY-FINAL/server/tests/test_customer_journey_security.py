"""Focused tests for public customer journey capability security.

These tests intentionally exercise the persistence/validation boundary without
employee authentication. Endpoint routes call this validator before every
customer-sensitive journey operation.
"""
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.runtime_store import RuntimeStore


def _seed_journey(store, tenant_id, customer_id, journey_id, blueprint_id):
    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "requires_payment": False,
        "edit_options": {"mode": "ACTION"},
        "actions": [],
    }
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO customers (id, name, email, created_at, tenant_id) VALUES (?, ?, ?, ?, ?)",
            (customer_id, customer_id, f"{customer_id}@example.invalid", now, tenant_id),
        )
        connection.execute(
            """
            INSERT INTO blueprints
            (id, service_name, status, service_json, analysis_json, created_at,
             updated_at, tenant_id)
            VALUES (?, ?, 'PUBLISHED', ?, ?, ?, ?, ?)
            """,
            (blueprint_id, blueprint_id, json.dumps({}), json.dumps({}), now, now, tenant_id),
        )
        connection.execute(
            """
            INSERT INTO journeys
            (id, blueprint_id, customer_id, intent, lang, sandbox, state,
             plan_version, plan_json, payment_json, created_at, updated_at,
             tenant_id)
            VALUES (?, ?, ?, 'test', 'en', 1, 'PLAN_READY', 1, ?, '{}', ?, ?, ?)
            """,
            (journey_id, blueprint_id, customer_id, json.dumps(plan), now, now, tenant_id),
        )


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as directory:
        runtime = RuntimeStore(database_path=Path(directory) / "runtime.db")
        yield runtime


def test_correct_token_allowed(store):
    _seed_journey(store, "tenant-a", "customer-a", "journey-a", "blueprint-a")
    token, _ = store.issue_journey_capability("journey-a", "customer-a", ttl_seconds=3600)

    journey = store.validate_journey_capability("journey-a", token)

    assert journey is not None
    assert journey["customer_id"] == "customer-a"
    assert journey["tenant_id"] == "tenant-a"


def test_wrong_token_denied(store):
    _seed_journey(store, "tenant-a", "customer-a", "journey-a", "blueprint-a")
    store.issue_journey_capability("journey-a", "customer-a", ttl_seconds=3600)

    assert store.validate_journey_capability("journey-a", "wrong-token") is None


def test_expired_token_denied(store):
    _seed_journey(store, "tenant-a", "customer-a", "journey-a", "blueprint-a")
    token, _ = store.issue_journey_capability("journey-a", "customer-a", ttl_seconds=3600)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE journey_capabilities SET expires_at = ? WHERE journey_id = ?",
            (expired, "journey-a"),
        )

    assert store.validate_journey_capability("journey-a", token) is None


def test_customer_a_cannot_access_customer_b_journey(store):
    _seed_journey(store, "tenant-a", "customer-a", "journey-a", "blueprint-a")
    _seed_journey(store, "tenant-a", "customer-b", "journey-b", "blueprint-b")
    token_a, _ = store.issue_journey_capability("journey-a", "customer-a", ttl_seconds=3600)

    assert store.validate_journey_capability("journey-b", token_a) is None
    with pytest.raises(ValueError, match="mismatch"):
        store.issue_journey_capability("journey-b", "customer-a", ttl_seconds=3600)


def test_cross_tenant_access_denied(store):
    _seed_journey(store, "tenant-a", "customer-a", "journey-a", "blueprint-a")
    _seed_journey(store, "tenant-b", "customer-b", "journey-b", "blueprint-b")
    token_a, _ = store.issue_journey_capability("journey-a", "customer-a", ttl_seconds=3600)
    token_b, _ = store.issue_journey_capability("journey-b", "customer-b", ttl_seconds=3600)

    assert store.validate_journey_capability("journey-b", token_a) is None
    assert store.validate_journey_capability("journey-a", token_b) is None


def test_revoked_token_denied(store):
    _seed_journey(store, "tenant-a", "customer-a", "journey-a", "blueprint-a")
    token, _ = store.issue_journey_capability("journey-a", "customer-a", ttl_seconds=3600)
    store.revoke_journey_capabilities("journey-a")

    assert store.validate_journey_capability("journey-a", token) is None
