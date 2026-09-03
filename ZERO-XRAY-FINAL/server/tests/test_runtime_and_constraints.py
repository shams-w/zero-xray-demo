import tempfile
import unittest
from pathlib import Path

from agents.journey_builder_agent import JourneyBuilderAgent
from agents.step_compliance_agent import StepComplianceAgent
from core.runtime_store import RuntimeStore
from core.standards_catalog import STANDARDS_CATALOG
from core.standards_retrieval import retrieve_standard_evidence


STANDARDS = {"applicable_standards": STANDARDS_CATALOG}


class HumanConstraintTests(unittest.TestCase):
    def test_as_is_lock_is_never_removed(self):
        service = {
            "service_name": "Protected service",
            "description": "",
            "steps": [
                "Customer visits the service center",
                "Employee issues the result",
            ],
            "protected_steps": [
                {
                    "step_number": 1,
                    "level": "AS_IS",
                    "reason": "Temporary policy requirement",
                    "source_reference": "POL-10",
                }
            ],
        }
        compliance = StepComplianceAgent().run(service, {}, STANDARDS)
        first = compliance["step_assessment"][0]
        self.assertEqual(first["decision"], "KEEP")
        self.assertEqual(first["human_constraint"]["level"], "AS_IS")

        redesign = JourneyBuilderAgent().run(service, compliance, STANDARDS)
        self.assertFalse(any(
            item["step"] == service["steps"][0]
            for item in redesign["removed_steps"]
        ))
        protected = [
            item
            for item in redesign["future_steps"]
            if item.get("implementation_status") == "HUMAN_LOCKED_AS_IS"
        ]
        self.assertEqual(len(protected), 1)
        self.assertTrue(protected[0]["customer_burden"])
        self.assertEqual(redesign["future_customer_burden_steps"], 1)

    def test_requirement_lock_can_be_automated_but_not_removed(self):
        service = {
            "service_name": "Document service",
            "description": "",
            "steps": ["Customer uploads an identity document"],
            "protected_steps": [
                {
                    "step_number": 1,
                    "level": "REQUIREMENT",
                    "reason": "Identity evidence is mandatory",
                    "source_reference": "ID-POLICY",
                }
            ],
        }
        compliance = StepComplianceAgent().run(service, {}, STANDARDS)
        first = compliance["step_assessment"][0]
        self.assertNotEqual(first["decision"], "REMOVE")
        self.assertEqual(first["human_constraint"]["level"], "REQUIREMENT")


class RuntimeStoreTests(unittest.TestCase):
    def test_sandbox_journey_state_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            service = {
                "service_name": "Renew P.O. Box",
                "description": "Customer pays AED 120",
                "steps": ["Customer pays AED 120", "System issues confirmation"],
                "waiting_times": ["1 working day"],
            }
            analysis = {
                "redesign": {
                    "future_steps": [
                        {
                            "name": "Assistant executes renewal",
                            "action": "Submit and verify the renewal",
                            "completion_evidence": "Renewal reference",
                        }
                    ],
                    "required_integrations": [
                        {"status": "PROPOSED", "description": "P.O. Box API"}
                    ],
                }
            }
            blueprint = store.save_blueprint(service, analysis)
            self.assertEqual(blueprint["status"], "DRAFT")
            store.set_blueprint_status(blueprint["id"], "APPROVED")
            published = store.set_blueprint_status(blueprint["id"], "PUBLISHED")
            self.assertEqual(published["status"], "PUBLISHED")

            customer = store.register_customer("Test User", "test@example.com")
            journey = store.create_journey(
                customer["id"],
                "I want to renew my P.O. Box",
                blueprint_id=blueprint["id"],
                lang="en",
                sandbox=True,
            )
            self.assertEqual(journey["state"], "PLAN_READY")
            self.assertEqual(journey["plan"]["fee_amount"], 120.0)
            self.assertEqual(journey["plan"]["edit_options"]["mode"], "PAYMENT")
            self.assertEqual(
                journey["plan"]["edit_options"]["contract_durations"],
                [1, 2, 3, 5, 10],
            )

            package_id = journey["plan"]["edit_options"]["packages"][0]["id"]
            journey = store.edit_plan(
                journey["id"],
                selections={
                    "selected_package_id": package_id,
                    "contract_years": 2,
                    "auto_renewal": True,
                },
            )
            self.assertEqual(journey["plan_version"], 2)
            self.assertEqual(journey["plan"]["contract_years"], 2)
            self.assertEqual(journey["plan"]["fee_amount"], 240.0)
            self.assertTrue(journey["plan"]["auto_renewal"])
            journey = store.approve_plan(journey["id"])
            self.assertEqual(journey["state"], "PLAN_APPROVED")
            journey = store.pay(journey["id"], "SANDBOX_CARD")
            self.assertEqual(journey["state"], "PAID")
            journey = store.start_execution(journey["id"])
            self.assertEqual(journey["state"], "EXECUTING")
            self.assertTrue(store.list_events(journey["id"]))
            journey = store.complete_journey(journey["id"])
            self.assertEqual(journey["state"], "COMPLETED")

    def test_human_handoff_cannot_be_overwritten_by_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            blueprint = store.save_blueprint(
                {"service_name": "Assisted service", "steps": []},
                {"redesign": {"future_steps": []}},
            )
            customer = store.register_customer("Test User", "test@example.com")
            journey = store.create_journey(
                customer["id"],
                "I need assisted service",
                blueprint_id=blueprint["id"],
                sandbox=True,
            )
            store.approve_plan(journey["id"])
            store.start_execution(journey["id"])
            journey = store.change_journey_state(journey["id"], "HUMAN_HANDOFF")
            self.assertEqual(journey["state"], "HUMAN_HANDOFF")
            journey = store.complete_journey(journey["id"])
            self.assertEqual(journey["state"], "HUMAN_HANDOFF")

    def test_complaint_edit_uses_case_choices_without_payment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            blueprint = store.save_blueprint(
                {
                    "service_name": "Customer complaint",
                    "description": "Submit a complaint about delayed delivery",
                    "steps": ["Customer describes the complaint"],
                },
                {"redesign": {"future_steps": []}},
            )
            customer = store.register_customer("Test User", "test@example.com")
            journey = store.create_journey(
                customer["id"],
                "I want to submit a complaint",
                blueprint_id=blueprint["id"],
                sandbox=True,
            )
            self.assertFalse(journey["plan"]["requires_payment"])
            self.assertEqual(journey["plan"]["edit_options"]["mode"], "CASE")
            journey = store.edit_plan(
                journey["id"],
                selections={
                    "priority": "HIGH",
                    "requested_resolution": "CORRECT_SERVICE",
                },
            )
            self.assertEqual(journey["plan"]["case_priority"], "HIGH")
            self.assertEqual(
                journey["plan"]["requested_resolution"],
                "CORRECT_SERVICE",
            )

    def test_inquiry_edit_uses_topics_and_response_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            blueprint = store.save_blueprint(
                {
                    "service_name": "Customer Inquiry Service",
                    "description": "A free information service. No fee.",
                    "service_type": "INFORMATION",
                    "payment_requirement": "NOT_REQUIRED",
                    "steps": ["Select an inquiry topic", "Receive a sourced answer"],
                },
                {"redesign": {"future_steps": []}},
            )
            customer = store.register_customer("Test User", "test@example.com")
            journey = store.create_journey(
                customer["id"],
                "I need information about required documents",
                blueprint_id=blueprint["id"],
                sandbox=True,
            )

            self.assertFalse(journey["plan"]["requires_payment"])
            self.assertEqual(journey["plan"]["edit_options"]["mode"], "INQUIRY")

            journey = store.edit_plan(
                journey["id"],
                selections={
                    "inquiry_topic": "REQUIRED_DOCUMENTS",
                    "response_channel": "EMAIL",
                },
            )

            self.assertEqual(journey["plan"]["inquiry_topic"], "REQUIRED_DOCUMENTS")
            self.assertEqual(journey["plan"]["response_channel"], "EMAIL")


class StandardsRetrievalTests(unittest.TestCase):
    def test_retrieval_returns_reviewable_source_sections(self):
        guide = (
            "Outcome first\nThe assistant starts from the customer's outcome.\n\n"
            "Payment\nThe customer approves fees before payment.\n\n"
            "Exceptions\nTransfer the complete context to a human."
        )
        evidence = retrieve_standard_evidence(
            guide,
            "Customer pays a fee and approves the amount",
            limit=2,
        )
        self.assertTrue(evidence)
        self.assertTrue(all(item["evidence_id"].startswith("GUIDE-") for item in evidence))
        self.assertIn("Payment", evidence[0]["text"])


if __name__ == "__main__":
    unittest.main()
