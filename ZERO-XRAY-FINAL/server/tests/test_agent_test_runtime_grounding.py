"""Phase 5 focused tests: the existing Test Agent / Sandbox journey
runtime (client/src/components/LiveAgentPage.jsx via /api/sandbox/register
-> /api/journeys) now walks through the SAME grounded Agent decisions
Build Agent already showed (server/core/agent_capability_mapper.py's
Phase 2-4 `agent_capability_map`), instead of the old keyword-guessed
`redesign.execution_plan`/`redesign.required_integrations`.

Part 1 -- pure unit tests directly against the two new
core/runtime_store.py helpers (no server, no Ollama): shape preservation,
decision-semantics preservation, no secrets, no mutation, legacy/empty
safety.

Part 2 -- live API tests over the real FastAPI app: a journey created from
a grounded Blueprint reflects `agent_capability_map` in its plan; tenant/
Service-Owner/cross-tenant security around the staff-preview Test Agent
launch (`/api/sandbox/register`); CONNECTED/SANDBOX/NOT_CONNECTED
handling; INTEGRATION_REQUIRED never reported as success; no secrets in
the response; legacy Blueprints (no `agent_capability_map`) still work;
the existing execute_journey integration-security gate is unaffected;
Publish flow is unaffected.
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
from core.runtime_store import RuntimeStore


# ---------------------------------------------------------------------------
# Part 1: pure unit tests against the new runtime_store helpers
# ---------------------------------------------------------------------------


class GroundedActionsHelperTestCase(unittest.TestCase):
    def test_empty_or_missing_mapping_returns_empty_list(self):
        self.assertEqual(RuntimeStore._grounded_actions_from_capability_mapping(None), [])
        self.assertEqual(RuntimeStore._grounded_actions_from_capability_mapping([]), [])

    def test_automate_step_becomes_planned_action_with_mapped_integration(self):
        mapping = [{
            "step_number": 1, "name": "Verify licence", "step_type": "SYSTEM",
            "capability_status": "AUTOMATE", "reason": "A CONNECTED integration matches.",
            "mapped_integration": {"id": "int-1", "name": "Licence API", "status": "CONNECTED", "sandbox": False},
        }]
        actions = RuntimeStore._grounded_actions_from_capability_mapping(mapping)
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["sequence"], 1)
        self.assertEqual(action["title"], "Verify licence")
        self.assertEqual(action["status"], "PLANNED")
        self.assertEqual(action["capability_status"], "AUTOMATE")
        self.assertEqual(action["mapped_integration"]["id"], "int-1")
        self.assertIn("Licence API", action["evidence"])

    def test_sandbox_matched_integration_flag_preserved(self):
        mapping = [{
            "step_number": 1, "name": "Charge fee", "step_type": "SYSTEM",
            "capability_status": "AUTOMATE", "reason": "A SANDBOX integration matches.",
            "mapped_integration": {"id": "int-2", "name": "Payment Gateway", "status": "SANDBOX", "sandbox": True},
        }]
        actions = RuntimeStore._grounded_actions_from_capability_mapping(mapping)
        self.assertTrue(actions[0]["mapped_integration"]["sandbox"])
        self.assertEqual(actions[0]["mapped_integration"]["status"], "SANDBOX")

    def test_integration_required_step_never_reports_planned_success(self):
        mapping = [{
            "step_number": 1, "name": "Unmatched step", "step_type": "SYSTEM",
            "capability_status": "INTEGRATION_REQUIRED",
            "reason": "No configured Service Integration provides this capability.",
            "mapped_integration": None,
        }]
        actions = RuntimeStore._grounded_actions_from_capability_mapping(mapping)
        action = actions[0]
        self.assertEqual(action["status"], "INTEGRATION_REQUIRED")
        self.assertIsNone(action["mapped_integration"])
        self.assertIn("No suitable connected integration", action["evidence"])

    def test_customer_and_human_steps_preserve_step_type(self):
        mapping = [
            {"step_number": 1, "name": "Customer step", "step_type": "CUSTOMER",
             "capability_status": "NOT_APPLICABLE", "reason": "This step requires direct customer interaction.",
             "mapped_integration": None},
            {"step_number": 2, "name": "Human step", "step_type": "HUMAN",
             "capability_status": "NOT_APPLICABLE", "reason": "This step requires human or manual processing.",
             "mapped_integration": None},
        ]
        actions = RuntimeStore._grounded_actions_from_capability_mapping(mapping)
        self.assertEqual(actions[0]["step_type"], "CUSTOMER")
        self.assertEqual(actions[1]["step_type"], "HUMAN")
        self.assertTrue(all(a["capability_status"] == "NOT_APPLICABLE" for a in actions))

    def test_no_secret_fields_anywhere_in_output(self):
        mapping = [{
            "step_number": 1, "name": "Step", "step_type": "SYSTEM",
            "capability_status": "AUTOMATE", "reason": "A CONNECTED integration matches.",
            "mapped_integration": {"id": "int-1", "name": "API", "status": "CONNECTED", "sandbox": False},
        }]
        actions = RuntimeStore._grounded_actions_from_capability_mapping(mapping)
        blob = str(actions).lower()
        for forbidden in ("secret_reference", "api_key", "token", "authorization", "config"):
            self.assertNotIn(forbidden, blob)

    def test_does_not_mutate_input_mapping(self):
        mapping = [{
            "step_number": 1, "name": "Step", "step_type": "SYSTEM",
            "capability_status": "AUTOMATE", "reason": "x",
            "mapped_integration": {"id": "int-1", "name": "API", "status": "CONNECTED", "sandbox": False},
        }]
        original = [dict(m, mapped_integration=dict(m["mapped_integration"])) for m in mapping]
        RuntimeStore._grounded_actions_from_capability_mapping(mapping)
        self.assertEqual(mapping, original)

    def test_malformed_entries_are_skipped_safely(self):
        actions = RuntimeStore._grounded_actions_from_capability_mapping(["not-a-dict", None, 42])
        self.assertEqual(actions, [])


class GroundedIntegrationsHelperTestCase(unittest.TestCase):
    def test_empty_or_missing_map_returns_empty_list(self):
        self.assertEqual(RuntimeStore._grounded_integrations_from_capability_map(None), [])
        self.assertEqual(RuntimeStore._grounded_integrations_from_capability_map({}), [])

    def test_preserves_status_description_shape(self):
        cap_map = {"integration_capabilities": [
            {"id": "int-1", "name": "Registry API", "capability_type": "GOVERNMENT_API",
             "status": "CONNECTED", "available": True, "sandbox": False},
            {"id": "int-2", "name": "Payment Gateway", "capability_type": "PAYMENT_GATEWAY",
             "status": "SANDBOX", "available": False, "sandbox": True},
            {"id": "int-3", "name": "Docs API", "capability_type": "DOCUMENT_MANAGEMENT",
             "status": "NOT_CONNECTED", "available": False, "sandbox": False},
        ]}
        integrations = RuntimeStore._grounded_integrations_from_capability_map(cap_map)
        self.assertEqual(len(integrations), 3)
        statuses = {item["status"] for item in integrations}
        self.assertEqual(statuses, {"CONNECTED", "SANDBOX", "NOT_CONNECTED"})
        for item in integrations:
            self.assertIn("description", item)
            self.assertNotIn("secret_reference", item)
            self.assertNotIn("config", item)


# ---------------------------------------------------------------------------
# Part 2: live API tests
# ---------------------------------------------------------------------------


class TestAgentGroundingApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_module.startup()
        cls.client = TestClient(main_module.app)
        cls.repo = main_module.tenant_repository

    def _tenant_and_admin_headers(self, label):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"{label} {suffix}", f"{label.lower()}-{suffix}", status="ACTIVE")
        admin = self.repo.create_user(
            tenant["id"], f"{label} Admin", f"{label.lower()}-{suffix}@test.local", role="entity_admin"
        )
        r = self.client.post(
            "/api/auth/demo-login", json={"email": admin["email"], "credential": "zxr-demo-2026"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        return tenant, admin, {"Authorization": f"Bearer {r.json()['token']}"}

    def _published_blueprint(self, headers, integration_ids=None, service_name="Test Agent Grounding Service"):
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": service_name, "description": "test service",
                  "integration_ids": integration_ids or []},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        body = analyze.json()
        blueprint_id = body["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        publish = self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        self.assertEqual(publish.status_code, 200, publish.text)
        return blueprint_id, body

    def _register_and_start_journey(self, headers, blueprint_id):
        register = self.client.post(
            "/api/sandbox/register", headers=headers,
            json={"name": "Staff Preview Customer", "email": f"preview-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 200, register.text)
        customer = register.json()
        journey = self.client.post(
            "/api/journeys",
            json={"customer_id": customer["id"], "intent": "Test the generated agent",
                  "blueprint_id": blueprint_id, "lang": "en", "sandbox": True},
        )
        self.assertEqual(journey.status_code, 200, journey.text)
        return customer, journey.json()

    # -- 1/2/3: Test Agent uses the selected Blueprint, bound to the
    # correct tenant and Service --

    def test_test_agent_journey_bound_to_selected_blueprint_and_tenant(self):
        tenant, _admin, headers = self._tenant_and_admin_headers("TATenant")
        blueprint_id, _analysis = self._published_blueprint(headers)
        customer, journey = self._register_and_start_journey(headers, blueprint_id)
        self.assertEqual(journey["blueprint_id"], blueprint_id)
        self.assertEqual(customer.get("tenant_id") or tenant["id"], tenant["id"])

    def test_test_agent_plan_reflects_grounded_capability_mapping(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TAGround")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "Registry API", "status": "CONNECTED", "config": {}},
        ).json()
        blueprint_id, analysis = self._published_blueprint(headers, integration_ids=[integ["id"]])
        cap_map = analysis["agent_capability_map"]
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)

        plan_actions = journey["plan"]["actions"]
        self.assertEqual(len(plan_actions), len(cap_map["step_capability_mapping"]))
        for plan_action, mapped_step in zip(plan_actions, cap_map["step_capability_mapping"]):
            self.assertEqual(plan_action["capability_status"], mapped_step["capability_status"])
            self.assertEqual(plan_action["step_type"], mapped_step["step_type"])
            if mapped_step["capability_status"] == "INTEGRATION_REQUIRED":
                self.assertEqual(plan_action["status"], "INTEGRATION_REQUIRED")

    # -- 4: Service Owner cannot test an unassigned Service's Agent --

    def test_service_owner_cannot_launch_test_agent_for_unassigned_service(self):
        suffix = uuid.uuid4().hex[:8]
        tenant = self.repo.create_tenant(f"TAOwner {suffix}", f"taowner-{suffix}", status="ACTIVE")
        admin = self.repo.create_user(tenant["id"], "Admin", f"admin-{suffix}@test.local", role="entity_admin")
        owner = self.repo.create_user(tenant["id"], "Owner", f"owner-{suffix}@test.local", role="service_owner")

        def login(user):
            r = self.client.post(
                "/api/auth/demo-login", json={"email": user["email"], "credential": "zxr-demo-2026"}
            )
            self.assertEqual(r.status_code, 200)
            return {"Authorization": f"Bearer {r.json()['token']}"}

        admin_headers = login(admin)
        owner_headers = login(owner)

        # Entity Admin analyzes/approves/publishes a Blueprint WITHOUT
        # assigning the Service Owner to its Service.
        blueprint_id, _analysis = self._published_blueprint(admin_headers, service_name="Owner Unassigned Service")

        register = self.client.post(
            "/api/sandbox/register", headers=owner_headers,
            json={"name": "Owner Preview", "email": f"owner-preview-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 404)

    # -- 5: Entity Admin can test an Agent within their tenant --

    def test_entity_admin_can_launch_test_agent_within_tenant(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TAAdminOK")
        blueprint_id, _analysis = self._published_blueprint(headers)
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        self.assertIn("id", journey)

    # -- 6: Cross-tenant Agent testing fails --

    def test_cross_tenant_test_agent_launch_fails(self):
        _tenant_a, _admin_a, headers_a = self._tenant_and_admin_headers("TAXA")
        _tenant_b, _admin_b, headers_b = self._tenant_and_admin_headers("TAXB")
        blueprint_id, _analysis = self._published_blueprint(headers_a, service_name="Tenant A Only")

        register = self.client.post(
            "/api/sandbox/register", headers=headers_b,
            json={"name": "Cross Tenant Preview", "email": f"cross-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 404)

    # -- 7/8/9: CONNECTED executable path, SANDBOX stays sandbox,
    # NOT_CONNECTED never executed --

    def test_connected_mapped_integration_follows_executable_path(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TAConn")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "Registry API", "status": "CONNECTED", "config": {}},
        ).json()
        blueprint_id, analysis = self._published_blueprint(headers, integration_ids=[integ["id"]])
        cap_map = analysis["agent_capability_map"]
        automated = [s for s in cap_map["step_capability_mapping"] if s["capability_status"] == "AUTOMATE"]
        if not automated:
            self.skipTest("Mock AI did not produce an AUTOMATE step for this run.")
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        planned = [a for a in journey["plan"]["actions"] if a["capability_status"] == "AUTOMATE"]
        self.assertTrue(planned)
        for action in planned:
            self.assertEqual(action["status"], "PLANNED")
            self.assertIsNotNone(action["mapped_integration"])
            self.assertFalse(action["mapped_integration"]["sandbox"])

    def test_sandbox_mapped_integration_stays_sandbox_flagged(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TASandbox")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "PAYMENT_GATEWAY", "name": "Payment Gateway", "status": "SANDBOX", "config": {}},
        ).json()
        blueprint_id, analysis = self._published_blueprint(headers, integration_ids=[integ["id"]])
        cap_map = analysis["agent_capability_map"]
        sandbox_matched = [
            s for s in cap_map["step_capability_mapping"]
            if s["capability_status"] == "AUTOMATE" and s.get("mapped_integration", {}).get("sandbox")
        ]
        if not sandbox_matched:
            self.skipTest("No step matched the SANDBOX integration for this mock run.")
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        sandbox_actions = [
            a for a in journey["plan"]["actions"]
            if a.get("mapped_integration") and a["mapped_integration"].get("sandbox")
        ]
        self.assertTrue(sandbox_actions)

    def test_not_connected_integration_never_appears_executable_in_plan(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TANotConn")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "DOCUMENT_MANAGEMENT", "name": "Document Store", "status": "NOT_CONNECTED", "config": {}},
        ).json()
        blueprint_id, analysis = self._published_blueprint(headers, integration_ids=[integ["id"]])
        cap_map = analysis["agent_capability_map"]
        for step in cap_map["step_capability_mapping"]:
            if step["capability_status"] == "AUTOMATE":
                self.assertNotEqual(step["mapped_integration"]["status"], "NOT_CONNECTED")
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        for action in journey["plan"]["actions"]:
            matched = action.get("mapped_integration")
            if matched:
                self.assertNotEqual(matched.get("status"), "NOT_CONNECTED")

    # -- 10: INTEGRATION_REQUIRED never reports fake success --

    def test_integration_required_step_never_fakes_success_in_plan(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TAIntReq")
        blueprint_id, analysis = self._published_blueprint(headers)  # no integrations linked
        cap_map = analysis["agent_capability_map"]
        required = [s for s in cap_map["step_capability_mapping"] if s["capability_status"] == "INTEGRATION_REQUIRED"]
        if not required:
            self.skipTest("No SYSTEM step produced for this mock run.")
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        blocked_actions = [a for a in journey["plan"]["actions"] if a["capability_status"] == "INTEGRATION_REQUIRED"]
        self.assertTrue(blocked_actions)
        for action in blocked_actions:
            self.assertEqual(action["status"], "INTEGRATION_REQUIRED")
            self.assertNotEqual(action["status"], "COMPLETED")

    # -- 11/12: CUSTOMER/HUMAN preserved --

    def test_customer_and_human_steps_preserved_in_plan(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TACustHuman")
        blueprint_id, analysis = self._published_blueprint(headers)
        cap_map = analysis["agent_capability_map"]
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        plan_types = {a["step_type"] for a in journey["plan"]["actions"]}
        cap_types = {s["step_type"] for s in cap_map["step_capability_mapping"]}
        self.assertEqual(plan_types, cap_types)

    # -- 13/14/15: no secrets, no chain-of-thought --

    def test_no_secrets_or_chain_of_thought_in_journey_response(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TASecrets")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "GOVERNMENT_API", "name": "Registry API", "status": "CONNECTED",
                  "config": {"endpoint": "https://example.test"}, "secret_reference": "vault://should-not-leak"},
        ).json()
        blueprint_id, _analysis = self._published_blueprint(headers, integration_ids=[integ["id"]])
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        blob = str(journey).lower()
        for forbidden in ("secret_reference", "should-not-leak", "chain_of_thought"):
            self.assertNotIn(forbidden, blob)

    # -- 16: payment confirmation/security remains intact --

    def test_execute_still_blocks_on_real_not_connected_service_integration(self):
        """The real security gate (integration_execution.py) reads the
        Service's actual configured Integrations independently of the
        plan's `integrations` display list -- confirm it still rejects a
        genuinely NOT_CONNECTED, Service-linked Integration exactly as
        before this phase's changes."""
        _tenant, _admin, headers = self._tenant_and_admin_headers("TAPaySec")
        integ = self.client.post(
            "/api/integrations", headers=headers,
            json={"type": "PAYMENT_GATEWAY", "name": "Payment Gateway", "status": "NOT_CONNECTED", "config": {}},
        ).json()
        analyze = self.client.post(
            "/api/analyze", headers=headers,
            json={"service_name": "Payment Security Service", "description": "test",
                  "integration_ids": [integ["id"]]},
        )
        self.assertEqual(analyze.status_code, 200, analyze.text)
        blueprint_id = analyze.json()["blueprint_id"]
        self.client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
        self.client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
        service_id = analyze.json()["service_id"]

        register = self.client.post(
            "/api/sandbox/register", headers=headers,
            json={"name": "Pay Sec Preview", "email": f"paysec-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint_id},
        )
        self.assertEqual(register.status_code, 200, register.text)
        customer = register.json()
        journey = self.client.post(
            "/api/journeys",
            json={"customer_id": customer["id"], "intent": "test", "blueprint_id": blueprint_id,
                  "lang": "en", "sandbox": True},
        ).json()

        approve = self.client.post(f"/api/journeys/{journey['id']}/approve")
        self.assertEqual(approve.status_code, 200, approve.text)
        execute = self.client.post(f"/api/journeys/{journey['id']}/execute")
        # A genuinely NOT_CONNECTED Service-linked Integration must still
        # block execution exactly as before -- 409 with an
        # INTEGRATION_REQUIRED-shaped detail, never a silent success.
        self.assertEqual(execute.status_code, 409, execute.text)

    # -- 17: existing capability-token security remains intact --

    def test_journey_requires_capability_or_staff_context_to_read(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TAToken")
        blueprint_id, _analysis = self._published_blueprint(headers)
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        # A brand-new, unauthenticated client with no capability cookie and
        # no staff token must not be able to read this journey.
        other_client = TestClient(main_module.app)
        r = other_client.get(f"/api/journeys/{journey['id']}")
        self.assertEqual(r.status_code, 403)

    # -- 18: legacy Blueprint (no agent_capability_map) still works --

    def test_legacy_blueprint_without_capability_map_still_produces_a_working_plan(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TALegacy")
        # Build a legacy-shaped Blueprint directly through the runtime
        # store, bypassing /api/analyze entirely -- mirrors how pre-
        # Phase-2 Blueprints are shaped (no agent_capability_map key at
        # all), same lightweight-fixture style as
        # tests/test_service_owner_scoping.py.
        blueprint = main_module.runtime_store.save_blueprint(
            {"service_name": "Legacy Service", "lang": "en"},
            {
                "service": {"service_name": "Legacy Service"},
                "redesign": {
                    "future_steps": [{"step_number": 1, "name": "Legacy step", "assistant_action": "Do the thing"}],
                    "required_integrations": [{"status": "PROPOSED", "description": "Some legacy integration"}],
                },
            },
            tenant_id=_tenant["id"],
        )
        main_module.runtime_store.set_blueprint_status(blueprint["id"], "APPROVED", tenant_id=_tenant["id"])
        main_module.runtime_store.set_blueprint_status(blueprint["id"], "PUBLISHED", tenant_id=_tenant["id"])

        register = self.client.post(
            "/api/sandbox/register", headers=headers,
            json={"name": "Legacy Preview", "email": f"legacy-{uuid.uuid4().hex[:8]}@test.local",
                  "blueprint_id": blueprint["id"]},
        )
        self.assertEqual(register.status_code, 200, register.text)
        customer = register.json()
        journey = self.client.post(
            "/api/journeys",
            json={"customer_id": customer["id"], "intent": "test legacy", "blueprint_id": blueprint["id"],
                  "lang": "en", "sandbox": True},
        )
        self.assertEqual(journey.status_code, 200, journey.text)
        body = journey.json()
        self.assertTrue(body["plan"]["actions"])
        self.assertEqual(body["plan"]["actions"][0]["title"], "Legacy step")
        self.assertTrue(body["plan"]["integrations"])
        self.assertEqual(body["plan"]["integrations"][0]["description"], "Some legacy integration")

    # -- 22/23: existing Test Agent flow and Publish flow unaffected --

    def test_existing_test_agent_and_publish_flow_both_still_succeed(self):
        _tenant, _admin, headers = self._tenant_and_admin_headers("TAFullFlow")
        blueprint_id, _analysis = self._published_blueprint(headers)
        _customer, journey = self._register_and_start_journey(headers, blueprint_id)
        self.assertIn("plan", journey)

        publish_agent = self.client.post(
            "/api/agents/publish", json={"blueprint_id": blueprint_id}, headers=headers
        )
        self.assertEqual(publish_agent.status_code, 200, publish_agent.text)
        slug = publish_agent.json()["published_slug"]
        tenant_slug, agent_slug = slug.split("/", 1)
        public = self.client.get(f"/service/{tenant_slug}/{agent_slug}")
        self.assertEqual(public.status_code, 200, public.text)
        self.assertNotIn("agent_capability_map", public.json()["result"])


if __name__ == "__main__":
    unittest.main()
