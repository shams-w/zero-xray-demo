"""
Tests for the root-cause fix to two reported production issues:

1. "Current Journey Count" counting raw lines/paragraphs/options
   instead of actual semantic steps.
2. The Future Journey inventing a Payment stage for services that
   don't need one (reported against a complaint journey, but the fix
   — and these tests — are generic across services).

These exercise agents/service_agent.py's semantic step extraction and
evidence-gated capability detection, agents/journey_builder_agent.py's
capability-veto validation layer, and a full pipeline helper that
reproduces graph/workflow.py's service_node state merge-back (the
actual place the fix is wired in), so the tests validate the same
propagation path production traffic goes through.
"""

import json
import unittest

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


def run_pipeline(service, llm):
    """Reproduces graph/workflow.py's actual node sequence and, most
    importantly, service_node's state merge-back: service["steps"] is
    replaced with the semantically-extracted steps and
    service["capabilities"] is attached, exactly как workflow.py does
    it — so this test exercises the real propagation path, not a
    hand-picked shortcut.
    """
    service_agent = ServiceAnalystAgent(llm)
    standards_agent = StandardsAgent(llm)
    gap_agent = GapAnalysisAgent(llm)
    step_compliance_agent = StepComplianceAgent(llm)
    journey_builder_agent = JourneyBuilderAgent(llm)
    validation_agent = ValidationAgent(llm)

    service_analysis = service_agent.run(service)

    # --- exact mirror of workflow.py's service_node merge-back ---
    updated_service = dict(service)
    semantic_steps = service_analysis.get("steps")
    if isinstance(semantic_steps, list) and semantic_steps:
        updated_service["steps"] = semantic_steps
    updated_service["capabilities"] = service_analysis.get("capabilities", {})
    service = updated_service
    # ---------------------------------------------------------------

    relevant_standards = standards_agent.run(service_analysis, STANDARDS_SEED)
    gaps = gap_agent.run(service_analysis, relevant_standards)
    step_compliance = step_compliance_agent.run(
        service, service_analysis, relevant_standards
    )
    redesign = journey_builder_agent.run(
        service, step_compliance, relevant_standards
    )
    metrics = calculate_metrics(service, redesign)
    zb_score = calculate_zero_bureaucracy_score(metrics)
    validation = validation_agent.run(
        service=service,
        standards=relevant_standards,
        redesign=redesign,
        metrics={**metrics, "zero_bureaucracy_score": zb_score},
    )
    return {
        "service": service,
        "service_analysis": service_analysis,
        "relevant_standards": relevant_standards,
        "gaps": gaps,
        "step_compliance": step_compliance,
        "redesign": redesign,
        "metrics": metrics,
        "validation": validation,
    }


class SemanticStepMockLLM:
    """A mock that answers the semantic-step-extraction and
    capability-detection prompts realistically, and otherwise defers
    to a simple, generic default so the rest of the pipeline (journey
    generation etc.) exercises its own real fallback logic instead of
    needing a canned answer for every agent.
    """

    def __init__(self, semantic_steps=None, capabilities=None,
                 fail=False, malformed=False):
        self.semantic_steps = semantic_steps
        self.capabilities = capabilities
        self.fail = fail
        self.malformed = malformed

    def generate(self, system_prompt, user_prompt, max_new_tokens=None,
                 temperature=0, timeout=None):
        if self.fail:
            return ""
        if self.malformed:
            return "this is not json at all"

        if "identify the actual sequence of semantic steps" in user_prompt:
            return json.dumps({"steps": self.semantic_steps or []})

        if "CAPABILITIES TO EVALUATE" in user_prompt:
            return json.dumps(self.capabilities or {
                "has_payment": False, "payment_evidence": "",
                "has_documents": False, "documents_evidence": "",
                "has_physical_visit": False, "visit_evidence": "",
                "has_human_approval": False, "human_approval_evidence": "",
            })

        # Everything else (journey design, standards, gaps, step
        # compliance review, validation semantic review, step
        # classification, payment timing) intentionally returns
        # nothing usable, so those agents exercise their own real,
        # already-tested deterministic fallback paths.
        return ""


# ---------------------------------------------------------------
# 1. Semantic current-journey extraction (multi-line steps, options)
# ---------------------------------------------------------------

class SemanticStepCountingTests(unittest.TestCase):
    def test_multiline_and_option_lines_collapse_to_one_step_ai_path(self):
        raw_lines = [
            "Customer selects a shipping package",
            "Standard",
            "Express",
            "Premium",
            "Courier collects and weighs the parcel",
            "Customer pays the calculated fee",
        ]
        semantic = [
            "Customer selects a shipping package (Standard, Express, or Premium)",
            "Courier collects and weighs the parcel",
            "Customer pays the calculated fee",
        ]
        llm = SemanticStepMockLLM(semantic_steps=semantic)
        agent = ServiceAnalystAgent(llm)
        result = agent.run({
            "service_name": "Shipping",
            "description": "Ship a parcel abroad.",
            "steps": raw_lines,
        })
        self.assertEqual(result["steps"], semantic)
        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(result["steps_analysis_source"], "ai")
        # Raw lines are preserved separately for traceability.
        self.assertEqual(result["raw_steps"], raw_lines)

    def test_ai_cannot_inflate_step_count_beyond_raw_lines(self):
        """Structural anti-hallucination check: a 'semantic merge'
        that returns MORE steps than raw lines is untrustworthy by
        definition and must fall back."""
        raw_lines = ["Step one", "Step two"]

        class InflatingLLM:
            def generate(self, **kw):
                if "identify the actual sequence" in kw.get("user_prompt", ""):
                    return json.dumps({"steps": ["a", "b", "c", "d", "e"]})
                return ""

        agent = ServiceAnalystAgent(InflatingLLM())
        result = agent.run({
            "service_name": "X", "description": "Y", "steps": raw_lines,
        })
        self.assertEqual(result["steps_analysis_source"], "template")
        self.assertLessEqual(len(result["steps"]), len(raw_lines))

    def test_heuristic_fallback_merges_bullets_not_naive_line_count(self):
        """No LLM available: the deterministic fallback must still
        avoid counting an option/bullet line as its own step — no
        len(lines), no hardcoded numbers."""
        raw_lines = [
            "Customer selects a package",
            "- Standard",
            "- Express",
            "- Premium",
            "Courier collects the parcel",
        ]
        agent = ServiceAnalystAgent(llm=None)
        result = agent.run({
            "service_name": "Shipping",
            "description": "Ship a parcel.",
            "steps": raw_lines,
        })
        self.assertEqual(result["steps_analysis_source"], "template")
        # 5 raw lines -> should merge down to 2 real steps (the 3
        # bullets fold into the step above them), not stay at 5.
        self.assertEqual(len(result["steps"]), 2)
        self.assertIn("Standard", result["steps"][0])
        self.assertIn("Premium", result["steps"][0])

    def test_no_hardcoded_count_for_a_document_with_many_options(self):
        """Generic guard against a hardcoded number appearing
        anywhere in the step-counting logic (e.g. the reported '21')."""
        raw_lines = (
            ["Customer opens a case"]
            + [f"Reason {i}" for i in range(1, 20)]
            + ["Case is submitted"]
        )
        self.assertEqual(len(raw_lines), 21)
        agent = ServiceAnalystAgent(llm=None)
        result = agent.run({
            "service_name": "Case Submission",
            "description": "Pick a reason from many options and submit.",
            "steps": raw_lines,
        })
        # The heuristic must not literally echo the raw line count.
        self.assertNotEqual(len(result["steps"]), 21)
        self.assertLess(len(result["steps"]), 21)


# ---------------------------------------------------------------
# 2. Capability detection: payment / non-payment / complaint
# ---------------------------------------------------------------

class CapabilityDetectionTests(unittest.TestCase):
    def test_payment_service_detected_with_evidence_ai_path(self):
        llm = SemanticStepMockLLM(
            semantic_steps=["Customer requests renewal", "Customer pays the fee"],
            capabilities={
                "has_payment": True,
                "payment_evidence": "Customer pays the fee",
                "has_documents": False, "documents_evidence": "",
                "has_physical_visit": False, "visit_evidence": "",
                "has_human_approval": False, "human_approval_evidence": "",
            },
        )
        agent = ServiceAnalystAgent(llm)
        result = agent.run({
            "service_name": "License Renewal",
            "description": "Renew a license for a fee.",
            "steps": ["Customer requests renewal", "Customer pays the fee"],
        })
        self.assertTrue(result["capabilities"]["has_payment"])
        self.assertEqual(result["capabilities"]["analysis_source"], "ai")

    def test_complaint_service_does_not_get_payment_ai_path(self):
        llm = SemanticStepMockLLM(
            semantic_steps=[
                "Customer submits a complaint about an incorrect charge",
                "Employee reviews the case and issues a refund decision",
            ],
            capabilities={
                "has_payment": False, "payment_evidence": "",
                "has_documents": False, "documents_evidence": "",
                "has_physical_visit": False, "visit_evidence": "",
                "has_human_approval": True,
                "human_approval_evidence": "Employee reviews the case and issues a refund decision",
            },
        )
        agent = ServiceAnalystAgent(llm)
        result = agent.run({
            "service_name": "Billing Complaint",
            "description": "Customer disputes being charged twice.",
            "steps": [
                "Customer submits a complaint about an incorrect charge",
                "Employee reviews the case and issues a refund decision",
            ],
        })
        self.assertFalse(result["capabilities"]["has_payment"])
        self.assertTrue(result["capabilities"]["has_human_approval"])

    def test_ungrounded_ai_evidence_is_rejected(self):
        """Anti-hallucination validation: a capability marked true
        with evidence that shares nothing with the actual source text
        must be forced back to false."""
        llm = SemanticStepMockLLM(
            semantic_steps=["Customer asks for office hours"],
            capabilities={
                "has_payment": True,
                "payment_evidence": "customer wires a large international bank transfer",
                "has_documents": False, "documents_evidence": "",
                "has_physical_visit": False, "visit_evidence": "",
                "has_human_approval": False, "human_approval_evidence": "",
            },
        )
        agent = ServiceAnalystAgent(llm)
        result = agent.run({
            "service_name": "Office Hours Inquiry",
            "description": "Customer asks about opening hours.",
            "steps": ["Customer asks for office hours"],
        })
        self.assertFalse(result["capabilities"]["has_payment"])

    def test_complaint_keyword_fallback_does_not_invent_payment(self):
        """No LLM available: the deterministic keyword fallback must
        not treat 'refund'/'fee' inside a complaint as a real payment
        capability."""
        agent = ServiceAnalystAgent(llm=None)
        result = agent.run({
            "service_name": "Billing Complaint",
            "description": "Customer disputes an incorrect fee and wants a refund.",
            "steps": [
                "Customer files a complaint about being charged twice",
                "Employee reviews and issues a refund",
            ],
        })
        self.assertFalse(result["capabilities"]["has_payment"])

    def test_fixed_fee_service_keyword_fallback_detects_payment(self):
        agent = ServiceAnalystAgent(llm=None)
        result = agent.run({
            "service_name": "Driving License Renewal",
            "description": "Customer renews a license and pays a fixed fee.",
            "steps": ["Customer requests renewal", "Customer pays the renewal fee"],
        })
        self.assertTrue(result["capabilities"]["has_payment"])

    def test_no_fee_service_keyword_fallback_detects_no_payment(self):
        agent = ServiceAnalystAgent(llm=None)
        result = agent.run({
            "service_name": "Public Information Lookup",
            "description": "There is no fee for this service.",
            "steps": ["Customer asks", "Employee replies"],
        })
        self.assertFalse(result["capabilities"]["has_payment"])


# ---------------------------------------------------------------
# 3. Malformed Ollama response / total failure -> safe fallback
# ---------------------------------------------------------------

class MalformedAndFailureTests(unittest.TestCase):
    def test_malformed_json_response_falls_back_safely(self):
        llm = SemanticStepMockLLM(malformed=True)
        agent = ServiceAnalystAgent(llm)
        result = agent.run({
            "service_name": "Billing Complaint",
            "description": "Customer disputes an incorrect fee.",
            "steps": ["Customer files a complaint", "Employee reviews it"],
        })
        self.assertEqual(result["steps_analysis_source"], "template")
        self.assertEqual(result["capabilities"]["analysis_source"], "template")
        self.assertFalse(result["capabilities"]["has_payment"])

    def test_llm_total_failure_falls_back_safely(self):
        llm = SemanticStepMockLLM(fail=True)
        agent = ServiceAnalystAgent(llm)
        result = agent.run({
            "service_name": "Billing Complaint",
            "description": "Customer disputes an incorrect fee.",
            "steps": ["Customer files a complaint", "Employee reviews it"],
        })
        self.assertEqual(result["steps_analysis_source"], "template")
        self.assertFalse(result["capabilities"]["has_payment"])


# ---------------------------------------------------------------
# 4. End-to-end pipeline: the actual reported bug, and other services
# ---------------------------------------------------------------

class EndToEndCapabilityVetoTests(unittest.TestCase):
    def test_complaint_journey_never_gets_payment_no_llm(self):
        """Reproduces the exact reported production bug (a complaint
        journey getting an invented Payment stage) end-to-end, through
        the real service_node merge-back path, with no LLM available
        at all — the hardest case, relying purely on deterministic
        fallbacks at every stage."""
        service = {
            "service_name": "Billing Complaint",
            "description": "Customer complains they were charged twice and wants a refund.",
            "steps": [
                "Customer submits a complaint about being charged twice",
                "Employee reviews the billing history",
                "Employee decides on a refund",
                "Customer is notified of the outcome",
            ],
            "documents": [],
        }
        result = run_pipeline(service, llm=None)
        future = result["redesign"]["future_steps"]
        self.assertFalse(
            any(s.get("has_payment") for s in future),
            "A complaint journey must never get an invented payment stage.",
        )
        self.assertFalse(result["service_analysis"]["capabilities"]["has_payment"])

    def test_complaint_journey_never_gets_payment_with_ai(self):
        """Same reported bug, but with an AI journey-generation path
        available — the capability veto must still hold even if the
        journey-design model tries to add a payment step anyway."""
        semantic = [
            "Customer submits a complaint about being charged twice",
            "Employee reviews the billing history",
            "Employee decides on a refund",
            "Customer is notified of the outcome",
        ]

        class VetoTestLLM:
            def generate(self, system_prompt, user_prompt, max_new_tokens=None,
                         temperature=0, timeout=None):
                if "identify the actual sequence" in user_prompt:
                    return json.dumps({"steps": semantic})
                if "CAPABILITIES TO EVALUATE" in user_prompt:
                    return json.dumps({
                        "has_payment": False, "payment_evidence": "",
                        "has_documents": False, "documents_evidence": "",
                        "has_physical_visit": False, "visit_evidence": "",
                        "has_human_approval": True,
                        "human_approval_evidence": "Employee decides on a refund",
                    })
                if "Design the proposed FUTURE journey" in user_prompt:
                    # Deliberately hallucinate a payment step despite
                    # the prompt's explicit capability constraint —
                    # this is exactly what the validation veto layer
                    # must catch and strip.
                    return json.dumps({
                        "overall_reasoning": "test",
                        "steps": [
                            {
                                "name": "Review the complaint",
                                "type": "HUMAN",
                                "action": "Review the complaint details.",
                                "detailed_description": "A human reviews the complaint about a double charge and checks the billing history to determine whether a refund is warranted.",
                                "reasoning": "Requires judgement on the billing history.",
                                "customer_role": "Waits for the outcome.",
                                "has_payment": False,
                                "payment_reasoning": "",
                                "requires_human_judgement": True,
                                "human_judgement_reason": "Refund decisions require accountable review.",
                                "depends_on_previous": "",
                            },
                            {
                                "name": "Process a service fee",
                                "type": "SYSTEM",
                                "action": "Collect a processing fee.",
                                "detailed_description": "The assistant hallucinated a payment stage here even though this service has no evidenced payment capability, which the validation layer must strip.",
                                "reasoning": "invented",
                                "customer_role": "Pays a fee.",
                                "has_payment": True,
                                "payment_reasoning": "invented",
                                "requires_human_judgement": False,
                                "human_judgement_reason": "",
                                "depends_on_previous": "",
                            },
                        ],
                    })
                return ""

        service = {
            "service_name": "Billing Complaint",
            "description": "Customer complains they were charged twice and wants a refund.",
            "steps": semantic,
            "documents": [],
        }
        result = run_pipeline(service, llm=VetoTestLLM())
        future = result["redesign"]["future_steps"]
        self.assertEqual(result["redesign"]["analysis_source"], "ai")
        self.assertFalse(
            any(s.get("has_payment") for s in future),
            "The capability veto must strip a hallucinated payment "
            "step even when the AI journey-design path invents one.",
        )

    def test_shipping_service_keeps_evidenced_payment_no_llm(self):
        """The fix must not become a blanket payment-suppressor: a
        service that genuinely has payment must keep it."""
        service = {
            "service_name": "International Shipping",
            "description": "Customer ships a package abroad and pays a shipping fee.",
            "steps": [
                "Customer submits shipment request",
                "Courier collects and weighs the package",
                "Customer pays the shipping fee",
                "Shipment is dispatched",
            ],
            "documents": [],
        }
        result = run_pipeline(service, llm=None)
        future = result["redesign"]["future_steps"]
        self.assertTrue(
            any(s.get("has_payment") for s in future),
            "A genuinely paid service must keep its payment step.",
        )
        self.assertTrue(result["service_analysis"]["capabilities"]["has_payment"])

    def test_completely_different_service_no_special_casing(self):
        """A school-enrollment service (no payment, no relation to
        shipping or complaints at all) exercises the same generic
        pipeline correctly."""
        service = {
            "service_name": "School Enrollment",
            "description": "Parent enrolls a child in a public school for the upcoming year.",
            "steps": [
                "Parent submits enrollment preferences",
                "- Preferred school A",
                "- Preferred school B",
                "Eligibility and residency are verified",
                "A school place is assigned",
            ],
            "documents": [],
        }
        result = run_pipeline(service, llm=None)
        self.assertLess(
            len(result["service"]["steps"]), 5,
            "The two preference bullet lines should merge into the "
            "step above them instead of counting as separate steps.",
        )
        future = result["redesign"]["future_steps"]
        self.assertFalse(any(s.get("has_payment") for s in future))

    def test_current_journey_count_reflects_semantic_steps_in_metrics(self):
        """Directly proves the reported 'Current Journey Count' bug
        is fixed: metrics.current.steps must reflect the semantic
        count, not the raw noisy line count."""
        raw_lines = [
            "Customer selects a package",
            "- Standard",
            "- Express",
            "- Premium",
            "Courier collects the parcel",
            "Customer pays the fee",
        ]
        service = {
            "service_name": "Shipping",
            "description": "Ship a parcel with a chosen package.",
            "steps": raw_lines,
            "documents": [],
        }
        result = run_pipeline(service, llm=None)
        current_count = result["metrics"]["current"]["steps"]
        self.assertLess(
            current_count, len(raw_lines),
            "The current step count must not equal the raw line "
            "count once option/bullet lines are folded into their "
            "parent step.",
        )
        self.assertEqual(current_count, len(result["service"]["steps"]))


# ---------------------------------------------------------------
# 5. Formatting / line-count invariance (final audit requirement)
# ---------------------------------------------------------------

class FormattingInvarianceTests(unittest.TestCase):
    """The same underlying service, described with different line
    breaks / bullet formatting, must not change the semantic result
    just because the raw line count changed."""

    def test_ai_path_same_semantic_result_regardless_of_raw_formatting(self):
        semantic = [
            "Customer submits shipment request",
            "Courier collects and weighs the package",
            "Customer pays the shipping fee",
        ]

        # Version A: one raw line per real step.
        raw_a = list(semantic)
        # Version B: same content, split across many more raw lines
        # (wrapped sentences + bullet options), very different line
        # count, same underlying meaning.
        raw_b = [
            "Customer submits shipment request",
            "Includes destination and package type",
            "- Standard",
            "- Express",
            "- Premium",
            "Courier collects and weighs the package",
            "Weight and dimensions are recorded",
            "Customer pays the shipping fee",
            "based on the final calculated amount",
        ]
        self.assertNotEqual(len(raw_a), len(raw_b))

        llm = SemanticStepMockLLM(semantic_steps=semantic)
        agent = ServiceAnalystAgent(llm)

        result_a = agent.run({
            "service_name": "Shipping", "description": "Ship a package.",
            "steps": raw_a,
        })
        result_b = agent.run({
            "service_name": "Shipping", "description": "Ship a package.",
            "steps": raw_b,
        })
        # Same AI-driven semantic understanding -> same step count,
        # regardless of how many raw lines fed into it.
        self.assertEqual(len(result_a["steps"]), len(result_b["steps"]))
        self.assertEqual(result_a["steps"], result_b["steps"])

    def test_heuristic_fallback_converges_across_formatting_variants_no_llm(self):
        """Even without AI, reformatting the same content (extra blank
        lines, different bullet characters) must not inflate the
        semantic step count in the same drastic, naive way a plain
        len(lines) would."""
        raw_compact = [
            "Customer selects a package",
            "Standard/Express/Premium",
            "Courier collects the parcel",
            "Customer pays the fee",
        ]
        raw_verbose = [
            "Customer selects a package",
            "* Standard",
            "* Express",
            "* Premium",
            "Courier collects the parcel",
            "Customer pays the fee",
        ]
        agent = ServiceAnalystAgent(llm=None)
        result_compact = agent.run({
            "service_name": "Shipping", "description": "Ship.",
            "steps": raw_compact,
        })
        result_verbose = agent.run({
            "service_name": "Shipping", "description": "Ship.",
            "steps": raw_verbose,
        })
        # Both must converge to the same 3 real steps even though the
        # raw line counts differ (4 vs 6).
        self.assertEqual(len(result_compact["steps"]), 3)
        self.assertEqual(len(result_verbose["steps"]), 3)


# ---------------------------------------------------------------
# 6. Explicit final-audit trio: complaint / payment / non-payment
# ---------------------------------------------------------------

class FinalAuditTrioTests(unittest.TestCase):
    def test_complaint_service_end_to_end_no_llm(self):
        service = {
            "service_name": "Delivery Complaint",
            "description": "Customer complains a delivery was delayed and wants a refund of the fee.",
            "steps": [
                "Customer submits a complaint about a delayed delivery",
                "Employee investigates the delay",
                "Employee approves a refund",
            ],
            "documents": [],
        }
        result = run_pipeline(service, llm=None)
        self.assertFalse(
            any(s.get("has_payment") for s in result["redesign"]["future_steps"])
        )

    def test_payment_service_end_to_end_no_llm(self):
        service = {
            "service_name": "Permit Renewal",
            "description": "Customer renews a permit and pays the renewal fee.",
            "steps": [
                "Customer requests renewal",
                "Customer pays the renewal fee",
                "Permit is reissued",
            ],
            "documents": [],
        }
        result = run_pipeline(service, llm=None)
        self.assertTrue(
            any(s.get("has_payment") for s in result["redesign"]["future_steps"])
        )

    def test_non_payment_service_end_to_end_no_llm(self):
        service = {
            "service_name": "Public Holiday Calendar",
            "description": "Customer views the list of official public holidays. No fee.",
            "steps": [
                "Customer requests the holiday calendar",
                "Assistant displays the calendar",
            ],
            "documents": [],
        }
        result = run_pipeline(service, llm=None)
        self.assertFalse(
            any(s.get("has_payment") for s in result["redesign"]["future_steps"])
        )


if __name__ == "__main__":
    unittest.main()
