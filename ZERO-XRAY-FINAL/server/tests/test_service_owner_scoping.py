"""Service-owner assignment scoping regression tests.

Proves the required matrix without changing the existing tenant-isolation model:
Service 1 -> Owner A, Service 2 -> Owner B; each owner sees only their service
and service-derived resources, the entity admin sees both, and another tenant
sees neither.
"""
import unittest
import uuid

from fastapi.testclient import TestClient

import main as main_module


class ServiceOwnerScopingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _login(self, user):
        response = self.client.post(
            "/api/auth/demo-login",
            json={"email": user["email"], "credential": "zxr-demo-2026"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def _make_fixture(self):
        suffix = uuid.uuid4().hex[:10]
        tenant = self.repo.create_tenant(
            f"Ownership {suffix}", f"ownership-{suffix}", status="ACTIVE"
        )
        admin = self.repo.create_user(
            tenant["id"], "Entity Admin", f"admin-{suffix}@test.local", role="entity_admin"
        )
        owner_a = self.repo.create_user(
            tenant["id"], "Owner A", f"owner-a-{suffix}@test.local", role="service_owner"
        )
        owner_b = self.repo.create_user(
            tenant["id"], "Owner B", f"owner-b-{suffix}@test.local", role="service_owner"
        )
        other_tenant = self.repo.create_tenant(
            f"Other {suffix}", f"other-{suffix}", status="ACTIVE"
        )
        other_admin = self.repo.create_user(
            other_tenant["id"], "Other Admin", f"other-{suffix}@test.local", role="entity_admin"
        )

        admin_h = self._login(admin)
        a_h = self._login(owner_a)
        b_h = self._login(owner_b)
        other_h = self._login(other_admin)

        # Create one allowed data source for each service.
        ds1 = self.client.post(
            "/api/data-sources",
            headers=admin_h,
            json={"name": "DS1", "type": "TEXT", "status": "READY", "classification": "TENANT_PRIVATE_SOURCE", "configuration": {"content": "one"}},
        ).json()
        ds2 = self.client.post(
            "/api/data-sources",
            headers=admin_h,
            json={"name": "DS2", "type": "TEXT", "status": "READY", "classification": "TENANT_PRIVATE_SOURCE", "configuration": {"content": "two"}},
        ).json()
        service1 = self.client.post(
            "/api/services", headers=admin_h,
            json={"service_name": "Service 1", "description": "one", "language": "en", "data_source_ids": [ds1["id"]], "integration_ids": []},
        ).json()
        service2 = self.client.post(
            "/api/services", headers=admin_h,
            json={"service_name": "Service 2", "description": "two", "language": "en", "data_source_ids": [ds2["id"]], "integration_ids": []},
        ).json()

        self.assertEqual(self.client.post(
            f"/api/services/{service1['id']}/assignments/{owner_a['id']}", headers=admin_h
        ).status_code, 200)
        self.assertEqual(self.client.post(
            f"/api/services/{service2['id']}/assignments/{owner_b['id']}", headers=admin_h
        ).status_code, 200)

        # Build lightweight Blueprint/Analysis/Agent lineage without invoking AI.
        artifacts = {}
        for service, label in ((service1, "one"), (service2, "two")):
            blueprint = main_module.runtime_store.save_blueprint(
                {"service_name": service["service_name"], "lang": "en"},
                {"service": {"service_name": service["service_name"]}, "redesign": {}},
                tenant_id=tenant["id"],
            )
            analysis = main_module.service_store.create_analysis(
                tenant["id"], service["id"], blueprint["id"], created_by=admin["id"], result={"label": label}
            )
            blueprint = main_module.runtime_store.link_blueprint_to_service_analysis(
                blueprint["id"], tenant["id"], service["id"], analysis["id"]
            )
            main_module.runtime_store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=tenant["id"])
            blueprint = main_module.runtime_store.set_blueprint_status(blueprint["id"], "PUBLISHED", tenant_id=tenant["id"])
            agent = main_module.agent_store.publish_agent(tenant["id"], blueprint, created_by=admin["id"])
            artifacts[service["id"]] = {"blueprint": blueprint, "analysis": analysis, "agent": agent}

        return {
            "tenant": tenant, "admin_h": admin_h, "a_h": a_h, "b_h": b_h, "other_h": other_h,
            "service1": service1, "service2": service2, "ds1": ds1, "ds2": ds2, "artifacts": artifacts,
        }

    def test_required_service_owner_assignment_matrix(self):
        f = self._make_fixture()
        s1, s2 = f["service1"], f["service2"]

        # Service 1 -> Owner A; Service 2 -> Owner B.
        self.assertEqual(self.client.get(f"/api/services/{s1['id']}", headers=f["a_h"]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/services/{s2['id']}", headers=f["a_h"]).status_code, 404)
        self.assertEqual(self.client.get(f"/api/services/{s2['id']}", headers=f["b_h"]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/services/{s1['id']}", headers=f["b_h"]).status_code, 404)

        # Lists are scoped, not merely detail endpoints.
        self.assertEqual({x["id"] for x in self.client.get("/api/services", headers=f["a_h"]).json()["services"]}, {s1["id"]})
        self.assertEqual({x["id"] for x in self.client.get("/api/services", headers=f["b_h"]).json()["services"]}, {s2["id"]})

        a1 = f["artifacts"][s1["id"]]
        a2 = f["artifacts"][s2["id"]]

        # Related Analyses / Blueprints / Agents obey the same service assignment.
        self.assertEqual(self.client.get(f"/api/analyses/{a1['analysis']['id']}", headers=f["a_h"]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/analyses/{a2['analysis']['id']}", headers=f["a_h"]).status_code, 404)
        self.assertEqual(self.client.get(f"/api/blueprints/{a1['blueprint']['id']}", headers=f["a_h"]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/blueprints/{a2['blueprint']['id']}", headers=f["a_h"]).status_code, 404)
        self.assertEqual(self.client.get(f"/api/agents/{a1['agent']['id']}", headers=f["a_h"]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/agents/{a2['agent']['id']}", headers=f["a_h"]).status_code, 404)

        # Allowed Data Sources are the sources connected to assigned services only.
        self.assertEqual({x["id"] for x in self.client.get("/api/data-sources", headers=f["a_h"]).json()["data_sources"]}, {f["ds1"]["id"]})
        self.assertEqual(self.client.get(f"/api/data-sources/{f['ds2']['id']}", headers=f["a_h"]).status_code, 404)

        # Future Engine reads/operations cannot cross the service assignment boundary.
        self.assertEqual(self.client.get(f"/api/services/{s2['id']}/scenarios", headers=f["a_h"]).status_code, 404)
        self.assertEqual(self.client.post(f"/api/services/{s2['id']}/predict", headers=f["a_h"]).status_code, 404)

        # Entity Admin keeps full tenant-level access.
        for service in (s1, s2):
            self.assertEqual(self.client.get(f"/api/services/{service['id']}", headers=f["admin_h"]).status_code, 200)

        # Existing tenant isolation remains intact.
        for service in (s1, s2):
            self.assertEqual(self.client.get(f"/api/services/{service['id']}", headers=f["other_h"]).status_code, 404)


if __name__ == "__main__":
    unittest.main()
