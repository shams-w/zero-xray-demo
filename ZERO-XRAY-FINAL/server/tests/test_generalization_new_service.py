"""
Generalization test (ported from P1, SCOPED to what this merge pass
actually wired in -- see docstring notes below): proves the engine
works on a service it has never seen before, with no special-casing
anywhere in the agents.

The 9 services shipped as Demo/Validation Cases
(core/service_classifier.py -> DEMO_VALIDATION_PROFILES) are examples,
not the boundary of the system. This test deliberately picks a service
from a domain none of those cover -- trademark registration -- and a
service name/steps/protected_steps that appear nowhere else in the
codebase, then runs it through the same agent chain graph/workflow.py
wires (service_agent -> gap_agent -> step_compliance_agent ->
journey_builder_agent -> zero_bureaucracy_agent -> validation_agent),
with no LLM configured so only the deterministic baseline paths run.

SCOPING NOTE (merge task): P1's original version of this test also
asserted a "9-dimension intake" (core/framework.py's
build_framework_intake) and a 5-way "executor" field
(CUSTOMER/AGENT/GOVERNMENT_SYSTEM/EXTERNAL_SYSTEM/HUMAN_AUTHORITY) on
every future step. This merge pass copied core/framework.py itself and
wired its classify_gap() into agents/gap_agent.py and
agents/zero_bureaucracy_agent.py (see those files' "framework_categories"
fields, exercised below), but did NOT wire build_framework_intake or an
executor field into agents/step_compliance_agent.py /
agents/journey_builder_agent.py -- P2's existing "owner" field
(HUMAN/ASSISTANT/GOVERNMENT_SYSTEM/EXTERNAL_SYSTEM) is a related but
different classification already in active use across the frontend and
validation_agent, and swapping/adding a parallel executor taxonomy is a
separate, larger merge task not completed here (see MERGE_REPORT.md,
"Known limitations"). The assertions below are therefore scoped to what
the merged pipeline actually produces today; the deferred assertions
are listed in a skipped test at the bottom for visibility instead of
being silently dropped.
"""

import unittest

from agents.service_agent import ServiceAnalystAgent
from agents.gap_agent import GapAnalysisAgent
from agents.step_compliance_agent import StepComplianceAgent
from agents.journey_builder_agent import JourneyBuilderAgent
from agents.zero_bureaucracy_agent import ZeroBureaucracyAgent
from agents.validation_agent import ValidationAgent
from core.standards_catalog import STANDARDS_CATALOG
from core.rules import calculate_metrics
from core.scoring import calculate_zero_bureaucracy_score
from core.service_classifier import classify_service
from core.framework import DECISION_CATEGORIES


STANDARDS_SEED = {"applicable_standards": STANDARDS_CATALOG}


NEW_SERVICE = {
    "service_name": "Trademark Registration",
    "description": (
        "A business owner registers a new trademark for their brand "
        "name and logo, pays the registration fee, and receives a "
        "certificate once an examiner confirms there is no conflict "
        "with an existing mark."
    ),
    "steps": [
        "Customer visits the trademark office to submit the application in person",
        "Customer enters the brand name, logo and applicant details",
        "Customer uploads proof of business registration",
        "Customer pays the trademark examination fee",
        "Examiner manually reviews the application for conflicts with existing marks",
        "Office issues the registration certificate",
    ],
    "documents": ["Business registration certificate", "Logo artwork"],
    "approvals": ["Examiner conflict review"],
    "lang": "en",
    # An AS_IS-protected step that exists ONLY in this test service --
    # proves the compliance gate is generic, not hardcoded to the 9
    # demo services' own protected steps.
    "protected_steps": [
        {
            "step_number": 5,
            "level": "AS_IS",
            "reason": "Trademark law requires a licensed examiner's personal review; it cannot be delegated to an algorithm.",
            "source_reference": "TM-LAW-ART-12",
        }
    ],
}


def run_pipeline_no_llm(service):
    """Same agent chain and ordering as graph/workflow.py (service_agent
    now included, since the merged service_agent is where semantic
    steps and capabilities are produced for downstream agents), with no
    LLM configured so only the deterministic baseline/template paths
    run (no Ollama available in this environment)."""
    service_agent = ServiceAnalystAgent(llm=None)
    gap_agent = GapAnalysisAgent(llm=None)
    step_compliance_agent = StepComplianceAgent(llm=None)
    journey_builder_agent = JourneyBuilderAgent(llm=None)
    zero_bureaucracy_agent = ZeroBureaucracyAgent(llm=None)
    validation_agent = ValidationAgent(llm=None)

    service_analysis = service_agent.run(service)
    enriched_service = {
        **service,
        "steps": service_analysis["steps"],
        "capabilities": service_analysis["capabilities"],
    }
    relevant_standards = STANDARDS_SEED
    gaps = gap_agent.run(service_analysis, relevant_standards)
    step_compliance = step_compliance_agent.run(
        enriched_service, service_analysis, relevant_standards
    )
    redesign = journey_builder_agent.run(
        enriched_service, step_compliance, relevant_standards
    )
    zero_bureaucracy = zero_bureaucracy_agent.run(service_analysis, gaps)
    metrics = calculate_metrics(enriched_service, redesign)
    zb_score = calculate_zero_bureaucracy_score(metrics)
    validation = validation_agent.run(
        enriched_service,
        relevant_standards,
        redesign,
        {**metrics, "zero_bureaucracy_score": zb_score},
    )
    classification = classify_service(service)
    return {
        "service_analysis": service_analysis,
        "gaps": gaps,
        "step_compliance": step_compliance,
        "redesign": redesign,
        "zero_bureaucracy": zero_bureaucracy,
        "validation": validation,
        "classification": classification,
    }


class NewServiceIsNotOneOfTheDemoNine(unittest.TestCase):
    def test_service_name_outside_demo_domains(self):
        # P2's core/service_classifier.py does not expose a
        # DEMO_VALIDATION_PROFILES constant (P1-only), so this checks
        # the same intent -- the test service is not one of the
        # special-cased shipping/postal domains -- directly.
        for word in ("shipment", "postal", "shipping", "courier"):
            self.assertNotIn(word, NEW_SERVICE["service_name"].lower())
            self.assertNotIn(word, NEW_SERVICE["description"].lower())


class GeneralizationPipelineRunsCleanly(unittest.TestCase):
    def test_full_pipeline_runs_without_error(self):
        result = run_pipeline_no_llm(NEW_SERVICE)
        self.assertIn("step_assessment", result["step_compliance"])
        self.assertIn("future_steps", result["redesign"])
        self.assertIn("status", result["validation"])


class HumanConstraintGateGeneralizesToNewService(unittest.TestCase):
    """The AS_IS lock mechanism, exercised on a service that exists
    ONLY in this test file -- proving it is driven purely by the
    protected_steps schema, never by service name."""

    def test_as_is_examiner_step_is_locked_end_to_end(self):
        result = run_pipeline_no_llm(NEW_SERVICE)

        examiner_assessment = next(
            item
            for item in result["step_compliance"]["step_assessment"]
            if item["step_number"] == 5
        )
        self.assertEqual(examiner_assessment["decision"], "KEEP")
        self.assertEqual(
            examiner_assessment["human_constraint"]["level"], "AS_IS"
        )

        locked_future = [
            item
            for item in result["redesign"]["future_steps"]
            if item.get("implementation_status") == "HUMAN_LOCKED_AS_IS"
        ]
        self.assertEqual(len(locked_future), 1)
        # This protected step must never be counted as customer effort
        # -- it's explicitly a human-authority (examiner) step, not a
        # customer one.
        self.assertFalse(locked_future[0]["customer_burden"])


class GapAndZeroBureaucracyFrameworkLinkGeneralizes(unittest.TestCase):
    """Exercises the part of core/framework.py this merge pass DID
    wire in: classify_gap() on both agents/gap_agent.py and
    agents/zero_bureaucracy_agent.py."""

    def test_gaps_and_findings_carry_framework_categories(self):
        result = run_pipeline_no_llm(NEW_SERVICE)
        for gap in result["gaps"].get("gaps", []):
            self.assertIn("framework_categories", gap)
            for category in gap["framework_categories"]:
                self.assertIn(category, DECISION_CATEGORIES)

        zb = result["zero_bureaucracy"]
        self.assertIn("framework_category_counts", zb)
        for finding in zb["findings"]:
            self.assertIn("framework_categories", finding)
        for category in zb["framework_category_counts"]:
            self.assertIn(category, DECISION_CATEGORIES)


class NoDemoDomainLeakage(unittest.TestCase):
    """Nothing from the shipping/postal demo domains should appear in
    a trademark-registration journey -- proves templates/wording are
    generic, not copy-pasted per service."""

    def test_no_shipping_or_postal_wording_in_output(self):
        result = run_pipeline_no_llm(NEW_SERVICE)
        future_text = " ".join(
            str(step.get("name", "")) + " " + str(step.get("action", ""))
            for step in result["redesign"]["future_steps"]
        ).lower()
        for word in ("shipment", "courier", "postal box", "tracking number"):
            self.assertNotIn(word, future_text)


class DeferredFrameworkIntegrationScope(unittest.TestCase):
    """Not a real assertion -- documents, in a way that shows up in
    the test report, exactly what P1 functionality around
    core/framework.py was intentionally NOT wired into the merged
    pipeline in this pass (see this file's module docstring and
    MERGE_REPORT.md's "Known limitations")."""

    @unittest.skip(
        "Deferred: build_framework_intake() (9-dimension intake) and "
        "a 5-way executor field (CUSTOMER/AGENT/GOVERNMENT_SYSTEM/"
        "EXTERNAL_SYSTEM/HUMAN_AUTHORITY) on future_steps were not "
        "wired into agents/step_compliance_agent.py / "
        "agents/journey_builder_agent.py in this merge pass. "
        "core/framework.py itself IS present and its classify_gap() "
        "IS wired into gap_agent.py / zero_bureaucracy_agent.py (see "
        "GapAndZeroBureaucracyFrameworkLinkGeneralizes above)."
    )
    def test_deferred_9_dimension_intake_and_executor_field(self):
        pass


if __name__ == "__main__":
    unittest.main()
