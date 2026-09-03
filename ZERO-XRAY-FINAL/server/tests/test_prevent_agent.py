"""Focused tests for the Prevent capability (Step 5 of the ZERO
X-RAY -> Government Future Engine evolution): agents/prevent_agent.py,
core/prevention_store.py, and the POST/GET
/api/services/{service_id}/preventions endpoints.

Isolated the same way the other focused test files are: pure unit
tests where possible, temp-directory SQLite for store integration,
never a call into agents/orchestrator.py or graph/workflow.py, and
never a re-run of Evolve/Challenge/Simulate/Predict.
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

from agents.prevent_agent import PreventAgent, EARLY_WARNING_RATIO, TRIGGER_STATUS
from core.prevention_store import PreventionStore
from core.evolution_store import EvolutionStore
from core.challenge_store import ChallengeStore
from core.prediction_store import PredictionStore
from core.runtime_store import RuntimeStore
from core.service_store import ServiceStore
from core.simulation_store import SimulationStore
from core.score_methodology import SCORE_METHODOLOGY_MARKER


def _proposal(proposal_id="ADD_SLA_SAFEGUARD:X", exposure_before=80.0, protected=False,
              proposed_state="STEP-3 remains unchanged; an SLA safeguard is added.",
              grounding=None, fixes_vulnerability_id="SLA_FRAGILITY:STEP-3"):
    return {
        "proposal_id": proposal_id,
        "evolution_type": "ADD_SLA_SAFEGUARD",
        "fixes_vulnerability_id": fixes_vulnerability_id,
        "target": "STEP-3",
        "current_state": "STEP-3 has no monitored duration threshold.",
        "proposed_state": proposed_state,
        "protected": protected,
        "exposure_before": exposure_before,
        "exposure_after_estimate": None,
        "exposure_calculation_basis": None,
        "grounding": grounding if grounding is not None else [
            {"type": "FACT", "reference_id": "CASE-1", "detail": "2 of 2 customer-facing step(s) affected"},
        ],
        "explanation": "stub",
        "explanation_source": "template",
    }


def _evolve_output(proposals):
    return {
        "generated_at": "now",
        "challenge_id": "CHAL-1",
        "proposals": proposals,
        "skipped_vulnerabilities": [],
        "score_methodology": SCORE_METHODOLOGY_MARKER,
    }


class TriggerGenerationTestCase(unittest.TestCase):
    """Pure unit tests -- no database, no LLM."""

    def setUp(self):
        self.agent = PreventAgent(llm=None)

    def test_challenge_recurrence_trigger_always_generated_with_exposure(self):
        result = self.agent.run(_evolve_output([_proposal(exposure_before=80.0)]), "EVO-1")
        recurrence = [t for t in result["triggers"] if t["trigger_type"] == "CHALLENGE_RECURRENCE_TRIGGER"]
        self.assertEqual(len(recurrence), 1)
        self.assertEqual(recurrence[0]["threshold_value"], round(80.0 * EARLY_WARNING_RATIO, 2))

    def test_threshold_arithmetic_is_exact(self):
        result = self.agent.run(_evolve_output([_proposal(exposure_before=63.5)]), "EVO-1")
        recurrence = next(t for t in result["triggers"] if t["trigger_type"] == "CHALLENGE_RECURRENCE_TRIGGER")
        self.assertEqual(recurrence["threshold_value"], 50.8)  # 63.5 * 0.8
        self.assertIn("63.5", recurrence["threshold_basis"])
        self.assertIn("50.8", recurrence["threshold_basis"])

    def test_no_exposure_before_skips_the_proposal(self):
        proposal = _proposal()
        proposal["exposure_before"] = None
        result = self.agent.run(_evolve_output([proposal]), "EVO-1")
        self.assertEqual(result["triggers"], [])
        self.assertEqual(len(result["skipped_proposals"]), 1)
        self.assertEqual(result["skipped_proposals"][0]["proposal_id"], proposal["proposal_id"])

    def test_prediction_early_warning_trigger_generated_when_evidence_supports_it(self):
        grounding = [
            {"type": "PREDICTION", "reference_id": "CASE-1", "detail": "likelihood=0.9 (PREDICTION)"},
        ]
        result = self.agent.run(
            _evolve_output([_proposal(exposure_before=80.0, grounding=grounding)]), "EVO-1"
        )
        warning = [t for t in result["triggers"] if t["trigger_type"] == "PREDICTION_EARLY_WARNING_TRIGGER"]
        self.assertEqual(len(warning), 1)
        self.assertEqual(warning[0]["threshold_value"], round(0.9 * EARLY_WARNING_RATIO, 2))
        self.assertEqual(warning[0]["watch_metric"], "prediction_confidence")
        self.assertEqual(warning[0]["watch_scope"], "any Predict run for this service")

    def test_prediction_early_warning_trigger_absent_without_prediction_evidence(self):
        grounding = [
            {"type": "ASSUMPTION", "reference_id": "CASE-1", "detail": "some assumption detail"},
        ]
        result = self.agent.run(
            _evolve_output([_proposal(exposure_before=80.0, grounding=grounding)]), "EVO-1"
        )
        warning = [t for t in result["triggers"] if t["trigger_type"] == "PREDICTION_EARLY_WARNING_TRIGGER"]
        self.assertEqual(warning, [])
        # The CHALLENGE_RECURRENCE_TRIGGER must still be generated regardless.
        recurrence = [t for t in result["triggers"] if t["trigger_type"] == "CHALLENGE_RECURRENCE_TRIGGER"]
        self.assertEqual(len(recurrence), 1)

    def test_prediction_evidence_with_unparseable_likelihood_is_not_used(self):
        grounding = [
            {"type": "PREDICTION", "reference_id": "CASE-1", "detail": "no numeric likelihood here"},
        ]
        result = self.agent.run(
            _evolve_output([_proposal(exposure_before=80.0, grounding=grounding)]), "EVO-1"
        )
        warning = [t for t in result["triggers"] if t["trigger_type"] == "PREDICTION_EARLY_WARNING_TRIGGER"]
        self.assertEqual(warning, [])

    def test_empty_proposals_produces_empty_triggers(self):
        result = self.agent.run(_evolve_output([]), "EVO-1")
        self.assertEqual(result["triggers"], [])
        self.assertEqual(result["skipped_proposals"], [])


class ActionAndProtectionRelayTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = PreventAgent(llm=None)

    def test_action_if_triggered_exactly_matches_proposed_state(self):
        proposed_state = "STEP-3 remains unchanged; a very specific safeguard text is added here."
        result = self.agent.run(
            _evolve_output([_proposal(proposed_state=proposed_state)]), "EVO-1"
        )
        for trigger in result["triggers"]:
            self.assertEqual(trigger["action_if_triggered"], proposed_state)

    def test_protected_flag_relayed_unchanged_true(self):
        result = self.agent.run(_evolve_output([_proposal(protected=True)]), "EVO-1")
        for trigger in result["triggers"]:
            self.assertTrue(trigger["protected"])

    def test_protected_flag_relayed_unchanged_false(self):
        result = self.agent.run(_evolve_output([_proposal(protected=False)]), "EVO-1")
        for trigger in result["triggers"]:
            self.assertFalse(trigger["protected"])

    def test_status_is_always_defined(self):
        result = self.agent.run(_evolve_output([_proposal()]), "EVO-1")
        for trigger in result["triggers"]:
            self.assertEqual(trigger["status"], "DEFINED")
            self.assertEqual(trigger["status"], TRIGGER_STATUS)


class GroundingRelayTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = PreventAgent(llm=None)

    def test_source_grounding_is_relayed_unchanged(self):
        source_entry = {"type": "FACT", "reference_id": "CASE-1", "detail": "2 of 2 customer-facing step(s) affected"}
        result = self.agent.run(
            _evolve_output([_proposal(grounding=[source_entry])]), "EVO-1"
        )
        for trigger in result["triggers"]:
            self.assertIn(source_entry, trigger["grounding"])

    def test_threshold_gets_its_own_assumption_entry(self):
        result = self.agent.run(_evolve_output([_proposal()]), "EVO-1")
        for trigger in result["triggers"]:
            assumption_entries = [
                e for e in trigger["grounding"] if "EARLY_WARNING_RATIO" in e["detail"]
            ]
            self.assertEqual(len(assumption_entries), 1)
            self.assertEqual(assumption_entries[0]["type"], "ASSUMPTION")


class DeterminismAndLlmTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = PreventAgent(llm=None)

    def test_repeated_run_is_identical(self):
        proposals = [_proposal(proposal_id="P1", exposure_before=80.0),
                     _proposal(proposal_id="P2", exposure_before=40.0)]
        result_a = self.agent.run(_evolve_output(proposals), "EVO-1")
        result_b = self.agent.run(_evolve_output(proposals), "EVO-1")
        self.assertEqual(result_a["triggers"], result_b["triggers"])
        self.assertEqual(result_a["skipped_proposals"], result_b["skipped_proposals"])

    def test_score_methodology_present(self):
        result = self.agent.run(_evolve_output([]), "EVO-1")
        self.assertEqual(result["score_methodology"], SCORE_METHODOLOGY_MARKER)

    def test_llm_cannot_fabricate_new_facts(self):
        class FabricatingLLM:
            def generate(self, *args, **kwargs):
                return "This will cost $9999999 and affect 12345 citizens."

        agent = PreventAgent(llm=FabricatingLLM())
        result = agent.run(_evolve_output([_proposal()]), "EVO-1")
        trigger = result["triggers"][0]
        self.assertEqual(trigger["explanation_source"], "template")
        self.assertNotIn("9999999", trigger["explanation"])

    def test_no_llm_configured_always_uses_template(self):
        result = self.agent.run(_evolve_output([_proposal()]), "EVO-1")
        for trigger in result["triggers"]:
            self.assertEqual(trigger["explanation_source"], "template")

    def test_llm_explanation_accepted_when_grounded(self):
        class HonestLLM:
            def generate(self, *args, **kwargs):
                return "Watch this step's severity and apply the safeguard if it recurs."

        agent = PreventAgent(llm=HonestLLM())
        result = agent.run(_evolve_output([_proposal()]), "EVO-1")
        self.assertTrue(any(t["explanation_source"] == "ai" for t in result["triggers"]))


class PreventionStoreIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)
        self.service_store = ServiceStore(database_path=self.runtime_store.database_path)
        self.prevention_store = PreventionStore(database_path=self.runtime_store.database_path)
        self.evolution_store = EvolutionStore(database_path=self.runtime_store.database_path)
        self.challenge_store = ChallengeStore(database_path=self.runtime_store.database_path)
        self.prediction_store = PredictionStore(database_path=self.runtime_store.database_path)
        self.simulation_store = SimulationStore(database_path=self.runtime_store.database_path)
        self.tenant_id = self.runtime_store.default_tenant_id

    def tearDown(self):
        self._tmp.cleanup()

    def test_preventions_table_is_additive_other_tables_untouched(self):
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Svc")
        saved = self.prevention_store.save_prevention(
            tenant_id=self.tenant_id, service_id=service["id"], evolution_id="EVO-1",
            input_snapshot={"evolution_id": "EVO-1"}, result={"triggers": []},
        )
        self.assertIsNotNone(saved)
        self.assertEqual(
            self.evolution_store.list_evolutions_for_service(service["id"], self.tenant_id), []
        )
        self.assertEqual(
            self.challenge_store.list_challenges_for_service(service["id"], self.tenant_id), []
        )
        self.assertEqual(
            self.prediction_store.list_predictions_for_service(service["id"], self.tenant_id), []
        )
        self.assertEqual(
            self.simulation_store.list_scenarios_for_service(service["id"], self.tenant_id), []
        )


class PreventEndpointTestCase(unittest.TestCase):
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
            f"Prevent Test Tenant {suffix}", f"prevent-test-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Prevent Test Admin", f"prevent-test-{suffix}@test.local", role="entity_admin"
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

        other_suffix = uuid.uuid4().hex[:8]
        other_tenant = main_module.tenant_repository.create_tenant(
            f"Other Prevent Tenant {other_suffix}", f"other-prevent-tenant-{other_suffix}",
            status="ACTIVE",
        )
        other_user = main_module.tenant_repository.create_user(
            other_tenant["id"], "Other Admin", f"other-prevent-{other_suffix}@test.local",
            role="entity_admin",
        )
        other_login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": other_user["email"], "credential": "zxr-demo-2026"},
        )
        cls.other_headers = {"Authorization": f"Bearer {other_login.json()['token']}"}
        cls.other_tenant_id = other_tenant["id"]

    def _service_with_evolution(self, tenant_id, headers):
        service_payload = {
            "service_name": "Prevent Endpoint Service",
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

        return service_id, evolution_id

    def test_prevention_on_unknown_service_returns_404(self):
        response = self.client.post(
            "/api/services/does-not-exist/preventions",
            headers=self.headers,
            json={"evolution_id": "does-not-matter"},
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_evolution_returns_404(self):
        service_id, _ = self._service_with_evolution(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{service_id}/preventions",
            headers=self.headers,
            json={"evolution_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_evolution_is_treated_as_not_found(self):
        other_service_id, other_evolution_id = self._service_with_evolution(
            self.other_tenant_id, self.other_headers
        )
        my_service_id, _ = self._service_with_evolution(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{my_service_id}/preventions",
            headers=self.headers,  # a DIFFERENT tenant's token
            json={"evolution_id": other_evolution_id},
        )
        self.assertEqual(response.status_code, 404)

    def test_full_prevention_run_and_list(self):
        service_id, evolution_id = self._service_with_evolution(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{service_id}/preventions",
            headers=self.headers,
            json={"evolution_id": evolution_id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("prevention_id", body)
        self.assertEqual(body["evolution_id"], evolution_id)
        self.assertIn("triggers", body)
        self.assertIn("skipped_proposals", body)
        self.assertIn("score_methodology", body)
        for trigger in body["triggers"]:
            self.assertEqual(trigger["status"], "DEFINED")

        list_response = self.client.get(f"/api/services/{service_id}/preventions", headers=self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["preventions"]), 1)


if __name__ == "__main__":
    unittest.main()
