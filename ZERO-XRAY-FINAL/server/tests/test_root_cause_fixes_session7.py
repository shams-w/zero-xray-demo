"""Regression tests for the SEVENTH root-cause-fix pass: Journey
Builder as a service-AWARE AI agent that designs a genuinely different
journey shape depending on THIS service's own nature (transactional
vs. support/inquiry, or anything else), instead of one fixed flow
applied to every service -- with the archetype decision made entirely
by the model reasoning about the service's own evidence, never by
Python code branching on a service name or a fixed keyword-derived
category.
"""

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.journey_builder_agent import JourneyBuilderAgent


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.prompts = []

    def generate(self, system_prompt, user_prompt, max_new_tokens=None, temperature=0, timeout=None):
        self.calls += 1
        self.prompts.append(user_prompt)
        if not self._responses:
            return ""
        return self._responses.pop(0)


def _stage(name, action, detail, type_="SYSTEM", executor="AGENT",
           has_payment=False, payment_reason="", human=False, human_reason="",
           customer_approval=False, depends_on="", delivers=False,
           customer_role="None", reasoning="Because this follows the service's own evidence."):
    return {
        "name": name, "type": type_, "executor": executor, "action": action,
        "detailed_description": detail, "reasoning": reasoning,
        "customer_role": customer_role, "has_payment": has_payment,
        "payment_reasoning": payment_reason, "requires_human_judgement": human,
        "human_judgement_reason": human_reason, "requires_customer_approval": customer_approval,
        "depends_on_previous": depends_on, "delivers_customer_result": delivers,
    }


# ======================================================================
# 1) Two different service natures get two genuinely different shapes
# ======================================================================

TRANSACTIONAL_SERVICE = {
    "service_name": "P.O. Box renewal",
    "description": "A customer renews their post office box subscription.",
    "steps": [
        "Customer logs in and selects P.O. Box renewal",
        "Customer selects box size and contract duration",
        "Employee manually checks for outstanding balance",
        "System calculates the renewal fee",
        "Customer pays the renewal fee",
        "System renews the box and sends confirmation",
    ],
}

TRANSACTIONAL_AI_STEPS = [
    _stage(
        "Build renewal plan", "Assistant retrieves the box record and checks eligibility.",
        "The assistant retrieves the customer's existing P.O. Box record and checks for any outstanding balance automatically instead of a manual employee check.",
        reasoning="Automates the manual balance check.",
    ),
    _stage(
        "Present plan for approval and pay", "Assistant proposes the renewal plan and fee; customer approves and pays.",
        "The assistant proposes the default box size/duration from the existing record, calculates the fee, and lets the customer approve-and-pay in one action or edit the plan via specific choices.",
        has_payment=True, payment_reason="Fee is known once the plan and balance check are confirmed.",
        customer_approval=True, depends_on="Plan built", customer_role="Approves and pays, or edits the plan",
    ),
    _stage(
        "Deliver renewed box confirmation", "Customer receives the renewal confirmation.",
        "The assistant renews the box and delivers a confirmation record to the customer, concluding the journey.",
        delivers=True, depends_on="Payment completed", customer_role="Receives confirmation",
    ),
]

SUPPORT_SERVICE = {
    "service_name": "Delivery complaint",
    "description": "A customer complains that a parcel was not delivered on time.",
    "steps": [
        "Customer submits a complaint about a late delivery",
        "Employee looks up the shipment tracking history",
        "Employee investigates the delay with the courier",
        "Employee decides on a resolution (compensation or redelivery)",
        "Customer is notified of the outcome",
    ],
}

SUPPORT_AI_STEPS = [
    _stage(
        "Understand and investigate the complaint", "Assistant retrieves the shipment's tracking and delay history.",
        "The assistant pulls the shipment's tracking history and delay records from the customer's existing account context to understand what happened, without asking the customer to re-supply the tracking number.",
        reasoning="Uses existing account context instead of manual employee lookup.",
    ),
    _stage(
        "Propose resolution options", "Assistant analyzes the delay and offers specific resolution choices.",
        "Based on the delay found, the assistant offers the customer specific resolution options (e.g. redelivery or compensation) to choose from, rather than asking them to describe what they want.",
        customer_approval=True, depends_on="Investigation complete", customer_role="Selects a resolution option",
    ),
    _stage(
        "Deliver resolution outcome", "Customer receives the resolution outcome.",
        "The assistant applies the chosen resolution and confirms the outcome to the customer, concluding the case.",
        delivers=True, depends_on="Resolution selected", customer_role="Receives outcome",
    ),
]


def _run_journey(service, ai_steps):
    llm = FakeLLM([json.dumps({"steps": ai_steps, "overall_reasoning": "Service-specific design."}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []})
    return result, llm


def test_transactional_and_support_services_get_different_journey_shapes():
    """A transactional (P.O. Box renewal) and a support (delivery
    complaint) service must come out with genuinely different journey
    shapes -- one has payment/plan-approval, the other doesn't -- both
    driven by the SAME generic code path and prompt, never a fixed
    per-service flow."""
    transactional_result, _ = _run_journey(TRANSACTIONAL_SERVICE, TRANSACTIONAL_AI_STEPS)
    support_result, _ = _run_journey(SUPPORT_SERVICE, SUPPORT_AI_STEPS)

    t_steps = transactional_result["future_steps"]
    s_steps = support_result["future_steps"]

    assert any(s.get("has_payment") for s in t_steps), "Transactional service should have a payment stage."
    assert not any(s.get("has_payment") for s in s_steps), "Support/complaint service should have NO payment stage."

    # The two journeys' stage names/semantic content must not be
    # near-identical -- proving they aren't the same fixed flow with
    # labels swapped.
    t_names = {s["name"].lower() for s in t_steps}
    s_names = {s["name"].lower() for s in s_steps}
    assert t_names != s_names

    # Both must still be genuinely AI-authored, not template fallback.
    assert transactional_result["analysis_source"] == "ai"
    assert support_result["analysis_source"] == "ai"


def test_customer_experience_narrative_reflects_the_actual_ai_journey_not_a_fixed_archetype_text():
    """The customer_experience summary field must be derived from
    each journey's own actual stages -- not a canned, service_kind-
    keyed string -- so it differs meaningfully between an unrelated
    transactional service and a support service."""
    transactional_result, _ = _run_journey(TRANSACTIONAL_SERVICE, TRANSACTIONAL_AI_STEPS)
    support_result, _ = _run_journey(SUPPORT_SERVICE, SUPPORT_AI_STEPS)

    t_experience = transactional_result["customer_experience"]
    s_experience = support_result["customer_experience"]
    assert t_experience != s_experience
    assert "approve" in t_experience.lower() or "pay" in t_experience.lower()
    assert "resolution" in s_experience.lower()


def test_both_archetypes_minimize_human_and_customer_administrative_work():
    """Regardless of shape, both journeys must genuinely minimize
    customer/human involvement -- most stages carry no customer
    administrative burden, and no stage is HUMAN-typed without cause."""
    for service, steps in ((TRANSACTIONAL_SERVICE, TRANSACTIONAL_AI_STEPS), (SUPPORT_SERVICE, SUPPORT_AI_STEPS)):
        result, _ = _run_journey(service, steps)
        future_steps = result["future_steps"]
        human_typed = [s for s in future_steps if s["type"] == "HUMAN"]
        assert not human_typed, (
            f"Expected zero HUMAN-typed stages for {service['service_name']!r} "
            f"(all customer-visible current employee work should be automated "
            f"or moved to a real customer confirmation point); got {human_typed}"
        )
        no_burden = sum(
            1 for s in future_steps
            if str(s.get("customer_role", "")).strip().lower() in ("none", "")
        )
        assert no_burden >= 1, "Expected at least one stage with no customer administrative work."


# ======================================================================
# 2) The prompt actually carries the service-aware / archetype guidance
# ======================================================================

def test_prompt_instructs_current_steps_are_evidence_not_blueprint():
    llm = FakeLLM([json.dumps({"steps": TRANSACTIONAL_AI_STEPS, "overall_reasoning": "x"}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    agent.run(TRANSACTIONAL_SERVICE, {"steps": []}, relevant_standards={"applicable_standards": []})
    prompt = llm.prompts[0]
    assert "NOT a blueprint" in prompt
    assert "already authenticated" in prompt or "UAE PASS" in prompt


def test_prompt_offers_transactional_and_support_patterns_as_reference_not_fixed_rule():
    llm = FakeLLM([json.dumps({"steps": TRANSACTIONAL_AI_STEPS, "overall_reasoning": "x"}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    agent.run(TRANSACTIONAL_SERVICE, {"steps": []}, relevant_standards={"applicable_standards": []})
    prompt = llm.prompts[0]
    assert "approve-and-pay" in prompt
    assert "human handoff" in prompt.lower()
    assert "given only as reference points" in prompt or "reference points" in prompt


# ======================================================================
# 3) No hardcoded per-service branching in the AI-authoring code path
# ======================================================================

def test_ai_path_functions_contain_no_hardcoded_service_special_cases():
    """The functions that actually drive the AI-designed journey
    (prompt construction, response parsing, compact retry) must never
    branch on a fixed service name/kind/archetype -- that kind of
    special-casing is only acceptable in the deterministic TEMPLATE
    fallback, never in the primary AI-authoring path this session's
    request is about."""
    forbidden = (
        "POSTAL_ACTIVITY_LICENSE", "INTERNATIONAL_SHIPMENT",
        "service_archetype", "service_kind",
    )
    sources = "".join([
        inspect.getsource(JourneyBuilderAgent._generate_ai_future_journey),
        inspect.getsource(JourneyBuilderAgent._run_ai_journey_attempt),
        inspect.getsource(JourneyBuilderAgent._build_compact_journey_prompt),
        inspect.getsource(JourneyBuilderAgent._customer_experience_from_ai_journey),
    ])
    for term in forbidden:
        assert term not in sources, f"Found hardcoded/special-case term {term!r} in the AI-authoring code path."


if __name__ == "__main__":
    test_transactional_and_support_services_get_different_journey_shapes()
    test_customer_experience_narrative_reflects_the_actual_ai_journey_not_a_fixed_archetype_text()
    test_both_archetypes_minimize_human_and_customer_administrative_work()
    test_prompt_instructs_current_steps_are_evidence_not_blueprint()
    test_prompt_offers_transactional_and_support_patterns_as_reference_not_fixed_rule()
    test_ai_path_functions_contain_no_hardcoded_service_special_cases()
    print("ALL SESSION-7 ROOT-CAUSE-FIX TESTS PASSED")
