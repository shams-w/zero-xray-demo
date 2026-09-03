"""FutureSimulationAgent -- Step 2 ("Simulate") of the ZERO X-RAY ->
Government Future Engine evolution.

NOT THE SAME THING AS agents/simulation_agent.py. That existing agent
reshapes an already-decided current/future journey into a summary
view for the analysis pipeline; it is untouched by this file and is
never imported here. This agent answers a different question: "if a
predicted problem happens, what breaks next, and how badly" -- and it
answers that with a deterministic graph walk over data ZERO X-RAY
already stored, not with an LLM narrative.

======================================================================
WHY THIS IS A SIMULATION AND NOT "LLM, WRITE A STORY ABOUT THE FUTURE"
======================================================================
A Scenario (see models.schemas.Scenario) is a closed set of typed
variables against one of four fixed `scenario_type` archetypes. Each
archetype maps to exactly one pure Python function below
(_execute_integration_failure / _execute_cascading_step_failure /
_execute_sla_breach / _execute_volume_surge) that walks the SAME
`service_graph` structure built once from a service's own latest
stored analysis (agents/redesign_agent.py's `future_steps` /
`required_integrations`, exactly as already stored in
`analyses.result_json` -- the same table Predict already reads).
Given the same graph + the same scenario + the same variables, these
functions return the exact same affected-step set and the exact same
scores on every call -- see tests/test_future_simulation_agent.py's
determinism tests. The LLM is never asked to invent the scenario,
decide what's affected, or compute a score; it is optionally asked,
AFTER all of that is already computed, to phrase one sentence -- and
even that is validated against the computed facts (see
`_validate_llm_description`) before it's trusted.

======================================================================
THE SERVICE GRAPH -- WHAT'S REAL DATA VS. A DOCUMENTED MODELING RULE
======================================================================
`future_steps` (from the latest stored analysis) already carries a
real, agent-assigned `step_number` and a real `type` in
{"CUSTOMER", "HUMAN", "SYSTEM"} -- see agents/redesign_agent.py. This
agent treats that stored step_number ORDER as a real sequential
dependency chain (step N depends on step N-1) because that is
literally what "future_steps" already represents: an ordered
execution sequence the rest of the codebase already treats as
ordered (journey_builder_agent.py's own "depends_on_previous" field
exists for the same reason). That much is FACT, not invented.

What IS a documented modeling simplification (never hidden, always
labeled ASSUMPTION in the output) is: (a) which step `type`s count as
"customer-facing" ({"CUSTOMER", "HUMAN"}) vs. automated ("SYSTEM"),
and (b) that `required_integrations` have no stored per-step mapping,
so an integration failure is modeled as affecting all SYSTEM-type
steps rather than one specific step. Both rules are fixed constants
in this file, never re-decided per run and never decided by the LLM.

======================================================================
SCORING -- DETERMINISTIC ENGINEERING SCORES, NOT A STATISTICAL MODEL
======================================================================
Every score below is a bounded (core.scoring.clamp / local _clamp01),
explicitly-defined ratio or mean of counts that are themselves either
real stored data or a declared scenario variable. These are ZERO
X-RAY SIMULATION RISK/IMPACT SCORES: deterministic engineering
heuristics for comparing scenarios against each other, not a
statistically validated forecasting model, and this agent never
represents them as one.
"""

import re
from datetime import datetime, timezone
from core.result_provenance import provenance_for_mixed_result
from core.backend_language import normalize_lang

from agents.prediction_agent import fetch_journeys_for_service
from core.scoring import clamp
from core.score_methodology import SCORE_METHODOLOGY_MARKER
from core.llm_explanation_guard import is_placeholder_or_generic, extract_clean_explanation
from core.future_engine_errors import InsufficientDataError


# =====================================================================
# FIXED SCENARIO ARCHETYPES AND THEIR REQUIRED VARIABLES
# =====================================================================
SCENARIO_TYPES = {
    "VOLUME_SURGE": {"demand_multiplier", "time_horizon_days"},
    "INTEGRATION_FAILURE": {"failed_integration_id", "failure_duration_hours"},
    "SLA_BREACH": {"breached_step_id", "delay_multiplier"},
    "CASCADING_STEP_FAILURE": {"origin_step_id", "failure_probability"},
}

# Which stored step `type`s count as customer-facing (a citizen or a
# human employee is directly involved) vs. purely automated. This is
# a fixed, documented modeling rule -- not derived from stored data,
# not decided per run, not decided by the LLM.
CUSTOMER_FACING_STEP_TYPES = {"CUSTOMER", "HUMAN"}
AUTOMATED_STEP_TYPES = {"SYSTEM"}

# --- documented constants used only where stored data has no answer ---
# ROOT-CAUSE FIX (SLA handling audit): kept as the LAST-resort
# fallback only -- see resolve_sla_baseline_hours() below, which now
# checks real stored per-step and service-level evidence first and
# only reaches this constant when none exists anywhere.
GENERIC_SLA_HOURS_DEFAULT = 48

# Keyword evidence distinguishing "this text describes a committed
# SLA" from "this text just mentions a typical/expected duration" --
# used only to choose which of the two (documented, both real-
# evidence) resolution tiers a text-derived duration belongs to; it
# never affects WHETHER a duration is real evidence, only its label.
SLA_KEYWORDS = ("sla", "service level", "committed", "guarantee", "guaranteed")

# Duration mention pattern shared by step-level and service-level SLA
# resolution -- e.g. "3-5 business days", "48 hours", "2 weeks".
# Real, stored text only; never invents a number that isn't present.
_DURATION_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?)\s*)?"
    r"(hour|hr|business\s*day|working\s*day|day|week)s?",
    re.IGNORECASE,
)
_DURATION_UNIT_HOURS = {
    "hour": 1.0, "hr": 1.0, "businessday": 24.0, "workingday": 24.0,
    "day": 24.0, "week": 168.0,
}


def _parse_duration_hours(text):
    """Returns the LARGEST (most conservative -- the worst-case
    reading of a range like "3-5 days") duration explicitly mentioned
    in `text`, normalized to hours, or None if no duration is
    mentioned at all. Pure text parsing of REAL stored text -- never
    fabricates a number."""
    if not text:
        return None
    best = None
    for match in _DURATION_PATTERN.finditer(str(text)):
        low = float(match.group(1))
        high = float(match.group(2)) if match.group(2) else low
        unit_key = re.sub(r"\s+", "", match.group(3).lower())
        hours = high * _DURATION_UNIT_HOURS.get(unit_key, 1.0)
        if best is None or hours > best:
            best = hours
    return best

# Below this demand_multiplier, a volume surge is not modeled as
# degrading customer-facing steps -- an explicit, named threshold
# rather than a fuzzy per-run judgement call.
VOLUME_SURGE_DEGRADE_THRESHOLD = 1.5

# Used only when trigger_type=MANUAL and no PREDICTION-derived
# confidence is available to seed a scenario's likelihood. A single
# named constant, not an invented per-run number.
DEFAULT_MANUAL_LIKELIHOOD = 0.5

# =====================================================================
# FIX (Step 3 audit): fixed, deterministic lookup table mapping a
# stored Prediction's dominant signal source to a scenario_type +
# starting variables -- the originally specified Predict -> Simulate
# linkage (Step 2 design, Section 4, path 1) that was never wired up.
# No LLM involvement: every branch below is a plain function of
# already-computed, already-deterministic data (a Prediction's own
# `confidence`, a service_graph step's own real `order`).
# =====================================================================
# A citizen-need prediction (recurring journey intent) becomes a
# demand-surge stress test; a process-quality prediction (recurring
# gap or friction point) becomes an SLA-breach stress test on the
# service's earliest step, since neither signal type identifies a
# specific step/integration in the stored data (see the Step 2 design
# doc's own "no per-step mapping exists" note) -- the earliest step is
# used because it is real, stored, order-derived data, never a guess.
PREDICTION_SIGNAL_TO_SCENARIO_TYPE = {
    "journey_intent": "VOLUME_SURGE",
    "gap": "SLA_BREACH",
    "friction_point": "SLA_BREACH",
}

# Bounds applied to every prediction-derived variable below -- named,
# documented, never silently unbounded.
PREDICTION_DERIVED_VARIABLE_MIN = 1.0
PREDICTION_DERIVED_VARIABLE_MAX = 5.0
PREDICTION_DEFAULT_TIME_HORIZON_DAYS = 30.0
# How strongly a gap-sourced vs. friction-sourced prediction's
# confidence scales into an SLA delay_multiplier -- gaps are treated
# as a stronger signal (a stored, standards-linked compliance issue)
# than a friction point (a looser, free-text observation).
PREDICTION_GAP_DELAY_WEIGHT = 2.0
PREDICTION_FRICTION_DELAY_WEIGHT = 1.5

# Equal-weighted average of the two components of government_impact
# (affected SYSTEM steps vs. affected integrations). This is an
# explicit, documented engineering simplification -- NOT a
# statistically fitted weight -- kept as named constants so the
# formula is auditable at a glance.
GOVERNMENT_IMPACT_STEP_WEIGHT = 0.5
GOVERNMENT_IMPACT_INTEGRATION_WEIGHT = 0.5

# =====================================================================
# FIX (Section 2 audit): AUTO scenario generation -- fixed, named
# category list + variable defaults, used ONLY by
# generate_auto_scenarios() below. Deliberately NOT the same constants
# ChallengeAgent uses (CHALLENGE_WORST_CASE_PROBABILITY=1.0,
# CHALLENGE_SLA_STRESS_MULTIPLIER=3.0x, etc.) -- Challenge is an
# exhaustive, worst-case adversarial stress test over EVERY step and
# integration; AUTO Simulate is a single representative what-if per
# RELEVANT category, at a moderate (not worst-case) severity, so the
# two stay visibly distinct in intent even though both ultimately
# delegate to the same four deterministic scenario executors.
# =====================================================================
AUTO_SIM_STEP_FAILURE_PROBABILITY = 1.0
AUTO_SIM_INTEGRATION_FAILURE_DURATION_HOURS = 12.0
AUTO_SIM_SLA_DELAY_MULTIPLIER = 2.0
AUTO_SIM_DEMAND_SPIKE_MULTIPLIER = 2.0
AUTO_SIM_DEMAND_SPIKE_HORIZON_DAYS = PREDICTION_DEFAULT_TIME_HORIZON_DAYS

# Named, documented keyword evidence used ONLY to decide whether a
# category is RELEVANT to this specific service (payment/approval/
# missing-data) and, when relevant, which real stored step/integration
# it targets -- never to invent a step/integration that isn't already
# in service_graph. Checked against a step's own name/action text (see
# build_service_graph's "evidence_text") and an integration's own
# stored name -- both real, already-stored fields, not guesses.
AUTO_SIM_PAYMENT_KEYWORDS = ("payment", "pay ", "invoice", "billing", "fee ", "gateway", "checkout")
AUTO_SIM_APPROVAL_KEYWORDS = ("approv", "review", "authoriz", "sign-off", "signoff", "sign off")
AUTO_SIM_DOCUMENT_KEYWORDS = (
    "document", "upload", "attach", "identity proof", "id verification",
    "certificate", "form ", "supporting file",
)


def _text_has_any(text, keywords):
    lowered = str(text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _step_evidence_text(step):
    # Falls back to the step's own "name" when "evidence_text" isn't
    # present (e.g. a hand-built graph, or one from a version of
    # build_service_graph that predates this field) -- name is always
    # real, stored data either way, never invented.
    return step.get("evidence_text") or step.get("name") or ""


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _clamp01(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


class ScenarioValidationError(ValueError):
    """Raised for an invalid scenario_type, missing/invalid variable,
    or a step/integration reference that does not exist in this
    service's own stored graph. Callers (main.py) turn this into a
    400 response -- never a silent fallback and never a guess."""


class FutureSimulationAgent:

    def __init__(self, llm=None, lang="en"):
        self.llm = llm
        self.lang = normalize_lang(lang)

    # =================================================================
    # 1. SERVICE GRAPH (deterministic, built once from the LATEST
    #    stored analysis -- no LLM involved)
    # =================================================================

    def build_service_graph(self, service_id, tenant_id, service_store, database_path):
        analyses = service_store.list_analyses_for_service(service_id, tenant_id)
        journeys_count = len(
            fetch_journeys_for_service(database_path, service_id, tenant_id)
        )

        if not analyses:
            return {
                "steps": [], "integrations": [], "journeys_count": journeys_count,
                "source_analysis_id": None, "waiting_times": [],
            }

        latest = analyses[0]  # list_analyses_for_service orders DESC by created_at
        redesign = (latest.get("result") or {}).get("redesign", {}) or {}
        raw_steps = redesign.get("future_steps", []) or []
        raw_integrations = redesign.get("required_integrations", []) or []
        # ROOT-CAUSE FIX (SLA handling audit): ServiceInput.waiting_times
        # is a real, already-stored, user-entered field (free text like
        # "3-5 business days") that has never been read by Simulate/
        # Challenge before -- it is the SERVICE-level SLA/waiting-time
        # evidence resolve_sla_baseline_hours() falls back to when no
        # per-step evidence exists. Same existing result_json blob, no
        # schema change.
        raw_waiting_times = ((latest.get("result") or {}).get("service") or {}).get("waiting_times") or []

        steps = []
        for index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, dict):
                continue
            step_number = raw_step.get("step_number", index + 1)
            steps.append({
                "step_id": f"STEP-{step_number}",
                "name": raw_step.get("name", ""),
                "type": raw_step.get("type", "SYSTEM"),
                "order": index,
                # ROOT-CAUSE FIX (Section 2 audit -- relevance-gated
                # AUTO scenario generation): additive fields only,
                # never read by any pre-existing consumer of this
                # dict (they all read step_id/name/type/order only).
                # journey_builder_agent.py already stores has_payment
                # and requires_human_judgement/requires_customer_approval
                # per step -- both the AI-designed path and its own
                # template fallback set has_payment/requires_human_judgement
                # (see agents/journey_builder_agent.py) -- this is real,
                # already-stored evidence, not a new inference. Older
                # stored analyses that predate these fields simply have
                # them default to False here; generate_auto_scenarios()
                # below also falls back to keyword evidence in the
                # step's own name/action text so detection still works
                # for those older records (backward compatible).
                "has_payment": bool(raw_step.get("has_payment", False)),
                "requires_approval": bool(
                    raw_step.get("requires_human_judgement")
                    or raw_step.get("requires_customer_approval")
                ),
                "evidence_text": " ".join(
                    str(raw_step.get(field, "") or "")
                    for field in ("name", "action", "assistant_action", "detailed_description")
                ),
                # ROOT-CAUSE FIX (SLA handling audit): additive,
                # optional explicit fields -- no existing stored
                # future_step sets these today (same situation
                # has_payment/requires_approval were in before Section
                # 2's fix), so this is forward-compatible groundwork,
                # not a behavior change for any current record: a
                # caller that already knows a step's real committed
                # SLA or typical/expected duration (in hours) can store
                # it directly here, in the SAME existing future_steps
                # list -- no database/schema change. See
                # resolve_sla_baseline_hours().
                "sla_hours": raw_step.get("sla_hours"),
                "expected_duration_hours": raw_step.get("expected_duration_hours"),
            })

        integrations = []
        step_id_set = {s["step_id"] for s in steps}
        for index, raw_integration in enumerate(raw_integrations):
            # ROOT-CAUSE FIX (Integration-to-Step Mapping audit):
            # required_integrations has always been a plain list of
            # name strings (every existing stored analysis/blueprint
            # is exactly that) -- kept working byte-for-byte unchanged
            # below. This ADDITIONALLY accepts, per entry, a dict of
            # {"name": ..., "step_ids": [...]} so a caller that already
            # knows the real per-step mapping (e.g. STEP-1 -> UAE_PASS)
            # can store it directly in this SAME existing field --
            # required_integrations is already a JSON blob inside
            # result_json, so this needs no database/schema change at
            # all. Only step_ids that are real, currently-stored steps
            # are kept; anything else is silently dropped rather than
            # inventing a step reference (an old/stale mapping after a
            # re-analysis degrades to "no explicit mapping" instead of
            # pointing at a step that no longer exists).
            if isinstance(raw_integration, dict):
                name = str(raw_integration.get("name", "")).strip()
                explicit_step_ids = [
                    str(step_id) for step_id in (raw_integration.get("step_ids") or [])
                    if str(step_id) in step_id_set
                ]
            else:
                name = str(raw_integration).strip()
                explicit_step_ids = []
            if not name:
                continue
            integrations.append({
                "integration_id": f"INTEGRATION-{index + 1:03d}",
                "name": name,
                "step_ids": explicit_step_ids,
            })

        return {
            "steps": steps,
            "integrations": integrations,
            "journeys_count": journeys_count,
            "source_analysis_id": latest.get("id"),
            "waiting_times": [str(item) for item in raw_waiting_times if str(item).strip()],
        }

    # =================================================================
    # 1b. PREDICTION -> SCENARIO DERIVATION (fixed lookup table, no LLM)
    # =================================================================

    def derive_scenario_from_prediction(self, stored_prediction_result, service_graph):
        """Deterministically map a stored PredictionResult (Step 1's
        output, read-only, unmodified) to a (scenario_type, variables)
        pair, per PREDICTION_SIGNAL_TO_SCENARIO_TYPE above. Raises
        ScenarioValidationError if the prediction has nothing usable
        to derive from -- never falls back to guessing.

        Selection of WHICH prediction item to use, when a
        PredictionResult holds several, is itself deterministic:
        highest confidence first, tie-broken by prediction_id."""
        items = (stored_prediction_result or {}).get("predictions") or []
        if not items:
            raise ScenarioValidationError(
                "Linked prediction has no predictions to derive a scenario from."
            )
        chosen = min(items, key=lambda item: (-item.get("confidence", 0.0), item.get("prediction_id", "")))
        signals = chosen.get("signals") or []
        if not signals:
            raise ScenarioValidationError(
                "Linked prediction has no signals to derive a scenario from."
            )
        source = signals[0].get("source")
        if source not in PREDICTION_SIGNAL_TO_SCENARIO_TYPE:
            raise ScenarioValidationError(
                f"Unsupported prediction signal source '{source}' for scenario derivation. "
                f"Must be one of: {sorted(PREDICTION_SIGNAL_TO_SCENARIO_TYPE)}."
            )
        confidence = _clamp01(chosen.get("confidence", 0.0))
        scenario_type = PREDICTION_SIGNAL_TO_SCENARIO_TYPE[source]

        if scenario_type == "VOLUME_SURGE":
            demand_multiplier = round(
                min(PREDICTION_DERIVED_VARIABLE_MAX,
                    max(PREDICTION_DERIVED_VARIABLE_MIN, 1.0 + confidence)),
                2,
            )
            variables = {
                "demand_multiplier": demand_multiplier,
                "time_horizon_days": PREDICTION_DEFAULT_TIME_HORIZON_DAYS,
            }
        else:  # SLA_BREACH
            if not service_graph["steps"]:
                raise ScenarioValidationError(
                    "Linked prediction maps to an SLA_BREACH scenario, but this "
                    "service has no stored steps to target."
                )
            earliest_step = min(service_graph["steps"], key=lambda step: step["order"])
            weight = (
                PREDICTION_GAP_DELAY_WEIGHT if source == "gap" else PREDICTION_FRICTION_DELAY_WEIGHT
            )
            delay_multiplier = round(
                min(PREDICTION_DERIVED_VARIABLE_MAX,
                    max(PREDICTION_DERIVED_VARIABLE_MIN, 1.0 + weight * confidence)),
                2,
            )
            variables = {
                "breached_step_id": earliest_step["step_id"],
                "delay_multiplier": delay_multiplier,
            }

        return scenario_type, variables, chosen.get("prediction_id")

    # =================================================================
    # 1c. AUTO SCENARIO GENERATION (Section 2 audit fix -- fixed,
    #     relevance-gated rules, no LLM)
    # =================================================================

    def generate_auto_scenarios(self, service_graph):
        """Deterministically pick AT MOST ONE representative scenario
        per named category, and ONLY for a category this specific
        service actually has evidence for -- e.g. PAYMENT_FAILURE is
        never generated for a service with no payment step/integration.
        Returns a list of (category, scenario_type, variables) tuples
        in a fixed, documented priority order; callers still run each
        through validate_scenario()/run() exactly like any other
        scenario -- this method only DECIDES which scenarios are
        relevant, it does not execute or score anything itself.

        Never raises for an empty graph -- callers already check
        service_graph["steps"]/["integrations"] before reaching this
        point (see main.py), matching validate_scenario()'s own
        existing empty-graph guard.
        """
        steps = service_graph["steps"]
        integrations = service_graph["integrations"]
        ordered_steps = sorted(steps, key=lambda s: s["order"])
        candidates = []  # [(category, scenario_type, variables), ...]

        # -- STEP_FAILURE: relevant whenever any step is stored. Same
        # earliest-step convention already used by
        # derive_scenario_from_prediction above (real, stored order --
        # never a guess), which also happens to carry the most
        # downstream dependents (see _compute_bottlenecks).
        if ordered_steps:
            earliest = ordered_steps[0]
            candidates.append(("STEP_FAILURE", "CASCADING_STEP_FAILURE", {
                "origin_step_id": earliest["step_id"],
                "failure_probability": AUTO_SIM_STEP_FAILURE_PROBABILITY,
            }))

        # -- INTEGRATION_FAILURE (API/integration failure): relevant
        # only when this service has at least one stored integration.
        if integrations:
            first_integration = integrations[0]
            candidates.append(("INTEGRATION_FAILURE", "INTEGRATION_FAILURE", {
                "failed_integration_id": first_integration["integration_id"],
                "failure_duration_hours": AUTO_SIM_INTEGRATION_FAILURE_DURATION_HOURS,
            }))

        # -- SLA_DELAY: relevant whenever any step is stored.
        if ordered_steps:
            earliest = ordered_steps[0]
            candidates.append(("SLA_DELAY", "SLA_BREACH", {
                "breached_step_id": earliest["step_id"],
                "delay_multiplier": AUTO_SIM_SLA_DELAY_MULTIPLIER,
            }))

        # -- DEMAND_SPIKE: relevant only when a customer-facing step
        # exists -- a purely back-office/SYSTEM-only service has
        # nothing for a demand spike to degrade under this model.
        if any(s["type"] in CUSTOMER_FACING_STEP_TYPES for s in ordered_steps):
            candidates.append(("DEMAND_SPIKE", "VOLUME_SURGE", {
                "demand_multiplier": AUTO_SIM_DEMAND_SPIKE_MULTIPLIER,
                "time_horizon_days": AUTO_SIM_DEMAND_SPIKE_HORIZON_DAYS,
            }))

        # -- PAYMENT_FAILURE: relevant ONLY if this service has real
        # evidence of payment -- a step's own stored has_payment flag
        # or its evidence_text, or a payment-named integration. Prefer
        # the integration when both exist (a payment failure is most
        # naturally an integration/gateway failure).
        payment_integration = next(
            (item for item in integrations
             if _text_has_any(item["name"], AUTO_SIM_PAYMENT_KEYWORDS)),
            None,
        )
        payment_step = next(
            (s for s in ordered_steps
             if s.get("has_payment") or _text_has_any(_step_evidence_text(s), AUTO_SIM_PAYMENT_KEYWORDS)),
            None,
        )
        if payment_integration is not None:
            candidates.append(("PAYMENT_FAILURE", "INTEGRATION_FAILURE", {
                "failed_integration_id": payment_integration["integration_id"],
                "failure_duration_hours": AUTO_SIM_INTEGRATION_FAILURE_DURATION_HOURS,
            }))
        elif payment_step is not None:
            candidates.append(("PAYMENT_FAILURE", "CASCADING_STEP_FAILURE", {
                "origin_step_id": payment_step["step_id"],
                "failure_probability": AUTO_SIM_STEP_FAILURE_PROBABILITY,
            }))

        # -- APPROVAL_DELAY: relevant ONLY if a step's own stored
        # requires_human_judgement/requires_customer_approval flag or
        # its evidence_text indicates a real approval/review stage.
        approval_step = next(
            (s for s in ordered_steps
             if s.get("requires_approval") or _text_has_any(_step_evidence_text(s), AUTO_SIM_APPROVAL_KEYWORDS)),
            None,
        )
        if approval_step is not None:
            candidates.append(("APPROVAL_DELAY", "SLA_BREACH", {
                "breached_step_id": approval_step["step_id"],
                "delay_multiplier": AUTO_SIM_SLA_DELAY_MULTIPLIER,
            }))

        # -- MISSING_DATA: relevant ONLY if a step's own evidence_text
        # indicates a document/data-collection stage.
        document_step = next(
            (s for s in ordered_steps
             if _text_has_any(_step_evidence_text(s), AUTO_SIM_DOCUMENT_KEYWORDS)),
            None,
        )
        if document_step is not None:
            candidates.append(("MISSING_DATA", "CASCADING_STEP_FAILURE", {
                "origin_step_id": document_step["step_id"],
                "failure_probability": AUTO_SIM_STEP_FAILURE_PROBABILITY,
            }))

        # De-duplicate by (scenario_type, real target) -- e.g. a
        # 1-step service would otherwise get STEP_FAILURE, SLA_DELAY
        # AND possibly PAYMENT_FAILURE/MISSING_DATA all naming the
        # exact same (scenario_type, step) pair, which would execute
        # identically. Keep the FIRST (highest-priority, per the fixed
        # order above) label for any (scenario_type, target) already
        # covered rather than emit a duplicate.
        seen = set()
        deduped = []
        for category, scenario_type, variables in candidates:
            target = (
                variables.get("origin_step_id")
                or variables.get("breached_step_id")
                or variables.get("failed_integration_id")
            )
            key = (scenario_type, target)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((category, scenario_type, variables))

        return deduped

    # =================================================================
    # 2. SCENARIO VALIDATION (deterministic -- no LLM)
    # =================================================================

    def validate_scenario(self, scenario_type, variables, service_graph):
        if scenario_type not in SCENARIO_TYPES:
            raise ScenarioValidationError(
                f"Unknown scenario_type '{scenario_type}'. Must be one of: "
                f"{sorted(SCENARIO_TYPES)}."
            )

        required = SCENARIO_TYPES[scenario_type]
        missing = required - set(variables.keys())
        if missing:
            raise ScenarioValidationError(
                f"Missing required variable(s) for {scenario_type}: {sorted(missing)}."
            )

        step_ids = {step["step_id"] for step in service_graph["steps"]}
        integration_ids = {item["integration_id"] for item in service_graph["integrations"]}

        if not service_graph["steps"] and not service_graph["integrations"]:
            # ROOT-CAUSE FIX (service-generic/stage-dependency audit):
            # this is Simulate's OWN missing prerequisite (no stored
            # future_steps/required_integrations for this service yet)
            # -- a structurally different situation from every other
            # ScenarioValidationError below (a caller-supplied
            # scenario_type/variable/reference that's simply wrong).
            # InsufficientDataError gives main.py a stable, structured
            # shape to return instead of a plain string, so a caller
            # can tell "run Analyze first" apart from "your request was
            # invalid" without parsing message text.
            raise InsufficientDataError(
                reason=(
                    "This service has no stored future_steps or "
                    "required_integrations yet, so Simulate has nothing "
                    "to build a scenario graph from."
                ),
                missing_requirement="a completed analysis (future_steps/required_integrations)",
                next_action="Run /api/analyze for this service, then retry.",
            )

        if scenario_type == "VOLUME_SURGE":
            demand_multiplier = self._require_number(variables, "demand_multiplier", minimum=1.0)
            self._require_number(variables, "time_horizon_days", minimum=1.0)
            return {"demand_multiplier": demand_multiplier,
                    "time_horizon_days": float(variables["time_horizon_days"])}

        if scenario_type == "INTEGRATION_FAILURE":
            integration_id = str(variables["failed_integration_id"])
            if integration_id not in integration_ids:
                raise ScenarioValidationError(
                    f"failed_integration_id '{integration_id}' does not exist in this "
                    f"service's stored integrations {sorted(integration_ids)}."
                )
            duration = self._require_number(variables, "failure_duration_hours", minimum=0.0)
            return {"failed_integration_id": integration_id, "failure_duration_hours": duration}

        if scenario_type == "SLA_BREACH":
            step_id = str(variables["breached_step_id"])
            if step_id not in step_ids:
                raise ScenarioValidationError(
                    f"breached_step_id '{step_id}' does not exist in this service's "
                    f"stored steps {sorted(step_ids)}."
                )
            delay_multiplier = self._require_number(variables, "delay_multiplier", minimum=0.0)
            return {"breached_step_id": step_id, "delay_multiplier": delay_multiplier}

        if scenario_type == "CASCADING_STEP_FAILURE":
            step_id = str(variables["origin_step_id"])
            if step_id not in step_ids:
                raise ScenarioValidationError(
                    f"origin_step_id '{step_id}' does not exist in this service's "
                    f"stored steps {sorted(step_ids)}."
                )
            probability = self._require_number(
                variables, "failure_probability", minimum=0.0, maximum=1.0
            )
            return {"origin_step_id": step_id, "failure_probability": probability}

        raise ScenarioValidationError(f"Unhandled scenario_type '{scenario_type}'.")

    def _require_number(self, variables, key, minimum=None, maximum=None):
        try:
            value = float(variables[key])
        except (TypeError, ValueError):
            raise ScenarioValidationError(f"Variable '{key}' must be a number.")
        if minimum is not None and value < minimum:
            raise ScenarioValidationError(f"Variable '{key}' must be >= {minimum}.")
        if maximum is not None and value > maximum:
            raise ScenarioValidationError(f"Variable '{key}' must be <= {maximum}.")
        return value

    # =================================================================
    # 3. DETERMINISTIC EXECUTION -- one pure function per scenario_type
    # =================================================================

    def resolve_sla_baseline_hours(self, step, service_graph):
        """SLA handling audit fix -- the single shared resolution
        logic used by BOTH Simulate's SLA_BREACH execution AND
        Challenge's SLA_STRESS strategy (Challenge delegates to this
        same FutureSimulationAgent, so no separate Challenge-side
        logic is needed or added).

        Priority (real evidence first, invented value last):
          1. STEP_SLA          -- the step's own explicit sla_hours
                                   field, or its own text explicitly
                                   naming an SLA/commitment.
          2. STEP_EXPECTED_DURATION -- the step's own explicit
                                   expected_duration_hours field, or
                                   its own text mentioning a duration
                                   without SLA language.
          3. SERVICE_WAITING_TIME -- the service's own stored
                                   waiting_times text (ServiceInput.
                                   waiting_times), service-wide, used
                                   only when no per-step evidence
                                   exists for THIS step.
          4. ASSUMPTION         -- GENERIC_SLA_HOURS_DEFAULT (48h),
                                   the last resort only, always
                                   returned alongside its own source
                                   label so a caller never mistakes it
                                   for real evidence.

        Returns (hours: float, source: str). Never invents a number
        when real evidence exists -- an explicit field is used
        exactly; a text-derived duration is the largest value
        literally mentioned (see _parse_duration_hours), never
        adjusted or estimated beyond that.
        """
        explicit_sla = step.get("sla_hours")
        if isinstance(explicit_sla, (int, float)) and not isinstance(explicit_sla, bool) and explicit_sla > 0:
            return float(explicit_sla), "STEP_SLA"

        explicit_duration = step.get("expected_duration_hours")
        if isinstance(explicit_duration, (int, float)) and not isinstance(explicit_duration, bool) and explicit_duration > 0:
            return float(explicit_duration), "STEP_EXPECTED_DURATION"

        step_text = _step_evidence_text(step)
        if _text_has_any(step_text, SLA_KEYWORDS):
            parsed = _parse_duration_hours(step_text)
            if parsed:
                return parsed, "STEP_SLA"
        parsed = _parse_duration_hours(step_text)
        if parsed:
            return parsed, "STEP_EXPECTED_DURATION"

        for waiting_time_text in service_graph.get("waiting_times") or []:
            parsed = _parse_duration_hours(waiting_time_text)
            if parsed:
                return parsed, "SERVICE_WAITING_TIME"

        return float(GENERIC_SLA_HOURS_DEFAULT), "ASSUMPTION"

    def _map_integration_to_steps(self, integration, service_graph):
        """Integration-to-Step Mapping audit fix. Returns
        (step_ids: list[str] in service-graph order, source: str)
        where source is "EXPLICIT" (real stored per-step mapping),
        "TEXT_EVIDENCE" (the integration's own stored name appears in
        a step's own stored name/action/detailed_description text --
        real evidence, not a guess), or "ASSUMPTION" (no evidence at
        all -- the pre-existing fallback, preserved byte-for-byte for
        backward compatibility with every record that predates this
        fix, and still honestly labeled as an assumption)."""
        ordered_steps = sorted(service_graph["steps"], key=lambda s: s["order"])

        # Tier 1 -- EXPLICIT: build_service_graph() already validated
        # every id here is a real, currently-stored step.
        explicit_ids = integration.get("step_ids") or []
        if explicit_ids:
            valid_ids = {s["step_id"] for s in ordered_steps}
            mapped = [s["step_id"] for s in ordered_steps if s["step_id"] in explicit_ids and s["step_id"] in valid_ids]
            if mapped:
                return mapped, "EXPLICIT"

        # Tier 2 -- TEXT_EVIDENCE: the integration's own stored name
        # (normalized: underscores/hyphens as spaces, lowercased) shows
        # up in a step's own stored evidence_text. Requires at least 3
        # normalized characters to avoid a trivial/short name matching
        # everything.
        name = str(integration.get("name", "")).strip()
        normalized_name = re.sub(r"[_\-]+", " ", name).strip().lower()
        if len(normalized_name) >= 3:
            matched = [
                s["step_id"] for s in ordered_steps
                if normalized_name in _step_evidence_text(s).lower()
            ]
            if matched:
                return matched, "TEXT_EVIDENCE"

        # Tier 3 -- ASSUMPTION: pre-existing fallback, unchanged.
        fallback = [s["step_id"] for s in ordered_steps if s["type"] in AUTOMATED_STEP_TYPES]
        return fallback, "ASSUMPTION"

    def _execute_integration_failure(self, service_graph, variables):
        failed_id = variables["failed_integration_id"]
        integration = next(
            item for item in service_graph["integrations"]
            if item["integration_id"] == failed_id
        )
        mapped_step_ids, source = self._map_integration_to_steps(integration, service_graph)
        step_lookup = {s["step_id"]: s for s in service_graph["steps"]}
        affected = [
            {"step_id": step_id, "name": step_lookup[step_id]["name"], "status": "DEGRADED"}
            for step_id in mapped_step_ids if step_id in step_lookup
        ]

        if source == "ASSUMPTION":
            # Pre-existing fallback behavior, unchanged for backward
            # compatibility -- clearly marked as an ASSUMPTION exactly
            # as before.
            assumption_notes = [{
                "variable_name": "affected_steps_mapping",
                "value": "all SYSTEM-type steps",
                "reason": (
                    f"No stored per-step mapping or text evidence exists for "
                    f"integration '{integration['name']}'; treating all "
                    f"SYSTEM-type steps as dependent on it."
                ),
            }]
        else:
            # Real, stored evidence drove this -- not an assumption.
            assumption_notes = []

        return affected, assumption_notes

    def _execute_cascading_step_failure(self, service_graph, variables):
        origin_id = variables["origin_step_id"]
        origin = next(s for s in service_graph["steps"] if s["step_id"] == origin_id)
        # Real, stored sequential order (step_number-derived) -- every
        # step at or after the origin's position is blocked by the
        # chain dependency already implicit in "future_steps" order.
        affected = [
            {"step_id": step["step_id"], "name": step["name"], "status": "BLOCKED"}
            for step in service_graph["steps"] if step["order"] >= origin["order"]
        ]
        return affected, []

    def _execute_sla_breach(self, service_graph, variables):
        delay_multiplier = variables["delay_multiplier"]
        if delay_multiplier <= 1.0:
            return [], []  # no delay beyond baseline -> nothing affected, deterministically

        breached_id = variables["breached_step_id"]
        breached = next(s for s in service_graph["steps"] if s["step_id"] == breached_id)
        affected = [{
            "step_id": breached["step_id"], "name": breached["name"], "status": "SLA_VIOLATED",
        }]
        affected += [
            {"step_id": step["step_id"], "name": step["name"], "status": "DELAYED"}
            for step in service_graph["steps"] if step["order"] > breached["order"]
        ]

        # ROOT-CAUSE FIX (SLA handling audit): resolve_sla_baseline_hours()
        # checks real stored evidence first (step SLA -> step expected
        # duration -> service SLA/waiting time) and only falls back to
        # the platform default when none exists anywhere -- see its own
        # docstring for the full priority order. Only the fallback case
        # is marked as an ASSUMPTION; a real, evidence-derived baseline
        # is reported with its own honest source label and is NOT an
        # assumption.
        baseline_hours, source = self.resolve_sla_baseline_hours(breached, service_graph)
        if source == "ASSUMPTION":
            assumption_notes = [{
                "variable_name": "sla_hours_default",
                "value": baseline_hours,
                "reason": (
                    f"No stored per-step or service-level SLA/expected-duration "
                    f"evidence exists for '{breached['name']}'; using the "
                    f"platform default of {baseline_hours:g}h as the baseline "
                    f"being breached."
                ),
            }]
        else:
            assumption_notes = []
        return affected, assumption_notes

    def _execute_volume_surge(self, service_graph, variables):
        demand_multiplier = variables["demand_multiplier"]
        if demand_multiplier < VOLUME_SURGE_DEGRADE_THRESHOLD:
            return [], []  # deterministic threshold -- below it, nothing degrades

        affected = [
            {"step_id": step["step_id"], "name": step["name"], "status": "DEGRADED"}
            for step in service_graph["steps"] if step["type"] in CUSTOMER_FACING_STEP_TYPES
        ]
        assumption_notes = [{
            "variable_name": "capacity_constrained_types",
            "value": sorted(CUSTOMER_FACING_STEP_TYPES),
            "reason": (
                "No stored per-step throughput/capacity data exists; treating "
                "CUSTOMER/HUMAN-type steps as capacity-constrained under surge "
                "by default, since SYSTEM steps are agent-executed and scale."
            ),
        }]
        return affected, assumption_notes

    # =================================================================
    # 4. SCORING -- deterministic, bounded, documented (see module
    #    docstring: engineering scores, not a statistical model)
    # =================================================================

    def _compute_bottlenecks(self, service_graph, affected_steps):
        total = len(service_graph["steps"])
        affected_ids = {item["step_id"] for item in affected_steps}
        bottlenecks = []
        for step in service_graph["steps"]:
            if step["step_id"] not in affected_ids:
                continue
            dependent_count = max(0, total - step["order"] - 1)
            bottlenecks.append({
                "step_id": step["step_id"], "name": step["name"],
                "dependent_count": dependent_count,
            })
        bottlenecks.sort(key=lambda item: -item["dependent_count"])
        return bottlenecks

    def _compute_likelihood(self, scenario_type, variables, linked_prediction):
        """The ONLY numbers allowed to feed likelihood: a directly
        supplied probability variable, an inherited Predict confidence
        (already deterministic), or the single named default constant.
        Never an LLM judgement."""
        prediction_confidence = None
        if linked_prediction is not None:
            # Use the highest confidence among the linked prediction's
            # own (already deterministic) predictions, if any.
            values = [p.get("confidence", 0.0) for p in linked_prediction.get("predictions", [])]
            if values:
                prediction_confidence = _clamp01(max(values))

        if scenario_type == "CASCADING_STEP_FAILURE":
            variable_probability = _clamp01(variables["failure_probability"])
            # BUGFIX (Step 3 audit): a linked Prediction must not be
            # silently discarded just because this scenario_type also
            # carries an explicit failure_probability variable. Use
            # whichever is higher -- the more conservative, worst-case
            # reading for a stress test -- and tag its real source so
            # the choice stays traceable; never blended/averaged.
            if prediction_confidence is not None and prediction_confidence > variable_probability:
                return prediction_confidence, "PREDICTION"
            return variable_probability, "ASSUMPTION_OR_VARIABLE"

        if prediction_confidence is not None:
            return prediction_confidence, "PREDICTION"
        return DEFAULT_MANUAL_LIKELIHOOD, "ASSUMPTION"

    # =================================================================
    # CITIZEN OUTCOME IMPACT (root-cause fix -- "0 of 0 customer-facing
    # steps" must never automatically mean "no citizen impact")
    # =================================================================
    # A zero-customer-step Future Journey (every step SYSTEM/AGENT) is
    # a legitimate design -- citizen_impact's existing customer-facing-
    # step-ratio formula (UNCHANGED below) correctly reports 0 of 0 in
    # that case, and that number is preserved exactly as-is. What was
    # missing is a SEPARATE, additive signal for whether the CITIZEN
    # STILL doesn't get their result -- e.g. every execution step is
    # SYSTEM-only, but one of them fails and blocks the government
    # service from ever completing. This is derived ONLY from evidence
    # this deterministic engine already computed for THIS scenario --
    # a step's own assigned status (BLOCKED/SLA_VIOLATED/DELAYED/
    # DEGRADED, unchanged, see the four _execute_* methods above) and
    # its position in the service's own stored step order -- never a
    # new/invented fact, never an LLM judgement, never a change to
    # which steps get marked affected or what status they get.
    #
    # Evidence -> outcome-affected mapping (deterministic, no
    # invented facts):
    #   - BLOCKED       -> failure cascades and blocks downstream
    #                       execution (CASCADING_STEP_FAILURE's own
    #                       existing semantics -- always outcome-
    #                       affecting).
    #   - SLA_VIOLATED  -> the service's own committed/expected
    #                       completion time is breached at that step.
    #   - DELAYED       -> a downstream step is delayed because an
    #                       earlier one breached its SLA -- completion
    #                       itself is delayed.
    #   - the graph's own LAST step (highest stored order -- the step
    #     that produces/delivers the final result, e.g. "System issues
    #     the permit") is among the affected steps, REGARDLESS of its
    #     status -- if the delivery step itself is affected at all,
    #     the citizen does not cleanly receive their result.
    #   - DEGRADED on any OTHER (non-final) step alone does not, by
    #     itself, mean the final result was ever blocked or delayed --
    #     e.g. an integration mapped (see Integration-to-Step Mapping)
    #     to one earlier, non-final step degrading is a real, narrower
    #     finding that does not get inflated into "the citizen never
    #     got their result."

    def _determine_citizen_outcome_impact(self, service_graph, affected_steps):
        """Returns (citizen_outcome_affected: bool, outcome_impact_reason: str).
        Pure function of already-computed affected_steps + the
        service's own stored step order -- no new stored data read,
        no LLM, no change to affected_steps/status/scores themselves."""
        if not affected_steps:
            return False, "No steps were affected under this scenario."

        ordered_steps = sorted(service_graph["steps"], key=lambda s: s["order"])
        final_step_id = ordered_steps[-1]["step_id"] if ordered_steps else None
        affected_by_id = {item["step_id"]: item for item in affected_steps}

        blocked = [item for item in affected_steps if item["status"] == "BLOCKED"]
        if blocked:
            names = ", ".join(item["name"] or item["step_id"] for item in blocked[:3])
            return True, (
                f"Failure cascades and blocks downstream execution required to "
                f"complete the service (blocked: {names})."
            )

        sla_violated = [item for item in affected_steps if item["status"] == "SLA_VIOLATED"]
        delayed = [item for item in affected_steps if item["status"] == "DELAYED"]
        if sla_violated or delayed:
            basis = sla_violated[0] if sla_violated else delayed[0]
            return True, (
                f"Service completion is delayed -- {basis['name'] or basis['step_id']} "
                f"breaches or inherits a breached SLA on the execution path."
            )

        if final_step_id is not None and final_step_id in affected_by_id:
            final_item = affected_by_id[final_step_id]
            return True, (
                f"The final step that delivers the service outcome to the citizen "
                f"('{final_item['name'] or final_step_id}') is itself affected "
                f"({final_item['status']}), so the result is not cleanly delivered."
            )

        return False, (
            "The affected step(s) are degraded but do not block, delay, or reach "
            "the final step that delivers the service outcome to the citizen."
        )

    def _compute_scores(self, service_graph, affected_steps, likelihood):
        total_customer_facing = sum(
            1 for s in service_graph["steps"] if s["type"] in CUSTOMER_FACING_STEP_TYPES
        )
        total_system = sum(
            1 for s in service_graph["steps"] if s["type"] in AUTOMATED_STEP_TYPES
        )
        total_integrations = len(service_graph["integrations"])

        affected_ids = {item["step_id"] for item in affected_steps}
        affected_customer_facing = sum(
            1 for s in service_graph["steps"]
            if s["step_id"] in affected_ids and s["type"] in CUSTOMER_FACING_STEP_TYPES
        )
        affected_system = sum(
            1 for s in service_graph["steps"]
            if s["step_id"] in affected_ids and s["type"] in AUTOMATED_STEP_TYPES
        )
        # No per-step integration mapping exists, so affected-integration
        # ratio is approximated as 1.0 whenever any SYSTEM step is
        # affected (an integration-dependent step is affected), else 0.
        affected_integration_ratio = 1.0 if affected_system > 0 and total_integrations > 0 else 0.0

        citizen_impact_ratio = affected_customer_facing / max(1, total_customer_facing)
        system_ratio = affected_system / max(1, total_system)

        # ZERO X-RAY SIMULATION RISK/IMPACT SCORE -- deterministic
        # engineering ratio, bounded 0-100 by clamp(), NOT a
        # statistically validated forecast.
        citizen_impact_score = clamp(100 * citizen_impact_ratio * likelihood)
        government_impact_score = clamp(
            100 * (
                GOVERNMENT_IMPACT_STEP_WEIGHT * system_ratio
                + GOVERNMENT_IMPACT_INTEGRATION_WEIGHT * affected_integration_ratio
            ) * likelihood
        )
        overall_risk_score = clamp((citizen_impact_score + government_impact_score) / 2)

        return {
            "citizen_impact": {
                "score": round(citizen_impact_score, 2),
                "basis": (
                    f"{affected_customer_facing} of {total_customer_facing} customer-facing "
                    f"step(s) affected, scaled by likelihood {round(likelihood, 2)}"
                ),
            },
            "government_impact": {
                "score": round(government_impact_score, 2),
                "basis": (
                    f"{affected_system} of {total_system} system step(s) and "
                    f"{'an' if affected_integration_ratio else 'no'} affected integration, "
                    f"scaled by likelihood {round(likelihood, 2)}"
                ),
            },
            "overall_risk_score": round(overall_risk_score, 2),
        }

    # =================================================================
    # 5. LLM-PHRASED OUTCOME DESCRIPTION ONLY -- validated
    # =================================================================

    def _template_description(self, scenario_type, affected_steps, scores):
        if not affected_steps:
            if self.lang == "ar":
                return f"في سيناريو {scenario_type}، لم تستوفِ أي خطوة محفوظة الحد المطلوب لاعتبارها متأثرة."
            return (
                f"Under this {scenario_type} scenario, no stored steps met the "
                f"threshold to be marked affected."
            )
        names = ", ".join(item["name"] or item["step_id"] for item in affected_steps[:5])
        if self.lang == "ar":
            more = f" و{len(affected_steps) - 5} أخرى" if len(affected_steps) > 5 else ""
            return (f"في سيناريو {scenario_type}، تأثرت {len(affected_steps)} خطوة ({names}{more}). "
                    f"درجة المخاطر الكلية: {scores['overall_risk_score']} (درجة محاكاة حتمية من ZERO X-RAY وليست توقعًا إحصائيًا).")
        more = f" and {len(affected_steps) - 5} more" if len(affected_steps) > 5 else ""
        return (
            f"Under this {scenario_type} scenario, {len(affected_steps)} step(s) are "
            f"affected ({names}{more}). Overall risk score: "
            f"{scores['overall_risk_score']} (deterministic ZERO X-RAY simulation score, "
            f"not a statistical forecast)."
        )

    def _validate_llm_description(self, text, affected_steps, scores):
        if not text or not text.strip() or len(text) > 800:
            return False
        if is_placeholder_or_generic(text):
            return False
        allowed_numbers = {len(affected_steps), scores["overall_risk_score"],
                            scores["citizen_impact"]["score"], scores["government_impact"]["score"]}
        claimed_numbers = {
            float(match) for match in re.findall(r"\d+(?:\.\d+)?", text)
        }
        # Every number the LLM states must match a real computed number
        # (small integers like counts, or the exact scores) -- anything
        # else is treated as fabrication and rejected.
        for number in claimed_numbers:
            if number in allowed_numbers:
                continue
            if number == int(number) and number <= len(affected_steps):
                continue  # a small in-range count is plausible phrasing, not a new fact
            return False
        return True

    def _generate_description(self, scenario_type, affected_steps, scores):
        template = self._template_description(scenario_type, affected_steps, scores)
        if self.llm is None:
            return template, "template"
        try:
            system_prompt = (
                "You rephrase an already-computed simulation result into one "
                "natural sentence for a government analyst. Do not invent any "
                "new number, step name, or score not given to you."
            )
            user_prompt = (
                f"Scenario type: {scenario_type}\n"
                f"Affected step count: {len(affected_steps)}\n"
                f"Overall risk score: {scores['overall_risk_score']}\n"
                f"Citizen impact score: {scores['citizen_impact']['score']}\n"
                f"Government impact score: {scores['government_impact']['score']}\n"
                "Write one clear sentence summarizing this. Do not add new numbers."
            )
            if self.lang == "ar":
                user_prompt += "\nWrite the explanation in Arabic. Keep enum values, field names, identifiers, and technical IDs unchanged."
            raw = self.llm.generate(system_prompt, user_prompt, max_new_tokens=180,
                                     temperature=0, timeout=30)
        except Exception:
            return template, "template"

        candidate = extract_clean_explanation(raw)
        if candidate and self._validate_llm_description(candidate, affected_steps, scores):
            return candidate, "ai"
        return template, "template"

    # =================================================================
    # 6. TOP-LEVEL ENTRY POINT
    # =================================================================

    def run(self, scenario_type, variables, service_graph, linked_prediction=None,
            generate_description=True):
        """`variables` must already be the validated dict returned by
        validate_scenario(). `linked_prediction` is the stored
        PredictionResult dict when trigger_type=PREDICTION, else None.

        generate_description (root-cause fix -- Challenge hanging):
        defaults to True, which is the exact previous behavior for
        every existing caller (the /scenarios endpoint's own single
        what-if run still always gets an LLM-phrased description when
        an LLM is configured -- UNCHANGED). Pass False only when the
        caller has no use for a per-run description at all: Challenge
        (agents/challenge_agent.py) executes this method once per
        generated case -- often dozens of cases -- purely to read
        `affected_steps`/`bottlenecks`/scores; it builds its own
        separate, already-validated explanations later, only for the
        top-K RANKED vulnerabilities (see
        ChallengeAgent._generate_explanation). The per-case
        `possible_outcomes[0].description` this method would otherwise
        compute was never read by Challenge at all, yet still made one
        full LLM call per case -- e.g. 20+ cases x up to a ~30s-plus
        Ollama round trip each, run strictly sequentially, is exactly
        the reported "Challenge appears frozen" symptom. Skipping it
        removes that dead work with zero effect on any number, status,
        or ranking Challenge produces, since none of that ever reads
        this field."""

        executors = {
            "INTEGRATION_FAILURE": self._execute_integration_failure,
            "CASCADING_STEP_FAILURE": self._execute_cascading_step_failure,
            "SLA_BREACH": self._execute_sla_breach,
            "VOLUME_SURGE": self._execute_volume_surge,
        }
        affected_steps, rule_assumptions = executors[scenario_type](service_graph, variables)
        bottlenecks = self._compute_bottlenecks(service_graph, affected_steps)
        likelihood, likelihood_source = self._compute_likelihood(
            scenario_type, variables, linked_prediction
        )
        scores = self._compute_scores(service_graph, affected_steps, likelihood)
        citizen_outcome_affected, outcome_impact_reason = self._determine_citizen_outcome_impact(
            service_graph, affected_steps
        )
        if generate_description:
            description, description_source = self._generate_description(
                scenario_type, affected_steps, scores
            )
        else:
            # No LLM call at all -- see the generate_description
            # docstring note above. Still a real, honestly-labeled
            # template description (never blank), it is just never
            # read by a caller that opts out (Challenge).
            description = self._template_description(scenario_type, affected_steps, scores)
            description_source = "template"

        fact_count = len(affected_steps) + len(bottlenecks)
        prediction_count = 1 if likelihood_source == "PREDICTION" else 0
        assumption_count = len(rule_assumptions) + (
            1 if likelihood_source in {"ASSUMPTION", "ASSUMPTION_OR_VARIABLE"} else 0
        )

        generated_at = _now_iso()
        ai_used = description_source == "ai"
        evidence_refs = [service_graph.get("source_analysis_id")] if service_graph.get("source_analysis_id") else []
        return {
            "generated_at": generated_at,
            "provenance": provenance_for_mixed_result(llm_present=self.llm is not None, ai_used=ai_used, evidence_references=evidence_refs, generated_at=generated_at),
            "affected_steps": affected_steps,
            "bottlenecks": bottlenecks,
            "citizen_impact": scores["citizen_impact"],
            "government_impact": scores["government_impact"],
            "overall_risk_score": scores["overall_risk_score"],
            # ADDITIVE (citizen/outcome impact audit fix): whether the
            # FINAL service outcome delivered to the citizen is
            # affected -- separate from citizen_impact's own unchanged
            # direct-customer-facing-step ratio above, which correctly
            # stays 0 for a zero-customer-step service design. See
            # _determine_citizen_outcome_impact()'s own docstring for
            # the exact evidence rule.
            "citizen_outcome_affected": citizen_outcome_affected,
            "outcome_impact_reason": outcome_impact_reason,
            "likelihood": round(likelihood, 2),
            "likelihood_source": likelihood_source,
            "possible_outcomes": [{
                "outcome_id": "OUTCOME-001",
                "likelihood": round(likelihood, 2),
                "description": description,
                "description_source": description_source,
            }],
            "assumptions": rule_assumptions,
            "grounding_summary": {
                "fact_count": fact_count,
                "prediction_count": prediction_count,
                "assumption_count": assumption_count,
            },
            "score_methodology": SCORE_METHODOLOGY_MARKER,
        }
