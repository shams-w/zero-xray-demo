"""Additive, isolated storage for the Prevent capability (Step 5 of
the ZERO X-RAY -> Government Future Engine evolution).

Follows the exact same pattern as core/evolution_store.py: its own
file, its own table, only ever CREATEs that new table, never ALTERs
an existing one.
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


class PreventionStore:
    """NOTE: like EvolutionStore/ChallengeStore/SimulationStore/
    PredictionStore, assumes RuntimeStore has already initialized the
    shared db file."""

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
                CREATE TABLE IF NOT EXISTS preventions (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    evolution_id TEXT NOT NULL,
                    input_snapshot_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_by TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_preventions_tenant_id ON preventions (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_preventions_service_id ON preventions (service_id);
                """
            )

    # --- Preventions ------------------------------------------------------

    def save_prevention(self, tenant_id, service_id, evolution_id, input_snapshot, result,
                         created_by=None):
        prevention_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO preventions
                (id, tenant_id, service_id, evolution_id, input_snapshot_json, result_json,
                 created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (prevention_id, tenant_id, service_id, evolution_id, _json(input_snapshot),
                 _json(result), created_by, now),
            )
        return self.get_prevention_for_tenant(prevention_id, tenant_id)

    def get_prevention_for_tenant(self, prevention_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM preventions WHERE id = ? AND tenant_id = ?",
                (prevention_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["input_snapshot"] = _read_json(item.pop("input_snapshot_json", None))
        item["result"] = _read_json(item.pop("result_json", None))
        return item

    def list_preventions_for_service(self, service_id, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM preventions WHERE service_id = ? AND tenant_id = ? "
                "ORDER BY created_at DESC",
                (service_id, tenant_id),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["input_snapshot"] = _read_json(item.pop("input_snapshot_json", None))
            item["result"] = _read_json(item.pop("result_json", None))
            results.append(item)
        return results
