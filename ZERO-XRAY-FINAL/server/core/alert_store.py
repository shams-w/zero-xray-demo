"""Additive, isolated storage for the Monitoring/Alerts capability
(Step 8 of the ZERO X-RAY -> Government Future Engine evolution).

Follows the exact same pattern as core/prevention_store.py: its own
file, its own table, only ever CREATEs that new table, never ALTERs
an existing one.

STATE MACHINE (deterministic, no LLM, no invented states):
  - No open alert + breached=True  -> create a new alert, status="TRIGGERED"
  - Open alert (status="TRIGGERED") + breached=True  -> unchanged, same
    alert row returned (idempotent -- repeated checks while the
    underlying condition stays breached do not create duplicate alerts)
  - Open alert (status="TRIGGERED") + breached=False -> transition that
    alert to status="RESOLVED", set resolved_at
  - No open alert + breached=False -> no-op, nothing stored
An alert never claims to have been sent anywhere external (no email,
SMS, webhook) -- it is only ever a stored record of a real, re-checked
threshold breach/recovery.
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

from core.database import connect_database, resolve_database_target, table_columns, is_postgresql, ensure_database_safety


def _now():
    return datetime.now(timezone.utc).isoformat()


class AlertStore:
    """NOTE: like PreventionStore/EvolutionStore/..., assumes
    RuntimeStore has already initialized the shared db file."""

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
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    prevention_id TEXT NOT NULL,
                    trigger_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_value REAL,
                    threshold_value REAL NOT NULL,
                    checked_against TEXT,
                    evidence TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_tenant_id ON alerts (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_alerts_service_id ON alerts (service_id);
                CREATE INDEX IF NOT EXISTS idx_alerts_trigger_id ON alerts (trigger_id);
                """
            )

    def _row_to_dict(self, row):
        return dict(row) if row else None

    # --- Alerts -----------------------------------------------------

    def get_open_alert(self, tenant_id, service_id, trigger_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alerts WHERE tenant_id = ? AND service_id = ? AND trigger_id = ? "
                "AND status = 'TRIGGERED' ORDER BY created_at DESC LIMIT 1",
                (tenant_id, service_id, trigger_id),
            ).fetchone()
        return self._row_to_dict(row)

    def create_alert(self, tenant_id, service_id, prevention_id, trigger_id,
                      current_value, threshold_value, checked_against, evidence):
        alert_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO alerts
                (id, tenant_id, service_id, prevention_id, trigger_id, status,
                 current_value, threshold_value, checked_against, evidence,
                 created_at, updated_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, 'TRIGGERED', ?, ?, ?, ?, ?, ?, NULL)
                """,
                (alert_id, tenant_id, service_id, prevention_id, trigger_id,
                 current_value, threshold_value, checked_against, evidence, now, now),
            )
        return self.get_alert_for_tenant(alert_id, tenant_id)

    def resolve_alert(self, alert_id, tenant_id, current_value, checked_against, evidence):
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE alerts
                SET status = 'RESOLVED', current_value = ?, checked_against = ?,
                    evidence = ?, updated_at = ?, resolved_at = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (current_value, checked_against, evidence, now, now, alert_id, tenant_id),
            )
        return self.get_alert_for_tenant(alert_id, tenant_id)

    def get_alert_for_tenant(self, alert_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alerts WHERE id = ? AND tenant_id = ?",
                (alert_id, tenant_id),
            ).fetchone()
        return self._row_to_dict(row)

    def list_alerts_for_service(self, service_id, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts WHERE service_id = ? AND tenant_id = ? "
                "ORDER BY created_at DESC",
                (service_id, tenant_id),
            ).fetchall()
        return [dict(row) for row in rows]


# =========================================================================
# STORED ALERTS PRESENTATION FIX (additive, read-only, no schema change)
# =========================================================================
# Root cause: list_alerts_for_service() above (UNCHANGED) already
# returns every alert this service has ever had, most-recent-first --
# correct for audit/history, but with no way to tell an alert from the
# CURRENT Challenge->Evolve->Prevent chain apart from one left over
# from an older chain (different threshold_value, since Prevent's
# threshold is derived from Challenge/Evolve values that can change
# between runs). trigger_id is deterministic
# (f"{trigger_type}:{proposal_id}", see agents/prevent_agent.py), so
# the SAME trigger_id can legitimately recur across separate
# Prevention runs over the service's lifetime -- that is precisely how
# an old run's alert (e.g. "50 / threshold 40") and a fresh one from
# the current run (e.g. "25 / threshold 20") can both be real, valid,
# stored rows for what looks like "the same" trigger.
#
# These two pure, DB-free functions classify and reorder an already-
# fetched alert list -- they never query the database themselves,
# never delete/resolve/mutate a stored alert, and are called only from
# main.py's read-only GET /api/services/{id}/alerts endpoint. Nothing
# about alert creation, resolution, trigger evaluation, or threshold
# comparison (core/alert_store.py's existing methods, agents/
# monitoring_agent.py, agents/prevent_agent.py) is touched.

def determine_current_prevention_id(preventions_for_service):
    """`preventions_for_service` is exactly what
    PreventionStore.list_preventions_for_service() returns (ordered
    DESC by created_at, unchanged) -- the first entry is the CURRENT
    monitoring context for this service. Returns None when the
    service has no stored Prevention run at all (nothing is "current"
    yet)."""
    if not preventions_for_service:
        return None
    return preventions_for_service[0]["id"]


def classify_and_order_alerts(alerts, current_prevention_id, prevention_to_challenge_id=None):
    """Additive, read-only classification for the Stored Alerts
    presentation fix. Never deletes, mutates, resolves, or reorders
    WITHIN a group -- it only labels each alert and partitions the
    list into [current alerts...] + [historical alerts...], each
    group keeping the relative (already created_at DESC) order it
    arrived in.

    `prevention_to_challenge_id` is an optional {prevention_id:
    challenge_id} lookup the caller can supply (resolved via
    PreventionStore -> EvolutionStore, both unchanged) so each alert
    can additionally report which Challenge run it traces back to;
    omitted/unresolvable entries get source_challenge_id=None rather
    than a guess.

    Every original alert field is preserved unchanged; only new,
    additive keys are added: is_current, is_historical,
    current_context_id, source_prevention_id, source_challenge_id.
    """
    prevention_to_challenge_id = prevention_to_challenge_id or {}
    current, historical = [], []
    for alert in alerts:
        prevention_id = alert.get("prevention_id")
        is_current = current_prevention_id is not None and prevention_id == current_prevention_id
        enriched = {
            **alert,
            "is_current": is_current,
            "is_historical": not is_current,
            "current_context_id": current_prevention_id,
            "source_prevention_id": prevention_id,
            "source_challenge_id": prevention_to_challenge_id.get(prevention_id),
        }
        (current if is_current else historical).append(enriched)
    return current + historical

