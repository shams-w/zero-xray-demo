"""
Regression tests for the Zero Bureaucracy / customer-effort-reduction
scoring bug: future (AI-designed and template) journey stages used to
hardcode ``customer_burden: False`` regardless of what the stage's
own ``customer_role`` text actually said, so any genuine remaining
customer administrative work in the redesigned journey was invisible
to ``customer_effort_reduction_percent`` (and, through it, to the
Zero Bureaucracy score). These tests are service-agnostic: none of
the services below are one of the 9 demo services, and the detector
under test (core.rules.step_customer_role_is_burden) never inspects
a service name.
"""

import json
import unittest

from agents.journey_builder_agent import JourneyBuilderAgent
from agents.step_compliance_agent import StepComplianceAgent
from agents.validation_agent import ValidationAgent
from core.rules import (
    calculate_metrics,
    step_customer_role_is_burden,
)
from core.scoring import calculate_zero_bureaucracy_score
from core.standards_catalog import STANDARDS_CATALOG

STANDARDS = {"applicable_standards": STANDARDS_CATALOG}


def service(name, steps):
    return {
        "service_name": name,
        "description": "\n".join(steps),
        "steps": steps,
        "documents": [],
        "actors": [],
        "approvals": [],
        "waiting_times": [],
        "manual_actions": [],
        "digital_actions": [],
        "dependencies": [],
        "branch_visits": 0,
    }


def analyze(value):
    compliance = StepComplianceAgent().run(value, {}, STANDARDS)
    redesign = JourneyBuilderAgent().run(value, compliance, STANDARDS)
    metrics = calculate_metrics(value, redesign)
    metrics["zero_bureaucracy_score"] = calculate_zero_bureaucracy_score(
        metrics
    )
    validation = ValidationAgent().run(value, STANDARDS, redesign, metrics)
    return compliance, redesign, metrics, validation


class CustomerRoleBurdenDetectorTests(unittest.TestCase):
    """Unit-level tests of the shared detector itself."""

    def test_default_no_burden_text_is_not_burden(self):
        self.assertFalse(
            step_customer_role_is_burden("No administrative customer work")
        )
        self.assertFalse(
            step_customer_role_is_burden("لا يوجد عمل إداري على المتعامل")
        )

    def test_negated_admin_action_is_not_burden(self):
        self.assertFalse(step_customer_role_is_burden(
            "No upload or re-entry of data already known to government"
        ))
        self.assertFalse(step_customer_role_is_burden(
            "لا يرفع أو يعيد إدخال بيانات معروفة حكوميًا"
        ))

    def test_package_choice_is_not_burden(self):
        self.assertFalse(
            step_customer_role_is_burden("Selects or changes the package.")
        )

    def test_payment_approval_without_admin_work_is_not_burden(self):
        self.assertFalse(
            step_customer_role_is_burden("Review the amount and pay")
        )
        self.assertFalse(
            step_customer_role_is_burden("Reviews the amount and pays.")
        )

    def test_genuine_remaining_admin_work_is_burden(self):
        self.assertTrue(step_customer_role_is_burden(
            "Customer prints, signs, gets the form notarized, and "
            "personally submits the original document at the office."
        ))
        self.assertTrue(step_customer_role_is_burden(
            "العميل يرفع صورة من المستند المطلوب."
        ))
        self.assertTrue(step_customer_role_is_burden(
            "The customer must still visit the branch to collect the "
            "physical card."
        ))

    def test_empty_text_is_not_burden(self):
        self.assertFalse(step_customer_role_is_burden(""))
        self.assertFalse(step_customer_role_is_burden(None))


class TemplatePathHiddenBurdenIsDetected(unittest.TestCase):
    """A brand-new (non-demo) service whose current journey requires an
    in-person notarized submission that step_compliance does NOT lock
    as AS_IS (i.e. it is not protected — it is left for the redesign
    to genuinely re-architect). Before the fix, this stage's
    customer_burden was always False no matter what remained, so the
    Zero Bureaucracy score could not tell the difference between a
    journey that truly removed customer effort and one that just
    renamed it. After the fix, remaining burden is measured from the
    stage's own customer_role text.
    """

    def test_unresolved_in_person_step_lowers_customer_effort_reduction(self):
        value = service(
            "Apply for a research equipment loan",
            [
                "Customer submits the equipment loan request",
                "Customer uploads a signed liability waiver",
                "Customer visits the lab office to collect the equipment "
                "in person",
                "Employee verifies the waiver",
                "Employee logs the loan in the inventory system",
                "Employee hands over the equipment",
            ],
        )
        _, redesign, metrics, _ = analyze(value)

        # This is a generic, service-agnostic assertion: whatever the
        # template fallback produced, the future journey's own
        # customer-effort-reduction figure must not silently jump to
        # 100% while a future stage's own customer_role still
        # describes genuine administrative work.
        future_steps = redesign["future_steps"]
        any_stage_still_describes_admin_work = any(
            step_customer_role_is_burden(step.get("customer_role", ""))
            for step in future_steps
        )
        if any_stage_still_describes_admin_work:
            self.assertGreater(
                metrics["future"]["customer_burden_steps"], 0,
                "A future stage whose own customer_role text still "
                "describes administrative work must be counted as "
                "customer burden.",
            )
            self.assertLess(
                metrics["transformation"][
                    "customer_effort_reduction_percent"
                ],
                100,
            )


class AIPathHiddenBurdenIsDetected(unittest.TestCase):
    """Same proof as above, but through the AI-designed journey path
    (a mock LLM standing in for Ollama), matching how
    journey_builder_agent actually runs in production when Ollama is
    available. Confirms the fix applies to both code paths, not just
    the deterministic template fallback.
    """

    def test_ai_designed_stage_with_real_admin_work_is_counted(self):
        import sys
        import os

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__))
        )
        from test_full_pipeline_ai_scenarios import (  # noqa: E402
            ScenarioMockLLM,
            step,
            run_pipeline,
        )

        current_steps = [
            "Customer requests a duplicate property title deed",
            "Customer fills the request form",
            "Customer uploads proof of ownership",
            "Employee verifies ownership records",
            "Customer visits the registry office to sign the new deed "
            "in person",
            "Employee issues the duplicate deed",
        ]
        future = [
            step(
                "Intake duplicate deed request", "SYSTEM",
                "The assistant captures the request and confirms the "
                "property reference from the connected land registry, "
                "since every later stage depends on it.",
            ),
            step(
                "Verify ownership", "SYSTEM",
                "The assistant verifies current ownership directly "
                "against the land registry instead of asking the "
                "customer to upload proof.",
            ),
            step(
                "In-person signature at the registry", "HUMAN",
                "Regulation requires a wet-ink signature on the new "
                "deed, so the customer must still travel to the "
                "registry office and sign the document in person "
                "before it can be issued.",
                human=True,
                human_reason=(
                    "A physical signature on the deed is a statutory "
                    "requirement that cannot be automated."
                ),
                customer_role=(
                    "Customer travels to the registry office and signs "
                    "the new deed in person."
                ),
            ),
            step(
                "Issue duplicate deed", "SYSTEM",
                "The assistant issues and digitally records the "
                "duplicate deed immediately after the signature is "
                "captured.",
                customer_role="Receives the outcome.",
            ),
        ]
        llm = ScenarioMockLLM(future)
        value = {
            "service_name": "Duplicate property title deed",
            "description": "\n".join(current_steps),
            "steps": current_steps,
            "lang": "en",
        }
        result = run_pipeline(value, llm)
        redesign = result["redesign"]
        self.assertEqual(redesign["analysis_source"], "ai")

        metrics = calculate_metrics(value, redesign)
        self.assertGreater(
            metrics["future"]["customer_burden_steps"], 0,
            "The in-person signature stage still describes genuine "
            "customer administrative work in its own customer_role "
            "and must be counted.",
        )
        self.assertLess(
            metrics["transformation"]["customer_effort_reduction_percent"],
            100,
        )


class CleanRedesignStillReportsFullReduction(unittest.TestCase):
    """Guard against over-correction: a future journey that genuinely
    removes all customer administrative work must still report 100%
    customer effort reduction after the fix."""

    def test_fully_agent_executed_journey_still_reports_100_percent(self):
        value = service(
            "Report a broken streetlight",
            [
                "Customer visits the branch to report a broken "
                "streetlight",
                "Customer fills a paper complaint form",
                "Employee logs the complaint manually",
                "Employee dispatches a technician",
                "Technician fixes the streetlight",
                "Employee closes the complaint",
            ],
        )
        _, redesign, metrics, _ = analyze(value)
        future_steps = redesign["future_steps"]
        self.assertFalse(any(
            step_customer_role_is_burden(step.get("customer_role", ""))
            for step in future_steps
        ))
        self.assertEqual(metrics["future"]["customer_burden_steps"], 0)
        self.assertEqual(
            metrics["transformation"]["customer_effort_reduction_percent"],
            100,
        )


if __name__ == "__main__":
    unittest.main()
