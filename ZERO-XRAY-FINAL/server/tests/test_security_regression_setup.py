"""Cross-cutting regression checks for previously hardened security behavior.

These tests intentionally exercise existing public store/provider contracts only;
no production behavior is changed for testability.
"""
import json
import tempfile
import unittest
from pathlib import Path

from core.integration_execution import IntegrationExecutionError, IntegrationExecutionValidator
from core.payment_provider import PaymentValidationError, SandboxPaymentProvider
from core.runtime_store import RuntimeStore


class _Services:
    def get_service_for_tenant(self, service_id, tenant_id):
        if (service_id, tenant_id) == ("svc-1", "tenant-a"):
            return {"id": service_id, "tenant_id": tenant_id}
        return None

    def get_service_connection_ids(self, service_id, tenant_id):
        return {"data_source_ids": [], "integration_ids": ["int-1"]}


class _Catalog:
    def get_integration_for_tenant(self, integration_id, tenant_id):
        if (integration_id, tenant_id) == ("int-1", "tenant-a"):
            return {"id": integration_id, "tenant_id": tenant_id, "status": "NOT_CONNECTED", "config": {}}
        return None


class SecurityRegressionSetupTests(unittest.TestCase):
    def test_audit_writer_still_sanitizes_nested_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(database_path=Path(tmp) / "audit.db")
            store.record_audit("tenant-a", "user-a", "SECURITY_REGRESSION", "service", "svc-1", {
                "safe": "keep",
                "authorization": "Bearer should-not-persist",
                "nested": {"client_secret": "should-not-persist", "safe": "keep-too"},
            })
            row = store.list_audit_log_for_tenant("tenant-a")[0]
            details = json.loads(row["details_json"])
            self.assertEqual(details, {"safe": "keep", "nested": {"safe": "keep-too"}})

    def test_not_connected_integration_cannot_be_real_execution_success(self):
        validator = IntegrationExecutionValidator(_Services(), _Catalog())
        with self.assertRaises(IntegrationExecutionError):
            validator.validate_real_execution("tenant-a", "svc-1", "int-1")

    def test_unknown_payment_amount_is_not_invented(self):
        provider = SandboxPaymentProvider()
        with self.assertRaises(PaymentValidationError):
            provider.create_payment({"requires_payment": True, "fee_status": "VERIFY", "fee_amount": None}, "SANDBOX_CARD")


if __name__ == "__main__":
    unittest.main()
