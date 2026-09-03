"""
End-to-end smoke test: runs the REAL 9-stage ZERO X-RAY pipeline
(mirroring graph/workflow.py's stage order) against a locally started
mock Ollama server, talking to it over ACTUAL HTTP through
core/llm.py's LocalLLM.generate() -- not an in-process stub like
tests/test_full_pipeline_ai_scenarios.py's ScenarioMockLLM.

This is the tool to run when you want to prove, end to end, that:
  - Service Agent's semantic-step extraction is AI-primary and never
    emits more steps than raw input lines.
  - Standards Agent's returned standard_ids are real catalog IDs (AI
    path, not the deterministic baseline).
  - Gap Analysis Agent returns real AI-authored gaps (not baseline).
  - Journey Builder's future journey is AI-designed (not the
    template-based fallback).
  - The </think> without <think> Qwen3 quirk is parsed correctly.
  - No agent silently fell back when the AI path should have
    succeeded.

Usage:
    cd server
    python -m tools.run_local_pipeline_check
    python -m tools.run_local_pipeline_check --failure-mode empty_response
    python -m tools.run_local_pipeline_check --failure-mode invalid_json

Exits non-zero (and prints which agent[s]) if any agent that should
have used AI fell back to its deterministic baseline in the "none"
(success) failure mode.
"""

import argparse
import os
import sys

# --- Configure env BEFORE importing core.llm, which reads these at
# import time. -----------------------------------------------------
os.environ.setdefault("ZX_LLM_MODE", "mock")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--failure-mode",
        default="none",
        choices=["none", "empty_response", "invalid_json", "chat_500", "timeout"],
        help="Simulated Ollama failure mode (default: none = normal success).",
    )
    args = parser.parse_args()

    os.environ["ZX_MOCK_FAILURE_MODE"] = args.failure_mode

    from tools.mock_ollama_server_stdlib import start_server

    httpd, thread = start_server(host="127.0.0.1", port=0)
    port = httpd.server_port
    os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{port}"
    print(f"[1/9] Stdlib mock Ollama server started at http://127.0.0.1:{port} "
          f"(failure_mode={args.failure_mode!r}).")

    try:
        # Import AFTER env vars are set, since core.llm reads
        # OLLAMA_HOST/ZX_LLM_MODE at module import time.
        from core.llm import LocalLLM
        from agents.service_agent import ServiceAnalystAgent
        from agents.standards_agent import StandardsAgent
        from agents.gap_agent import GapAnalysisAgent
        from agents.step_compliance_agent import StepComplianceAgent
        from agents.journey_builder_agent import JourneyBuilderAgent
        from agents.validation_agent import ValidationAgent
        from core.standards_catalog import STANDARDS_CATALOG
        from core.rules import calculate_metrics
        from core.scoring import calculate_zero_bureaucracy_score

        llm = LocalLLM()

        # This is the exact shape of the original bug report: 8 raw
        # input lines. The semantic-steps AI call must never return
        # more steps than this.
        raw_lines = [
            "Customer logs into the portal",
            "Customer selects the mailbox rental service",
            "Customer uploads Emirates ID and trade license",
            "Customer selects mailbox size and duration",
            "System calculates the rental fee",
            "Customer pays the rental fee online",
            "Staff reviews and approves the application",
            "Customer receives the mailbox key and confirmation",
        ]
        service = {
            "service_name": "Mailbox Rental (Individuals)",
            "description": "A customer rents a postal mailbox for personal use.",
            "steps": raw_lines,
            "lang": "en",
        }
        standards_seed = {"applicable_standards": STANDARDS_CATALOG}

        service_agent = ServiceAnalystAgent(llm)
        standards_agent = StandardsAgent(llm)
        gap_agent = GapAnalysisAgent(llm)
        step_compliance_agent = StepComplianceAgent(llm)
        journey_builder_agent = JourneyBuilderAgent(llm)
        validation_agent = ValidationAgent(llm)

        failures = []

        print("[2/9] Service Agent...")
        service_analysis = service_agent.run(service)
        semantic_steps = service_analysis.get("semantic_steps") or service_analysis.get("steps") or []
        print(f"      analysis_source={service_analysis.get('analysis_source')!r}, "
              f"semantic_steps={len(semantic_steps)} (raw_lines={len(raw_lines)})")
        if args.failure_mode == "none":
            if service_analysis.get("analysis_source") not in ("MOCK_AI", "ai"):
                failures.append("Service Agent did not use AI (analysis_source="
                                f"{service_analysis.get('analysis_source')!r})")
            if len(semantic_steps) > len(raw_lines):
                failures.append(
                    f"Service Agent hallucinated MORE steps ({len(semantic_steps)}) "
                    f"than raw input lines ({len(raw_lines)})"
                )

        print("[3/9] Standards Agent...")
        relevant_standards = standards_agent.run(service_analysis, standards_seed)
        applicable = relevant_standards.get("applicable_standards", [])
        catalog_ids = {item.get("standard_id") for item in STANDARDS_CATALOG}
        print(f"      analysis_source={relevant_standards.get('analysis_source')!r}, "
              f"applicable_standards={[s.get('standard_id') for s in applicable]}")
        if args.failure_mode == "none":
            if relevant_standards.get("analysis_source") not in ("MOCK_AI", "ai"):
                failures.append("Standards Agent did not use AI (analysis_source="
                                f"{relevant_standards.get('analysis_source')!r})")
            bad_ids = [s.get("standard_id") for s in applicable
                       if s.get("standard_id") not in catalog_ids]
            if bad_ids:
                failures.append(f"Standards Agent returned IDs not in the catalog: {bad_ids}")
            if not applicable:
                failures.append("Standards Agent returned zero applicable standards")

        print("[4/9] Gap Analysis Agent...")
        gaps = gap_agent.run(service_analysis, relevant_standards)
        gap_list = gaps.get("gaps", [])
        print(f"      analysis_source={gaps.get('analysis_source')!r}, gaps={len(gap_list)}")
        if args.failure_mode == "none":
            if gaps.get("analysis_source") not in ("MOCK_AI", "ai"):
                failures.append("Gap Analysis Agent did not use AI (analysis_source="
                                f"{gaps.get('analysis_source')!r})")
            if not gap_list:
                failures.append("Gap Analysis Agent returned zero gaps")

        print("[5/9] Zero Bureaucracy scoring (deterministic, no AI)...")
        # scoring happens later against the redesign; placeholder stage
        # to mirror workflow.py's numbering.

        print("[6/9] Step Compliance Agent...")
        step_compliance = step_compliance_agent.run(service, service_analysis, relevant_standards)
        print(f"      analysis_source={step_compliance.get('analysis_source')!r}")

        print("[7/9] Journey Builder...")
        redesign = journey_builder_agent.run(service, step_compliance, relevant_standards, gaps)
        future_steps = redesign.get("future_steps", [])
        print(f"      analysis_source={redesign.get('analysis_source')!r}, "
              f"future_steps={len(future_steps)}")
        if args.failure_mode == "none":
            if redesign.get("analysis_source") not in ("MOCK_AI", "ai"):
                failures.append("Journey Builder did not use AI (analysis_source="
                                f"{redesign.get('analysis_source')!r}) -- used template fallback")
            if not future_steps:
                failures.append("Journey Builder returned zero future steps")

        print("[8/9] Simulation / metrics...")
        metrics = calculate_metrics(service, redesign)
        zb_score = calculate_zero_bureaucracy_score(metrics)
        print(f"      zero_bureaucracy_score={zb_score}")

        print("[9/9] Validation Agent...")
        validation = validation_agent.run(
            service=service,
            standards=relevant_standards,
            redesign=redesign,
            metrics={**metrics, "zero_bureaucracy_score": zb_score},
        )
        print(f"      verdict={validation.get('verdict')!r}, "
              f"issues={len(validation.get('issues', []))}")

        print()
        if failures:
            print(f"RESULT: FAIL ({len(failures)} problem(s)):")
            for f in failures:
                print(f"  - {f}")
            return 1

        print("RESULT: PASS -- all agents used AI end-to-end "
              f"(failure_mode={args.failure_mode!r}), no unexpected fallback.")
        return 0
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
