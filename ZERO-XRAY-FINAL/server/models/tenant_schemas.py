from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DemoLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=300)
    credential: str = Field(min_length=1, max_length=300)


class PublishAgentRequest(BaseModel):
    blueprint_id: str = Field(min_length=1, max_length=100)
    name: Optional[str] = Field(default=None, max_length=300)


class CreateDataSourceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    type: str = Field(min_length=1, max_length=50)
    classification: str = Field(default="TENANT_PRIVATE_SOURCE", max_length=50)
    configuration: Optional[dict] = None
    # Knowledge-source lifecycle is separate from integration connectivity.
    status: str = Field(default="READY", max_length=50)
    original_filename: Optional[str] = Field(default=None, max_length=500)
    mime_type: Optional[str] = Field(default=None, max_length=200)
    file_content_base64: Optional[str] = None


class CreateIntegrationRequest(BaseModel):
    type: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=300)
    config: Optional[dict] = None
    secret_reference: Optional[str] = Field(default=None, max_length=500)
    status: str = Field(default="NOT_CONNECTED", max_length=50)


class ImportOpenApiRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2_000)
    environment: str = Field(default="SANDBOX", max_length=50)
    name: Optional[str] = Field(default=None, max_length=300)
    integration_type: str = Field(default="GOVERNMENT_API", max_length=50)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value):
        if value not in {"CONNECTED", "SANDBOX", "NOT_CONNECTED"}:
            raise ValueError("environment must be CONNECTED, SANDBOX, or NOT_CONNECTED")
        return value


class CreateServiceRequest(BaseModel):
    service_name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=100_000)
    language: str = Field(default="en", max_length=10)
    data_source_ids: list[str] = Field(default_factory=list, max_length=100)
    integration_ids: list[str] = Field(default_factory=list, max_length=100)


class CreateTenantUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    email: str = Field(min_length=3, max_length=300)
    role: str = Field(min_length=1, max_length=50)


class UpdateUserRoleRequest(BaseModel):
    role: str = Field(min_length=1, max_length=50)


class UpdateUserStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=50)


class CreateGovernmentEntityRequest(BaseModel):
    entity_name: str = Field(min_length=1, max_length=300)
    slug: str = Field(min_length=1, max_length=100)
    subscription_plan: str = Field(default="PILOT", max_length=50)
    subscription_start: Optional[str] = None
    subscription_end: Optional[str] = None
    admin_name: str = Field(min_length=1, max_length=300)
    admin_email: str = Field(min_length=3, max_length=300)


class UpdateGovernmentEntitySubscriptionRequest(BaseModel):
    status: Optional[str] = Field(default=None, max_length=50)
    subscription_plan: Optional[str] = Field(default=None, max_length=50)
    subscription_start: Optional[str] = None
    subscription_end: Optional[str] = None
    extend_days: Optional[int] = Field(default=None, ge=1, le=3650)


# Phase 8 -- Agent Comparison Readiness. Every field is optional: an
# employee describing an existing entity Agent will rarely know every
# detail, and a field left out must stay UNKNOWN/NOT_PROVIDED (see
# core/agent_comparison.py) rather than be treated as false/zero.
_TRISTATE_VALUES = {"SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "UNKNOWN"}


class ExternalAgentProfileRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=5_000)
    known_data_sources: Optional[list[str]] = Field(default=None, max_length=100)
    known_data_sources_count: Optional[int] = Field(default=None, ge=0, le=100_000)
    known_apis: Optional[list[str]] = Field(default=None, max_length=100)
    known_apis_count: Optional[int] = Field(default=None, ge=0, le=100_000)
    customer_steps: Optional[int] = Field(default=None, ge=0, le=100_000)
    automated_steps: Optional[int] = Field(default=None, ge=0, le=100_000)
    manual_steps: Optional[int] = Field(default=None, ge=0, le=100_000)
    integration_required_steps: Optional[int] = Field(default=None, ge=0, le=100_000)
    automatic_data_fetching: Optional[str] = Field(default=None, max_length=20)
    transaction_execution: Optional[str] = Field(default=None, max_length=20)
    payment_supported: Optional[bool] = None
    human_handoff: Optional[bool] = None
    api_limit_awareness: Optional[str] = Field(default=None, max_length=20)
    traceability_available: Optional[bool] = None
    evidence_notes: Optional[str] = Field(default=None, max_length=5_000)

    @field_validator("automatic_data_fetching", "transaction_execution", "api_limit_awareness")
    @classmethod
    def validate_tristate(cls, value):
        if value is not None and value not in _TRISTATE_VALUES:
            raise ValueError(f"Must be one of {sorted(_TRISTATE_VALUES)} or omitted.")
        return value
