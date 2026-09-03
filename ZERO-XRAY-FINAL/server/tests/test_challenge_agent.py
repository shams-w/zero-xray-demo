"""Focused tests for the Challenge capability (Step 3 of the ZERO
X-RAY -> Government Future Engine evolution):
agents/challenge_agent.py, core/challenge_store.py, and the
POST/GET /api/services/{service_id}/challenges endpoints.

Isolated the same way tests/test_future_simulation_agent.py is: pure
unit tests where possible, temp-directory SQLite for store
integration, and never a call into agents/orchestrator.py or
graph/workflow.py.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:19999")  # deliberately unreachable
os.environ.setdefault("ZX_LLM_MODE", "ollama")

from agents.challenge_agent import (
    ChallengeAgent,
    CHALLENGE_STRATEGIES,
    SPOF_RATIO_THRESHOLD,
    CUSTOMER_EXPOSURE_THRESHOLD,
)
from agents.future_simulation_agent import FutureSimulationAgent, ScenarioValidationError
from core.future_engine_errors import InsufficientDataError
from core.challenge_store import ChallengeStore
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


# A 4-step chain: CUSTOMER -> SYSTEM -> HUMAN -> SYSTEM, plus one
# integration -- big enough to exercise every strategy/rule without
# being expensive to compute by hand for assertions.
SAMPLE_STEPS = [
    _future_step(1, "Customer states the request", "CUSTOMER"),
    _future_step(2, "System verifies identity", "SYSTEM"),
    _future_step(3, "Employee reviews the case", "HUMAN"),
    _future_step(4, "System issues the result", "SYSTEM"),
]
SAMPLE_INTEGRATIONS = ["National ID Registry"]


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


class DeterministicCaseGenerationTestCase(unittest.TestCase):
    def setUp(self):
        self.simulation_agent = FutureSimulationAgent(llm=None)
        self.agent = ChallengeAgent(future_simulation_agent=self.simulation_agent, llm=None)
        self.graph = _sample_graph()

    def test_all_four_strategies_produce_expected_case_counts(self):
        cases = self.agent.generate_cases([], self.graph)  # empty = all strategies
        by_strategy = {}
        for case in cases:
            by_strategy.setdefault(case["strategy"], []).append(case)
        self.assertEqual(len(by_strategy["EXHAUSTIVE_STEP_FAILURE"]), 4)   # one per step
        self.assertEqual(len(by_strategy["EXHAUSTIVE_INTEGRATION_FAILURE"]), 1)  # one per integration
        self.assertEqual(len(by_strategy["SLA_STRESS"]), 4)               # one per step
        self.assertEqual(len(by_strategy["DEMAND_STRESS"]), 1)            # exactly one
        self.assertEqual(len(cases), 2 * 4 + 1 + 1)

    def test_case_ids_are_deterministic_not_random(self):
        cases_a = self.agent.generate_cases(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        cases_b = self.agent.generate_cases(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        self.assertEqual([c["case_id"] for c in cases_a], [c["case_id"] for c in cases_b])
        self.assertEqual(cases_a[0]["case_id"], "EXHAUSTIVE_STEP_FAILURE:STEP-1")

    def test_demand_stress_case_id_is_fixed(self):
        cases = self.agent.generate_cases(["DEMAND_STRESS"], self.graph)
        self.assertEqual(cases[0]["case_id"], "DEMAND_STRESS:SERVICE")
        self.assertIsNone(cases[0]["target"])

    # --- invalid strategy -------------------------------------------
    def test_invalid_strategy_is_rejected(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.generate_cases(["NOT_A_REAL_STRATEGY"], self.graph)

    def test_strategy_order_is_independent_of_request_order(self):
        cases_forward = self.agent.generate_cases(
            ["DEMAND_STRESS", "SLA_STRESS", "EXHAUSTIVE_STEP_FAILURE"], self.graph
        )
        cases_reversed = self.agent.generate_cases(
            ["EXHAUSTIVE_STEP_FAILURE", "SLA_STRESS", "DEMAND_STRESS"], self.graph
        )
        self.assertEqual(
            [c["case_id"] for c in cases_forward], [c["case_id"] for c in cases_reversed]
        )


class VulnerabilityDerivationTestCase(unittest.TestCase):
    """Pure logic tests -- proves each of the 6 derivation rules fires
    exactly at its documented threshold and not before."""

    def setUp(self):
        self.simulation_agent = FutureSimulationAgent(llm=None)
        self.agent = ChallengeAgent(future_simulation_agent=self.simulation_agent, llm=None)
        self.graph = _sample_graph()

    def test_single_point_of_failure_fires_at_threshold(self):
        # STEP-1 (order 0) failing cascades to all 4 steps -> ratio 1.0 >= 0.5
        result = self.agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        spof = [v for v in result["vulnerabilities"] if v["vulnerability_type"] == "SINGLE_POINT_OF_FAILURE"]
        self.assertTrue(any(v["target"] == "STEP-1" for v in spof))

    def test_single_point_of_failure_does_not_fire_below_threshold(self):
        # STEP-4 (last step, order 3) failing only affects itself -> ratio 0.25 < 0.5
        result = self.agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        spof_targets = {
            v["target"] for v in result["vulnerabilities"]
            if v["vulnerability_type"] == "SINGLE_POINT_OF_FAILURE"
        }
        self.assertNotIn("STEP-4", spof_targets)

    def test_cascading_failure_path_picks_the_worst_single_case(self):
        result = self.agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        cascading = [v for v in result["vulnerabilities"] if v["vulnerability_type"] == "CASCADING_FAILURE_PATH"]
        self.assertEqual(len(cascading), 1)  # exactly one, per design
        self.assertEqual(cascading[0]["target"], "STEP-1")  # earliest step = most affected

    def test_sla_fragility_fires_only_when_affected_steps_nonempty(self):
        result = self.agent.run(["SLA_STRESS"], self.graph)
        # delay_multiplier=3.0 > 1.0, so every SLA_STRESS case has an effect
        sla = [v for v in result["vulnerabilities"] if v["vulnerability_type"] == "SLA_FRAGILITY"]
        self.assertEqual(len(sla), 4)  # one per step, all breach at 3x

    def test_demand_fragility_targets_customer_facing_steps_only(self):
        result = self.agent.run(["DEMAND_STRESS"], self.graph)
        demand = [v for v in result["vulnerabilities"] if v["vulnerability_type"] == "DEMAND_FRAGILITY"]
        targets = {v["target"] for v in demand}
        self.assertEqual(targets, {"STEP-1", "STEP-3"})  # CUSTOMER + HUMAN only

    def test_critical_path_exposure_requires_min_case_count(self):
        result = self.agent.run(
            ["EXHAUSTIVE_STEP_FAILURE", "SLA_STRESS"], self.graph
        )
        critical = [v for v in result["vulnerabilities"] if v["vulnerability_type"] == "CRITICAL_PATH_EXPOSURE"]
        # Every vulnerability of this type must have >= 2 source cases (the threshold).
        for vulnerability in critical:
            self.assertGreaterEqual(len(vulnerability["source_case_ids"]), 2)

    def test_customer_facing_exposure_respects_threshold_and_type(self):
        result = self.agent.run(["EXHAUSTIVE_STEP_FAILURE", "DEMAND_STRESS"], self.graph)
        customer_facing = [
            v for v in result["vulnerabilities"] if v["vulnerability_type"] == "CUSTOMER_FACING_EXPOSURE"
        ]
        for vulnerability in customer_facing:
            self.assertGreaterEqual(vulnerability["severity"], CUSTOMER_EXPOSURE_THRESHOLD)
        # No integration target should ever qualify (integrations aren't step-typed).
        self.assertNotIn("INTEGRATION-001", {v["target"] for v in customer_facing})

    def test_integration_failure_only_produces_spof_not_customer_facing(self):
        result = self.agent.run(["EXHAUSTIVE_INTEGRATION_FAILURE"], self.graph)
        types_by_target = {v["target"]: v["vulnerability_type"] for v in result["vulnerabilities"]}
        self.assertIn("INTEGRATION-001", types_by_target)
        self.assertEqual(types_by_target["INTEGRATION-001"], "SINGLE_POINT_OF_FAILURE")

    def test_integration_impact_changes_correctly_when_mapping_exists(self):
        # Integration-to-Step Mapping audit fix: Challenge's own SPOF
        # classification (agents/challenge_agent.py's
        # _derive_single_point_of_failure, UNCHANGED by this fix) is
        # driven entirely by how many steps FutureSimulationAgent's
        # INTEGRATION_FAILURE execution says are affected. Restricting
        # that to a real, mapped step (instead of every SYSTEM step)
        # must change Challenge's own downstream classification --
        # proving the mapping fix actually reaches Challenge, not just
        # Simulate, with zero changes to challenge_agent.py itself.
        graph = {
            "steps": [
                {"step_id": "STEP-1", "name": "Customer submits request", "type": "CUSTOMER", "order": 0,
                 "has_payment": False, "requires_approval": False, "evidence_text": "Customer submits request"},
                {"step_id": "STEP-2", "name": "System step A", "type": "SYSTEM", "order": 1,
                 "has_payment": False, "requires_approval": False, "evidence_text": "System step A"},
                {"step_id": "STEP-3", "name": "System step B", "type": "SYSTEM", "order": 2,
                 "has_payment": False, "requires_approval": False, "evidence_text": "System step B"},
                {"step_id": "STEP-4", "name": "System step C", "type": "SYSTEM", "order": 3,
                 "has_payment": False, "requires_approval": False, "evidence_text": "System step C"},
            ],
            "integrations": [
                {"integration_id": "INTEGRATION-001", "name": "Niche Integration"},
            ],
            "journeys_count": 0, "source_analysis_id": "an-impact-change",
        }
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(future_simulation_agent=simulation_agent, llm=None)

        # Before mapping: fallback ASSUMPTION affects all 3 SYSTEM
        # steps out of 4 total (ratio 0.75 >= 0.5 threshold) -> SPOF.
        before = agent.run(["EXHAUSTIVE_INTEGRATION_FAILURE"], graph)
        before_types = {v["target"]: v["vulnerability_type"] for v in before["vulnerabilities"]}
        self.assertEqual(before_types.get("INTEGRATION-001"), "SINGLE_POINT_OF_FAILURE")

        # With an explicit mapping to a single step: 1 of 4 (ratio
        # 0.25 < 0.5 threshold) -> no longer classified as SPOF.
        graph["integrations"][0]["step_ids"] = ["STEP-2"]
        after = agent.run(["EXHAUSTIVE_INTEGRATION_FAILURE"], graph)
        after_types = {v["target"]: v["vulnerability_type"] for v in after["vulnerabilities"]}
        self.assertNotEqual(after_types.get("INTEGRATION-001"), "SINGLE_POINT_OF_FAILURE")

    def test_citizen_outcome_impact_field_propagates_via_source_outputs(self):
        # Citizen/outcome impact audit fix: Challenge does NOT
        # duplicate _determine_citizen_outcome_impact() -- it relays
        # the field from each vulnerability's own source_outputs (each
        # a full FutureSimulationAgent.run() output), unchanged.
        # STEP-1 (order 0) cascading failure blocks all 4 steps
        # (including the last one), so it must carry
        # citizen_outcome_affected=True even for the zero-customer-
        # step slice of this graph.
        result = self.agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        step1_vulnerabilities = [v for v in result["vulnerabilities"] if v["target"] == "STEP-1"]
        self.assertTrue(step1_vulnerabilities)
        for vulnerability in step1_vulnerabilities:
            self.assertIn("citizen_outcome_affected", vulnerability)
            self.assertIn("outcome_impact_reason", vulnerability)
            self.assertTrue(vulnerability["citizen_outcome_affected"])
            self.assertTrue(vulnerability["outcome_impact_reason"])

    def test_citizen_outcome_impact_false_when_no_source_output_indicates_it(self):
        # Proves the FALSE aggregation path itself: when none of a
        # vulnerability's source_outputs report outcome impact (an
        # integration mapped to a non-final step only, DEGRADED, not
        # blocking/delaying/reaching the final step), the relayed
        # field is correctly False, not True by default. Total step
        # count kept small so the SPOF ratio threshold is still met
        # (1 of 2 steps affected -- see agents/challenge_agent.py's
        # SPOF_RATIO_THRESHOLD, unchanged), proving a REAL derived
        # vulnerability, not an empty result.
        graph = {
            "steps": [
                {"step_id": "STEP-1", "name": "System non-final step", "type": "SYSTEM", "order": 0},
                {"step_id": "STEP-2", "name": "System final step", "type": "SYSTEM", "order": 1},
            ],
            "integrations": [{"integration_id": "INTEGRATION-001", "name": "Non-Critical API",
                               "step_ids": ["STEP-1"]}],  # mapped to the NON-final step only
            "journeys_count": 0, "source_analysis_id": "an-x",
        }
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(future_simulation_agent=simulation_agent, llm=None)
        result = agent.run(["EXHAUSTIVE_INTEGRATION_FAILURE"], graph)
        integration_vulnerabilities = [v for v in result["vulnerabilities"] if v["target"] == "INTEGRATION-001"]
        self.assertTrue(integration_vulnerabilities)
        for vulnerability in integration_vulnerabilities:
            self.assertFalse(vulnerability["citizen_outcome_affected"])


class RankingTestCase(unittest.TestCase):
    def setUp(self):
        self.simulation_agent = FutureSimulationAgent(llm=None)
        self.agent = ChallengeAgent(future_simulation_agent=self.simulation_agent, llm=None)
        self.graph = _sample_graph()

    def test_vulnerabilities_are_sorted_by_severity_descending(self):
        result = self.agent.run(list(CHALLENGE_STRATEGIES), self.graph)
        severities = [v["severity"] for v in result["vulnerabilities"]]
        self.assertEqual(severities, sorted(severities, reverse=True))

    def test_tie_break_is_step_order_ascending(self):
        # Both STEP-1 and STEP-2 SPOF at ratio 1.0 with the same
        # likelihood (1.0), so their severities tie; STEP-1 (order 0)
        # must rank before STEP-2 (order 1).
        result = self.agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        spof_targets_in_order = [
            v["target"] for v in result["vulnerabilities"]
            if v["vulnerability_type"] == "SINGLE_POINT_OF_FAILURE"
        ]
        step1_index = spof_targets_in_order.index("STEP-1") if "STEP-1" in spof_targets_in_order else None
        step2_index = spof_targets_in_order.index("STEP-2") if "STEP-2" in spof_targets_in_order else None
        if step1_index is not None and step2_index is not None:
            self.assertLess(step1_index, step2_index)


class DeterminismAndGroundingTestCase(unittest.TestCase):
    def setUp(self):
        self.simulation_agent = FutureSimulationAgent(llm=None)
        self.agent = ChallengeAgent(future_simulation_agent=self.simulation_agent, llm=None)
        self.graph = _sample_graph()

    # --- repeated identical runs ---------------------------------------
    def test_repeated_run_is_identical(self):
        result_a = self.agent.run(list(CHALLENGE_STRATEGIES), self.graph)
        result_b = self.agent.run(list(CHALLENGE_STRATEGIES), self.graph)
        self.assertEqual(
            [c["case_id"] for c in result_a["cases_executed"]],
            [c["case_id"] for c in result_b["cases_executed"]],
        )
        self.assertEqual(result_a["vulnerabilities"], result_b["vulnerabilities"])
        self.assertEqual(result_a["grounding_summary"], result_b["grounding_summary"])

    # --- grounding propagation -----------------------------------------
    def test_grounding_propagates_assumption_tags_from_simulation(self):
        result = self.agent.run(["EXHAUSTIVE_INTEGRATION_FAILURE"], self.graph)
        spof = next(
            v for v in result["vulnerabilities"] if v["vulnerability_type"] == "SINGLE_POINT_OF_FAILURE"
        )
        # INTEGRATION_FAILURE's underlying Simulation always records an
        # ASSUMPTION (no per-step integration mapping exists) -- that
        # tag must survive into Challenge's evidence untouched.
        assumption_types = {entry["type"] for entry in spof["evidence"]}
        self.assertIn("ASSUMPTION", assumption_types)

    def test_prediction_linked_run_shows_prediction_grounding(self):
        linked_prediction = {
            "predictions": [{"confidence": 0.9}],
            "data_sufficiency": {"verdict": "SUFFICIENT"},
        }
        result = self.agent.run(
            ["DEMAND_STRESS"], self.graph, linked_prediction=linked_prediction
        )
        self.assertGreater(result["grounding_summary"]["prediction_count"], 0)

    # --- LLM fabrication rejection --------------------------------------
    def test_llm_cannot_fabricate_severity_or_counts(self):
        class FabricatingLLM:
            def generate(self, *args, **kwargs):
                return "This vulnerability has severity 9999 across 500 cases."

        agent = ChallengeAgent(
            future_simulation_agent=FutureSimulationAgent(llm=None), llm=FabricatingLLM()
        )
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        for vulnerability in result["vulnerabilities"][:1]:
            self.assertEqual(vulnerability["explanation_source"], "template")
            self.assertNotIn("9999", vulnerability["explanation"])

    # --- LLM unavailable fallback ----------------------------------------
    def test_no_llm_configured_always_uses_template(self):
        result = self.agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        for vulnerability in result["vulnerabilities"]:
            self.assertEqual(vulnerability["explanation_source"], "template")
            self.assertTrue(vulnerability["explanation"])

    def test_llm_explanation_accepted_when_grounded(self):
        class HonestLLM:
            def generate(self, *args, **kwargs):
                return "This step is a critical single point of failure."

        agent = ChallengeAgent(
            future_simulation_agent=FutureSimulationAgent(llm=None), llm=HonestLLM()
        )
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph)
        self.assertTrue(any(v["explanation_source"] == "ai" for v in result["vulnerabilities"]))

    def test_top_k_limit_does_not_affect_determinism_of_ranking(self):
        result_no_llm = self.agent.run(list(CHALLENGE_STRATEGIES), self.graph)

        class HonestLLM:
            def generate(self, *args, **kwargs):
                return "Summary sentence with no invented facts."

        agent_with_llm = ChallengeAgent(
            future_simulation_agent=FutureSimulationAgent(llm=None), llm=HonestLLM()
        )
        result_with_llm = agent_with_llm.run(list(CHALLENGE_STRATEGIES), self.graph)
        self.assertEqual(
            [v["vulnerability_id"] for v in result_no_llm["vulnerabilities"]],
            [v["vulnerability_id"] for v in result_with_llm["vulnerabilities"]],
        )
        self.assertEqual(
            [v["severity"] for v in result_no_llm["vulnerabilities"]],
            [v["severity"] for v in result_with_llm["vulnerabilities"]],
        )


class ServiceGraphAndStoreIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)
        self.service_store = ServiceStore(database_path=self.runtime_store.database_path)
        self.challenge_store = ChallengeStore(database_path=self.runtime_store.database_path)
        self.prediction_store = PredictionStore(database_path=self.runtime_store.database_path)
        self.simulation_store = SimulationStore(database_path=self.runtime_store.database_path)
        self.tenant_id = self.runtime_store.default_tenant_id

    def tearDown(self):
        self._tmp.cleanup()

    # --- empty service graph ---------------------------------------------
    def test_empty_service_graph_is_rejected_by_underlying_simulation_validation(self):
        """An empty graph has no step/integration to validate ANY
        scenario against -- including DEMAND_STRESS, which targets the
        whole service. FutureSimulationAgent.validate_scenario() (Step
        2, unmodified) already refuses this; Challenge must propagate
        that refusal rather than silently swallowing it. This is why
        the /challenges endpoint checks for an empty graph up front
        and returns 400 before ever calling ChallengeAgent.run() --
        see test_challenge_on_service_with_no_analysis_returns_400."""
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Fresh Service")
        simulation_agent = FutureSimulationAgent(llm=None)
        graph = simulation_agent.build_service_graph(
            service_id=service["id"], tenant_id=self.tenant_id,
            service_store=self.service_store, database_path=self.runtime_store.database_path,
        )
        self.assertEqual(graph["steps"], [])
        self.assertEqual(graph["integrations"], [])
        agent = ChallengeAgent(future_simulation_agent=simulation_agent, llm=None)
        with self.assertRaises(InsufficientDataError):
            agent.run(list(CHALLENGE_STRATEGIES), graph)

    def test_challenges_table_is_additive_predictions_and_scenarios_untouched(self):
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Svc")
        saved = self.challenge_store.save_challenge(
            tenant_id=self.tenant_id, service_id=service["id"],
            input_snapshot={"strategies": []}, result={"vulnerabilities": []},
        )
        self.assertIsNotNone(saved)
        self.assertEqual(
            self.prediction_store.list_predictions_for_service(service["id"], self.tenant_id), []
        )
        self.assertEqual(
            self.simulation_store.list_scenarios_for_service(service["id"], self.tenant_id), []
        )


class ChallengeEndpointTestCase(unittest.TestCase):
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
            f"Challenge Test Tenant {suffix}", f"challenge-test-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Challenge Test Admin", f"challenge-test-{suffix}@test.local", role="entity_admin"
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

        other_suffix = uuid.uuid4().hex[:8]
        other_tenant = main_module.tenant_repository.create_tenant(
            f"Other Challenge Tenant {other_suffix}", f"other-challenge-tenant-{other_suffix}",
            status="ACTIVE",
        )
        other_user = main_module.tenant_repository.create_user(
            other_tenant["id"], "Other Admin", f"other-challenge-{other_suffix}@test.local",
            role="entity_admin",
        )
        other_login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": other_user["email"], "credential": "zxr-demo-2026"},
        )
        cls.other_headers = {"Authorization": f"Bearer {other_login.json()['token']}"}
        cls.other_tenant_id = other_tenant["id"]

    def _service_with_graph(self, tenant_id):
        service = self.main_module.service_store.create_service(
            tenant_id=tenant_id, service_name="Challenge Endpoint Service"
        )
        self.main_module.service_store.create_analysis(
            tenant_id=tenant_id, service_id=service["id"], blueprint_id="bp-challenge",
            result=_analysis_result(future_steps=SAMPLE_STEPS, required_integrations=SAMPLE_INTEGRATIONS),
        )
        return service

    # --- missing service ---------------------------------------------------
    def test_challenge_on_unknown_service_returns_404(self):
        response = self.client.post(
            "/api/services/does-not-exist/challenges", headers=self.headers, json={}
        )
        self.assertEqual(response.status_code, 404)

    # --- empty service graph (via endpoint) ---------------------------------
    def test_challenge_on_service_with_no_analysis_returns_400(self):
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="No History Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/challenges", headers=self.headers, json={}
        )
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        # Structured INSUFFICIENT_DATA (service-generic/stage-dependency
        # audit fix) -- not an unstructured string.
        self.assertEqual(detail["error_code"], "INSUFFICIENT_DATA")
        self.assertTrue(detail["reason"])
        self.assertTrue(detail["missing_requirement"])
        self.assertTrue(detail["next_action"])

    # --- invalid strategy (via endpoint) -------------------------------------
    def test_invalid_strategy_returns_422_from_schema(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/challenges",
            headers=self.headers,
            json={"strategies": ["NOT_REAL"]},
        )
        self.assertEqual(response.status_code, 422)

    # --- missing prediction reference ----------------------------------------
    def test_missing_prediction_reference_returns_404(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/challenges",
            headers=self.headers,
            json={"prediction_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)

    # --- cross-tenant prediction reference ------------------------------------
    def test_prediction_from_another_tenant_is_treated_as_not_found(self):
        other_service = self._service_with_graph(self.other_tenant_id)
        prediction_response = self.client.post(
            f"/api/services/{other_service['id']}/predict", headers=self.other_headers
        )
        self.assertEqual(prediction_response.status_code, 200)
        other_prediction_id = prediction_response.json()["prediction_id"]

        my_service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{my_service['id']}/challenges",
            headers=self.headers,  # a DIFFERENT tenant's token
            json={"prediction_id": other_prediction_id},
        )
        self.assertEqual(response.status_code, 404)

    # --- endpoint smoke test ---------------------------------------------------
    def test_full_challenge_run_and_list(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/challenges", headers=self.headers, json={}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("challenge_id", body)
        self.assertGreater(len(body["cases_executed"]), 0)
        self.assertIn("vulnerabilities", body)
        self.assertIn("grounding_summary", body)

        list_response = self.client.get(
            f"/api/services/{service['id']}/challenges", headers=self.headers
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["challenges"]), 1)

    def test_single_strategy_request_only_executes_that_strategy(self):
        service = self._service_with_graph(self.tenant_id)
        response = self.client.post(
            f"/api/services/{service['id']}/challenges",
            headers=self.headers,
            json={"strategies": ["DEMAND_STRESS"]},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["cases_executed"]), 1)
        self.assertEqual(body["cases_executed"][0]["strategy"], "DEMAND_STRESS")


if __name__ == "__main__":
    unittest.main()
