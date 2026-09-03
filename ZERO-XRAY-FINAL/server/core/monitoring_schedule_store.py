"""Small additive store for optional per-service scheduled monitoring."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from core.database import connect_database, ensure_database_safety


def _now_dt():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat()


def _next_run(frequency: str, from_time=None):
    base = from_time or _now_dt()
    delta = timedelta(hours=1) if frequency == "hourly" else timedelta(days=1)
    return _iso(base + delta)


class MonitoringScheduleStore:
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
                CREATE TABLE IF NOT EXISTS monitoring_schedules (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    frequency TEXT NOT NULL DEFAULT 'daily',
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at TEXT,
                    next_run_at TEXT,
                    UNIQUE (tenant_id, service_id)
                );
                CREATE INDEX IF NOT EXISTS idx_monitoring_schedules_tenant_id ON monitoring_schedules (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_monitoring_schedules_service_id ON monitoring_schedules (service_id);
                CREATE INDEX IF NOT EXISTS idx_monitoring_schedules_created_by ON monitoring_schedules (created_by);
                CREATE INDEX IF NOT EXISTS idx_monitoring_schedules_next_run_at ON monitoring_schedules (next_run_at);
                """
            )

    @staticmethod
    def _row(row):
        if not row:
            return None
        result = dict(row)
        result["enabled"] = bool(result.get("enabled"))
        return result

    def get_for_service(self, tenant_id, service_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM monitoring_schedules WHERE tenant_id = ? AND service_id = ?",
                (tenant_id, service_id),
            ).fetchone()
        return self._row(row)

    def upsert(self, tenant_id, service_id, enabled, frequency, actor_user_id):
        if frequency not in {"hourly", "daily"}:
            raise ValueError("Unsupported monitoring frequency")
        now = _now_dt()
        current = self.get_for_service(tenant_id, service_id)
        next_run_at = _next_run(frequency, now) if enabled else None
        with self._connect() as connection:
            if current:
                connection.execute(
                    """
                    UPDATE monitoring_schedules
                    SET enabled = ?, frequency = ?, updated_at = ?, next_run_at = ?
                    WHERE tenant_id = ? AND service_id = ?
                    """,
                    (1 if enabled else 0, frequency, _iso(now), next_run_at, tenant_id, service_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO monitoring_schedules
                    (id, tenant_id, service_id, enabled, frequency, created_by,
                     created_at, updated_at, last_run_at, next_run_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (str(uuid4()), tenant_id, service_id, 1 if enabled else 0,
                     frequency, actor_user_id, _iso(now), _iso(now), next_run_at),
                )
        return self.get_for_service(tenant_id, service_id)

    def list_due(self, now=None):
        now_iso = _iso(now or _now_dt())
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_schedules
                WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (now_iso,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def mark_run(self, schedule_id, frequency, ran_at=None):
        ran = ran_at or _now_dt()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE monitoring_schedules
                SET last_run_at = ?, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (_iso(ran), _next_run(frequency, ran), _iso(ran), schedule_id),
            )
