"""Focused tests for the Evolve capability (Step 4 of the ZERO X-RAY
-> Government Future Engine evolution): agents/evolve_agent.py,
core/evolution_store.py, and the POST/GET
/api/services/{service_id}/evolutions endpoints.

Isolated the same way the other focused test files are: pure unit
tests where possible, temp-directory SQLite for store integration,
never a call into agents/orchestrator.py or graph/workflow.py.
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

from agents.evolve_agent import EvolveAgent
from core.evolution_store import EvolutionStore
from core.challenge_store import ChallengeStore
from core.prediction_store import PredictionStore
from core.runtime_store import RuntimeStore
from core.service_store import ServiceStore
from core.simulation_store import SimulationStore
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


def _vulnerability(vulnerability_type, target, severity=80.0, severity_basis="",
                    evidence=None, vulnerability_id=None):
    return {
        "vulnerability_id": vulnerability_id or f"{vulnerability_type}:{target}",
        "vulnerability_type": vulnerability_type,
        "target": target,
        "source_case_ids": ["CASE-1"],
        "severity": severity,
        "severity_basis": severity_basis,
        "evidence": evidence if evidence is not None else [
            {"type": "ASSUMPTION", "reference_id": "CASE-1", "detail": "likelihood=1.0 (ASSUMPTION_OR_VARIABLE)"},
            {"type": "FACT", "reference_id": "CASE-1", "detail": "2 of 2 customer-facing step(s) affected"},
        ],
        "explanation": "stub",
        "explanation_source": "template",
    }


def _challenge_output(vulnerabilities):
    return {
        "generated_at": "now",
        "cases_executed": [],
        "vulnerabilities": vulnerabilities,
        "grounding_summary": {"fact_count": 1, "prediction_count": 0, "assumption_count": 1},
        "score_methodology": SCORE_METHODOLOGY_MARKER,
    }


class EvolutionTypeSelectionTestCase(unittest.TestCase):
    """Pure unit tests -- no database, no LLM. Prove each of the 5
    evolution types fires under its exact documented condition and
    nothing else."""

    def setUp(self):
        self.agent = EvolveAgent(llm=None)
        self.graph = _sample_graph()

    def test_single_point_of_failure_on_integration_maps_to_add_redundancy(self):
        vulnerability = _vulnerability(
            "SINGLE_POINT_OF_FAILURE", "INTEGRATION-001",
            severity_basis="2 of 4 steps affected (ratio 0.5 >= threshold 0.5) when INTEGRATION-001 fails.",
        )
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(result["proposals"][0]["evolution_type"], "ADD_REDUNDANCY")
        self.assertEqual(result["skipped_vulnerabilities"], [])

    def test_single_point_of_failure_on_step_maps_to_decouple_dependency(self):
        vulnerability = _vulnerability(
            "SINGLE_POINT_OF_FAILURE", "STEP-1",
            severity_basis="4 of 4 steps affected (ratio 1.0 >= threshold 0.5) when STEP-1 fails.",
        )
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["evolution_type"], "DECOUPLE_DEPENDENCY")

    def test_cascading_failure_path_maps_to_decouple_dependency(self):
        vulnerability = _vulnerability(
            "CASCADING_FAILURE_PATH", "STEP-1",
            severity_basis="Worst observed cascade: failing STEP-1 blocked 4 step(s), the highest of any EXHAUSTIVE_STEP_FAILURE case.",
        )
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["evolution_type"], "DECOUPLE_DEPENDENCY")

    def test_critical_path_exposure_maps_to_decouple_dependency_but_no_exposure_after(self):
        vulnerability = _vulnerability(
            "CRITICAL_PATH_EXPOSURE", "STEP-2",
            severity_basis="STEP-2 was the top bottleneck in 2 distinct cases (>= threshold 2).",
        )
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        proposal = result["proposals"][0]
        self.assertEqual(proposal["evolution_type"], "DECOUPLE_DEPENDENCY")
        # No affected-step count in this basis text -> data doesn't support an estimate.
        self.assertIsNone(proposal["exposure_after_estimate"])

    def test_last_step_has_no_downstream_and_is_skipped(self):
        vulnerability = _vulnerability("SINGLE_POINT_OF_FAILURE", "STEP-4", severity_basis="")
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"], [])
        self.assertEqual(len(result["skipped_vulnerabilities"]), 1)
        self.assertIn("no downstream", result["skipped_vulnerabilities"][0]["reason"])

    def test_sla_fragility_maps_to_add_sla_safeguard(self):
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-3")
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["evolution_type"], "ADD_SLA_SAFEGUARD")

    def test_demand_fragility_on_customer_facing_step_maps_to_add_capacity_buffer(self):
        vulnerability = _vulnerability("DEMAND_FRAGILITY", "STEP-1")  # CUSTOMER type
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["evolution_type"], "ADD_CAPACITY_BUFFER")

    def test_demand_fragility_on_system_step_is_skipped(self):
        vulnerability = _vulnerability("DEMAND_FRAGILITY", "STEP-2")  # SYSTEM type
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"], [])
        self.assertEqual(len(result["skipped_vulnerabilities"]), 1)

    def test_customer_facing_exposure_maps_to_add_citizen_safeguard(self):
        vulnerability = _vulnerability("CUSTOMER_FACING_EXPOSURE", "STEP-3")  # HUMAN type
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["evolution_type"], "ADD_CITIZEN_SAFEGUARD")

    def test_unknown_target_is_skipped_not_crashed(self):
        vulnerability = _vulnerability("SINGLE_POINT_OF_FAILURE", "STEP-DOES-NOT-EXIST")
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"], [])
        self.assertEqual(len(result["skipped_vulnerabilities"]), 1)
        self.assertIn("no longer exists", result["skipped_vulnerabilities"][0]["reason"])

    def test_empty_challenge_output_produces_nothing(self):
        result = self.agent.run(_challenge_output([]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"], [])
        self.assertEqual(result["skipped_vulnerabilities"], [])


class ProtectedStepHandlingTestCase(unittest.TestCase):
    """Proves the protected flag is set correctly and that NO
    evolution_type in the closed set ever removes/retypes/reorders a
    protected (HUMAN-type) step -- a structural invariant check, not
    just a flag check."""

    def setUp(self):
        self.agent = EvolveAgent(llm=None)
        self.graph = _sample_graph()

    def test_human_type_step_target_is_marked_protected(self):
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-3")  # HUMAN
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertTrue(result["proposals"][0]["protected"])

    def test_non_human_type_step_target_is_not_protected(self):
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-2")  # SYSTEM
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertFalse(result["proposals"][0]["protected"])

    def test_integration_target_is_never_marked_protected(self):
        vulnerability = _vulnerability("SINGLE_POINT_OF_FAILURE", "INTEGRATION-001", severity_basis="")
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertFalse(result["proposals"][0]["protected"])

    def test_no_proposal_ever_changes_step_name_or_type_in_proposed_state(self):
        """Every proposed_state for a step-targeting evolution_type
        must explicitly say the step 'remains unchanged' or
        equivalent -- the additive-only guarantee, checked at the
        content level, not just by convention."""
        vulnerabilities = [
            _vulnerability("SLA_FRAGILITY", "STEP-3"),
            _vulnerability("DEMAND_FRAGILITY", "STEP-1"),
            _vulnerability("CUSTOMER_FACING_EXPOSURE", "STEP-3", vulnerability_id="CFE:STEP-3"),
        ]
        result = self.agent.run(_challenge_output(vulnerabilities), self.graph, "CHAL-1")
        for proposal in result["proposals"]:
            self.assertIn("remains", proposal["proposed_state"])


class ExposureCalculationTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = EvolveAgent(llm=None)
        self.graph = _sample_graph()

    def test_exposure_before_equals_source_severity_exactly(self):
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-3", severity=63.5)
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["exposure_before"], 63.5)

    def test_non_decouple_types_never_get_exposure_after_estimate(self):
        for vtype, target in [
            ("SLA_FRAGILITY", "STEP-3"),
            ("DEMAND_FRAGILITY", "STEP-1"),
            ("CUSTOMER_FACING_EXPOSURE", "STEP-3"),
        ]:
            vulnerability = _vulnerability(vtype, target, vulnerability_id=f"{vtype}:{target}")
            result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
            self.assertIsNone(result["proposals"][0]["exposure_after_estimate"])

    def test_decouple_with_extractable_count_computes_bounded_estimate(self):
        vulnerability = _vulnerability(
            "SINGLE_POINT_OF_FAILURE", "STEP-1", severity=100.0,
            severity_basis="4 of 4 steps affected (ratio 1.0 >= threshold 0.5) when STEP-1 fails.",
        )
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        proposal = result["proposals"][0]
        self.assertIsNotNone(proposal["exposure_after_estimate"])
        # 4 affected -> 1 affected out of 4 total steps: ratio shrinks 4x -> 100/4 = 25.0
        self.assertEqual(proposal["exposure_after_estimate"], 25.0)
        self.assertLessEqual(proposal["exposure_after_estimate"], proposal["exposure_before"])
        self.assertIsNotNone(proposal["exposure_calculation_basis"])

    def test_decouple_without_extractable_count_leaves_estimate_null(self):
        vulnerability = _vulnerability(
            "CASCADING_FAILURE_PATH", "STEP-1", severity_basis="no numbers here at all"
        )
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertIsNone(result["proposals"][0]["exposure_after_estimate"])


class GroundingRelayTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = EvolveAgent(llm=None)
        self.graph = _sample_graph()

    def test_source_evidence_is_relayed_unchanged(self):
        evidence = [{"type": "PREDICTION", "reference_id": "PRED-1", "detail": "confidence=0.9"}]
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-3", evidence=evidence)
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        grounding = result["proposals"][0]["grounding"]
        self.assertIn(evidence[0], grounding)

    def test_exposure_after_estimate_adds_one_assumption_entry(self):
        vulnerability = _vulnerability(
            "SINGLE_POINT_OF_FAILURE", "STEP-1", severity=100.0,
            severity_basis="4 of 4 steps affected (ratio 1.0 >= threshold 0.5) when STEP-1 fails.",
        )
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        assumption_entries = [e for e in result["proposals"][0]["grounding"] if "proportional" in e["detail"]]
        self.assertEqual(len(assumption_entries), 1)
        self.assertEqual(assumption_entries[0]["type"], "ASSUMPTION")


class DeterminismAndLlmTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = EvolveAgent(llm=None)
        self.graph = _sample_graph()

    def test_repeated_run_is_identical(self):
        vulnerabilities = [
            _vulnerability("SLA_FRAGILITY", "STEP-3"),
            _vulnerability("DEMAND_FRAGILITY", "STEP-1"),
        ]
        result_a = self.agent.run(_challenge_output(vulnerabilities), self.graph, "CHAL-1")
        result_b = self.agent.run(_challenge_output(vulnerabilities), self.graph, "CHAL-1")
        self.assertEqual(result_a["proposals"], result_b["proposals"])
        self.assertEqual(result_a["skipped_vulnerabilities"], result_b["skipped_vulnerabilities"])

    def test_score_methodology_present(self):
        result = self.agent.run(_challenge_output([]), self.graph, "CHAL-1")
        self.assertEqual(result["score_methodology"], SCORE_METHODOLOGY_MARKER)

    def test_llm_cannot_fabricate_new_facts(self):
        class FabricatingLLM:
            def generate(self, *args, **kwargs):
                return "This affects 9999 citizens and costs $1000000."

        agent = EvolveAgent(llm=FabricatingLLM())
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-3")
        result = agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        proposal = result["proposals"][0]
        self.assertEqual(proposal["explanation_source"], "template")
        self.assertNotIn("9999", proposal["explanation"])

    def test_no_llm_configured_always_uses_template(self):
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-3")
        result = self.agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["explanation_source"], "template")

    def test_llm_explanation_accepted_when_grounded(self):
        class HonestLLM:
            def generate(self, *args, **kwargs):
                return "This step remains unchanged, with a new monitored SLA threshold."

        agent = EvolveAgent(llm=HonestLLM())
        vulnerability = _vulnerability("SLA_FRAGILITY", "STEP-3")
        result = agent.run(_challenge_output([vulnerability]), self.graph, "CHAL-1")
        self.assertEqual(result["proposals"][0]["explanation_source"], "ai")


class EvolutionStoreIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)
        self.service_store = ServiceStore(database_path=self.runtime_store.database_path)
        self.evolution_store = EvolutionStore(database_path=self.runtime_store.database_path)
        self.challenge_store = ChallengeStore(database_path=self.runtime_store.database_path)
        self.prediction_store = PredictionStore(database_path=self.runtime_store.database_path)
        self.simulation_store = SimulationStore(database_path=self.runtime_store.database_path)
        self.tenant_id = self.runtime_store.default_tenant_id

    def tearDown(self):
        self._tmp.cleanup()

    def test_evolutions_table_is_additive_other_tables_untouched(self):
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Svc")
        saved = self.evolution_store.save_evolution(
            tenant_id=self.tenant_id, service_id=service["id"], challenge_id="CHAL-1",
            input_snapshot={"challenge_id": "CHAL-1"}, result={"proposals": []},
        )
        self.assertIsNotNone(saved)
        self.assertEqual(
            self.challenge_store.list_challenges_for_service(service["id"], self.tenant_id), []
        )
        self.assertEqual(
            self.prediction_store.list_predictions_for_service(service["id"], self.tenant_id), []
        )
        self.assertEqual(
            self.simulation_store.list_scenarios_for_service(service["id"], self.tenant_id), []
        )


class EvolveEndpointTestCase(unittest.TestCase):
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
            f"Evolve Test Tenant {suffix}", f"evolve-test-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Evolve Test Admin", f"evolve-test-{suffix}@test.local", role="entity_admin"
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

        other_suffix = uuid.uuid4().hex[:8]
        other_tenant = main_module.tenant_repository.create_tenant(
            f"Other Evolve Tenant {other_suffix}", f"other-evolve-tenant-{other_suffix}",
            status="ACTIVE",
        )
        other_user = main_module.tenant_repository.create_user(
            other_tenant["id"], "Other Admin", f"other-evolve-{other_suffix}@test.local",
            role="entity_admin",
        )
        other_login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": other_user["email"], "credential": "zxr-demo-2026"},
        )
        cls.other_headers = {"Authorization": f"Bearer {other_login.json()['token']}"}
        cls.other_tenant_id = other_tenant["id"]

    def _service_with_challenge(self, tenant_id, headers):
        service_payload = {
            "service_name": "Evolve Endpoint Service",
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
        return service_id, challenge_response.json()["challenge_id"]

    def test_evolution_on_unknown_service_returns_404(self):
        response = self.client.post(
            "/api/services/does-not-exist/evolutions",
            headers=self.headers,
            json={"challenge_id": "does-not-matter"},
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_challenge_returns_404(self):
        service_id, _ = self._service_with_challenge(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{service_id}/evolutions",
            headers=self.headers,
            json={"challenge_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_challenge_is_treated_as_not_found(self):
        other_service_id, other_challenge_id = self._service_with_challenge(
            self.other_tenant_id, self.other_headers
        )
        my_service_id, _ = self._service_with_challenge(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{my_service_id}/evolutions",
            headers=self.headers,  # a DIFFERENT tenant's token
            json={"challenge_id": other_challenge_id},
        )
        self.assertEqual(response.status_code, 404)

    def test_full_evolution_run_and_list(self):
        service_id, challenge_id = self._service_with_challenge(self.tenant_id, self.headers)
        response = self.client.post(
            f"/api/services/{service_id}/evolutions",
            headers=self.headers,
            json={"challenge_id": challenge_id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("evolution_id", body)
        self.assertEqual(body["challenge_id"], challenge_id)
        self.assertIn("proposals", body)
        self.assertIn("skipped_vulnerabilities", body)
        self.assertIn("score_methodology", body)

        list_response = self.client.get(f"/api/services/{service_id}/evolutions", headers=self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["evolutions"]), 1)


if __name__ == "__main__":
    unittest.main()
