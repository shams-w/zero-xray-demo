import base64
import binascii
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

import asyncio
import json
import os
import threading
import time

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import (
    CORSMiddleware
)
from fastapi.responses import StreamingResponse, JSONResponse

from models.schemas import (
    CustomerRegistration,
    JourneyStart,
    PlanEdit,
    SandboxPayment,
    ServiceInput,
    ScenarioCreateRequest,
    ChallengeCreateRequest,
    EvolveCreateRequest,
    PreventCreateRequest,
    MonitoringCheckRequest,
    MonitoringScheduleUpdateRequest,
)

from agents.orchestrator import (
    ServiceOrchestrator
)

from core.llm import REQUIRE_OLLAMA, ZX_LLM_MODE, ai_label


from core.pdf_reader import (
    get_full_standards_text
)

from core.i18n_dictionary import (
    translate_result,
    translate_error,
)
from core.runtime_store import RuntimeStore
from core.agent_store import AgentStore, sanitize_for_public
from core.catalog_store import CatalogStore
from core.service_store import ServiceStore
from core.prediction_store import PredictionStore
from core.simulation_store import SimulationStore
from core.challenge_store import ChallengeStore
from core.evolution_store import EvolutionStore
from core.prevention_store import PreventionStore
from core.alert_store import AlertStore, determine_current_prevention_id, classify_and_order_alerts
from core.monitoring_schedule_store import MonitoringScheduleStore
from core.monitoring_scheduler import MonitoringScheduler
from core.notification_provider import get_notification_provider
from core.integration_execution import IntegrationExecutionValidator, IntegrationExecutionError
from core.agent_capability_mapper import build_agent_capability_map
from core.agent_comparison import build_zero_xray_comparison_profile, build_external_agent_profile, build_comparison_readiness
from core.comparison_store import ComparisonStore
from core.api_operation_store import ApiOperationStore
from core.live_api_executor import LiveApiExecutor, LiveApiExecutionError
from core.openapi_importer import fetch_and_parse, OpenApiImportError
from core.url_safety import UnsafeUrlError
from core.data_paths import get_tenant_files_root, get_data_root
from agents.prediction_agent import PredictionAgent
from agents.future_simulation_agent import FutureSimulationAgent, ScenarioValidationError
from core.future_engine_errors import InsufficientDataError, insufficient_data_detail
from agents.challenge_agent import ChallengeAgent, CHALLENGE_STRATEGIES
from agents.evolve_agent import EvolveAgent
from agents.prevent_agent import PreventAgent
from agents.monitoring_agent import MonitoringAgent
from core.score_methodology import SCORE_METHODOLOGY_MARKER

from auth.dependencies import (
    get_tenant_context,
    get_tenant_context_optional,
    get_platform_context,
    require_permission,
)
from auth.service import get_auth_provider
from core.tenant_context import TenantContext
from tenants.repository import TenantRepository
from tenants.service import (
    QuotaExceededError,
    TenantService,
    assert_within_quota,
)
from models.tenant_schemas import (
    CreateDataSourceRequest,
    CreateGovernmentEntityRequest, UpdateGovernmentEntitySubscriptionRequest,
    CreateIntegrationRequest,
    CreateServiceRequest,
    CreateTenantUserRequest,
    DemoLoginRequest,
    ExternalAgentProfileRequest,
    ImportOpenApiRequest,
    PublishAgentRequest,
    UpdateUserRoleRequest,
    UpdateUserStatusRequest,
)
from fastapi import Depends


app = FastAPI(

    title=(
            "ZERO X-RAY Agentic AI "
        "Service Reengineering Engine"
    ),

    version="1.0.0"
)


app.add_middleware(

    CORSMiddleware,

    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "ZX_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:5174,http://127.0.0.1:5174",
        ).split(",")
        if origin.strip()
    ],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"]
)


orchestrator = None
runtime_store = RuntimeStore()


def _journey_capability_cookie_name(journey_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9]", "", journey_id)
    return f"zx_journey_{safe_id}"


def _customer_journey_or_403(journey_id: str, request: Request, context: TenantContext | None):
    """Authorize staff with existing tenant auth, otherwise require the
    public customer's journey-scoped HttpOnly capability cookie. Public
    customer traffic never needs or derives authority from employee auth.
    """
    if context is not None:
        journey = runtime_store.get_journey(journey_id, tenant_id=context.tenant_id)
    else:
        raw_token = request.cookies.get(_journey_capability_cookie_name(journey_id))
        journey = runtime_store.validate_journey_capability(journey_id, raw_token)
    if not journey:
        raise HTTPException(status_code=403, detail="Journey session is invalid or expired.")
    return journey


def _set_customer_journey_cookie(response: Response, journey_id: str, raw_token: str, expires_at: str):
    # Keep the opaque capability out of URLs, JSON bodies and frontend state.
    # HttpOnly prevents JavaScript from reading it; Path scopes it to exactly
    # one journey's API surface. Secure cookies can be enabled in deployment.
    secure_setting = os.getenv("ZX_SECURE_COOKIES", "").strip().lower()
    if secure_setting:
        secure_cookie = secure_setting in {"1", "true", "yes"}
    else:
        # Vercel -> Render is a cross-site browser request. Modern browsers
        # only send that capability cookie when it is SameSite=None; Secure.
        # Keep local HTTP development on SameSite=Lax.
        allowed_origins = os.getenv("ZX_ALLOWED_ORIGINS", "")
        secure_cookie = any(
            origin.strip().lower().startswith("https://")
            for origin in allowed_origins.split(",")
            if origin.strip()
        )
    expires_dt = datetime.fromisoformat(expires_at)
    max_age = max(1, int((expires_dt - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=_journey_capability_cookie_name(journey_id),
        value=raw_token,
        max_age=max_age,
        expires=expires_dt,
        path=f"/api/journeys/{journey_id}",
        secure=secure_cookie,
        httponly=True,
        samesite="none" if secure_cookie else "lax",
    )
tenant_repository = TenantRepository(database_path=runtime_store.database_path)
tenant_service = TenantService(repository=tenant_repository)
agent_store = AgentStore(database_path=runtime_store.database_path)
catalog_store = CatalogStore(database_path=runtime_store.database_path)
service_store = ServiceStore(database_path=runtime_store.database_path)
integration_execution_validator = IntegrationExecutionValidator(service_store, catalog_store)
# Predict (Step 1 of the Government Future Engine evolution): its own
# additive table, its own store -- see core/prediction_store.py.
prediction_store = PredictionStore(database_path=runtime_store.database_path)
# Future Simulation (Step 2): its own additive table, its own store --
# see core/simulation_store.py.
simulation_store = SimulationStore(database_path=runtime_store.database_path)
# Challenge (Step 3): its own additive table, its own store -- see
# core/challenge_store.py.
challenge_store = ChallengeStore(database_path=runtime_store.database_path)
# Evolve (Step 4): its own additive table, its own store -- see
# core/evolution_store.py.
evolution_store = EvolutionStore(database_path=runtime_store.database_path)
# Prevent (Step 5): its own additive table, its own store -- see
# core/prevention_store.py.
prevention_store = PreventionStore(database_path=runtime_store.database_path)
# Monitoring/Alerts (Step 8): its own additive table, its own store --
# see core/alert_store.py.
alert_store = AlertStore(database_path=runtime_store.database_path)
monitoring_schedule_store = MonitoringScheduleStore(database_path=runtime_store.database_path)
# Agent Comparison Readiness (Phase 8): its own additive table, its own
# store -- see core/comparison_store.py. Holds only the employee-supplied
# external/entity Agent description; ZERO X-RAY's own generated Agent
# profile is always derived fresh from the Blueprint, never stored here.
comparison_store = ComparisonStore(database_path=runtime_store.database_path)
api_operation_store = ApiOperationStore(database_path=runtime_store.database_path)
live_api_executor = LiveApiExecutor(api_operation_store, catalog_store)
notification_provider = get_notification_provider()
monitoring_scheduler = None

# =============================================================
# ROOT-CAUSE FIX: single-flight guard for /api/analyze
# =============================================================
# The reported symptom ("analysis stops at a stage like [4/9] and
# only a full restart un-sticks it") was never actually an infinite
# hang inside one agent -- every individual Ollama call already has
# a bounded timeout (core/llm.py). What made it LOOK infinite is that
# nothing here ever stopped a second /api/analyze call from starting
# a full, independent 9-stage pipeline (with its own Ollama calls)
# while a first one was still mid-flight -- e.g. an impatient retry
# after the on-screen progress bar sat at its ~96% ceiling for a
# while with no feedback, a page refresh, or `--reload` restarting
# the frontend but not an already-slow backend call. A real local
# Ollama instance runs one model inference at a time, so the second
# pipeline's LLM calls silently QUEUE behind the first's instead of
# running concurrently -- both requests then appear to sit at
# whichever stage each was on indefinitely, and nothing ever times
# them out from the caller's side because each individual HTTP call
# to Ollama does eventually get its turn and finish; it is the queue
# itself, growing with every retry, that never converges. Only
# killing the whole backend process actually cleared the queue,
# which is exactly the "needs restart" behavior reported.
#
# Fix: only ever run one analyze pipeline at a time in this process.
# A second, overlapping request is rejected immediately with a clear
# 409 instead of being silently queued behind Ollama -- this is a
# concurrency guard only; it does not change the workflow, remove any
# AI reasoning step, or alter what a single analysis produces.
_analyze_lock = threading.Lock()
_analyze_started_at = None


@app.middleware("http")
async def _single_flight_analyze_guard(request, call_next):
    if request.url.path != "/api/analyze" or request.method != "POST":
        return await call_next(request)

    global _analyze_started_at

    acquired = _analyze_lock.acquire(blocking=False)
    if not acquired:
        waited_for = (
            round(time.monotonic() - _analyze_started_at, 1)
            if _analyze_started_at
            else None
        )

        return JSONResponse(
            status_code=409,
            content={
                "error": (
                    "An analysis is already running in this backend "
                    "process"
                    + (f" (started {waited_for}s ago)" if waited_for else "")
                    + ". Local Ollama processes one request at a time, "
                    "so a second concurrent analysis would only queue "
                    "behind the first and make both look stuck. Wait "
                    "for the current analysis to finish, or check the "
                    "server logs for its current stage, instead of "
                    "retrying or restarting."
                )
            },
        )

    _analyze_started_at = time.monotonic()
    try:
        return await call_next(request)
    finally:
        _analyze_started_at = None
        _analyze_lock.release()


@app.on_event("startup")
def startup():

    global orchestrator

    # Check standards PDF
    standards_text = (
        get_full_standards_text()
    )

    print(
        "Government standards loaded:",
        len(standards_text),
        "characters"
    )

    print(
        "Initializing analysis engine..."
    )

    orchestrator = (
        ServiceOrchestrator(
            standards_text
        )

    )

    print(
        "ZERO X-RAY Agentic Engine ready."
    )

    global monitoring_scheduler
    if monitoring_scheduler is None:
        monitoring_scheduler = MonitoringScheduler(
            monitoring_schedule_store,
            _run_scheduled_monitoring,
            poll_seconds=int(os.getenv("ZX_MONITORING_SCHEDULER_POLL_SECONDS", "60")),
        )
    monitoring_scheduler.start()


@app.on_event("shutdown")
def shutdown():
    if monitoring_scheduler is not None:
        monitoring_scheduler.stop()


@app.get("/")
def root():

    return {
        "name": (
            "ZERO X-RAY Agentic AI Service "
            "Reengineering Engine"
        ),
        "status": "running"
    }


@app.get("/api/health")
def health():

    return {
        "status": "healthy",
        "standards": "loaded",
        "ai": (
            "ready"
            if orchestrator
            else "loading"
        )
    }

@app.get("/api/system/storage-info")
def storage_info(context: TenantContext = Depends(get_tenant_context)):
    """Show the authenticated user where persistent demo data lives."""
    return {
        "data_root": str(get_data_root()),
        "database_path": str(runtime_store.database_path),
        "tenant_files_root": str(get_tenant_files_root()),
    }



# NOTE: the two route groups below (/api/auth/*, /api/platform/*) are
# the Phase 1 multi-tenant foundation layer. Every pre-existing route
# beneath them is untouched and still runs exactly as before -- wiring
# /api/analyze, /api/blueprints/*, and /api/journeys/* through
# get_tenant_context is Phase 2 work, done as its own reviewable step
# so a regression here doesn't also block the single-tenant demo.


@app.get("/api/auth/status")
def auth_status():
    """Non-sensitive authentication connectivity status for deployment checks."""
    return get_auth_provider().public_status()


@app.post("/api/auth/demo-login")
def demo_login(payload: DemoLoginRequest):
    """*** DEMO / DEVELOPMENT AUTHENTICATION ONLY ***
    Not UAE PASS, not production SSO -- see `auth/service.py`. Issues
    an opaque in-process session token for use as
    `Authorization: Bearer <token>` on the tenant-aware routes."""
    try:
        session = get_auth_provider().authenticate(payload.email, payload.credential)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    runtime_store.record_audit(
        session["tenant_id"], session["user_id"], "LOGIN", "user", session["user_id"],
        {"auth_provider": get_auth_provider().provider_name},
    )
    return session


@app.post("/api/auth/logout")
def employee_logout(request: Request):
    """Invalidate the current employee session without changing Logout UX."""
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            # Resolve only to attribute the audit event; never persist/log token.
            session = None
            try:
                session = get_auth_provider().resolve_session(token)
            except ValueError:
                pass
            get_auth_provider().revoke_session(token)
            if session:
                runtime_store.record_audit(
                    session["tenant_id"], session["user_id"], "LOGOUT", "user", session["user_id"]
                )
    return {"status": "logged_out"}


@app.get("/api/me")
def whoami(context: TenantContext = Depends(get_tenant_context)):
    return {
        "user_id": context.user_id,
        "tenant_id": context.tenant_id,
        "role": context.role,
        "tenant_name": context.tenant["name"],
        "tenant_status": context.tenant["status"],
    }


@app.post("/api/platform/entities")
def create_government_entity(
    payload: CreateGovernmentEntityRequest,
    context: TenantContext = Depends(get_platform_context),
):
    require_permission(context, "platform:manage_tenants")
    try:
        result = tenant_service.create_government_entity(
            entity_name=payload.entity_name,
            slug=payload.slug,
            subscription_plan=payload.subscription_plan,
            subscription_start=payload.subscription_start,
            subscription_end=payload.subscription_end,
            admin_name=payload.admin_name,
            admin_email=payload.admin_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result



def _effective_tenant_status(entity):
    if entity.get("status") in {"SUSPENDED", "ARCHIVED", "EXPIRED"}:
        return entity.get("status")
    end = entity.get("subscription_end")
    if end:
        try:
            parsed = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed < datetime.now(timezone.utc):
                return "EXPIRED"
        except ValueError:
            pass
    return entity.get("status")


@app.put("/api/platform/entities/{tenant_id}/subscription")
def update_government_entity_subscription(
    tenant_id: str,
    payload: UpdateGovernmentEntitySubscriptionRequest,
    context: TenantContext = Depends(get_platform_context),
):
    require_permission(context, "platform:manage_tenants")
    tenant = tenant_repository.get_tenant(tenant_id)
    if not tenant or tenant.get("slug") == "default-dev":
        raise HTTPException(status_code=404, detail="Government entity not found.")

    subscription_end = payload.subscription_end
    if payload.extend_days:
        now = datetime.now(timezone.utc)
        base = now
        existing_end = tenant.get("subscription_end")
        if existing_end:
            try:
                parsed = datetime.fromisoformat(str(existing_end).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed > now:
                    base = parsed
            except ValueError:
                pass
        subscription_end = (base + timedelta(days=payload.extend_days)).isoformat()

    try:
        updated = tenant_repository.update_tenant_subscription(
            tenant_id,
            status=payload.status,
            subscription_plan=payload.subscription_plan,
            subscription_start=payload.subscription_start,
            subscription_end=subscription_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime_store.record_audit(
        context.tenant_id, context.user_id, "PLATFORM_TENANT_SUBSCRIPTION_UPDATED",
        "tenant", tenant_id,
        details={
            "target_tenant_id": tenant_id,
            "status": payload.status,
            "subscription_plan": payload.subscription_plan,
            "subscription_start": payload.subscription_start,
            "subscription_end": subscription_end,
            "extend_days": payload.extend_days,
        },
    )
    updated["effective_status"] = _effective_tenant_status(updated)
    return {"tenant": updated}


@app.get("/api/platform/entities")
def list_government_entities(context: TenantContext = Depends(get_platform_context)):
    require_permission(context, "platform:view_metadata")
    entities = [e for e in tenant_repository.list_tenants() if e.get("slug") != "default-dev"]
    # Section 6/22: Platform Admin sees only high-level counts per
    # entity -- never confidential tenant content (no service names,
    # no analysis results, no journey data).
    for entity in entities:
        entity["effective_status"] = _effective_tenant_status(entity)
        users = tenant_repository.list_users_for_tenant(entity["id"])
        services = service_store.list_services_for_tenant(entity["id"])
        agents = agent_store.list_agents_for_tenant(entity["id"])
        entity["counts"] = {
            "users": len(users),
            "services": len(services),
            "analyses": service_store.count_analyses_for_tenant(entity["id"]),
            "agents": len(agents),
            "published_agents": sum(1 for a in agents if a["status"] == "PUBLISHED"),
        }
    return {"entities": entities}


@app.get("/api/platform/stats")
def platform_stats(context: TenantContext = Depends(get_platform_context)):
    """Section 6/22: platform-wide summary counts for the Platform
    Admin dashboard header -- aggregated from the same per-tenant
    counts as /api/platform/entities, never exposing any single
    tenant's confidential content."""
    require_permission(context, "platform:view_metadata")
    entities = [e for e in tenant_repository.list_tenants() if e.get("slug") != "default-dev"]
    status_counts = {}
    total_users = total_services = total_agents = total_published = total_analyses = 0
    for entity in entities:
        effective_status = _effective_tenant_status(entity)
        status_counts[effective_status] = status_counts.get(effective_status, 0) + 1
        total_users += len(tenant_repository.list_users_for_tenant(entity["id"]))
        services = service_store.list_services_for_tenant(entity["id"])
        agents = agent_store.list_agents_for_tenant(entity["id"])
        total_services += len(services)
        total_agents += len(agents)
        total_published += sum(1 for a in agents if a["status"] == "PUBLISHED")
        total_analyses += service_store.count_analyses_for_tenant(entity["id"])
    return {
        "total_entities": len(entities),
        "by_status": status_counts,
        "total_users": total_users,
        "total_services": total_services,
        "total_analyses": total_analyses,
        "total_agents": total_agents,
        "total_published_agents": total_published,
    }


@app.get("/api/users")
def list_tenant_users(context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_users")
    return {"users": tenant_repository.list_users_for_tenant(context.tenant_id)}


@app.post("/api/users")
def create_tenant_user(payload: CreateTenantUserRequest, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_users")
    if payload.role == "platform_admin":
        raise HTTPException(status_code=422, detail="Cannot create a platform_admin from a tenant workspace.")
    existing = tenant_repository.list_users_for_tenant(context.tenant_id)
    try:
        assert_within_quota(context.tenant, len(existing), "max_users", "user")
    except QuotaExceededError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    try:
        user = tenant_repository.create_user(
            tenant_id=context.tenant_id, name=payload.name, email=payload.email, role=payload.role,
        )
        runtime_store.record_audit(context.tenant_id, context.user_id, "USER_CREATED", "user", user["id"], {"role": user["role"]})
        return user
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/users/{user_id}/role")
def change_user_role(user_id: str, payload: UpdateUserRoleRequest, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_users")
    if user_id == context.user_id:
        raise HTTPException(status_code=409, detail="You cannot change your own role from the active session.")
    try:
        user = tenant_repository.update_user_role(user_id, context.tenant_id, payload.role)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    runtime_store.record_audit(context.tenant_id, context.user_id, "ROLE_CHANGED", "user", user_id, {"new_role": user["role"]})
    return user


@app.post("/api/users/{user_id}/status")
def change_user_status(user_id: str, payload: UpdateUserStatusRequest, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_users")
    if user_id == context.user_id:
        raise HTTPException(status_code=409, detail="You cannot suspend or reactivate your own active account.")
    try:
        user = tenant_repository.set_user_status(user_id, context.tenant_id, payload.status)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    runtime_store.record_audit(context.tenant_id, context.user_id, "USER_STATUS_CHANGED", "user", user_id, {"status": user["status"]})
    return user


@app.get("/api/service-assignments")
def list_service_assignments(context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_users")
    assignments = []
    for service in service_store.list_services_for_tenant(context.tenant_id):
        assignments.extend(service_store.list_assignments_for_service(context.tenant_id, service["id"]))
    return {"assignments": assignments}


@app.post("/api/services/{service_id}/assignments/{user_id}")
def assign_service_owner(service_id: str, user_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_users")
    service = service_store.get_service_for_tenant(service_id, context.tenant_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    user = tenant_repository.get_user(user_id)
    if not user or user.get("tenant_id") != context.tenant_id:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.get("role") != "service_owner":
        raise HTTPException(status_code=422, detail="Only service_owner users can be assigned to services.")
    assignment = service_store.assign_user_to_service(context.tenant_id, service_id, user_id)
    runtime_store.record_audit(context.tenant_id, context.user_id, "SERVICE_ASSIGNED", "service", service_id, {"user_id": user_id})
    return assignment


@app.delete("/api/services/{service_id}/assignments/{user_id}")
def unassign_service_owner(service_id: str, user_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_users")
    service = service_store.get_service_for_tenant(service_id, context.tenant_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    user = tenant_repository.get_user(user_id)
    if not user or user.get("tenant_id") != context.tenant_id:
        raise HTTPException(status_code=404, detail="User not found.")
    service_store.unassign_user_from_service(context.tenant_id, service_id, user_id)
    runtime_store.record_audit(context.tenant_id, context.user_id, "SERVICE_UNASSIGNED", "service", service_id, {"user_id": user_id})
    return {"service_id": service_id, "user_id": user_id, "assigned": False}


def _require_service_access(service_id, context):
    """Tenant isolation first, then service-owner assignment scoping.

    Other tenant roles retain their existing tenant-wide visibility. Service
    owners deliberately receive the same 404 for an unassigned service as for
    a non-existent/cross-tenant service, so assignment state cannot be used to
    probe resource existence.
    """
    service = service_store.get_service_for_tenant(service_id, context.tenant_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    if context.role == "service_owner" and not service_store.is_user_assigned_to_service(
        context.tenant_id, service_id, context.user_id
    ):
        raise HTTPException(status_code=404, detail="Service not found.")
    return service


def _require_blueprint_service_access(blueprint, context):
    if context.role == "service_owner":
        service_id = blueprint.get("service_id") if blueprint else None
        if not service_id:
            raise HTTPException(status_code=404, detail="Blueprint not found.")
        _require_service_access(service_id, context)


def _service_owner_data_source_ids(context):
    return set(service_store.list_assigned_data_source_ids(context.tenant_id, context.user_id))


def _validate_service_resources(tenant_id, data_source_ids=None, integration_ids=None, context=None):
    sources = []
    integrations = []
    for source_id in list(dict.fromkeys(data_source_ids or [])):
        source = catalog_store.get_data_source_for_tenant(source_id, tenant_id)
        if not source:
            raise HTTPException(status_code=404, detail="Data source not found.")
        if context is not None and context.role == "service_owner" and source_id not in _service_owner_data_source_ids(context):
            raise HTTPException(status_code=404, detail="Data source not found.")
        sources.append(source)
    for integration_id in list(dict.fromkeys(integration_ids or [])):
        integration = catalog_store.get_integration_for_tenant(integration_id, tenant_id)
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found.")
        integrations.append(integration)
    return sources, integrations


def _organization_context_text(sources, integrations, api_operations=None):
    parts = []
    if sources:
        parts.append("APPROVED ORGANIZATION DATA SOURCES:")
        for source in sources:
            content = str((source.get("configuration") or {}).get("content") or "").strip()
            excerpt = content[:8000]
            line = f"- {source['name']} [{source['type']}; {source['status']}]"
            if excerpt:
                line += f"\n  Content: {excerpt}"
            parts.append(line)
    if integrations:
        parts.append("AVAILABLE EXECUTION TOOLS / INTEGRATIONS:")
        for integration in integrations:
            parts.append(f"- {integration['name']} [{integration['type']}; status={integration['status']}]")
        parts.append("Only CONNECTED integrations may be treated as executable. SANDBOX is demo-only. NOT_CONNECTED means INTEGRATION_REQUIRED; do not invent execution capability.")
    if api_operations:
        parts.append("DISCOVERED OPENAPI OPERATIONS (STRUCTURED, SERVICE-LINKED):")
        for operation in list(api_operations)[:80]:
            operation_id = operation.get("operation_id") or "(no operationId)"
            summary = str(operation.get("summary") or "")[:300]
            parts.append(
                f"- {operation.get('method')} {operation.get('path')} | operationId={operation_id}"
                + (f" | {summary}" if summary else "")
            )
        parts.append("Design automation only around operations listed above or other explicitly configured integrations; never invent an endpoint.")
    return "\n".join(parts)[:50000]


@app.post("/api/services")
def create_service(payload: CreateServiceRequest, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:analyze")
    sources, integrations = _validate_service_resources(
        context.tenant_id, payload.data_source_ids, payload.integration_ids, context=context
    )
    service = service_store.create_service(
        tenant_id=context.tenant_id,
        service_name=payload.service_name,
        description=payload.description,
        language=payload.language,
        source_info=json.dumps({
            "data_source_ids": [item["id"] for item in sources],
            "integration_ids": [item["id"] for item in integrations],
        }, ensure_ascii=False),
        created_by=context.user_id,
    )
    service_store.set_service_connections(
        service["id"], context.tenant_id,
        [item["id"] for item in sources], [item["id"] for item in integrations]
    )
    if context.role == "service_owner":
        service_store.assign_user_to_service(context.tenant_id, service["id"], context.user_id)
    runtime_store.record_audit(context.tenant_id, context.user_id, "SERVICE_CREATED", "service", service["id"], {"data_source_count": len(sources), "integration_count": len(integrations)})
    return service


@app.get("/api/services/{service_id}")
def get_service(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    service = _require_service_access(service_id, context)
    return service


@app.get("/api/services/{service_id}/context")
def get_service_context(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    service = _require_service_access(service_id, context)
    ids = service_store.get_service_connection_ids(service_id, context.tenant_id)
    sources, integrations = _validate_service_resources(
        context.tenant_id, ids["data_source_ids"], ids["integration_ids"], context=context
    )
    connected = sum(1 for item in integrations if item["status"] == "CONNECTED")
    sandbox = sum(1 for item in integrations if item["status"] == "SANDBOX")
    required = sum(1 for item in integrations if item["status"] == "NOT_CONNECTED")
    total = len(integrations)
    readiness = 0 if total == 0 else round(((connected + 0.5 * sandbox) / total) * 100)
    return {
        "service": service,
        "data_sources": sources,
        "integrations": integrations,
        "agent_readiness": readiness,
        "connected_count": connected,
        "sandbox_count": sandbox,
        "integration_required_count": required,
    }


# ---------------------------------------------------------------------
# Phase 8: Agent Comparison Readiness. Reuses the exact same tenant
# context / Service Owner scoping (_require_service_access,
# _require_blueprint_service_access) already enforced everywhere else --
# no parallel authorization layer. No AI call, no scoring, no "winner".
# ---------------------------------------------------------------------

@app.put("/api/services/{service_id}/external-agent-profile")
def upsert_external_agent_profile(
    service_id: str,
    payload: ExternalAgentProfileRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    require_permission(context, "tenant:manage_agents")
    _require_service_access(service_id, context)
    profile = build_external_agent_profile(context.tenant_id, service_id, payload.model_dump())
    saved = comparison_store.upsert_profile(
        context.tenant_id, service_id, profile, created_by=context.user_id
    )
    runtime_store.record_audit(
        context.tenant_id, context.user_id, "EXTERNAL_AGENT_PROFILE_SAVED",
        "service", service_id, {"service_id": service_id},
    )
    return saved


@app.get("/api/services/{service_id}/external-agent-profile")
def get_external_agent_profile(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    _require_service_access(service_id, context)
    saved = comparison_store.get_profile_for_tenant_service(context.tenant_id, service_id)
    if not saved:
        raise HTTPException(status_code=404, detail="No external Agent profile has been saved for this Service.")
    return saved


@app.get("/api/blueprints/{blueprint_id}/comparison")
def get_agent_comparison(blueprint_id: str, context: TenantContext = Depends(get_tenant_context)):
    """Comparison-readiness response: ZERO X-RAY's own generated Agent
    (derived fresh from this Blueprint, never a second AI call) next to
    whatever external/entity Agent profile the tenant has saved for the
    same Service -- purely descriptive, side by side. No score, no
    ranking, no "winner"."""
    require_permission(context, "tenant:read")
    blueprint = runtime_store.get_blueprint_for_tenant(blueprint_id, context.tenant_id)
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    _require_blueprint_service_access(blueprint, context)

    service_id = blueprint.get("service_id")
    zero_xray_profile = build_zero_xray_comparison_profile(context.tenant_id, service_id, blueprint)

    entity_profile = None
    if service_id:
        saved = comparison_store.get_profile_for_tenant_service(context.tenant_id, service_id)
        if saved:
            entity_profile = saved["profile"]

    return build_comparison_readiness(zero_xray_profile, entity_profile)


@app.post("/api/analyze")
def analyze_service(
    service: ServiceInput,
    context: TenantContext = Depends(get_tenant_context),
):
    require_permission(context, "tenant:analyze")

    # TEMPORARY DIAGNOSTIC (language debug trace) -- confirms the exact
    # `lang` value received in the request and after Pydantic validation,
    # at the single entry point every analyze call goes through.
    print(f"[LANG DEBUG] request=lang:{service.lang!r}")
    print(f"[LANG DEBUG] service=lang:{service.lang!r} service_name:{service.service_name!r}")

    if orchestrator is None:

        return {
            "error":
                translate_error(
                    "AI engine is not ready.",
                    service.lang,
                )
        }

    # ROOT-CAUSE FIX (Mandatory AI Mode -- requirements 1/2/6): Analyze
    # is the one operation whose CORE value (semantic step extraction,
    # journey design, standards/gap reasoning) is genuinely AI-
    # dependent, not merely AI-narrated -- unlike Predict/Simulate/
    # Challenge/Evolve/Prevent, whose scoring/severity/evidence stay
    # fully deterministic in Python regardless of Ollama (see each of
    # those agents' own docstrings) and are therefore left untouched
    # here. REQUIRE_OLLAMA defaults to True (Mandatory AI Mode is the
    # default). Checked BEFORE any other work -- resource validation,
    # service lookups, the pipeline itself -- so an unreachable Ollama
    # or a missing configured model stops this request immediately
    # with a clear, structured AI_ENGINE_UNAVAILABLE error instead of
    # quietly completing on every agent's deterministic fallback and
    # reporting that as a successful AI analysis. check_available()
    # uses the centralized, cached check (core/llm.py) -- a single,
    # non-retrying, short-timeout request, never a retry loop.
    if REQUIRE_OLLAMA:
        available, reason = orchestrator.llm.check_available()
        if not available:
            raise HTTPException(
                status_code=503,
                detail=f"AI_ENGINE_UNAVAILABLE: {reason}",
            )
        orchestrator.llm.reset_run_failure_tracking()

    service_payload = service.model_dump()
    selected_sources = []
    selected_integrations = []
    if service.service_id:
        existing_service = _require_service_access(service.service_id, context)
        existing_ids = service_store.get_service_connection_ids(service.service_id, context.tenant_id)
        selected_sources, selected_integrations = _validate_service_resources(
            context.tenant_id,
            service.data_source_ids or existing_ids["data_source_ids"],
            service.integration_ids or existing_ids["integration_ids"],
            context=context,
        )
        service_store.set_service_connections(
            service.service_id, context.tenant_id,
            [item["id"] for item in selected_sources],
            [item["id"] for item in selected_integrations],
        )
    else:
        selected_sources, selected_integrations = _validate_service_resources(
            context.tenant_id, service.data_source_ids, service.integration_ids, context=context
        )

    selected_integration_ids = [item["id"] for item in selected_integrations]
    structured_operations = (
        api_operation_store.list_operations_for_integrations(
            context.tenant_id, selected_integration_ids, service_id=service.service_id
        )
        if service.service_id else []
    )
    org_context = _organization_context_text(selected_sources, selected_integrations, structured_operations)
    if org_context:
        # ROOT-CAUSE FIX (OpenAPI contamination -- generic, applies to
        # every Service and every imported specification):
        #
        # This block used to CONCATENATE the whole organization context
        # (data-source content, integration list, and every discovered
        # OpenAPI operation with its summary/description) onto
        # `service_payload["description"]`. `description` is not a free
        # text bag -- it is the field that describes THE CUSTOMER'S OWN
        # CURRENT JOURNEY, and several downstream consumers read it as
        # exactly that:
        #
        #   * agents/service_agent.py `_extract_semantic_steps()` passes
        #     it to the model as "Description:" while asking it to
        #     identify the real semantic steps -- so API operation
        #     summaries ("Get available boxes", "Update payment") read
        #     as extra journey steps. This is precisely the observed
        #     7 semantic steps before import -> 8 after import.
        #   * core/pricing_catalog.py `_text()` regex-scans it for a
        #     fixed fee, so any "price"/"fee"/"amount" wording inside an
        #     imported operation description manufactured a pricing step
        #     for a service that has no such fee.
        #   * agents/service_agent.py `_detect_capabilities()` and
        #     core/service_classifier.py classify the service from it.
        #
        # None of those are supposed to see integration metadata. The
        # context is genuinely useful, but only as EVIDENCE about which
        # systems/operations already exist -- never as journey text. It
        # now travels in its own dedicated field, which the journey
        # designer reads explicitly (see
        # agents/journey_builder_agent.py) and every current-journey
        # consumer correctly ignores. Nothing about what is discovered
        # or stored changes; only where it is allowed to be read from.
        service_payload["organization_context"] = org_context
        service_payload["dependencies"] = list(service_payload.get("dependencies") or []) + [
            f"{item['name']} ({item['type']}) - {item['status']}" for item in selected_integrations
        ]

    result = orchestrator.analyze(service_payload)

    # Production quality gate for Groq: the cloud-free-tier workflow
    # intentionally reserves AI inference for Journey Builder while the
    # other eight logical agents run their existing deterministic,
    # evidence-grounded rules. Therefore the redesigned journey itself
    # MUST be AI-produced and sufficiently complete before anything is
    # translated, persisted, or exposed to Build Agent. A template
    # fallback remains an internal safety net, but it must never be saved
    # or displayed as if it were a successful AI analysis.
    if ZX_LLM_MODE == "groq":
        redesign = result.get("redesign") if isinstance(result, dict) else None
        future_steps = (redesign or {}).get("future_steps") or []
        journey_source = str((redesign or {}).get("analysis_source", "")).lower()
        current_steps = (result.get("service") or {}).get("steps") or service_payload.get("steps") or []
        minimum_future_steps = 3 if len(current_steps) >= 5 else 2
        quality_issues = []
        if journey_source != ai_label():
            quality_issues.append(
                f"Journey Builder source is {journey_source or 'missing'}, not AI."
            )
        if not isinstance(future_steps, list) or len(future_steps) < minimum_future_steps:
            quality_issues.append(
                f"Future journey has {len(future_steps) if isinstance(future_steps, list) else 0} "
                f"step(s); at least {minimum_future_steps} are required for this service."
            )
        if quality_issues:
            print("[ANALYSIS QUALITY GATE] Rejected incomplete Groq analysis: " + " ".join(quality_issues))
            raise HTTPException(
                status_code=503,
                detail=(
                    "AI_ANALYSIS_INCOMPLETE: The AI journey did not pass the "
                    "quality gate and was NOT saved. Please retry after the "
                    "Groq rate-limit window clears. " + " ".join(quality_issues)
                ),
            )

    # `organization_context` is pipeline-internal EVIDENCE only (see the
    # contamination fix above). It must not be persisted into the
    # Blueprint or echoed back to the client: it can carry Data Source
    # content, and the frontend re-submits `result.service` verbatim on a
    # language switch, which would otherwise grow the payload on every
    # re-analysis. The operations themselves stay available through their
    # own endpoint (GET /api/integrations/{id}/openapi/operations) and
    # through `agent_capability_map`, both unchanged.
    if isinstance(result.get("service"), dict):
        result["service"].pop("organization_context", None)

    # ROOT-CAUSE FIX (requirement 4 -- "abort cleanly... do not save an
    # incomplete operation as successful"): Ollama was reachable at the
    # preflight check above but may still have gone down PARTWAY
    # through the 9-stage pipeline (crashed, network dropped, etc.).
    # had_connectivity_failure_this_run is set by core/llm.py's
    # generate() only on a genuine connectivity-level failure -- never
    # on a parse/empty-content model-quality issue, which keeps using
    # its existing, unchanged, honestly-labeled deterministic fallback
    # (requirement 5). Checked BEFORE translate_result/save_blueprint/
    # create_analysis, so a run that lost Ollama mid-flight is
    # discarded here, never persisted and never returned as if it were
    # a complete/successful analysis.
    if REQUIRE_OLLAMA and orchestrator.llm.had_connectivity_failure_this_run:
        raise HTTPException(
            status_code=503,
            detail=(
                "AI_ENGINE_UNAVAILABLE: Ollama became unreachable during "
                "analysis. The incomplete analysis was discarded rather "
                "than saved -- retry once Ollama is reachable again."
            ),
        )

    # The rule-based agents author their fallback / baseline text in
    # English regardless of the language the service was typed in.
    # translate_result swaps those known phrases for their Arabic
    # translation when the frontend asked for lang="ar" (driven by
    # the UI language switch), and is a no-op otherwise.
    result = translate_result(
        result,
        service.lang,
    )

    # PHASE 2 (Build Agent grounding): attach an additive, read-only
    # capability map derived ONLY from this Service's own linked Data
    # Sources/Integrations (selected_sources/selected_integrations were
    # already tenant- and Service-Owner-scoped above by
    # _validate_service_resources) and the already-computed
    # redesign.future_steps. Never mutates future_steps/required_integrations
    # or any other existing field; excluded from the public Agent payload by
    # agent_store.py's existing allowlist. service_id is filled in below once
    # it is resolved.
    result["agent_capability_map"] = build_agent_capability_map(
        service_id=service.service_id,
        data_sources=selected_sources,
        integrations=selected_integrations,
        future_steps=(result.get("redesign") or {}).get("future_steps"),
        api_operations=structured_operations,
        service_context=" ".join(filter(None, [service.service_name, service.description])),
    )

    blueprint = runtime_store.save_blueprint(
        result.get("service", service.model_dump()),
        result,
        tenant_id=context.tenant_id,
    )

    # Section 4: give this Blueprint a real Service/Analysis lineage.
    # A brand-new Blueprint (no blueprint_id in the request) means a
    # new Service; re-analyzing an existing Blueprint keeps its
    # original Service and just records a new Analysis (a Service can
    # have a history of analyses over time). Never touches the engine
    # itself -- `blueprint["analysis"]` is still the single working
    # copy the pipeline reads/writes.
    if service.service_id:
        service_id = service.service_id
    elif service.blueprint_id and blueprint.get("service_id"):
        service_id = blueprint["service_id"]
    else:
        service_record = service_store.create_service(
            tenant_id=context.tenant_id,
            service_name=blueprint["service_name"],
            description=service.description,
            language=service.lang,
            created_by=context.user_id,
        )
        service_id = service_record["id"]
        if context.role == "service_owner":
            service_store.assign_user_to_service(context.tenant_id, service_id, context.user_id)
        service_store.set_service_connections(
            service_id, context.tenant_id,
            [item["id"] for item in selected_sources],
            [item["id"] for item in selected_integrations],
        )
    analysis_record = service_store.create_analysis(
        tenant_id=context.tenant_id,
        service_id=service_id,
        blueprint_id=blueprint["id"],
        created_by=context.user_id,
        status="COMPLETED",
        result=result,
    )
    runtime_store.link_blueprint_to_service_analysis(
        blueprint["id"], context.tenant_id, service_id, analysis_record["id"]
    )

    result["blueprint_id"] = blueprint["id"]
    result["blueprint_status"] = blueprint["status"]
    result["service_id"] = service_id
    result["analysis_id"] = analysis_record["id"]
    result["agent_capability_map"]["service_id"] = service_id
    runtime_store.record_audit(context.tenant_id, context.user_id, "ANALYSIS_EXECUTED", "analysis", analysis_record["id"], {"service_id": service_id, "blueprint_id": blueprint["id"]})

    # TEMPORARY DIAGNOSTIC (language debug trace) -- the exact journey
    # content about to be returned in THIS response, so it's directly
    # comparable to what the request asked for above.
    _future_steps_debug = result.get("redesign", {}).get("future_steps", [])
    print(f"[LANG DEBUG] journey=lang:{service.lang!r} steps:{len(_future_steps_debug)}")
    print(f"[LANG DEBUG] source={_future_steps_debug[0].get('analysis_source') if _future_steps_debug else None!r}")
    print(f"[LANG DEBUG] first_step={_future_steps_debug[0].get('name') if _future_steps_debug else None!r}")

    return result


@app.get("/api/blueprints/{blueprint_id}")
def get_blueprint(blueprint_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    blueprint = runtime_store.get_blueprint_for_tenant(blueprint_id, context.tenant_id)
    if not blueprint:
        # Deliberately 404, not 403: confirming a Blueprint UUID exists
        # under another tenant is itself an information leak (Section 29).
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    _require_blueprint_service_access(blueprint, context)
    return blueprint


@app.post("/api/blueprints/{blueprint_id}/approve")
def approve_blueprint(blueprint_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:publish")
    current = runtime_store.get_blueprint_for_tenant(blueprint_id, context.tenant_id)
    if not current:
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    _require_blueprint_service_access(current, context)
    blueprint = runtime_store.set_blueprint_status(blueprint_id, "APPROVED", tenant_id=context.tenant_id)
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    runtime_store.record_audit(context.tenant_id, context.user_id, "BLUEPRINT_APPROVED", "blueprint", blueprint_id, {"service_id": blueprint.get("service_id")})
    return blueprint


@app.post("/api/blueprints/{blueprint_id}/publish")
def publish_blueprint(blueprint_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:publish")
    current = runtime_store.get_blueprint_for_tenant(blueprint_id, context.tenant_id)
    if not current:
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    _require_blueprint_service_access(current, context)
    try:
        blueprint = runtime_store.set_blueprint_status(blueprint_id, "PUBLISHED", tenant_id=context.tenant_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    return blueprint


@app.get("/api/services")
def list_services(context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    services = (
        service_store.list_services_for_user(context.tenant_id, context.user_id)
        if context.role == "service_owner"
        else service_store.list_services_for_tenant(context.tenant_id)
    )
    return {"services": services}


@app.get("/api/services/{service_id}/analyses")
def list_service_analyses(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    _require_service_access(service_id, context)
    return {"analyses": service_store.list_analyses_for_service(service_id, context.tenant_id)}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    analysis = service_store.get_analysis_for_tenant(analysis_id, context.tenant_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    if context.role == "service_owner":
        _require_service_access(analysis["service_id"], context)
    return analysis


@app.post("/api/services/{service_id}/predict")
def predict_service(service_id: str, lang: str = "en", context: TenantContext = Depends(get_tenant_context)):
    """Predict (Step 1 of the Government Future Engine evolution):
    isolated, read-only over a service's own stored analysis/journey
    history. Does NOT call agents/orchestrator.py, does NOT touch
    /api/analyze's flow, and does NOT write to any existing table --
    see core/prediction_agent.py / core/prediction_store.py for the
    determinism guarantees (confidence, occurrence counts and
    data_sufficiency are computed here in Python, never by the LLM)."""
    require_permission(context, "future:predict")
    _require_service_access(service_id, context)

    llm = orchestrator.llm if orchestrator is not None else None
    agent = PredictionAgent(llm=llm, lang=lang)
    prediction_input = agent.gather_input(
        service_id=service_id,
        tenant_id=context.tenant_id,
        service_store=service_store,
        database_path=runtime_store.database_path,
    )
    result = agent.run(prediction_input)

    saved = prediction_store.save_prediction(
        tenant_id=context.tenant_id,
        service_id=service_id,
        input_snapshot=prediction_input,
        result=result,
        data_sufficiency=result["data_sufficiency"]["verdict"],
        created_by=context.user_id,
    )

    runtime_store.record_audit(context.tenant_id, context.user_id, "FUTURE_PREDICT_EXECUTED", "prediction", saved["id"], {"service_id": service_id})
    return {"prediction_id": saved["id"], **result}


@app.post("/api/services/{service_id}/scenarios")
def create_scenario(
    service_id: str,
    request: ScenarioCreateRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    """Future Simulation (Step 2 of the Government Future Engine
    evolution): isolated, deterministic scenario execution over a
    service's own stored future_steps/required_integrations graph.
    Does NOT call agents/orchestrator.py, agents/simulation_agent.py,
    or graph/workflow.py, and does NOT write to any existing table --
    see agents/future_simulation_agent.py for the determinism
    guarantees (affected steps, bottlenecks, scores and likelihood
    are all computed here in Python, never by the LLM).

    ROOT-CAUSE FIX (Section 2 audit -- "Run Simulation" 400s / manual
    scenario treated as required): trigger_type=MANUAL with no
    scenario_type, and trigger_type=PREDICTION with no prediction_id,
    used to 400 immediately below -- exactly what happens when a
    caller clicks "Run Simulation" with nothing filled in. Both cases
    now fall through to the SAME AUTO generation path as an explicit
    trigger_type="AUTO" request (Section 2's real requirement: a
    missing/omitted prediction is optional enrichment, never a hard
    requirement). trigger_type=MANUAL WITH a scenario_type, and
    trigger_type=PREDICTION WITH a prediction_id, are both completely
    UNCHANGED -- same validation, same 404s, same single-scenario
    response shape."""
    require_permission(context, "future:simulate")
    _require_service_access(service_id, context)

    linked_prediction = None
    trigger_reference_id = None
    if request.trigger_type == "PREDICTION" and request.prediction_id:
        stored_prediction = prediction_store.get_prediction_for_tenant(
            request.prediction_id, context.tenant_id
        )
        if not stored_prediction or stored_prediction.get("service_id") != service_id:
            raise HTTPException(status_code=404, detail="Prediction not found.")
        linked_prediction = stored_prediction["result"]
        trigger_reference_id = request.prediction_id

    llm = orchestrator.llm if orchestrator is not None else None
    agent = FutureSimulationAgent(llm=llm, lang=request.lang)
    service_graph = agent.build_service_graph(
        service_id=service_id,
        tenant_id=context.tenant_id,
        service_store=service_store,
        database_path=runtime_store.database_path,
    )

    requested_scenario_type = request.scenario_type
    requested_variables = request.variables

    # A request only ever resolves to AUTO when it gave this endpoint
    # nothing concrete to act on: no manual scenario_type, and (for
    # PREDICTION) no prediction_id. MANUAL+scenario_type and
    # PREDICTION+prediction_id never reach here -- see the docstring.
    resolved_as_auto = (
        request.trigger_type == "AUTO"
        or (request.trigger_type == "MANUAL" and not requested_scenario_type)
        or (request.trigger_type == "PREDICTION" and not request.prediction_id)
    )

    if resolved_as_auto:
        if not service_graph["steps"] and not service_graph["integrations"]:
            raise HTTPException(
                status_code=400,
                detail=insufficient_data_detail(
                    reason=(
                        "This service has no stored future_steps or "
                        "required_integrations yet, so Simulate has "
                        "nothing to build a scenario graph from."
                    ),
                    missing_requirement="a completed analysis (future_steps/required_integrations)",
                    next_action="Run /api/analyze for this service, then retry.",
                ),
            )

        auto_candidates = agent.generate_auto_scenarios(service_graph)
        auto_scenarios = []
        for category, scenario_type, variables in auto_candidates:
            validated_variables = agent.validate_scenario(scenario_type, variables, service_graph)
            result = agent.run(
                scenario_type, validated_variables, service_graph,
                linked_prediction=linked_prediction,
            )
            scenario_definition = {
                "scenario_type": scenario_type,
                "trigger_type": "AUTO",
                "auto_category": category,
                "trigger_reference_id": trigger_reference_id,
                "variables": validated_variables,
                "service_graph_source_analysis_id": service_graph.get("source_analysis_id"),
            }
            saved = simulation_store.save_scenario(
                tenant_id=context.tenant_id,
                service_id=service_id,
                scenario_type=scenario_type,
                trigger_type="AUTO",
                trigger_reference_id=trigger_reference_id,
                scenario=scenario_definition,
                result=result,
                created_by=context.user_id,
            )
            auto_scenarios.append({
                "scenario_id": saved["id"],
                "service_id": service_id,
                "scenario": scenario_definition,
                **result,
            })

        # Backward-compatible top-level shape: the first generated
        # scenario (STEP_FAILURE when relevant, else generate_auto_
        # scenarios' own fixed priority order) is also surfaced at the
        # top level exactly like the single-scenario response every
        # other trigger_type has always returned, so a caller reading
        # only scenario_id/scenario/affected_steps/etc. still gets a
        # real, usable result. `auto_scenarios` is purely additive.
        primary = auto_scenarios[0]
        runtime_store.record_audit(context.tenant_id, context.user_id, "FUTURE_SIMULATE_EXECUTED", "scenario", primary["scenario_id"], {"service_id": service_id, "trigger_type": "AUTO", "scenario_count": len(auto_scenarios)})
        return {**primary, "auto_scenarios": auto_scenarios}

    # ---- everything below this line is the pre-existing, UNCHANGED
    # ---- MANUAL(+scenario_type) / PREDICTION(+prediction_id) path.

    # Fix (Step 3 audit): the originally specified Predict -> Simulate
    # linkage. Auto-derive scenario_type/variables from the linked
    # prediction ONLY when the caller didn't explicitly supply them --
    # an explicit caller-supplied scenario_type/variables under
    # trigger_type=PREDICTION is still honored exactly as before, so
    # this is purely additive and fully backward compatible.
    if request.trigger_type == "PREDICTION" and not requested_scenario_type:
        try:
            requested_scenario_type, requested_variables, _ = agent.derive_scenario_from_prediction(
                linked_prediction, service_graph
            )
        except ScenarioValidationError as error:
            raise HTTPException(status_code=400, detail=str(error))

    try:
        validated_variables = agent.validate_scenario(
            requested_scenario_type, requested_variables, service_graph
        )
    except InsufficientDataError as error:
        raise HTTPException(status_code=400, detail=error.to_detail())
    except ScenarioValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))

    result = agent.run(
        requested_scenario_type, validated_variables, service_graph,
        linked_prediction=linked_prediction,
    )

    scenario_definition = {
        "scenario_type": requested_scenario_type,
        "trigger_type": request.trigger_type,
        "trigger_reference_id": trigger_reference_id,
        "variables": validated_variables,
        "service_graph_source_analysis_id": service_graph.get("source_analysis_id"),
    }

    saved = simulation_store.save_scenario(
        tenant_id=context.tenant_id,
        service_id=service_id,
        scenario_type=requested_scenario_type,
        trigger_type=request.trigger_type,
        trigger_reference_id=trigger_reference_id,
        scenario=scenario_definition,
        result=result,
        created_by=context.user_id,
    )

    runtime_store.record_audit(context.tenant_id, context.user_id, "FUTURE_SIMULATE_EXECUTED", "scenario", saved["id"], {"service_id": service_id, "trigger_type": request.trigger_type})
    return {
        "scenario_id": saved["id"],
        "service_id": service_id,
        "scenario": scenario_definition,
        **result,
    }


@app.get("/api/services/{service_id}/scenarios")
def list_scenarios(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    _require_service_access(service_id, context)
    return {"scenarios": simulation_store.list_scenarios_for_service(service_id, context.tenant_id)}


@app.post("/api/services/{service_id}/challenges")
def create_challenge(
    service_id: str,
    request: ChallengeCreateRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    """Challenge (Step 3 of the Government Future Engine evolution):
    generates a fixed, closed set of deterministic stress cases and
    executes every one of them through the EXISTING, unmodified
    FutureSimulationAgent -- this endpoint creates no new simulation
    logic. Does NOT call agents/orchestrator.py, graph/workflow.py,
    or modify Predict/Simulate's own stored data. See
    agents/challenge_agent.py for the determinism guarantees (case
    generation, vulnerability derivation, severity and ranking are
    all fixed deterministic rules, never LLM-decided)."""
    require_permission(context, "future:challenge")
    _require_service_access(service_id, context)

    linked_prediction = None
    if request.prediction_id:
        stored_prediction = prediction_store.get_prediction_for_tenant(
            request.prediction_id, context.tenant_id
        )
        if not stored_prediction or stored_prediction.get("service_id") != service_id:
            raise HTTPException(status_code=404, detail="Prediction not found.")
        linked_prediction = stored_prediction["result"]

    llm = orchestrator.llm if orchestrator is not None else None
    simulation_agent = FutureSimulationAgent(llm=llm, lang=request.lang)
    service_graph = simulation_agent.build_service_graph(
        service_id=service_id,
        tenant_id=context.tenant_id,
        service_store=service_store,
        database_path=runtime_store.database_path,
    )
    if not service_graph["steps"] and not service_graph["integrations"]:
        raise HTTPException(
            status_code=400,
            detail=insufficient_data_detail(
                reason=(
                    "This service has no stored future_steps or "
                    "required_integrations yet, so Challenge has "
                    "nothing to build stress cases from."
                ),
                missing_requirement="a completed analysis (future_steps/required_integrations)",
                next_action="Run /api/analyze for this service, then retry.",
            ),
        )

    challenge_agent = ChallengeAgent(future_simulation_agent=simulation_agent, llm=llm, lang=request.lang)
    try:
        result = challenge_agent.run(
            request.strategies, service_graph, linked_prediction=linked_prediction
        )
    except InsufficientDataError as error:
        raise HTTPException(status_code=400, detail=error.to_detail())
    except ScenarioValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))

    input_snapshot = {
        "strategies": request.strategies or sorted(CHALLENGE_STRATEGIES),
        "prediction_id": request.prediction_id,
        "service_graph_source_analysis_id": service_graph.get("source_analysis_id"),
    }

    saved = challenge_store.save_challenge(
        tenant_id=context.tenant_id,
        service_id=service_id,
        input_snapshot=input_snapshot,
        result=result,
        created_by=context.user_id,
    )

    runtime_store.record_audit(context.tenant_id, context.user_id, "FUTURE_CHALLENGE_EXECUTED", "challenge", saved["id"], {"service_id": service_id})
    return {"challenge_id": saved["id"], "service_id": service_id, **result}


@app.get("/api/services/{service_id}/challenges")
def list_challenges(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    _require_service_access(service_id, context)
    return {"challenges": challenge_store.list_challenges_for_service(service_id, context.tenant_id)}


@app.post("/api/services/{service_id}/evolutions")
def create_evolution(
    service_id: str,
    request: EvolveCreateRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    """Evolve (Step 4 of the Government Future Engine evolution):
    reads a stored Challenge output (Step 3, read-only, unmodified)
    and proposes structural fixes for its vulnerabilities from a
    closed, deterministic set of 5 evolution types. Does NOT call
    agents/orchestrator.py, graph/workflow.py, or re-run Challenge/
    Simulate, and does NOT write to any existing table -- see
    agents/evolve_agent.py for the determinism guarantees (which
    evolution_type applies, exposure_before/after, and protection
    status are all computed here in Python, never by the LLM)."""
    require_permission(context, "future:evolve")
    _require_service_access(service_id, context)

    stored_challenge = challenge_store.get_challenge_for_tenant(
        request.challenge_id, context.tenant_id
    )
    if not stored_challenge or stored_challenge.get("service_id") != service_id:
        raise HTTPException(status_code=404, detail="Challenge not found.")

    llm = orchestrator.llm if orchestrator is not None else None
    simulation_agent = FutureSimulationAgent(llm=llm, lang=request.lang)
    service_graph = simulation_agent.build_service_graph(
        service_id=service_id,
        tenant_id=context.tenant_id,
        service_store=service_store,
        database_path=runtime_store.database_path,
    )

    evolve_agent = EvolveAgent(llm=llm, lang=request.lang)
    result = evolve_agent.run(
        stored_challenge["result"], service_graph, challenge_id=request.challenge_id
    )

    input_snapshot = {
        "challenge_id": request.challenge_id,
        "service_graph_source_analysis_id": service_graph.get("source_analysis_id"),
    }

    saved = evolution_store.save_evolution(
        tenant_id=context.tenant_id,
        service_id=service_id,
        challenge_id=request.challenge_id,
        input_snapshot=input_snapshot,
        result=result,
        created_by=context.user_id,
    )

    runtime_store.record_audit(context.tenant_id, context.user_id, "FUTURE_EVOLVE_EXECUTED", "evolution", saved["id"], {"service_id": service_id})
    return {"evolution_id": saved["id"], "service_id": service_id, **result}


@app.get("/api/services/{service_id}/evolutions")
def list_evolutions(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    _require_service_access(service_id, context)
    return {"evolutions": evolution_store.list_evolutions_for_service(service_id, context.tenant_id)}


@app.post("/api/services/{service_id}/preventions")
def create_prevention(
    service_id: str,
    request: PreventCreateRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    """Prevent (Step 5 of the Government Future Engine evolution):
    reads a stored Evolve output (Step 4, read-only, unmodified) and
    DEFINES deterministic prevention triggers for each proposal. Does
    NOT call agents/orchestrator.py, graph/workflow.py, or re-run
    Evolve/Challenge/Simulate/Predict, and does NOT schedule, monitor,
    or execute anything -- every trigger's `status` is always the
    fixed constant "DEFINED". See agents/prevent_agent.py for the
    determinism guarantees (trigger generation and thresholds are
    computed here in Python, never by the LLM)."""
    require_permission(context, "future:prevent")
    _require_service_access(service_id, context)

    stored_evolution = evolution_store.get_evolution_for_tenant(
        request.evolution_id, context.tenant_id
    )
    if not stored_evolution or stored_evolution.get("service_id") != service_id:
        raise HTTPException(status_code=404, detail="Evolution not found.")

    llm = orchestrator.llm if orchestrator is not None else None
    prevent_agent = PreventAgent(llm=llm, lang=request.lang)
    result = prevent_agent.run(stored_evolution["result"], evolution_id=request.evolution_id)

    input_snapshot = {"evolution_id": request.evolution_id}

    saved = prevention_store.save_prevention(
        tenant_id=context.tenant_id,
        service_id=service_id,
        evolution_id=request.evolution_id,
        input_snapshot=input_snapshot,
        result=result,
        created_by=context.user_id,
    )

    runtime_store.record_audit(context.tenant_id, context.user_id, "FUTURE_PREVENT_EXECUTED", "prevention", saved["id"], {"service_id": service_id})
    return {"prevention_id": saved["id"], "service_id": service_id, **result}


@app.get("/api/services/{service_id}/preventions")
def list_preventions(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    _require_service_access(service_id, context)
    return {"preventions": prevention_store.list_preventions_for_service(service_id, context.tenant_id)}


def _execute_monitoring_check(service_id: str, tenant_id: str, prevention_id: str, actor_user_id=None, lang="en"):
    """Single implementation used by both manual and scheduled monitoring."""
    stored_prevention = prevention_store.get_prevention_for_tenant(prevention_id, tenant_id)
    if not stored_prevention or stored_prevention.get("service_id") != service_id:
        raise HTTPException(status_code=404, detail="Prevention not found.")

    outcome = MonitoringAgent(lang=lang).run(
        stored_prevention["result"], service_id, tenant_id,
        prediction_store, challenge_store,
    )

    checks = []
    for check in outcome["checks"]:
        trigger_id = check["trigger_id"]
        open_alert = alert_store.get_open_alert(tenant_id, service_id, trigger_id)

        if check["breached"]:
            if open_alert is None:
                alert = alert_store.create_alert(
                    tenant_id=tenant_id, service_id=service_id,
                    prevention_id=stored_prevention["id"], trigger_id=trigger_id,
                    current_value=check["current_value"], threshold_value=check["threshold_value"],
                    checked_against=check["checked_against"], evidence=check["evidence"],
                )
                notification_provider.notify_alert(alert)
                alert_action = "CREATED"
            else:
                alert = open_alert
                alert_action = "ALREADY_OPEN"
        else:
            if open_alert is not None:
                alert = alert_store.resolve_alert(
                    open_alert["id"], tenant_id,
                    current_value=check["current_value"],
                    checked_against=check["checked_against"], evidence=check["evidence"],
                )
                alert_action = "RESOLVED"
            else:
                alert = None
                alert_action = "NO_ALERT"

        checks.append({**check, "alert_action": alert_action, "alert": alert})

    runtime_store.record_audit(
        tenant_id, actor_user_id, "FUTURE_MONITORING_CHECK_EXECUTED",
        "prevention", stored_prevention["id"],
        {"service_id": service_id, "checks": len(checks)},
    )
    return {
        "prevention_id": stored_prevention["id"],
        "service_id": service_id,
        "generated_at": outcome["generated_at"],
        "checks": checks,
        "score_methodology": SCORE_METHODOLOGY_MARKER,
    }


def _run_scheduled_monitoring(schedule):
    """Run the latest stored prevention for a due service, if one exists."""
    preventions = prevention_store.list_preventions_for_service(
        schedule["service_id"], schedule["tenant_id"]
    )
    if not preventions:
        return None
    return _execute_monitoring_check(
        schedule["service_id"], schedule["tenant_id"], preventions[0]["id"], actor_user_id=None
    )


@app.post("/api/services/{service_id}/monitoring-checks")
def create_monitoring_check(
    service_id: str,
    request: MonitoringCheckRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    """Existing on-demand Monitoring Check. Scheduled monitoring is optional and separate."""
    require_permission(context, "future:monitor")
    _require_service_access(service_id, context)
    return _execute_monitoring_check(
        service_id, context.tenant_id, request.prevention_id, actor_user_id=context.user_id, lang=request.lang
    )


@app.get("/api/services/{service_id}/monitoring-schedule")
def get_monitoring_schedule(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "future:monitor")
    _require_service_access(service_id, context)
    schedule = monitoring_schedule_store.get_for_service(context.tenant_id, service_id)
    return {
        "schedule": schedule or {"enabled": False, "frequency": "daily", "last_run_at": None, "next_run_at": None},
        "notifications": notification_provider.public_status(),
    }


@app.put("/api/services/{service_id}/monitoring-schedule")
def update_monitoring_schedule(
    service_id: str,
    request: MonitoringScheduleUpdateRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    require_permission(context, "future:monitor")
    _require_service_access(service_id, context)
    schedule = monitoring_schedule_store.upsert(
        context.tenant_id, service_id, request.enabled, request.frequency, context.user_id
    )
    runtime_store.record_audit(
        context.tenant_id, context.user_id, "MONITORING_SCHEDULE_UPDATED",
        "service", service_id,
        {"enabled": request.enabled, "frequency": request.frequency},
    )
    return {"schedule": schedule, "notifications": notification_provider.public_status()}


@app.get("/api/notifications/status")
def notification_status(context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    return notification_provider.public_status()


@app.get("/api/services/{service_id}/alerts")
def list_alerts(service_id: str, context: TenantContext = Depends(get_tenant_context)):
    """Stored Alerts (Monitoring/Alerts capability). Read-only --
    ROOT-CAUSE FIX (Stored Alerts presentation audit): this used to
    return every alert this service has ever had, most-recent-first,
    with no way to tell an alert from the CURRENT Challenge->Evolve->
    Prevent chain apart from a leftover row from an older chain (which
    can carry a different, equally-valid threshold_value). Alert
    creation/resolution/threshold logic (alert_store.py's other
    methods, agents/monitoring_agent.py, agents/prevent_agent.py) is
    completely unchanged -- this endpoint only additively classifies
    and reorders the already-stored rows it reads: current-context
    alerts (matching this service's latest Prevention run) first,
    then historical alerts, each group keeping its own most-recent-
    first order. No alert is deleted, mutated, or resolved here."""
    require_permission(context, "tenant:read")
    _require_service_access(service_id, context)

    alerts = alert_store.list_alerts_for_service(service_id, context.tenant_id)
    preventions = prevention_store.list_preventions_for_service(service_id, context.tenant_id)
    current_prevention_id = determine_current_prevention_id(preventions)

    # Resolve each DISTINCT prevention_id present among the alerts to
    # its own source Challenge run (prevention -> evolution ->
    # challenge, all three stores/relationships already existing and
    # unchanged) -- so an alert can honestly report which Challenge
    # run it traces back to, without guessing.
    prevention_to_challenge_id = {}
    for prevention_id in {alert["prevention_id"] for alert in alerts}:
        prevention = prevention_store.get_prevention_for_tenant(prevention_id, context.tenant_id)
        if not prevention:
            continue
        evolution = evolution_store.get_evolution_for_tenant(prevention["evolution_id"], context.tenant_id)
        if evolution:
            prevention_to_challenge_id[prevention_id] = evolution["challenge_id"]

    classified = classify_and_order_alerts(alerts, current_prevention_id, prevention_to_challenge_id)
    return {"alerts": classified}


@app.get("/api/audit-log")
def get_audit_log(context: TenantContext = Depends(get_tenant_context)):
    """Section 21/38: audit trail is tenant-scoped like everything
    else -- Tenant A can never see Tenant B's audit entries."""
    require_permission(context, "tenant:read")
    return {"entries": runtime_store.list_audit_log_for_tenant(context.tenant_id)}


@app.post("/api/data-sources")
def create_data_source(payload: CreateDataSourceRequest, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_data_sources")
    file_bytes = None
    safe_name = None
    if payload.file_content_base64 and payload.original_filename:
        try:
            file_bytes = base64.b64decode(payload.file_content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=422, detail="Uploaded file content is not valid base64.") from exc
        if len(file_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Demo upload limit is 25 MB per file.")
        safe_name = Path(payload.original_filename).name
        safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", safe_name).strip() or "source.bin"
    try:
        source = catalog_store.create_data_source(
            tenant_id=context.tenant_id,
            name=payload.name,
            source_type=payload.type,
            configuration=payload.configuration,
            classification=payload.classification,
            created_by=context.user_id,
            status=payload.status,
        )
        if file_bytes is not None and safe_name:
            root = get_tenant_files_root()
            destination = root / context.tenant_id / source["id"]
            destination.mkdir(parents=True, exist_ok=True)
            file_path = destination / safe_name
            try:
                file_path.write_bytes(file_bytes)
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Could not persist the uploaded tenant file.") from exc
            # Tenant uploads live under persistent ZX_DATA_ROOT and can be
            # outside the extracted project directory. Store their path relative
            # to that persistent data root instead of server/.
            relative_path = str(file_path.relative_to(get_data_root()))
            source = catalog_store.attach_file_metadata(
                source["id"], context.tenant_id, relative_path, safe_name,
                payload.mime_type, len(file_bytes),
            )
        return source
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/data-sources")
def list_data_sources(context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    items = catalog_store.list_data_sources_for_tenant(context.tenant_id)
    if context.role == "service_owner":
        allowed = _service_owner_data_source_ids(context)
        items = [item for item in items if item["id"] in allowed]
    return {"data_sources": items}


def _require_openapi_management(context):
    # Phase 10: Service Owners may import/refresh OpenAPI only for Services
    # assigned to them; `_require_service_access` remains the resource gate.
    if context.role == "service_owner":
        return
    require_permission(context, "tenant:manage_integrations")


def _openapi_http_error(error):
    if isinstance(error, UnsafeUrlError):
        return HTTPException(status_code=422, detail={"code": "OPENAPI_UNSAFE_URL", "message": str(error)})
    if isinstance(error, OpenApiImportError):
        return HTTPException(status_code=422, detail={"code": getattr(error, "code", "OPENAPI_IMPORT_FAILED"), "message": str(error)})
    return HTTPException(status_code=422, detail={"code": "OPENAPI_IMPORT_FAILED", "message": "OpenAPI import failed safely."})


@app.post("/api/services/{service_id}/openapi-import")
def import_openapi_for_service(
    service_id: str,
    payload: ImportOpenApiRequest,
    context: TenantContext = Depends(get_tenant_context),
):
    """Discover one Swagger/OpenAPI document and register its operations.

    Import is metadata discovery only: no described API operation is executed.
    """
    _require_openapi_management(context)
    _require_service_access(service_id, context)
    try:
        metadata, operations = fetch_and_parse(payload.url)
        integration = catalog_store.create_integration(
            tenant_id=context.tenant_id,
            integration_type=payload.integration_type,
            name=payload.name or metadata.get("title") or "Imported OpenAPI",
            config={"source": "OPENAPI"},
            secret_reference=None,
            status=payload.environment,
        )
        saved_source = api_operation_store.upsert_source_and_operations(
            context.tenant_id, service_id, integration["id"], metadata, operations, integration["status"]
        )
        current = service_store.get_service_connection_ids(service_id, context.tenant_id)
        integration_ids = list(dict.fromkeys((current.get("integration_ids") or []) + [integration["id"]]))
        service_store.set_service_connections(
            service_id, context.tenant_id, current.get("data_source_ids") or [], integration_ids
        )
        runtime_store.record_audit(
            context.tenant_id, context.user_id, "OPENAPI_IMPORTED", "integration", integration["id"],
            {"service_id": service_id, "operations_discovered": len(operations), "environment": integration["status"]},
        )
        return {
            "integration_id": integration["id"],
            "source_id": saved_source["id"],
            "title": metadata.get("title"),
            "api_version": metadata.get("api_version"),
            "openapi_version": metadata.get("openapi_version"),
            "environment": integration["status"],
            "operations_discovered": len(operations),
            "servers": metadata.get("servers") or [],
        }
    except (UnsafeUrlError, OpenApiImportError) as error:
        raise _openapi_http_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/integrations/{integration_id}/openapi-refresh")
def refresh_openapi_integration(
    integration_id: str,
    context: TenantContext = Depends(get_tenant_context),
):
    _require_openapi_management(context)
    integration = catalog_store.get_integration_for_tenant(integration_id, context.tenant_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found.")
    # Source lookup binds refresh to the original tenant/service/integration.
    source = None
    # We do not know service_id until reading the tenant's sources, so find it
    # through the Integration's linked services, never through user input.
    for service in service_store.list_services_for_tenant(context.tenant_id):
        ids = service_store.get_service_connection_ids(service["id"], context.tenant_id)
        if integration_id in (ids.get("integration_ids") or []):
            candidate = api_operation_store.get_source_for_integration(context.tenant_id, service["id"], integration_id)
            if candidate:
                source = candidate
                break
    if not source:
        raise HTTPException(status_code=404, detail="Imported OpenAPI source not found.")
    _require_service_access(source["service_id"], context)
    try:
        metadata, operations = fetch_and_parse(source["source_url"])
        saved_source = api_operation_store.upsert_source_and_operations(
            context.tenant_id, source["service_id"], integration_id, metadata, operations, integration["status"]
        )
        runtime_store.record_audit(
            context.tenant_id, context.user_id, "OPENAPI_REFRESHED", "integration", integration_id,
            {"service_id": source["service_id"], "operations_discovered": len(operations), "environment": integration["status"]},
        )
        return {
            "integration_id": integration_id,
            "source_id": saved_source["id"],
            "title": metadata.get("title"),
            "api_version": metadata.get("api_version"),
            "openapi_version": metadata.get("openapi_version"),
            "environment": integration["status"],
            "operations_discovered": len(operations),
            "servers": metadata.get("servers") or [],
        }
    except (UnsafeUrlError, OpenApiImportError) as error:
        raise _openapi_http_error(error) from error


@app.get("/api/integrations/{integration_id}/operations")
def list_openapi_operations(integration_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    integration = catalog_store.get_integration_for_tenant(integration_id, context.tenant_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found.")
    source = None
    for service in service_store.list_services_for_tenant(context.tenant_id):
        candidate = api_operation_store.get_source_for_integration(context.tenant_id, service["id"], integration_id)
        if candidate:
            source = candidate
            break
    if not source:
        return {"integration_id": integration_id, "source": None, "operations": []}
    _require_service_access(source["service_id"], context)
    operations = api_operation_store.list_operations_for_integration(
        context.tenant_id, integration_id, service_id=source["service_id"]
    )
    safe_source = {
        "id": source["id"], "service_id": source["service_id"], "integration_id": source["integration_id"],
        "source_url": source["source_url"], "title": source["title"], "api_version": source.get("api_version"),
        "openapi_version": source["openapi_version"], "format": source["format"], "servers": source.get("servers") or [],
        "updated_at": source["updated_at"],
    }
    return {"integration_id": integration_id, "source": safe_source, "operations": operations}


@app.post("/api/integrations")
def create_integration(payload: CreateIntegrationRequest, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:manage_integrations")
    try:
        integration = catalog_store.create_integration(
            tenant_id=context.tenant_id,
            integration_type=payload.type,
            name=payload.name,
            config=payload.config,
            secret_reference=payload.secret_reference,
            status=payload.status,
        )
        runtime_store.record_audit(context.tenant_id, context.user_id, "INTEGRATION_CONFIGURED", "integration", integration["id"], {"type": integration["type"], "status": integration["status"]})
        return integration
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/integrations")
def list_integrations(context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    return {"integrations": catalog_store.list_integrations_for_tenant(context.tenant_id)}


@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    customer = runtime_store.get_customer_for_tenant(customer_id, context.tenant_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return customer


@app.get("/api/data-sources/{data_source_id}")
def get_data_source(data_source_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    data_source = catalog_store.get_data_source_for_tenant(data_source_id, context.tenant_id)
    if not data_source:
        raise HTTPException(status_code=404, detail="Data source not found.")
    if context.role == "service_owner" and data_source_id not in _service_owner_data_source_ids(context):
        raise HTTPException(status_code=404, detail="Data source not found.")
    return data_source


@app.get("/api/integrations/{integration_id}")
def get_integration(integration_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    integration = catalog_store.get_integration_for_tenant(integration_id, context.tenant_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found.")
    return integration


@app.post("/api/agents/publish")
def publish_agent(payload: PublishAgentRequest, context: TenantContext = Depends(get_tenant_context)):
    """Publishing an Agent is an additive step on top of an already
    PUBLISHED Blueprint (Section 34's approval requirement is
    unchanged) -- it creates the persistent, tenant-scoped public
    slug that replaces the frontend's localStorage-based
    `zero-xray:{agentId}` lookup (Section 12/13)."""
    require_permission(context, "tenant:manage_agents")
    blueprint = runtime_store.get_blueprint_for_tenant(payload.blueprint_id, context.tenant_id)
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    _require_blueprint_service_access(blueprint, context)
    try:
        agent = agent_store.publish_agent(
            tenant_id=context.tenant_id,
            blueprint=blueprint,
            name=payload.name,
            created_by=context.user_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return agent


@app.get("/api/agents")
def list_agents(context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    agents = agent_store.list_agents_for_tenant(context.tenant_id)
    if context.role == "service_owner":
        allowed = {item["id"] for item in service_store.list_services_for_user(context.tenant_id, context.user_id)}
        agents = [agent for agent in agents if agent.get("service_id") in allowed]
    return {"agents": agents}


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, context: TenantContext = Depends(get_tenant_context)):
    require_permission(context, "tenant:read")
    agent = agent_store.get_agent_for_tenant(agent_id, context.tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    if context.role == "service_owner":
        try:
            _require_service_access(agent["service_id"], context)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


@app.get("/service/{tenant_slug}/{agent_slug}")
def get_public_service(tenant_slug: str, agent_slug: str):
    """*** PUBLIC, ANONYMOUS ENDPOINT ***
    No tenant context required by design (Section 42) -- this is the
    customer-facing published-service URL. Returns ONLY the
    sanitized/allowlisted subset of the Blueprint's analysis (see
    `core.agent_store.sanitize_for_public`): never internal analysis
    reasoning, standards-retrieval text, validation detail, prompts,
    or credentials."""
    agent = agent_store.get_agent_by_public_slug(tenant_slug, agent_slug)
    if not agent:
        raise HTTPException(status_code=404, detail="Service not found.")
    blueprint = runtime_store.get_blueprint_for_tenant(agent["blueprint_id"], agent["tenant_id"])
    if not blueprint or blueprint["status"] != "PUBLISHED":
        raise HTTPException(status_code=404, detail="Service not found.")
    public_result = sanitize_for_public(blueprint["analysis"])
    public_result["blueprint_id"] = blueprint["id"]
    public_result["blueprint_status"] = blueprint["status"]
    return {
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "tenant_slug": tenant_slug,
        "result": public_result,
    }


@app.post("/api/sandbox/register")
def register_customer(
    customer: CustomerRegistration,
    context: TenantContext = Depends(get_tenant_context_optional),
):
    if not customer.name.strip() or not customer.email.strip():
        raise HTTPException(status_code=422, detail="Name and email are required.")

    # Keep both launch paths valid without weakening tenant isolation:
    #   * Staff preview (authenticated): the requested Blueprint must belong
    #     to the signed-in tenant; APPROVED and PUBLISHED Blueprints may be
    #     exercised in Sandbox.
    #   * Public published service (anonymous): only a PUBLISHED Blueprint is
    #     accepted, exactly matching the public /service/... boundary.
    # In both cases the server, never the browser, derives the customer tenant.
    tenant_id = None
    if customer.blueprint_id:
        if context is not None:
            blueprint = runtime_store.get_blueprint_for_tenant(
                customer.blueprint_id, context.tenant_id
            )
            if not blueprint:
                raise HTTPException(status_code=404, detail="Service Blueprint not found.")
            # PHASE 5: staff-preview Test Agent launch must respect the same
            # Service Owner assignment scoping already enforced for viewing
            # /publishing this Blueprint elsewhere (get_blueprint/approve/
            # publish/publish_agent) -- tenant ownership alone is not
            # enough. Reuses the existing helper; a Service Owner not
            # assigned to this Blueprint's Service gets the same 404 as a
            # nonexistent Blueprint, so assignment state cannot be probed.
            _require_blueprint_service_access(blueprint, context)
            tenant_id = context.tenant_id
        else:
            blueprint = runtime_store.get_blueprint(customer.blueprint_id)
            if not blueprint or blueprint["status"] != "PUBLISHED":
                raise HTTPException(status_code=404, detail="Published service not found.")
            tenant_id = blueprint.get("tenant_id")

    return runtime_store.register_customer(customer.name, customer.email, tenant_id=tenant_id)


@app.post("/api/journeys")
def start_journey(request: JourneyStart, response: Response):
    if not request.sandbox:
        raise HTTPException(
            status_code=409,
            detail="Live execution is disabled. Connect approved identity, payment and service adapters before enabling it.",
        )
    try:
        journey = runtime_store.create_journey(
            customer_id=request.customer_id,
            intent=request.intent,
            blueprint_id=request.blueprint_id,
            lang=request.lang,
            sandbox=request.sandbox,
        )

        blueprint = runtime_store.get_blueprint_for_tenant(
            journey["blueprint_id"],
            journey["tenant_id"],
        )

        if blueprint and blueprint.get("service_id"):
            try:
                candidates = live_api_executor.select_read_operations(
                    journey["tenant_id"],
                    blueprint["service_id"],
                    service_name=blueprint.get("service_name", ""),
                    intent=request.intent,
                    limit=12,
                )

                live_results = []
                known_values = {}
                pending_candidates = []

                print(
                    "[LIVE API] service=",
                    blueprint.get("service_name"),
                    "service_id=",
                    blueprint.get("service_id"),
                    "candidates=",
                    len(candidates),
                )

                # Pass 1: execute GETs whose required parameters are already
                # available from OpenAPI examples/defaults.
                for candidate in candidates:
                    operation = candidate["operation"]
                    prepared = live_api_executor.prepare_request_arguments(
                        operation,
                        known_values=known_values,
                    )

                    if prepared["missing"]:
                        pending_candidates.append(candidate)
                        print(
                            "[LIVE API] waiting for parameters",
                            operation.get("operation_id") or operation.get("path"),
                            prepared["missing"],
                        )
                        continue

                    try:
                        result = live_api_executor.execute_get(
                            journey["tenant_id"],
                            candidate["source_service_id"],
                            candidate["integration_id"],
                            operation,
                            path_params=prepared["path_params"],
                            query_params=prepared["query_params"],
                            headers=prepared["headers"],
                        )
                        live_results.append(result)
                        known_values.update(
                            live_api_executor.extract_context_values(
                                result.get("payload")
                            )
                        )
                        print(
                            "[LIVE API] GET OK",
                            candidate.get("match_scope"),
                            operation.get("operation_id") or operation.get("path"),
                            result.get("status_code"),
                        )
                    except LiveApiExecutionError as error:
                        print(
                            "[LIVE API] GET skipped",
                            operation.get("operation_id") or operation.get("path"),
                            str(error),
                        )

                # Pass 2: retry parameterized GETs using exact-name values
                # returned by successful reads from Pass 1.
                for candidate in pending_candidates:
                    operation = candidate["operation"]
                    prepared = live_api_executor.prepare_request_arguments(
                        operation,
                        known_values=known_values,
                    )

                    if prepared["missing"]:
                        continue

                    try:
                        result = live_api_executor.execute_get(
                            journey["tenant_id"],
                            candidate["source_service_id"],
                            candidate["integration_id"],
                            operation,
                            path_params=prepared["path_params"],
                            query_params=prepared["query_params"],
                            headers=prepared["headers"],
                        )
                        live_results.append(result)
                        known_values.update(
                            live_api_executor.extract_context_values(
                                result.get("payload")
                            )
                        )
                        print(
                            "[LIVE API] chained GET OK",
                            candidate.get("match_scope"),
                            operation.get("operation_id") or operation.get("path"),
                            result.get("status_code"),
                        )
                    except LiveApiExecutionError as error:
                        print(
                            "[LIVE API] chained GET skipped",
                            operation.get("operation_id") or operation.get("path"),
                            str(error),
                        )

                if live_results:
                    normalized = live_api_executor.normalize_results(live_results)
                    plan = dict(journey.get("plan") or {})
                    edit_options = dict(plan.get("edit_options") or {})

                    duration_years = []
                    for raw_duration in normalized.get("durations") or []:
                        text = str(raw_duration or "").strip().lower()
                        years = None

                        if re.fullmatch(r"\d+", text):
                            years = int(text)
                        else:
                            year_match = re.search(r"(\d+)\s*(?:year|years|yr|yrs)", text)
                            month_match = re.search(r"(\d+)\s*(?:month|months|mo|mos)", text)

                            if year_match:
                                years = int(year_match.group(1))
                            elif month_match:
                                months = int(month_match.group(1))
                                if months > 0 and months % 12 == 0:
                                    years = months // 12

                        if years and years > 0 and years not in duration_years:
                            duration_years.append(years)

                    package_period = (
                        "YEAR"
                        if duration_years or edit_options.get("contract_durations")
                        else "ONCE"
                    )

                    api_packages = []
                    for index, item in enumerate(
                        normalized.get("packages") or [],
                        start=1,
                    ):
                        name = str(item.get("name") or f"Option {index}").strip()
                        package_id = re.sub(
                            r"[^a-z0-9]+",
                            "-",
                            name.lower(),
                        ).strip("-") or f"api-option-{index}"

                        api_packages.append({
                            "id": package_id,
                            "name": name,
                            "price_per_year": item.get("price"),
                            "billing_period": package_period,
                            "source": "LIVE_API",
                        })

                    api_add_ons = []
                    for index, item in enumerate(
                        normalized.get("add_ons") or [],
                        start=1,
                    ):
                        name = str(item.get("name") or f"Add-on {index}").strip()
                        add_on_id = re.sub(
                            r"[^a-z0-9]+",
                            "-",
                            name.lower(),
                        ).strip("-") or f"api-addon-{index}"

                        api_add_ons.append({
                            "id": add_on_id,
                            "name": name,
                            "unit_price": item.get("price"),
                            "billing_period": "ONCE",
                            "default_quantity": 0,
                            "source": "LIVE_API",
                        })

                    api_fees = []
                    for index, item in enumerate(
                        normalized.get("fees") or [],
                        start=1,
                    ):
                        name = str(item.get("name") or f"Fee {index}").strip()
                        fee_id = re.sub(
                            r"[^a-z0-9]+",
                            "-",
                            name.lower(),
                        ).strip("-") or f"api-fee-{index}"

                        api_fees.append({
                            "id": fee_id,
                            "name": name,
                            "unit_price": item.get("price"),
                            "billing_period": "ONCE",
                            "source": "LIVE_API",
                        })

                    if api_packages:
                        edit_options["packages"] = api_packages

                    if duration_years:
                        edit_options["contract_durations"] = duration_years

                    if api_add_ons:
                        edit_options["add_ons"] = api_add_ons

                    if api_fees:
                        edit_options["one_time_fees"] = api_fees

                    currency = normalized.get("currency") or "AED"
                    edit_options["currency"] = currency
                    edit_options["catalog_source"] = "LIVE_API"

                    priced_packages = [
                        item
                        for item in api_packages
                        if item.get("price_per_year") is not None
                    ]
                    priced_fees = [
                        item
                        for item in api_fees
                        if item.get("unit_price") is not None
                    ]

                    live_amount = None
                    if priced_packages:
                        live_amount = float(priced_packages[0]["price_per_year"])
                    elif priced_fees:
                        live_amount = sum(
                            float(item["unit_price"])
                            for item in priced_fees
                        )

                    if api_packages or api_add_ons or api_fees:
                        edit_options["mode"] = "PAYMENT"

                    plan["edit_options"] = edit_options

                    if api_packages:
                        plan["selected_package_id"] = api_packages[0]["id"]
                        plan["selected_package_name"] = api_packages[0]["name"]

                    if duration_years:
                        plan["contract_years"] = duration_years[0]

                    if live_amount is not None:
                        plan["requires_payment"] = True
                        plan["payment_context"] = "REQUIRED"
                        plan["fee_amount"] = live_amount
                        plan["total_fee"] = live_amount
                        plan["fee_currency"] = currency
                        plan["fee_status"] = "REQUIRED"
                        plan["fee_source"] = "Live connected API"
                        plan["fee_display"] = f"{currency} {live_amount:,.2f}"

                    plan["live_api"] = {
                        "status": "CONNECTED",
                        "source": "OPENAPI",
                        "identity_mode": "DEMO_PLACEHOLDER",
                        "identity_note": (
                            "Temporary sandbox values are being used until UAE PASS "
                            "or another authoritative identity source is connected."
                        ),
                        "catalog": normalized,
                        "operations": [
                            {
                                "integration_id": result.get("integration_id"),
                                "operation_id": result.get("operation_id"),
                                "method": result.get("method"),
                                "path": result.get("path"),
                                "status_code": result.get("status_code"),
                            }
                            for result in live_results
                        ],
                    }

                    journey = runtime_store.apply_live_plan_enrichment(
                        journey["id"],
                        journey["tenant_id"],
                        plan,
                    )

                else:
                    plan = dict(journey.get("plan") or {})
                    edit_options = dict(plan.get("edit_options") or {})

                    service_text = " ".join([
                        str(blueprint.get("service_name") or ""),
                        str((blueprint.get("service") or {}).get("name") or ""),
                        str((blueprint.get("service") or {}).get("service_name") or ""),
                        str(request.intent or ""),
                    ]).lower()

                    is_corporate_po_box = (
                        "corporate" in service_text
                        and (
                            "p.o. box" in service_text
                            or "po box" in service_text
                            or "pobox" in service_text
                        )
                    )

                    if is_corporate_po_box:
                        demo_packages = [
                            {
                                "id": "basic",
                                "name": "Basic",
                                "price_per_year": 995.0,
                                "billing_period": "YEAR",
                                "source": "DEMO_FALLBACK_UNTIL_IDENTITY",
                            },
                            {
                                "id": "premium",
                                "name": "Premium",
                                "price_per_year": 2495.0,
                                "billing_period": "YEAR",
                                "source": "DEMO_FALLBACK_UNTIL_IDENTITY",
                            },
                            {
                                "id": "premium-plus",
                                "name": "Premium+",
                                "price_per_year": 11995.0,
                                "billing_period": "YEAR",
                                "source": "DEMO_FALLBACK_UNTIL_IDENTITY",
                            },
                        ]

                        edit_options["mode"] = "PAYMENT"
                        edit_options["packages"] = demo_packages
                        edit_options["contract_durations"] = [1, 2, 3, 5, 10]
                        edit_options["currency"] = "AED"
                        edit_options["catalog_source"] = "DEMO_UNTIL_IDENTITY"

                        plan["edit_options"] = edit_options
                        plan["selected_package_id"] = demo_packages[0]["id"]
                        plan["selected_package_name"] = demo_packages[0]["name"]
                        plan["contract_years"] = 1
                        plan["requires_payment"] = True
                        plan["payment_context"] = "REQUIRED"
                        plan["fee_amount"] = demo_packages[0]["price_per_year"]
                        plan["total_fee"] = demo_packages[0]["price_per_year"]
                        plan["fee_currency"] = "AED"
                        plan["fee_status"] = "DEMO_ESTIMATE"
                        plan["fee_source"] = "Demo fallback until UAE PASS"
                        plan["fee_display"] = "From AED 995.00"
                        plan["recommended_option"] = (
                            "Choose a package and duration. The live Emirates Post API "
                            "will replace these temporary demo values automatically once "
                            "authoritative identity/account data is connected."
                        )
                    else:
                        plan["fee_amount"] = None
                        plan["total_fee"] = None
                        plan["fee_status"] = "PENDING_IDENTITY"
                        plan["fee_source"] = "CONNECTED_API_PENDING_IDENTITY"
                        plan["fee_display"] = "Price available after identity verification"
                        plan["recommended_option"] = (
                            "The agent matched the connected API. Final options and price "
                            "will be retrieved automatically after identity verification."
                        )

                    plan["live_api"] = {
                        "status": "WAITING_FOR_AUTHORITATIVE_DATA",
                        "source": "OPENAPI",
                        "identity_mode": "DEMO_PLACEHOLDER",
                        "identity_note": (
                            "Temporary demo values are shown only until UAE PASS or "
                            "another authoritative identity source is connected."
                        ),
                    }

                    journey = runtime_store.apply_live_plan_enrichment(
                        journey["id"],
                        journey["tenant_id"],
                        plan,
                    )

            except LiveApiExecutionError:
                pass

        raw_token, expires_at = runtime_store.issue_journey_capability(
            journey["id"], journey["customer_id"]
        )
        _set_customer_journey_cookie(response, journey["id"], raw_token, expires_at)
        return journey
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/journeys/{journey_id}")
def get_journey(journey_id: str, request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    return _customer_journey_or_403(journey_id, request, context)


@app.post("/api/journeys/{journey_id}/edit")
def edit_plan(journey_id: str, request: PlanEdit, http_request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    authorized = _customer_journey_or_403(journey_id, http_request, context)
    try:
        return runtime_store.edit_plan(
            journey_id,
            request.instruction,
            request.selections,
            tenant_id=authorized["tenant_id"],
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/journeys/{journey_id}/approve")
def approve_plan(journey_id: str, request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    authorized = _customer_journey_or_403(journey_id, request, context)
    try:
        return runtime_store.approve_plan(journey_id, tenant_id=authorized["tenant_id"])
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/journeys/{journey_id}/payment")
def sandbox_payment(journey_id: str, request: SandboxPayment, http_request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    authorized = _customer_journey_or_403(journey_id, http_request, context)
    try:
        journey = runtime_store.pay(
            journey_id,
            payment_method=request.payment_method,
            approved=request.approved,
            tenant_id=authorized["tenant_id"],
        )
        runtime_store.record_audit(authorized["tenant_id"], context.user_id if context else None, "PAYMENT_STATUS_CHANGED", "journey", journey_id, {"approved": request.approved, "payment_method": request.payment_method, "customer_id": authorized.get("customer_id")})
        return journey
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/journeys/{journey_id}/payment-assessment")
def prepare_payment_assessment(journey_id: str, request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    authorized = _customer_journey_or_403(journey_id, request, context)
    try:
        return runtime_store.prepare_payment_assessment(journey_id, tenant_id=authorized["tenant_id"])
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/journeys/{journey_id}/execute")
def execute_journey(journey_id: str, request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    authorized = _customer_journey_or_403(journey_id, request, context)
    try:
        # Public customer journeys are intentionally Sandbox-only today. Before
        # execution starts, validate that every attached integration belongs to
        # this tenant/service and that NOT_CONNECTED dependencies cannot be
        # mistaken for successful external execution. SANDBOX remains demo-only;
        # even CONNECTED integrations are not claimed as externally executed
        # because this endpoint performs no real adapter/API call.
        blueprint = runtime_store.get_blueprint_for_tenant(
            authorized["blueprint_id"], authorized["tenant_id"]
        )
        if blueprint and blueprint.get("service_id"):
            integration_execution_validator.validate_sandbox_journey(
                authorized["tenant_id"],
                blueprint["service_id"],
                required_integrations=(authorized.get("plan") or {}).get("integrations") or [],
            )
        return runtime_store.start_execution(journey_id, tenant_id=authorized["tenant_id"])
    except IntegrationExecutionError as error:
        raise HTTPException(
            status_code=409,
            detail={"state": error.state, "message": str(error), **error.details},
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/journeys/{journey_id}/events")
async def journey_events(journey_id: str, request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    authorized = _customer_journey_or_403(journey_id, request, context)
    tenant_id = authorized["tenant_id"]
    journey = authorized

    async def event_stream():
        events = runtime_store.list_events(journey_id, tenant_id=tenant_id)
        for event in events:
            current_journey = runtime_store.get_journey(journey_id, tenant_id=tenant_id)
            if current_journey and current_journey["state"] in {
                "PAUSED",
                "CANCELLED",
                "HUMAN_HANDOFF",
            }:
                yield (
                    "event: journey_controlled\n"
                    f"data: {json.dumps(current_journey, ensure_ascii=False)}\n\n"
                )
                return
            if event["status"] == "COMPLETED":
                continue
            runtime_store.set_event_status(event["id"], "RUNNING", tenant_id=tenant_id)
            running = {**event, "status": "RUNNING"}
            yield f"event: agent_event\ndata: {json.dumps(running, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.7)
            current_journey = runtime_store.get_journey(journey_id, tenant_id=tenant_id)
            if current_journey and current_journey["state"] in {
                "PAUSED",
                "CANCELLED",
                "HUMAN_HANDOFF",
            }:
                runtime_store.set_event_status(event["id"], "PAUSED", tenant_id=tenant_id)
                yield (
                    "event: journey_controlled\n"
                    f"data: {json.dumps(current_journey, ensure_ascii=False)}\n\n"
                )
                return
            runtime_store.set_event_status(event["id"], "COMPLETED", tenant_id=tenant_id)
            completed = {**event, "status": "COMPLETED"}
            yield f"event: agent_event\ndata: {json.dumps(completed, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.25)

        current_journey = runtime_store.get_journey(journey_id, tenant_id=tenant_id)
        if current_journey and current_journey["state"] in {
            "PAUSED",
            "CANCELLED",
            "HUMAN_HANDOFF",
        }:
            yield (
                "event: journey_controlled\n"
                f"data: {json.dumps(current_journey, ensure_ascii=False)}\n\n"
            )
            return

        completed_journey = runtime_store.complete_journey(journey_id, tenant_id=tenant_id)
        yield (
            "event: journey_complete\n"
            f"data: {json.dumps(completed_journey, ensure_ascii=False)}\n\n"
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/journeys/{journey_id}/{action}")
def control_journey(journey_id: str, action: str, request: Request, context: TenantContext = Depends(get_tenant_context_optional)):
    authorized = _customer_journey_or_403(journey_id, request, context)
    tenant_id = authorized["tenant_id"]
    if action == "resume":
        try:
            journey = runtime_store.resume_journey(journey_id, tenant_id=tenant_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not journey:
            raise HTTPException(status_code=404, detail="Journey not found.")
        return journey

    state_by_action = {
        "pause": "PAUSED",
        "cancel": "CANCELLED",
        "handoff": "HUMAN_HANDOFF",
    }
    state = state_by_action.get(action)
    if not state:
        raise HTTPException(status_code=404, detail="Unknown journey action.")
    journey = runtime_store.change_journey_state(
        journey_id, state, tenant_id=tenant_id
    )
    if not journey:
        raise HTTPException(status_code=404, detail="Journey not found.")
    if action == "cancel":
        runtime_store.revoke_journey_capabilities(journey_id)
        runtime_store.record_audit(tenant_id, context.user_id if context else None, "JOURNEY_CANCELLED", "journey", journey_id, {"customer_id": authorized.get("customer_id")})
    elif action == "handoff":
        runtime_store.record_audit(tenant_id, context.user_id if context else None, "HUMAN_HANDOFF_REQUESTED", "journey", journey_id, {"customer_id": authorized.get("customer_id")})
    return journey
