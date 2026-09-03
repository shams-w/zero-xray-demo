"""
End-to-end pipeline tests exercising the full agent chain with a mock
Ollama client, covering the scenarios required for the AI-primary /
template-fallback rearchitecture:

  1. International shipping (weight-dependent, deferred payment)
  2. A service with no payment at all
  3. A service with an eligibility gate
  4. A service requiring genuine human approval
  5. A fixed-fee service (payment can be up front)
  6. A completely different service (proves no shipping special-casing)
  7. Detailed, service-specific step explanations
  8. Ollama failure / timeout / malformed JSON -> safe fallback
  9. The pre-existing test suite (run separately; see test_runtime_
     and_constraints.py / test_adaptive_service_paths.py /
     test_agentic_redesign.py, unaffected by any of this).

These tests call each agent directly (service_agent -> standards_agent
-> gap_agent -> step_compliance_agent -> journey_builder_agent ->
validation_agent) in the same order graph/workflow.py wires them,
without requiring langgraph/fastapi to be installed.
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


def journey_payload(steps, overall="AI-designed journey."):
    return json.dumps({
        "overall_reasoning": overall,
        "steps": steps,
    })


def step(name, type_, detail, reasoning="Because it follows logically.",
         has_payment=False, payment_reason="", human=False,
         human_reason="", depends_on="", customer_role="Reviews and confirms."):
    return {
        "name": name,
        "type": type_,
        "action": detail[:80],
        "detailed_description": detail,
        "reasoning": reasoning,
        "customer_role": customer_role,
        "has_payment": has_payment,
        "payment_reasoning": payment_reason,
        "requires_human_judgement": human,
        "human_judgement_reason": human_reason,
        "depends_on_previous": depends_on,
    }


class ScenarioMockLLM:
    """Routes generate() calls to canned, realistic responses based
    on recognizable content in the prompt, so each agent's real
    parsing/validation code runs against a genuine-looking payload.
    """

    def __init__(self, journey_steps, fail=False, malformed=False):
        self.journey_steps = journey_steps
        self.fail = fail
        self.malformed = malformed
        self.calls = []

    def generate(self, system_prompt, user_prompt, max_new_tokens=None,
                 temperature=0, timeout=None):
        self.calls.append(user_prompt[:60])

        if self.fail:
            # Simulate a network failure / timeout the way LocalLLM
            # itself reports one: an empty string.
            return ""

        if self.malformed:
            return "<<< not json, sorry about that >>>"

        # Full future-journey design (journey_builder_agent)
        if '"detailed_description"' in user_prompt or "Design the proposed FUTURE journey" in user_prompt:
            return journey_payload(self.journey_steps)

        # Step compliance review
        if '"assessments"' in user_prompt:
            steps_in_prompt = user_prompt.count("\n") # not used, just placeholder
            return json.dumps({"assessments": []})  # deliberately let count-mismatch fallback trigger unless overridden

        # Standards selection
        if "applicable_standard_ids" in user_prompt:
            return json.dumps({
                "applicable_standard_ids": ["STD-01", "STD-02", "STAGE-07"],
                "why_it_applies": {
                    "STD-01": "Outcome-based design applies.",
                    "STD-02": "Manual work exists.",
                    "STAGE-07": "Payment is involved.",
                },
            })

        # Gap analysis
        if '"gaps"' in user_prompt:
            return json.dumps({"gaps": []})

        # Service analysis
        if '"objective"' in user_prompt:
            return json.dumps({
                "objective": "The customer wants the outcome delivered with minimal effort.",
                "friction_points": [],
            })

        # Validation semantic review
        if '"verdict"' in user_prompt:
            return json.dumps({"issues": [], "verdict": "PASS"})

        return ""


def run_pipeline(service, llm):
    service_agent = ServiceAnalystAgent(llm)
    standards_agent = StandardsAgent(llm)
    gap_agent = GapAnalysisAgent(llm)
    step_compliance_agent = StepComplianceAgent(llm)
    journey_builder_agent = JourneyBuilderAgent(llm)
    validation_agent = ValidationAgent(llm)

    service_analysis = service_agent.run(service)
    relevant_standards = standards_agent.run(service_analysis, STANDARDS_SEED)
    gaps = gap_agent.run(service_analysis, relevant_standards)
    step_compliance = step_compliance_agent.run(
        service, service_analysis, relevant_standards
    )
    redesign = journey_builder_agent.run(
        service, step_compliance, relevant_standards, gaps
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
        "service_analysis": service_analysis,
        "relevant_standards": relevant_standards,
        "gaps": gaps,
        "step_compliance": step_compliance,
        "redesign": redesign,
        "validation": validation,
    }


class Scenario1InternationalShipping(unittest.TestCase):
    """Weight determines the fee -> payment must be AFTER weighing,
    not before. Pure test case, not a special-cased path."""

    def test_payment_after_weighing(self):
        steps = [
            step(
                "Capture shipment and destination",
                "SYSTEM",
                "The assistant collects the sender, destination and package description, verifying the destination is served before proceeding, since every later stage depends on knowing where the shipment is going.",
            ),
            step(
                "Pickup and actual weighing",
                "SYSTEM",
                "A courier collects the package and records its actual weight and dimensions, because international shipping cost depends on these physical measurements rather than any earlier estimate.",
                depends_on="Needs the destination from stage 1.",
            ),
            step(
                "Final cost calculation and payment",
                "SYSTEM",
                "Using the actual weight and destination, the assistant calculates the final fee and collects payment only after the amount is known, since it could not be determined before the package was weighed.",
                has_payment=True,
                payment_reason="The fee is only knowable after the actual weight is measured.",
                depends_on="Needs the actual weight from stage 2.",
            ),
            step(
                "Dispatch and tracking",
                "SYSTEM",
                "The assistant dispatches the shipment through the carrier network and provides live tracking until delivery is confirmed.",
                depends_on="Needs payment confirmed in stage 3.",
            ),
        ]
        llm = ScenarioMockLLM(steps)
        service = {
            "service_name": "International Shipping",
            "description": "Customer ships a package abroad; the fee depends on the actual weight measured at pickup.",
            "steps": [
                "Customer submits shipment request",
                "Courier collects and weighs the package",
                "Customer pays the shipping fee",
                "Shipment is dispatched and tracked",
            ],
            "lang": "en",
        }
        result = run_pipeline(service, llm)
        redesign = result["redesign"]
        self.assertEqual(redesign["analysis_source"], "ai")
        future = redesign["future_steps"]
        payment_index = next(i for i, s in enumerate(future) if s["has_payment"])
        weigh_index = next(
            i for i, s in enumerate(future)
            if "weigh" in s["detailed_description"].lower()
        )
        self.assertGreater(payment_index, weigh_index,
                            "Payment must come after weighing, not before.")
        for s in future:
            self.assertGreaterEqual(len(s["detailed_description"]), 30)
            self.assertEqual(s["analysis_source"], "ai")


class Scenario2NoPayment(unittest.TestCase):
    def test_no_payment_invented(self):
        steps = [
            step(
                "Understand the information request",
                "SYSTEM",
                "The assistant identifies exactly which public information the customer needs and confirms scope before any lookup begins, so no unnecessary data is retrieved.",
            ),
            step(
                "Retrieve and verify the information",
                "SYSTEM",
                "The assistant retrieves the requested information from the authoritative government source and verifies it is current before presenting it to the customer.",
                depends_on="Needs the scope from stage 1.",
            ),
            step(
                "Deliver the result",
                "SYSTEM",
                "The assistant presents the verified information to the customer in a clear format and offers a correction path if anything looks wrong.",
                depends_on="Needs the verified information from stage 2.",
            ),
        ]
        llm = ScenarioMockLLM(steps)
        service = {
            "service_name": "Public Information Lookup",
            "description": "Customer wants to know the opening hours of a government office. No fee is involved.",
            "steps": [
                "Customer asks for the information",
                "Employee looks it up",
                "Employee replies to the customer",
            ],
            "lang": "en",
        }
        result = run_pipeline(service, llm)
        future = result["redesign"]["future_steps"]
        self.assertFalse(any(s["has_payment"] for s in future),
                          "No payment step should be invented for a free service.")


class Scenario3Eligibility(unittest.TestCase):
    def test_eligibility_before_dependent_steps(self):
        steps = [
            step(
                "Verify eligibility",
                "SYSTEM",
                "The assistant checks the customer's eligibility for the subsidy against the program's registered criteria before any further processing, since the rest of the journey is meaningless if the customer does not qualify.",
            ),
            step(
                "Collect supporting documents",
                "SYSTEM",
                "Once eligibility is confirmed, the assistant collects only the supporting documents required to substantiate the specific subsidy category the customer qualifies for.",
                depends_on="Needs the eligibility outcome from stage 1.",
            ),
            step(
                "Approve and disburse",
                "HUMAN",
                "A caseworker reviews the substantiated eligibility and documents and approves disbursement, a judgement call the system cannot make on its own because it affects public funds.",
                human=True,
                human_reason="Disbursement of public funds requires accountable human sign-off.",
                depends_on="Needs the documents from stage 2.",
            ),
        ]
        llm = ScenarioMockLLM(steps)
        service = {
            "service_name": "Housing Subsidy Application",
            "description": "Customer applies for a housing subsidy; only eligible applicants can proceed.",
            "steps": [
                "Customer applies",
                "Eligibility is checked",
                "Documents are reviewed",
                "Caseworker approves",
            ],
            "lang": "en",
        }
        result = run_pipeline(service, llm)
        future = result["redesign"]["future_steps"]
        eligibility_index = next(
            i for i, s in enumerate(future) if "eligib" in s["name"].lower()
        )
        for i, s in enumerate(future):
            if i != eligibility_index and "depends" in s.get("depends_on_previous", "").lower():
                pass  # dependency wording varies; structural check below is what matters
        self.assertEqual(eligibility_index, 0,
                          "Eligibility should be checked before dependent steps.")


class Scenario4HumanApproval(unittest.TestCase):
    def test_human_step_marked_and_justified(self):
        steps = [
            step("Intake", "SYSTEM", "The assistant records the request and confirms the applicant's basic details before routing it for review."),
            step(
                "Committee review",
                "HUMAN",
                "A licensing committee reviews the application against safety criteria that require professional judgement, which is why this step cannot be automated.",
                human=True,
                human_reason="Safety judgement calls require accountable professional review.",
            ),
            step("Issue result", "SYSTEM", "The assistant issues the license or a rejection notice once the committee's decision is recorded."),
        ]
        llm = ScenarioMockLLM(steps)
        service = {
            "service_name": "Hazardous Materials License",
            "description": "Customer applies for a license to handle hazardous materials; a safety committee must review it.",
            "steps": ["Customer applies", "Committee reviews", "License issued"],
            "lang": "en",
        }
        result = run_pipeline(service, llm)
        future = result["redesign"]["future_steps"]
        human_steps = [s for s in future if s["type"] == "HUMAN"]
        self.assertTrue(human_steps, "A genuine human-approval step should be preserved.")
        self.assertTrue(all(s["requires_human_judgement"] for s in human_steps))
        self.assertTrue(all(len(s["reasoning"]) > 0 for s in human_steps))


class Scenario5FixedFee(unittest.TestCase):
    def test_payment_can_be_upfront_when_fee_is_known(self):
        steps = [
            step(
                "Confirm renewal details",
                "SYSTEM",
                "The assistant confirms the customer's identity and current license details, which are already on file and do not need to be re-entered.",
            ),
            step(
                "Collect the fixed renewal fee",
                "SYSTEM",
                "Because the renewal fee is a fixed, published amount that does not depend on anything produced later, the assistant collects payment immediately after confirming the details.",
                has_payment=True,
                payment_reason="The fee is a fixed statutory amount known in advance.",
                depends_on="Needs the confirmed details from stage 1.",
            ),
            step(
                "Issue the renewed license",
                "SYSTEM",
                "Once payment is confirmed, the assistant issues the renewed license immediately and makes it available to the customer.",
                depends_on="Needs payment confirmed in stage 2.",
            ),
        ]
        llm = ScenarioMockLLM(steps)
        service = {
            "service_name": "Driving License Renewal",
            "description": "Customer renews a driving license for a fixed statutory fee.",
            "steps": ["Customer requests renewal", "Customer pays the fixed fee", "License is renewed"],
            "lang": "en",
        }
        result = run_pipeline(service, llm)
        future = result["redesign"]["future_steps"]
        payment_index = next(i for i, s in enumerate(future) if s["has_payment"])
        self.assertLess(payment_index, len(future) - 1,
                         "Fixed-fee payment may legitimately happen before final execution.")


class Scenario6DifferentServiceNoTemplateReuse(unittest.TestCase):
    """Proves the shipping example isn't hard-coded: a totally
    different domain (a school enrollment service) gets its own
    AI-designed steps, not a copy of the shipping stage names."""

    def test_distinct_domain_gets_its_own_steps(self):
        steps = [
            step(
                "Capture enrollment preferences",
                "SYSTEM",
                "The assistant collects the child's grade level and preferred schools directly from the parent, since these choices are unique to this family and cannot be inferred.",
            ),
            step(
                "Verify residency and age",
                "SYSTEM",
                "The assistant verifies the child's age and residency against civil records to confirm enrollment eligibility for the selected school zone.",
                depends_on="Needs the preferences from stage 1.",
            ),
            step(
                "Assign a school place",
                "SYSTEM",
                "Based on verified eligibility and available capacity, the assistant assigns the child a place at the best-matching school and notifies the parent.",
                depends_on="Needs the verification result from stage 2.",
            ),
        ]
        llm = ScenarioMockLLM(steps)
        service = {
            "service_name": "School Enrollment",
            "description": "Parent enrolls a child in a public school for the upcoming year.",
            "steps": ["Parent applies", "Eligibility verified", "Place assigned"],
            "lang": "en",
        }
        result = run_pipeline(service, llm)
        future = result["redesign"]["future_steps"]
        names = [s["name"].lower() for s in future]
        shipping_words = ["weigh", "shipment", "courier", "dispatch", "tracking"]
        self.assertFalse(
            any(word in " ".join(names) for word in shipping_words),
            "A school-enrollment journey must not carry over shipping-specific stages.",
        )
        self.assertTrue(any("school" in n or "enroll" in n or "resid" in n or "eligib" in n for n in names))


class Scenario7DetailedExplanations(unittest.TestCase):
    def test_every_step_has_a_real_detailed_description(self):
        steps = [
            step("Stage A", "SYSTEM", "A" * 40),
            step("Stage B", "SYSTEM", "B" * 40),
        ]
        llm = ScenarioMockLLM(steps)
        service = {"service_name": "X", "description": "Y", "steps": ["a", "b"], "lang": "en"}
        result = run_pipeline(service, llm)
        future = result["redesign"]["future_steps"]
        for s in future:
            self.assertIn("detailed_description", s)
            self.assertGreaterEqual(len(s["detailed_description"]), 30)
            self.assertIn("reasoning", s)
            self.assertEqual(s["analysis_source"], "ai")
        self.assertEqual(result["redesign"]["analysis_source"], "ai")


class Scenario8FailureAndMalformedJSON(unittest.TestCase):
    def _service(self):
        return {
            "service_name": "International Shipping",
            "description": "Ships packages; fee depends on weight.",
            "steps": [
                "Customer submits shipment request",
                "Courier collects and weighs the package",
                "Customer pays the shipping fee",
                "Shipment is dispatched and tracked",
            ],
            "lang": "en",
        }

    def test_llm_failure_falls_back_cleanly(self):
        llm = ScenarioMockLLM(journey_steps=[], fail=True)
        result = run_pipeline(self._service(), llm)
        redesign = result["redesign"]
        self.assertEqual(redesign["analysis_source"], "template")
        self.assertTrue(redesign["future_steps"])
        for s in redesign["future_steps"]:
            self.assertEqual(s["analysis_source"], "template")
        # Every other stage must still produce a usable, non-crashing
        # result when the AI is unavailable end to end.
        self.assertIn("step_assessment", result["step_compliance"])
        self.assertIn("applicable_standards", result["relevant_standards"])
        self.assertIn("status", result["validation"])

    def test_malformed_json_falls_back_cleanly(self):
        llm = ScenarioMockLLM(journey_steps=[], malformed=True)
        result = run_pipeline(self._service(), llm)
        redesign = result["redesign"]
        self.assertEqual(redesign["analysis_source"], "template")
        self.assertTrue(redesign["future_steps"])
        self.assertIn("status", result["validation"])

    def test_no_llm_at_all_falls_back_cleanly(self):
        result = run_pipeline(self._service(), llm=None)
        redesign = result["redesign"]
        self.assertEqual(redesign["analysis_source"], "template")
        self.assertTrue(redesign["future_steps"])


if __name__ == "__main__":
    unittest.main()
