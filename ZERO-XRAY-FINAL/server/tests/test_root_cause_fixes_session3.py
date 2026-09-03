"""Regression tests for the THIRD root-cause-fix pass, based on a real
Ollama 0.32.15 + qwen3:4b end-to-end run:

    1) SERVICE   -> grounding still dropped correct Arabic paraphrase
       steps that used multiple stacked prefixes/suffixes ("وبالعنوان"
       vs "العنوان") -- light_stem() only stripped one affix layer.

    2) JOURNEY   -> a package/tier-selection stage was placed AFTER
       the payment stage in some AI responses (fee should be
       confirmed before it is charged, not after).

    3) VALIDATION -> Compliance score was floored at 0 for basically
       EVERY AI-designed journey because change_type="AI_DESIGNED"
       (which the AI path always sets) was never in validation_agent's
       allowed_change_types set, so every single stage triggered a
       CRITICAL "invalid change_type" issue (-30 each) regardless of
       how good the actual redesign was. This is the dominant,
       previously-undiagnosed cause of the reported Compliance=0.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.service_agent import ServiceAnalystAgent
from agents.journey_builder_agent import JourneyBuilderAgent
from agents.validation_agent import ValidationAgent
from core.grounding import light_stem, is_semantically_grounded
from core.rules import calculate_metrics
from core.scoring import calculate_zero_bureaucracy_score


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, system_prompt, user_prompt, max_new_tokens=None, temperature=0, timeout=None):
        self.calls += 1
        if not self._responses:
            return ""
        return self._responses.pop(0)


# ======================================================================
# 1) SERVICE: iterative multi-affix Arabic stemming
# ======================================================================

def test_light_stem_strips_multiple_stacked_arabic_affixes():
    """A word with three stacked layers (و + ب + ال + عنوان) must stem
    to the same root as the bare noun -- the old single-pass stemmer
    left extra affixes attached and under-matched real paraphrases."""
    assert light_stem("وبالعنوان") == light_stem("العنوان")
    assert light_stem("وبالعنوان") == "عنوان"


def test_service_agent_accepts_real_arabic_compound_split_from_real_log():
    """The exact real-world example reported: a dense Arabic raw line
    describing address + delivery preference + an additional postal
    agent, split by the AI into elaborated sub-steps that use
    different (stacked-affix) wording than the raw line."""
    raw_lines = [
        "العميل يقدم طلب توصيل بريدي ويحدد عنوان الاستلام ووسيلة التوصيل "
        "المفضلة، ويمكنه أيضاً إضافة شخص آخر مخول لاستلام الطرود نيابة عنه",
        "الموظف يراجع الطلب ويتحقق من صحة البيانات المدخلة",
        "المشرف يعتمد الطلب بعد المراجعة",
    ]
    ai_steps = [
        "العميل يقدم طلب توصيل بريدي",
        "تحديد عنوان المنزل وتفضيلات التوصيل",
        "إضافة وكيل بريدي إضافي لاستلام الطرود",
        "الموظف يراجع الطلب ويتحقق من صحة البيانات",
        "المشرف يعتمد الطلب بعد المراجعة",
    ]

    llm = FakeLLM([
        json.dumps({"steps": ai_steps}, ensure_ascii=False),
        json.dumps({"objective": "تسليم طرد بريدي للعميل", "friction_points": []}, ensure_ascii=False),
        json.dumps({
            "has_payment": False, "payment_evidence": "",
            "has_documents": False, "documents_evidence": "",
            "has_physical_visit": False, "visit_evidence": "",
            "has_human_approval": True, "human_approval_evidence": "المشرف يعتمد الطلب بعد المراجعة",
        }, ensure_ascii=False),
    ])
    agent = ServiceAnalystAgent(llm)
    result = agent.run({
        "service_name": "خدمة التوصيل البريدي",
        "description": "توصيل الطرود البريدية للعملاء",
        "steps": raw_lines,
    })

    assert result["steps_analysis_source"] == "ai"
    # both elaborated paraphrase steps must survive individually now
    assert "تحديد عنوان المنزل وتفضيلات التوصيل" in result["steps"]
    assert "إضافة وكيل بريدي إضافي لاستلام الطرود" in result["steps"]


# ======================================================================
# 2) JOURNEY: package-before-payment ordering safety net
# ======================================================================

SOURCE_STEPS = [
    "Customer submits a shipping request",
    "Customer selects a shipping package (Standard, Express or Premium)",
    "System calculates the fee based on the selected package",
    "Customer pays the shipping fee",
    "Customer receives the shipment",
]


def _misordered_payment_before_package_steps():
    """Reproduces the real defect: payment stage comes BEFORE the
    package-selection stage it should depend on."""
    return [
        {
            "name": "Submit shipping request", "type": "SYSTEM", "executor": "AGENT",
            "action": "The assistant captures the shipment request.",
            "detailed_description": "The assistant captures the shipment request details from the customer to begin processing.",
            "reasoning": "Entry point of the journey.", "customer_role": "Describes the shipment",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "", "delivers_customer_result": False,
        },
        {
            "name": "Collect payment", "type": "SYSTEM", "executor": "AGENT",
            "action": "The assistant collects the shipping fee from the customer.",
            "detailed_description": "The assistant charges the customer's saved payment method for the shipping fee before the package is even chosen.",
            "reasoning": "Payment collected.", "customer_role": "Approves payment",
            "has_payment": True, "payment_reasoning": "Fee is charged here.",
            "requires_human_judgement": False, "human_judgement_reason": "",
            "requires_customer_approval": False, "depends_on_previous": "Request submitted",
            "delivers_customer_result": False,
        },
        {
            "name": "Select shipping package", "type": "SYSTEM", "executor": "AGENT",
            "action": "The customer selects a package (Standard, Express or Premium).",
            "detailed_description": "The assistant presents package tiers and the customer selects or changes the recommended package.",
            "reasoning": "Package determines final delivery terms.", "customer_role": "Selects the package",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Request submitted", "delivers_customer_result": False,
        },
        {
            "name": "Deliver shipment", "type": "SYSTEM", "executor": "AGENT",
            "action": "The customer receives the shipment.",
            "detailed_description": "The assistant coordinates delivery and the customer receives their shipment with a confirmation record.",
            "reasoning": "Concludes the journey.", "customer_role": "Receives the shipment",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Package selected", "delivers_customer_result": True,
        },
    ]


def test_journey_builder_reorders_package_selection_before_payment():
    """Real bug: the AI placed 'Collect payment' before 'Select
    shipping package'. The agent must deterministically reorder the
    package-selection stage before the payment stage without altering
    stage content or count."""
    steps = _misordered_payment_before_package_steps()
    llm = FakeLLM([
        json.dumps({"overall_reasoning": "Journey with fee collected before package chosen.", "steps": steps}, ensure_ascii=False),
    ])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Shipping service",
        "description": "Ship a package for a customer",
        "steps": SOURCE_STEPS,
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []})
    future_steps = result.get("future_steps", [])

    assert len(future_steps) == len(steps), "Reordering must not drop or invent stages."

    package_index = next(
        i for i, s in enumerate(future_steps)
        if "package" in str(s.get("name", "")).lower()
        and not s.get("has_payment")
    )
    payment_index = next(
        i for i, s in enumerate(future_steps) if s.get("has_payment")
    )
    assert package_index < payment_index, (
        "Package selection must come before payment after reordering; "
        f"got package at {package_index}, payment at {payment_index}."
    )
    # step_number must be renumbered consistently after reordering.
    assert [s["step_number"] for s in future_steps] == list(range(1, len(future_steps) + 1))


def test_journey_builder_leaves_already_correct_order_unchanged():
    """Sanity check: when package selection already precedes payment,
    the safety net must not touch the journey at all."""
    steps = _misordered_payment_before_package_steps()
    # swap indices 1 and 2 to make it already correctly ordered
    steps[1], steps[2] = steps[2], steps[1]
    llm = FakeLLM([
        json.dumps({"overall_reasoning": "Correctly ordered journey.", "steps": steps}, ensure_ascii=False),
    ])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Shipping service",
        "description": "Ship a package for a customer",
        "steps": SOURCE_STEPS,
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []})
    future_steps = result.get("future_steps", [])
    names_in_order = [s.get("name") for s in future_steps]
    assert names_in_order == [s["name"] for s in steps]


# ======================================================================
# 3) VALIDATION: change_type=AI_DESIGNED must not zero out compliance
# ======================================================================

def _good_ai_designed_future_steps():
    return [
        {
            "step_number": 1, "name": "Consolidated intake", "type": "SYSTEM",
            "action": "Assistant collects the request using known profile data.",
            "change_type": "AI_DESIGNED",
            "reason": "AI-designed based on this service's own logic.",
            "standard_id": None, "related_standard_ids": [], "source_steps": [],
            "semantic_category": "execution_continuity", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT",
            "assistant_action": "Collects request", "customer_role": "Provides intent",
            "visible_before_payment": True, "completion_evidence": "Reviewable execution log",
            "has_payment": False, "requires_human_judgement": False,
            "requires_customer_approval": False, "depends_on_previous": "",
            "detailed_description": "The assistant collects everything needed for this request from already-known profile data.",
            "reasoning": "Consolidated entry point.", "analysis_source": "ai",
        },
        {
            "step_number": 2, "name": "Automated validation", "type": "SYSTEM",
            "action": "System validates eligibility automatically.",
            "change_type": "AI_DESIGNED",
            "reason": "AI-designed based on this service's own logic.",
            "standard_id": None, "related_standard_ids": [], "source_steps": [],
            "semantic_category": "execution_continuity", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT",
            "assistant_action": "Validates eligibility", "customer_role": "No administrative customer work",
            "visible_before_payment": True, "completion_evidence": "Reviewable execution log",
            "has_payment": False, "requires_human_judgement": False,
            "requires_customer_approval": False, "depends_on_previous": "Intake complete",
            "detailed_description": "The system automatically validates the request against backend records instead of a manual review.",
            "reasoning": "Removes manual review.", "analysis_source": "ai",
        },
        {
            "step_number": 3, "name": "Deliver outcome", "type": "SYSTEM",
            "action": "Customer receives the final result.",
            "change_type": "AI_DESIGNED",
            "reason": "AI-designed based on this service's own logic.",
            "standard_id": None, "related_standard_ids": [], "source_steps": [],
            "semantic_category": "customer_outcome", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT",
            "assistant_action": "Delivers outcome", "customer_role": "Receives the result",
            "visible_before_payment": True, "completion_evidence": "Reviewable execution log",
            "has_payment": False, "requires_human_judgement": False,
            "requires_customer_approval": False, "depends_on_previous": "Validation complete",
            "detailed_description": "The assistant delivers the final result directly to the customer, concluding the journey with a clear outcome.",
            "reasoning": "Concludes the journey.", "analysis_source": "ai",
        },
    ]


def test_validation_agent_does_not_penalize_ai_designed_change_type():
    """Real bug: change_type='AI_DESIGNED' (set on every AI-authored
    stage) was outside validation_agent's allowed_change_types set, so
    every stage triggered a CRITICAL 'invalid change_type' issue
    (-30 each), flooring compliance_score at 0 regardless of actual
    journey quality. A good, well-formed AI-designed journey must not
    be penalized for its own producer's vocabulary."""
    future_steps = _good_ai_designed_future_steps()
    service = {
        "service_name": "Test service",
        "description": "A test service",
        "steps": ["Step A", "Step B", "Step C", "Step D", "Step E"],
        "manual_actions": ["Manual review step"],
    }
    redesign = {
        "future_steps": future_steps,
        "removed_steps": [],
        "merged_steps": [],
        "future_customer_burden_steps": 0,
        "future_branch_visits": 0,
        "future_manual_actions": [],
        "review_steps": [],
        "required_integrations": [],
        "automation_opportunities": [],
        "customer_only_actions": [],
        "service_classification": {},
    }
    standards = {"applicable_standards": []}

    metrics = calculate_metrics(service, redesign)
    zb_score = calculate_zero_bureaucracy_score(metrics)

    agent = ValidationAgent(llm=None)
    validation = agent.run(
        service=service,
        standards=standards,
        redesign=redesign,
        metrics={**metrics, "zero_bureaucracy_score": zb_score},
    )

    change_type_issues = [
        issue for issue in validation["issues"]
        if "change_type" in str(issue.get("issue", "")).lower()
    ]
    assert not change_type_issues, (
        "AI_DESIGNED must be an allowed change_type; got spurious "
        f"issues: {change_type_issues}"
    )
    assert validation["compliance_score"] > 0, (
        "A well-formed AI-designed journey (5 current steps -> 3 "
        "consolidated future stages, no other real defects) must not "
        f"have compliance_score floored at 0; got {validation['compliance_score']}."
    )


def test_count_change_types_recognizes_ai_designed():
    from core.rules import count_change_types
    redesign = {"future_steps": _good_ai_designed_future_steps()}
    counts = count_change_types(redesign)
    assert counts.get("AI_DESIGNED") == 3


if __name__ == "__main__":
    test_light_stem_strips_multiple_stacked_arabic_affixes()
    test_service_agent_accepts_real_arabic_compound_split_from_real_log()
    test_journey_builder_reorders_package_selection_before_payment()
    test_journey_builder_leaves_already_correct_order_unchanged()
    test_validation_agent_does_not_penalize_ai_designed_change_type()
    test_count_change_types_recognizes_ai_designed()
    print("ALL SESSION-3 ROOT-CAUSE-FIX TESTS PASSED")
