"""Regression tests for the FINAL FIX PASS root causes.

Every test here is service-agnostic on purpose: each one uses a made-up
service from a different domain, so a fix that only worked for one
particular service (or one particular imported specification) would fail
here. Nothing in these tests -- or in the code they cover -- references a
real service, tenant or API.

Covered root causes:
  1. Unsubstantiated AI validation FAIL.
  2. OpenAPI/organization context contaminating the current journey.
  3. AI future journey not grounded in the actual available operations.
  4. Verification misread as human approval.
  5. Duplicate frontend triggers (backend-visible half).
  6. Gap agent discarding usable AI output / masking an empty result.
"""

import unittest

from agents.gap_agent import GapAnalysisAgent
from agents.journey_builder_agent import JourneyBuilderAgent
from agents.service_agent import ServiceAnalystAgent
from agents.validation_agent import ValidationAgent


class RecordingLLM:
    """Minimal LLM double that returns queued responses and records the
    prompts it was given, so a test can assert what the model actually
    got to see."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def generate(self, system_prompt="", user_prompt="", **kwargs):
        self.prompts.append(user_prompt)
        if not self._responses:
            return ""
        return self._responses.pop(0)


def _future_step(**overrides):
    step = {
        "step_number": 1,
        "name": "Confirm request details",
        "type": "SYSTEM",
        "action": "The assistant confirms the submitted request details.",
        "detailed_description": (
            "The assistant reads the details already supplied with the "
            "request and confirms them without asking the customer again."
        ),
        "reason": "Removes a repeated data entry step.",
        "reasoning": "Removes a repeated data entry step.",
        "change_type": "AUTOMATED",
        "standard_id": "STD-01",
        "semantic_category": "execution_continuity",
        "has_payment": False,
        "requires_human_judgement": False,
        "requires_customer_approval": False,
        "delivers_customer_result": False,
        "depends_on_previous": "",
        "customer_role": "None",
        "customer_burden": False,
        "owner": "ASSISTANT",
        "source_steps": ["Customer submits the request"],
    }
    step.update(overrides)
    return step


def _passing_inputs():
    """A redesign/metrics/standards set that passes every deterministic
    gate, so any FAIL observed must come from the AI review."""
    redesign = {
        "future_steps": [
            _future_step(),
            _future_step(
                step_number=2,
                name="Deliver the outcome",
                action="The assistant delivers the completed outcome.",
                detailed_description=(
                    "The assistant completes the request and returns the "
                    "result to the customer in the same session."
                ),
                delivers_customer_result=True,
                semantic_category="customer_outcome",
                change_type="MERGED",
                source_steps=[
                    "Customer submits the request",
                    "Employee closes the request",
                ],
            ),
        ],
        "removed_steps": [
            {
                "step": "Employee closes the request",
                "reason": "The assistant completes and closes it directly.",
                "standard_id": "STD-01",
            }
        ],
        "exception_paths": [
            {
                "name": "Specialist handoff",
                "trigger": "The automated path cannot complete the request.",
                "action": "The request is routed to a specialist for review.",
                "standard_id": "STD-01",
            }
        ],
        "control_points": [],
        "required_integrations": [],
    }
    metrics = {
        "valid_for_scoring": True,
        "validation_errors": [],
        "zero_bureaucracy_score": 85,
    }
    standards = {
        "applicable_standards": [
            {"standard_id": "STD-01", "title": "Reduce customer effort"},
        ]
    }
    return redesign, metrics, standards


# =====================================================================
# 1. VALIDATION FAIL
# =====================================================================

class ValidationVerdictSubstantiationTests(unittest.TestCase):

    def _run(self, ai_response):
        redesign, metrics, standards = _passing_inputs()
        agent = ValidationAgent(RecordingLLM([ai_response]))
        return agent.run(
            service={"service_name": "Equipment Loan Request"},
            standards=standards,
            redesign=redesign,
            metrics=metrics,
        )

    def test_deterministic_gates_pass_without_ai(self):
        """Baseline: these inputs must PASS on the deterministic rules
        alone, so the tests below isolate the AI verdict."""
        redesign, metrics, standards = _passing_inputs()
        result = ValidationAgent(llm=None).run(
            service={"service_name": "Equipment Loan Request"},
            standards=standards,
            redesign=redesign,
            metrics=metrics,
        )
        self.assertEqual(result["status"], "PASS")

    def test_fail_verdict_without_high_issue_is_not_applied(self):
        """The observed failure: verdict=FAIL emitted alongside a single
        non-blocking issue blocked an otherwise clean analysis."""
        result = self._run(
            '{"issues": [{"severity": "LOW", '
            '"step": "Deliver the outcome", '
            '"issue": "The stage name could be more specific.", '
            '"required_change": "Rename the stage."}], '
            '"verdict": "FAIL"}'
        )
        self.assertEqual(result["status"], "PASS")
        # The finding itself is still surfaced -- it is downgraded from
        # blocking, not silenced.
        self.assertTrue(
            any(
                "more specific" in issue.get("issue", "")
                for issue in result["issues"]
            )
        )

    def test_fail_verdict_with_no_issues_at_all_is_not_applied(self):
        result = self._run('{"issues": [], "verdict": "FAIL"}')
        self.assertEqual(result["status"], "PASS")

    def test_grounded_high_issue_still_fails(self):
        """The guard must not become a bypass: a real, attributable
        blocking issue still fails the analysis."""
        result = self._run(
            '{"issues": [{"severity": "HIGH", '
            '"step": "Deliver the outcome", '
            '"issue": "Deliver the outcome depends on a confirmation '
            'that no earlier stage produces.", '
            '"required_change": "Produce the confirmation first."}], '
            '"verdict": "FAIL"}'
        )
        self.assertEqual(result["status"], "FAIL")

    def test_issue_about_a_nonexistent_stage_is_dropped(self):
        """A hallucinated stage reference cannot fail the analysis."""
        result = self._run(
            '{"issues": [{"severity": "HIGH", '
            '"step": "Biometric enrolment at the counter", '
            '"issue": "Biometric enrolment at the counter cannot be '
            'automated.", '
            '"required_change": "Remove it."}], '
            '"verdict": "FAIL"}'
        )
        self.assertEqual(result["status"], "PASS")

    def test_reviewer_is_given_the_journey_entry_preconditions(self):
        """ROOT CAUSE of the persistent FAIL: the reviewer judged
        dependency satisfaction without knowing what the journey starts
        with, so a correct FIRST stage declaring a dependency was forced
        into a HIGH "missing dependency" report. The designer's entry
        contract must reach the reviewer too."""
        redesign, metrics, standards = _passing_inputs()
        redesign["future_steps"][0]["depends_on_previous"] = (
            "The customer's verified identity and their request"
        )
        llm = RecordingLLM(['{"issues": [], "verdict": "PASS"}'])
        ValidationAgent(llm).run(
            service={"service_name": "Certificate Renewal"},
            standards=standards,
            redesign=redesign,
            metrics=metrics,
        )
        prompt = llm.prompts[0]
        self.assertIn("ALREADY SATISFIED BEFORE STAGE 1", prompt)
        self.assertIn("identity is already verified", prompt)
        self.assertIn(
            "Never report a missing dependency against the FIRST stage",
            prompt,
        )

    def test_high_severity_is_restricted_to_non_executable_journeys(self):
        """A recommendation/optimization must not be gradeable as HIGH."""
        redesign, metrics, standards = _passing_inputs()
        llm = RecordingLLM(['{"issues": [], "verdict": "PASS"}'])
        ValidationAgent(llm).run(
            service={"service_name": "Certificate Renewal"},
            standards=standards,
            redesign=redesign,
            metrics=metrics,
        )
        prompt = llm.prompts[0]
        self.assertIn(
            "Use HIGH ONLY when the journey cannot actually execute",
            prompt,
        )
        self.assertIn("is NEVER HIGH", prompt)
        # A redesign's own intended outcome is not an inconsistency.
        self.assertIn("This is a REDESIGN", prompt)

    def test_unattributed_high_issue_cannot_block(self):
        """A HIGH issue with no step field is reported but not blocking:
        there is nothing concrete to act on or verify."""
        redesign, metrics, standards = _passing_inputs()
        agent = ValidationAgent(RecordingLLM([
            '{"issues": [{"severity": "HIGH", '
            '"issue": "Something is inconsistent somewhere.", '
            '"required_change": "Fix it."}], "verdict": "FAIL"}'
        ]))
        result = agent.run(
            service={"service_name": "Certificate Renewal"},
            standards=standards,
            redesign=redesign,
            metrics=metrics,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(
            any(
                "inconsistent somewhere" in issue.get("issue", "")
                for issue in result["issues"]
            )
        )

    def test_reviewer_sees_the_dependency_fields_it_must_judge(self):
        redesign, metrics, standards = _passing_inputs()
        redesign["future_steps"][1]["depends_on_previous"] = (
            "The confirmed request details from the first stage"
        )
        llm = RecordingLLM(['{"issues": [], "verdict": "PASS"}'])
        ValidationAgent(llm).run(
            service={"service_name": "Equipment Loan Request"},
            standards=standards,
            redesign=redesign,
            metrics=metrics,
        )
        prompt = llm.prompts[0]
        self.assertIn("depends_on_previous", prompt)
        self.assertIn("The confirmed request details", prompt)
        self.assertIn("detailed_description", prompt)


# =====================================================================
# 2 + 3. OPENAPI CONTAMINATION AND JOURNEY GROUNDING
# =====================================================================

class OrganizationContextIsolationTests(unittest.TestCase):

    ORG_CONTEXT = (
        "AVAILABLE EXECUTION TOOLS / INTEGRATIONS:\n"
        "- Records API [REST; status=CONNECTED]\n"
        "DISCOVERED OPENAPI OPERATIONS (STRUCTURED, SERVICE-LINKED):\n"
        "- GET /v1/records | operationId=listRecords | "
        "Returns the caller's records\n"
        "- POST /v1/charges | operationId=createCharge | "
        "Creates a charge. The service fee is AED 250 per record.\n"
    )

    SERVICE = {
        "service_name": "Training Room Booking",
        "description": "Staff book a training room for a scheduled session.",
        "steps": [
            "Requester opens the booking form",
            "Requester selects a date and room",
            "Facilities officer confirms availability",
        ],
    }

    def test_semantic_step_extraction_never_sees_api_metadata(self):
        """The contamination path: API operation summaries reaching the
        step extractor made them read as additional journey steps."""
        service = dict(self.SERVICE, organization_context=self.ORG_CONTEXT)
        llm = RecordingLLM([
            '{"steps": ["Requester opens the booking form", '
            '"Requester selects a date and room", '
            '"Facilities officer confirms availability"]}',
            "",
            '{"has_payment": false, "payment_evidence": "", '
            '"has_documents": false, "documents_evidence": "", '
            '"has_physical_visit": false, "visit_evidence": "", '
            '"has_human_approval": false, "human_approval_evidence": ""}',
        ])
        result = ServiceAnalystAgent(llm).run(service)

        step_prompt = llm.prompts[0]
        self.assertNotIn("operationId", step_prompt)
        self.assertNotIn("/v1/charges", step_prompt)
        self.assertEqual(len(result["steps"]), 3)

    def test_capability_detection_never_sees_api_metadata(self):
        service = dict(self.SERVICE, organization_context=self.ORG_CONTEXT)
        llm = RecordingLLM([
            '{"steps": ["Requester opens the booking form", '
            '"Requester selects a date and room", '
            '"Facilities officer confirms availability"]}',
            "",
            '{"has_payment": false, "payment_evidence": "", '
            '"has_documents": false, "documents_evidence": "", '
            '"has_physical_visit": false, "visit_evidence": "", '
            '"has_human_approval": false, "human_approval_evidence": ""}',
        ])
        ServiceAnalystAgent(llm).run(service)

        capability_prompt = llm.prompts[-1]
        self.assertNotIn("AED 250", capability_prompt)
        self.assertNotIn("createCharge", capability_prompt)

    def test_pricing_is_not_derived_from_api_descriptions(self):
        """A fee quoted inside an imported operation description must not
        become this service's fee."""
        from core.pricing_catalog import _text

        service = dict(self.SERVICE, organization_context=self.ORG_CONTEXT)
        self.assertNotIn("aed 250", _text(service))

    def test_journey_builder_receives_operations_as_evidence(self):
        """Grounding: the designer must be told which operations exist,
        explicitly as evidence rather than as journey steps."""
        service = dict(self.SERVICE, organization_context=self.ORG_CONTEXT)
        llm = RecordingLLM([""])
        JourneyBuilderAgent(llm)._generate_ai_future_journey(
            service=service,
            step_compliance={},
            relevant_standards={},
            source_steps=list(self.SERVICE["steps"]),
            source_text=" ".join(self.SERVICE["steps"]),
            is_arabic=False,
            capabilities={},
            gaps={},
        )
        prompt = llm.prompts[0]
        self.assertIn("listRecords", prompt)
        self.assertIn("EVIDENCE", prompt)
        self.assertIn("Never invent a system", prompt)
        self.assertIn("never turn an API operation description", prompt)

    def test_journey_builder_without_integrations_states_none_available(self):
        llm = RecordingLLM([""])
        JourneyBuilderAgent(llm)._generate_ai_future_journey(
            service=dict(self.SERVICE),
            step_compliance={},
            relevant_standards={},
            source_steps=list(self.SERVICE["steps"]),
            source_text=" ".join(self.SERVICE["steps"]),
            is_arabic=False,
            capabilities={},
            gaps={},
        )
        prompt = llm.prompts[0]
        self.assertIn(
            "No systems or API operations are linked to this service",
            prompt,
        )


# =====================================================================
# 4. VERIFICATION IS NOT HUMAN APPROVAL
# =====================================================================

class VerificationVersusApprovalTests(unittest.TestCase):

    def _capabilities(self, steps, evidence):
        llm = RecordingLLM([
            '{"steps": ' + repr(steps).replace("'", '"') + "}",
            "",
            '{"has_payment": false, "payment_evidence": "", '
            '"has_documents": false, "documents_evidence": "", '
            '"has_physical_visit": false, "visit_evidence": "", '
            '"has_human_approval": true, "human_approval_evidence": '
            f'"{evidence}"}}',
        ])
        result = ServiceAnalystAgent(llm).run({
            "service_name": "Asset Transfer Request",
            "description": "An internal asset is transferred between teams.",
            "steps": steps,
        })
        return result["capabilities"]

    def test_verification_step_is_not_human_approval(self):
        steps = [
            "Requester submits the transfer request",
            "Officer verifies the asset tag against the asset register",
        ]
        capabilities = self._capabilities(
            steps,
            "Officer verifies the asset tag against the asset register",
        )
        self.assertFalse(capabilities["has_human_approval"])
        self.assertEqual(capabilities["human_approval_evidence"], "")

    def test_genuine_human_decision_is_still_human_approval(self):
        steps = [
            "Requester submits the transfer request",
            "Department head approves or rejects the transfer",
        ]
        capabilities = self._capabilities(
            steps,
            "Department head approves or rejects the transfer",
        )
        self.assertTrue(capabilities["has_human_approval"])

    def test_automated_verification_is_not_human_approval(self):
        steps = [
            "Requester submits the transfer request",
            "The system validates and confirms the asset record automatically",
        ]
        capabilities = self._capabilities(
            steps,
            "The system validates and confirms the asset record automatically",
        )
        self.assertFalse(capabilities["has_human_approval"])

    def test_keyword_fallback_applies_the_same_distinction(self):
        agent = ServiceAnalystAgent(llm=None)
        verification_steps = [
            "Officer verifies the submitted reference against the register",
        ]
        verification = agent._keyword_capabilities(
            verification_steps, " ".join(verification_steps)
        )
        self.assertFalse(verification["has_human_approval"])

        approval_steps = [
            "Committee approves the request before it proceeds",
        ]
        approval = agent._keyword_capabilities(
            approval_steps, " ".join(approval_steps)
        )
        self.assertTrue(approval["has_human_approval"])

    def test_discriminator_is_domain_agnostic(self):
        """The same wording must classify identically regardless of the
        service it appears in."""
        agent = ServiceAnalystAgent(llm=None)
        for service_flavour in (
            "permit", "grievance", "subscription", "inspection",
        ):
            evidence = (
                f"Officer verifies the {service_flavour} details "
                "against the record"
            )
            self.assertFalse(
                agent._evidence_is_human_approval(evidence),
                msg=f"verification misread as approval for {service_flavour}",
            )
            evidence = (
                f"Manager approves the {service_flavour} at their discretion"
            )
            self.assertTrue(
                agent._evidence_is_human_approval(evidence),
                msg=f"real approval missed for {service_flavour}",
            )


# =====================================================================
# 6. GAP AGENT
# =====================================================================

class GapAgentOutputTests(unittest.TestCase):

    SERVICE_ANALYSIS = {
        "steps": [
            "Applicant fills the paper form at the counter",
            "Employee re-enters the data into the system",
        ],
        "manual_actions": ["Employee re-enters the data into the system"],
        "waiting_points": [],
        "approvals": [],
        "documents": [],
        "friction_points": ["Manual operational work exists"],
        "branch_visits": 1,
    }

    STANDARDS = {
        "applicable_standards": [
            {"standard_id": "STD-7", "title": "No repeated data entry"},
        ]
    }

    def test_prompt_does_not_ship_an_empty_field_template(self):
        """The empty-string skeleton was being echoed back verbatim as
        the model's answer."""
        llm = RecordingLLM(['{"gaps": []}'])
        GapAnalysisAgent(llm).run(self.SERVICE_ANALYSIS, self.STANDARDS)
        prompt = llm.prompts[0]
        self.assertNotIn('"description": ""', prompt)
        self.assertNotIn('"standard_id": ""', prompt)
        self.assertIn("never return a gap whose fields", prompt)

    def test_echoed_empty_template_triggers_a_corrective_retry(self):
        llm = RecordingLLM([
            '{"gaps": [{"category": "", "description": "", '
            '"evidence": "", "affected_step": "", "standard_id": "", '
            '"severity": "HIGH", "recommendation": "", '
            '"expected_impact": ""}]}',
            '{"gaps": [{"category": "Data reuse", '
            '"description": "The employee re-enters data the applicant '
            'already supplied.", '
            '"evidence": "Employee re-enters the data into the system", '
            '"affected_step": "Employee re-enters the data into the system", '
            '"standard_id": "STD-7", "severity": "HIGH", '
            '"recommendation": "Capture the data once and reuse it.", '
            '"expected_impact": "Removes a full manual step."}]}',
        ])
        result = GapAnalysisAgent(llm).run(
            self.SERVICE_ANALYSIS, self.STANDARDS
        )
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("YOUR PREVIOUS ANSWER WAS REJECTED", llm.prompts[1])
        self.assertEqual(len(result["gaps"]), 1)
        self.assertEqual(result["gaps"][0]["standard_id"], "STD-7")
        self.assertNotEqual(result["analysis_source"], "template")

    def test_genuine_empty_result_is_not_reported_as_a_failure(self):
        llm = RecordingLLM(['{"gaps": []}'])
        result = GapAnalysisAgent(llm).run(
            self.SERVICE_ANALYSIS, self.STANDARDS
        )
        self.assertEqual(result["gaps"], [])
        self.assertNotEqual(result["analysis_source"], "template")
        # No retry: an empty list is a valid answer, not a malformed one.
        self.assertEqual(len(llm.prompts), 1)

    def test_deterministic_fallback_is_preserved(self):
        """Two unusable responses in a row must still fall back."""
        unusable = (
            '{"gaps": [{"standard_id": "NOT-A-REAL-ID", '
            '"description": "Something is wrong."}]}'
        )
        llm = RecordingLLM([unusable, unusable])
        result = GapAnalysisAgent(llm).run(
            self.SERVICE_ANALYSIS, self.STANDARDS
        )
        self.assertEqual(result["analysis_source"], "template")


if __name__ == "__main__":
    unittest.main()
