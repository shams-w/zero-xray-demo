"""Service-generic / stage-dependency tests for the full Government
Future Engine chain:

    Predict -> Simulate -> Challenge -> Evolve -> Prevent -> Monitoring

Covers:
  1. The full chain runs correctly end-to-end for four differently-
     shaped services (Event Permit: payment+docs+approvals+
     integrations; Shipment Tracking: no payment+no documents;
     P.O. Box Renewal: payment+docs+integrations; Complaint Service:
     no payment+human escalation+SLA) -- no stage assumes every
     service has payment/documents/integrations/approvals/human steps.
  2. Each stage validates only its OWN real prerequisites -- a missing
     prerequisite returns a clear, structured INSUFFICIENT_DATA result
     (reason/missing_requirement/next_action), never an unexplained
     400, a hang, or a silent wrong-looking success.
  3. Stages don't block each other unnecessarily: Simulate still runs
     from the stored service/future-journey context even when Predict
     has insufficient history (this is additionally covered in depth
     by tests/test_future_simulation_agent.py's AUTO-mode tests; this
     file re-confirms it as part of the full chain).

Builds each service's stored analysis directly via service_store (the
same pattern tests/test_future_simulation_agent.py and
tests/test_challenge_agent.py already use), so these tests do not
depend on Ollama/AI availability -- every stage exercised here is
fully deterministic Python.
"""

import os
import unittest

os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:19999")  # deliberately unreachable
os.environ.setdefault("ZX_LLM_MODE", "ollama")

from fastapi.testclient import TestClient

import main as main_module


def _future_step(step_number, name, step_type, has_payment=False, requires_human_judgement=False):
    return {
        "step_number": step_number, "name": name, "type": step_type,
        "action": name, "change_type": "KEPT", "reason": "", "standard_id": "",
        "has_payment": has_payment, "requires_human_judgement": requires_human_judgement,
    }


# =====================================================================
# FOUR DIFFERENTLY-SHAPED SERVICES (Section 3/4/5 audit fix)
# =====================================================================

EVENT_PERMIT = {
    "name": "Public Event Permit",
    "future_steps": [
        _future_step(1, "Customer submits event permit application", "CUSTOMER"),
        _future_step(2, "System verifies venue availability", "SYSTEM"),
        _future_step(3, "Customer uploads supporting documents", "CUSTOMER"),
        _future_step(4, "Employee approves the permit request", "HUMAN", requires_human_judgement=True),
        _future_step(5, "Customer pays the permit fee", "CUSTOMER", has_payment=True),
        _future_step(6, "System issues the permit", "SYSTEM"),
    ],
    "required_integrations": ["Venue Booking Registry", "Payment Gateway"],
}

SHIPMENT_TRACKING = {
    "name": "Shipment Tracking",
    "future_steps": [
        _future_step(1, "Customer enters a tracking number", "CUSTOMER"),
        _future_step(2, "System retrieves shipment status", "SYSTEM"),
        _future_step(3, "System displays delivery estimate", "SYSTEM"),
    ],
    "required_integrations": [],  # no payment, no documents, no integrations
}

POBOX_RENEWAL = {
    "name": "Corporate P.O. Box Renewal",
    "future_steps": [
        _future_step(1, "Customer submits renewal request", "CUSTOMER"),
        _future_step(2, "Customer uploads company registration document", "CUSTOMER"),
        _future_step(3, "System verifies box ownership", "SYSTEM"),
        _future_step(4, "Customer pays the renewal fee", "CUSTOMER", has_payment=True),
        _future_step(5, "System confirms the renewal", "SYSTEM"),
    ],
    "required_integrations": ["Corporate Registry", "Payment Gateway"],
}

COMPLAINT_SERVICE = {
    "name": "Complaint Service",
    "future_steps": [
        _future_step(1, "Customer submits a complaint", "CUSTOMER"),
        _future_step(2, "System logs and categorizes the complaint", "SYSTEM"),
        _future_step(3, "Employee reviews and escalates unresolved complaints", "HUMAN",
                      requires_human_judgement=True),
        _future_step(4, "System closes the complaint", "SYSTEM"),
    ],
    "required_integrations": [],  # no payment
}

ALL_SERVICE_SHAPES = [EVENT_PERMIT, SHIPMENT_TRACKING, POBOX_RENEWAL, COMPLAINT_SERVICE]


class FullChainAcrossServiceShapesTestCase(unittest.TestCase):
    """Runs Predict -> Simulate -> Challenge -> Evolve -> Prevent ->
    Monitoring end to end for each of the four named service shapes."""

    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)

        import uuid
        suffix = uuid.uuid4().hex[:8]
        tenant = main_module.tenant_repository.create_tenant(
            f"Future Engine Shapes Tenant {suffix}", f"future-engine-shapes-{suffix}",
            status="ACTIVE",
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Future Engine Shapes Admin", f"future-engine-shapes-{suffix}@test.local",
            role="entity_admin",
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

    def _service_with_shape(self, shape):
        service = main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name=shape["name"]
        )
        main_module.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id=f"bp-{service['id']}",
            result={
                "redesign": {
                    "future_steps": shape["future_steps"],
                    "required_integrations": shape["required_integrations"],
                },
            },
        )
        return service["id"]

    def _run_full_chain(self, shape):
        service_id = self._service_with_shape(shape)

        # 1. Predict -- always succeeds (200), even with zero history;
        # a fresh service correctly reports data_sufficiency=INSUFFICIENT
        # rather than hanging, failing silently, or 400ing.
        predict = self.client.post(f"/api/services/{service_id}/predict", headers=self.headers)
        self.assertEqual(predict.status_code, 200, predict.text)
        self.assertIn(predict.json()["data_sufficiency"]["verdict"], ("SUFFICIENT", "LIMITED", "INSUFFICIENT"))

        # 2. Simulate (AUTO) -- runs from the stored future-journey/
        # service context alone; does NOT require Predict to have
        # produced anything (this service has zero stored analyses
        # history beyond the one just created, so Predict's own verdict
        # here is INSUFFICIENT -- Simulate must still work).
        simulate = self.client.post(
            f"/api/services/{service_id}/scenarios", headers=self.headers, json={"trigger_type": "AUTO"}
        )
        self.assertEqual(simulate.status_code, 200, simulate.text)
        auto_scenarios = simulate.json()["auto_scenarios"]
        self.assertGreater(len(auto_scenarios), 0)
        categories = {item["scenario"]["auto_category"] for item in auto_scenarios}
        # Relevance gating -- Section 2's requirement re-confirmed as
        # part of the full chain, not just in isolation.
        has_payment_step = any(s.get("has_payment") for s in shape["future_steps"])
        has_integrations = bool(shape["required_integrations"])
        self.assertEqual("PAYMENT_FAILURE" in categories, has_payment_step or any(
            "payment" in i.lower() for i in shape["required_integrations"]
        ))
        self.assertEqual("INTEGRATION_FAILURE" in categories, has_integrations)

        # 3. Challenge -- exhaustive stress test over whatever this
        # service actually has (steps always exist; integrations only
        # if this shape has any).
        challenge = self.client.post(f"/api/services/{service_id}/challenges", headers=self.headers, json={})
        self.assertEqual(challenge.status_code, 200, challenge.text)
        challenge_id = challenge.json()["challenge_id"]
        cases_executed = challenge.json()["cases_executed"]
        integration_cases = [c for c in cases_executed if c["strategy"] == "EXHAUSTIVE_INTEGRATION_FAILURE"]
        self.assertEqual(len(integration_cases), len(shape["required_integrations"]))

        # 4. Evolve -- genuinely depends on a real challenge_id (this
        # is a REAL prerequisite, not something to loosen); must
        # succeed (200) even if Challenge found zero vulnerabilities.
        evolve = self.client.post(
            f"/api/services/{service_id}/evolutions", headers=self.headers,
            json={"challenge_id": challenge_id},
        )
        self.assertEqual(evolve.status_code, 200, evolve.text)
        evolution_id = evolve.json()["evolution_id"]

        # 5. Prevent -- genuinely depends on a real evolution_id.
        prevent = self.client.post(
            f"/api/services/{service_id}/preventions", headers=self.headers,
            json={"evolution_id": evolution_id},
        )
        self.assertEqual(prevent.status_code, 200, prevent.text)
        prevention_id = prevent.json()["prevention_id"]

        # 6. Monitoring -- genuinely depends on a real prevention_id.
        monitoring = self.client.post(
            f"/api/services/{service_id}/monitoring-checks", headers=self.headers,
            json={"prevention_id": prevention_id},
        )
        self.assertEqual(monitoring.status_code, 200, monitoring.text)

        return {
            "predict": predict.json(), "simulate": simulate.json(),
            "challenge": challenge.json(), "evolve": evolve.json(),
            "prevent": prevent.json(), "monitoring": monitoring.json(),
        }

    def test_event_permit_full_chain(self):
        self._run_full_chain(EVENT_PERMIT)

    def test_shipment_tracking_full_chain(self):
        self._run_full_chain(SHIPMENT_TRACKING)

    def test_pobox_renewal_full_chain(self):
        self._run_full_chain(POBOX_RENEWAL)

    def test_complaint_service_full_chain(self):
        self._run_full_chain(COMPLAINT_SERVICE)

    def test_all_four_shapes_produce_different_auto_categories(self):
        """No two differently-shaped services get an identical set of
        AUTO scenario categories -- proves the engine is reading each
        service's own real characteristics, not returning one
        one-size-fits-all result regardless of input."""
        category_sets = []
        for shape in ALL_SERVICE_SHAPES:
            service_id = self._service_with_shape(shape)
            response = self.client.post(
                f"/api/services/{service_id}/scenarios", headers=self.headers, json={"trigger_type": "AUTO"}
            )
            self.assertEqual(response.status_code, 200)
            categories = frozenset(
                item["scenario"]["auto_category"] for item in response.json()["auto_scenarios"]
            )
            category_sets.append(categories)
        self.assertEqual(len(category_sets), len(set(category_sets)))


class StageIndependenceTestCase(unittest.TestCase):
    """Each stage validates only ITS OWN real prerequisites; a stage's
    own missing data returns a structured INSUFFICIENT_DATA result
    instead of an unexplained 400, and does not block a LATER stage
    that has an alternative, sufficient data source of its own."""

    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)

        import uuid
        suffix = uuid.uuid4().hex[:8]
        tenant = main_module.tenant_repository.create_tenant(
            f"Stage Independence Tenant {suffix}", f"stage-independence-{suffix}", status="ACTIVE"
        )
        user = main_module.tenant_repository.create_user(
            tenant["id"], "Stage Independence Admin", f"stage-independence-{suffix}@test.local",
            role="entity_admin",
        )
        login = cls.client.post(
            "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        cls.tenant_id = tenant["id"]

    def test_simulate_runs_despite_predict_having_insufficient_history(self):
        # A service with exactly one stored analysis: Predict's own
        # MIN_ANALYSES_FOR_PREDICTION threshold is not met, so Predict
        # correctly reports INSUFFICIENT and returns zero predictions
        # -- Simulate must still succeed from the service/future-
        # journey context alone (requirement 4's explicit example).
        service = main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Sparse History Service"
        )
        main_module.service_store.create_analysis(
            tenant_id=self.tenant_id, service_id=service["id"], blueprint_id="bp-sparse",
            result={
                "redesign": {
                    "future_steps": SHIPMENT_TRACKING["future_steps"],
                    "required_integrations": [],
                },
            },
        )

        predict = self.client.post(f"/api/services/{service['id']}/predict", headers=self.headers)
        self.assertEqual(predict.status_code, 200)
        self.assertEqual(predict.json()["data_sufficiency"]["verdict"], "INSUFFICIENT")

        simulate = self.client.post(
            f"/api/services/{service['id']}/scenarios", headers=self.headers, json={"trigger_type": "AUTO"}
        )
        self.assertEqual(simulate.status_code, 200, simulate.text)
        self.assertGreater(len(simulate.json()["auto_scenarios"]), 0)

    def test_simulate_on_fresh_service_returns_structured_insufficient_data(self):
        service = main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Never Analyzed Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/scenarios", headers=self.headers, json={"trigger_type": "AUTO"}
        )
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["error_code"], "INSUFFICIENT_DATA")
        self.assertTrue(detail["reason"])
        self.assertTrue(detail["missing_requirement"])
        self.assertTrue(detail["next_action"])

    def test_challenge_on_fresh_service_returns_structured_insufficient_data(self):
        service = main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="Never Analyzed Service 2"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/challenges", headers=self.headers, json={}
        )
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["error_code"], "INSUFFICIENT_DATA")
        self.assertTrue(detail["reason"])
        self.assertTrue(detail["missing_requirement"])
        self.assertTrue(detail["next_action"])

    def test_evolve_requires_its_own_real_challenge_id(self):
        # Evolve's dependency on Challenge is a REAL prerequisite
        # (nothing to evolve without a Challenge run) -- unlike
        # Simulate/Predict, this is correctly a 404 for an unknown
        # reference, not something this fix loosens.
        service = main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="No Challenge Yet Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/evolutions", headers=self.headers,
            json={"challenge_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)

    def test_prevent_requires_its_own_real_evolution_id(self):
        service = main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="No Evolution Yet Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/preventions", headers=self.headers,
            json={"evolution_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)

    def test_monitoring_requires_its_own_real_prevention_id(self):
        service = main_module.service_store.create_service(
            tenant_id=self.tenant_id, service_name="No Prevention Yet Service"
        )
        response = self.client.post(
            f"/api/services/{service['id']}/monitoring-checks", headers=self.headers,
            json={"prevention_id": "does-not-exist"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
