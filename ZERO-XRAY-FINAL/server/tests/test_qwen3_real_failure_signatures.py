"""
Regression tests reproducing the EXACT failure signatures reported from
a real Ollama 0.32.15 + qwen3:4b run (not the mock server):

    Service AI   -> "14 steps from 8 raw lines" -> fallback
    Standards AI -> "no valid standard_ids" -> fallback
    Gaps AI      -> "no valid gaps" -> fallback
    Journey AI   -> "unusable output" -> fallback

Each test feeds a FakeLLM a canned response shaped exactly like the
real qwen3:4b output that triggered the bug (over-split-but-grounded
steps, ids echoed with their titles attached, a gaps array truncated
mid-object, a journey where one stage has a thin description) and
asserts the agent now ACCEPTS it (analysis_source reports AI, not
"template") instead of silently discarding real model output.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.service_agent import ServiceAnalystAgent
from agents.standards_agent import StandardsAgent
from agents.gap_agent import GapAnalysisAgent
from agents.journey_builder_agent import JourneyBuilderAgent
from core.standards_catalog import STANDARDS_CATALOG


class FakeLLM:
    """Returns pre-scripted responses in call order, mimicking exactly
    what a real Ollama /api/chat call would hand back as
    message.content (already extracted from the JSON envelope, since
    that's the contract LocalLLM.generate() honors)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, system_prompt, user_prompt, max_new_tokens=None, temperature=0, timeout=None):
        self.calls += 1
        if not self._responses:
            return ""
        return self._responses.pop(0)


def test_service_agent_accepts_more_steps_than_raw_lines_when_grounded():
    """Real bug: qwen3:4b legitimately split 8 raw lines (some of them
    compound sentences) into 14 real, text-grounded steps. The old
    code rejected this outright just because 14 > 8."""
    raw_lines = [
        "Customer submits the application form and uploads a copy of the national ID",
        "Employee reviews the application, checks eligibility, then forwards it to the supervisor for approval",
        "Supervisor approves or rejects the request",
        "System generates the certificate and sends it to the customer by email",
        "Customer pays the applicable fee before the certificate is released",
        "Customer visits the branch to collect a printed copy if needed",
        "System logs the transaction for audit purposes",
        "Customer can submit a complaint if the certificate contains an error",
    ]
    ai_steps = [
        "Customer submits the application form",
        "Customer uploads a copy of the national ID",
        "Employee reviews the application",
        "Employee checks eligibility",
        "Employee forwards the application to the supervisor for approval",
        "Supervisor approves the request",
        "Supervisor rejects the request",
        "System generates the certificate",
        "System sends the certificate to the customer by email",
        "Customer pays the applicable fee before the certificate is released",
        "Customer visits the branch to collect a printed copy if needed",
        "System logs the transaction for audit purposes",
        "Customer submits a complaint if the certificate contains an error",
        "System reviews the complaint",
    ]
    assert len(ai_steps) == 14 and len(raw_lines) == 8

    llm = FakeLLM([
        json.dumps({"steps": ai_steps}, ensure_ascii=False),
        # objective/friction call
        json.dumps({"objective": "Get a certificate issued", "friction_points": ["Branch visit required"]}, ensure_ascii=False),
        # capability detection call
        json.dumps({
            "has_payment": True, "payment_evidence": "Customer pays the applicable fee",
            "has_documents": True, "documents_evidence": "uploads a copy of the national ID",
            "has_physical_visit": True, "visit_evidence": "Customer visits the branch",
            "has_human_approval": True, "human_approval_evidence": "Supervisor approves the request",
        }, ensure_ascii=False),
    ])

    agent = ServiceAnalystAgent(llm)
    result = agent.run({
        "service_name": "Certificate issuance",
        "description": "Issue a certificate to a customer",
        "steps": raw_lines,
    })

    assert result["steps_analysis_source"] == "ai", (
        "Expected the AI's 14-step decomposition to be accepted; got "
        f"fallback instead. steps={result['steps']}"
    )
    assert len(result["steps"]) == 14


def test_service_agent_still_rejects_genuinely_invented_steps():
    """Sanity check the guard still works: steps with NO grounding in
    the raw text at all should still be rejected."""
    raw_lines = ["Customer submits a form"]
    ai_steps = [f"Completely unrelated invented action number {i} about spaceships" for i in range(6)]

    llm = FakeLLM([
        json.dumps({"steps": ai_steps}, ensure_ascii=False),
        "",
        "",
    ])
    agent = ServiceAnalystAgent(llm)
    result = agent.run({"service_name": "X", "description": "", "steps": raw_lines})
    assert result["steps_analysis_source"] == "template"


def test_standards_agent_accepts_ids_echoed_with_titles():
    """Real bug: qwen3:4b returned ids like 'STD-01 - Outcome Before
    Procedure' instead of the bare id, so exact-match validation
    zeroed out every selection."""
    service_analysis = {
        "steps": ["Customer submits a request", "Employee manually processes it"],
        "manual_actions": ["Employee manually processes it"],
        "waiting_points": [],
        "approvals": [],
        "documents": [],
        "friction_points": ["Manual operational work exists"],
        "service_classification": {"requires_customer_payment": False},
    }

    a_titled_id = f"{STANDARDS_CATALOG[1]['standard_id']} - {STANDARDS_CATALOG[1]['title']}"
    response = json.dumps({
        "applicable_standard_ids": [a_titled_id],
        "why_it_applies": {a_titled_id: "Manual processing exists in the current journey."},
    }, ensure_ascii=False)

    llm = FakeLLM([response])
    agent = StandardsAgent(llm)
    result = agent.run(service_analysis, standards={"source_text": ""})

    assert result["analysis_source"] == "ai", "AI standard selection should have been accepted"
    ids = {item["standard_id"] for item in result["applicable_standards"]}
    assert STANDARDS_CATALOG[1]["standard_id"] in ids
    # reasoning text should have carried over onto the canonical id
    matching = [item for item in result["applicable_standards"] if item["standard_id"] == STANDARDS_CATALOG[1]["standard_id"]]
    assert matching[0]["why_it_applies"] == "Manual processing exists in the current journey."


def test_gap_agent_accepts_gaps_missing_secondary_fields_and_truncated_tail():
    """Real bug: a gaps array cut off mid-object (context/token budget
    exhausted) used to be discarded wholesale; and any single gap
    missing one non-critical field discarded that whole gap."""
    applicable_standards = [
        {"standard_id": "STD-02", "title": "Burden Shifts to the Assistant", "requirement": "...", "measurable_test": "..."},
        {"standard_id": "STAGE-05", "title": "Manual work review", "requirement": "...", "measurable_test": "..."},
    ]
    service_analysis = {
        "steps": ["Employee manually re-enters the same data"],
        "manual_actions": ["Employee manually re-enters the same data"],
        "waiting_points": [],
        "approvals": [],
        "documents": [],
        "branch_visits": 0,
    }

    # Gap 1 is missing "affected_step" and "expected_impact" (should
    # still be accepted, backfilled). Gap 2's object is cut off before
    # it closes (simulates a truncated response) but gap 1 must still
    # survive.
    truncated_response = (
        '{"gaps": [terminal to real content ignored'  # never actually used
    )
    # Build a genuinely truncated JSON string: full valid gap 1, then a
    # gap 2 that never closes.
    truncated_response = (
        '{"gaps": [{"category": "Duplicate Data", "description": '
        '"Manual re-entry of the same data.", "standard_id": "STD-02", '
        '"severity": "HIGH", "recommendation": "Reuse captured data."}, '
        '{"category": "Manual Work", "description": "Manual processing '
        'exists", "standard_id": "STAGE-05", "severity": "MEDIUM'
    )

    llm = FakeLLM([truncated_response])
    agent = GapAnalysisAgent(llm)
    result = agent.run(service_analysis, {"applicable_standards": applicable_standards})

    assert result["analysis_source"] == "ai", f"Expected AI gaps to be accepted, got: {result}"
    assert len(result["gaps"]) >= 1
    gap = result["gaps"][0]
    assert gap["standard_id"] == "STD-02"
    assert gap["description"] == "Manual re-entry of the same data."
    # backfilled defaults for the fields the model omitted
    assert gap["affected_step"] == ""
    assert gap["expected_impact"] == ""


def test_journey_agent_keeps_good_stages_when_one_stage_is_weak():
    """Real bug: one stage with a thin detailed_description used to
    discard the entire AI-designed journey."""
    steps = [
        {
            "name": "Submit request", "type": "SYSTEM", "executor": "AGENT",
            "action": "Customer submits the request",
            "detailed_description": "The customer submits the request through the assistant, providing the required identifying information so the request can be validated and routed.",
            "reasoning": "This is the entry point of the journey.",
            "customer_role": "Provides request details", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "", "delivers_customer_result": False,
        },
        {
            # weak stage: detailed_description under 30 chars
            "name": "Check", "type": "SYSTEM", "executor": "AGENT",
            "action": "System checks eligibility automatically",
            "detailed_description": "Auto check.",
            "reasoning": "", "customer_role": "None", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Submitted request", "delivers_customer_result": False,
        },
        {
            "name": "Deliver result", "type": "SYSTEM", "executor": "AGENT",
            "action": "Customer receives the final decision",
            "detailed_description": "The system notifies the customer of the final decision and makes the result available for download or review at any time.",
            "reasoning": "This concludes the journey with a clear outcome.",
            "customer_role": "Views the result", "has_payment": False,
            "payment_reasoning": "", "requires_human_judgement": False,
            "human_judgement_reason": "", "requires_customer_approval": False,
            "depends_on_previous": "Eligibility checked", "delivers_customer_result": True,
        },
    ]
    response = json.dumps({
        "overall_reasoning": "Three-stage journey for this service.",
        "steps": steps,
    }, ensure_ascii=False)

    llm = FakeLLM([response])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "Test service",
        "description": "A test service",
        "steps": ["Customer submits", "System checks", "Result delivered"],
    }
    step_compliance = {"steps": []}
    result = agent.run(service, step_compliance, relevant_standards={"applicable_standards": []})

    future_steps = result.get("future_steps", [])
    sources = {s.get("analysis_source") for s in future_steps}
    assert "ai" in sources, f"Expected the AI-designed journey to be (partially) accepted, got sources={sources}, result keys={list(result.keys())}"
    assert len(future_steps) == 3, "The weak stage should be repaired (via action/reasoning text), not dropped, since it still had usable content"


if __name__ == "__main__":
    test_service_agent_accepts_more_steps_than_raw_lines_when_grounded()
    test_service_agent_still_rejects_genuinely_invented_steps()
    test_standards_agent_accepts_ids_echoed_with_titles()
    test_gap_agent_accepts_gaps_missing_secondary_fields_and_truncated_tail()
    test_journey_agent_keeps_good_stages_when_one_stage_is_weak()
    print("ALL QWEN3 REAL-FAILURE-SIGNATURE TESTS PASSED")
