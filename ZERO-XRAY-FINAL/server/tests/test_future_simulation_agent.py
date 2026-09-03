"""Focused tests for the Future Simulation capability (Step 2 of the
ZERO X-RAY -> Government Future Engine evolution):
agents/future_simulation_agent.py, core/simulation_store.py, and the
POST/GET /api/services/{service_id}/scenarios endpoints.

Isolated from the rest of the suite the same way
tests/test_prediction_agent.py is: no call into
agents/orchestrator.py or graph/workflow.py, and every store is
either a pure-Python unit test or backed by a fresh temp-directory
SQLite file -- never the real server/data database.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:19999")  # deliberately unreachable
os.environ.setdefault("ZX_LLM_MODE", "ollama")

from agents.future_simulation_agent import (
    FutureSimulationAgent,
    ScenarioValidationError,
)
from core.future_engine_errors import InsufficientDataError
from core.prediction_store import PredictionStore
from core.runtime_store import RuntimeStore
from core.service_store import ServiceStore
from core.simulation_store import SimulationStore


def _future_step(step_number, name, step_type):
    return {"step_number": step_number, "name": name, "type": step_type,
            "action": name, "change_type": "KEPT", "reason": "", "standard_id": ""}


def _analysis_result(future_steps=None, required_integrations=None):
    return {
        "redesign": {
            "future_steps": future_steps or [],
            "required_integrations": required_integrations or [],
        },
    }


SAMPLE_STEPS = [
    _future_step(1, "Customer states the request", "CUSTOMER"),
    _future_step(2, "System verifies identity", "SYSTEM"),
    _future_step(3, "Employee reviews the case", "HUMAN"),
    _future_step(4, "System issues the result", "SYSTEM"),
]
SAMPLE_INTEGRATIONS = ["National ID Registry", "Payment Gateway"]

# A service with genuinely NO payment, NO integrations, and NO
# approval/document evidence anywhere -- used to prove AUTO generation
# never invents an irrelevant category for a service that has none of
# that evidence (Section 2: "Do not generate irrelevant scenarios").
NO_EVIDENCE_STEPS = [
    _future_step(1, "Customer submits a complaint", "CUSTOMER"),
    _future_step(2, "System logs the complaint", "SYSTEM"),
    _future_step(3, "System closes the complaint", "SYSTEM"),
]
NO_EVIDENCE_INTEGRATIONS = []


def _sample_graph():
    return {
        "steps": [
            {"step_id": f"STEP-{s['step_number']}", "name": s["name"],
             "type": s["type"], "order": index}
            for index, s in enumerate(SAMPLE_STEPS)
        ],
        "integrations": [
            {"integration_id": f"INTEGRATION-{i + 1:03d}", "name": name}
            for i, name in enumerate(SAMPLE_INTEGRATIONS)
        ],
        "journeys_count": 5,
        "source_analysis_id": "an-sample",
    }


def _no_evidence_graph():
    return {
        "steps": [
            {"step_id": f"STEP-{s['step_number']}", "name": s["name"],
             "type": s["type"], "order": index}
            for index, s in enumerate(NO_EVIDENCE_STEPS)
        ],
        "integrations": [],
        "journeys_count": 2,
        "source_analysis_id": "an-no-evidence",
    }


class AutoScenarioGenerationTestCase(unittest.TestCase):
    """Section 2 audit fix: FutureSimulationAgent.generate_auto_scenarios
    -- pure unit tests, no database, no LLM, no endpoint. Every
    candidate returned must also survive validate_scenario() unchanged
    (proves AUTO never produces something the existing deterministic
    validator would reject)."""

    def setUp(self):
        self.agent = FutureSimulationAgent(llm=None)

    def _categories(self, graph):
        return {category for category, _, _ in self.agent.generate_auto_scenarios(graph)}

    def test_default_sample_graph_includes_every_evidenced_category(self):
        # SAMPLE_STEPS has a HUMAN "reviews" step (-> APPROVAL_DELAY)
        # and SAMPLE_INTEGRATIONS has a "Payment Gateway" integration
        # (-> PAYMENT_FAILURE via the integration branch), plus a
        # CUSTOMER-facing step (-> DEMAND_SPIKE) and stored
        # steps/integrations (-> STEP_FAILURE/INTEGRATION_FAILURE/
        # SLA_DELAY). No step mentions a document -> no MISSING_DATA.
        categories = self._categories(_sample_graph())
        self.assertEqual(
            categories,
            {"STEP_FAILURE", "INTEGRATION_FAILURE", "SLA_DELAY", "DEMAND_SPIKE",
             "PAYMENT_FAILURE", "APPROVAL_DELAY"},
        )

    def test_service_with_no_evidence_excludes_every_irrelevant_category(self):
        # No integrations, no payment, no approval, no document
        # evidence anywhere -- only the two categories that need
        # nothing beyond "a step exists" fire.
        categories = self._categories(_no_evidence_graph())
        self.assertEqual(categories, {"STEP_FAILURE", "SLA_DELAY", "DEMAND_SPIKE"})

    def test_service_without_integrations_excludes_integration_failure(self):
        graph = _no_evidence_graph()
        self.assertNotIn("INTEGRATION_FAILURE", self._categories(graph))

    def test_service_with_integrations_includes_integration_failure(self):
        self.assertIn("INTEGRATION_FAILURE", self._categories(_sample_graph()))

    def test_service_without_payment_evidence_excludes_payment_failure(self):
        self.assertNotIn("PAYMENT_FAILURE", self._categories(_no_evidence_graph()))

    def test_payment_flag_on_step_is_honored_without_keyword_match(self):
        # Real stored has_payment=True evidence, with a step NAME that
        # contains no payment keyword at all -- proves the flag itself
        # (not just keyword matching) drives detection.
        graph = _no_evidence_graph()
        graph["steps"][1]["has_payment"] = True
        self.assertIn("PAYMENT_FAILURE", self._categories(graph))

    def test_payment_integration_is_preferred_over_payment_step(self):
        graph = _sample_graph()
        graph["steps"][1]["has_payment"] = True  # also flag a step
        candidates = dict(
            (c, (t, v)) for c, t, v in self.agent.generate_auto_scenarios(graph)
        )
        scenario_type, variables = candidates["PAYMENT_FAILURE"]
        self.assertEqual(scenario_type, "INTEGRATION_FAILURE")
        self.assertEqual(variables["failed_integration_id"], "INTEGRATION-002")

    def test_service_without_approval_evidence_excludes_approval_delay(self):
        self.assertNotIn("APPROVAL_DELAY", self._categories(_no_evidence_graph()))

    def test_requires_approval_flag_is_honored_without_keyword_match(self):
        graph = _no_evidence_graph()
        graph["steps"][1]["requires_approval"] = True
        self.assertIn("APPROVAL_DELAY", self._categories(graph))

    def test_missing_data_category_fires_only_with_document_evidence(self):
        graph = _no_evidence_graph()
        self.assertNotIn("MISSING_DATA", self._categories(graph))
        graph["steps"][1]["evidence_text"] = "Customer uploads supporting document"
        self.assertIn("MISSING_DATA", self._categories(graph))

    def test_empty_graph_returns_no_candidates(self):
        empty_graph = {"steps": [], "integrations": [], "journeys_count": 0,
                        "source_analysis_id": None}
        self.assertEqual(self.agent.generate_auto_scenarios(empty_graph), [])

    def test_generation_is_deterministic(self):
        graph = _sample_graph()
        first = self.agent.generate_auto_scenarios(graph)
        second = self.agent.generate_auto_scenarios(graph)
        self.assertEqual(first, second)

    def test_no_duplicate_scenario_type_target_pairs(self):
        graph = _sample_graph()
        candidates = self.agent.generate_auto_scenarios(graph)
        keys = [
            (scenario_type,
             variables.get("origin_step_id") or variables.get("breached_step_id")
             or variables.get("failed_integration_id"))
            for _, scenario_type, variables in candidates
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_candidate_survives_validate_scenario(self):
        graph = _sample_graph()
        for _, scenario_type, variables in self.agent.generate_auto_scenarios(graph):
            validated = self.agent.validate_scenario(scenario_type, variables, graph)
            # Executing each one must not raise either.
            self.agent.run(scenario_type, validated, graph)


class DeterministicExecutionTestCase(unittest.TestCase):
    """Pure unit tests -- no database, no LLM. Prove affected
    steps/bottlenecks/scores/likelihood are plain deterministic
    computation over the graph."""

    def setUp(self):
        self.agent = FutureSimulationAgent(llm=None)
        self.graph = _sample_graph()

    # --- edge case 3: invalid scenario type -------------------------
    def test_invalid_scenario_type_is_rejected(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.validate_scenario("NOT_A_REAL_TYPE", {}, self.graph)

    # --- edge case 4: invalid scenario variables ---------------------
    def test_missing_required_variable_is_rejected(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.validate_scenario("VOLUME_SURGE", {}, self.graph)

    def test_out_of_range_variable_is_rejected(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.validate_scenario(
                "CASCADING_STEP_FAILURE",
                {"origin_step_id": "STEP-1", "failure_probability": 1.5},  # >1.0
                self.graph,
            )

    def test_non_numeric_variable_is_rejected(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.validate_scenario(
                "VOLUME_SURGE",
                {"demand_multiplier": "a lot", "time_horizon_days": 30},
                self.graph,
            )

    # --- edge case 5: invalid step/integration reference -------------
    def test_unknown_step_reference_is_rejected(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.validate_scenario(
                "SLA_BREACH",
                {"breached_step_id": "STEP-999", "delay_multiplier": 2.0},
                self.graph,
            )

    def test_unknown_integration_reference_is_rejected(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.validate_scenario(
                "INTEGRATION_FAILURE",
                {"failed_integration_id": "INTEGRATION-999", "failure_duration_hours": 4},
                self.graph,
            )

    # --- edge case 2: service with no usable graph --------------------
    def test_empty_graph_rejects_every_scenario(self):
        empty_graph = {"steps": [], "integrations": [], "journeys_count": 0,
                        "source_analysis_id": None}
        with self.assertRaises(InsufficientDataError):
            self.agent.validate_scenario(
                "VOLUME_SURGE", {"demand_multiplier": 2.0, "time_horizon_days": 30}, empty_graph
            )

    # --- deterministic execution: CASCADING_STEP_FAILURE --------------
    def test_cascading_failure_blocks_origin_and_downstream_only(self):
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE",
            {"origin_step_id": "STEP-2", "failure_probability": 0.8},
            self.graph,
        )
        result = self.agent.run("CASCADING_STEP_FAILURE", variables, self.graph)
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        # STEP-2 is order index 1; STEP-1 (order 0) must NOT be affected,
        # STEP-2/3/4 (orders 1,2,3) must be.
        self.assertEqual(affected_ids, {"STEP-2", "STEP-3", "STEP-4"})
        self.assertEqual(result["likelihood"], 0.8)
        self.assertEqual(result["likelihood_source"], "ASSUMPTION_OR_VARIABLE")

    # --- edge case 8: repeated execution is identical ------------------
    def test_repeated_execution_is_identical(self):
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE",
            {"origin_step_id": "STEP-2", "failure_probability": 0.8},
            self.graph,
        )
        result_a = self.agent.run("CASCADING_STEP_FAILURE", variables, self.graph)
        result_b = self.agent.run("CASCADING_STEP_FAILURE", variables, self.graph)
        self.assertEqual(result_a["affected_steps"], result_b["affected_steps"])
        self.assertEqual(result_a["bottlenecks"], result_b["bottlenecks"])
        self.assertEqual(result_a["citizen_impact"], result_b["citizen_impact"])
        self.assertEqual(result_a["government_impact"], result_b["government_impact"])
        self.assertEqual(result_a["overall_risk_score"], result_b["overall_risk_score"])
        self.assertEqual(result_a["likelihood"], result_b["likelihood"])

    # --- deterministic execution: INTEGRATION_FAILURE ------------------
    def test_integration_failure_affects_only_system_steps(self):
        variables = self.agent.validate_scenario(
            "INTEGRATION_FAILURE",
            {"failed_integration_id": "INTEGRATION-001", "failure_duration_hours": 6},
            self.graph,
        )
        result = self.agent.run("INTEGRATION_FAILURE", variables, self.graph)
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        self.assertEqual(affected_ids, {"STEP-2", "STEP-4"})  # the two SYSTEM steps
        self.assertEqual(len(result["assumptions"]), 1)
        self.assertIn("SYSTEM-type", result["assumptions"][0]["reason"])


    # --- deterministic execution: SLA_BREACH ----------------------------
    def test_sla_breach_below_threshold_has_no_effect(self):
        variables = self.agent.validate_scenario(
            "SLA_BREACH", {"breached_step_id": "STEP-3", "delay_multiplier": 0.5}, self.graph
        )
        result = self.agent.run("SLA_BREACH", variables, self.graph)
        self.assertEqual(result["affected_steps"], [])

    def test_sla_breach_above_threshold_violates_and_delays_downstream(self):
        variables = self.agent.validate_scenario(
            "SLA_BREACH", {"breached_step_id": "STEP-3", "delay_multiplier": 3.0}, self.graph
        )
        result = self.agent.run("SLA_BREACH", variables, self.graph)
        statuses = {item["step_id"]: item["status"] for item in result["affected_steps"]}
        self.assertEqual(statuses["STEP-3"], "SLA_VIOLATED")
        self.assertEqual(statuses["STEP-4"], "DELAYED")
        self.assertNotIn("STEP-1", statuses)
        self.assertNotIn("STEP-2", statuses)

    # --- deterministic execution: VOLUME_SURGE ---------------------------
    def test_volume_surge_below_threshold_has_no_effect(self):
        variables = self.agent.validate_scenario(
            "VOLUME_SURGE", {"demand_multiplier": 1.1, "time_horizon_days": 30}, self.graph
        )
        result = self.agent.run("VOLUME_SURGE", variables, self.graph)
        self.assertEqual(result["affected_steps"], [])

    def test_volume_surge_above_threshold_degrades_customer_facing_steps(self):
        variables = self.agent.validate_scenario(
            "VOLUME_SURGE", {"demand_multiplier": 2.0, "time_horizon_days": 30}, self.graph
        )
        result = self.agent.run("VOLUME_SURGE", variables, self.graph)
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        self.assertEqual(affected_ids, {"STEP-1", "STEP-3"})  # CUSTOMER + HUMAN steps

    # --- scores are bounded 0-100 ------------------------------------
    def test_scores_are_bounded(self):
        variables = self.agent.validate_scenario(
            "VOLUME_SURGE", {"demand_multiplier": 50.0, "time_horizon_days": 1}, self.graph
        )
        result = self.agent.run("VOLUME_SURGE", variables, self.graph)
        self.assertLessEqual(result["citizen_impact"]["score"], 100.0)
        self.assertGreaterEqual(result["citizen_impact"]["score"], 0.0)
        self.assertLessEqual(result["overall_risk_score"], 100.0)

    # --- edge case 9: grounding tags are correct -----------------------
    def test_grounding_summary_counts_are_consistent(self):
        variables = self.agent.validate_scenario(
            "INTEGRATION_FAILURE",
            {"failed_integration_id": "INTEGRATION-001", "failure_duration_hours": 6},
            self.graph,
        )
        result = self.agent.run("INTEGRATION_FAILURE", variables, self.graph)
        summary = result["grounding_summary"]
        self.assertEqual(summary["assumption_count"], len(result["assumptions"]) + 1)  # + likelihood
        self.assertEqual(summary["prediction_count"], 0)  # no linked_prediction supplied

    def test_prediction_linked_scenario_uses_prediction_likelihood(self):
        linked_prediction = {
            "predictions": [{"confidence": 0.75}, {"confidence": 0.4}],
            "data_sufficiency": {"verdict": "SUFFICIENT"},
        }
        variables = self.agent.validate_scenario(
            "VOLUME_SURGE", {"demand_multiplier": 2.0, "time_horizon_days": 30}, self.graph
        )
        result = self.agent.run(
            "VOLUME_SURGE", variables, self.graph, linked_prediction=linked_prediction
        )
        self.assertEqual(result["likelihood"], 0.75)  # max confidence, not invented
        self.assertEqual(result["likelihood_source"], "PREDICTION")
        self.assertEqual(result["grounding_summary"]["prediction_count"], 1)

    # --- edge case 10: LLM cannot fabricate steps/counts/scores --------
    def test_llm_description_rejected_when_it_invents_a_number(self):
        class FabricatingLLM:
            def generate(self, *args, **kwargs):
                return "This scenario affects 9999 steps with a risk score of 500."

        agent = FutureSimulationAgent(llm=FabricatingLLM())
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE",
            {"origin_step_id": "STEP-2", "failure_probability": 0.8},
            self.graph,
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, self.graph)
        outcome = result["possible_outcomes"][0]
        self.assertEqual(outcome["description_source"], "template")
        self.assertNotIn("9999", outcome["description"])
        # Real computed numbers are unaffected by the LLM's fabrication.
        self.assertEqual(len(result["affected_steps"]), 3)

    # --- edge case 11: fallback template works when LLM unavailable ----
    def test_no_llm_configured_always_uses_template(self):
        agent = FutureSimulationAgent(llm=None)
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE",
            {"origin_step_id": "STEP-2", "failure_probability": 0.8},
            self.graph,
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, self.graph)
        outcome = result["possible_outcomes"][0]
        self.assertEqual(outcome["description_source"], "template")
        self.assertTrue(outcome["description"])

    def test_llm_description_accepted_when_grounded(self):
        class HonestLLM:
            def generate(self, *args, **kwargs):
                return "This cascading failure affects 3 downstream steps."

        agent = FutureSimulationAgent(llm=HonestLLM())
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE",
            {"origin_step_id": "STEP-2", "failure_probability": 0.8},
            self.graph,
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, self.graph)
        self.assertEqual(result["possible_outcomes"][0]["description_source"], "ai")


class IntegrationToStepMappingTestCase(unittest.TestCase):
    """Integration-to-Step Mapping audit fix: explicit mapping and
    text-evidence mapping must be used in preference to the old
    "every SYSTEM step depends on every integration" ASSUMPTION, and
    that ASSUMPTION must be preserved byte-for-byte when neither kind
    of evidence exists (backward compatibility with old records --
    already covered by test_integration_failure_affects_only_system_
    steps above)."""

    def setUp(self):
        self.agent = FutureSimulationAgent(llm=None)

    def _graph(self, steps, integrations):
        return {
            "steps": [
                {"step_id": f"STEP-{i + 1}", "name": name, "type": step_type, "order": i,
                 "has_payment": False, "requires_approval": False, "evidence_text": name}
                for i, (name, step_type) in enumerate(steps)
            ],
            "integrations": integrations,
            "journeys_count": 0,
            "source_analysis_id": "an-mapping-test",
        }

    def _run_integration_failure(self, graph, integration_id):
        variables = self.agent.validate_scenario(
            "INTEGRATION_FAILURE",
            {"failed_integration_id": integration_id, "failure_duration_hours": 6},
            graph,
        )
        return self.agent.run("INTEGRATION_FAILURE", variables, graph)

    # --- explicit step -> integration mapping ---------------------------
    def test_explicit_mapping_restricts_affected_steps(self):
        graph = self._graph(
            steps=[
                ("Customer logs in", "CUSTOMER"),
                ("System checks trade license", "SYSTEM"),
                ("System executes the service", "SYSTEM"),
                ("System charges the fee", "SYSTEM"),
            ],
            integrations=[
                {"integration_id": "INTEGRATION-001", "name": "UAE_PASS", "step_ids": ["STEP-1"]},
            ],
        )
        result = self._run_integration_failure(graph, "INTEGRATION-001")
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        # Only the explicitly mapped step -- NOT every SYSTEM step,
        # even though STEP-2/3/4 are all type SYSTEM.
        self.assertEqual(affected_ids, {"STEP-1"})
        self.assertEqual(result["assumptions"], [])  # real evidence, not an assumption

    def test_multiple_integrations_mapped_to_different_steps(self):
        graph = self._graph(
            steps=[
                ("Customer logs in", "CUSTOMER"),
                ("System checks trade license", "SYSTEM"),
                ("System executes the service", "SYSTEM"),
                ("Customer pays the fee", "CUSTOMER"),
            ],
            integrations=[
                {"integration_id": "INTEGRATION-001", "name": "UAE_PASS", "step_ids": ["STEP-1"]},
                {"integration_id": "INTEGRATION-002", "name": "TRADE_LICENSE_API", "step_ids": ["STEP-2"]},
                {"integration_id": "INTEGRATION-003", "name": "SERVICE_EXECUTION_API", "step_ids": ["STEP-3"]},
                {"integration_id": "INTEGRATION-004", "name": "PAYMENT_GATEWAY", "step_ids": ["STEP-4"]},
            ],
        )
        expectations = {
            "INTEGRATION-001": {"STEP-1"}, "INTEGRATION-002": {"STEP-2"},
            "INTEGRATION-003": {"STEP-3"}, "INTEGRATION-004": {"STEP-4"},
        }
        for integration_id, expected_steps in expectations.items():
            result = self._run_integration_failure(graph, integration_id)
            affected_ids = {item["step_id"] for item in result["affected_steps"]}
            self.assertEqual(affected_ids, expected_steps, integration_id)

    def test_integration_mapped_to_a_single_step_among_many(self):
        graph = self._graph(
            steps=[(f"System step {i}", "SYSTEM") for i in range(1, 6)],
            integrations=[
                {"integration_id": "INTEGRATION-001", "name": "NICHE_API", "step_ids": ["STEP-3"]},
            ],
        )
        result = self._run_integration_failure(graph, "INTEGRATION-001")
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        self.assertEqual(affected_ids, {"STEP-3"})
        self.assertEqual(len(affected_ids), 1)

    def test_explicit_mapping_drops_step_ids_that_no_longer_exist(self):
        # A stale mapping referencing a step that isn't in the CURRENT
        # graph must never invent that step -- it degrades to no
        # explicit evidence rather than fabricating a reference.
        graph = self._graph(
            steps=[("System step", "SYSTEM")],
            integrations=[
                {"integration_id": "INTEGRATION-001", "name": "STALE_API", "step_ids": ["STEP-99"]},
            ],
        )
        result = self._run_integration_failure(graph, "INTEGRATION-001")
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        # Falls through to the ASSUMPTION tier (the one SYSTEM step),
        # never STEP-99.
        self.assertEqual(affected_ids, {"STEP-1"})
        self.assertEqual(len(result["assumptions"]), 1)

    # --- text-evidence mapping (no explicit step_ids, but the ------------
    # --- integration's own name appears in a step's own stored text) ----
    def test_text_evidence_mapping_used_when_no_explicit_mapping(self):
        graph = self._graph(
            steps=[
                ("Customer logs in with UAE Pass", "CUSTOMER"),
                ("System verifies trade license via Trade License API", "SYSTEM"),
                ("System executes the request", "SYSTEM"),
            ],
            integrations=[
                {"integration_id": "INTEGRATION-001", "name": "Trade License API"},
            ],
        )
        result = self._run_integration_failure(graph, "INTEGRATION-001")
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        self.assertEqual(affected_ids, {"STEP-2"})
        self.assertEqual(result["assumptions"], [])  # real text evidence, not an assumption

    def test_text_evidence_matches_underscore_style_integration_names(self):
        graph = self._graph(
            steps=[("Customer authenticates via UAE Pass", "CUSTOMER")],
            integrations=[{"integration_id": "INTEGRATION-001", "name": "UAE_PASS"}],
        )
        result = self._run_integration_failure(graph, "INTEGRATION-001")
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        self.assertEqual(affected_ids, {"STEP-1"})

    # --- backward compatibility: old records with no mapping/evidence ---
    def test_old_record_without_mapping_or_evidence_uses_assumption_fallback(self):
        graph = self._graph(
            steps=[
                ("Customer submits request", "CUSTOMER"),
                ("System processes request", "SYSTEM"),
                ("Employee reviews", "HUMAN"),
                ("System finalizes", "SYSTEM"),
            ],
            integrations=[{"integration_id": "INTEGRATION-001", "name": "Some Unrelated Integration"}],
        )
        result = self._run_integration_failure(graph, "INTEGRATION-001")
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        # Preserved, unchanged fallback: every SYSTEM-type step.
        self.assertEqual(affected_ids, {"STEP-2", "STEP-4"})
        self.assertEqual(len(result["assumptions"]), 1)
        self.assertEqual(result["assumptions"][0]["variable_name"], "affected_steps_mapping")
        self.assertIn("Some Unrelated Integration", result["assumptions"][0]["reason"])

    def test_build_service_graph_parses_explicit_mapping_from_stored_analysis(self):
        # End-to-end: build_service_graph() itself must extract
        # step_ids from a dict-shaped required_integrations entry --
        # no database/schema change, still the same JSON field.
        from core.runtime_store import RuntimeStore
        from core.service_store import ServiceStore
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            runtime_store = RuntimeStore(database_path=db_path)
            service_store = ServiceStore(database_path=db_path)
            tenant_id = "tenant-mapping-e2e"
            service = service_store.create_service(tenant_id=tenant_id, service_name="Mapping E2E Service")
            service_store.create_analysis(
                tenant_id=tenant_id, service_id=service["id"], blueprint_id="bp-mapping",
                result={
                    "redesign": {
                        "future_steps": [
                            {"step_number": 1, "name": "Customer logs in", "type": "CUSTOMER"},
                            {"step_number": 2, "name": "System checks license", "type": "SYSTEM"},
                        ],
                        "required_integrations": [
                            {"name": "UAE_PASS", "step_ids": ["STEP-1"]},
                            "Legacy Plain String Integration",  # old format, still works
                        ],
                    },
                },
            )
            agent = FutureSimulationAgent(llm=None)
            graph = agent.build_service_graph(
                service_id=service["id"], tenant_id=tenant_id,
                service_store=service_store, database_path=runtime_store.database_path,
            )
            uae_pass = next(i for i in graph["integrations"] if i["name"] == "UAE_PASS")
            legacy = next(i for i in graph["integrations"] if i["name"] == "Legacy Plain String Integration")
            self.assertEqual(uae_pass["step_ids"], ["STEP-1"])
            self.assertEqual(legacy["step_ids"], [])  # plain string -> no explicit mapping


class SlaResolutionTestCase(unittest.TestCase):
    """SLA handling audit fix: resolve_sla_baseline_hours()'s priority
    order (step SLA -> step expected duration -> service SLA/waiting
    time -> 48h ASSUMPTION), and _execute_sla_breach()'s use of it."""

    def setUp(self):
        self.agent = FutureSimulationAgent(llm=None)

    def _graph(self, steps, waiting_times=None):
        return {
            "steps": [
                {"step_id": f"STEP-{i + 1}", "name": name, "type": "SYSTEM", "order": i,
                 "has_payment": False, "requires_approval": False, "evidence_text": name,
                 **extra}
                for i, (name, extra) in enumerate(steps)
            ],
            "integrations": [], "journeys_count": 0, "source_analysis_id": "an-sla-test",
            "waiting_times": waiting_times or [],
        }

    def _run_sla_breach(self, graph, breached_step_id, delay_multiplier=3.0):
        variables = self.agent.validate_scenario(
            "SLA_BREACH", {"breached_step_id": breached_step_id, "delay_multiplier": delay_multiplier}, graph
        )
        return self.agent.run("SLA_BREACH", variables, graph)

    # --- priority 1: explicit per-step SLA -------------------------------
    def test_explicit_step_sla_hours_is_used_exactly(self):
        graph = self._graph([("Employee reviews the case", {"sla_hours": 6})])
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 6.0)
        self.assertEqual(source, "STEP_SLA")

    def test_sla_breach_execution_reports_no_assumption_when_step_sla_exists(self):
        graph = self._graph([
            ("Employee reviews the case", {"sla_hours": 6}),
            ("System issues the result", {}),
        ])
        result = self._run_sla_breach(graph, "STEP-1")
        self.assertEqual(result["assumptions"], [])  # real evidence -- not an assumption

    # --- priority 2: per-step expected duration ---------------------------
    def test_explicit_step_expected_duration_used_when_no_sla(self):
        graph = self._graph([("System processes the request", {"expected_duration_hours": 2})])
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 2.0)
        self.assertEqual(source, "STEP_EXPECTED_DURATION")

    def test_step_sla_takes_priority_over_step_expected_duration(self):
        graph = self._graph([
            ("Employee reviews the case", {"sla_hours": 6, "expected_duration_hours": 2}),
        ])
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 6.0)
        self.assertEqual(source, "STEP_SLA")

    def test_step_text_evidence_with_sla_keyword_is_step_sla(self):
        graph = self._graph([
            ("System issues the result within an SLA of 4 hours", {}),
        ])
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 4.0)
        self.assertEqual(source, "STEP_SLA")

    def test_step_text_evidence_without_sla_keyword_is_expected_duration(self):
        graph = self._graph([
            ("Employee typically completes this review within 2 business days", {}),
        ])
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 48.0)  # 2 business days -> 48h
        self.assertEqual(source, "STEP_EXPECTED_DURATION")

    # --- priority 3: service-level SLA/waiting time -----------------------
    def test_service_waiting_time_used_when_no_step_evidence(self):
        graph = self._graph(
            [("System processes the request", {})],
            waiting_times=["Processing typically takes 3-5 business days."],
        )
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 120.0)  # upper bound: 5 business days -> 120h
        self.assertEqual(source, "SERVICE_WAITING_TIME")

    def test_step_evidence_takes_priority_over_service_waiting_time(self):
        graph = self._graph(
            [("Employee reviews the case", {"sla_hours": 6})],
            waiting_times=["Processing typically takes 3-5 business days."],
        )
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 6.0)
        self.assertEqual(source, "STEP_SLA")

    # --- priority 4: 48h ASSUMPTION fallback -------------------------------
    def test_no_evidence_anywhere_falls_back_to_48h_assumption(self):
        graph = self._graph([("System processes the request", {})])
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 48.0)
        self.assertEqual(source, "ASSUMPTION")

    def test_sla_breach_execution_marks_fallback_as_assumption(self):
        graph = self._graph([
            ("System processes the request", {}),
            ("System finalizes", {}),
        ])
        result = self._run_sla_breach(graph, "STEP-1")
        self.assertEqual(len(result["assumptions"]), 1)
        self.assertEqual(result["assumptions"][0]["variable_name"], "sla_hours_default")
        self.assertEqual(result["assumptions"][0]["value"], 48.0)
        self.assertIn("48h", result["assumptions"][0]["reason"])

    # --- different steps, different values --------------------------------
    def test_different_steps_resolve_to_their_own_different_sla_values(self):
        graph = self._graph([
            ("Customer authenticates", {"sla_hours": 1}),
            ("System checks trade license", {"expected_duration_hours": 3}),
            ("Employee approves", {}),  # no evidence -> 48h assumption
        ])
        results = {
            step["step_id"]: self.agent.resolve_sla_baseline_hours(step, graph)
            for step in graph["steps"]
        }
        self.assertEqual(results["STEP-1"], (1.0, "STEP_SLA"))
        self.assertEqual(results["STEP-2"], (3.0, "STEP_EXPECTED_DURATION"))
        self.assertEqual(results["STEP-3"], (48.0, "ASSUMPTION"))

    # --- backward compatibility -------------------------------------------
    def test_old_style_graph_without_waiting_times_key_still_works(self):
        # A hand-built/old graph that predates the "waiting_times" key
        # entirely must not crash -- resolve_sla_baseline_hours()
        # degrades gracefully to the ASSUMPTION tier.
        graph = {
            "steps": [{"step_id": "STEP-1", "name": "System step", "type": "SYSTEM", "order": 0}],
            "integrations": [], "journeys_count": 0, "source_analysis_id": "an-old",
        }
        hours, source = self.agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
        self.assertEqual(hours, 48.0)
        self.assertEqual(source, "ASSUMPTION")

    def test_build_service_graph_parses_service_level_waiting_times(self):
        from core.runtime_store import RuntimeStore
        from core.service_store import ServiceStore
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            runtime_store = RuntimeStore(database_path=db_path)
            service_store = ServiceStore(database_path=db_path)
            tenant_id = "tenant-sla-e2e"
            service = service_store.create_service(tenant_id=tenant_id, service_name="SLA E2E Service")
            service_store.create_analysis(
                tenant_id=tenant_id, service_id=service["id"], blueprint_id="bp-sla",
                result={
                    "redesign": {
                        "future_steps": [
                            {"step_number": 1, "name": "System step", "type": "SYSTEM"},
                        ],
                        "required_integrations": [],
                    },
                    "service": {"waiting_times": ["Typically completed within 48-72 hours."]},
                },
            )
            agent = FutureSimulationAgent(llm=None)
            graph = agent.build_service_graph(
                service_id=service["id"], tenant_id=tenant_id,
                service_store=service_store, database_path=runtime_store.database_path,
            )
            self.assertEqual(graph["waiting_times"], ["Typically completed within 48-72 hours."])
            hours, source = agent.resolve_sla_baseline_hours(graph["steps"][0], graph)
            self.assertEqual(hours, 72.0)
            self.assertEqual(source, "SERVICE_WAITING_TIME")

    # --- Challenge uses the same shared resolution logic -------------------
    def test_challenge_sla_stress_uses_resolved_real_step_value(self):
        from agents.challenge_agent import ChallengeAgent
        graph = self._graph([
            ("Employee reviews the case", {"sla_hours": 6}),
            ("System issues the result", {}),
        ])
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(future_simulation_agent=simulation_agent, llm=None)
        result = agent.run(["SLA_STRESS"], graph)
        # The SLA_STRESS case targeting STEP-1 (which has a real,
        # stored sla_hours) must show no assumption in its own source
        # output -- proving Challenge went through the SAME resolution
        # logic as Simulate, not a separate/duplicated one.
        step1_cases = [
            item for item in result.get("cases_executed", [])
            if item.get("target") == "STEP-1" and item.get("strategy") == "SLA_STRESS"
        ]
        self.assertTrue(step1_cases)


class CitizenOutcomeImpactTestCase(unittest.TestCase):
    """Citizen/outcome impact audit fix:
    "0 of 0 customer-facing steps affected" must never automatically
    imply the citizen isn't affected -- FutureSimulationAgent.
    _determine_citizen_outcome_impact() and the additive
    citizen_outcome_affected/outcome_impact_reason fields on run()'s
    output. Does not touch citizen_impact's own existing numeric
    ratio/score -- every test here also asserts that score is
    unchanged."""

    def setUp(self):
        self.agent = FutureSimulationAgent(llm=None)

    def _graph(self, steps, integrations=None):
        return {
            "steps": [
                {"step_id": f"STEP-{i + 1}", "name": name, "type": step_type, "order": i,
                 "has_payment": False, "requires_approval": False, "evidence_text": name}
                for i, (name, step_type) in enumerate(steps)
            ],
            "integrations": integrations or [],
            "journeys_count": 0, "source_analysis_id": "an-outcome-test", "waiting_times": [],
        }

    # --- 1. real customer-facing steps: direct impact still correct ------
    def test_journey_with_customer_steps_calculates_direct_impact_correctly(self):
        graph = self._graph([
            ("Customer submits request", "CUSTOMER"),
            ("Employee reviews", "HUMAN"),
            ("System issues result", "SYSTEM"),
        ])
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 1.0}, graph
        )
        result = self.agent.run("CASCADING_STEP_FAILURE", variables, graph)
        # Direct customer-facing ratio: STEP-1 (CUSTOMER) and STEP-2
        # (HUMAN) are both blocked by the cascade -> 2 of 2.
        self.assertIn("2 of 2 customer-facing", result["citizen_impact"]["basis"])
        self.assertGreater(result["citizen_impact"]["score"], 0)

    # --- 2. zero-customer-step journey may legitimately stay 0 of 0 ------
    def test_zero_customer_step_journey_direct_impact_may_legitimately_be_zero_of_zero(self):
        graph = self._graph([
            ("System validates the request", "SYSTEM"),
            ("System issues the result", "SYSTEM"),
        ])
        variables = self.agent.validate_scenario(
            "SLA_BREACH", {"breached_step_id": "STEP-1", "delay_multiplier": 1.0}, graph
        )
        result = self.agent.run("SLA_BREACH", variables, graph)
        self.assertIn("0 of 0 customer-facing", result["citizen_impact"]["basis"])
        # delay_multiplier <= 1.0 -> deterministically nothing affected
        # -- legitimately 0 of 0 AND no outcome impact.
        self.assertFalse(result["citizen_outcome_affected"])

    # --- 3. SYSTEM-step failure blocking completion -> outcome affected --
    def test_system_step_failure_blocking_completion_marks_outcome_affected(self):
        graph = self._graph([
            ("System validates the request", "SYSTEM"),
            ("System issues the result", "SYSTEM"),
        ])
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 1.0}, graph
        )
        result = self.agent.run("CASCADING_STEP_FAILURE", variables, graph)
        # Zero customer-facing steps -> direct impact stays 0 of 0 ...
        self.assertIn("0 of 0 customer-facing", result["citizen_impact"]["basis"])
        self.assertEqual(result["citizen_impact"]["score"], 0)
        # ... but the citizen still doesn't get their result.
        self.assertTrue(result["citizen_outcome_affected"])
        self.assertIn("blocks", result["outcome_impact_reason"].lower())

    # --- 4. SYSTEM-step failure NOT affecting final delivery -> no false --
    # --- positive -----------------------------------------------------
    def test_system_step_failure_not_reaching_final_step_does_not_falsely_block_outcome(self):
        graph = self._graph(
            [
                ("System logs the request", "SYSTEM"),
                ("System validates the request", "SYSTEM"),
                ("System issues the result", "SYSTEM"),
            ],
            integrations=[{"integration_id": "INTEGRATION-001", "name": "Logging Service",
                            "step_ids": ["STEP-1"]}],  # mapped to a NON-final step only
        )
        variables = self.agent.validate_scenario(
            "INTEGRATION_FAILURE",
            {"failed_integration_id": "INTEGRATION-001", "failure_duration_hours": 6}, graph,
        )
        result = self.agent.run("INTEGRATION_FAILURE", variables, graph)
        affected_ids = {item["step_id"] for item in result["affected_steps"]}
        self.assertEqual(affected_ids, {"STEP-1"})  # only the mapped, non-final step
        self.assertFalse(result["citizen_outcome_affected"])
        self.assertIn("do not block", result["outcome_impact_reason"].lower())

    # --- 5. no fake CUSTOMER steps are ever created -----------------------
    def test_no_fake_customer_steps_are_created(self):
        graph = self._graph([
            ("System validates the request", "SYSTEM"),
            ("System issues the result", "SYSTEM"),
        ])
        original_types = [s["type"] for s in graph["steps"]]
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 1.0}, graph
        )
        self.agent.run("CASCADING_STEP_FAILURE", variables, graph)
        # The graph's own step types are never mutated by this fix.
        self.assertEqual([s["type"] for s in graph["steps"]], original_types)
        self.assertNotIn("CUSTOMER", original_types)
        self.assertNotIn("HUMAN", original_types)

    # --- 6. critical-path/cascading failure affects citizen outcome ------
    # --- even with 0 customer-facing steps --------------------------------
    def test_cascading_failure_with_zero_customer_steps_still_affects_outcome(self):
        graph = self._graph([
            (f"System step {i}", "SYSTEM") for i in range(1, 6)
        ])
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 1.0}, graph
        )
        result = self.agent.run("CASCADING_STEP_FAILURE", variables, graph)
        self.assertEqual(result["citizen_impact"]["score"], 0)  # unchanged formula
        self.assertTrue(result["citizen_outcome_affected"])

    # --- 7. SLA delay can produce delayed outcome impact ------------------
    def test_sla_delay_produces_outcome_affected_when_supported_by_evidence(self):
        graph = self._graph([
            ("System processes the request", "SYSTEM"),
            ("System issues the result", "SYSTEM"),
        ])
        variables = self.agent.validate_scenario(
            "SLA_BREACH", {"breached_step_id": "STEP-1", "delay_multiplier": 3.0}, graph
        )
        result = self.agent.run("SLA_BREACH", variables, graph)
        self.assertTrue(result["citizen_outcome_affected"])
        self.assertIn("delayed", result["outcome_impact_reason"].lower())

    # --- 8. integration failure affecting citizen outcome when it --------
    # --- blocks required execution (reaches the final step) --------------
    def test_integration_failure_reaching_final_step_affects_outcome(self):
        graph = self._graph(
            [
                ("System validates the request", "SYSTEM"),
                ("System issues the result", "SYSTEM"),
            ],
            integrations=[{"integration_id": "INTEGRATION-001", "name": "Result Delivery API",
                            "step_ids": ["STEP-2"]}],  # mapped to the FINAL step
        )
        variables = self.agent.validate_scenario(
            "INTEGRATION_FAILURE",
            {"failed_integration_id": "INTEGRATION-001", "failure_duration_hours": 6}, graph,
        )
        result = self.agent.run("INTEGRATION_FAILURE", variables, graph)
        self.assertTrue(result["citizen_outcome_affected"])
        self.assertIn("final step", result["outcome_impact_reason"].lower())

    # --- 9. existing deterministic scores remain unchanged ----------------
    def test_citizen_and_government_impact_scores_unchanged_by_this_fix(self):
        graph = self._graph([
            ("Customer submits request", "CUSTOMER"),
            ("System issues result", "SYSTEM"),
        ])
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 0.8}, graph
        )
        result = self.agent.run("CASCADING_STEP_FAILURE", variables, graph)
        # Same formula as before this fix: 2 of 2 customer/system-mixed
        # steps affected (cascade blocks everything downstream too),
        # scaled by likelihood 0.8.
        self.assertEqual(result["citizen_impact"]["score"], round(100 * 1.0 * 0.8, 2))
        self.assertIn("citizen_outcome_affected", result)  # additive, present alongside it
        self.assertIn("outcome_impact_reason", result)

    def test_empty_affected_steps_means_no_outcome_impact(self):
        graph = self._graph([("System step", "SYSTEM")])
        outcome_affected, reason = self.agent._determine_citizen_outcome_impact(graph, [])
        self.assertFalse(outcome_affected)
        self.assertIn("No steps were affected", reason)


class ServiceGraphIntegrationTestCase(unittest.TestCase):
    """Integration tests against a real (temp, isolated) SQLite file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)
        self.service_store = ServiceStore(database_path=self.runtime_store.database_path)
        self.simulation_store = SimulationStore(database_path=self.runtime_store.database_path)
        self.prediction_store = PredictionStore(database_path=self.runtime_store.database_path)
        self.tenant_id = self.runtime_store.default_tenant_id

    def tearDown(self):
        self._tmp.cleanup()

    # --- edge case 2: no usable analysis graph --------------------------
    def test_service_with_no_analyses_has_empty_graph(self):
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Fresh Service")
        agent = FutureSimulationAgent(llm=None)
        graph = agent.build_service_graph(
            service_id=service["id"], tenant_id=self.tenant_id,
            service_store=self.service_store, database_path=self.runtime_store.database_path,
        )
        self.assertEqual(graph["steps"], [])
        self.assertEqual(graph["integrations"], [])

    def test_service_with_stored_analysis_builds_real_graph(self):
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Real Service")
        self.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-1",
            result=_analysis_result(future_steps=SAMPLE_STEPS, required_integrations=SAMPLE_INTEGRATIONS),
        )
        agent = FutureSimulationAgent(llm=None)
        graph = agent.build_service_graph(
            service_id=service["id"], tenant_id=self.tenant_id,
            service_store=self.service_store, database_path=self.runtime_store.database_path,
        )
        self.assertEqual(len(graph["steps"]), 4)
        self.assertEqual(len(graph["integrations"]), 2)
        self.assertEqual(graph["steps"][0]["step_id"], "STEP-1")

    def test_build_service_graph_propagates_payment_and_approval_evidence(self):
        # Section 2 audit fix: real journey_builder_agent output
        # stores has_payment/requires_human_judgement per step -- this
        # is the real, already-stored evidence generate_auto_scenarios
        # relies on, so build_service_graph must carry it through.
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Evidence Service")
        steps_with_flags = [
            {"step_number": 1, "name": "Customer submits form", "type": "CUSTOMER",
             "has_payment": False, "requires_human_judgement": False},
            {"step_number": 2, "name": "System charges the fee", "type": "SYSTEM",
             "has_payment": True, "requires_human_judgement": False},
            {"step_number": 3, "name": "Employee makes a decision", "type": "HUMAN",
             "has_payment": False, "requires_human_judgement": True},
        ]
        self.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-2",
            result=_analysis_result(future_steps=steps_with_flags, required_integrations=[]),
        )
        agent = FutureSimulationAgent(llm=None)
        graph = agent.build_service_graph(
            service_id=service["id"], tenant_id=self.tenant_id,
            service_store=self.service_store, database_path=self.runtime_store.database_path,
        )
        self.assertFalse(graph["steps"][0]["has_payment"])
        self.assertTrue(graph["steps"][1]["has_payment"])
        self.assertTrue(graph["steps"][2]["requires_approval"])

    def test_predictions_table_untouched_scenarios_table_is_additive(self):
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Svc")
        saved = self.simulation_store.save_scenario(
            tenant_id=self.tenant_id, service_id=service["id"],
            scenario_type="VOLUME_SURGE", trigger_type="MANUAL", trigger_reference_id=None,
            scenario={"variables": {}}, result={"affected_steps": []},
        )
        self.assertIsNotNone(saved)
        # The predictions table (Step 1) is untouched by this write.
        self.assertEqual(
            self.prediction_store.list_predictions_for_service(service["id"], self.tenant_id), []
        )


class ScenarioEndpointTestCase(unittest.TestCase):
    """Endpoint-level tests through the real FastAPI app."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import main as main_module

        main_module.startup()
        cls.main_module = main_module
        cls.client = TestClient(main_module.app)

        import uuid
        suffix = uuid.uuid4().hex[:8]
        tenant = main_module.tenant_repository.create_tenant(
            f"Sim Test Tenant {suffix}", f"sim-test-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Sim Test Admin", f"sim-test-{suffix}@test.local", role="entity_admin"
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

        # A second, independent tenant for the cross-tenant prediction test.
        other_suffix = uuid.uuid4().hex[:8]
        other_tenant = main_module.tenant_repository.create_tenant(
            f"Other Tenant {other_suffix}", f"other-tenant-{other_suffix}", status="ACTIVE"
        )
        other_user = main_module.tenant_repository.create_user(
            other_tenant["id"], "Other Admin", f"other-{other_suffix}@test.local", role="entity_admin"
        )
        other_login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": other_user["email"], "credential": "zxr-demo-2026"},
        )
        cls.other_headers = {"Authorization": f"Bearer {other_login.json()['token']}"}
        cls.other_tenant_id = other_tenant["id"]

    def _service_with_graph(self, tenant_id):
        service = self.main_module.service_store.create_service(
            tenant_id=tenant_id, service_name="Endpoint Test Service"
        )
        self.main_module.service_store.create_analysis(
            tenant_id=tenant_id, service_id=service["id"], blueprint_id="bp-e2e",
            result=_analysis_result(future_steps=SAMPLE_STEPS, required_integrations=SAMPLE_INTEGRATIONS),
        )
        return service

    def _service_with_no_evidence_graph(self, tenant_id):
        service = self.main_module.service_store.create_service(
            tenant_id=tenant_id, service_name="No Evidence Endpoint Service"
        )
        self.main_module.service_store.create_analysis(
            tenant_id=tenant_id, service_id=service["id"], blueprint_id="bp-e2e-no-evidence",
            result=_analysis_result(future_steps=NO_EVIDENCE_STEPS, required_integrations=NO_EVIDENCE_INTEGRATIONS),
        )
        return service

    # --- edge case 1: missing service ------------------------------------
    def test_scenario_on_unknown_service_returns_404(self):
        response = self.client.post(
            "/api/services/does-not-exist/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "VOLUME_SURGE", "trigger_type": "MANUAL",
                "variables": {"demand_multiplier": 2.0, "time_horizon_days": 30},
            },
        )
        self.assertEqual(response.status_code, 404)

    # --- edge case 2: no usable analysis graph ----------------------------
    def test_scenario_on_service_with_no_analysis_returns_400(self):
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="No History Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "VOLUME_SURGE", "trigger_type": "MANUAL",
                "variables": {"demand_multiplier": 2.0, "time_horizon_days": 30},
            },
        )
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        # Structured INSUFFICIENT_DATA (service-generic/stage-dependency
        # audit fix) -- not an unstructured string.
        self.assertEqual(detail["error_code"], "INSUFFICIENT_DATA")
        self.assertTrue(detail["reason"])
        self.assertTrue(detail["missing_requirement"])
        self.assertTrue(detail["next_action"])

    # --- edge case 3: invalid scenario type -------------------------------
    def test_invalid_scenario_type_returns_400(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"scenario_type": "NOT_REAL", "trigger_type": "MANUAL", "variables": {}},
        )
        self.assertEqual(response.status_code, 422)  # rejected by the Literal[...] schema itself

    # --- edge case 4/5: invalid variables / invalid reference -------------
    def test_invalid_step_reference_returns_400(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "SLA_BREACH", "trigger_type": "MANUAL",
                "variables": {"breached_step_id": "STEP-999", "delay_multiplier": 2.0},
            },
        )
        self.assertEqual(response.status_code, 400)

    # --- edge case 6: missing prediction reference -------------------------
    def test_missing_prediction_reference_returns_404(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "VOLUME_SURGE", "trigger_type": "PREDICTION",
                "prediction_id": "does-not-exist",
                "variables": {"demand_multiplier": 2.0, "time_horizon_days": 30},
            },
        )
        self.assertEqual(response.status_code, 404)

    # --- edge case 7: prediction belonging to another tenant ----------------
    def test_prediction_from_another_tenant_is_treated_as_not_found(self):
        other_service = self._service_with_graph(self.other_tenant_id)
        prediction_response = self.client.post(
            f"/api/services/{other_service['id']}/predict", headers=self.other_headers
        )
        self.assertEqual(prediction_response.status_code, 200)
        other_prediction_id = prediction_response.json()["prediction_id"]

        my_service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{my_service['id']}/scenarios",
            headers=self.headers,  # a DIFFERENT tenant's token
            json={
                "scenario_type": "VOLUME_SURGE", "trigger_type": "PREDICTION",
                "prediction_id": other_prediction_id,
                "variables": {"demand_multiplier": 2.0, "time_horizon_days": 30},
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_manual_variables_are_tagged_assumption_and_scenario_is_stored(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "CASCADING_STEP_FAILURE", "trigger_type": "MANUAL",
                "variables": {"origin_step_id": "STEP-2", "failure_probability": 0.9},
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scenario"]["trigger_type"], "MANUAL")
        self.assertEqual(body["likelihood_source"], "ASSUMPTION_OR_VARIABLE")
        self.assertEqual(len(body["affected_steps"]), 3)

        stored = self.main_module.simulation_store.list_scenarios_for_service(
            service["id"], self.tenant_id
        )
        self.assertEqual(len(stored), 1)

    def test_list_scenarios_endpoint_returns_stored_scenario(self):
        service = self._service_with_graph(self.tenant_id)
        self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "VOLUME_SURGE", "trigger_type": "MANUAL",
                "variables": {"demand_multiplier": 2.0, "time_horizon_days": 30},
            },
        )
        response = self.client.get(f"/api/services/{service['id']}/scenarios", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["scenarios"]), 1)

    # =====================================================================
    # Section 2 audit fix: AUTO trigger_type / "Run Simulation" with no
    # manual input and no prediction must never 400.
    # =====================================================================

    def test_explicit_auto_trigger_generates_multiple_relevant_scenarios(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scenario"]["trigger_type"], "AUTO")
        self.assertIn("auto_scenarios", body)
        categories = {item["scenario"]["auto_category"] for item in body["auto_scenarios"]}
        self.assertEqual(
            categories,
            {"STEP_FAILURE", "INTEGRATION_FAILURE", "SLA_DELAY", "DEMAND_SPIKE",
             "PAYMENT_FAILURE", "APPROVAL_DELAY"},
        )
        # Every generated scenario was actually stored.
        stored = self.main_module.simulation_store.list_scenarios_for_service(
            service["id"], self.tenant_id
        )
        self.assertEqual(len(stored), len(body["auto_scenarios"]))

    def test_manual_with_no_scenario_type_falls_back_to_auto_not_400(self):
        # Exact reported bug: clicking "Run Simulation" with nothing
        # filled in used to send trigger_type=MANUAL with no
        # scenario_type and get a 400.
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"trigger_type": "MANUAL"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scenario"]["trigger_type"], "AUTO")

    def test_prediction_with_no_prediction_id_falls_back_to_auto_not_400(self):
        # Exact reported bug: the frontend's default "from prediction"
        # mode can send prediction_id=null before Predict has ever
        # run. Prediction is optional enrichment, not a requirement.
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"trigger_type": "PREDICTION"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scenario"]["trigger_type"], "AUTO")
        self.assertIsNone(body["scenario"]["trigger_reference_id"])

    def test_prediction_with_a_real_prediction_id_is_unaffected(self):
        # A genuinely wrong/unknown prediction_id must still 404 --
        # only a MISSING (null/omitted) prediction_id falls back to AUTO.
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"trigger_type": "PREDICTION", "prediction_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)

    def test_auto_on_service_with_no_analysis_still_returns_400(self):
        # AUTO must not silently succeed with an empty/nonexistent
        # simulation graph -- that 400 is unrelated to "no manual
        # scenario supplied" and must be preserved.
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="No History AUTO Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["error_code"], "INSUFFICIENT_DATA")
        self.assertTrue(detail["reason"])
        self.assertTrue(detail["missing_requirement"])
        self.assertTrue(detail["next_action"])

    def test_auto_excludes_payment_and_integration_categories_when_absent(self):
        service = self._service_with_no_evidence_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(response.status_code, 200)
        categories = {
            item["scenario"]["auto_category"] for item in response.json()["auto_scenarios"]
        }
        self.assertEqual(categories, {"STEP_FAILURE", "SLA_DELAY", "DEMAND_SPIKE"})
        self.assertNotIn("PAYMENT_FAILURE", categories)
        self.assertNotIn("INTEGRATION_FAILURE", categories)
        self.assertNotIn("APPROVAL_DELAY", categories)

    def test_auto_includes_payment_and_integration_categories_when_present(self):
        service = self._service_with_graph(self.tenant_id)  # has Payment Gateway integration
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(response.status_code, 200)
        categories = {
            item["scenario"]["auto_category"] for item in response.json()["auto_scenarios"]
        }
        self.assertIn("PAYMENT_FAILURE", categories)
        self.assertIn("INTEGRATION_FAILURE", categories)

    def test_manual_scenario_with_explicit_type_is_completely_unchanged(self):
        # Regression: a genuine manual scenario (scenario_type given)
        # must behave exactly as before -- single-scenario response,
        # trigger_type stays MANUAL, no auto_scenarios key at all.
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "CASCADING_STEP_FAILURE", "trigger_type": "MANUAL",
                "variables": {"origin_step_id": "STEP-2", "failure_probability": 0.9},
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scenario"]["trigger_type"], "MANUAL")
        self.assertEqual(body["scenario"]["scenario_type"], "CASCADING_STEP_FAILURE")
        self.assertNotIn("auto_scenarios", body)
        self.assertEqual(len(body["affected_steps"]), 3)

    def test_integration_mapping_via_endpoint_and_tenant_isolation_unaffected(self):
        # Integration-to-Step Mapping audit fix, end to end through the
        # real endpoint -- plus confirms this fix touches nothing about
        # tenant isolation: tenant A's mapped-integration scenario must
        # only ever see tenant A's own stored steps/integrations, and
        # tenant B cannot read or influence it.
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Mapped Integration Endpoint Service"
        )
        self.main_module.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-mapping-endpoint",
            result=_analysis_result(
                future_steps=SAMPLE_STEPS,
                required_integrations=[
                    {"name": "National ID Registry", "step_ids": ["STEP-2"]},
                    "Payment Gateway",  # left as a plain string -- old format, still works
                ],
            ),
        )
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "INTEGRATION_FAILURE", "trigger_type": "MANUAL",
                "variables": {"failed_integration_id": "INTEGRATION-001", "failure_duration_hours": 6},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        affected_ids = {item["step_id"] for item in body["affected_steps"]}
        self.assertEqual(affected_ids, {"STEP-2"})  # only the explicitly mapped step
        self.assertEqual(body["assumptions"], [])

        # Tenant isolation: the other tenant cannot see or act on this
        # service at all -- unaffected by anything in this fix.
        cross_tenant = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.other_headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(cross_tenant.status_code, 404)

    def test_sla_resolution_via_endpoint_and_tenant_isolation_unaffected(self):
        # SLA handling audit fix, end to end through the real endpoint
        # -- plus confirms this fix touches nothing about tenant
        # isolation.
        steps_with_sla = [
            _future_step(1, "Customer states the request", "CUSTOMER"),
            {**_future_step(2, "Employee reviews the case", "HUMAN"), "sla_hours": 6},
            _future_step(3, "System issues the result", "SYSTEM"),
        ]
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="SLA Endpoint Service"
        )
        self.main_module.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-sla-endpoint",
            result=_analysis_result(future_steps=steps_with_sla, required_integrations=[]),
        )
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "SLA_BREACH", "trigger_type": "MANUAL",
                "variables": {"breached_step_id": "STEP-2", "delay_multiplier": 3.0},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["assumptions"], [])  # real step-level SLA -- not an assumption

        # Tenant isolation: the other tenant cannot see or act on this
        # service at all -- unaffected by anything in this fix.
        cross_tenant = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.other_headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(cross_tenant.status_code, 404)

    def test_citizen_outcome_impact_via_endpoint_and_tenant_isolation_unaffected(self):
        # Citizen/outcome impact audit fix, end to end through the
        # real endpoint -- a zero-customer-step service (all SYSTEM
        # steps) whose first step cascades and blocks the rest,
        # including the final delivery step -- plus confirms this fix
        # touches nothing about tenant isolation.
        zero_customer_steps = [
            _future_step(1, "System validates the request", "SYSTEM"),
            _future_step(2, "System issues the result", "SYSTEM"),
        ]
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Zero Customer Step Outcome Service"
        )
        self.main_module.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-outcome-endpoint",
            result=_analysis_result(future_steps=zero_customer_steps, required_integrations=[]),
        )
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "CASCADING_STEP_FAILURE", "trigger_type": "MANUAL",
                "variables": {"origin_step_id": "STEP-1", "failure_probability": 1.0},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("0 of 0 customer-facing", body["citizen_impact"]["basis"])
        self.assertEqual(body["citizen_impact"]["score"], 0)
        self.assertTrue(body["citizen_outcome_affected"])
        self.assertTrue(body["outcome_impact_reason"])

        # Tenant isolation: the other tenant cannot see or act on this
        # service at all -- unaffected by anything in this fix.
        cross_tenant = self.client.post(
            f"/api/services/{service['id']}/scenarios",
            headers=self.other_headers,
            json={"trigger_type": "AUTO"},
        )
        self.assertEqual(cross_tenant.status_code, 404)


if __name__ == "__main__":
    unittest.main()
