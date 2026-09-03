"""RBAC regression coverage for state-changing Government Future Engine APIs.

The backend is the security boundary. Frontend button visibility is only a UX mirror.
"""

import unittest
import uuid

from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env

_ollama_patch = None

def setUpModule():
    global _ollama_patch
    _ollama_patch = patch_ollama_env()

def tearDownModule():
    unpatch_ollama_env(_ollama_patch)

from fastapi.testclient import TestClient

import main as main_module


class FutureEngineRbacTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def setUp(self):
        suffix = uuid.uuid4().hex[:10]
        self.tenant = self.repo.create_tenant(
            f"Future RBAC {suffix}", f"future-rbac-{suffix}", status="ACTIVE"
        )
        self._users = {}
        self.headers = {
            role: self._make_user_and_headers(role, suffix)
            for role in ("entity_admin", "service_owner", "analyst", "viewer")
        }
        self.service_id = self._seed_service()
        # A service_owner only ever sees/acts on a Service they're
        # explicitly assigned to (main.py's _require_service_access,
        # enforced identically for the Future Engine endpoints below) --
        # the same assignment every real service_owner gets via
        # POST /api/services/{id}/assignments/{user_id} or automatically
        # on creating their own Service (main.py's create_service). A
        # fixture that skips this and expects access anyway is testing an
        # access pattern that can't occur through the real API.
        main_module.service_store.assign_user_to_service(
            self.tenant["id"], self.service_id, self._users["service_owner"]["id"]
        )

    def _make_user_and_headers(self, role, suffix):
        user = self.repo.create_user(
            self.tenant["id"],
            f"{role} {suffix}",
            f"{role}-{suffix}@test.local",
            role=role,
        )
        self._users[role] = user
        response = self.client.post(
            "/api/auth/demo-login",
            json={"email": user["email"], "credential": "zxr-demo-2026"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def _seed_service(self):
        service = main_module.service_store.create_service(
            tenant_id=self.tenant["id"],
            service_name="Future RBAC Service",
            description="Deterministic service fixture for Future Engine RBAC",
            created_by="rbac-test",
        )
        main_module.service_store.create_analysis(
            tenant_id=self.tenant["id"],
            service_id=service["id"],
            blueprint_id=f"rbac-blueprint-{uuid.uuid4()}",
            created_by="rbac-test",
            result={
                "service": {"waiting_times": ["2 hours"]},
                "redesign": {
                    "future_steps": [
                        {
                            "step_number": 1,
                            "name": "Validate request",
                            "type": "SYSTEM",
                            "has_payment": False,
                        },
                        {
                            "step_number": 2,
                            "name": "Complete service outcome",
                            "type": "SYSTEM",
                            "has_payment": False,
                        },
                    ],
                    "required_integrations": ["Identity API"],
                },
            },
        )
        return service["id"]

    def _post_predict(self, role):
        return self.client.post(
            f"/api/services/{self.service_id}/predict", headers=self.headers[role]
        )

    def _post_simulate(self, role):
        return self.client.post(
            f"/api/services/{self.service_id}/scenarios",
            headers=self.headers[role],
            json={"trigger_type": "AUTO"},
        )

    def _post_challenge(self, role):
        return self.client.post(
            f"/api/services/{self.service_id}/challenges",
            headers=self.headers[role],
            json={},
        )

    def _post_evolve(self, role, challenge_id="not-needed-for-denied-request"):
        return self.client.post(
            f"/api/services/{self.service_id}/evolutions",
            headers=self.headers[role],
            json={"challenge_id": challenge_id},
        )

    def _post_prevent(self, role, evolution_id="not-needed-for-denied-request"):
        return self.client.post(
            f"/api/services/{self.service_id}/preventions",
            headers=self.headers[role],
            json={"evolution_id": evolution_id},
        )

    def _post_monitor(self, role, prevention_id="not-needed-for-denied-request"):
        return self.client.post(
            f"/api/services/{self.service_id}/monitoring-checks",
            headers=self.headers[role],
            json={"prevention_id": prevention_id},
        )

    def _assert_full_chain_allowed(self, role):
        prediction = self._post_predict(role)
        self.assertEqual(prediction.status_code, 200, prediction.text)

        simulation = self._post_simulate(role)
        self.assertEqual(simulation.status_code, 200, simulation.text)

        challenge = self._post_challenge(role)
        self.assertEqual(challenge.status_code, 200, challenge.text)

        evolution = self._post_evolve(role, challenge.json()["challenge_id"])
        self.assertEqual(evolution.status_code, 200, evolution.text)

        prevention = self._post_prevent(role, evolution.json()["evolution_id"])
        self.assertEqual(prevention.status_code, 200, prevention.text)

        monitoring = self._post_monitor(role, prevention.json()["prevention_id"])
        self.assertEqual(monitoring.status_code, 200, monitoring.text)

    def test_viewer_is_read_only_and_all_future_engine_posts_are_denied(self):
        # Viewer retains tenant reads.
        read = self.client.get(
            f"/api/services/{self.service_id}/scenarios", headers=self.headers["viewer"]
        )
        self.assertEqual(read.status_code, 200, read.text)

        for request in (
            self._post_predict("viewer"),
            self._post_simulate("viewer"),
            self._post_challenge("viewer"),
            self._post_evolve("viewer"),
            self._post_prevent("viewer"),
            self._post_monitor("viewer"),
        ):
            self.assertEqual(request.status_code, 403, request.text)

    def test_analyst_can_predict_simulate_challenge_but_not_evolve_prevent_monitor(self):
        self.assertEqual(self._post_predict("analyst").status_code, 200)
        self.assertEqual(self._post_simulate("analyst").status_code, 200)
        self.assertEqual(self._post_challenge("analyst").status_code, 200)

        self.assertEqual(self._post_evolve("analyst").status_code, 403)
        self.assertEqual(self._post_prevent("analyst").status_code, 403)
        self.assertEqual(self._post_monitor("analyst").status_code, 403)

    def test_service_owner_can_run_full_future_engine_chain(self):
        self._assert_full_chain_allowed("service_owner")

    def test_entity_admin_can_run_full_future_engine_chain(self):
        self._assert_full_chain_allowed("entity_admin")

    def test_platform_admin_future_engine_behavior_is_unchanged(self):
        suffix = uuid.uuid4().hex[:10]
        platform_tenant = self.repo.create_tenant(
            f"Platform RBAC {suffix}", f"platform-rbac-{suffix}", status="ACTIVE"
        )
        user = self.repo.create_user(
            platform_tenant["id"], "Platform Admin", f"platform-{suffix}@test.local",
            role="platform_admin",
        )
        login = self.client.post(
            "/api/auth/demo-login",
            json={"email": user["email"], "credential": "zxr-demo-2026"},
        )
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        # platform_admin had no tenant:read permission before this fix; the
        # new granular Future Engine permissions intentionally do not change that.
        requests = (
            self.client.post(f"/api/services/{self.service_id}/predict", headers=headers),
            self.client.post(f"/api/services/{self.service_id}/scenarios", headers=headers, json={"trigger_type": "AUTO"}),
            self.client.post(f"/api/services/{self.service_id}/challenges", headers=headers, json={}),
            self.client.post(f"/api/services/{self.service_id}/evolutions", headers=headers, json={"challenge_id": "unused"}),
            self.client.post(f"/api/services/{self.service_id}/preventions", headers=headers, json={"evolution_id": "unused"}),
            self.client.post(f"/api/services/{self.service_id}/monitoring-checks", headers=headers, json={"prevention_id": "unused"}),
        )
        for response in requests:
            self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
