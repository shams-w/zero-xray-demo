"""Phase 8 -- Agent Comparison Readiness.

Deterministic adapters that convert:

  1. ZERO X-RAY's own generated Blueprint (already grounded/summarized/
     traced by Phases 2-4) into a safe, structured comparison profile.
  2. An employee-supplied description of an EXISTING entity Agent into
     the SAME structural shape, using ONLY explicitly supplied fields.

This module makes NO AI call, recalculates NOTHING already computed by
core/agent_capability_mapper.py, and invents NO score, percentage, or
"winner". Every capability dimension resolves to one of four states --
SUPPORTED / PARTIAL / NOT_SUPPORTED / UNKNOWN -- with concrete evidence
drawn only from already-structured data. Missing evidence is UNKNOWN,
never a guessed NOT_SUPPORTED/zero (see CAPABILITY_STATES below).

Nothing here persists anything; core/comparison_store.py owns storage.
"""

from __future__ import annotations

# The four states every capability dimension resolves to. Deliberately
# not a numeric score -- Phase 8 is comparison READINESS, not scoring.
CAPABILITY_STATES = {"SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "UNKNOWN"}

UNKNOWN = "UNKNOWN"
NOT_PROVIDED = "NOT_PROVIDED"

DIMENSIONS = [
    "service_understanding",
    "data_grounding",
    "real_api_usage",
    "customer_step_reduction",
    "automatic_data_fetching",
    "transaction_execution",
    "api_limit_awareness",
    "human_intervention",
    "traceability",
    "future_journey_alignment",
]


def _dim(state, evidence=None):
    """One capability-dimension entry. `evidence` is always a plain dict
    of already-structured facts -- never free narrative, never a prompt,
    never chain-of-thought."""
    if state not in CAPABILITY_STATES:
        state = UNKNOWN
    return {"state": state, "evidence": evidence or {}}


# ---------------------------------------------------------------------------
# 1. ZERO X-RAY generated Agent -> comparison profile
# ---------------------------------------------------------------------------


def build_zero_xray_comparison_profile(tenant_id, service_id, blueprint):
    """Build the ZERO X-RAY side of a comparison from an already-generated
    Blueprint (server/core/runtime_store.py's shape: blueprint["analysis"]
    contains the Phase 2-4 `agent_capability_map`, if the Blueprint was
    created after Phase 2).

    Never calls the AI, never re-derives future_steps/required_integrations
    -- everything here is read straight from `agent_capability_map`
    (Phase 2's data_sources_used/integration_capabilities/
    step_capability_mapping/summary). A legacy Blueprint (no
    `agent_capability_map` at all) safely produces UNKNOWN metrics and
    UNKNOWN capability dimensions rather than crashing or guessing.
    """
    analysis = (blueprint or {}).get("analysis") or {}
    cap_map = analysis.get("agent_capability_map") or {}
    summary = cap_map.get("summary")
    step_mapping = cap_map.get("step_capability_mapping") or []
    has_grounding = bool(cap_map)

    metrics = _zero_xray_metrics(summary, has_grounding)

    capabilities = {
        "service_understanding": _zero_xray_service_understanding(analysis),
        "data_grounding": _zero_xray_data_grounding(summary, has_grounding),
        "real_api_usage": _zero_xray_real_api_usage(summary, has_grounding),
        "customer_step_reduction": _zero_xray_customer_step_reduction(summary, has_grounding),
        "automatic_data_fetching": _zero_xray_automatic_data_fetching(step_mapping, has_grounding),
        "transaction_execution": _zero_xray_transaction_execution(step_mapping, has_grounding),
        "api_limit_awareness": _zero_xray_api_limit_awareness(summary, has_grounding),
        "human_intervention": _zero_xray_human_intervention(summary, has_grounding),
        "traceability": _zero_xray_traceability(step_mapping, has_grounding),
        "future_journey_alignment": _zero_xray_future_journey_alignment(step_mapping, has_grounding),
    }

    return {
        "source": "ZERO_XRAY",
        "tenant_id": tenant_id,
        "service_id": service_id,
        "blueprint_id": blueprint.get("id") if blueprint else None,
        "name": (blueprint or {}).get("service_name"),
        "metrics": metrics,
        "capabilities": capabilities,
    }


def _zero_xray_metrics(summary, has_grounding):
    if not has_grounding or not isinstance(summary, dict):
        return {
            "used_data_sources": UNKNOWN,
            "connected_apis": UNKNOWN,
            "sandbox_apis": UNKNOWN,
            "automated_steps": UNKNOWN,
            "total_steps": UNKNOWN,
            "customer_steps": UNKNOWN,
            "manual_steps": UNKNOWN,
            "integration_required": UNKNOWN,
        }
    # Reuse Phase 3's already-computed counts verbatim -- no
    # recalculation, so this can never disagree with the Build Agent
    # capability summary the employee already saw.
    return {
        "used_data_sources": summary.get("used_data_sources", 0),
        "connected_apis": summary.get("connected_apis", 0),
        "sandbox_apis": summary.get("sandbox_apis", 0),
        "automated_steps": summary.get("automated_steps", 0),
        "total_steps": summary.get("total_steps", 0),
        "customer_steps": summary.get("customer_steps", 0),
        "manual_steps": summary.get("manual_steps", 0),
        "integration_required": summary.get("integration_required", 0),
    }


def _zero_xray_service_understanding(analysis):
    # "Understanding" evidence = the structured service analysis already
    # produced by ServiceAnalystAgent exists on this Blueprint.
    service_analysis = analysis.get("service_analysis")
    if not isinstance(service_analysis, dict) or not service_analysis:
        return _dim(UNKNOWN)
    return _dim("SUPPORTED", {
        "has_structured_service_analysis": True,
        "step_count": len(service_analysis.get("steps") or []),
    })


def _zero_xray_data_grounding(summary, has_grounding):
    if not has_grounding:
        return _dim(UNKNOWN)
    used = summary.get("used_data_sources", 0)
    state = "SUPPORTED" if used > 0 else "NOT_SUPPORTED"
    return _dim(state, {"used_data_sources": used})


def _zero_xray_real_api_usage(summary, has_grounding):
    if not has_grounding:
        return _dim(UNKNOWN)
    connected = summary.get("connected_apis", 0)
    sandbox = summary.get("sandbox_apis", 0)
    if connected > 0:
        state = "SUPPORTED"
    elif sandbox > 0:
        state = "PARTIAL"
    else:
        state = "NOT_SUPPORTED"
    # CONNECTED/SANDBOX/NOT_CONNECTED are never combined into one
    # misleading count -- both are surfaced separately, per spec.
    return _dim(state, {"connected_apis": connected, "sandbox_apis": sandbox})


def _zero_xray_customer_step_reduction(summary, has_grounding):
    """Only the FUTURE customer-step count is reliably structured in
    this project (Phase 3's summary.customer_steps, derived from the
    Future Journey's own step_type classification). The CURRENT
    Journey's raw `service.steps` are plain, unclassified text -- there
    is no reliable structured customer/system/human split for them, so
    guessing a reduction from that text would be exactly the kind of
    inference this phase forbids. Reduction is therefore always UNKNOWN
    today; only the future-side count is reported as evidence."""
    if not has_grounding:
        return _dim(UNKNOWN)
    future_customer_steps = summary.get("customer_steps")
    return _dim(UNKNOWN, {
        "future_customer_steps": future_customer_steps if future_customer_steps is not None else UNKNOWN,
        "current_customer_steps": UNKNOWN,
        "reason": "No reliable structured customer-step classification exists for the Current Journey.",
    })


def _zero_xray_automatic_data_fetching(step_mapping, has_grounding):
    """Not inferred merely from a Data Source existing. Only a SYSTEM
    step already classified AUTOMATE with a real mapped Integration
    counts as evidence of an automated capability -- and even then this
    is only PARTIAL evidence of "fetching" specifically, since the
    project does not structurally distinguish a fetch/read step from any
    other automated action."""
    if not has_grounding:
        return _dim(UNKNOWN)
    automated_with_integration = [
        step for step in step_mapping
        if isinstance(step, dict)
        and step.get("capability_status") == "AUTOMATE"
        and step.get("mapped_integration")
    ]
    if not automated_with_integration:
        return _dim("NOT_SUPPORTED", {"automated_steps_with_integration": 0})
    return _dim("PARTIAL", {
        "automated_steps_with_integration": len(automated_with_integration),
        "reason": "Automated steps exist with a matched Integration, but the project does not "
                  "structurally distinguish a data-fetch action from any other automated action.",
    })


def _zero_xray_transaction_execution(step_mapping, has_grounding):
    """Same caution as automatic_data_fetching -- an Integration (even
    a payment one) existing does not by itself prove transaction
    execution. Only AUTOMATE steps mapped to a CONNECTED (not sandbox)
    Integration count as weak (PARTIAL) evidence."""
    if not has_grounding:
        return _dim(UNKNOWN)
    connected_automate = [
        step for step in step_mapping
        if isinstance(step, dict)
        and step.get("capability_status") == "AUTOMATE"
        and (step.get("mapped_integration") or {}).get("status") == "CONNECTED"
    ]
    if not connected_automate:
        return _dim("NOT_SUPPORTED", {"automated_steps_with_connected_integration": 0})
    return _dim("PARTIAL", {
        "automated_steps_with_connected_integration": len(connected_automate),
        "reason": "A CONNECTED Integration is wired to an automated step, but the project does not "
                  "structurally prove that step performs a transactional/write action.",
    })


def _zero_xray_api_limit_awareness(summary, has_grounding):
    """Whether the Agent explicitly knows when an API is unavailable
    rather than hallucinating execution. The project's own
    INTEGRATION_REQUIRED / NOT_CONNECTED-exclusion / sandbox-distinction
    machinery (Phase 2/4) IS this awareness, structurally, whenever
    grounding exists at all."""
    if not has_grounding:
        return _dim(UNKNOWN)
    return _dim("SUPPORTED", {
        "integration_required_steps": summary.get("integration_required", 0),
        "mechanism": "INTEGRATION_REQUIRED classification + NOT_CONNECTED exclusion from execution",
    })


def _zero_xray_human_intervention(summary, has_grounding):
    if not has_grounding:
        return _dim(UNKNOWN)
    manual = summary.get("manual_steps", 0)
    state = "SUPPORTED" if manual > 0 else "NOT_SUPPORTED"
    return _dim(state, {"manual_steps": manual})


def _zero_xray_traceability(step_mapping, has_grounding):
    """Phase 4's structured, concise `reason` per step -- never
    chain-of-thought, prompts, or hidden reasoning."""
    if not has_grounding or not step_mapping:
        return _dim(UNKNOWN)
    traceable = [s for s in step_mapping if isinstance(s, dict) and s.get("reason")]
    if not traceable:
        return _dim("NOT_SUPPORTED", {"traceable_steps": 0})
    return _dim("SUPPORTED", {"traceable_steps": len(traceable), "total_steps": len(step_mapping)})


def _zero_xray_future_journey_alignment(step_mapping, has_grounding):
    """Structural relationship only -- the generated Agent IS derived
    from the Future Journey by construction. No alignment SCORE is
    computed; this states the relationship and its evidence count."""
    if not has_grounding or not step_mapping:
        return _dim(UNKNOWN)
    return _dim("SUPPORTED", {
        "relationship": "derived_from_future_journey",
        "future_step_count": len(step_mapping),
    })


# ---------------------------------------------------------------------------
# 2. External / entity Agent -> comparison profile
# ---------------------------------------------------------------------------

# Fields the external profile may state a tri-state capability for
# directly (as supplied by the employee) rather than deriving from
# counts -- never inferred, only accepted verbatim when present.
_EXTERNAL_TRISTATE_FIELDS = (
    "automatic_data_fetching",
    "transaction_execution",
    "api_limit_awareness",
)


def _external_count_or_unknown(value):
    if value is None:
        return UNKNOWN
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return UNKNOWN


def _external_tristate(value):
    if value in CAPABILITY_STATES:
        return value
    return UNKNOWN


def build_external_agent_profile(tenant_id, service_id, payload):
    """Build the entity/external Agent side of a comparison from an
    employee-supplied, explicitly-stated description ONLY.

    `payload` is a plain dict (already validated by the Pydantic request
    model at the API boundary) of optional fields. Every field absent or
    None stays UNKNOWN/NOT_PROVIDED -- never converted into zero
    capability, never guessed from a count, never inferred from a
    Data Source or Integration merely existing.
    """
    payload = payload or {}

    known_data_sources_count = _external_count_or_unknown(payload.get("known_data_sources_count"))
    known_apis_count = _external_count_or_unknown(payload.get("known_apis_count"))
    customer_steps = _external_count_or_unknown(payload.get("customer_steps"))
    automated_steps = _external_count_or_unknown(payload.get("automated_steps"))
    manual_steps = _external_count_or_unknown(payload.get("manual_steps"))
    integration_required_steps = _external_count_or_unknown(payload.get("integration_required_steps"))

    metrics = {
        "used_data_sources": known_data_sources_count,
        "connected_apis": UNKNOWN,  # never invented -- see real_api_usage below
        "sandbox_apis": UNKNOWN,
        "automated_steps": automated_steps,
        "total_steps": UNKNOWN,
        "customer_steps": customer_steps,
        "manual_steps": manual_steps,
        "integration_required": integration_required_steps,
    }

    capabilities = {
        "service_understanding": _dim(
            "SUPPORTED" if payload.get("description") else UNKNOWN,
            {"description_provided": bool(payload.get("description"))},
        ),
        "data_grounding": _dim(
            "SUPPORTED" if known_data_sources_count not in (UNKNOWN, 0)
            else ("NOT_SUPPORTED" if known_data_sources_count == 0 else UNKNOWN),
            {"known_data_sources_count": known_data_sources_count,
             "known_data_sources": payload.get("known_data_sources") or NOT_PROVIDED},
        ),
        # Real API usage: ONLY explicitly supplied evidence -- an API
        # list/count being provided is evidence of SOME API knowledge,
        # but never assumed CONNECTED/executable unless stated.
        "real_api_usage": _dim(
            "PARTIAL" if known_apis_count not in (UNKNOWN, 0)
            else ("NOT_SUPPORTED" if known_apis_count == 0 else UNKNOWN),
            {"known_apis_count": known_apis_count,
             "known_apis": payload.get("known_apis") or NOT_PROVIDED,
             "reason": "Listed APIs are not assumed production-connected unless explicitly stated."},
        ),
        "customer_step_reduction": _dim(UNKNOWN, {
            "customer_steps": customer_steps,
            "reason": "No Current-Journey comparison is available for an external Agent.",
        }),
        "automatic_data_fetching": _dim(
            _external_tristate(payload.get("automatic_data_fetching")),
            {"stated_by_employee": payload.get("automatic_data_fetching") or NOT_PROVIDED},
        ),
        "transaction_execution": _dim(
            _external_tristate(payload.get("transaction_execution")),
            {"stated_by_employee": payload.get("transaction_execution") or NOT_PROVIDED,
             "payment_supported": payload.get("payment_supported")
             if payload.get("payment_supported") is not None else NOT_PROVIDED},
        ),
        "api_limit_awareness": _dim(
            _external_tristate(payload.get("api_limit_awareness")),
            {"stated_by_employee": payload.get("api_limit_awareness") or NOT_PROVIDED},
        ),
        "human_intervention": _dim(
            "SUPPORTED" if payload.get("human_handoff") is True
            else ("NOT_SUPPORTED" if payload.get("human_handoff") is False else UNKNOWN),
            {"manual_steps": manual_steps,
             "human_handoff": payload.get("human_handoff")
             if payload.get("human_handoff") is not None else NOT_PROVIDED},
        ),
        "traceability": _dim(
            "SUPPORTED" if payload.get("traceability_available") is True
            else ("NOT_SUPPORTED" if payload.get("traceability_available") is False else UNKNOWN),
            {"traceability_available": payload.get("traceability_available")
             if payload.get("traceability_available") is not None else NOT_PROVIDED},
        ),
        "future_journey_alignment": _dim(UNKNOWN, {
            "reason": "No Future Journey mapping was supplied for this external Agent.",
        }),
    }

    return {
        "source": "ENTITY_EXISTING",
        "tenant_id": tenant_id,
        "service_id": service_id,
        "name": payload.get("name") or NOT_PROVIDED,
        "description": payload.get("description") or NOT_PROVIDED,
        "evidence_notes": payload.get("evidence_notes") or NOT_PROVIDED,
        "metrics": metrics,
        "capabilities": capabilities,
    }


def build_comparison_readiness(zero_xray_profile, entity_profile):
    """Descriptive, side-by-side structure only. No score, no ranking,
    no "winner" -- see Phase 8 spec. `dimensions` simply names what was
    compared, for a future (not-yet-built) comparison layer to walk."""
    return {
        "zero_xray_agent": zero_xray_profile,
        "entity_agent": entity_profile,
        "dimensions": list(DIMENSIONS),
    }
