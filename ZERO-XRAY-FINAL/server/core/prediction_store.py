"""Additive, isolated storage for the Predict capability (Step 1 of
the ZERO X-RAY -> Government Future Engine evolution).

Deliberately its OWN file and its OWN table, following the exact
connection/table-creation pattern already used by ServiceStore /
AgentStore / CatalogStore (see core/service_store.py). Predict must
never modify any existing table or column (blueprints, journeys,
services, analyses, ...) -- this store only ever CREATEs its own new
`predictions` table and only ever reads the existing tables through
the callers that already own them (ServiceStore / a read-only SQL
query in agents/prediction_agent.py). Nothing here ALTERs an existing
table.

`input_snapshot_json` is stored alongside `result_json` on purpose:
it is the exact PredictionInput the agent actually used, so a stored
prediction is reproducible and auditable later -- the same
accountability RuntimeStore's `audit_log` table already gives
Blueprint state changes, applied here to predictions.
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


DATA_SUFFICIENCY_LEVELS = {"SUFFICIENT", "LIMITED", "INSUFFICIENT"}


class PredictionStore:
    """NOTE: like ServiceStore/AgentStore/CatalogStore, assumes
    RuntimeStore has already initialized the shared db file (for the
    `tenants` FK relationship)."""

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
                CREATE TABLE IF NOT EXISTS predictions (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    input_snapshot_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    data_sufficiency TEXT NOT NULL,
                    created_by TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_predictions_tenant_id ON predictions (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_predictions_service_id ON predictions (service_id);
                """
            )

    # --- Predictions ----------------------------------------------------

    def save_prediction(self, tenant_id, service_id, input_snapshot, result,
                         data_sufficiency, created_by=None):
        if data_sufficiency not in DATA_SUFFICIENCY_LEVELS:
            raise ValueError(f"Unsupported data_sufficiency: {data_sufficiency}")
        prediction_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO predictions
                (id, tenant_id, service_id, generated_at, input_snapshot_json,
                 result_json, data_sufficiency, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (prediction_id, tenant_id, service_id, now, _json(input_snapshot),
                 _json(result), data_sufficiency, created_by, now),
            )
        return self.get_prediction_for_tenant(prediction_id, tenant_id)

    def get_prediction_for_tenant(self, prediction_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM predictions WHERE id = ? AND tenant_id = ?",
                (prediction_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["input_snapshot"] = _read_json(item.pop("input_snapshot_json", None))
        item["result"] = _read_json(item.pop("result_json", None))
        return item

    def list_predictions_for_service(self, service_id, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM predictions WHERE service_id = ? AND tenant_id = ? "
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
