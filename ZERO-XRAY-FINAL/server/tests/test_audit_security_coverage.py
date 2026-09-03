import json
import tempfile
import unittest
from pathlib import Path

from core.runtime_store import RuntimeStore


class AuditSecurityCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RuntimeStore(database_path=Path(self.tmp.name) / "audit.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_audit_retains_core_attribution_fields_and_sanitizes_secrets(self):
        self.store.record_audit(
            "tenant-a", "user-a", "INTEGRATION_CONFIGURED", "integration", "int-a",
            {
                "status": "CONNECTED",
                "password": "do-not-store",
                "token": "raw-bearer",
                "api_key": "raw-key",
                "nested": {"client_secret": "hidden", "safe": "kept"},
            },
        )
        entry = self.store.list_audit_log_for_tenant("tenant-a")[0]
        self.assertEqual(entry["tenant_id"], "tenant-a")
        self.assertEqual(entry["actor_user_id"], "user-a")
        self.assertEqual(entry["action"], "INTEGRATION_CONFIGURED")
        self.assertEqual(entry["entity_type"], "integration")
        self.assertEqual(entry["entity_id"], "int-a")
        self.assertTrue(entry["created_at"])
        details = json.loads(entry["details_json"])
        self.assertEqual(details["status"], "CONNECTED")
        self.assertEqual(details["nested"], {"safe": "kept"})
        serialized = json.dumps(details).lower()
        for forbidden in ("do-not-store", "raw-bearer", "raw-key", "client_secret", "password", "api_key"):
            self.assertNotIn(forbidden, serialized)

    def test_audit_is_append_only_at_store_surface(self):
        self.assertFalse(hasattr(self.store, "update_audit"))
        self.assertFalse(hasattr(self.store, "delete_audit"))
        self.assertFalse(hasattr(self.store, "clear_audit"))


if __name__ == "__main__":
    unittest.main()
