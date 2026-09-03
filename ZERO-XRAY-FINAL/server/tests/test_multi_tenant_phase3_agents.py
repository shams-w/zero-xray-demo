"""Phase 3 tests: persistent published-Agent store (replaces the
frontend's localStorage dependency) and the public sanitized endpoint.

Covers:
- `sanitize_for_public` strips internal analysis sections
- An Agent cannot be published from a non-PUBLISHED Blueprint
- The public URL survives "another device/browser" (a second,
  unrelated TestClient / no shared state) because it's backend
  persisted, not localStorage
- Tenant B's Blueprint can never be published under Tenant A's slug
  (Agent creation is tenant-scoped)
- The public payload never contains internal-only sections
"""

import os
import tempfile
import unittest
import uuid
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

from fastapi.testclient import TestClient

import main as main_module
from core.agent_store import AgentStore, sanitize_for_public
from core.runtime_store import RuntimeStore


class SanitizeForPublicTestCase(unittest.TestCase):
    def test_strips_internal_analysis_sections(self):
        full_result = {
            "service_name": "Renew PO Box",
            "service": {"service_name": "Renew PO Box", "steps": ["Pay fee"]},
            "redesign": {"future_steps": ["Submit online"]},
            "relevant_standards": {"raw_text": "internal government standards text"},
            "gap_analysis": {"internal_notes": "should never be public"},
            "step_compliance": {"debug": "internal"},
            "validation": {"issues": ["internal QA issue"]},
            "simulation": {"trace": "internal"},
            "metrics": {"internal_score": 42},
        }
        public = sanitize_for_public(full_result)
        self.assertIn("service_name", public)
        self.assertIn("service", public)
        self.assertIn("redesign", public)
        for internal_key in (
            "relevant_standards", "gap_analysis", "step_compliance",
            "validation", "simulation", "metrics",
        ):
            self.assertNotIn(internal_key, public)

    def test_non_dict_input_is_handled_safely(self):
        self.assertEqual(sanitize_for_public(None), {})
        self.assertEqual(sanitize_for_public("not a dict"), {})


class AgentStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "runtime.db"
        self.runtime_store = RuntimeStore(self.db_path)
        self.agent_store = AgentStore(database_path=self.db_path)
        self.tenant = self.runtime_store._tenant_repository.create_tenant(
            "Emirates Post", "emirates-post-agentstore", status="ACTIVE"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_cannot_publish_agent_from_unpublished_blueprint(self):
        blueprint = self.runtime_store.save_blueprint(
            {"service_name": "Draft Service"}, {}, tenant_id=self.tenant["id"]
        )
        with self.assertRaises(ValueError):
            self.agent_store.publish_agent(self.tenant["id"], blueprint)

    def test_publish_generates_stable_tenant_prefixed_slug(self):
        blueprint = self.runtime_store.save_blueprint(
            {"service_name": "Renew Corporate PO Box"}, {"redesign": {}}, tenant_id=self.tenant["id"]
        )
        self.runtime_store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=self.tenant["id"])
        published_blueprint = self.runtime_store.set_blueprint_status(
            blueprint["id"], "PUBLISHED", tenant_id=self.tenant["id"]
        )
        agent = self.agent_store.publish_agent(self.tenant["id"], published_blueprint)
        self.assertTrue(agent["published_slug"].startswith("emirates-post-agentstore/"))
        self.assertEqual(agent["status"], "PUBLISHED")

    def test_public_lookup_only_resolves_published_agents(self):
        blueprint = self.runtime_store.save_blueprint(
            {"service_name": "Some Service"}, {}, tenant_id=self.tenant["id"]
        )
        self.runtime_store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=self.tenant["id"])
        published = self.runtime_store.set_blueprint_status(blueprint["id"], "PUBLISHED", tenant_id=self.tenant["id"])
        agent = self.agent_store.publish_agent(self.tenant["id"], published)
        tenant_slug, agent_slug = agent["published_slug"].split("/", 1)
        found = self.agent_store.get_agent_by_public_slug(tenant_slug, agent_slug)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], agent["id"])
        # Unknown slug -> None, not an exception.
        self.assertIsNone(self.agent_store.get_agent_by_public_slug(tenant_slug, "does-not-exist"))


class PublishedAgentLiveApiTestCase(unittest.TestCase):
    """Live over the real FastAPI app -- same TestClient pattern as
    tests/test_api_endpoints.py."""

    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _make_tenant_and_headers(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        user = self.repo.create_user(tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin")
        r = self.client.post("/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"})
        self.assertEqual(r.status_code, 200)
        return tenant, {"Authorization": f"Bearer {r.json()['token']}"}

    def test_publish_then_fetch_via_public_url_survives_a_second_unrelated_client(self):
        tenant, headers = self._make_tenant_and_headers("PubTenant")

        analyze = self.client.post(
            "/api/analyze",
            json={"service_name": "Renew Corporate PO Box", "description": "test"},
            headers=headers,
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        blueprint_id = analyze.json()["blueprint_id"]

        approve = self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.assertEqual(approve.status_code, 200, approve.text)
        publish_bp = self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        self.assertEqual(publish_bp.status_code, 200, publish_bp.text)

        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)
        slug = publish_agent.json()["published_slug"]
        tenant_slug, agent_slug = slug.split("/", 1)

        # A brand-new TestClient with no cookies/localStorage/shared
        # state at all -- simulating "another device or browser".
        other_client = TestClient(main_module.app)
        public = other_client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200, public.text)
        body = public.json()
        self.assertIn("result", body)
        self.assertEqual(body["result"]["service_name"], "Renew Corporate PO Box")
        # The public payload must never carry internal analysis sections.
        for internal_key in ("relevant_standards", "gap_analysis", "step_compliance", "validation"):
            self.assertNotIn(internal_key, body["result"])

    def test_cannot_publish_agent_for_another_tenants_blueprint(self):
        tenant_a, headers_a = self._make_tenant_and_headers("AgentTenantA")
        _tenant_b, headers_b = self._make_tenant_and_headers("AgentTenantB")

        analyze = self.client.post(
            "/api/analyze",
            json={"service_name": "Tenant A Only Service", "description": "x"},
            headers=headers_a,
        )
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers_a)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers_a)

        # Tenant B tries to publish an Agent from Tenant A's real Blueprint ID.
        cross = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers_b
        )
        self.assertEqual(cross.status_code, 404)

    def test_unknown_public_service_url_is_404(self):
        r = self.client.get("/service/no-such-tenant/no-such-agent")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
