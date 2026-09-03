"""Regression tests for the EIGHTH root-cause-fix pass: the Journey
Builder must distinguish, generically, between:

  1. Information ALREADY AVAILABLE from the identity/login source
     (UAE PASS) -- must never be re-requested.
  2. Information RETRIEVABLE via a proposed integration with THIS
     service's own system (e.g. related shipments/transactions) --
     must be framed as a proposed lookup the assistant performs, not
     assumed to already exist inside the identity source itself.
  3. Information GENUINELY MISSING (only the actual complaint
     description, resolution choice, or optional attachments) --
     the only things it's correct to still ask the customer for.

Uses the exact complaint-service scenario supplied for this session
as the primary regression/generalization case, plus a companion test
proving the engine still rejects/flags the specific hallucination
this feature could otherwise enable: claiming UAE PASS itself already
contains shipment/transaction numbers.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.journey_builder_agent import JourneyBuilderAgent
from agents.validation_agent import ValidationAgent
from core.standards_catalog import STANDARDS_CATALOG
from core.rules import calculate_metrics
from core.scoring import calculate_zero_bureaucracy_score


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


# The exact complaint-service current journey supplied for this session.
COMPLAINT_SERVICE = {
    "service_name": "تقديم شكوى",
    "description": "تقديم شكوى بخصوص خدمة أو معاملة لدى بريد الإمارات",
    "steps": [
        "الدخول إلى موقع أو تطبيق بريد الإمارات",
        "تسجيل الدخول باستخدام الهوية الرقمية UAE PASS أو بيانات الحساب",
        "اختيار خدمة تقديم شكوى",
        "اختيار نوع الشكوى والخدمة أو المعاملة المرتبطة بها",
        "إدخال رقم الشحنة أو رقم المعاملة أو رقم صندوق البريد",
        "كتابة تفاصيل الشكوى",
        "إرفاق المستندات الداعمة إن وجدت",
        "تأكيد بيانات التواصل",
        "مراجعة البيانات والموافقة على الإقرار",
        "إرسال الشكوى",
        "استلام رقم مرجعي وتأكيد تقديم الشكوى",
        "متابعة حالة الشكوى باستخدام الرقم المرجعي",
        "استلام الرد أو الحل المقترح",
        "قبول الحل أو طلب التصعيد عند عدم الرضا",
    ],
    "lang": "ar",
}


def _good_complaint_ai_steps():
    """A GOOD response following the requested data-reuse chain:
    identity already established -> separate service-system lookup
    for related transactions (proposed integration, not assumed) ->
    only genuinely missing info asked -> submit -> auto-track ->
    notify. Grounded in the current journey's own evidence (it shows
    a manual reference-number entry step, so the lookup stage is
    justified)."""
    return [
        {
            "name": "استقبال الشكوى وفهم المشكلة", "type": "SYSTEM", "executor": "AGENT",
            "action": "يستقبل المساعد وصف المتعامل للمشكلة.",
            "detailed_description": "يستمع المساعد لوصف المتعامل للمشكلة بلغته الطبيعية ليحدد نوع الشكوى دون الحاجة لقوائم اختيار طويلة.",
            "reasoning": "نقطة البداية من نية المتعامل.", "customer_role": "يشرح المشكلة",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "", "delivers_customer_result": False,
        },
        {
            "name": "استرجاع المعاملة المرتبطة من نظام بريد الإمارات", "type": "SYSTEM", "executor": "AGENT",
            "action": "يسترجع المساعد شحنات ومعاملات المتعامل من نظام الخدمة بناءً على هويته المؤكدة.",
            "detailed_description": "باستخدام هوية المتعامل المؤكدة مسبقًا، يستعلم المساعد من نظام بريد الإمارات عن الشحنات والمعاملات المرتبطة به ويعرضها ليختار المتعامل المعاملة المقصودة، بدل أن يكتب رقمها يدويًا.",
            "reasoning": "الخطوة الحالية كانت تطلب من العميل كتابة رقم الشحنة يدويًا؛ هذا تكامل مقترح مع نظام الخدمة نفسه وليس افتراضًا أن UAE PASS يحتوي على هذه البيانات.",
            "customer_role": "يختار المعاملة من القائمة المسترجعة",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "هوية المتعامل مؤكدة من تسجيل الدخول", "delivers_customer_result": False,
        },
        {
            "name": "طلب تفاصيل الشكوى والمرفقات الناقصة فقط", "type": "SYSTEM", "executor": "AGENT",
            "action": "يطلب المساعد تفاصيل المشكلة والمرفقات فقط إن لزم.",
            "detailed_description": "يطلب المساعد من المتعامل فقط تفاصيل المشكلة الفعلية والمرفقات الداعمة إن وُجدت، وهي المعلومات الوحيدة غير المتاحة في أي نظام.",
            "reasoning": "هذه المعلومات الوحيدة غير الموجودة مسبقًا في أي نظام.",
            "customer_role": "يكتب تفاصيل الشكوى ويرفق المستندات إن وجدت",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "المعاملة محددة", "delivers_customer_result": False,
        },
        {
            "name": "مراجعة وإرسال الشكوى", "type": "SYSTEM", "executor": "AGENT",
            "action": "يعرض المساعد ملخص الشكوى ليوافق المتعامل على إرسالها.",
            "detailed_description": "يعرض المساعد ملخص الشكوى الجاهز (المعاملة، التفاصيل، المرفقات) ليوافق المتعامل على إرسالها دون إعادة كتابة أي بيانات.",
            "reasoning": "موافقة صريحة قبل الإرسال.", "customer_role": "يوافق على الإرسال",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": True,
            "depends_on_previous": "التفاصيل مكتملة", "delivers_customer_result": False,
        },
        {
            "name": "تسليم الرقم المرجعي ومتابعة الحالة تلقائيًا", "type": "SYSTEM", "executor": "AGENT",
            "action": "يصدر النظام رقمًا مرجعيًا ويتابع حالة الشكوى تلقائيًا.",
            "detailed_description": "يصدر النظام رقمًا مرجعيًا فور الإرسال، ويتابع المساعد حالة الشكوى تلقائيًا ويشعر المتعامل بأي تحديث أو حل دون أن يحتاج للسؤال بنفسه.",
            "reasoning": "يختتم الرحلة بنتيجة واضحة ومتابعة تلقائية.",
            "customer_role": "يستلم الرقم المرجعي والتحديثات",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "الشكوى أُرسلت", "delivers_customer_result": True,
        },
    ]


def _run_complaint(ai_steps_response):
    llm = FakeLLM([json.dumps({"steps": ai_steps_response, "overall_reasoning": "تصميم يعتمد على الهوية المؤكدة واسترجاع المعاملة."}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    result = agent.run(COMPLAINT_SERVICE, {"steps": []}, relevant_standards={"applicable_standards": STANDARDS_CATALOG})
    return result, llm


def test_complaint_journey_does_not_reintroduce_a_login_stage():
    """The 14-step current journey's own login step (step 2) must not
    reappear as a customer-facing login/identity-entry stage in the
    redesigned journey -- login already happened before this journey."""
    result, _ = _run_complaint(_good_complaint_ai_steps())
    assert result["analysis_source"] == "ai"
    for step in result["future_steps"]:
        text = " ".join(str(step.get(f, "")) for f in ("name", "action", "customer_role")).lower()
        assert "تسجيل الدخول" not in text
        assert "log in" not in text and "login" not in text


def test_complaint_journey_proposes_transaction_lookup_instead_of_manual_entry():
    """The manual 'enter shipment/transaction number' step (step 5)
    must become a proposed system lookup where the assistant retrieves
    related records and the customer selects, not a re-typed number."""
    result, _ = _run_complaint(_good_complaint_ai_steps())
    future_steps = result["future_steps"]

    lookup_stages = [
        s for s in future_steps
        if "يسترجع" in str(s.get("action", "")) or "استرجاع" in str(s.get("name", ""))
    ]
    assert lookup_stages, f"Expected a retrieval/lookup stage; got names={[s['name'] for s in future_steps]}"
    lookup = lookup_stages[0]
    # Must depend on identity being established -- proving the chain
    # is identity FIRST, then a separate service-system lookup.
    assert lookup["depends_on_previous"], "The lookup stage must depend on identity being established first."
    # Must not itself be marked as requiring the customer to type a number.
    assert "يكتب الرقم" not in str(lookup.get("customer_role", ""))


def test_complaint_journey_only_asks_for_genuinely_missing_information():
    """Only the problem description / attachments should be an actual
    customer-input point -- not identity, not the transaction number."""
    result, _ = _run_complaint(_good_complaint_ai_steps())
    future_steps = result["future_steps"]
    detail_stage = next(
        (s for s in future_steps if "تفاصيل" in str(s.get("name", ""))), None
    )
    assert detail_stage is not None
    text = str(detail_stage.get("detailed_description", ""))
    assert "المشكلة" in text or "الشكوى" in text


def test_complaint_journey_reduces_customer_administrative_steps_vs_current():
    """Real quality bar: the redesigned journey must have fewer real
    customer-input touchpoints than the 14-step current journey (which
    has login, service selection, complaint-type selection, manual
    reference entry, details, attachments, contact confirmation,
    review/approval, submit -- 9+ customer-facing administrative
    actions)."""
    result, _ = _run_complaint(_good_complaint_ai_steps())
    future_steps = result["future_steps"]
    assert len(future_steps) < len(COMPLAINT_SERVICE["steps"])

    customer_admin_stages = [
        s for s in future_steps
        if str(s.get("customer_role", "")).strip()
        and str(s.get("customer_role", "")).strip() not in ("لا يوجد", "None", "none")
    ]
    # Real reduction: at most 5 genuine customer touchpoints (explain
    # problem, select the retrieved transaction, provide details,
    # approve send, receive updates) vs. 9+ administrative steps today.
    assert len(customer_admin_stages) <= 5, (
        f"Expected genuinely reduced customer touchpoints; got "
        f"{len(customer_admin_stages)}: {[s['customer_role'] for s in customer_admin_stages]}"
    )


def test_complaint_journey_prompt_carries_the_data_reuse_guidance():
    """Confirms the actual wiring: the prompt sent to the model for
    this exact scenario carries the data-reuse distinction, not just
    that the hand-crafted test fixture happens to look right."""
    _, llm = _run_complaint(_good_complaint_ai_steps())
    prompt = llm.prompts[0]
    assert "ALREADY AVAILABLE" in prompt
    assert "RETRIEVABLE VIA THIS SERVICE" in prompt
    assert "GENUINELY MISSING" in prompt
    assert "never claim the identity source" in prompt.lower() or "never claim the identity" in prompt


# ======================================================================
# Hallucination rejection: identity source falsely claimed to already
# contain service-specific records
# ======================================================================

def test_validation_flags_hallucinated_uae_pass_contains_shipments_claim():
    """The specific hallucination this feature must NOT enable: a
    stage claiming UAE PASS itself already contains shipment/
    transaction numbers. Must be flagged by validation, not silently
    accepted as a legitimate 'already available' claim."""
    future_steps = [
        {
            "step_number": 1, "name": "Confirm identity", "type": "SYSTEM", "action": "x",
            "change_type": "NEW", "reason": "New.", "standard_id": "STD-01",
            "related_standard_ids": ["STD-01"], "source_steps": [],
            "semantic_category": "execution_continuity", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT", "assistant_action": "x",
            "customer_role": "None", "visible_before_payment": True,
            "completion_evidence": "log", "has_payment": False,
            "requires_human_judgement": False, "requires_customer_approval": False,
            "depends_on_previous": "",
            "detailed_description": (
                "UAE PASS already contains all of the customer's shipment "
                "and transaction numbers, so no lookup is needed."
            ),
            "reasoning": (
                "UAE PASS already contains all of the customer's shipment "
                "and transaction numbers, so no lookup is needed."
            ),
            "analysis_source": "ai",
        },
        {
            "step_number": 2, "name": "Deliver outcome", "type": "SYSTEM", "action": "x",
            "change_type": "NEW", "reason": "New.", "standard_id": "STD-01",
            "related_standard_ids": ["STD-01"], "source_steps": [],
            "semantic_category": "customer_outcome", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT", "assistant_action": "x",
            "customer_role": "Receives result", "visible_before_payment": True,
            "completion_evidence": "log", "has_payment": False,
            "requires_human_judgement": False, "requires_customer_approval": False,
            "depends_on_previous": "Complaint filed",
            "detailed_description": "The assistant delivers the outcome with a reviewable record.",
            "reasoning": "Concludes the journey.", "analysis_source": "ai",
        },
    ]
    service = {"service_name": "X", "description": "Y", "steps": ["a", "b"]}
    redesign = {"future_steps": future_steps, "removed_steps": [], "merged_steps": [],
                "future_customer_burden_steps": 0, "future_branch_visits": 0,
                "future_manual_actions": [], "review_steps": [], "required_integrations": [],
                "automation_opportunities": [], "customer_only_actions": [], "service_classification": {}}
    metrics = calculate_metrics(service, redesign)
    zb = calculate_zero_bureaucracy_score(metrics)
    validation = ValidationAgent(llm=None).run(
        service=service, standards={"applicable_standards": STANDARDS_CATALOG}, redesign=redesign,
        metrics={**metrics, "zero_bureaucracy_score": zb},
    )
    conflation_issues = [
        i for i in validation["issues"]
        if "identity" in str(i.get("issue", "")).lower() and "not grounded" in str(i.get("issue", "")).lower()
    ]
    assert conflation_issues, f"Expected the identity/service-system conflation to be flagged; got {validation['issues']}"


def test_validation_does_not_flag_correctly_framed_integration_proposal():
    """Sanity check: a CORRECTLY framed lookup stage (identity first,
    then a separate service-system integration) must not be flagged
    by the same check -- this isn't a blanket ban on mentioning UAE
    PASS and records together, only on claiming they're the same
    source."""
    future_steps = [
        {
            "step_number": 1, "name": "Retrieve related transactions", "type": "SYSTEM", "action": "x",
            "change_type": "NEW", "reason": "New.", "standard_id": "STD-01",
            "related_standard_ids": ["STD-01"], "source_steps": [],
            "semantic_category": "execution_continuity", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT", "assistant_action": "x",
            "customer_role": "Selects the transaction", "visible_before_payment": True,
            "completion_evidence": "log", "has_payment": False,
            "requires_human_judgement": False, "requires_customer_approval": False,
            "depends_on_previous": "Identity confirmed via UAE PASS",
            "detailed_description": (
                "Using the identity already confirmed via UAE PASS, the "
                "assistant queries the service system for related "
                "shipment records and lets the customer select one."
            ),
            "reasoning": (
                "This is a proposed integration with the service's own "
                "system, not an assumption that UAE PASS itself holds "
                "shipment records."
            ),
            "analysis_source": "ai",
        },
    ]
    service = {"service_name": "X", "description": "Y", "steps": ["a"]}
    redesign = {"future_steps": future_steps, "removed_steps": [], "merged_steps": [],
                "future_customer_burden_steps": 0, "future_branch_visits": 0,
                "future_manual_actions": [], "review_steps": [], "required_integrations": [],
                "automation_opportunities": [], "customer_only_actions": [], "service_classification": {}}
    metrics = calculate_metrics(service, redesign)
    zb = calculate_zero_bureaucracy_score(metrics)
    validation = ValidationAgent(llm=None).run(
        service=service, standards={"applicable_standards": STANDARDS_CATALOG}, redesign=redesign,
        metrics={**metrics, "zero_bureaucracy_score": zb},
    )
    conflation_issues = [
        i for i in validation["issues"]
        if "identity" in str(i.get("issue", "")).lower() and "not grounded" in str(i.get("issue", "")).lower()
    ]
    assert not conflation_issues, f"Correctly framed integration must not be flagged; got {conflation_issues}"


# ======================================================================
# Regression: mailbox rental (P.O. Box) scenario referenced as the
# previously-successful baseline must keep working identically.
# ======================================================================

def test_mailbox_rental_scenario_still_keeps_plan_approval_step():
    """Exact same assertion as the pre-existing
    test_complaint_regression.py::test_payment_service_keeps_plan_approval_step
    -- re-run here as an explicit no-regression guard for this
    session's changes."""
    from agents.service_agent import ServiceAnalystAgent
    from agents.step_compliance_agent import StepComplianceAgent

    service = {
        "service_name": "استئجار صندوق بريد",
        "description": "استئجار صندوق بريد جديد للأفراد",
        "steps": [
            "العميل يقدم طلب استئجار صندوق بريد",
            "العميل يرفع صورة الهوية",
            "العميل يدفع رسوم الاستئجار",
            "النظام يصدر رقم الصندوق",
        ],
        "documents": [], "actors": [], "approvals": [], "waiting_times": [],
        "manual_actions": [], "digital_actions": [], "dependencies": [], "branch_visits": 0,
    }
    analysis = ServiceAnalystAgent(llm=None).run(service)
    enriched = {**service, "steps": analysis["steps"], "capabilities": analysis["capabilities"]}
    compliance = StepComplianceAgent(llm=None).run(enriched, analysis, {"applicable_standards": STANDARDS_CATALOG})
    redesign = JourneyBuilderAgent(llm=None).run(enriched, compliance, {"applicable_standards": STANDARDS_CATALOG})

    control_points = [
        point for step in redesign["future_steps"]
        for point in (step.get("customer_control_points") or [])
    ]
    assert any("الموافقة على الخطة" in point for point in control_points), (
        "Regression: the mailbox-rental baseline must still show the "
        "plan-approval control point exactly as before."
    )


if __name__ == "__main__":
    test_complaint_journey_does_not_reintroduce_a_login_stage()
    test_complaint_journey_proposes_transaction_lookup_instead_of_manual_entry()
    test_complaint_journey_only_asks_for_genuinely_missing_information()
    test_complaint_journey_reduces_customer_administrative_steps_vs_current()
    test_complaint_journey_prompt_carries_the_data_reuse_guidance()
    test_validation_flags_hallucinated_uae_pass_contains_shipments_claim()
    test_validation_does_not_flag_correctly_framed_integration_proposal()
    test_mailbox_rental_scenario_still_keeps_plan_approval_step()
    print("ALL SESSION-8 ROOT-CAUSE-FIX TESTS PASSED")
