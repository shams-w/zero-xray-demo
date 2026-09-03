"""Regression tests for the FOURTH root-cause-fix pass.

    1) JOURNEY quality signal -> GapAnalysisAgent's structured gaps
       (standard_id/severity/recommendation) were never actually
       passed into the journey builder's prompt, so the AI redesign
       could only be judged on generic principles/step count, never
       on whether it closes THIS service's real identified gaps.

    2) VALIDATION (step compliance) -> the AI step-compliance review
       was all-or-nothing: any mismatch between the AI's assessment
       count and the reviewable step count (a single truncated/
       skipped step) discarded the ENTIRE AI review, even when most
       steps were validly, genuinely reviewed.

    3) GENERICITY -> the whole pipeline (service extraction, gap
       identification, journey redesign) must behave identically in
       shape across completely unrelated service domains -- nothing
       here may be tuned to one specific service.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.service_agent import ServiceAnalystAgent
from agents.standards_agent import StandardsAgent
from agents.gap_agent import GapAnalysisAgent
from agents.step_compliance_agent import StepComplianceAgent
from agents.journey_builder_agent import JourneyBuilderAgent
from agents.validation_agent import ValidationAgent
from core.standards_catalog import STANDARDS_CATALOG
from core.rules import calculate_metrics
from core.scoring import calculate_zero_bureaucracy_score

STANDARDS_SEED = {"applicable_standards": STANDARDS_CATALOG}


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


# ======================================================================
# 1) JOURNEY: gaps are actually threaded into the prompt
# ======================================================================

def test_journey_builder_prompt_includes_identified_gaps():
    """The gaps GapAnalysisAgent identified for this service must show
    up verbatim (standard_id + description) in the journey builder's
    prompt -- proving they're actually used as a design input, not
    just accepted-and-ignored."""
    gaps = {
        "gaps": [
            {
                "category": "Duplicate Data",
                "description": "Customer re-enters the same address twice across two steps.",
                "standard_id": "STD-02",
                "severity": "HIGH",
                "recommendation": "Capture the address once and reuse it downstream.",
            }
        ]
    }
    good_steps = [
        {
            "name": "Consolidated intake", "type": "SYSTEM", "executor": "AGENT",
            "action": "Collects everything needed once.",
            "detailed_description": "The assistant collects the request once using existing profile data, removing duplicate entry.",
            "reasoning": "Addresses the duplicate-data gap directly.",
            "customer_role": "Confirms details", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "", "delivers_customer_result": False,
        },
        {
            "name": "Deliver outcome", "type": "SYSTEM", "executor": "AGENT",
            "action": "Customer receives the result.",
            "detailed_description": "The assistant delivers the final outcome directly to the customer with a reviewable record.",
            "reasoning": "Concludes the journey.", "customer_role": "Receives result",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Intake complete", "delivers_customer_result": True,
        },
    ]
    llm = FakeLLM([
        json.dumps({"overall_reasoning": "Closes the duplicate-data gap.", "steps": good_steps}, ensure_ascii=False),
    ])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Generic request service",
        "description": "A generic government request",
        "steps": ["Customer enters address", "Customer enters address again to confirm", "Staff processes request"],
    }
    agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []}, gaps=gaps)

    assert llm.calls == 1
    prompt = llm.prompts[0]
    assert "Customer re-enters the same address twice" in prompt
    assert "STD-02" in prompt
    assert "Capture the address once and reuse it downstream" in prompt


def test_journey_builder_run_accepts_missing_gaps_backward_compatible():
    """Existing callers that don't pass `gaps` at all must keep
    working unchanged (backward compatibility for the new parameter)."""
    good_steps = [
        {
            "name": "Do the thing", "type": "SYSTEM", "executor": "AGENT",
            "action": "Handles the request end to end.",
            "detailed_description": "The assistant handles the request end to end without manual steps.",
            "reasoning": "Simplest possible design.", "customer_role": "Confirms",
            "has_payment": False, "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "", "delivers_customer_result": True,
        },
    ]
    llm = FakeLLM([json.dumps({"overall_reasoning": "Simple.", "steps": good_steps}, ensure_ascii=False)])
    agent = JourneyBuilderAgent(llm)
    service = {"service_name": "X", "description": "Y", "steps": ["Do a thing"]}
    result = agent.run(service, {"steps": []}, {"applicable_standards": []})  # positional, no gaps
    assert result.get("future_steps")


# ======================================================================
# 2) VALIDATION (step compliance): partial AI acceptance
# ======================================================================

def test_step_compliance_agent_keeps_partial_ai_review_on_count_mismatch():
    """Real-world failure shape: the AI reviewed 3 of 4 steps validly
    and truncated/skipped the 4th. The old code discarded the AI's
    3 genuinely-reasoned assessments along with the missing one. The
    fix must keep the 3 valid ones and use the deterministic baseline
    only for the step the AI didn't cover."""
    service = {
        "service_name": "Generic service",
        "steps": [
            "Customer submits the request",
            "Employee manually reviews the request",
            "System issues the result",
            "Customer receives the result",
        ],
        "protected_steps": [],
    }
    service_analysis = {"objective": "Get the result", "friction_points": []}
    relevant_standards = {"applicable_standards": [
        {"standard_id": "STD-02", "title": "Burden Shifts to the Assistant"},
    ]}

    # AI only returns assessments for steps 1, 2, 3 -- step 4 missing
    # (simulates truncation), and previously this would have discarded
    # ALL FOUR baseline-derived-but-AI-reviewed entries.
    ai_response = json.dumps({
        "assessments": [
            {"step_number": 1, "status": "PASS", "decision": "KEEP", "reason": "Fine as-is.", "standard_id": ""},
            {"step_number": 2, "status": "FAIL", "decision": "AUTOMATE", "reason": "Manual review can be automated.", "standard_id": "STD-02"},
            {"step_number": 3, "status": "PASS", "decision": "KEEP", "reason": "System step, fine.", "standard_id": ""},
        ]
    }, ensure_ascii=False)

    llm = FakeLLM([ai_response])
    agent = StepComplianceAgent(llm)
    result = agent.run(service, service_analysis, relevant_standards)

    assessments = {item["step_number"]: item for item in result["step_assessment"]}
    assert assessments[2]["decision"] == "AUTOMATE", (
        "Step 2's genuine AI review must survive even though step 4 "
        f"was missing from the response; got {assessments[2]}"
    )
    assert assessments[2].get("analysis_source") == "ai"
    # Step 4 wasn't in the AI's response -- it must still be present
    # (from the deterministic baseline), not silently dropped.
    assert 4 in assessments
    assert result["analysis_source"] == "ai"


def test_step_compliance_agent_still_falls_back_when_nothing_usable():
    """If the AI's response has zero salvageable assessments (every
    item malformed), the whole thing must still fall back to the
    deterministic baseline -- partial retention isn't a loophole for
    garbage output."""
    service = {
        "service_name": "Generic service",
        "steps": ["Customer submits the request", "Employee manually reviews it"],
        "protected_steps": [],
    }
    ai_response = json.dumps({
        "assessments": [
            {"step_number": "not-a-number", "status": "WEIRD", "decision": "??", "reason": ""},
            {"step_number": 999, "status": "PASS", "decision": "KEEP", "reason": "Out of range."},
        ]
    }, ensure_ascii=False)
    llm = FakeLLM([ai_response])
    agent = StepComplianceAgent(llm)
    result = agent.run(service, {}, {"applicable_standards": []})
    assert result["analysis_source"] == "template"


# ======================================================================
# 3) GENERICITY: two unrelated service domains, same pipeline shape
# ======================================================================

def _run_full_pipeline(service, journey_steps_response):
    """Drives the real production agent chain (mirrors graph/workflow.
    py's order) with a FakeLLM that answers generically based on
    prompt content -- no per-domain branching in the test harness
    itself, proving the AGENTS' own logic is what's generic."""

    class RoutingLLM:
        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt, user_prompt, max_new_tokens=None, temperature=0, timeout=None):
            self.calls += 1
            if "Design the proposed FUTURE journey" in user_prompt:
                return json.dumps({
                    "overall_reasoning": "Generic outcome-first redesign.",
                    "steps": journey_steps_response,
                }, ensure_ascii=False)
            if "STANDARDS CHECKLIST" in user_prompt:
                return json.dumps({
                    "selections": {
                        item["standard_id"]: {
                            "applicable": item["standard_id"] in ("STD-01", "STD-02"),
                            "why_it_applies": "Applies generically to this service's own evidence." if item["standard_id"] in ("STD-01", "STD-02") else "",
                        }
                        for item in STANDARDS_CATALOG
                    }
                }, ensure_ascii=False)
            if '"gaps"' in user_prompt:
                return json.dumps({"gaps": [
                    {"category": "Manual Work", "description": "A manual step exists that could be automated.", "standard_id": "STD-02", "severity": "MEDIUM", "recommendation": "Automate it.", "expected_impact": "Faster turnaround."}
                ]}, ensure_ascii=False)
            if '"objective"' in user_prompt:
                return json.dumps({"objective": "Get the outcome delivered.", "friction_points": []}, ensure_ascii=False)
            if '"steps"' in user_prompt and "RAW LINES" in user_prompt:
                return json.dumps({"steps": service["steps"]}, ensure_ascii=False)
            if '"has_payment"' in user_prompt:
                return json.dumps({
                    "has_payment": False, "payment_evidence": "",
                    "has_documents": False, "documents_evidence": "",
                    "has_physical_visit": False, "visit_evidence": "",
                    "has_human_approval": True, "human_approval_evidence": service["steps"][1] if len(service["steps"]) > 1 else "",
                }, ensure_ascii=False)
            if '"assessments"' in user_prompt:
                return json.dumps({"assessments": []}, ensure_ascii=False)
            return ""

    llm = RoutingLLM()
    service_agent = ServiceAnalystAgent(llm)
    standards_agent = StandardsAgent(llm)
    gap_agent = GapAnalysisAgent(llm)
    step_compliance_agent = StepComplianceAgent(llm)
    journey_builder_agent = JourneyBuilderAgent(llm)
    validation_agent = ValidationAgent(llm)

    service_analysis = service_agent.run(service)
    relevant_standards = standards_agent.run(service_analysis, STANDARDS_SEED)
    gaps = gap_agent.run(service_analysis, relevant_standards)
    step_compliance = step_compliance_agent.run(service, service_analysis, relevant_standards)
    redesign = journey_builder_agent.run(service, step_compliance, relevant_standards, gaps)
    metrics = calculate_metrics(service, redesign)
    zb_score = calculate_zero_bureaucracy_score(metrics)
    validation = validation_agent.run(
        service=service, standards=relevant_standards, redesign=redesign,
        metrics={**metrics, "zero_bureaucracy_score": zb_score},
    )
    return {
        "service_analysis": service_analysis,
        "redesign": redesign,
        "validation": validation,
    }


def _consolidated_two_stage_journey(outcome_name):
    return [
        {
            "name": "Consolidated intake and processing", "type": "SYSTEM", "executor": "AGENT",
            "action": "Assistant handles intake and processing automatically.",
            "detailed_description": "The assistant collects the request once and processes it automatically using available data, removing manual handling.",
            "reasoning": "Consolidates redundant current steps into one AI-driven stage.",
            "customer_role": "States what they need", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "", "delivers_customer_result": False,
        },
        {
            "name": f"Deliver {outcome_name}", "type": "SYSTEM", "executor": "AGENT",
            "action": "Customer receives the final outcome.",
            "detailed_description": f"The assistant delivers the {outcome_name} directly to the customer with a reviewable confirmation record.",
            "reasoning": "Concludes the journey with a clear result.",
            "customer_role": "Receives the outcome", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Processing complete", "delivers_customer_result": True,
        },
    ]


def test_pipeline_is_generic_across_two_unrelated_service_domains():
    """Two services from completely unrelated domains (a birth
    certificate request and a business trade-license renewal) must
    both go through service extraction -> standards -> gaps -> journey
    redesign -> validation and come out with the SAME kind of
    consolidated, AI-designed outcome -- proving nothing in the
    pipeline is tuned to one specific service."""
    service_a = {
        "service_name": "Birth certificate issuance",
        "description": "A parent requests an official birth certificate for their child.",
        "steps": [
            "Customer logs into the portal and fills out the birth certificate request form",
            "Customer uploads the hospital birth notification and the parents' Emirates IDs",
            "Employee manually reviews the submitted documents",
            "System issues the birth certificate as a PDF",
        ],
        "lang": "en",
    }
    service_b = {
        "service_name": "Trade license renewal",
        "description": "A business owner renews their commercial trade license.",
        "steps": [
            "Owner logs into the business portal and selects license renewal",
            "Owner uploads the tenancy contract and prior license copy",
            "Employee manually checks for outstanding violations",
            "System issues the renewed trade license",
        ],
        "lang": "en",
    }

    for service, outcome in ((service_a, "certificate"), (service_b, "renewed license")):
        result = _run_full_pipeline(service, _consolidated_two_stage_journey(outcome))
        redesign = result["redesign"]
        future_steps = redesign.get("future_steps", [])

        assert redesign.get("analysis_source") == "ai", (
            f"Expected AI-designed journey for {service['service_name']!r}, "
            f"got analysis_source={redesign.get('analysis_source')!r}"
        )
        assert len(future_steps) < len(service["steps"]), (
            f"Expected real consolidation for {service['service_name']!r}: "
            f"{len(future_steps)} future stages vs {len(service['steps'])} current steps."
        )
        assert any(s.get("delivers_customer_result") or s.get("semantic_category") == "customer_outcome" for s in future_steps)
        # No cross-contamination: nothing from one service's domain
        # vocabulary should appear in the other's redesigned journey.
        other_word = "trade license" if service is service_a else "birth certificate"
        for step in future_steps:
            text = " ".join(str(step.get(f, "")) for f in ("name", "action", "detailed_description")).lower()
            assert other_word not in text


if __name__ == "__main__":
    test_journey_builder_prompt_includes_identified_gaps()
    test_journey_builder_run_accepts_missing_gaps_backward_compatible()
    test_step_compliance_agent_keeps_partial_ai_review_on_count_mismatch()
    test_step_compliance_agent_still_falls_back_when_nothing_usable()
    test_pipeline_is_generic_across_two_unrelated_service_domains()
    print("ALL SESSION-4 ROOT-CAUSE-FIX TESTS PASSED")
