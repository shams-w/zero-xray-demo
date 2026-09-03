"""Service-Agnostic Government Service Re-engineering Framework.

This module is the single source of truth for the FIXED framework the
engine applies to ANY government service it is given — not just the 9
services shipped in this repository as Demo/Validation Cases (see
core/service_classifier.py -> DEMO_VALIDATION_PROFILES).

The framework has two parts:

1. INTAKE — every service, regardless of domain, is understood along the
   same 9 dimensions (build_framework_intake()).
2. DECISIONS — every current step, regardless of the service it belongs
   to, is classified along the same 8 decision categories
   (map_decision_to_categories()), each carrying a plain-language
   explanation of why the step was kept/removed/automated and what, if
   anything, replaces it (build_explanation()).

Nothing in this file references a specific service by name. Adding a
new, previously-unseen service requires no change here: the same
functions run over whatever the upstream agents (ServiceAnalystAgent,
StandardsAgent, JourneyBuilderAgent, ...) already extracted.
"""

# ---------------------------------------------------------------------------
# 1. INTAKE FRAMEWORK — fixed set of dimensions every service is read into
# ---------------------------------------------------------------------------

INTAKE_DIMENSIONS = [
    "goal",
    "actors",
    "inputs_and_data",
    "documents",
    "systems_and_integrations",
    "rules",
    "fees",
    "approvals",
    "exceptions",
]

INTAKE_DIMENSION_LABELS = {
    "en": {
        "goal": "Service Goal / Outcome",
        "actors": "Actors",
        "inputs_and_data": "Inputs & Data",
        "documents": "Documents",
        "systems_and_integrations": "Systems & Integrations",
        "rules": "Rules",
        "fees": "Fees",
        "approvals": "Approvals",
        "exceptions": "Exceptions",
    },
    "ar": {
        "goal": "هدف/نتيجة الخدمة",
        "actors": "الأطراف المعنية",
        "inputs_and_data": "المدخلات والبيانات",
        "documents": "المستندات",
        "systems_and_integrations": "الأنظمة والتكاملات",
        "rules": "القواعد",
        "fees": "الرسوم",
        "approvals": "الموافقات",
        "exceptions": "الاستثناءات",
    },
}


def build_framework_intake(service, service_analysis, relevant_standards, classification, gaps=None):
    """Read ANY service into the fixed 9-dimension intake shape.

    Every field below is assembled purely from what the upstream,
    service-agnostic agents already extracted (ServiceAnalystAgent,
    StandardsAgent, GapAnalysisAgent, service_classifier). No branch here
    checks a service name, so this works identically on the 9 shipped
    demo services and on a service the engine has never seen before.
    """

    service = service or {}
    service_analysis = service_analysis or {}
    relevant_standards = relevant_standards or {}
    classification = classification or {}
    gaps = gaps or {}

    capabilities = service_analysis.get("capabilities", {}) or {}

    return {
        "goal": {
            "outcome": service_analysis.get("objective") or service.get("description", ""),
            "service_archetype": classification.get("service_archetype"),
            "archetype_evidence": classification.get("archetype_evidence", ""),
        },
        "actors": {
            "listed": service_analysis.get("actors", []) or service.get("actors", []),
            "customer_touchpoints": service_analysis.get("customer_touchpoints", []),
        },
        "inputs_and_data": {
            "current_steps": service_analysis.get("steps", []),
            "dependencies": service_analysis.get("dependencies", []),
            "digital_actions": service_analysis.get("digital_actions", []),
        },
        "documents": {
            "required": service_analysis.get("documents", []),
            "evidence": capabilities.get("documents_evidence", ""),
        },
        "systems_and_integrations": {
            "digital_actions": service_analysis.get("digital_actions", []),
            "manual_actions": service_analysis.get("manual_actions", []),
        },
        "rules": {
            "applicable_standards": relevant_standards.get("applicable_standards", []),
        },
        "fees": {
            "requires_customer_payment": classification.get("requires_customer_payment"),
            "payment_context": classification.get("payment_context"),
            "payment_evidence": classification.get("payment_evidence", ""),
            "fee_model": classification.get("fee_model"),
        },
        "approvals": {
            "listed": service_analysis.get("approvals", []),
            "requires_human_decision": classification.get("requires_human_decision"),
        },
        "exceptions": {
            "friction_points": service_analysis.get("friction_points", []),
            "gaps": gaps.get("gaps", []),
        },
    }


# ---------------------------------------------------------------------------
# 2. DECISION FRAMEWORK — fixed set of categories every current step maps to
# ---------------------------------------------------------------------------

DECISION_CATEGORIES = [
    "DUPLICATE",
    "UNNECESSARY",
    "GOVERNMENT_KNOWN_DATA",
    "AUTOMATABLE",
    "API_INTEGRATION_OPPORTUNITY",
    "AGENT_EXECUTABLE",
    "HUMAN_REQUIRED",
    "LEGAL_COMPLIANCE_REQUIRED",
]

DECISION_CATEGORY_LABELS = {
    "en": {
        "DUPLICATE": "Duplicate",
        "UNNECESSARY": "Unnecessary",
        "GOVERNMENT_KNOWN_DATA": "Government-known Data",
        "AUTOMATABLE": "Automatable",
        "API_INTEGRATION_OPPORTUNITY": "API / Integration Opportunity",
        "AGENT_EXECUTABLE": "Agent Executable",
        "HUMAN_REQUIRED": "Human Required",
        "LEGAL_COMPLIANCE_REQUIRED": "Legal / Compliance Required",
    },
    "ar": {
        "DUPLICATE": "مكررة",
        "UNNECESSARY": "غير ضرورية",
        "GOVERNMENT_KNOWN_DATA": "بيانات معروفة حكوميًا",
        "AUTOMATABLE": "قابلة للأتمتة",
        "API_INTEGRATION_OPPORTUNITY": "فرصة تكامل / API",
        "AGENT_EXECUTABLE": "قابلة لتنفيذ الـAgent",
        "HUMAN_REQUIRED": "تتطلب تدخل بشري",
        "LEGAL_COMPLIANCE_REQUIRED": "تتطلب امتثالًا قانونيًا",
    },
}

# Legacy step-level decision codes already produced by StepComplianceAgent /
# JourneyBuilderAgent (KEEP, MERGE, AUTOMATE, REMOVE, REVIEW). This maps them onto
# the richer, fixed 8-category framework using only the decision code and
# generic text signals in the reason — never a service name — so it applies
# to any current or future service.
_REASON_SIGNALS = {
    "DUPLICATE": [
        "duplicate", "repeated", "re-enter", "reenter", "already provided",
        "already collected", "same data", "مكرر", "مكررة", "نفس البيانات",
        "إعادة إدخال",
    ],
    "GOVERNMENT_KNOWN_DATA": [
        "government-known", "already held by government", "national id",
        "registry", "already on file", "known to government",
        "بيانات حكومية", "متوفرة لدى الحكومة", "الهوية الوطنية",
    ],
    "LEGAL_COMPLIANCE_REQUIRED": [
        "legal", "policy", "compliance", "regulation", "statutory",
        "security", "mandated", "قانون", "امتثال", "تنظيم", "إلزامي",
    ],
    "HUMAN_REQUIRED": [
        "human", "manual review", "committee", "notary", "supervisor",
        "case officer", "investigation", "judgement",
        "بشري", "مراجعة يدوية", "لجنة", "كاتب العدل", "تحقيق",
    ],
    "API_INTEGRATION_OPPORTUNITY": [
        "integration", "connect", "api", "system-to-system", "connected system",
        "تكامل", "ربط", "نظام متصل",
    ],
}


def map_decision_to_categories(decision, reason="", status=""):
    """Map a step-level decision (+ its free-text reason) to one or more of
    the 8 fixed framework categories. Works for any service because it only
    looks at the decision code and generic reason vocabulary.
    """

    decision = str(decision or "").strip().upper()
    reason_lower = str(reason or "").lower()
    status = str(status or "").strip().upper()

    categories = set()

    if decision == "REMOVE":
        categories.add("UNNECESSARY")
    elif decision == "MERGE":
        categories.add("DUPLICATE")
    elif decision == "AUTOMATE":
        categories.add("AUTOMATABLE")
        categories.add("AGENT_EXECUTABLE")
    elif decision == "REVIEW":
        categories.add("HUMAN_REQUIRED")
    elif decision == "KEEP":
        categories.add("LEGAL_COMPLIANCE_REQUIRED")

    for category, signals in _REASON_SIGNALS.items():
        if any(signal in reason_lower for signal in signals):
            categories.add(category)

    if status == "FAIL":
        categories.add("LEGAL_COMPLIANCE_REQUIRED")

    if not categories:
        categories.add("AGENT_EXECUTABLE" if decision == "AUTOMATE" else "HUMAN_REQUIRED")

    # Stable, deterministic ordering matching DECISION_CATEGORIES.
    return [category for category in DECISION_CATEGORIES if category in categories]


# Generic gap-category -> framework decision-category signal. Gaps never
# carry a KEEP/REMOVE/AUTOMATE decision code (that vocabulary is
# step-level, from StepComplianceAgent), so a gap is classified from its
# own "category" label plus free-text reason using the same
# service-agnostic _REASON_SIGNALS matcher map_decision_to_categories
# already uses, with a light default per known gap category so every
# gap still resolves to at least one framework category even with no
# text-signal match.
_GAP_CATEGORY_DEFAULTS = {
    "Manual Work": "AUTOMATABLE",
    "Waiting": "AUTOMATABLE",
    "Approval Review": "HUMAN_REQUIRED",
    "Branch Visit": "AUTOMATABLE",
}


def classify_gap(gap):
    """Map a single gap (as produced by GapAnalysisAgent, either the AI
    or the deterministic baseline path) onto the same fixed 8-category
    framework used for current-journey steps. Purely generic: reads
    only the gap's own category/description/recommendation text, never
    a service name, so it works for any gap on any service.
    """
    gap = gap or {}
    category_label = str(gap.get("category", "")).strip()
    reason_text = " ".join(
        str(gap.get(field, ""))
        for field in ("description", "recommendation", "expected_impact")
    ).lower()

    categories = set()
    for framework_category, signals in _REASON_SIGNALS.items():
        if any(signal in reason_text for signal in signals):
            categories.add(framework_category)

    if not categories:
        default = _GAP_CATEGORY_DEFAULTS.get(category_label)
        if default:
            categories.add(default)

    if str(gap.get("severity", "")).strip().upper() == "HIGH":
        categories.add("LEGAL_COMPLIANCE_REQUIRED")

    if not categories:
        categories.add("AGENT_EXECUTABLE")

    return [category for category in DECISION_CATEGORIES if category in categories]


def build_explanation(step_text, decision, reason, alternative=""):
    """Return the mandatory 'why + what replaces it' explanation for a
    single step-level decision. `alternative` is whatever the redesign
    already names as the replacement (an automation, an API call, a
    government-known-data lookup, ...); when the caller has none, a
    generic, decision-derived alternative is produced instead of leaving
    the explanation empty.
    """

    decision = str(decision or "").strip().upper()
    reason = str(reason or "").strip()
    alternative = str(alternative or "").strip()

    if not alternative:
        alternative = {
            "REMOVE": "No replacement needed; the step added no value.",
            "MERGE": "Combined into a single agent-prepared step.",
            "AUTOMATE": "Executed automatically by the agent in the background.",
            "REVIEW": "Routed to a human reviewer with full case context attached.",
            "KEEP": "Kept as-is to satisfy a legal, security or policy requirement.",
        }.get(decision, "Handled by the agent as part of the redesigned journey.")

    return {
        "step": step_text,
        "decision": decision,
        "why": reason or "No specific reason was recorded for this decision.",
        "replaced_by": alternative,
    }


# ---------------------------------------------------------------------------
# 3. AGENTIC JOURNEY PATTERN — generic customer-effort shape for ANY service
# ---------------------------------------------------------------------------

# The minimum customer touchpoints an agent-led journey should collapse to.
# A service adds a payment stage only when the classifier confirms one is
# actually required; every other stage happens in the background.
AGENTIC_JOURNEY_STAGES = ["IDENTITY", "REVIEW_AND_APPROVE", "PAY"]


def summarize_customer_effort(current_step_count, future_steps):
    """Report the shift from N current steps to near-zero customer effort.

    The headline number is not "future step count" (moving 30 steps to 15
    still means 15) — it is how many of the FUTURE steps still require the
    customer to do something (type HUMAN / owner CUSTOMER), because those
    are the only steps that remain the customer's effort.
    """

    future_steps = future_steps or []

    def _is_customer_effort(step):
        # The primary, already-existing signal: a stage that carries at
        # least one customer_control_point (natural-language request,
        # approve the plan, complete payment, ...) is real customer
        # effort. Fall back to owner/type only when a step somehow
        # carries neither field (defensive, not the normal path).
        if "customer_control_points" in step:
            return bool(step.get("customer_control_points"))
        return (
            str(step.get("owner", "")).upper() == "CUSTOMER"
            or (
                str(step.get("type", "")).upper() == "HUMAN"
                and str(step.get("owner", "")).upper() != "ASSISTANT"
                and str(step.get("owner", "")).upper() != "HUMAN"
            )
        )

    customer_effort_steps = [
        step for step in future_steps if _is_customer_effort(step)
    ]
    agent_steps = [step for step in future_steps if step not in customer_effort_steps]

    return {
        "current_step_count": current_step_count,
        "future_step_count": len(future_steps),
        "future_customer_effort_steps": len(customer_effort_steps),
        "future_agent_executed_steps": len(agent_steps),
        "customer_effort_reduction_pct": (
            round(
                100
                * (1 - (len(customer_effort_steps) / current_step_count)),
                1,
            )
            if current_step_count
            else 0
        ),
        "target_pattern": AGENTIC_JOURNEY_STAGES,
    }
