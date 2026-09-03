"""Regression tests for the second root-cause-fix pass, reproducing the
specific failure signatures reported from a real Ollama 0.32.15 +
qwen3:4b run in Arabic:

    1) SERVICE  -> a batch of 14 grounded semantic steps was discarded
       ENTIRELY because 3 of them (real, logical elaborations such as
       "specify the home address and delivery preference" / "add an
       additional postal agent") sat right at the edge of the
       per-step grounding check. Fix: keep the grounded majority
       instead of discarding the whole batch.

    2) JOURNEY  -> the AI accepted a "redesigned" journey that was
       really the current 8-step journey copied into 10 near-identical
       future stages (same order, reworded), which correctly failed
       validation (0% reduction, ZB=68, compliance=0) but was never
       actually challenged to do better. Fix: detect this pattern and
       give the model one corrective retry before accepting it.

Both fixes preserve Ollama/qwen3:4b as the PRIMARY author: neither one
discards real AI output in favor of a template/baseline. The service
fix keeps more of the AI's own steps than before (partial retention
instead of all-or-nothing); the journey fix gives the AI a genuine
second chance with concrete feedback instead of silently accepting
(or silently replacing) a low-quality first draft.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.service_agent import ServiceAnalystAgent
from agents.journey_builder_agent import JourneyBuilderAgent


class FakeLLM:
    """Returns pre-scripted responses in call order."""

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


# ======================================================================
# 1) SERVICE: partial grounding retention (Arabic real-world example)
# ======================================================================

def test_service_agent_keeps_grounded_majority_when_a_minority_fail_grounding():
    """Real bug: qwen3:4b returned 14 real, meaning-grounded Arabic
    steps split out of 8 raw lines. 3 of them (elaborations like
    'specify the home address and delivery preference' / 'add an
    additional postal agent') individually sat at/under the grounding
    threshold because they introduce a *new* concrete noun (e.g. 'home')
    that paraphrases rather than echoes the raw line, while the other
    11 steps matched comfortably. The old code discarded ALL 14 the
    moment ANY step failed grounding. The fix must keep the 11 (or
    however many are actually grounded) instead of falling back to the
    crude heuristic merge for the whole batch."""
    raw_lines = [
        "العميل يقدم طلب توصيل بريدي ويحدد عنوان الاستلام ووسيلة التوصيل المفضلة، ويمكنه أيضاً إضافة شخص آخر مخول لاستلام الطرود نيابة عنه",
        "الموظف يراجع الطلب ويتحقق من صحة البيانات المدخلة",
        "المشرف يعتمد الطلب بعد المراجعة",
        "النظام يصدر رقم تتبع للشحنة ويرسله للعميل عبر الرسائل النصية",
        "العميل يدفع رسوم التوصيل المستحقة قبل تسليم الطرد",
        "العميل يستلم الطرد من المندوب أو من الفرع",
        "النظام يسجل عملية التسليم لأغراض التدقيق",
        "يمكن للعميل تقديم شكوى في حال وجود تلف أو تأخير في التسليم",
    ]
    # 14 AI-produced steps: two of them ("تحديد عنوان المنزل وتفضيلات
    # التوصيل" and "إضافة وكيل بريدي إضافي") are genuine paraphrases of
    # raw_lines[0] but introduce new wording ("المنزل" / "وكيل بريدي")
    # that doesn't lexically overlap enough with the raw text to pass
    # the per-step grounding check on its own -- they should be
    # DROPPED, not used to discard the other 12 real steps.
    ai_steps = [
        "العميل يقدم طلب توصيل بريدي",
        "تحديد عنوان المنزل وتفضيلات التوصيل",
        "إضافة وكيل بريدي إضافي لاستلام الطرود",
        "الموظف يراجع الطلب",
        "الموظف يتحقق من صحة البيانات المدخلة",
        "المشرف يعتمد الطلب بعد المراجعة",
        "النظام يصدر رقم تتبع للشحنة",
        "النظام يرسل رقم التتبع للعميل عبر الرسائل النصية",
        "العميل يدفع رسوم التوصيل المستحقة قبل تسليم الطرد",
        "العميل يستلم الطرد من المندوب أو من الفرع",
        "النظام يسجل عملية التسليم لأغراض التدقيق",
        "العميل يقدم شكوى في حال وجود تلف",
        "العميل يقدم شكوى في حال وجود تأخير في التسليم",
        "طرح مخترع تماما عن مركبات فضائية لا علاقة له بالخدمة إطلاقا",
    ]
    assert len(ai_steps) == 14 and len(raw_lines) == 8

    llm = FakeLLM([
        json.dumps({"steps": ai_steps}, ensure_ascii=False),
        json.dumps({"objective": "تسليم طرد بريدي للعميل", "friction_points": []}, ensure_ascii=False),
        json.dumps({
            "has_payment": True, "payment_evidence": "العميل يدفع رسوم التوصيل المستحقة",
            "has_documents": False, "documents_evidence": "",
            "has_physical_visit": True, "visit_evidence": "العميل يستلم الطرد من المندوب أو من الفرع",
            "has_human_approval": True, "human_approval_evidence": "المشرف يعتمد الطلب بعد المراجعة",
        }, ensure_ascii=False),
    ])

    agent = ServiceAnalystAgent(llm)
    result = agent.run({
        "service_name": "خدمة التوصيل البريدي",
        "description": "توصيل الطرود البريدية للعملاء",
        "steps": raw_lines,
    })

    assert result["steps_analysis_source"] == "ai", (
        "Expected the grounded majority of the AI's 14-step breakdown "
        f"to be accepted; got fallback instead. steps={result['steps']}"
    )
    # The wholly-invented spaceship step must never survive.
    assert not any("فضائية" in s for s in result["steps"])
    # A healthy majority of the real steps must survive -- this is a
    # partial-retention check, not an exact-count check (the specific
    # borderline paraphrases may or may not individually pass the
    # grounding threshold; what matters is the batch wasn't nuked).
    assert len(result["steps"]) >= 10, result["steps"]


def test_service_agent_still_rejects_when_majority_is_ungrounded():
    """Sanity check: if MOST of the AI's steps have no real basis in
    the raw text, the whole batch should still be rejected (falls back
    to the heuristic merge) -- partial retention must not become a
    loophole for mostly-invented output."""
    raw_lines = ["العميل يقدم طلب بسيط"]
    ai_steps = [f"خطوة مخترعة تماما رقم {i} عن موضوع غير متعلق بالخدمة" for i in range(6)]

    llm = FakeLLM([
        json.dumps({"steps": ai_steps}, ensure_ascii=False),
        "",
        "",
    ])
    agent = ServiceAnalystAgent(llm)
    result = agent.run({"service_name": "X", "description": "", "steps": raw_lines})
    assert result["steps_analysis_source"] == "template"


# ======================================================================
# 2) JOURNEY: near-copy detection + corrective retry
# ======================================================================

def _echoed_journey_steps(source_steps):
    """Build a future-journey AI response that just restates each
    current step as its own future stage, in the same order -- the
    exact real-world failure signature (Current=8, Future=10, 0%
    reduction)."""
    steps = []
    for i, source in enumerate(source_steps):
        steps.append({
            "name": f"Stage {i + 1}",
            "type": "SYSTEM",
            "executor": "AGENT",
            "action": source,
            "detailed_description": (
                f"{source}. This stage carries out the same action as "
                "the current journey step, executed by the assistant "
                "instead of manually."
            ),
            "reasoning": "Follows the current journey order.",
            "customer_role": "Provides required input" if i % 2 == 0 else "None",
            "has_payment": False,
            "payment_reasoning": "",
            "requires_human_judgement": False,
            "human_judgement_reason": "",
            "requires_customer_approval": False,
            "depends_on_previous": "",
            "delivers_customer_result": i == len(source_steps) - 1,
        })
    # Two extra near-duplicate stages on top -- this is the "Future=10
    # from Current=8" signature.
    steps.append({
        "name": "Extra navigation stage",
        "type": "SYSTEM", "executor": "AGENT",
        "action": source_steps[0],
        "detailed_description": f"{source_steps[0]}. Repeated navigation stage.",
        "reasoning": "", "customer_role": "None", "has_payment": False,
        "payment_reasoning": "", "requires_human_judgement": False,
        "human_judgement_reason": "", "requires_customer_approval": False,
        "depends_on_previous": "", "delivers_customer_result": False,
    })
    steps.append({
        "name": "Extra confirmation stage",
        "type": "SYSTEM", "executor": "AGENT",
        "action": source_steps[1] if len(source_steps) > 1 else source_steps[0],
        "detailed_description": "Confirms the previous stage. Adds no new value.",
        "reasoning": "", "customer_role": "None", "has_payment": False,
        "payment_reasoning": "", "requires_human_judgement": False,
        "human_judgement_reason": "", "requires_customer_approval": False,
        "depends_on_previous": "", "delivers_customer_result": False,
    })
    return steps


def _consolidated_journey_steps(source_steps):
    """A genuinely redesigned, consolidated journey (fewer stages,
    outcome-oriented) for the retry response."""
    return [
        {
            "name": "Submit request via assistant",
            "type": "SYSTEM", "executor": "AGENT",
            "action": "The assistant collects the delivery outcome the customer wants using already-known profile data.",
            "detailed_description": (
                "The assistant gathers the customer's delivery address and preferences from "
                "their verified profile/UAE PASS data instead of asking them to re-enter it, "
                "consolidating what used to be several separate data-entry and navigation steps."
            ),
            "reasoning": "Single consolidated entry point replacing multiple redundant current steps.",
            "customer_role": "States the outcome they want", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "", "delivers_customer_result": False,
        },
        {
            "name": "Automated eligibility and data checks",
            "type": "SYSTEM", "executor": "AGENT",
            "action": "The system automatically validates the request against backend records.",
            "detailed_description": (
                "Eligibility and data validation, previously a manual employee review step, is "
                "performed automatically by the assistant against backend systems, removing the "
                "wait and the manual handoff."
            ),
            "reasoning": "Automates what was manual review.",
            "customer_role": "None", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Request submitted", "delivers_customer_result": False,
        },
        {
            "name": "Payment and execution",
            "type": "SYSTEM", "executor": "AGENT",
            "action": "Customer pays and the assistant executes and tracks the delivery.",
            "detailed_description": (
                "Once validated, the assistant collects payment and coordinates execution and "
                "tracking end-to-end, removing the separate branch visit and manual tracking steps."
            ),
            "reasoning": "Payment happens once the request is validated.",
            "customer_role": "Approves payment", "has_payment": True,
            "payment_reasoning": "Amount is known once the request is validated.",
            "requires_human_judgement": False, "human_judgement_reason": "",
            "requires_customer_approval": False,
            "depends_on_previous": "Eligibility validated", "delivers_customer_result": False,
        },
        {
            "name": "Delivery and outcome confirmation",
            "type": "SYSTEM", "executor": "AGENT",
            "action": "Customer receives the delivered package and a confirmation record.",
            "detailed_description": (
                "The customer receives the outcome directly, with a reviewable confirmation "
                "record available at any time, concluding the journey."
            ),
            "reasoning": "Concludes the journey with a clear customer-visible outcome.",
            "customer_role": "Receives the delivery", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Payment completed", "delivers_customer_result": True,
        },
    ]


SOURCE_STEPS = [
    "Customer submits a delivery request and specifies the receiving address",
    "Customer selects the preferred delivery method",
    "Employee reviews the request and checks the submitted data",
    "Supervisor approves the request after review",
    "System issues a tracking number for the shipment",
    "System sends the tracking number to the customer",
    "Customer pays the applicable delivery fee before the parcel is delivered",
    "Customer receives the parcel from the courier or the branch",
]


def test_journey_builder_detects_near_copy_and_retries_with_feedback():
    """Real bug: the AI's first attempt just echoed the 8 current steps
    as 10 future stages in the same order (0% real reduction). The
    fixed agent must detect this and retry once with corrective
    feedback -- and must use the (better) retry result, not silently
    keep the uncompressed first draft."""
    echoed = _echoed_journey_steps(SOURCE_STEPS)
    consolidated = _consolidated_journey_steps(SOURCE_STEPS)

    llm = FakeLLM([
        json.dumps({"overall_reasoning": "Mirrors current steps.", "steps": echoed}, ensure_ascii=False),
        json.dumps({"overall_reasoning": "Consolidated, outcome-first redesign.", "steps": consolidated}, ensure_ascii=False),
    ])

    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Postal delivery service",
        "description": "Deliver a parcel to a customer",
        "steps": SOURCE_STEPS,
    }
    step_compliance = {"steps": []}
    result = agent.run(service, step_compliance, relevant_standards={"applicable_standards": []})

    future_steps = result.get("future_steps", [])
    assert llm.calls == 2, (
        "Expected exactly one corrective retry after the near-copy "
        f"first attempt; got {llm.calls} LLM call(s)."
    )
    assert len(future_steps) < len(SOURCE_STEPS), (
        "Expected the retry's consolidated journey (fewer stages than "
        f"the {len(SOURCE_STEPS)} current steps) to be used instead of "
        f"the uncompressed first draft; got {len(future_steps)} stages."
    )
    # The retry prompt must actually carry concrete feedback, not just
    # a bare repeat of the same prompt.
    assert "CORRECTIVE FEEDBACK" in llm.prompts[1]
    assert str(len(echoed)) in llm.prompts[1]


def test_journey_builder_keeps_first_ai_attempt_when_not_a_near_copy():
    """Sanity check: a journey that already reduces/consolidates the
    current steps must be accepted on the first attempt -- the retry
    logic must not fire on genuinely good AI output."""
    consolidated = _consolidated_journey_steps(SOURCE_STEPS)
    llm = FakeLLM([
        json.dumps({"overall_reasoning": "Consolidated redesign.", "steps": consolidated}, ensure_ascii=False),
    ])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Postal delivery service",
        "description": "Deliver a parcel to a customer",
        "steps": SOURCE_STEPS,
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []})

    assert llm.calls == 1, "Should not retry when the first attempt is already a real redesign."
    assert len(result.get("future_steps", [])) == len(consolidated)


def test_journey_builder_keeps_first_attempt_if_retry_hard_fails():
    """If the corrective retry itself comes back unusable (parse
    error), the agent must keep the first attempt's real AI output
    rather than losing everything and falling back to the template."""
    echoed = _echoed_journey_steps(SOURCE_STEPS)
    llm = FakeLLM([
        json.dumps({"overall_reasoning": "Mirrors current steps.", "steps": echoed}, ensure_ascii=False),
        "not valid json at all {{{",
    ])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Postal delivery service",
        "description": "Deliver a parcel to a customer",
        "steps": SOURCE_STEPS,
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []})

    assert result.get("service_classification") is not None or "future_steps" in result
    future_steps = result.get("future_steps", [])
    ai_sourced = [s for s in future_steps if s.get("analysis_source") == "ai" or s.get("change_type") == "AI_DESIGNED"]
    assert ai_sourced, (
        "Expected the first attempt's real AI-designed stages to survive "
        "when the retry hard-fails, not a silent drop to the template."
    )


# ======================================================================
# 2) STANDARDS + GAPS: checklist validation / ID validity / evidence
#    linking, as explicitly re-verified for this session (no code
#    change was needed here -- these lock in the existing behavior).
# ======================================================================

from agents.standards_agent import StandardsAgent
from agents.gap_agent import GapAnalysisAgent
from core.standards_catalog import STANDARDS_CATALOG, valid_standard_ids


def test_standards_agent_checklist_rejects_ids_outside_the_catalog():
    """Every returned standard_id must be a real catalog id -- an id
    the model invents (not in the checklist it was given) must never
    reach the result."""
    service_analysis = {
        "steps": ["Customer submits a request", "Employee manually processes it"],
        "manual_actions": ["Employee manually processes it"],
        "waiting_points": [], "approvals": [], "documents": [],
        "friction_points": ["Manual operational work exists"],
        "service_classification": {"requires_customer_payment": False},
    }
    response = json.dumps({
        "selections": {
            STANDARDS_CATALOG[0]["standard_id"]: {
                "applicable": True,
                "why_it_applies": "Manual work exists in the current journey.",
            },
            "STD-99-INVENTED": {
                "applicable": True,
                "why_it_applies": "Should never be accepted.",
            },
        }
    }, ensure_ascii=False)

    llm = FakeLLM([response])
    agent = StandardsAgent(llm)
    result = agent.run(service_analysis, standards={"source_text": ""})

    ids = {item["standard_id"] for item in result["applicable_standards"]}
    assert "STD-99-INVENTED" not in ids
    assert ids.issubset(valid_standard_ids())
    assert STANDARDS_CATALOG[0]["standard_id"] in ids


def test_gap_agent_rejects_gap_with_standard_id_outside_applicable_set():
    """A gap's standard_id must be one of the standards actually
    marked applicable for this service -- not just any catalog id."""
    applicable_standards = [
        {"standard_id": "STD-02", "title": "Burden Shifts to the Assistant", "requirement": "...", "measurable_test": "..."},
    ]
    service_analysis = {
        "steps": ["Employee manually re-enters the same data"],
        "manual_actions": ["Employee manually re-enters the same data"],
        "waiting_points": [], "approvals": [], "documents": [], "branch_visits": 0,
    }
    response = json.dumps({"gaps": [
        {
            "category": "Duplicate Data",
            "description": "Manual re-entry of the same data.",
            "standard_id": "STD-02",
            "severity": "HIGH",
            "recommendation": "Reuse captured data.",
        },
        {
            "category": "Unrelated",
            "description": "A gap citing a standard never marked applicable for this service.",
            "standard_id": "STD-07",
            "severity": "LOW",
            "recommendation": "N/A",
        },
    ]}, ensure_ascii=False)

    llm = FakeLLM([response])
    agent = GapAnalysisAgent(llm)
    result = agent.run(service_analysis, {"applicable_standards": applicable_standards})

    standard_ids = {gap["standard_id"] for gap in result["gaps"]}
    assert "STD-07" not in standard_ids, (
        "A gap citing a standard outside the applicable set must be "
        f"rejected; got gaps={result['gaps']}"
    )
    assert "STD-02" in standard_ids


if __name__ == "__main__":
    test_service_agent_keeps_grounded_majority_when_a_minority_fail_grounding()
    test_service_agent_still_rejects_when_majority_is_ungrounded()
    test_journey_builder_detects_near_copy_and_retries_with_feedback()
    test_journey_builder_keeps_first_ai_attempt_when_not_a_near_copy()
    test_journey_builder_keeps_first_attempt_if_retry_hard_fails()
    test_standards_agent_checklist_rejects_ids_outside_the_catalog()
    test_gap_agent_rejects_gap_with_standard_id_outside_applicable_set()
    print("ALL SESSION-2 ROOT-CAUSE-FIX TESTS PASSED")
