"""Focused tests for the Predict capability (Step 1 of the ZERO X-RAY
-> Government Future Engine evolution): agents/prediction_agent.py,
core/prediction_store.py, and the POST /api/services/{service_id}/predict
endpoint.

Deliberately isolated from the rest of the suite: these tests never
call agents/orchestrator.py or graph/workflow.py, and never assert
anything about the Current Journey -> Analysis -> Future Journey
pipeline (that remains covered by the existing test files, unchanged).

Every stored analysis/journey used here is inserted directly through
ServiceStore/RuntimeStore's own existing methods, into a fresh
temp-directory SQLite file -- never against the real server/data
database -- matching the isolation pattern already used by
tests/test_multi_tenant_phase1.py and tests/test_runtime_and_constraints.py.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:19999")  # deliberately unreachable
os.environ.setdefault("ZX_LLM_MODE", "ollama")

from agents.prediction_agent import PredictionAgent, fetch_journeys_for_service
from core.prediction_store import PredictionStore
from core.runtime_store import RuntimeStore
from core.service_store import ServiceStore


def _gap(standard_id, description, category="Documentation", gap_id="GAP-001"):
    return {
        "gap_id": gap_id,
        "standard_id": standard_id,
        "description": description,
        "category": category,
        "severity": "MEDIUM",
    }


def _analysis_result(gaps=None, friction_points=None):
    return {
        "gaps": {"gaps": gaps or []},
        "service_analysis": {"friction_points": friction_points or []},
    }


class PredictionAgentDeterminismTestCase(unittest.TestCase):
    """Pure unit tests of the deterministic aggregation logic -- no
    database, no LLM. These prove confidence/occurrence
    counts/data_sufficiency are plain Python arithmetic."""

    def setUp(self):
        self.agent = PredictionAgent(llm=None)  # no LLM at all -> template-only path

    def test_zero_analyses_is_insufficient_and_empty(self):
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [], "journeys": [],
        }
        result = self.agent.run(prediction_input)
        self.assertEqual(result["data_sufficiency"]["verdict"], "INSUFFICIENT")
        self.assertEqual(result["predictions"], [])

    def test_single_analysis_is_insufficient_even_with_gaps(self):
        """One analysis can never establish 'recurrence' -- the hard
        rule is that missing data must never be compensated for."""
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
            ],
            "journeys": [],
        }
        result = self.agent.run(prediction_input)
        self.assertEqual(result["data_sufficiency"]["verdict"], "INSUFFICIENT")
        self.assertEqual(result["predictions"], [])

    def test_recurring_gap_across_two_analyses_produces_prediction_with_correct_confidence(self):
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t1", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check", gap_id="GAP-001")]
                )},
                {"id": "an-2", "created_at": "t2", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check", gap_id="GAP-002")]
                )},
            ],
            "journeys": [],
        }
        result = self.agent.run(prediction_input)
        self.assertEqual(result["data_sufficiency"]["verdict"], "LIMITED")
        self.assertEqual(result["data_sufficiency"]["analyses_count"], 2)
        self.assertEqual(len(result["predictions"]), 1)
        prediction = result["predictions"][0]
        # 2 occurrences out of 2 analyses -> confidence must be exactly 1.0,
        # computed by code, not stated by an LLM.
        self.assertEqual(prediction["confidence"], 1.0)
        self.assertEqual(prediction["prediction_type"], "EVIDENCE_BASED")
        self.assertEqual(prediction["explanation_source"], "template")  # no LLM configured
        self.assertIn("2 of 2", prediction["confidence_basis"])

    def test_non_recurring_gap_is_dropped(self):
        """A gap seen only once (even across 3 analyses total) is not
        a recurring pattern and must not become a prediction."""
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t1", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
                {"id": "an-2", "created_at": "t2", "result": _analysis_result(gaps=[])},
                {"id": "an-3", "created_at": "t3", "result": _analysis_result(gaps=[])},
            ],
            "journeys": [],
        }
        result = self.agent.run(prediction_input)
        self.assertEqual(result["predictions"], [])
        self.assertEqual(result["data_sufficiency"]["verdict"], "LIMITED")

    def test_recurring_friction_point_across_four_analyses_is_sufficient(self):
        analyses = []
        for index in range(4):
            analyses.append({
                "id": f"an-{index}", "created_at": f"t{index}",
                "result": _analysis_result(friction_points=["Citizen must visit branch in person"]),
            })
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": analyses, "journeys": [],
        }
        result = self.agent.run(prediction_input)
        self.assertEqual(result["data_sufficiency"]["verdict"], "SUFFICIENT")
        self.assertEqual(len(result["predictions"]), 1)
        prediction = result["predictions"][0]
        self.assertEqual(prediction["category"], "CUSTOMER_FRICTION")
        self.assertEqual(prediction["confidence"], 1.0)

    def test_every_prediction_references_a_real_supplied_id(self):
        """Every signal's reference_id must trace back to an id that
        was actually present in the input (a real analysis_id here) --
        never a fabricated placeholder."""
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "REAL-ANALYSIS-ID-1", "created_at": "t1", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
                {"id": "REAL-ANALYSIS-ID-2", "created_at": "t2", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
            ],
            "journeys": [],
        }
        result = self.agent.run(prediction_input)
        supplied_ids = {"REAL-ANALYSIS-ID-1", "REAL-ANALYSIS-ID-2"}
        for prediction in result["predictions"]:
            for signal in prediction["signals"]:
                self.assertIn(signal["reference_id"], supplied_ids)

    def test_llm_explanation_rejected_when_it_invents_a_count(self):
        """Confidence/occurrence counts must never come from the LLM --
        if the LLM's phrasing invents a number of occurrences that
        doesn't match reality, it is discarded in favor of the
        deterministic template, not trusted."""

        class FabricatingLLM:
            def generate(self, *args, **kwargs):
                return "This has happened 99 times across many analyses."

        agent = PredictionAgent(llm=FabricatingLLM())
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t1", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
                {"id": "an-2", "created_at": "t2", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
            ],
            "journeys": [],
        }
        result = agent.run(prediction_input)
        prediction = result["predictions"][0]
        self.assertEqual(prediction["explanation_source"], "template")
        self.assertNotIn("99", prediction["explanation"])
        # The real, code-computed confidence is unaffected by the LLM's claim.
        self.assertEqual(prediction["confidence"], 1.0)

    def test_llm_explanation_accepted_when_it_matches_real_numbers(self):
        class HonestLLM:
            def generate(self, *args, **kwargs):
                return "This gap has recurred in 2 analyses for this service."

        agent = PredictionAgent(llm=HonestLLM())
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t1", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
                {"id": "an-2", "created_at": "t2", "result": _analysis_result(
                    gaps=[_gap("STD-01", "Missing digital ID check")]
                )},
            ],
            "journeys": [],
        }
        result = agent.run(prediction_input)
        prediction = result["predictions"][0]
        self.assertEqual(prediction["explanation_source"], "ai")


class PredictionStoreAndDbIntegrationTestCase(unittest.TestCase):
    """Integration tests against a real (temp, isolated) SQLite file:
    proves gather_input() correctly reads existing tables read-only,
    and PredictionStore correctly persists to its own additive table
    without touching any existing one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)
        self.service_store = ServiceStore(database_path=self.runtime_store.database_path)
        self.prediction_store = PredictionStore(database_path=self.runtime_store.database_path)
        self.tenant_id = self.runtime_store.default_tenant_id

    def tearDown(self):
        self._tmp.cleanup()

    def test_gather_input_reads_stored_analyses_for_service(self):
        service = self.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Renew Corporate P.O. Box"
        )
        self.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-1",
            result=_analysis_result(gaps=[_gap("STD-01", "Missing digital ID check")]),
        )
        self.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-2",
            result=_analysis_result(gaps=[_gap("STD-01", "Missing digital ID check")]),
        )

        agent = PredictionAgent(llm=None)
        prediction_input = agent.gather_input(
            service_id=service["id"], tenant_id=self.tenant_id,
            service_store=self.service_store, database_path=self.runtime_store.database_path,
        )
        self.assertEqual(len(prediction_input["analyses"]), 2)

        result = agent.run(prediction_input)
        self.assertEqual(len(result["predictions"]), 1)
        self.assertEqual(result["data_sufficiency"]["verdict"], "LIMITED")

    def test_fetch_journeys_for_service_is_read_only_and_scoped(self):
        service_a = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Service A")
        service_b = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Service B")

        blueprint_a = self.runtime_store.save_blueprint(
            {"service_name": "Service A"}, {"score": 1}, tenant_id=self.tenant_id
        )
        blueprint_b = self.runtime_store.save_blueprint(
            {"service_name": "Service B"}, {"score": 1}, tenant_id=self.tenant_id
        )
        self.runtime_store.link_blueprint_to_service_analysis(
            blueprint_a["id"], self.tenant_id, service_a["id"], "an-a"
        )
        self.runtime_store.link_blueprint_to_service_analysis(
            blueprint_b["id"], self.tenant_id, service_b["id"], "an-b"
        )

        customer = self.runtime_store.register_customer("Test Citizen", "citizen@example.com")
        self.runtime_store.create_journey(
            customer_id=customer["id"], intent="Renew my permit",
            blueprint_id=blueprint_a["id"], lang="en", sandbox=True,
        )
        self.runtime_store.create_journey(
            customer_id=customer["id"], intent="Ask about a different service",
            blueprint_id=blueprint_b["id"], lang="en", sandbox=True,
        )

        journeys_for_a = fetch_journeys_for_service(
            self.runtime_store.database_path, service_a["id"], self.tenant_id
        )
        self.assertEqual(len(journeys_for_a), 1)
        self.assertEqual(journeys_for_a[0]["intent"], "Renew my permit")

    def test_predictions_table_is_additive_and_does_not_touch_existing_tables(self):
        service = self.service_store.create_service(tenant_id=self.tenant_id, service_name="Some Service")
        saved = self.prediction_store.save_prediction(
            tenant_id=self.tenant_id, service_id=service["id"],
            input_snapshot={"analyses": []}, result={"predictions": []},
            data_sufficiency="INSUFFICIENT",
        )
        self.assertIsNotNone(saved)
        fetched = self.prediction_store.get_prediction_for_tenant(saved["id"], self.tenant_id)
        self.assertEqual(fetched["data_sufficiency"], "INSUFFICIENT")

        # Existing tables/rows are completely undisturbed.
        services_after = self.service_store.list_services_for_tenant(self.tenant_id)
        self.assertEqual(len(services_after), 1)


class PredictEndpointTestCase(unittest.TestCase):
    """Endpoint-level smoke test through the real FastAPI app, proving
    the route is wired without needing the /api/analyze pipeline."""

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
            f"Predict Test Tenant {suffix}", f"predict-test-tenant-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Predict Test Admin", f"predict-test-{suffix}@test.local", role="entity_admin"
        )
        login = cls.client.post(
            "/api/auth/demo-login",
            json={"email": user["email"], "credential": "zxr-demo-2026"},
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

    def test_predict_unknown_service_returns_404(self):
        response = self.client.post(
            "/api/services/does-not-exist/predict", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

    def test_predict_service_with_no_analyses_returns_insufficient(self):
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Freshly Created Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/predict", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data_sufficiency"]["verdict"], "INSUFFICIENT")
        self.assertEqual(body["predictions"], [])
        self.assertIn("prediction_id", body)

    def test_predict_service_with_recurring_stored_gap_returns_prediction(self):
        service = self.main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Service With History"
        )
        for _ in range(2):
            self.main_module.service_store.create_analysis(
                tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-x",
                result=_analysis_result(gaps=[_gap("STD-01", "Missing digital ID check")]),
            )
        response = self.client.post(
            f"/api/services/{service['id']}/predict", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["predictions"]), 1)
        self.assertEqual(body["predictions"][0]["confidence"], 1.0)

        # Stored and retrievable from the new, additive predictions table.
        stored = self.main_module.prediction_store.list_predictions_for_service(
            service["id"], self.tenant_id
        )
        self.assertEqual(len(stored), 1)


if __name__ == "__main__":
    unittest.main()
