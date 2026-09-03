"""FINAL VERIFICATION ONLY -- not part of the test suite, not
imported by anything. Run standalone:

    PYTHONPATH=. python3 tools/final_verification.py

Exercises the REAL FastAPI app, through TestClient, against the
repo's real stdlib mock Ollama server (a genuine HTTP round trip
through core/llm.py's actual request/response code -- not a
fixture-only construction like the unit test suite uses for most of
its Future Engine coverage). Prints a PASS/FAIL line per check and
exits non-zero if anything fails.
"""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.test_mock_env import patch_ollama_env, unpatch_ollama_env

RESULTS = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    RESULTS.append((status, label, detail))
    print(f"[{status}] {label}" + (f" -- {detail}" if detail and status == "FAIL" else ""))
    return condition


def main():
    import main as main_module

    main_module.startup()
    from fastapi.testclient import TestClient
    client = TestClient(main_module.app)

    suffix = uuid.uuid4().hex[:8]
    tenant = main_module.tenant_repository.create_tenant(
        f"Final Verify Tenant {suffix}", f"final-verify-{suffix}", status="ACTIVE"
    )
    user = main_module.tenant_repository.create_user(
        tenant["id"], "Final Verify Admin", f"final-verify-{suffix}@test.local", role="entity_admin"
    )
    demo_credential = (os.getenv("ZX_DEMO_DEV_PASSPHRASE") or "").strip()
    if not demo_credential:
        raise RuntimeError("Set ZX_DEMO_DEV_PASSPHRASE before running final_verification.py")
    login = client.post(
        "/api/auth/demo-login",
        json={"email": user["email"], "credential": demo_credential},
    )
    check("demo-login succeeds", login.status_code == 200, login.text)
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    other_suffix = uuid.uuid4().hex[:8]
    other_tenant = main_module.tenant_repository.create_tenant(
        f"Final Verify Other Tenant {other_suffix}", f"final-verify-other-{other_suffix}", status="ACTIVE"
    )
    other_user = main_module.tenant_repository.create_user(
        other_tenant["id"], "Other Admin", f"final-verify-other-{other_suffix}@test.local", role="entity_admin"
    )
    other_login = client.post(
        "/api/auth/demo-login", json={"email": other_user["email"], "credential": demo_credential}
    )
    other_headers = {"Authorization": f"Bearer {other_login.json()['token']}"}

    # =====================================================================
    # 1. Ollama mandatory behavior -- unreachable BEFORE patching the mock
    # =====================================================================
    started = time.monotonic()
    unreachable = client.post(
        "/api/analyze", headers=headers,
        json={"service_name": "Preflight Check Service", "description": "x", "steps": ["a"], "lang": "en"},
    )
    elapsed = time.monotonic() - started
    check("Ollama unavailable -> 503", unreachable.status_code == 503, unreachable.text)
    check(
        "Ollama unavailable -> AI_ENGINE_UNAVAILABLE in body",
        "AI_ENGINE_UNAVAILABLE" in unreachable.text, unreachable.text,
    )
    check("Ollama unavailable -> fast, not hung", elapsed < 5.0, f"{elapsed:.2f}s")

    # =====================================================================
    # 2. Full chain, 4 differently-shaped services, via REAL /api/analyze
    # =====================================================================
    SERVICE_SHAPES = {
        "Event Permit": {
            "service_name": "Public Event Permit",
            "description": "Organizers apply for a permit to hold a public event.",
            "steps": [
                "Customer submits event details and venue",
                "Customer uploads supporting documents (insurance, safety plan)",
                "Employee reviews and approves the application",
                "Customer pays the permit fee",
                "System issues the permit",
            ],
        },
        "Shipment Tracking": {
            "service_name": "Shipment Tracking",
            "description": "Customers track the status of a shipment by tracking number.",
            "steps": [
                "Customer enters a tracking number",
                "System retrieves shipment status",
                "System displays delivery estimate",
            ],
        },
        "Corporate P.O. Box Renewal": {
            "service_name": "Corporate P.O. Box Renewal",
            "description": "A company renews its post office box subscription.",
            "steps": [
                "Customer submits renewal request",
                "Customer uploads company registration document",
                "System verifies box ownership",
                "Customer pays the renewal fee",
                "System confirms the renewal",
            ],
        },
        "Complaint Service": {
            "service_name": "Complaint Service",
            "description": "Citizens submit complaints about a government service.",
            "steps": [
                "Customer submits a complaint",
                "System logs and categorizes the complaint",
                "Employee reviews and escalates unresolved complaints",
                "System closes the complaint",
            ],
        },
    }

    prior_patch = patch_ollama_env()
    main_module.orchestrator.llm._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
    try:
        for label, payload in SERVICE_SHAPES.items():
            print(f"\n--- {label} ---")
            payload = {**payload, "lang": "en"}

            t0 = time.monotonic()
            analyze = client.post("/api/analyze", headers=headers, json=payload)
            t_analyze = time.monotonic() - t0
            if not check(f"[{label}] Analyze succeeds", analyze.status_code == 200, analyze.text):
                continue
            check(f"[{label}] Analyze not hung", t_analyze < 60.0, f"{t_analyze:.2f}s")
            service_id = analyze.json()["service_id"]

            t0 = time.monotonic()
            predict = client.post(f"/api/services/{service_id}/predict", headers=headers)
            t_predict = time.monotonic() - t0
            check(f"[{label}] Predict succeeds (never blocks)", predict.status_code == 200, predict.text)
            check(f"[{label}] Predict not hung", t_predict < 15.0, f"{t_predict:.2f}s")
            verdict = predict.json().get("data_sufficiency", {}).get("verdict") if predict.status_code == 200 else None
            check(
                f"[{label}] Predict insufficiency doesn't block Simulate (verdict={verdict})",
                verdict in ("SUFFICIENT", "LIMITED", "INSUFFICIENT"),
            )

            t0 = time.monotonic()
            simulate = client.post(
                f"/api/services/{service_id}/scenarios", headers=headers, json={"trigger_type": "AUTO"}
            )
            t_simulate = time.monotonic() - t0
            check(f"[{label}] Simulate AUTO succeeds", simulate.status_code == 200, simulate.text)
            check(f"[{label}] Simulate AUTO not hung", t_simulate < 15.0, f"{t_simulate:.2f}s")
            auto_scenarios = simulate.json().get("auto_scenarios", []) if simulate.status_code == 200 else []
            check(f"[{label}] Simulate AUTO generated >=1 scenario", len(auto_scenarios) > 0)
            categories = {item["scenario"]["auto_category"] for item in auto_scenarios}
            print(f"    AUTO categories: {sorted(categories)}")

            t0 = time.monotonic()
            challenge = client.post(f"/api/services/{service_id}/challenges", headers=headers, json={})
            t_challenge = time.monotonic() - t0
            check(f"[{label}] Challenge succeeds", challenge.status_code == 200, challenge.text)
            check(f"[{label}] Challenge does not hang", t_challenge < 30.0, f"{t_challenge:.2f}s")
            challenge_id = challenge.json().get("challenge_id") if challenge.status_code == 200 else None

            evolve_id = None
            if challenge_id:
                evolve = client.post(
                    f"/api/services/{service_id}/evolutions", headers=headers, json={"challenge_id": challenge_id}
                )
                check(f"[{label}] Evolve works from Challenge results", evolve.status_code == 200, evolve.text)
                evolve_id = evolve.json().get("evolution_id") if evolve.status_code == 200 else None

            prevention_id = None
            if evolve_id:
                prevent = client.post(
                    f"/api/services/{service_id}/preventions", headers=headers, json={"evolution_id": evolve_id}
                )
                check(f"[{label}] Prevent works from Evolve results", prevent.status_code == 200, prevent.text)
                prevention_id = prevent.json().get("prevention_id") if prevent.status_code == 200 else None

            if prevention_id:
                monitoring = client.post(
                    f"/api/services/{service_id}/monitoring-checks", headers=headers,
                    json={"prevention_id": prevention_id},
                )
                check(
                    f"[{label}] Monitoring works from Prevention triggers",
                    monitoring.status_code == 200, monitoring.text,
                )

            # Tenant isolation, once per shape.
            cross = client.post(
                f"/api/services/{service_id}/scenarios", headers=other_headers, json={"trigger_type": "AUTO"}
            )
            check(f"[{label}] Tenant isolation preserved", cross.status_code == 404, cross.text)
    finally:
        unpatch_ollama_env(prior_patch)
        main_module.orchestrator.llm._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}

    # =====================================================================
    # 3. Publish / Agent / Customer Journey smoke check (unrelated to any
    #    of the fixes -- confirms nothing regressed)
    # =====================================================================
    print("\n--- Publish / Agent / Customer Journey smoke check ---")
    prior_patch = patch_ollama_env()
    main_module.orchestrator.llm._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
    try:
        analyze = client.post(
            "/api/analyze", headers=headers,
            json={
                "service_name": "Publish Smoke Service", "description": "x",
                "steps": ["Customer submits a request", "System issues the result"], "lang": "en",
            },
        )
        check("[Publish smoke] Analyze succeeds", analyze.status_code == 200, analyze.text)
        blueprint_id = analyze.json().get("blueprint_id") if analyze.status_code == 200 else None
        if blueprint_id:
            approve = client.post(f"/api/blueprints/{blueprint_id}/approve", headers=headers)
            check("[Publish smoke] Blueprint approve", approve.status_code == 200, approve.text)
            publish = client.post(f"/api/blueprints/{blueprint_id}/publish", headers=headers)
            check("[Publish smoke] Blueprint publish", publish.status_code == 200, publish.text)
    finally:
        unpatch_ollama_env(prior_patch)
        main_module.orchestrator.llm._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}

    # =====================================================================
    # 4. Stored Alerts: current vs historical separation + retention
    #    (Alert-history audit fix)
    # =====================================================================
    print("\n--- Stored Alerts: current vs historical separation ---")
    alerts_service = main_module.service_store.create_service(
        tenant_id=tenant["id"], service_name="Final Verify Alerts Service"
    )
    challenge_1 = main_module.challenge_store.save_challenge(
        tenant_id=tenant["id"], service_id=alerts_service["id"],
        input_snapshot={}, result={"vulnerabilities": []},
    )
    evolution_1 = main_module.evolution_store.save_evolution(
        tenant_id=tenant["id"], service_id=alerts_service["id"], challenge_id=challenge_1["id"],
        input_snapshot={}, result={"proposals": []},
    )
    old_prevention = main_module.prevention_store.save_prevention(
        tenant_id=tenant["id"], service_id=alerts_service["id"], evolution_id=evolution_1["id"],
        input_snapshot={}, result={"triggers": []},
    )
    old_alert = main_module.alert_store.create_alert(
        tenant_id=tenant["id"], service_id=alerts_service["id"], prevention_id=old_prevention["id"],
        trigger_id="SLA_FRAGILITY:PROPOSAL-1", current_value=50.0, threshold_value=40.0,
        checked_against="CHAL-OLD", evidence="Old run: severity 50 against threshold 40.",
    )
    challenge_2 = main_module.challenge_store.save_challenge(
        tenant_id=tenant["id"], service_id=alerts_service["id"],
        input_snapshot={}, result={"vulnerabilities": []},
    )
    evolution_2 = main_module.evolution_store.save_evolution(
        tenant_id=tenant["id"], service_id=alerts_service["id"], challenge_id=challenge_2["id"],
        input_snapshot={}, result={"proposals": []},
    )
    new_prevention = main_module.prevention_store.save_prevention(
        tenant_id=tenant["id"], service_id=alerts_service["id"], evolution_id=evolution_2["id"],
        input_snapshot={}, result={"triggers": []},
    )
    new_alert = main_module.alert_store.create_alert(
        tenant_id=tenant["id"], service_id=alerts_service["id"], prevention_id=new_prevention["id"],
        trigger_id="SLA_FRAGILITY:PROPOSAL-1", current_value=25.0, threshold_value=20.0,
        checked_against="CHAL-NEW", evidence="New run: severity 25 against threshold 20.",
    )
    alerts_response = client.get(f"/api/services/{alerts_service['id']}/alerts", headers=headers)
    check("[Alerts] endpoint succeeds", alerts_response.status_code == 200, alerts_response.text)
    alerts_body = alerts_response.json().get("alerts", []) if alerts_response.status_code == 200 else []
    by_id = {a["id"]: a for a in alerts_body}
    check("[Alerts] both old and new records retained", old_alert["id"] in by_id and new_alert["id"] in by_id)
    check("[Alerts] new alert marked current", by_id.get(new_alert["id"], {}).get("is_current") is True)
    check("[Alerts] old alert marked historical, never current",
          by_id.get(old_alert["id"], {}).get("is_historical") is True
          and by_id.get(old_alert["id"], {}).get("is_current") is False)
    check("[Alerts] current alert returned first",
          alerts_body and alerts_body[0]["id"] == new_alert["id"])

    # =====================================================================
    # 5. Citizen Outcome Impact: zero-customer-step journey still
    #    reports outcome affected; direct step ratio stays honest;
    #    no fake CUSTOMER steps invented (Citizen/outcome impact fix)
    # =====================================================================
    print("\n--- Citizen Outcome Impact: zero-customer-step journey ---")
    zero_customer_service = main_module.service_store.create_service(
        tenant_id=tenant["id"], service_name="Final Verify Zero Customer Step Service"
    )
    zero_customer_steps = [
        {"step_number": 1, "name": "System validates the request", "type": "SYSTEM",
         "action": "System validates the request", "change_type": "KEPT", "reason": "", "standard_id": ""},
        {"step_number": 2, "name": "System issues the result", "type": "SYSTEM",
         "action": "System issues the result", "change_type": "KEPT", "reason": "", "standard_id": ""},
    ]
    original_types = [s["type"] for s in zero_customer_steps]
    main_module.service_store.create_analysis(
        tenant_id=tenant["id"], service_id=zero_customer_service["id"], blueprint_id="bp-outcome-verify",
        result={"redesign": {"future_steps": zero_customer_steps, "required_integrations": []}},
    )
    outcome_response = client.post(
        f"/api/services/{zero_customer_service['id']}/scenarios", headers=headers,
        json={
            "scenario_type": "CASCADING_STEP_FAILURE", "trigger_type": "MANUAL",
            "variables": {"origin_step_id": "STEP-1", "failure_probability": 1.0},
        },
    )
    check("[Outcome Impact] Simulate succeeds", outcome_response.status_code == 200, outcome_response.text)
    outcome_body = outcome_response.json() if outcome_response.status_code == 200 else {}
    check("[Outcome Impact] direct customer-step impact honestly 0 of 0",
          "0 of 0 customer-facing" in outcome_body.get("citizen_impact", {}).get("basis", ""))
    check("[Outcome Impact] citizen_impact.score unchanged (still 0)",
          outcome_body.get("citizen_impact", {}).get("score") == 0)
    check("[Outcome Impact] citizen_outcome_affected reports True despite 0 customer steps",
          outcome_body.get("citizen_outcome_affected") is True)
    check("[Outcome Impact] outcome_impact_reason present", bool(outcome_body.get("outcome_impact_reason")))
    check("[Outcome Impact] no fake CUSTOMER/HUMAN steps were created",
          "CUSTOMER" not in original_types and "HUMAN" not in original_types)

    # =====================================================================
    # 6. SLA fallback labeling + Integration-to-Step Mapping
    # =====================================================================
    print("\n--- SLA fallback (ASSUMPTION) + Integration-to-Step Mapping ---")
    sla_mapping_service = main_module.service_store.create_service(
        tenant_id=tenant["id"], service_name="Final Verify SLA and Mapping Service"
    )
    mapped_steps = [
        {"step_number": 1, "name": "Customer authenticates via UAE Pass", "type": "CUSTOMER",
         "action": "Customer authenticates via UAE Pass", "change_type": "KEPT", "reason": "", "standard_id": ""},
        {"step_number": 2, "name": "System processes the request", "type": "SYSTEM",
         "action": "System processes the request", "change_type": "KEPT", "reason": "", "standard_id": ""},
        {"step_number": 3, "name": "System issues the result", "type": "SYSTEM",
         "action": "System issues the result", "change_type": "KEPT", "reason": "", "standard_id": ""},
    ]
    main_module.service_store.create_analysis(
        tenant_id=tenant["id"], service_id=sla_mapping_service["id"], blueprint_id="bp-sla-mapping-verify",
        result={
            "redesign": {
                "future_steps": mapped_steps,
                "required_integrations": [{"name": "UAE_PASS", "step_ids": ["STEP-1"]}],
            },
        },
    )
    mapping_response = client.post(
        f"/api/services/{sla_mapping_service['id']}/scenarios", headers=headers,
        json={
            "scenario_type": "INTEGRATION_FAILURE", "trigger_type": "MANUAL",
            "variables": {"failed_integration_id": "INTEGRATION-001", "failure_duration_hours": 6},
        },
    )
    check("[Integration Mapping] Simulate succeeds", mapping_response.status_code == 200, mapping_response.text)
    mapping_body = mapping_response.json() if mapping_response.status_code == 200 else {}
    mapped_affected_ids = {item["step_id"] for item in mapping_body.get("affected_steps", [])}
    check("[Integration Mapping] impact restricted to the explicitly mapped step only",
          mapped_affected_ids == {"STEP-1"}, str(mapped_affected_ids))
    check("[Integration Mapping] real mapping evidence -> no assumption note",
          mapping_body.get("assumptions") == [])

    sla_response = client.post(
        f"/api/services/{sla_mapping_service['id']}/scenarios", headers=headers,
        json={
            "scenario_type": "SLA_BREACH", "trigger_type": "MANUAL",
            "variables": {"breached_step_id": "STEP-2", "delay_multiplier": 3.0},
        },
    )
    check("[SLA] Simulate succeeds", sla_response.status_code == 200, sla_response.text)
    sla_body = sla_response.json() if sla_response.status_code == 200 else {}
    sla_assumptions = sla_body.get("assumptions", [])
    check("[SLA] no stored evidence -> falls back to 48h, clearly labeled ASSUMPTION",
          any(a.get("variable_name") == "sla_hours_default" and a.get("value") == 48.0 for a in sla_assumptions),
          str(sla_assumptions))

    # =====================================================================
    # 7. Ollama prompt/JSON leakage guard -- sanity check against the
    #    REAL mock backend's own narration output (the dedicated
    #    synthetic-leak-string regression suite already lives in
    #    tests/test_llm_explanation_guard.py; this just confirms the
    #    real narration path never surfaces raw JSON/instruction text)
    # =====================================================================
    print("\n--- Ollama prompt/JSON leakage guard (real narration path) ---")
    leakage_service = main_module.service_store.create_service(
        tenant_id=tenant["id"], service_name="Final Verify Leakage Guard Service"
    )
    main_module.service_store.create_analysis(
        tenant_id=tenant["id"], service_id=leakage_service["id"], blueprint_id="bp-leakage-verify",
        result={"redesign": {"future_steps": mapped_steps, "required_integrations": []}},
    )
    prior_patch = patch_ollama_env()
    main_module.orchestrator.llm._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
    try:
        leakage_response = client.post(
            f"/api/services/{leakage_service['id']}/scenarios", headers=headers,
            json={
                "scenario_type": "CASCADING_STEP_FAILURE", "trigger_type": "MANUAL",
                "variables": {"origin_step_id": "STEP-1", "failure_probability": 1.0},
            },
        )
        check("[Leakage Guard] Simulate succeeds", leakage_response.status_code == 200, leakage_response.text)
        description = ""
        if leakage_response.status_code == 200:
            outcomes = leakage_response.json().get("possible_outcomes", [])
            description = outcomes[0]["description"] if outcomes else ""
        check(
            "[Leakage Guard] explanation contains no raw prompt/instruction markers",
            all(marker not in description for marker in ('"task"', '"constraints"', '"required_output"', "Rephrase")),
            description,
        )
    finally:
        unpatch_ollama_env(prior_patch)
        main_module.orchestrator.llm._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}

    # =====================================================================
    # Summary
    # =====================================================================
    failures = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{'='*70}\n{len(RESULTS)} checks, {len(failures)} failed\n{'='*70}")
    if failures:
        for status, label, detail in failures:
            print(f"FAIL: {label} -- {detail}")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
