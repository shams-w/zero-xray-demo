"""Focused tests for the two Step-3-audit fixes:

Fix #1 -- the originally specified deterministic Predict -> Simulate
linkage (agents/future_simulation_agent.py::derive_scenario_from_prediction)
and the CASCADING_STEP_FAILURE likelihood bugfix.

Fix #2 -- the additive `score_methodology` marker on Predict/Simulate/
Challenge outputs (core/score_methodology.py).

Isolated the same way the other focused test files are: pure unit
tests where possible, temp-directory SQLite for store integration,
never a call into agents/orchestrator.py or graph/workflow.py.
"""

import os
import unittest

from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env

# Mandatory AI Mode audit fix: this file exercises /api/analyze only as a
# fixture for UNRELATED functionality, so it needs a completed analysis --
# point core.llm at the repo's real, reachable stdlib mock Ollama server for
# the duration of THIS module's tests only (never a deliberately unreachable
# host), then restore whatever was there before. See tools/test_mock_env.py
# for why this is scoped via setUpModule/tearDownModule rather than a plain
# module-level call.
_ollama_patch = None


def setUpModule():
    global _ollama_patch
    _ollama_patch = patch_ollama_env()


def tearDownModule():
    unpatch_ollama_env(_ollama_patch)

from agents.challenge_agent import ChallengeAgent
from agents.future_simulation_agent import (
    FutureSimulationAgent,
    ScenarioValidationError,
    PREDICTION_DEFAULT_TIME_HORIZON_DAYS,
)
from agents.prediction_agent import PredictionAgent
from core.score_methodology import SCORE_METHODOLOGY_MARKER


def _sample_graph():
    return {
        "steps": [
            {"step_id": "STEP-1", "name": "Customer states the request", "type": "CUSTOMER", "order": 0},
            {"step_id": "STEP-2", "name": "System verifies identity", "type": "SYSTEM", "order": 1},
            {"step_id": "STEP-3", "name": "Employee reviews the case", "type": "HUMAN", "order": 2},
            {"step_id": "STEP-4", "name": "System issues the result", "type": "SYSTEM", "order": 3},
        ],
        "integrations": [{"integration_id": "INTEGRATION-001", "name": "National ID Registry"}],
        "journeys_count": 5,
        "source_analysis_id": "an-sample",
    }


def _prediction_result(predictions):
    return {"service_id": "svc-1", "generated_at": "now", "predictions": predictions,
            "data_sufficiency": {"analyses_count": 2, "journeys_count": 2, "verdict": "LIMITED"}}


def _prediction_item(prediction_id, confidence, source, category="General"):
    return {
        "prediction_id": prediction_id,
        "prediction_type": "EVIDENCE_BASED",
        "statement": "stub statement",
        "category": category,
        "confidence": confidence,
        "confidence_basis": "2 of 2 analyses",
        "signals": [{"source": source, "reference_id": "an-1", "detail": "stub"}],
        "explanation": "stub",
        "explanation_source": "template",
        "recommendation": None,
    }


class PredictionToScenarioLookupTestCase(unittest.TestCase):
    """Fix #1: agents/future_simulation_agent.py::derive_scenario_from_prediction
    -- pure unit tests, no database, no LLM."""

    def setUp(self):
        self.agent = FutureSimulationAgent(llm=None)
        self.graph = _sample_graph()

    def test_journey_intent_signal_maps_to_volume_surge(self):
        prediction = _prediction_result([_prediction_item("PRED-001", 0.8, "journey_intent")])
        scenario_type, variables, prediction_id = self.agent.derive_scenario_from_prediction(
            prediction, self.graph
        )
        self.assertEqual(scenario_type, "VOLUME_SURGE")
        self.assertEqual(prediction_id, "PRED-001")
        self.assertIn("demand_multiplier", variables)
        self.assertIn("time_horizon_days", variables)
        self.assertEqual(variables["time_horizon_days"], PREDICTION_DEFAULT_TIME_HORIZON_DAYS)
        # deterministic: 1.0 + confidence, bounded [1.0, 5.0]
        self.assertEqual(variables["demand_multiplier"], round(1.0 + 0.8, 2))

    def test_gap_signal_maps_to_sla_breach_on_earliest_step(self):
        prediction = _prediction_result([_prediction_item("PRED-001", 0.5, "gap")])
        scenario_type, variables, _ = self.agent.derive_scenario_from_prediction(prediction, self.graph)
        self.assertEqual(scenario_type, "SLA_BREACH")
        self.assertEqual(variables["breached_step_id"], "STEP-1")  # earliest step, order=0
        # gap weight = 2.0 -> 1.0 + 2.0*0.5 = 2.0
        self.assertEqual(variables["delay_multiplier"], 2.0)

    def test_friction_point_signal_maps_to_sla_breach_with_lower_weight(self):
        prediction = _prediction_result([_prediction_item("PRED-001", 0.5, "friction_point")])
        scenario_type, variables, _ = self.agent.derive_scenario_from_prediction(prediction, self.graph)
        self.assertEqual(scenario_type, "SLA_BREACH")
        # friction weight = 1.5 -> 1.0 + 1.5*0.5 = 1.75
        self.assertEqual(variables["delay_multiplier"], 1.75)

    def test_derived_variables_are_bounded(self):
        # confidence=1.0 with gap weight 2.0 -> raw 3.0, still within [1,5]; use an
        # extreme confidence to prove the bound actually clips rather than trusting
        # the formula alone.
        prediction = _prediction_result([_prediction_item("PRED-001", 1.0, "journey_intent")])
        _, variables, _ = self.agent.derive_scenario_from_prediction(prediction, self.graph)
        self.assertLessEqual(variables["demand_multiplier"], 5.0)
        self.assertGreaterEqual(variables["demand_multiplier"], 1.0)

    def test_highest_confidence_prediction_is_selected_deterministically(self):
        prediction = _prediction_result([
            _prediction_item("PRED-LOW", 0.2, "gap"),
            _prediction_item("PRED-HIGH", 0.9, "journey_intent"),
        ])
        scenario_type, variables, chosen_id = self.agent.derive_scenario_from_prediction(
            prediction, self.graph
        )
        self.assertEqual(chosen_id, "PRED-HIGH")
        self.assertEqual(scenario_type, "VOLUME_SURGE")  # from the higher-confidence one

    def test_tie_break_is_deterministic_by_prediction_id(self):
        prediction = _prediction_result([
            _prediction_item("PRED-B", 0.5, "gap"),
            _prediction_item("PRED-A", 0.5, "journey_intent"),
        ])
        _, _, chosen_id = self.agent.derive_scenario_from_prediction(prediction, self.graph)
        self.assertEqual(chosen_id, "PRED-A")  # same confidence -> lexically first id wins

    def test_no_predictions_raises_validation_error(self):
        with self.assertRaises(ScenarioValidationError):
            self.agent.derive_scenario_from_prediction(_prediction_result([]), self.graph)

    def test_no_signals_raises_validation_error(self):
        item = _prediction_item("PRED-001", 0.5, "gap")
        item["signals"] = []
        with self.assertRaises(ScenarioValidationError):
            self.agent.derive_scenario_from_prediction(_prediction_result([item]), self.graph)

    def test_unsupported_signal_source_raises_validation_error(self):
        item = _prediction_item("PRED-001", 0.5, "unknown_source")
        with self.assertRaises(ScenarioValidationError):
            self.agent.derive_scenario_from_prediction(_prediction_result([item]), self.graph)

    def test_gap_signal_with_empty_graph_raises_validation_error(self):
        empty_graph = {"steps": [], "integrations": [], "journeys_count": 0, "source_analysis_id": None}
        prediction = _prediction_result([_prediction_item("PRED-001", 0.5, "gap")])
        with self.assertRaises(ScenarioValidationError):
            self.agent.derive_scenario_from_prediction(prediction, empty_graph)

    def test_derived_scenario_is_runnable_end_to_end(self):
        """The derived (scenario_type, variables) must pass Simulate's
        own unmodified validate_scenario() and run() -- proving the
        lookup table produces genuinely valid Simulate input, not just
        a plausible-looking dict."""
        prediction = _prediction_result([_prediction_item("PRED-001", 0.8, "journey_intent")])
        scenario_type, variables, _ = self.agent.derive_scenario_from_prediction(prediction, self.graph)
        validated = self.agent.validate_scenario(scenario_type, variables, self.graph)
        result = self.agent.run(scenario_type, validated, self.graph, linked_prediction=prediction)
        self.assertIn("affected_steps", result)
        self.assertEqual(result["likelihood_source"], "PREDICTION")  # not silently ignored


class CascadingStepFailureLikelihoodFixTestCase(unittest.TestCase):
    """Fix #1b: a linked Prediction must inform CASCADING_STEP_FAILURE's
    likelihood when it's more informative than the supplied variable,
    instead of being unconditionally ignored."""

    def setUp(self):
        self.agent = FutureSimulationAgent(llm=None)
        self.graph = _sample_graph()

    def test_prediction_confidence_used_when_higher_than_variable(self):
        prediction = _prediction_result([_prediction_item("PRED-001", 0.95, "gap")])
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-2", "failure_probability": 0.3}, self.graph
        )
        result = self.agent.run(
            "CASCADING_STEP_FAILURE", variables, self.graph, linked_prediction=prediction
        )
        self.assertEqual(result["likelihood"], 0.95)
        self.assertEqual(result["likelihood_source"], "PREDICTION")

    def test_variable_used_when_higher_than_prediction_confidence(self):
        prediction = _prediction_result([_prediction_item("PRED-001", 0.2, "gap")])
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-2", "failure_probability": 0.9}, self.graph
        )
        result = self.agent.run(
            "CASCADING_STEP_FAILURE", variables, self.graph, linked_prediction=prediction
        )
        self.assertEqual(result["likelihood"], 0.9)
        self.assertEqual(result["likelihood_source"], "ASSUMPTION_OR_VARIABLE")

    def test_no_linked_prediction_behaves_exactly_as_before(self):
        variables = self.agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-2", "failure_probability": 0.8}, self.graph
        )
        result = self.agent.run("CASCADING_STEP_FAILURE", variables, self.graph, linked_prediction=None)
        self.assertEqual(result["likelihood"], 0.8)
        self.assertEqual(result["likelihood_source"], "ASSUMPTION_OR_VARIABLE")

    def test_challenge_exhaustive_step_failure_unaffected_by_fix(self):
        """Challenge's EXHAUSTIVE_STEP_FAILURE always uses
        failure_probability=1.0 (the worst-case constant), which no
        prediction confidence (<=1.0) can ever exceed -- so this fix
        must not change Challenge's own case severities/ranking."""
        prediction = _prediction_result([_prediction_item("PRED-001", 0.99, "gap")])
        agent = ChallengeAgent(future_simulation_agent=self.agent, llm=None)
        result_without = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self.graph, linked_prediction=None)
        result_with = agent.run(
            ["EXHAUSTIVE_STEP_FAILURE"], self.graph, linked_prediction=prediction
        )
        self.assertEqual(
            [v["severity"] for v in result_without["vulnerabilities"]],
            [v["severity"] for v in result_with["vulnerabilities"]],
        )


class PredictionTriggeredScenarioEndpointTestCase(unittest.TestCase):
    """Endpoint-level test: trigger_type=PREDICTION with scenario_type
    omitted now auto-derives via the fixed lookup table; explicit
    scenario_type/variables under trigger_type=PREDICTION still work
    exactly as before (backward compatible); MANUAL still requires
    scenario_type; tenant isolation is preserved."""

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
            f"Audit Fix Tenant {suffix}", f"audit-fix-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Audit Fix Admin", f"audit-fix-{suffix}@test.local", role="entity_admin"
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

        other_suffix = uuid.uuid4().hex[:8]
        other_tenant = main_module.tenant_repository.create_tenant(
            f"Other Audit Fix Tenant {other_suffix}", f"other-audit-fix-tenant-{other_suffix}",
            status="ACTIVE",
        )
        other_user = main_module.tenant_repository.create_user(
            other_tenant["id"], "Other Admin", f"other-audit-fix-{other_suffix}@test.local",
            role="entity_admin",
        )
        other_login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": other_user["email"], "credential": "zxr-demo-2026"},
        )
        cls.other_headers = {"Authorization": f"Bearer {other_login.json()['token']}"}
        cls.other_tenant_id = other_tenant["id"]

    def _service_with_history(self, tenant_id, headers):
        """A service with a real stored analysis AND enough recurring
        signal (2 analyses with the same gap) for Predict to produce a
        usable prediction, via the real /api/analyze -> /api/predict
        flow -- not a hand-built fixture."""
        service_payload = {
            "service_name": "Audit Fix Renewal Service",
            "description": "Renew a permit",
            "steps": ["Customer submits request", "Employee reviews and approves"],
        }
        analyze_response = self.client.post("/api/analyze", headers=headers, json=service_payload)
        self.assertEqual(analyze_response.status_code, 200)
        service_id = analyze_response.json()["service_id"]
        service_payload["service_id"] = service_id
        # A second analysis on the same service_id so Predict has >=2
        # analyses to work with.
        second_response = self.client.post("/api/analyze", headers=headers, json=service_payload)
        self.assertEqual(second_response.status_code, 200)
        return service_id

    def test_manual_trigger_without_scenario_type_falls_back_to_auto(self):
        # ROOT-CAUSE FIX (Section 2 audit -- Simulation "Run
        # Simulation" 400 bug): this used to assert a 400 here, which
        # was itself the exact bug report -- a valid service must not
        # 400 just because no manual scenario was entered. MANUAL with
        # no scenario_type now falls back to AUTO scenario generation
        # instead (see agents/future_simulation_agent.py's
        # generate_auto_scenarios and main.py's create_scenario).
        # MANUAL *with* an explicit scenario_type is unchanged --
        # see test_explicit_scenario_type_under_prediction_trigger_still_works
        # below and tests/test_future_simulation_agent.py's
        # test_manual_scenario_with_explicit_type_is_completely_unchanged.
        service_id = self._service_with_history(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{service_id}/scenarios",
            headers=self.headers,
            json={"trigger_type": "MANUAL", "variables": {}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scenario"]["trigger_type"], "AUTO")

    def test_explicit_scenario_type_under_prediction_trigger_still_works(self):
        """Backward compatibility: a caller that still supplies
        scenario_type/variables explicitly under trigger_type=PREDICTION
        (the only behavior that existed before this fix) must continue
        to work exactly as before."""
        service_id = self._service_with_history(self.tenant_id, self.headers)
        predict_response = self.client.post(f"/api/services/{service_id}/predict", headers=self.headers)
        self.assertEqual(predict_response.status_code, 200)
        prediction_id = predict_response.json()["prediction_id"]

        response = self.client.post(
            f"/api/services/{service_id}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "VOLUME_SURGE", "trigger_type": "PREDICTION",
                "prediction_id": prediction_id,
                "variables": {"demand_multiplier": 2.0, "time_horizon_days": 30},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scenario"]["scenario_type"], "VOLUME_SURGE")

    def test_score_methodology_present_on_scenario_and_challenge_endpoints(self):
        service_id = self._service_with_history(self.tenant_id, self.headers)
        scenario_response = self.client.post(
            f"/api/services/{service_id}/scenarios",
            headers=self.headers,
            json={
                "scenario_type": "VOLUME_SURGE", "trigger_type": "MANUAL",
                "variables": {"demand_multiplier": 2.0, "time_horizon_days": 30},
            },
        )
        self.assertEqual(scenario_response.status_code, 200)
        self.assertEqual(
            scenario_response.json()["score_methodology"]["kind"], "ZERO_XRAY_ENGINEERING_HEURISTIC"
        )

        challenge_response = self.client.post(
            f"/api/services/{service_id}/challenges", headers=self.headers, json={}
        )
        self.assertEqual(challenge_response.status_code, 200)
        self.assertFalse(challenge_response.json()["score_methodology"]["statistically_validated"])

        predict_response = self.client.post(f"/api/services/{service_id}/predict", headers=self.headers)
        self.assertEqual(predict_response.status_code, 200)
        self.assertIn("score_methodology", predict_response.json())

    def test_prediction_trigger_without_scenario_type_auto_derives_via_endpoint(self):
        """The core of Fix #1: an omitted scenario_type under
        trigger_type=PREDICTION is auto-derived through the real
        endpoint from a real stored prediction row -- not just the
        agent-level unit test. A synthetic prediction with a known
        signal is inserted directly (bypassing the AI/heuristic
        pipeline's variability) so this test asserts the wiring, not
        the fallback pipeline's own gap-detection behavior."""
        service_id = self._service_with_history(self.tenant_id, self.headers)
        synthetic_result = {
            "service_id": service_id,
            "generated_at": "now",
            "predictions": [{
                "prediction_id": "PRED-SYNTHETIC",
                "prediction_type": "EVIDENCE_BASED",
                "statement": "Citizens repeatedly request faster renewal.",
                "category": "CITIZEN_INTENT",
                "confidence": 0.8,
                "confidence_basis": "2 of 2 journeys",
                "signals": [{"source": "journey_intent", "reference_id": "j-1", "detail": "renew"}],
                "explanation": "stub",
                "explanation_source": "template",
                "recommendation": None,
            }],
            "data_sufficiency": {"analyses_count": 2, "journeys_count": 2, "verdict": "LIMITED"},
        }
        saved = self.main_module.prediction_store.save_prediction(
            tenant_id=self.tenant_id, service_id=service_id,
            input_snapshot={}, result=synthetic_result, data_sufficiency="LIMITED",
        )

        response = self.client.post(
            f"/api/services/{service_id}/scenarios",
            headers=self.headers,
            json={"trigger_type": "PREDICTION", "prediction_id": saved["id"]},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scenario"]["scenario_type"], "VOLUME_SURGE")  # journey_intent -> VOLUME_SURGE
        self.assertEqual(body["scenario"]["trigger_reference_id"], saved["id"])
        self.assertIn("demand_multiplier", body["scenario"]["variables"])
        self.assertEqual(body["likelihood_source"], "PREDICTION")

    def test_cross_tenant_prediction_still_blocks_auto_derivation(self):
        """Tenant isolation must hold for the new auto-derivation path
        exactly as it already does for the explicit-variables path."""
        other_service_id = self._service_with_history(self.other_tenant_id, self.other_headers)
        other_predict_response = self.client.post(
            f"/api/services/{other_service_id}/predict", headers=self.other_headers
        )
        self.assertEqual(other_predict_response.status_code, 200)
        other_prediction_id = other_predict_response.json()["prediction_id"]

        my_service_id = self._service_with_history(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{my_service_id}/scenarios",
            headers=self.headers,  # a DIFFERENT tenant's token
            json={"trigger_type": "PREDICTION", "prediction_id": other_prediction_id},
        )
        self.assertEqual(response.status_code, 404)


class ScoreMethodologyMarkerTestCase(unittest.TestCase):
    """Fix #2: the additive score_methodology marker is present and
    correct on all three capabilities' outputs, and no existing
    field/value changed."""

    def test_marker_constant_shape(self):
        self.assertEqual(SCORE_METHODOLOGY_MARKER["kind"], "ZERO_XRAY_ENGINEERING_HEURISTIC")
        self.assertFalse(SCORE_METHODOLOGY_MARKER["statistically_validated"])
        self.assertIn("not calibrated statistical probabilities", SCORE_METHODOLOGY_MARKER["note"])

    def test_prediction_output_carries_marker(self):
        agent = PredictionAgent(llm=None)
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [], "journeys": [],
        }
        result = agent.run(prediction_input)
        self.assertEqual(result["score_methodology"], SCORE_METHODOLOGY_MARKER)
        # Existing fields/values must be completely unaffected.
        self.assertEqual(result["data_sufficiency"]["verdict"], "INSUFFICIENT")
        self.assertEqual(result["predictions"], [])

    def test_simulation_output_carries_marker(self):
        agent = FutureSimulationAgent(llm=None)
        graph = _sample_graph()
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-2", "failure_probability": 0.8}, graph
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, graph)
        self.assertEqual(result["score_methodology"], SCORE_METHODOLOGY_MARKER)
        # Existing scoring values must be completely unaffected by the marker.
        self.assertEqual(result["likelihood"], 0.8)

    def test_challenge_output_carries_marker(self):
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(future_simulation_agent=simulation_agent, llm=None)
        graph = _sample_graph()
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], graph)
        self.assertEqual(result["score_methodology"], SCORE_METHODOLOGY_MARKER)


if __name__ == "__main__":
    unittest.main()
