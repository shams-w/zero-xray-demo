"""Additive, isolated storage for the Future Simulation capability
(Step 2 of the ZERO X-RAY -> Government Future Engine evolution).

Follows the exact same pattern as core/prediction_store.py: its own
file, its own table, only ever CREATEs that new table, never ALTERs
an existing one. A single `scenarios` row stores both the scenario
definition that was actually executed (`scenario_json`) and the full
computed result (`result_json`) together, so a stored scenario is
reproducible/auditable later -- the same posture Predict already
takes with its `input_snapshot_json` + `result_json` pair.
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


SCENARIO_TYPES = {"VOLUME_SURGE", "INTEGRATION_FAILURE", "SLA_BREACH", "CASCADING_STEP_FAILURE"}
TRIGGER_TYPES = {"PREDICTION", "MANUAL", "AUTO"}


class SimulationStore:
    """NOTE: like PredictionStore/ServiceStore, assumes RuntimeStore
    has already initialized the shared db file."""

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
                CREATE TABLE IF NOT EXISTS scenarios (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    scenario_type TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    trigger_reference_id TEXT,
                    scenario_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_by TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_id ON scenarios (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_scenarios_service_id ON scenarios (service_id);
                """
            )

    # --- Scenarios --------------------------------------------------

    def save_scenario(self, tenant_id, service_id, scenario_type, trigger_type,
                       trigger_reference_id, scenario, result, created_by=None):
        if scenario_type not in SCENARIO_TYPES:
            raise ValueError(f"Unsupported scenario_type: {scenario_type}")
        if trigger_type not in TRIGGER_TYPES:
            raise ValueError(f"Unsupported trigger_type: {trigger_type}")
        scenario_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scenarios
                (id, tenant_id, service_id, scenario_type, trigger_type,
                 trigger_reference_id, scenario_json, result_json, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (scenario_id, tenant_id, service_id, scenario_type, trigger_type,
                 trigger_reference_id, _json(scenario), _json(result), created_by, now),
            )
        return self.get_scenario_for_tenant(scenario_id, tenant_id)

    def get_scenario_for_tenant(self, scenario_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scenarios WHERE id = ? AND tenant_id = ?",
                (scenario_id, tenant_id),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["scenario"] = _read_json(item.pop("scenario_json", None))
        item["result"] = _read_json(item.pop("result_json", None))
        return item

    def list_scenarios_for_service(self, service_id, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scenarios WHERE service_id = ? AND tenant_id = ? "
                "ORDER BY created_at DESC",
                (service_id, tenant_id),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["scenario"] = _read_json(item.pop("scenario_json", None))
            item["result"] = _read_json(item.pop("result_json", None))
            results.append(item)
        return results
