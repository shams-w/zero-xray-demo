"""Focused tests for the Monitoring/Alerts capability (Step 8 of the
ZERO X-RAY -> Government Future Engine evolution):
agents/monitoring_agent.py, core/alert_store.py, and the POST/GET
/api/services/{service_id}/monitoring-checks and
/api/services/{service_id}/alerts endpoints.

Isolated the same way the other focused test files are: pure unit
tests where possible, temp-directory SQLite for store integration,
never a call into agents/orchestrator.py or graph/workflow.py, and
never a re-run of Predict/Simulate/Challenge/Evolve/Prevent.
"""

import os
import tempfile
import unittest
from pathlib import Path

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

from agents.monitoring_agent import MonitoringAgent
from core.alert_store import AlertStore, determine_current_prevention_id, classify_and_order_alerts
from core.prevention_store import PreventionStore
from core.evolution_store import EvolutionStore
from core.challenge_store import ChallengeStore
from core.prediction_store import PredictionStore
from core.runtime_store import RuntimeStore
from core.service_store import ServiceStore
from core.simulation_store import SimulationStore


def _prediction_trigger(trigger_id="TRIG-1", threshold=0.7, source_vulnerability_id="V1"):
    return {
        "trigger_id": trigger_id,
        "trigger_type": "PREDICTION_EARLY_WARNING_TRIGGER",
        "source_proposal_id": "P1",
        "source_vulnerability_id": source_vulnerability_id,
        "watch_metric": "prediction_confidence",
        "watch_scope": "any Predict run for this service",
        "threshold_value": threshold,
        "threshold_basis": "stub",
        "action_if_triggered": "stub action",
        "protected": False,
        "status": "DEFINED",
        "grounding": [],
        "explanation": "stub",
        "explanation_source": "template",
    }


def _challenge_trigger(trigger_id="TRIG-2", threshold=60.0, source_vulnerability_id="V1"):
    return {
        "trigger_id": trigger_id,
        "trigger_type": "CHALLENGE_RECURRENCE_TRIGGER",
        "source_proposal_id": "P1",
        "source_vulnerability_id": source_vulnerability_id,
        "watch_metric": "challenge_severity",
        "watch_scope": f"vulnerability {source_vulnerability_id}",
        "threshold_value": threshold,
        "threshold_basis": "stub",
        "action_if_triggered": "stub action",
        "protected": False,
        "status": "DEFINED",
        "grounding": [],
        "explanation": "stub",
        "explanation_source": "template",
    }


class FakePredictionStore:
    def __init__(self, rows):
        self._rows = rows  # already in DESC order, like the real store returns

    def list_predictions_for_service(self, service_id, tenant_id):
        return self._rows


class FakeChallengeStore:
    def __init__(self, rows):
        self._rows = rows

    def list_challenges_for_service(self, service_id, tenant_id):
        return self._rows


class MonitoringAgentCheckTestCase(unittest.TestCase):
    """Pure unit tests -- no database. Prove the check logic is a
    deterministic comparison against already-stored data only."""

    def setUp(self):
        self.agent = MonitoringAgent()

    def test_prediction_confidence_no_stored_predictions(self):
        result = self.agent.check_trigger(
            _prediction_trigger(), "svc-1", "t-1", FakePredictionStore([]), FakeChallengeStore([])
        )
        self.assertIsNone(result["current_value"])
        self.assertFalse(result["breached"])
        self.assertIn("No stored Predict result", result["evidence"])

    def test_prediction_confidence_breached(self):
        stored = [{"id": "PRED-1", "result": {"predictions": [{"confidence": 0.9}, {"confidence": 0.3}]}}]
        result = self.agent.check_trigger(
            _prediction_trigger(threshold=0.7), "svc-1", "t-1",
            FakePredictionStore(stored), FakeChallengeStore([]),
        )
        self.assertEqual(result["current_value"], 0.9)  # max confidence, real data
        self.assertTrue(result["breached"])
        self.assertEqual(result["checked_against"], "PRED-1")

    def test_prediction_confidence_not_breached(self):
        stored = [{"id": "PRED-1", "result": {"predictions": [{"confidence": 0.5}]}}]
        result = self.agent.check_trigger(
            _prediction_trigger(threshold=0.7), "svc-1", "t-1",
            FakePredictionStore(stored), FakeChallengeStore([]),
        )
        self.assertEqual(result["current_value"], 0.5)
        self.assertFalse(result["breached"])

    def test_prediction_confidence_empty_predictions_list(self):
        stored = [{"id": "PRED-1", "result": {"predictions": []}}]
        result = self.agent.check_trigger(
            _prediction_trigger(), "svc-1", "t-1", FakePredictionStore(stored), FakeChallengeStore([])
        )
        self.assertIsNone(result["current_value"])
        self.assertFalse(result["breached"])

    def test_uses_latest_stored_prediction_not_oldest(self):
        # list_predictions_for_service is DESC by created_at -- index 0 is latest.
        stored = [
            {"id": "PRED-LATEST", "result": {"predictions": [{"confidence": 0.95}]}},
            {"id": "PRED-OLD", "result": {"predictions": [{"confidence": 0.1}]}},
        ]
        result = self.agent.check_trigger(
            _prediction_trigger(threshold=0.5), "svc-1", "t-1",
            FakePredictionStore(stored), FakeChallengeStore([]),
        )
        self.assertEqual(result["checked_against"], "PRED-LATEST")
        self.assertEqual(result["current_value"], 0.95)

    def test_challenge_severity_no_stored_challenge(self):
        result = self.agent.check_trigger(
            _challenge_trigger(), "svc-1", "t-1", FakePredictionStore([]), FakeChallengeStore([])
        )
        self.assertIsNone(result["current_value"])
        self.assertFalse(result["breached"])
        self.assertIn("No stored Challenge result", result["evidence"])

    def test_challenge_severity_vulnerability_not_recurred(self):
        stored = [{"id": "CHAL-1", "result": {"vulnerabilities": [
            {"vulnerability_id": "OTHER_ID", "severity": 90.0},
        ]}}]
        result = self.agent.check_trigger(
            _challenge_trigger(source_vulnerability_id="V1"), "svc-1", "t-1",
            FakePredictionStore([]), FakeChallengeStore(stored),
        )
        self.assertIsNone(result["current_value"])
        self.assertFalse(result["breached"])
        self.assertIn("did not recur", result["evidence"])

    def test_challenge_severity_breached(self):
        stored = [{"id": "CHAL-1", "result": {"vulnerabilities": [
            {"vulnerability_id": "V1", "severity": 80.0},
        ]}}]
        result = self.agent.check_trigger(
            _challenge_trigger(threshold=60.0, source_vulnerability_id="V1"), "svc-1", "t-1",
            FakePredictionStore([]), FakeChallengeStore(stored),
        )
        self.assertEqual(result["current_value"], 80.0)
        self.assertTrue(result["breached"])
        self.assertEqual(result["checked_against"], "CHAL-1")

    def test_challenge_severity_not_breached(self):
        stored = [{"id": "CHAL-1", "result": {"vulnerabilities": [
            {"vulnerability_id": "V1", "severity": 40.0},
        ]}}]
        result = self.agent.check_trigger(
            _challenge_trigger(threshold=60.0, source_vulnerability_id="V1"), "svc-1", "t-1",
            FakePredictionStore([]), FakeChallengeStore(stored),
        )
        self.assertFalse(result["breached"])

    def test_unknown_watch_metric_never_breaches(self):
        trigger = _prediction_trigger()
        trigger["watch_metric"] = "something_invented"
        result = self.agent.check_trigger(
            trigger, "svc-1", "t-1", FakePredictionStore([]), FakeChallengeStore([])
        )
        self.assertFalse(result["breached"])
        self.assertIn("Unknown watch_metric", result["evidence"])

    def test_run_produces_one_check_per_trigger_deterministically(self):
        stored_prediction = [{"id": "PRED-1", "result": {"predictions": [{"confidence": 0.9}]}}]
        stored_challenge = [{"id": "CHAL-1", "result": {"vulnerabilities": [
            {"vulnerability_id": "V1", "severity": 80.0},
        ]}}]
        prevention_result = {"triggers": [
            _prediction_trigger(trigger_id="A", threshold=0.5),
            _challenge_trigger(trigger_id="B", threshold=60.0, source_vulnerability_id="V1"),
        ]}
        result_a = self.agent.run(
            prevention_result, "svc-1", "t-1",
            FakePredictionStore(stored_prediction), FakeChallengeStore(stored_challenge),
        )
        result_b = self.agent.run(
            prevention_result, "svc-1", "t-1",
            FakePredictionStore(stored_prediction), FakeChallengeStore(stored_challenge),
        )
        self.assertEqual(len(result_a["checks"]), 2)
        # Strip generated_at (a timestamp) before comparing for determinism.
        checks_a = [{k: v for k, v in c.items()} for c in result_a["checks"]]
        checks_b = [{k: v for k, v in c.items()} for c in result_b["checks"]]
        self.assertEqual(checks_a, checks_b)


class AlertStateMachineTestCase(unittest.TestCase):
    """Integration tests against a real (temp, isolated) SQLite file:
    proves the TRIGGERED -> RESOLVED state machine and tenant
    isolation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)
        self.alert_store = AlertStore(database_path=self.runtime_store.database_path)
        self.tenant_id = self.runtime_store.default_tenant_id
        self.other_tenant_id = "other-tenant-id"

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_open_alert_initially(self):
        self.assertIsNone(self.alert_store.get_open_alert(self.tenant_id, "svc-1", "TRIG-1"))

    def test_create_alert_then_it_is_open(self):
        alert = self.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id="svc-1", prevention_id="PREV-1",
            trigger_id="TRIG-1", current_value=0.9, threshold_value=0.7,
            checked_against="PRED-1", evidence="stub evidence",
        )
        self.assertEqual(alert["status"], "TRIGGERED")
        self.assertIsNone(alert["resolved_at"])
        open_alert = self.alert_store.get_open_alert(self.tenant_id, "svc-1", "TRIG-1")
        self.assertEqual(open_alert["id"], alert["id"])

    def test_resolve_alert_closes_it(self):
        alert = self.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id="svc-1", prevention_id="PREV-1",
            trigger_id="TRIG-1", current_value=0.9, threshold_value=0.7,
            checked_against="PRED-1", evidence="stub evidence",
        )
        resolved = self.alert_store.resolve_alert(
            alert["id"], self.tenant_id, current_value=0.4,
            checked_against="PRED-2", evidence="no longer breached",
        )
        self.assertEqual(resolved["status"], "RESOLVED")
        self.assertIsNotNone(resolved["resolved_at"])
        self.assertIsNone(self.alert_store.get_open_alert(self.tenant_id, "svc-1", "TRIG-1"))

    def test_idempotent_no_duplicate_alert_while_still_breached(self):
        first = self.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id="svc-1", prevention_id="PREV-1",
            trigger_id="TRIG-1", current_value=0.9, threshold_value=0.7,
            checked_against="PRED-1", evidence="stub",
        )
        # Simulate the endpoint's own idempotency check: a second
        # breached check should reuse the same open alert, not create
        # a new one.
        still_open = self.alert_store.get_open_alert(self.tenant_id, "svc-1", "TRIG-1")
        self.assertEqual(still_open["id"], first["id"])
        all_alerts = self.alert_store.list_alerts_for_service("svc-1", self.tenant_id)
        self.assertEqual(len(all_alerts), 1)

    def test_tenant_isolation(self):
        self.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id="svc-1", prevention_id="PREV-1",
            trigger_id="TRIG-1", current_value=0.9, threshold_value=0.7,
            checked_against="PRED-1", evidence="stub",
        )
        self.assertIsNone(self.alert_store.get_open_alert(self.other_tenant_id, "svc-1", "TRIG-1"))
        self.assertEqual(
            self.alert_store.list_alerts_for_service("svc-1", self.other_tenant_id), []
        )

    def test_alerts_table_is_additive_other_tables_untouched(self):
        service_store = ServiceStore(database_path=self.runtime_store.database_path)
        prevention_store = PreventionStore(database_path=self.runtime_store.database_path)
        evolution_store = EvolutionStore(database_path=self.runtime_store.database_path)
        challenge_store = ChallengeStore(database_path=self.runtime_store.database_path)
        prediction_store = PredictionStore(database_path=self.runtime_store.database_path)
        simulation_store = SimulationStore(database_path=self.runtime_store.database_path)

        service = service_store.create_service(tenant_id=self.tenant_id, service_name="Svc")
        self.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id=service["id"], prevention_id="PREV-1",
            trigger_id="TRIG-1", current_value=0.9, threshold_value=0.7,
            checked_against="PRED-1", evidence="stub",
        )
        self.assertEqual(prevention_store.list_preventions_for_service(service["id"], self.tenant_id), [])
        self.assertEqual(evolution_store.list_evolutions_for_service(service["id"], self.tenant_id), [])
        self.assertEqual(challenge_store.list_challenges_for_service(service["id"], self.tenant_id), [])
        self.assertEqual(prediction_store.list_predictions_for_service(service["id"], self.tenant_id), [])
        self.assertEqual(simulation_store.list_scenarios_for_service(service["id"], self.tenant_id), [])


class MonitoringEndpointTestCase(unittest.TestCase):
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
            f"Monitoring Test Tenant {suffix}", f"monitoring-test-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Monitoring Test Admin", f"monitoring-test-{suffix}@test.local",
            role="entity_admin",
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

        other_suffix = uuid.uuid4().hex[:8]
        other_tenant = main_module.tenant_repository.create_tenant(
            f"Other Monitoring Tenant {other_suffix}", f"other-monitoring-tenant-{other_suffix}",
            status="ACTIVE",
        )
        other_user = main_module.tenant_repository.create_user(
            other_tenant["id"], "Other Admin", f"other-monitoring-{other_suffix}@test.local",
            role="entity_admin",
        )
        other_login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": other_user["email"], "credential": "zxr-demo-2026"},
        )
        cls.other_headers = {"Authorization": f"Bearer {other_login.json()['token']}"}
        cls.other_tenant_id = other_tenant["id"]

    def _service_with_full_chain(self, tenant_id, headers):
        service_payload = {
            "service_name": "Monitoring Endpoint Service",
            "description": "Renew a permit",
            "steps": ["Customer submits request", "Employee reviews and approves"],
        }
        analyze_response = self.client.post("/api/analyze", headers=headers, json=service_payload)
        self.assertEqual(analyze_response.status_code, 200)
        service_id = analyze_response.json()["service_id"]

        challenge_response = self.client.post(
            f"/api/services/{service_id}/challenges", headers=headers, json={}
        )
        self.assertEqual(challenge_response.status_code, 200)
        challenge_id = challenge_response.json()["challenge_id"]

        evolution_response = self.client.post(
            f"/api/services/{service_id}/evolutions", headers=headers,
            json={"challenge_id": challenge_id},
        )
        self.assertEqual(evolution_response.status_code, 200)
        evolution_id = evolution_response.json()["evolution_id"]

        prevention_response = self.client.post(
            f"/api/services/{service_id}/preventions", headers=headers,
            json={"evolution_id": evolution_id},
        )
        self.assertEqual(prevention_response.status_code, 200)
        prevention_id = prevention_response.json()["prevention_id"]

        return service_id, prevention_id

    def test_monitoring_check_on_unknown_service_returns_404(self):
        response = self.client.post(
            "/api/services/does-not-exist/monitoring-checks",
            headers=self.headers,
            json={"prevention_id": "does-not-matter"},
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_prevention_returns_404(self):
        service_id, _ = self._service_with_full_chain(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{service_id}/monitoring-checks",
            headers=self.headers,
            json={"prevention_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_prevention_is_treated_as_not_found(self):
        other_service_id, other_prevention_id = self._service_with_full_chain(
            self.other_tenant_id, self.other_headers
        )
        my_service_id, _ = self._service_with_full_chain(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{my_service_id}/monitoring-checks",
            headers=self.headers,  # a DIFFERENT tenant's token
            json={"prevention_id": other_prevention_id},
        )
        self.assertEqual(response.status_code, 404)

    def test_full_monitoring_check_and_alerts_list(self):
        service_id, prevention_id = self._service_with_full_chain(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{service_id}/monitoring-checks",
            headers=self.headers,
            json={"prevention_id": prevention_id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["prevention_id"], prevention_id)
        self.assertIn("checks", body)
        self.assertIn("score_methodology", body)
        for check in body["checks"]:
            self.assertIn(check["alert_action"], {"CREATED", "ALREADY_OPEN", "RESOLVED", "NO_ALERT"})

        list_response = self.client.get(f"/api/services/{service_id}/alerts", headers=self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertIsInstance(list_response.json()["alerts"], list)

    def test_alerts_list_is_tenant_isolated(self):
        my_service_id, my_prevention_id = self._service_with_full_chain(self.tenant_id, self.headers)
        self.client.post(
            f"/api/services/{my_service_id}/monitoring-checks", headers=self.headers,
            json={"prevention_id": my_prevention_id},
        )
        other_response = self.client.get(f"/api/services/{my_service_id}/alerts", headers=self.other_headers)
        # my_service_id doesn't even exist for the other tenant.
        self.assertEqual(other_response.status_code, 404)

    # =====================================================================
    # STORED ALERTS PRESENTATION FIX -- endpoint-level regression test
    # =====================================================================
    # Directly constructs two separate Prevention "runs" for the SAME
    # service, sharing the SAME trigger_id (exactly how a real
    # Challenge->Evolve->Prevent cycle repeated over time behaves,
    # since trigger_id is deterministic -- see agents/prevent_agent.py)
    # but with different threshold_value, so an alert exists from each
    # run -- then proves GET /alerts classifies and orders them
    # correctly through the real HTTP endpoint.
    def test_alerts_endpoint_separates_current_from_historical_run(self):
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Two Prevention Runs Service"
        )
        service_id = service["id"]

        challenge_1 = self.main_module.challenge_store.save_challenge(
            tenant_id=self.tenant_id, service_id=service_id,
            input_snapshot={}, result={"vulnerabilities": []},
        )
        evolution_1 = self.main_module.evolution_store.save_evolution(
            tenant_id=self.tenant_id, service_id=service_id, challenge_id=challenge_1["id"],
            input_snapshot={}, result={"proposals": []},
        )
        old_prevention = self.main_module.prevention_store.save_prevention(
            tenant_id=self.tenant_id, service_id=service_id, evolution_id=evolution_1["id"],
            input_snapshot={}, result={"triggers": []},
        )
        old_alert = self.main_module.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id=service_id, prevention_id=old_prevention["id"],
            trigger_id="SLA_FRAGILITY:PROPOSAL-1", current_value=50.0, threshold_value=40.0,
            checked_against="CHAL-OLD", evidence="Old run: severity 50 against threshold 40.",
        )
        # The old alert must be RESOLVED so a fresh TRIGGERED row can
        # exist for the same trigger_id under the new run (matches the
        # real create_monitoring_check state machine, unchanged here).
        self.main_module.alert_store.resolve_alert(
            old_alert["id"], self.tenant_id, current_value=10.0,
            checked_against="CHAL-OLD-2", evidence="Old run: recovered.",
        )

        challenge_2 = self.main_module.challenge_store.save_challenge(
            tenant_id=self.tenant_id, service_id=service_id,
            input_snapshot={}, result={"vulnerabilities": []},
        )
        evolution_2 = self.main_module.evolution_store.save_evolution(
            tenant_id=self.tenant_id, service_id=service_id, challenge_id=challenge_2["id"],
            input_snapshot={}, result={"proposals": []},
        )
        new_prevention = self.main_module.prevention_store.save_prevention(
            tenant_id=self.tenant_id, service_id=service_id, evolution_id=evolution_2["id"],
            input_snapshot={}, result={"triggers": []},
        )
        new_alert = self.main_module.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id=service_id, prevention_id=new_prevention["id"],
            trigger_id="SLA_FRAGILITY:PROPOSAL-1", current_value=25.0, threshold_value=20.0,
            checked_against="CHAL-NEW", evidence="New run: severity 25 against threshold 20.",
        )

        response = self.client.get(f"/api/services/{service_id}/alerts", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        alerts = response.json()["alerts"]
        self.assertEqual(len(alerts), 2)  # both retained -- nothing deleted

        by_id = {a["id"]: a for a in alerts}
        current = by_id[new_alert["id"]]
        historical = by_id[old_alert["id"]]

        # 1/2. Current vs historical classification.
        self.assertTrue(current["is_current"])
        self.assertFalse(current["is_historical"])
        self.assertFalse(historical["is_current"])
        self.assertTrue(historical["is_historical"])
        self.assertEqual(current["current_context_id"], new_prevention["id"])
        self.assertEqual(historical["current_context_id"], new_prevention["id"])

        # Metadata: source_prevention_id / source_challenge_id.
        self.assertEqual(current["source_prevention_id"], new_prevention["id"])
        self.assertEqual(current["source_challenge_id"], challenge_2["id"])
        self.assertEqual(historical["source_prevention_id"], old_prevention["id"])
        self.assertEqual(historical["source_challenge_id"], challenge_1["id"])

        # 5. Current alerts appear first.
        self.assertEqual(alerts[0]["id"], new_alert["id"])
        self.assertEqual(alerts[1]["id"], old_alert["id"])

        # 8. Values never altered by this fix -- the old alert still
        # shows its own real 50/40, the new one its own real 25/20;
        # neither was recomputed, rewritten, or mixed with the other.
        self.assertEqual(historical["current_value"], 10.0)  # its own resolved value
        self.assertEqual(historical["threshold_value"], 40.0)
        self.assertEqual(current["current_value"], 25.0)
        self.assertEqual(current["threshold_value"], 20.0)

    def test_alerts_endpoint_two_runs_tenant_isolated(self):
        # 7. Tenant isolation for the classified/reordered response,
        # not just the raw list.
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Tenant Isolation Two Runs Service"
        )
        challenge = self.main_module.challenge_store.save_challenge(
            tenant_id=self.tenant_id, service_id=service["id"], input_snapshot={}, result={},
        )
        evolution = self.main_module.evolution_store.save_evolution(
            tenant_id=self.tenant_id, service_id=service["id"], challenge_id=challenge["id"],
            input_snapshot={}, result={},
        )
        prevention = self.main_module.prevention_store.save_prevention(
            tenant_id=self.tenant_id, service_id=service["id"], evolution_id=evolution["id"],
            input_snapshot={}, result={},
        )
        self.main_module.alert_store.create_alert(
            tenant_id=self.tenant_id, service_id=service["id"], prevention_id=prevention["id"],
            trigger_id="TRIG-X", current_value=25.0, threshold_value=20.0,
            checked_against="CHAL-X", evidence="stub",
        )
        response = self.client.get(f"/api/services/{service['id']}/alerts", headers=self.other_headers)
        self.assertEqual(response.status_code, 404)

    def test_rerunning_monitoring_check_endpoint_does_not_corrupt_prior_alert_history(self):
        # Requirement 6 (Stored Alerts presentation audit): drives the
        # REAL create_monitoring_check endpoint twice for the same
        # service -- once under an initial Prevention run, then again
        # under a fresh Prevention run -- and proves the first run's
        # alert row is still present, unchanged, and correctly
        # reclassified as historical once a newer run exists, rather
        # than being dropped, overwritten, or merged.
        service_id, prevention_id_1 = self._service_with_full_chain(self.tenant_id, self.headers)

        first_check = self.client.post(
            f"/api/services/{service_id}/monitoring-checks", headers=self.headers,
            json={"prevention_id": prevention_id_1},
        )
        self.assertEqual(first_check.status_code, 200)

        alerts_after_first_run = self.client.get(
            f"/api/services/{service_id}/alerts", headers=self.headers
        ).json()["alerts"]
        first_run_alert_ids = {a["id"] for a in alerts_after_first_run}

        # Build a second, independent Challenge -> Evolve -> Prevent
        # chain for the SAME service (a real "re-run"), then run
        # Monitoring again under the new Prevention run.
        challenge_2 = self.client.post(
            f"/api/services/{service_id}/challenges", headers=self.headers, json={}
        )
        self.assertEqual(challenge_2.status_code, 200)
        evolution_2 = self.client.post(
            f"/api/services/{service_id}/evolutions", headers=self.headers,
            json={"challenge_id": challenge_2.json()["challenge_id"]},
        )
        self.assertEqual(evolution_2.status_code, 200)
        prevention_2 = self.client.post(
            f"/api/services/{service_id}/preventions", headers=self.headers,
            json={"evolution_id": evolution_2.json()["evolution_id"]},
        )
        self.assertEqual(prevention_2.status_code, 200)
        prevention_id_2 = prevention_2.json()["prevention_id"]

        second_check = self.client.post(
            f"/api/services/{service_id}/monitoring-checks", headers=self.headers,
            json={"prevention_id": prevention_id_2},
        )
        self.assertEqual(second_check.status_code, 200)

        alerts_after_second_run = self.client.get(
            f"/api/services/{service_id}/alerts", headers=self.headers
        ).json()["alerts"]

        # Every alert row created by the first run is still present --
        # re-running Monitoring never dropped or overwrote them.
        surviving_ids = {a["id"] for a in alerts_after_second_run}
        self.assertTrue(first_run_alert_ids.issubset(surviving_ids))

        # Any alert row still tracing back to the first Prevention run
        # is now correctly historical, never current -- the second
        # run's own Prevention id is the only current_context_id.
        for alert in alerts_after_second_run:
            if alert["source_prevention_id"] == prevention_id_1:
                self.assertFalse(alert["is_current"])
                self.assertTrue(alert["is_historical"])
            self.assertEqual(alert["current_context_id"], prevention_id_2)


class AlertClassificationUnitTestCase(unittest.TestCase):
    """Pure, DB-free unit tests for the Stored Alerts presentation fix
    (core/alert_store.py's determine_current_prevention_id /
    classify_and_order_alerts) -- proves the classification/ordering
    logic itself without needing the HTTP layer or a real database."""

    def _alert(self, alert_id, prevention_id, created_at, **extra):
        return {
            "id": alert_id, "tenant_id": "t-1", "service_id": "svc-1",
            "prevention_id": prevention_id, "trigger_id": "TRIG-1", "status": "TRIGGERED",
            "current_value": 1.0, "threshold_value": 1.0, "checked_against": "CHAL-1",
            "evidence": "stub", "created_at": created_at, "updated_at": created_at,
            "resolved_at": None, **extra,
        }

    def test_determine_current_prevention_id_uses_first_entry(self):
        preventions = [{"id": "PREV-NEW"}, {"id": "PREV-OLD"}]  # DESC by created_at, as the store returns
        self.assertEqual(determine_current_prevention_id(preventions), "PREV-NEW")

    def test_determine_current_prevention_id_none_when_no_preventions(self):
        self.assertIsNone(determine_current_prevention_id([]))

    def test_latest_run_alert_classified_as_current(self):
        alerts = [self._alert("A-NEW", "PREV-NEW", "2026-01-02T00:00:00Z")]
        classified = classify_and_order_alerts(alerts, current_prevention_id="PREV-NEW")
        self.assertTrue(classified[0]["is_current"])
        self.assertFalse(classified[0]["is_historical"])

    def test_older_run_alert_classified_as_historical(self):
        alerts = [self._alert("A-OLD", "PREV-OLD", "2026-01-01T00:00:00Z")]
        classified = classify_and_order_alerts(alerts, current_prevention_id="PREV-NEW")
        self.assertFalse(classified[0]["is_current"])
        self.assertTrue(classified[0]["is_historical"])

    def test_historical_alerts_are_retained_not_dropped(self):
        alerts = [
            self._alert("A-NEW", "PREV-NEW", "2026-01-02T00:00:00Z"),
            self._alert("A-OLD", "PREV-OLD", "2026-01-01T00:00:00Z"),
        ]
        classified = classify_and_order_alerts(alerts, current_prevention_id="PREV-NEW")
        self.assertEqual({a["id"] for a in classified}, {"A-NEW", "A-OLD"})

    def test_historical_alert_never_marked_current_even_if_it_sorts_first_in_input(self):
        # Input order deliberately reversed from created_at DESC to
        # prove classification is driven by prevention_id, not by
        # position in the input list.
        alerts = [
            self._alert("A-OLD", "PREV-OLD", "2026-01-01T00:00:00Z"),
            self._alert("A-NEW", "PREV-NEW", "2026-01-02T00:00:00Z"),
        ]
        classified = classify_and_order_alerts(alerts, current_prevention_id="PREV-NEW")
        by_id = {a["id"]: a for a in classified}
        self.assertFalse(by_id["A-OLD"]["is_current"])
        self.assertTrue(by_id["A-NEW"]["is_current"])

    def test_current_alerts_returned_first(self):
        alerts = [
            self._alert("A-OLD-1", "PREV-OLD", "2026-01-03T00:00:00Z"),  # newest by time, still historical
            self._alert("A-NEW-1", "PREV-NEW", "2026-01-02T00:00:00Z"),
            self._alert("A-NEW-2", "PREV-NEW", "2026-01-01T00:00:00Z"),
            self._alert("A-OLD-2", "PREV-OLD", "2025-12-31T00:00:00Z"),
        ]
        classified = classify_and_order_alerts(alerts, current_prevention_id="PREV-NEW")
        ids_in_order = [a["id"] for a in classified]
        self.assertEqual(ids_in_order, ["A-NEW-1", "A-NEW-2", "A-OLD-1", "A-OLD-2"])
        # Relative (already created_at DESC) order preserved WITHIN
        # each group -- never re-sorted by this fix.

    def test_no_prevention_run_yet_means_nothing_is_current(self):
        alerts = [self._alert("A-1", "PREV-1", "2026-01-01T00:00:00Z")]
        classified = classify_and_order_alerts(alerts, current_prevention_id=None)
        self.assertFalse(classified[0]["is_current"])
        self.assertTrue(classified[0]["is_historical"])
        self.assertIsNone(classified[0]["current_context_id"])

    def test_source_challenge_id_resolved_via_mapping(self):
        alerts = [self._alert("A-1", "PREV-1", "2026-01-01T00:00:00Z")]
        classified = classify_and_order_alerts(
            alerts, current_prevention_id="PREV-1",
            prevention_to_challenge_id={"PREV-1": "CHAL-1"},
        )
        self.assertEqual(classified[0]["source_challenge_id"], "CHAL-1")

    def test_source_challenge_id_none_when_unresolvable(self):
        alerts = [self._alert("A-1", "PREV-1", "2026-01-01T00:00:00Z")]
        classified = classify_and_order_alerts(alerts, current_prevention_id="PREV-1")
        self.assertIsNone(classified[0]["source_challenge_id"])

    def test_original_alert_fields_untouched(self):
        alerts = [self._alert("A-1", "PREV-1", "2026-01-01T00:00:00Z",
                               current_value=25.0, threshold_value=20.0, status="TRIGGERED")]
        classified = classify_and_order_alerts(alerts, current_prevention_id="PREV-1")
        self.assertEqual(classified[0]["current_value"], 25.0)
        self.assertEqual(classified[0]["threshold_value"], 20.0)
        self.assertEqual(classified[0]["status"], "TRIGGERED")
        self.assertEqual(classified[0]["trigger_id"], "TRIG-1")


if __name__ == "__main__":
    unittest.main()
