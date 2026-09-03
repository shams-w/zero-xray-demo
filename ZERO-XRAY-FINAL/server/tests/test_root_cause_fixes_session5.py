"""Regression tests for the FIFTH root-cause-fix pass: Journey Builder
redesigned as a genuine full-service-reengineering AI agent, and
Validation Agent evaluating real journey substance rather than shape.

Covers (per the explicit request this session):
  1. AI_DESIGNED is never returned as a change_type -- the agent now
     classifies every AI-designed stage into the EXISTING backend/
     frontend contract (KEPT/MERGED/AUTOMATED/NEW), computed
     generically from how much of each current step is reflected in
     the stage.
  2. HUMAN is not used when the assistant/system can do the step.
  3. No payment stage precedes the value/selection it depends on.
  4. Confirmation/payment comes after the request is prepared
     (fee/summary), and a redundant "explain fee" + "collect payment"
     pair gets merged into one stage.
  5. Dependencies/ordering are validated for real by ValidationAgent.
  6. Duplicate/near-duplicate stages get merged, and the validator
     flags them if they weren't.
  7. An AI-generated journey starts from outcome/intent, not from
     reordering the current steps 1:1.
  8. Everything above is domain-generic -- proven by running two
     unrelated service types through the identical code path.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.journey_builder_agent import JourneyBuilderAgent
from agents.validation_agent import ValidationAgent
from core.standards_catalog import STANDARDS_CATALOG, valid_standard_ids
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


def _stage(name, action, detail, reasoning="Because this follows the service's own logic and stated evidence.",
           type_="SYSTEM", executor="AGENT", has_payment=False, payment_reason="",
           human=False, human_reason="", customer_approval=False, depends_on="",
           delivers=False, customer_role="Confirms the outcome"):
    return {
        "name": name, "type": type_, "executor": executor,
        "action": action, "detailed_description": detail,
        "reasoning": reasoning, "customer_role": customer_role,
        "has_payment": has_payment, "payment_reasoning": payment_reason,
        "requires_human_judgement": human, "human_judgement_reason": human_reason,
        "requires_customer_approval": customer_approval,
        "depends_on_previous": depends_on, "delivers_customer_result": delivers,
    }


# ======================================================================
# 1) change_type contract: AI_DESIGNED must never appear
# ======================================================================

def test_ai_designed_never_returned_as_change_type():
    """The producer must never emit a change_type outside the backend/
    frontend's existing vocabulary (KEPT/MERGED/REMOVED/AUTOMATED/
    NEW) -- classification is derived from actual overlap with the
    current steps, not a fixed label."""
    steps = [
        _stage(
            "Consolidated intake", "Assistant gathers everything needed at once.",
            "The assistant collects the request together with the uploaded documents, reusing existing profile data instead of asking the customer to log in and fill a separate form.",
            reasoning="Merges the login, form-filling and document-upload current steps.",
        ),
        _stage(
            "Deliver outcome", "Customer receives the final result.",
            "The assistant delivers the final outcome directly with a reviewable confirmation record, concluding the journey.",
            reasoning="Concludes with a clear customer-visible result.", delivers=True,
        ),
    ]
    llm = FakeLLM([json.dumps({"overall_reasoning": "Outcome-first redesign.", "steps": steps}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Generic request service",
        "description": "A generic government request",
        "steps": [
            "Customer logs into the portal",
            "Customer fills out the request form",
            "Customer uploads supporting documents",
        ],
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": STANDARDS_CATALOG})
    change_types = {s["change_type"] for s in result["future_steps"]}
    assert "AI_DESIGNED" not in change_types
    assert change_types.issubset({"KEPT", "MERGED", "REMOVED", "AUTOMATED", "NEW"})


def test_ai_designed_change_type_still_tolerated_defensively_by_validator():
    """Backward-compat safety net: even though the producer no longer
    emits it, the validator still tolerates AI_DESIGNED defensively
    (e.g. cached/legacy redesigns) rather than crashing or zeroing
    compliance for it."""
    future_steps = [{
        "step_number": 1, "name": "Legacy stage", "type": "SYSTEM",
        "action": "x", "change_type": "AI_DESIGNED", "reason": "Legacy reasoning text.",
        "standard_id": None, "related_standard_ids": [], "source_steps": [],
        "semantic_category": "execution_continuity", "component_categories": [],
        "implementation_status": "PROPOSED", "customer_burden": False,
        "customer_control_points": [], "owner": "ASSISTANT",
        "assistant_action": "x", "customer_role": "None",
        "visible_before_payment": True, "completion_evidence": "log",
        "has_payment": False, "requires_human_judgement": False,
        "requires_customer_approval": False, "depends_on_previous": "",
        "detailed_description": "Legacy AI-designed stage from before the change_type fix.",
        "reasoning": "Legacy.", "analysis_source": "ai",
    }]
    service = {"service_name": "X", "description": "Y", "steps": ["a"]}
    redesign = {"future_steps": future_steps, "removed_steps": [], "merged_steps": [],
                "future_customer_burden_steps": 0, "future_branch_visits": 0,
                "future_manual_actions": [], "review_steps": [], "required_integrations": [],
                "automation_opportunities": [], "customer_only_actions": [], "service_classification": {}}
    metrics = calculate_metrics(service, redesign)
    zb = calculate_zero_bureaucracy_score(metrics)
    validation = ValidationAgent(llm=None).run(
        service=service, standards={"applicable_standards": []}, redesign=redesign,
        metrics={**metrics, "zero_bureaucracy_score": zb},
    )
    change_type_issues = [i for i in validation["issues"] if "change_type" in str(i.get("issue", "")).lower()]
    assert not change_type_issues


# ======================================================================
# 2) HUMAN not used when system/agent can do it; unjustified HUMAN flagged
# ======================================================================

def test_validation_flags_human_stage_with_no_justification():
    """A HUMAN-typed stage with no real reasoning text must be flagged
    -- proof the validator checks SUBSTANCE, not just shape."""
    future_steps = [
        {
            "step_number": 1, "name": "Staff review", "type": "HUMAN",
            "action": "x", "change_type": "KEPT", "reason": "",
            "standard_id": None, "related_standard_ids": [], "source_steps": [],
            "semantic_category": "human_control", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "HUMAN",
            "assistant_action": "x", "customer_role": "None",
            "visible_before_payment": True, "completion_evidence": "log",
            "has_payment": False, "requires_human_judgement": True,
            "requires_customer_approval": False, "depends_on_previous": "",
            "detailed_description": "A staff member reviews this.",
            "reasoning": "", "analysis_source": "ai",
        },
        {
            "step_number": 2, "name": "Deliver outcome", "type": "SYSTEM",
            "action": "x", "change_type": "NEW", "reason": "New capability.",
            "standard_id": "STD-01", "related_standard_ids": ["STD-01"], "source_steps": [],
            "semantic_category": "customer_outcome", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT",
            "assistant_action": "x", "customer_role": "Receives result",
            "visible_before_payment": True, "completion_evidence": "log",
            "has_payment": False, "requires_human_judgement": False,
            "requires_customer_approval": False, "depends_on_previous": "Review complete",
            "detailed_description": "The assistant delivers the outcome to the customer with a reviewable record.",
            "reasoning": "Concludes the journey.", "analysis_source": "ai",
        },
    ]
    service = {"service_name": "X", "description": "Y", "steps": ["a", "b", "c"]}
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
    human_issues = [i for i in validation["issues"] if "human judgement" in str(i.get("issue", "")).lower()]
    assert human_issues, f"Expected an unjustified-HUMAN issue; got {validation['issues']}"


def test_journey_builder_classifies_manual_step_now_automated_as_automated_not_human():
    """When the AI correctly turns a manual/staff step into a
    SYSTEM-executed one, the derived change_type must be AUTOMATED
    (not KEPT, not a fabricated HUMAN requirement)."""
    steps = [
        _stage(
            "Automated eligibility check", "System checks eligibility automatically.",
            "The assistant automatically checks eligibility against backend records instead of requiring a staff member to manually review the request.",
            reasoning="Removes the manual employee review step by automating the check.",
        ),
        _stage(
            "Deliver outcome", "Customer receives the result.",
            "The assistant delivers the final outcome with a reviewable confirmation record.",
            delivers=True,
        ),
    ]
    llm = FakeLLM([json.dumps({"overall_reasoning": "Automates manual review.", "steps": steps}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Generic approval service",
        "description": "A generic approval",
        "steps": ["Employee manually reviews the request and checks eligibility"],
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": STANDARDS_CATALOG})
    automated = [s for s in result["future_steps"] if s["change_type"] == "AUTOMATED"]
    assert automated, f"Expected an AUTOMATED stage; got {[(s['name'], s['change_type']) for s in result['future_steps']]}"
    assert automated[0]["type"] == "SYSTEM"


# ======================================================================
# 3 & 4) payment/dependency ordering + fee/payment consolidation
# ======================================================================

def test_validation_flags_payment_with_no_traceable_dependency_on_ai_path():
    """On the AI path specifically, a payment stage past the first
    position with no stated dependency must be flagged (the amount
    being charged isn't traceably determined)."""
    future_steps = [
        {
            "step_number": 1, "name": "Intake", "type": "SYSTEM", "action": "x",
            "change_type": "NEW", "reason": "New consolidated intake.", "standard_id": "STD-01",
            "related_standard_ids": ["STD-01"], "source_steps": [], "semantic_category": "execution_continuity",
            "component_categories": [], "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT", "assistant_action": "x",
            "customer_role": "States intent", "visible_before_payment": True, "completion_evidence": "log",
            "has_payment": False, "requires_human_judgement": False, "requires_customer_approval": False,
            "depends_on_previous": "", "detailed_description": "The assistant gathers everything needed for the request.",
            "reasoning": "Entry point.", "analysis_source": "ai",
        },
        {
            "step_number": 2, "name": "Collect payment", "type": "SYSTEM", "action": "x",
            "change_type": "NEW", "reason": "Payment.", "standard_id": "STAGE-07",
            "related_standard_ids": ["STAGE-07"], "source_steps": [], "semantic_category": "payment",
            "component_categories": ["payment"], "implementation_status": "PROPOSED", "customer_burden": False,
            "customer_control_points": [], "owner": "ASSISTANT", "assistant_action": "x",
            "customer_role": "Approves payment", "visible_before_payment": True, "completion_evidence": "log",
            "has_payment": True, "requires_human_judgement": False, "requires_customer_approval": False,
            "depends_on_previous": "", "detailed_description": "The assistant charges the customer for an amount that was never actually calculated by an earlier stage.",
            "reasoning": "Collects payment.", "analysis_source": "ai",
        },
    ]
    service = {"service_name": "X", "description": "Y", "steps": ["a", "b"]}
    redesign = {"analysis_source": "ai", "future_steps": future_steps, "removed_steps": [], "merged_steps": [],
                "future_customer_burden_steps": 0, "future_branch_visits": 0,
                "future_manual_actions": [], "review_steps": [], "required_integrations": [],
                "automation_opportunities": [], "customer_only_actions": [], "service_classification": {}}
    metrics = calculate_metrics(service, redesign)
    zb = calculate_zero_bureaucracy_score(metrics)
    validation = ValidationAgent(llm=None).run(
        service=service, standards={"applicable_standards": STANDARDS_CATALOG}, redesign=redesign,
        metrics={**metrics, "zero_bureaucracy_score": zb},
    )
    payment_issues = [i for i in validation["issues"] if "traceably determined" in str(i.get("issue", ""))]
    assert payment_issues


def test_journey_builder_merges_redundant_fee_explanation_and_payment_stages():
    """A stage that only explains the fee, immediately followed by
    the actual payment stage with no independent decision in between,
    must be merged into one."""
    steps = [
        _stage("Select package", "Assistant recommends and customer confirms a package.",
               "The assistant recommends the best-fit package based on stated needs; the customer confirms or changes it.",
               reasoning="Package determines the fee.", customer_role="Confirms package"),
        _stage("Explain the fee", "Assistant shows the total fee for the selected package.",
               "The assistant calculates and displays the total amount due based on the selected package.",
               reasoning="Fee depends on the package.", depends_on="Package selected", customer_role="Reviews fee"),
        _stage("Collect payment", "Customer pays the confirmed amount.",
               "The assistant collects payment for the confirmed amount through the government payment gateway.",
               has_payment=True, payment_reason="Amount known after package and fee confirmed.",
               depends_on="Fee confirmed", customer_role="Approves payment"),
        _stage("Deliver result", "Customer receives the outcome.",
               "The assistant delivers the final outcome with a reviewable record, concluding the journey.",
               depends_on="Payment completed", delivers=True, customer_role="Receives outcome"),
    ]
    llm = FakeLLM([json.dumps({"overall_reasoning": "Package -> fee -> pay -> deliver.", "steps": steps}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Generic paid service", "description": "A generic paid service",
        "steps": ["Customer selects package", "System calculates fee", "Customer pays", "Customer receives result"],
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []})
    future_steps = result["future_steps"]
    assert len(future_steps) == 3, f"Expected the fee-explanation and payment stages merged into one; got {[s['name'] for s in future_steps]}"
    payment_stage = next(s for s in future_steps if s["has_payment"])
    assert "fee" in payment_stage["detailed_description"].lower() or "amount" in payment_stage["detailed_description"].lower()


# ======================================================================
# 5 & 6) validation checks substance: ordering, duplicates
# ======================================================================

def test_validation_flags_near_duplicate_future_stages():
    """Two future stages describing essentially the same action must
    be flagged as an unmerged duplicate."""
    future_steps = [
        {
            "step_number": 1, "name": "Review the request", "type": "SYSTEM", "action": "The assistant reviews the submitted request",
            "change_type": "NEW", "reason": "New.", "standard_id": "STD-01", "related_standard_ids": ["STD-01"],
            "source_steps": [], "semantic_category": "execution_continuity", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False, "customer_control_points": [],
            "owner": "ASSISTANT", "assistant_action": "x", "customer_role": "None",
            "visible_before_payment": True, "completion_evidence": "log", "has_payment": False,
            "requires_human_judgement": False, "requires_customer_approval": False, "depends_on_previous": "",
            "detailed_description": "The assistant reviews the submitted request for completeness and accuracy.",
            "reasoning": "x", "analysis_source": "ai",
        },
        {
            "step_number": 2, "name": "Check the request", "type": "SYSTEM", "action": "The assistant checks the submitted request",
            "change_type": "NEW", "reason": "New.", "standard_id": "STD-01", "related_standard_ids": ["STD-01"],
            "source_steps": [], "semantic_category": "execution_continuity", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False, "customer_control_points": [],
            "owner": "ASSISTANT", "assistant_action": "x", "customer_role": "None",
            "visible_before_payment": True, "completion_evidence": "log", "has_payment": False,
            "requires_human_judgement": False, "requires_customer_approval": False, "depends_on_previous": "",
            "detailed_description": "The assistant checks the submitted request for completeness and accuracy.",
            "reasoning": "x", "analysis_source": "ai",
        },
        {
            "step_number": 3, "name": "Deliver outcome", "type": "SYSTEM", "action": "Customer receives result",
            "change_type": "NEW", "reason": "New.", "standard_id": "STD-01", "related_standard_ids": ["STD-01"],
            "source_steps": [], "semantic_category": "customer_outcome", "component_categories": [],
            "implementation_status": "PROPOSED", "customer_burden": False, "customer_control_points": [],
            "owner": "ASSISTANT", "assistant_action": "x", "customer_role": "Receives result",
            "visible_before_payment": True, "completion_evidence": "log", "has_payment": False,
            "requires_human_judgement": False, "requires_customer_approval": False, "depends_on_previous": "",
            "detailed_description": "The assistant delivers the final result to the customer with a reviewable record.",
            "reasoning": "x", "analysis_source": "ai",
        },
    ]
    service = {"service_name": "X", "description": "Y", "steps": ["a", "b", "c"]}
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
    dup_issues = [i for i in validation["issues"] if "same action" in str(i.get("issue", "")).lower()]
    assert dup_issues, f"Expected a duplicate-stage issue; got {validation['issues']}"


def test_validation_flags_type_owner_inconsistency():
    """A SYSTEM-typed stage owned by HUMAN (or vice versa) must be
    flagged as an internal inconsistency."""
    future_steps = [{
        "step_number": 1, "name": "Weird stage", "type": "SYSTEM", "action": "x",
        "change_type": "NEW", "reason": "x", "standard_id": "STD-01", "related_standard_ids": ["STD-01"],
        "source_steps": [], "semantic_category": "execution_continuity", "component_categories": [],
        "implementation_status": "PROPOSED", "customer_burden": False, "customer_control_points": [],
        "owner": "HUMAN", "assistant_action": "x", "customer_role": "None",
        "visible_before_payment": True, "completion_evidence": "log", "has_payment": False,
        "requires_human_judgement": False, "requires_customer_approval": False, "depends_on_previous": "",
        "detailed_description": "This is typed SYSTEM but owned by HUMAN, which should never happen.",
        "reasoning": "x", "analysis_source": "ai",
    }]
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
    inconsistency_issues = [i for i in validation["issues"] if "inconsistent" in str(i.get("issue", "")).lower()]
    assert inconsistency_issues


# ======================================================================
# 7 & 8) outcome-first + genericity
# ======================================================================

def test_ai_journey_is_not_a_reordering_of_current_steps():
    """An AI-generated journey must reduce real stage count relative
    to the current journey, not merely reorder/reword it 1:1."""
    current = [
        "Customer logs into the portal",
        "Customer selects the service",
        "Customer fills out the form",
        "Customer uploads documents",
        "Employee manually reviews the request",
        "System issues the result",
    ]
    steps = [
        _stage("Consolidated login and intake", "Assistant handles login, service selection, form filling and document upload in one step.",
               "The assistant logs the customer in, selects the service, fills out the form and uploads the documents in one consolidated step, reusing already-available profile data instead of four separate portal steps.",
               reasoning="Consolidates the login, service selection, form-filling and document-upload current steps into one."),
        _stage("Automated review", "System automatically reviews the request.",
               "The assistant automatically validates the request against backend rules instead of requiring a manual employee to review the request.",
               reasoning="Automates the manual employee review step."),
        _stage("Deliver outcome", "Customer receives the result.",
               "The assistant issues the result and delivers the final outcome to the customer with a reviewable record, concluding the journey.",
               delivers=True),
    ]
    llm = FakeLLM([json.dumps({"overall_reasoning": "Outcome-first, heavily consolidated.", "steps": steps}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    service = {"service_name": "Generic request", "description": "A generic government request", "steps": current}
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": STANDARDS_CATALOG})
    assert result["analysis_source"] == "ai"
    assert len(result["future_steps"]) < len(current)
    assert any(s["change_type"] == "MERGED" for s in result["future_steps"])


def test_generic_decision_logic_not_hardcoded_to_mailbox_service():
    """Grep-level guarantee: no production code path references
    mailbox-specific vocabulary. The decision logic (package/duration/
    human-vs-system) must come from generic keyword/overlap signals
    only."""
    import subprocess
    result = subprocess.run(
        ["grep", "-rEil", "mailbox|صندوق البريد", "agents", "core"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", f"Found service-specific hardcoding: {result.stdout}"


if __name__ == "__main__":
    test_ai_designed_never_returned_as_change_type()
    test_ai_designed_change_type_still_tolerated_defensively_by_validator()
    test_validation_flags_human_stage_with_no_justification()
    test_journey_builder_classifies_manual_step_now_automated_as_automated_not_human()
    test_validation_flags_payment_with_no_traceable_dependency_on_ai_path()
    test_journey_builder_merges_redundant_fee_explanation_and_payment_stages()
    test_validation_flags_near_duplicate_future_stages()
    test_validation_flags_type_owner_inconsistency()
    test_ai_journey_is_not_a_reordering_of_current_steps()
    test_generic_decision_logic_not_hardcoded_to_mailbox_service()
    print("ALL SESSION-5 ROOT-CAUSE-FIX TESTS PASSED")
