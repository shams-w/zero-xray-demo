"""Validation boundary for service integrations before execution.

Current customer journeys remain Sandbox-only.  The validator distinguishes
CONNECTED, SANDBOX and NOT_CONNECTED so no simulated path can be represented
as successful real-world external execution.  A future real adapter can call
``validate_real_execution`` before making an external API request.
"""

EXECUTION_PERMISSION_VALUES = {"EXECUTE", "EXECUTION", "WRITE", "CALL"}


class IntegrationExecutionError(ValueError):
    def __init__(self, message, state="INTEGRATION_REQUIRED", details=None):
        super().__init__(message)
        self.state = state
        self.details = details or {}


class IntegrationExecutionValidator:
    def __init__(self, service_store, catalog_store):
        self.service_store = service_store
        self.catalog_store = catalog_store

    @staticmethod
    def _has_execution_permission(integration):
        config = integration.get("config") or {}
        if config.get("allow_execution") is True or config.get("execution_enabled") is True:
            return True
        configured = config.get("permissions") or config.get("allowed_operations") or []
        if isinstance(configured, str):
            configured = [configured]
        values = {str(value).strip().upper() for value in configured}
        return bool(values & EXECUTION_PERMISSION_VALUES)

    @staticmethod
    def _has_real_configuration(integration):
        config = integration.get("config") or {}
        # A CONNECTED production integration needs non-secret connection
        # configuration and, for adapters that require credentials, a secret
        # reference.  Secret material itself is intentionally never inspected.
        return bool(config) and bool(integration.get("secret_reference") or config.get("credentialless") is True)

    def _service_integrations(self, tenant_id, service_id):
        service = self.service_store.get_service_for_tenant(service_id, tenant_id)
        if not service:
            raise IntegrationExecutionError("Service is not available for this tenant.")
        ids = self.service_store.get_service_connection_ids(service_id, tenant_id).get("integration_ids", [])
        integrations = []
        for integration_id in ids:
            integration = self.catalog_store.get_integration_for_tenant(integration_id, tenant_id)
            if not integration:
                # Covers tenant ownership plus broken/cross-tenant relationship.
                raise IntegrationExecutionError(
                    "A configured service integration is not available for this tenant.",
                    details={"integration_id": integration_id},
                )
            integrations.append(integration)
        return integrations

    def validate_sandbox_journey(self, tenant_id, service_id, required_integrations=None):
        """Validate current Sandbox execution without pretending it is real."""
        integrations = self._service_integrations(tenant_id, service_id)
        required_integrations = required_integrations or []
        if required_integrations and not integrations:
            # Customer journeys in this endpoint are explicitly SANDBOX-only and
            # perform no external adapter/API call.  `required_integrations` comes
            # from the AI-designed Blueprint and can therefore describe conceptual
            # systems even when the entity has not configured a catalog integration
            # yet.  Allow the demo simulation to continue, while making the
            # non-real status explicit.  Actual configured NOT_CONNECTED
            # integrations are still rejected below, and real execution remains
            # protected by validate_real_execution().
            return {
                "state": "SANDBOX_READY",
                "real_world_execution": False,
                "integrations": [],
                "simulated_required_integrations": required_integrations,
                "integration_configuration_missing": True,
            }
        unavailable = [item for item in integrations if item.get("status") == "NOT_CONNECTED"]
        if unavailable:
            raise IntegrationExecutionError(
                "A required service integration is not connected.",
                details={"integration_ids": [item["id"] for item in unavailable]},
            )
        return {
            "state": "SANDBOX_READY",
            "real_world_execution": False,
            "integrations": [
                {"id": item["id"], "status": item.get("status"), "real_world_execution": False}
                for item in integrations
            ],
        }

    def validate_real_execution(self, tenant_id, service_id, integration_id):
        """Future production guard. Does not make an external API call."""
        integrations = self._service_integrations(tenant_id, service_id)
        integration = next((item for item in integrations if item["id"] == integration_id), None)
        if not integration:
            raise IntegrationExecutionError("Integration is not assigned to this service.")
        if integration.get("status") != "CONNECTED":
            raise IntegrationExecutionError("Integration is not CONNECTED for real-world execution.")
        if not self._has_real_configuration(integration):
            raise IntegrationExecutionError("Integration configuration is incomplete.")
        if not self._has_execution_permission(integration):
            raise IntegrationExecutionError("Integration does not grant execution permission.")
        return {
            "state": "CONNECTED",
            "integration_id": integration["id"],
            "tenant_id": tenant_id,
            "service_id": service_id,
            "real_world_execution": False,
            "adapter_call_performed": False,
        }
