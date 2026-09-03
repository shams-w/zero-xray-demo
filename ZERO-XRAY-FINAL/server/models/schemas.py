from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ProtectedStep(BaseModel):
    step_number: int = Field(ge=1, le=500)
    level: Literal["REQUIREMENT", "HUMAN", "AS_IS"] = "REQUIREMENT"
    reason: str = Field(default="", max_length=1_000)
    source_reference: str = Field(default="", max_length=500)


class ServiceInput(BaseModel):
    service_name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=100_000)

    # Optional owner-supplied hints. Explicit policy always wins over detection.
    service_type: Optional[Literal[
        "APPLICATION",
        "COMPLAINT",
        "DISPUTE_REFUND",
        "INFORMATION",
        "PURCHASE",
        "RENEWAL",
    ]] = None
    payment_requirement: Optional[Literal[
        "REQUIRED",
        "NOT_REQUIRED",
        "REFUND_OR_DISPUTE",
        "UNKNOWN",
    ]] = None

    steps: List[str] = Field(default_factory=list)
    documents: List[str] = Field(default_factory=list)
    actors: List[str] = Field(default_factory=list)
    approvals: List[str] = Field(default_factory=list)
    waiting_times: List[str] = Field(default_factory=list)
    manual_actions: List[str] = Field(default_factory=list)
    digital_actions: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    branch_visits: int = Field(default=0, ge=0, le=100)

    blueprint_id: Optional[str] = Field(default=None, max_length=100)
    service_id: Optional[str] = Field(default=None, max_length=100)
    data_source_ids: List[str] = Field(default_factory=list, max_length=100)
    integration_ids: List[str] = Field(default_factory=list, max_length=100)
    protected_steps: List[ProtectedStep] = Field(default_factory=list, max_length=500)
    lang: Literal["en", "ar"] = "en"

    @field_validator(
        "steps",
        "documents",
        "actors",
        "approvals",
        "waiting_times",
        "manual_actions",
        "digital_actions",
        "dependencies",
    )
    @classmethod
    def validate_text_lists(cls, values):
        if len(values) > 500:
            raise ValueError("A service field cannot contain more than 500 items.")
        if any(len(str(item)) > 5_000 for item in values):
            raise ValueError("A service item cannot exceed 5,000 characters.")
        return values


class AnalysisResponse(BaseModel):
    service_name: str
    service_analysis: Dict[str, Any]
    relevant_standards: Dict[str, Any]
    gaps: Dict[str, Any]
    zero_bureaucracy_findings: Dict[str, Any]
    redesign: Dict[str, Any]
    simulation: Dict[str, Any]
    validation: Dict[str, Any]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    iterations: int = 0


class CustomerRegistration(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    blueprint_id: Optional[str] = Field(default=None, max_length=100)
    service_id: Optional[str] = Field(default=None, max_length=100)
    data_source_ids: List[str] = Field(default_factory=list, max_length=100)
    integration_ids: List[str] = Field(default_factory=list, max_length=100)


class JourneyStart(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    intent: str = Field(min_length=1, max_length=5_000)
    blueprint_id: Optional[str] = Field(default=None, max_length=100)
    service_id: Optional[str] = Field(default=None, max_length=100)
    data_source_ids: List[str] = Field(default_factory=list, max_length=100)
    integration_ids: List[str] = Field(default_factory=list, max_length=100)
    lang: Literal["en", "ar"] = "en"
    sandbox: bool = True


class PlanEdit(BaseModel):
    instruction: str = Field(default="", max_length=5_000)
    selections: Optional[Dict[str, Any]] = None


class SandboxPayment(BaseModel):
    payment_method: Literal[
        "SANDBOX_CARD",
        "SANDBOX_BANK_TRANSFER",
        "SANDBOX_APPLE_PAY",
        "SANDBOX_GOOGLE_PAY",
        "SANDBOX_SAMSUNG_PAY",
    ] = "SANDBOX_CARD"
    approved: bool = True


# =====================================================================
# PREDICT (Step 1 of the ZERO X-RAY -> Government Future Engine
# evolution -- additive only, does not affect any model above).
# =====================================================================

class PredictionSignal(BaseModel):
    source: Literal["gap", "friction_point", "journey_intent"]
    reference_id: str
    detail: str = Field(default="", max_length=2_000)


class PredictionItem(BaseModel):
    prediction_id: str
    prediction_type: Literal["EVIDENCE_BASED", "MODEL_INFERRED"]
    statement: str
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_basis: str
    signals: List[PredictionSignal] = Field(default_factory=list)
    explanation: str
    explanation_source: Literal["template", "ai"] = "template"
    recommendation: Optional[str] = None


class DataSufficiency(BaseModel):
    analyses_count: int
    journeys_count: int
    verdict: Literal["SUFFICIENT", "LIMITED", "INSUFFICIENT"]


# Additive, backward-compatible marker (Step 3 audit fix #2): makes
# explicit, in the API response itself, that confidence/likelihood/
# impact/risk fields below are deterministic engineering heuristics or
# evidence-derived ratios -- never calibrated statistical
# probabilities. Does not rename or change any existing field/value.
class ScoreMethodology(BaseModel):
    kind: Literal["ZERO_XRAY_ENGINEERING_HEURISTIC"] = "ZERO_XRAY_ENGINEERING_HEURISTIC"
    statistically_validated: bool = False
    note: str = (
        "confidence/likelihood/impact/risk values in this result are "
        "deterministic evidence-derived ratios or named engineering "
        "default constants, not calibrated statistical probabilities."
    )


class PredictionResult(BaseModel):
    service_id: str
    generated_at: str
    predictions: List[PredictionItem] = Field(default_factory=list)
    data_sufficiency: DataSufficiency
    score_methodology: ScoreMethodology = Field(default_factory=ScoreMethodology)


# =====================================================================
# FUTURE SIMULATION (Step 2 of the ZERO X-RAY -> Government Future
# Engine evolution -- additive only, does not affect any model above).
# =====================================================================

class ScenarioCreateRequest(BaseModel):
    lang: Literal["en", "ar"] = "en"
    # Optional: when trigger_type=PREDICTION and this is omitted, it is
    # derived deterministically from the linked prediction (see
    # FutureSimulationAgent.derive_scenario_from_prediction). Required
    # (enforced at the endpoint) when trigger_type=MANUAL, unchanged
    # from prior behavior. Never required for trigger_type=AUTO (see
    # below).
    scenario_type: Optional[Literal[
        "VOLUME_SURGE", "INTEGRATION_FAILURE", "SLA_BREACH", "CASCADING_STEP_FAILURE",
    ]] = None
    # ROOT-CAUSE FIX (Section 2 audit): "AUTO" added -- purely additive,
    # does not change the meaning or required fields of "PREDICTION" or
    # "MANUAL" for any caller that already supplies what those modes
    # always required. Clicking "Run Simulation" with no manual input
    # and no prediction now has an explicit, self-describing trigger_type
    # to ask for instead of overloading "MANUAL"/"PREDICTION" with no
    # scenario_type/prediction_id (which used to 400 -- see main.py's
    # create_scenario for the exact, narrow compatibility fallback that
    # also covers callers still sending the old shapes).
    trigger_type: Literal["PREDICTION", "MANUAL", "AUTO"]
    prediction_id: Optional[str] = Field(default=None, max_length=100)
    variables: Dict[str, Any] = Field(default_factory=dict)



class AffectedStep(BaseModel):
    step_id: str
    name: str
    status: Literal["BLOCKED", "DELAYED", "DEGRADED", "SLA_VIOLATED"]


class Bottleneck(BaseModel):
    step_id: str
    name: str
    dependent_count: int


class ImpactScore(BaseModel):
    score: float = Field(ge=0.0, le=100.0)
    basis: str


class PossibleOutcome(BaseModel):
    outcome_id: str
    likelihood: float = Field(ge=0.0, le=1.0)
    description: str
    description_source: Literal["template", "ai"] = "template"


class ScenarioAssumption(BaseModel):
    variable_name: str
    value: Any
    reason: str


class GroundingSummary(BaseModel):
    fact_count: int
    prediction_count: int
    assumption_count: int


class SimulationOutput(BaseModel):
    generated_at: str
    affected_steps: List[AffectedStep] = Field(default_factory=list)
    bottlenecks: List[Bottleneck] = Field(default_factory=list)
    citizen_impact: ImpactScore
    government_impact: ImpactScore
    overall_risk_score: float = Field(ge=0.0, le=100.0)
    likelihood: float = Field(ge=0.0, le=1.0)
    likelihood_source: Literal["PREDICTION", "ASSUMPTION", "ASSUMPTION_OR_VARIABLE"]
    possible_outcomes: List[PossibleOutcome] = Field(default_factory=list)
    assumptions: List[ScenarioAssumption] = Field(default_factory=list)
    grounding_summary: GroundingSummary
    score_methodology: ScoreMethodology = Field(default_factory=ScoreMethodology)


# =====================================================================
# CHALLENGE (Step 3 of the ZERO X-RAY -> Government Future Engine
# evolution -- additive only, does not affect any model above).
# =====================================================================

class ChallengeCreateRequest(BaseModel):
    lang: Literal["en", "ar"] = "en"
    strategies: List[Literal[
        "EXHAUSTIVE_STEP_FAILURE", "EXHAUSTIVE_INTEGRATION_FAILURE",
        "SLA_STRESS", "DEMAND_STRESS",
    ]] = Field(default_factory=list)  # empty = run all 4
    prediction_id: Optional[str] = Field(default=None, max_length=100)


class ChallengeCaseSummary(BaseModel):
    case_id: str
    strategy: str
    scenario_type: str
    target: Optional[str] = None
    overall_risk_score: float


class ChallengeEvidence(BaseModel):
    type: Literal["FACT", "PREDICTION", "ASSUMPTION"]
    reference_id: str
    detail: str


class Vulnerability(BaseModel):
    vulnerability_id: str
    vulnerability_type: Literal[
        "SINGLE_POINT_OF_FAILURE", "CASCADING_FAILURE_PATH",
        "SLA_FRAGILITY", "DEMAND_FRAGILITY",
        "CRITICAL_PATH_EXPOSURE", "CUSTOMER_FACING_EXPOSURE",
    ]
    target: Optional[str] = None
    source_case_ids: List[str] = Field(default_factory=list)
    severity: float = Field(ge=0.0, le=100.0)
    severity_basis: str
    evidence: List[ChallengeEvidence] = Field(default_factory=list)
    explanation: str
    explanation_source: Literal["template", "ai"] = "template"


class ChallengeOutput(BaseModel):
    generated_at: str
    cases_executed: List[ChallengeCaseSummary] = Field(default_factory=list)
    vulnerabilities: List[Vulnerability] = Field(default_factory=list)
    grounding_summary: GroundingSummary
    score_methodology: ScoreMethodology = Field(default_factory=ScoreMethodology)


# =====================================================================
# EVOLVE (Step 4 of the ZERO X-RAY -> Government Future Engine
# evolution -- additive only, does not affect any model above).
# =====================================================================

class EvolveCreateRequest(BaseModel):
    lang: Literal["en", "ar"] = "en"
    challenge_id: str = Field(min_length=1, max_length=100)


class EvolutionProposal(BaseModel):
    proposal_id: str
    evolution_type: Literal[
        "ADD_REDUNDANCY", "DECOUPLE_DEPENDENCY", "ADD_SLA_SAFEGUARD",
        "ADD_CAPACITY_BUFFER", "ADD_CITIZEN_SAFEGUARD",
    ]
    fixes_vulnerability_id: str
    target: str
    current_state: str
    proposed_state: str
    protected: bool
    exposure_before: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    exposure_after_estimate: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    exposure_calculation_basis: Optional[str] = None
    grounding: List[ChallengeEvidence] = Field(default_factory=list)
    explanation: str
    explanation_source: Literal["template", "ai"] = "template"


class SkippedVulnerability(BaseModel):
    vulnerability_id: str
    reason: str


class EvolveOutput(BaseModel):
    generated_at: str
    challenge_id: str
    proposals: List[EvolutionProposal] = Field(default_factory=list)
    skipped_vulnerabilities: List[SkippedVulnerability] = Field(default_factory=list)
    score_methodology: ScoreMethodology = Field(default_factory=ScoreMethodology)


# =====================================================================
# PREVENT (Step 5 of the ZERO X-RAY -> Government Future Engine
# evolution -- additive only, does not affect any model above).
# =====================================================================

class PreventCreateRequest(BaseModel):
    lang: Literal["en", "ar"] = "en"
    evolution_id: str = Field(min_length=1, max_length=100)


class PreventionTrigger(BaseModel):
    trigger_id: str
    trigger_type: Literal["CHALLENGE_RECURRENCE_TRIGGER", "PREDICTION_EARLY_WARNING_TRIGGER"]
    source_proposal_id: str
    source_vulnerability_id: str
    watch_metric: Literal["challenge_severity", "prediction_confidence"]
    watch_scope: str
    threshold_value: float
    threshold_basis: str
    action_if_triggered: str
    protected: bool
    status: Literal["DEFINED"] = "DEFINED"
    grounding: List[ChallengeEvidence] = Field(default_factory=list)
    explanation: str
    explanation_source: Literal["template", "ai"] = "template"


class SkippedProposal(BaseModel):
    proposal_id: str
    reason: str


class PreventOutput(BaseModel):
    generated_at: str
    evolution_id: str
    triggers: List[PreventionTrigger] = Field(default_factory=list)
    skipped_proposals: List[SkippedProposal] = Field(default_factory=list)
    score_methodology: ScoreMethodology = Field(default_factory=ScoreMethodology)


# =====================================================================
# MONITORING / ALERTS (Step 8 of the ZERO X-RAY -> Government Future
# Engine evolution -- additive only, does not affect any model above).
#
# An Alert is only ever a STORED RECORD of a real, re-checked threshold
# breach or recovery -- it never claims to have been sent anywhere
# external (no email/SMS/webhook integration exists).
# =====================================================================

class MonitoringCheckRequest(BaseModel):
    lang: Literal["en", "ar"] = "en"
    prevention_id: str = Field(min_length=1, max_length=100)


class MonitoringScheduleUpdateRequest(BaseModel):
    enabled: bool
    frequency: Literal["hourly", "daily"] = "daily"


class Alert(BaseModel):
    id: str
    tenant_id: str
    service_id: str
    prevention_id: str
    trigger_id: str
    status: Literal["TRIGGERED", "RESOLVED"]
    current_value: Optional[float] = None
    threshold_value: float
    checked_against: Optional[str] = None
    evidence: str
    created_at: str
    updated_at: str
    resolved_at: Optional[str] = None


class TriggerCheckResult(BaseModel):
    trigger_id: str
    watch_metric: Literal["challenge_severity", "prediction_confidence"]
    threshold_value: float
    current_value: Optional[float] = None
    breached: bool
    checked_against: Optional[str] = None
    evidence: str
    alert_action: Literal["CREATED", "ALREADY_OPEN", "RESOLVED", "NO_ALERT"]
    alert: Optional[Alert] = None


class MonitoringCheckOutput(BaseModel):
    prevention_id: str
    service_id: str
    generated_at: str
    checks: List[TriggerCheckResult] = Field(default_factory=list)
    score_methodology: ScoreMethodology = Field(default_factory=ScoreMethodology)
