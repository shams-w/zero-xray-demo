"""Phase 2 tests: exercises the REAL FastAPI app end-to-end (same
pattern as tests/test_api_endpoints.py -- no mocked routes) to prove
`/api/analyze`, `/api/blueprints/*` are now tenant-scoped, and that a
direct-object-access attack (Tenant B requesting Tenant A's real
Blueprint UUID) is denied with 404, not 403 and not the data.

Uses uuid-suffixed tenant slugs so repeated runs against the shared
demo database (the existing project's convention -- see
test_api_endpoints.py, which has no DB isolation either) never collide.
"""

import os
import unittest
import uuid

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

from fastapi.testclient import TestClient

import main as main_module


class CrossTenantApiIsolationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _make_tenant_and_token(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        user = self.repo.create_user(tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin")
        r = self.client.post(
            "/api/auth/demo-login",
            json={"email": user["email"], "credential": "zxr-demo-2026"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        return tenant, {"Authorization": f"Bearer {token}"}

    def test_tenant_b_gets_404_for_tenant_a_blueprint(self):
        tenant_a, headers_a = self._make_tenant_and_token("TenantA")
        _tenant_b, headers_b = self._make_tenant_and_token("TenantB")

        analyze_response = self.client.post(
            "/api/analyze",
            json={"service_name": "Renew Corporate PO Box", "description": "test service"},
            headers=headers_a,
        )
        self.assertEqual(analyze_response.status_code, 200, analyze_response.text)
        blueprint_id = analyze_response.json()["blueprint_id"]

        # Tenant A can fetch its own Blueprint.
        own = self.client.get(f"/api/blueprints/{blueprint_id}", headers=headers_a)
        self.assertEqual(own.status_code, 200)

        # Tenant B using Tenant A's REAL Blueprint UUID must get 404,
        # not the record, and not a 403 that would confirm it exists.
        cross = self.client.get(f"/api/blueprints/{blueprint_id}", headers=headers_b)
        self.assertEqual(cross.status_code, 404)

        # Same for approve/publish -- Tenant B cannot mutate Tenant A's Blueprint.
        cross_approve = self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_b)
        self.assertEqual(cross_approve.status_code, 404)

    def test_unauthenticated_analyze_call_is_now_rejected(self):
        # Soft/anonymous fallback on /api/analyze was intentionally
        # removed (task: "Remove Soft Auth" -- replace
        # get_tenant_context_soft with strict get_tenant_context on
        # ALL private APIs). A caller with no Authorization header at
        # all must now get 401, not silently fall back to the default
        # tenant.
        r = self.client.post(
            "/api/analyze",
            json={"service_name": "Legacy Unauthenticated Call", "description": "x"},
        )
        self.assertEqual(r.status_code, 401)

    def test_bad_token_on_blueprint_endpoint_is_rejected(self):
        r = self.client.get(
            "/api/blueprints/does-not-matter",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
