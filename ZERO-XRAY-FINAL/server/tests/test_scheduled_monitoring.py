import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from core.monitoring_schedule_store import MonitoringScheduleStore
from core.monitoring_scheduler import MonitoringScheduler
from core.notification_provider import (
    DATABASE_ONLY,
    EMAIL_NOT_CONNECTED,
    SMS_NOT_CONNECTED,
    WEBHOOK_NOT_CONNECTED,
    DatabaseOnlyNotificationProvider,
)
from tenants.models import has_permission


class ScheduledMonitoringStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "runtime.db"
        self.store = MonitoringScheduleStore(str(self.db))

    def tearDown(self):
        self.tmp.cleanup()

    def test_schedule_can_be_enabled_hourly_and_disabled(self):
        enabled = self.store.upsert("tenant-1", "service-1", True, "hourly", "owner-1")
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["frequency"], "hourly")
        self.assertIsNotNone(enabled["next_run_at"])

        disabled = self.store.upsert("tenant-1", "service-1", False, "daily", "owner-1")
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["frequency"], "daily")
        self.assertIsNone(disabled["next_run_at"])

    def test_due_schedule_runs_once_and_advances_next_run(self):
        schedule = self.store.upsert("tenant-1", "service-1", True, "hourly", "owner-1")
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE monitoring_schedules SET next_run_at = ? WHERE id = ?",
                (past, schedule["id"]),
            )

        calls = []
        scheduler = MonitoringScheduler(self.store, lambda row: calls.append(row), poll_seconds=60)
        scheduler.run_due_once()
        self.assertEqual(len(calls), 1)

        updated = self.store.get_for_service("tenant-1", "service-1")
        self.assertIsNotNone(updated["last_run_at"])
        self.assertGreater(
            datetime.fromisoformat(updated["next_run_at"]),
            datetime.fromisoformat(updated["last_run_at"]),
        )

    def test_disabled_schedule_is_never_due(self):
        self.store.upsert("tenant-1", "service-1", False, "hourly", "owner-1")
        self.assertEqual(self.store.list_due(), [])


class NotificationProviderTests(unittest.TestCase):
    def test_database_only_provider_does_not_claim_external_delivery(self):
        provider = DatabaseOnlyNotificationProvider()
        result = provider.notify_alert({"id": "alert-1"})
        self.assertEqual(result["state"], DATABASE_ONLY)
        self.assertFalse(result["delivered_externally"])

        status = provider.public_status()
        self.assertEqual(status["state"], DATABASE_ONLY)
        self.assertEqual(status["email"], EMAIL_NOT_CONNECTED)
        self.assertEqual(status["sms"], SMS_NOT_CONNECTED)
        self.assertEqual(status["webhook"], WEBHOOK_NOT_CONNECTED)
        self.assertFalse(status["external_delivery_configured"])


class ScheduledMonitoringPermissionTests(unittest.TestCase):
    def test_only_entity_admin_and_service_owner_have_monitor_permission(self):
        self.assertTrue(has_permission("entity_admin", "future:monitor"))
        self.assertTrue(has_permission("service_owner", "future:monitor"))
        self.assertFalse(has_permission("analyst", "future:monitor"))
        self.assertFalse(has_permission("viewer", "future:monitor"))


if __name__ == "__main__":
    unittest.main()
