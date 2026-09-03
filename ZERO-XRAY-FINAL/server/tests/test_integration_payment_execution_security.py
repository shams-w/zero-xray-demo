import unittest

from core.integration_execution import IntegrationExecutionError, IntegrationExecutionValidator
from core.payment_provider import PaymentValidationError, SandboxPaymentProvider


class FakeServiceStore:
    def __init__(self):
        self.services = {("tenant-a", "service-1"): {"id": "service-1", "tenant_id": "tenant-a"}}
        self.connections = {("tenant-a", "service-1"): []}

    def get_service_for_tenant(self, service_id, tenant_id):
        return self.services.get((tenant_id, service_id))

    def get_service_connection_ids(self, service_id, tenant_id):
        return {"data_source_ids": [], "integration_ids": list(self.connections.get((tenant_id, service_id), []))}


class FakeCatalogStore:
    def __init__(self):
        self.integrations = {}

    def get_integration_for_tenant(self, integration_id, tenant_id):
        return self.integrations.get((tenant_id, integration_id))


def integration(status, config=None, secret_reference=None):
    return {
        "id": "integration-1",
        "tenant_id": "tenant-a",
        "status": status,
        "config": config or {},
        "secret_reference": secret_reference,
    }


class IntegrationExecutionValidationTests(unittest.TestCase):
    def setUp(self):
        self.services = FakeServiceStore()
        self.catalog = FakeCatalogStore()
        self.validator = IntegrationExecutionValidator(self.services, self.catalog)

    def attach(self, row):
        self.services.connections[("tenant-a", "service-1")] = ["integration-1"]
        self.catalog.integrations[("tenant-a", "integration-1")] = row

    def test_not_connected_returns_controlled_integration_required(self):
        self.attach(integration("NOT_CONNECTED"))
        with self.assertRaises(IntegrationExecutionError) as caught:
            self.validator.validate_sandbox_journey("tenant-a", "service-1", [{"name": "API"}])
        self.assertEqual(caught.exception.state, "INTEGRATION_REQUIRED")

    def test_sandbox_is_allowed_only_as_non_real_execution(self):
        self.attach(integration("SANDBOX"))
        result = self.validator.validate_sandbox_journey("tenant-a", "service-1", [{"name": "API"}])
        self.assertEqual(result["state"], "SANDBOX_READY")
        self.assertFalse(result["real_world_execution"])
        with self.assertRaises(IntegrationExecutionError):
            self.validator.validate_real_execution("tenant-a", "service-1", "integration-1")

    def test_connected_real_execution_requires_config_and_permission(self):
        self.attach(integration("CONNECTED", config={"base_url": "https://example.invalid"}, secret_reference="vault/path"))
        with self.assertRaises(IntegrationExecutionError):
            self.validator.validate_real_execution("tenant-a", "service-1", "integration-1")
        self.catalog.integrations[("tenant-a", "integration-1")]["config"]["permissions"] = ["EXECUTE"]
        result = self.validator.validate_real_execution("tenant-a", "service-1", "integration-1")
        self.assertEqual(result["state"], "CONNECTED")
        self.assertFalse(result["real_world_execution"])
        self.assertFalse(result["adapter_call_performed"])

    def test_cross_tenant_or_unrelated_integration_is_denied(self):
        self.services.connections[("tenant-a", "service-1")] = ["integration-1"]
        self.catalog.integrations[("tenant-b", "integration-1")] = integration("CONNECTED")
        with self.assertRaises(IntegrationExecutionError):
            self.validator.validate_sandbox_journey("tenant-a", "service-1", [])
        with self.assertRaises(IntegrationExecutionError):
            self.validator.validate_real_execution("tenant-a", "service-1", "integration-other")

    def test_unconfigured_conceptual_integration_is_simulated_only_in_sandbox(self):
        result = self.validator.validate_sandbox_journey(
            "tenant-a", "service-1", [{"name": "Payment API"}]
        )
        self.assertEqual(result["state"], "SANDBOX_READY")
        self.assertFalse(result["real_world_execution"])
        self.assertTrue(result["integration_configuration_missing"])
        self.assertEqual(result["simulated_required_integrations"], [{"name": "Payment API"}])


class PaymentProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = SandboxPaymentProvider()

    def test_free_service_has_no_payment(self):
        with self.assertRaises(PaymentValidationError):
            self.provider.create_payment({"requires_payment": False}, "SANDBOX_CARD")

    def test_unknown_fee_is_never_invented(self):
        plan = {"requires_payment": True, "fee_status": "VERIFY", "fee_amount": None}
        with self.assertRaises(PaymentValidationError):
            self.provider.create_payment(plan, "SANDBOX_CARD")

    def test_server_catalog_recalculates_authoritative_amount(self):
        plan = {
            "requires_payment": True,
            "fee_status": "REQUIRED",
            "fee_amount": 1.0,  # deliberately wrong/rendered value
            "fee_currency": "AED",
            "payment_timing": "BEFORE_EXECUTION",
            "selected_package_id": "pkg",
            "contract_years": 2,
            "add_on_quantities": {},
            "edit_options": {
                "currency": "AED",
                "packages": [{"id": "pkg", "name": "Package", "price_per_year": 100.0, "billing_period": "YEAR"}],
                "one_time_fees": [],
                "add_ons": [],
                "tax": {"status": "NOT_CONFIRMED"},
            },
        }
        payment = self.provider.create_payment(plan, "SANDBOX_CARD")
        self.assertEqual(payment["amount"], 200.0)
        self.assertEqual(payment["amount_authority"], "SERVER_CATALOG")
        self.assertTrue(payment["sandbox"])
        self.assertFalse(payment["real_gateway_execution"])

    def test_deferred_server_assessment_is_authoritative_in_sandbox(self):
        plan = {
            "requires_payment": True,
            "fee_status": "REQUIRED",
            "fee_amount": 185.0,
            "fee_currency": "AED",
            "payment_timing": "AFTER_PHYSICAL_VERIFICATION",
            "physical_checkpoint": {"status": "COMPLETED", "quote_reference": "SBX-QUOTE"},
            "edit_options": {"packages": [{"id": "standard", "name": "Standard"}]},
        }
        payment = self.provider.create_payment(plan, "SANDBOX_CARD")
        self.assertEqual(payment["amount"], 185.0)
        self.assertEqual(payment["amount_authority"], "SANDBOX_ASSESSMENT")
        self.assertFalse(payment["real_gateway_execution"])


if __name__ == "__main__":
    unittest.main()
