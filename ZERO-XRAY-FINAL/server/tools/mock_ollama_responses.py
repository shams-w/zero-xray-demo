"""
Pure-Python (stdlib only) response-routing logic for the ZERO X-RAY
mock Ollama server.

This module intentionally has ZERO third-party imports (no fastapi,
no requests, nothing outside the standard library). It exists so the
exact same "route by system_prompt marker -> canned per-agent JSON"
logic that tools/mock_ollama_server.py exposes over HTTP can ALSO be:

  1. Imported directly by unit tests without needing fastapi/uvicorn
     installed at all (useful in minimal/offline environments, CI
     images that don't carry the web stack, etc).
  2. Served by tools/mock_ollama_server_stdlib.py, a zero-dependency
     http.server-based Ollama-compatible server, for environments
     where installing fastapi/uvicorn isn't possible or desired but a
     REAL HTTP round trip (not just an in-process stub) is still
     needed to exercise core/llm.py's actual request/response code.

tools/mock_ollama_server.py (the full-featured FastAPI version, with
header-based per-request failure-mode overrides used by the test
suite) now imports its response logic from here instead of duplicating
it, so there is exactly one place this behavior is defined.
"""

import re

def _extract_standard_ids(user_prompt: str):
    ids = re.findall(r"\b(STD-\d+|STAGE-\d+)\b", user_prompt)
    # de-dupe, keep order
    seen = []
    for item in ids:
        if item not in seen:
            seen.append(item)
    return seen


def _build_semantic_steps(user_prompt: str) -> dict:
    # Mirror the raw lines back, lightly "understood" (mock cannot do
    # real semantic merging, but must return a plausible non-trivial
    # list of steps -- never more lines than were given, matching the
    # real anti-hallucination invariant service_agent.py enforces).
    numbered_lines = re.findall(r"^\d+\.\s*(.+)$", user_prompt, re.MULTILINE)
    if not numbered_lines:
        numbered_lines = ["Customer submits the request", "Result is delivered"]
    # Merge the last two raw lines into one, if there's more than one,
    # so the mock's output count is strictly <= raw count (proving the
    # real anti-hallucination check in service_agent.py accepts it) yet
    # still demonstrably different from a naive 1:1 passthrough.
    if len(numbered_lines) > 2:
        merged = numbered_lines[:-2] + [
            numbered_lines[-2] + " (" + numbered_lines[-1] + ")"
        ]
    else:
        merged = numbered_lines
    return {"steps": merged}


def _build_capability_detection(user_prompt: str) -> dict:
    lowered = user_prompt.lower()
    no_fee = any(
        s in lowered
        for s in ("no fee", "without payment", "لا توجد رسوم", "بدون رسوم")
    )
    has_payment = ("payment" in lowered or "fee" in lowered) and not no_fee
    payment_evidence = ""
    if has_payment:
        for line in user_prompt.splitlines():
            if "pay" in line.lower() or "fee" in line.lower():
                payment_evidence = line.strip()[:150]
                break
    has_documents = "upload" in lowered or "document" in lowered
    has_visit = "branch" in lowered or "in person" in lowered or "physical" in lowered
    has_approval = "approv" in lowered and "customer approv" not in lowered
    return {
        "has_payment": has_payment,
        "payment_evidence": payment_evidence,
        "has_documents": has_documents,
        "documents_evidence": "Document upload step present in the service text." if has_documents else "",
        "has_physical_visit": has_visit,
        "visit_evidence": "Physical visit step present in the service text." if has_visit else "",
        "has_human_approval": has_approval,
        "human_approval_evidence": "Human approval step present in the service text." if has_approval else "",
    }


def _build_objective_friction(user_prompt: str) -> dict:
    return {
        "objective": "The customer wants this request completed accurately and quickly.",
        "friction_points": [
            "Manual data re-entry may exist between steps.",
        ],
    }


def _build_standards(user_prompt: str) -> dict:
    ids = _extract_standard_ids(user_prompt)
    chosen = ids[:2] if ids else []
    return {
        "applicable_standard_ids": chosen,
        "why_it_applies": {
            std_id: "MOCK_AI: directly relevant to this service's current journey."
            for std_id in chosen
        },
    }


def _build_gaps(user_prompt: str) -> dict:
    ids = _extract_standard_ids(user_prompt)
    standard_id = ids[0] if ids else "STAGE-01"
    return {
        "gaps": [
            {
                "category": "Manual Processing",
                "description": "A step in the current journey requires manual staff handling that could be automated.",
                "evidence": "Manual review step identified in the current journey steps.",
                "affected_step": "Manual review",
                "standard_id": standard_id,
                "severity": "MEDIUM",
                "recommendation": "Automate the manual review using system validation where policy allows.",
                "expected_impact": "Reduces processing time and the chance of inconsistent decisions.",
            }
        ]
    }


def _build_step_compliance_review(user_prompt: str) -> dict:
    # The prompt lists "1. text\n2. text..." for the reviewable steps
    # AND separately embeds the baseline JSON (which also contains
    # "step_number" ints) -- only take the leading enumerated CURRENT
    # STEPS block's numbers, not any step_number appearing later
    # inside the embedded baseline JSON blob.
    lines_section = user_prompt.split("A deterministic keyword scan")[0]
    numbers = [int(n) for n in re.findall(r"^(\d+)\.\s", lines_section, re.MULTILINE)]
    assessments = [
        {
            "step_number": n,
            "status": "PASS",
            "decision": "KEEP",
            "reason": "MOCK_AI: step is clear, necessary, and correctly scoped.",
            "standard_id": "",
        }
        for n in numbers
    ]
    return {"assessments": assessments}


def _build_journey(user_prompt: str) -> dict:
    ids = _extract_standard_ids(user_prompt)
    has_payment_evidence = "PAYMENT: CONFIRMED" in user_prompt
    steps = [
        {
            "name": "Request Intake",
            "type": "SYSTEM",
            "executor": "AGENT",
            "action": "The assistant captures the customer's request details automatically.",
            "detailed_description": (
                "MOCK_AI: the assistant collects the customer's request details through "
                "a guided intake flow, validating each field against the government "
                "standard as it is entered, so no incomplete request reaches the next stage."
            ),
            "reasoning": "This must happen first since every later stage depends on complete, validated intake data.",
            "customer_role": "Customer describes what they need in their own words.",
            "has_payment": False,
            "payment_reasoning": "",
            "requires_human_judgement": False,
            "human_judgement_reason": "",
            "requires_customer_approval": False,
            "depends_on_previous": "",
            "delivers_customer_result": False,
        },
        {
            "name": "Automated Verification",
            "type": "SYSTEM",
            "executor": "GOVERNMENT_SYSTEM",
            "action": "The system verifies eligibility against the relevant government registry.",
            "detailed_description": (
                "MOCK_AI: the assistant calls the appropriate government registry to confirm "
                "the customer's eligibility and prior records, removing any need for the "
                "customer to submit proof manually where the system already holds that data."
            ),
            "reasoning": "Verification must happen before any payment or approval step so those steps are never reached for an ineligible request.",
            "customer_role": "No administrative customer work.",
            "has_payment": False,
            "payment_reasoning": "",
            "requires_human_judgement": False,
            "human_judgement_reason": "",
            "requires_customer_approval": False,
            "depends_on_previous": "Uses the intake data collected in the previous stage.",
            "delivers_customer_result": False,
        },
    ]
    if has_payment_evidence:
        steps.append({
            "name": "Payment",
            "type": "SYSTEM",
            "executor": "AGENT",
            "action": "The customer reviews and approves the amount before it is charged.",
            "detailed_description": (
                "MOCK_AI: since this service has confirmed payment evidence, the assistant "
                "presents the exact amount and lets the customer approve it before any "
                "charge is made, keeping the customer in control of their own payment."
            ),
            "reasoning": "Payment must happen after verification (so the amount is accurate) and before final execution.",
            "customer_role": "Customer reviews and approves the amount.",
            "has_payment": True,
            "payment_reasoning": "The amount is already known after verification, so payment can happen before execution.",
            "requires_human_judgement": False,
            "human_judgement_reason": "",
            "requires_customer_approval": True,
            "depends_on_previous": "Requires the verified eligibility/amount from the previous stage.",
            "delivers_customer_result": False,
        })
    steps.append({
        "name": "Result Delivery",
        "type": "SYSTEM",
        "executor": "AGENT",
        "action": "The assistant delivers the final result to the customer.",
        "detailed_description": (
            "MOCK_AI: the assistant issues the final outcome (confirmation, document, or "
            "decision) and makes it immediately visible to the customer, closing the "
            "request with a clear, checkable result rather than leaving it open-ended."
        ),
        "reasoning": "This is the natural final stage: every prior stage exists to produce this result.",
        "customer_role": "Customer receives and can review the final result.",
        "has_payment": False,
        "payment_reasoning": "",
        "requires_human_judgement": False,
        "human_judgement_reason": "",
        "requires_customer_approval": False,
        "depends_on_previous": "Requires the previous stage(s) to have completed successfully.",
        "delivers_customer_result": True,
    })
    return {
        "overall_reasoning": (
            "MOCK_AI: designed as intake -> verification"
            + (" -> payment" if has_payment_evidence else "")
            + " -> result, so every stage only runs once its real "
            "prerequisites are satisfied."
        ),
        "steps": steps,
    }


def _build_validation_review(user_prompt: str) -> dict:
    return {"issues": [], "verdict": "PASS"}


AGENT_SYSTEM_PROMPT_MARKERS = [
    ("You are a meticulous process analyst who", _build_semantic_steps),
    ("You are a strict, evidence-only service", _build_capability_detection),
    ("You are a careful service-analysis expert.", _build_objective_friction),
    ("You are a government service standards", _build_standards),
    ("You are a government service gap analysis", _build_gaps),
    ("You are a meticulous compliance reviewer who", _build_step_compliance_review),
    ("You are a meticulous service-design expert who", _build_journey),
    # journey_builder_agent.py's system_prompt is language-aware (see
    # its ROOT-CAUSE FIX comment) -- fully Arabic when is_arabic=True,
    # not just this same English string. Without this marker, an
    # Arabic-language mock request would never match the English
    # marker above and would silently fall through to the generic
    # "no specific response template matched" response instead of
    # exercising _build_journey like every other mode does.
    ("أنت خبير دقيق في تصميم الخدمات", _build_journey),
    ("You are a meticulous logical-consistency", _build_validation_review),
]


def _route_response(messages) -> dict:
    system_prompt = ""
    user_prompt = ""
    for message in messages:
        if message.get("role") == "system":
            system_prompt = message.get("content", "")
        elif message.get("role") == "user":
            user_prompt = message.get("content", "")

    for marker, builder in AGENT_SYSTEM_PROMPT_MARKERS:
        if marker in system_prompt:
            return builder(user_prompt)

    # Unknown caller -- still return valid, generic JSON rather than
    # an empty/garbage body, so an unrecognized agent doesn't get
    # mistaken for a genuine AI-failure test case.
    return {"note": "MOCK_AI: no specific response template matched this caller."}


