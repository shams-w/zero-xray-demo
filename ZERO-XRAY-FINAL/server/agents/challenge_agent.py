"""ChallengeAgent -- Step 3 ("Challenge") of the ZERO X-RAY ->
Government Future Engine evolution.

DOES NOT CREATE A SECOND SIMULATION ENGINE. Every case this agent
generates is executed by calling agents/future_simulation_agent.py's
own already-tested `build_service_graph()` / `validate_scenario()` /
`run()` directly -- unmodified, unimported-around. Challenge adds
exactly two things Simulate doesn't have on its own: (1) systematic,
fixed-rule GENERATION of many scenarios instead of one caller-
supplied scenario, and (2) deterministic ANALYSIS of the resulting
outputs into ranked vulnerabilities. Neither is new execution
machinery.

======================================================================
WHY THIS IS ADVERSARIAL TESTING AND NOT "LLM, LIST SOME RISKS"
======================================================================
Nothing about which cases run, how they run, or what counts as a
vulnerability is decided per-request or by a model call:
  - WHICH CASES RUN is fixed by CHALLENGE_STRATEGIES, a closed set of
    4 generation functions, each a simple loop over real stored data
    (`service_graph["steps"]` / `service_graph["integrations"]`) with
    fixed constants. Same graph -> same case list, same case_ids
    (`f"{strategy}:{target}"`, never a random UUID), same order.
  - HOW EACH CASE RUNS is FutureSimulationAgent.run() -- already
    proven deterministic by tests/test_future_simulation_agent.py.
  - WHAT COUNTS AS A VULNERABILITY is a fixed set of threshold rules
    (VULNERABILITY_RULES section below) over Simulate's own already-
    computed numbers -- a comparison against named constants, never a
    judgement call.
  - RANKING is a stable sort with an explicit, documented tie-break
    (`_rank_vulnerabilities`).
Given the same service graph, stored data, strategies and constants,
repeated Challenge runs produce identical case_ids, identical
affected steps, identical vulnerabilities, identical severities, and
identical ranking -- see
tests/test_challenge_agent.py::test_repeated_run_is_identical.

======================================================================
GROUNDING -- CHALLENGE NEVER RE-TAGS, ONLY RELAYS
======================================================================
Every vulnerability's `evidence` list is copied directly from its
source case's own SimulationOutput (`assumptions`, `likelihood_source`,
`citizen_impact`/`government_impact` basis strings) -- this file has
no code path that changes a FACT/PREDICTION/ASSUMPTION tag, only code
that aggregates and re-displays tags FutureSimulationAgent already
assigned. This is the concrete mechanism behind "never silently
convert an assumption into a fact."

======================================================================
SEVERITY -- DETERMINISTIC ENGINEERING RULES, NOT STATISTICAL FACTS
======================================================================
Every severity value below is either copied directly from a source
case's own already-bounded (core.scoring.clamp) score, or a max/mean
of such scores -- never a new, separately-invented number. Thresholds
(SPOF_RATIO_THRESHOLD, CRITICAL_PATH_MIN_CASE_COUNT,
CUSTOMER_EXPOSURE_THRESHOLD) and stress constants are named,
documented engineering defaults, exactly as flagged for Simulate's
own scores -- not statistically validated cutoffs.
"""

import re
from datetime import datetime, timezone
from core.result_provenance import provenance_for_mixed_result
from core.backend_language import normalize_lang

from agents.future_simulation_agent import ScenarioValidationError
from core.score_methodology import SCORE_METHODOLOGY_MARKER
from core.llm_explanation_guard import is_placeholder_or_generic, extract_clean_explanation


# =====================================================================
# CHALLENGE STRATEGIES -- closed set, fixed constants, no randomness
# =====================================================================
CHALLENGE_STRATEGIES = {
    "EXHAUSTIVE_STEP_FAILURE",
    "EXHAUSTIVE_INTEGRATION_FAILURE",
    "SLA_STRESS",
    "DEMAND_STRESS",
}

# Named, documented stress constants -- engineering defaults chosen to
# represent a worst-plausible-case stress test, not statistically
# derived values.
CHALLENGE_WORST_CASE_PROBABILITY = 1.0
CHALLENGE_INTEGRATION_FAILURE_DURATION_HOURS = 24.0
CHALLENGE_SLA_STRESS_MULTIPLIER = 3.0
CHALLENGE_DEMAND_STRESS_MULTIPLIER = 5.0
CHALLENGE_DEMAND_STRESS_HORIZON_DAYS = 30.0

# =====================================================================
# VULNERABILITY DERIVATION THRESHOLDS -- named, documented, fixed
# =====================================================================
SPOF_RATIO_THRESHOLD = 0.5
CRITICAL_PATH_MIN_CASE_COUNT = 2
CUSTOMER_EXPOSURE_THRESHOLD = 50.0

CUSTOMER_FACING_STEP_TYPES = {"CUSTOMER", "HUMAN"}

# Only the top-K ranked vulnerabilities are ever offered to the LLM
# for phrasing -- keeps LLM cost flat regardless of how large the
# case set grows, and keeps determinism of ranking wholly unaffected
# by whether an LLM is configured at all.
CHALLENGE_EXPLANATION_TOP_K = 10


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class ChallengeAgent:

    def __init__(self, future_simulation_agent, llm=None, lang="en"):
        """`future_simulation_agent` is a real FutureSimulationAgent
        instance -- Challenge never constructs its own copy of
        simulation logic, it is handed the one the caller already
        built (main.py) and calls its public methods directly."""
        self.simulation_agent = future_simulation_agent
        self.llm = llm
        self.lang = normalize_lang(lang)

    # =================================================================
    # 1. DETERMINISTIC CASE GENERATION
    # =================================================================

    def generate_cases(self, strategies, service_graph):
        cases = []
        strategies = list(strategies) if strategies else sorted(CHALLENGE_STRATEGIES)
        # Iterate in a fixed, sorted order regardless of caller-supplied
        # order, so case order never depends on request formatting.
        for strategy in sorted(set(strategies)):
            if strategy not in CHALLENGE_STRATEGIES:
                raise ScenarioValidationError(
                    f"Unknown challenge strategy '{strategy}'. Must be one of: "
                    f"{sorted(CHALLENGE_STRATEGIES)}."
                )
            if strategy == "EXHAUSTIVE_STEP_FAILURE":
                for step in service_graph["steps"]:
                    cases.append({
                        "case_id": f"EXHAUSTIVE_STEP_FAILURE:{step['step_id']}",
                        "strategy": strategy,
                        "scenario_type": "CASCADING_STEP_FAILURE",
                        "target": step["step_id"],
                        "variables": {
                            "origin_step_id": step["step_id"],
                            "failure_probability": CHALLENGE_WORST_CASE_PROBABILITY,
                        },
                    })
            elif strategy == "EXHAUSTIVE_INTEGRATION_FAILURE":
                for integration in service_graph["integrations"]:
                    cases.append({
                        "case_id": f"EXHAUSTIVE_INTEGRATION_FAILURE:{integration['integration_id']}",
                        "strategy": strategy,
                        "scenario_type": "INTEGRATION_FAILURE",
                        "target": integration["integration_id"],
                        "variables": {
                            "failed_integration_id": integration["integration_id"],
                            "failure_duration_hours": CHALLENGE_INTEGRATION_FAILURE_DURATION_HOURS,
                        },
                    })
            elif strategy == "SLA_STRESS":
                for step in service_graph["steps"]:
                    cases.append({
                        "case_id": f"SLA_STRESS:{step['step_id']}",
                        "strategy": strategy,
                        "scenario_type": "SLA_BREACH",
                        "target": step["step_id"],
                        "variables": {
                            "breached_step_id": step["step_id"],
                            "delay_multiplier": CHALLENGE_SLA_STRESS_MULTIPLIER,
                        },
                    })
            elif strategy == "DEMAND_STRESS":
                cases.append({
                    "case_id": "DEMAND_STRESS:SERVICE",
                    "strategy": strategy,
                    "scenario_type": "VOLUME_SURGE",
                    "target": None,
                    "variables": {
                        "demand_multiplier": CHALLENGE_DEMAND_STRESS_MULTIPLIER,
                        "time_horizon_days": CHALLENGE_DEMAND_STRESS_HORIZON_DAYS,
                    },
                })
        return cases

    # =================================================================
    # 2. EXECUTION -- delegates entirely to FutureSimulationAgent
    # =================================================================

    def execute_cases(self, cases, service_graph, linked_prediction=None):
        # ROOT-CAUSE FIX (Challenge appearing frozen/stuck): each case
        # here is executed purely to read its deterministic
        # affected_steps/bottlenecks/scores (see the vulnerability
        # derivation methods below) -- nothing in this file ever reads
        # a case's own possible_outcomes[0].description. Challenge
        # builds its own separate, evidence-validated explanations
        # later, only for the top-K RANKED vulnerabilities (see
        # _generate_explanation), not per executed case. Without
        # generate_description=False, FutureSimulationAgent.run()
        # would make one full LLM call per case for a description that
        # is immediately discarded -- with 20-30+ cases for a service
        # with many steps/integrations, run strictly sequentially,
        # that is exactly the reported hang. This changes nothing
        # about WHICH cases run, HOW they run, or any number/ranking
        # Challenge produces -- only removes a wasted, unread LLM call
        # per case. Simulate's own /scenarios endpoint is untouched:
        # it calls FutureSimulationAgent.run() directly, without this
        # flag, so its description generation is unchanged.
        executed = []
        for case in cases:
            validated_variables = self.simulation_agent.validate_scenario(
                case["scenario_type"], case["variables"], service_graph
            )
            output = self.simulation_agent.run(
                case["scenario_type"], validated_variables, service_graph,
                linked_prediction=linked_prediction,
                generate_description=False,
            )
            executed.append({"case": case, "output": output})
        return executed

    # =================================================================
    # 3. DETERMINISTIC VULNERABILITY DERIVATION
    # =================================================================

    def _step_lookup(self, service_graph):
        by_id = {step["step_id"]: step for step in service_graph["steps"]}
        total_steps = len(service_graph["steps"])
        return by_id, total_steps

    def _derive_single_point_of_failure(self, executed, total_steps):
        vulnerabilities = []
        for item in executed:
            case, output = item["case"], item["output"]
            if case["strategy"] not in {"EXHAUSTIVE_STEP_FAILURE", "EXHAUSTIVE_INTEGRATION_FAILURE"}:
                continue
            affected_count = len(output["affected_steps"])
            ratio = affected_count / max(1, total_steps)
            if ratio >= SPOF_RATIO_THRESHOLD:
                vulnerabilities.append({
                    "vulnerability_type": "SINGLE_POINT_OF_FAILURE",
                    "target": case["target"],
                    "source_case_ids": [case["case_id"]],
                    "severity": output["overall_risk_score"],
                    "severity_basis": (
                        f"{affected_count} of {total_steps} steps affected "
                        f"(ratio {round(ratio, 2)} >= threshold {SPOF_RATIO_THRESHOLD}) "
                        f"when {case['target']} fails."
                    ),
                    "source_outputs": [output],
                })
        return vulnerabilities

    def _derive_cascading_failure_path(self, executed, step_by_id):
        candidates = [
            item for item in executed
            if item["case"]["strategy"] == "EXHAUSTIVE_STEP_FAILURE"
            and len(item["output"]["affected_steps"]) > 0
        ]
        if not candidates:
            return []
        # Highest affected_step_count wins; ties broken by lowest step
        # order -- both explicit, both deterministic.
        best = min(
            candidates,
            key=lambda item: (
                -len(item["output"]["affected_steps"]),
                step_by_id[item["case"]["target"]]["order"],
            ),
        )
        case, output = best["case"], best["output"]
        return [{
            "vulnerability_type": "CASCADING_FAILURE_PATH",
            "target": case["target"],
            "source_case_ids": [case["case_id"]],
            "severity": output["overall_risk_score"],
            "severity_basis": (
                f"Worst observed cascade: failing {case['target']} blocked "
                f"{len(output['affected_steps'])} step(s), the highest of any "
                f"EXHAUSTIVE_STEP_FAILURE case."
            ),
            "source_outputs": [output],
        }]

    def _derive_sla_fragility(self, executed):
        vulnerabilities = []
        for item in executed:
            case, output = item["case"], item["output"]
            if case["strategy"] != "SLA_STRESS":
                continue
            if not output["affected_steps"]:
                continue
            vulnerabilities.append({
                "vulnerability_type": "SLA_FRAGILITY",
                "target": case["target"],
                "source_case_ids": [case["case_id"]],
                "severity": output["overall_risk_score"],
                "severity_basis": (
                    f"A {CHALLENGE_SLA_STRESS_MULTIPLIER}x delay at {case['target']} "
                    f"produced {len(output['affected_steps'])} affected step(s) "
                    f"exceeding SLA."
                ),
                "source_outputs": [output],
            })
        return vulnerabilities

    def _derive_demand_fragility(self, executed):
        vulnerabilities = []
        for item in executed:
            case, output = item["case"], item["output"]
            if case["strategy"] != "DEMAND_STRESS":
                continue
            for affected in output["affected_steps"]:
                vulnerabilities.append({
                    "vulnerability_type": "DEMAND_FRAGILITY",
                    "target": affected["step_id"],
                    "source_case_ids": [case["case_id"]],
                    "severity": output["overall_risk_score"],
                    "severity_basis": (
                        f"At {CHALLENGE_DEMAND_STRESS_MULTIPLIER}x demand, "
                        f"{affected['step_id']} ({affected['name']}) was marked "
                        f"{affected['status']}."
                    ),
                    "source_outputs": [output],
                })
        return vulnerabilities

    def _derive_critical_path_exposure(self, executed):
        top_bottleneck_occurrences = {}  # step_id -> [ (case_id, output) ]
        for item in executed:
            case, output = item["case"], item["output"]
            bottlenecks = output.get("bottlenecks") or []
            if not bottlenecks:
                continue
            top_step_id = bottlenecks[0]["step_id"]
            top_bottleneck_occurrences.setdefault(top_step_id, []).append((case, output))

        vulnerabilities = []
        for step_id, occurrences in top_bottleneck_occurrences.items():
            if len(occurrences) < CRITICAL_PATH_MIN_CASE_COUNT:
                continue
            best_case, best_output = max(occurrences, key=lambda pair: pair[1]["overall_risk_score"])
            vulnerabilities.append({
                "vulnerability_type": "CRITICAL_PATH_EXPOSURE",
                "target": step_id,
                "source_case_ids": [case["case_id"] for case, _ in occurrences],
                "severity": max(output["overall_risk_score"] for _, output in occurrences),
                "severity_basis": (
                    f"{step_id} was the top bottleneck in {len(occurrences)} distinct "
                    f"cases (>= threshold {CRITICAL_PATH_MIN_CASE_COUNT})."
                ),
                "source_outputs": [output for _, output in occurrences],
            })
        return vulnerabilities

    def _derive_customer_facing_exposure(self, base_vulnerabilities, step_by_id):
        # Group by target across ALL already-derived base vulnerability
        # types, keeping only the highest qualifying citizen_impact
        # score per target -- avoids duplicate CUSTOMER_FACING_EXPOSURE
        # entries when several rules already fired for the same step.
        best_per_target = {}
        for vulnerability in base_vulnerabilities:
            target = vulnerability["target"]
            if target not in step_by_id:
                continue  # integration targets are not step-typed
            if step_by_id[target]["type"] not in CUSTOMER_FACING_STEP_TYPES:
                continue
            max_citizen_score = max(
                output["citizen_impact"]["score"] for output in vulnerability["source_outputs"]
            )
            if max_citizen_score < CUSTOMER_EXPOSURE_THRESHOLD:
                continue
            existing = best_per_target.get(target)
            if existing is None or max_citizen_score > existing["severity"]:
                best_per_target[target] = {
                    "vulnerability_type": "CUSTOMER_FACING_EXPOSURE",
                    "target": target,
                    "source_case_ids": vulnerability["source_case_ids"],
                    "severity": max_citizen_score,
                    "severity_basis": (
                        f"{target} is a {step_by_id[target]['type']}-type step with citizen "
                        f"impact score {round(max_citizen_score, 2)} "
                        f"(>= threshold {CUSTOMER_EXPOSURE_THRESHOLD}), surfaced via "
                        f"{vulnerability['vulnerability_type']}."
                    ),
                    "source_outputs": vulnerability["source_outputs"],
                }
        return list(best_per_target.values())

    def _rank_vulnerabilities(self, vulnerabilities, step_by_id):
        def sort_key(vulnerability):
            target = vulnerability["target"]
            if target in step_by_id:
                tie_break = (0, step_by_id[target]["order"])
            else:
                tie_break = (1, str(target))
            return (-vulnerability["severity"], tie_break)

        return sorted(vulnerabilities, key=sort_key)

    def _build_evidence(self, vulnerability):
        """Relay -- never re-derive -- the FACT/PREDICTION/ASSUMPTION
        tags FutureSimulationAgent already assigned to each source
        output. This is the concrete grounding-propagation mechanism."""
        evidence = []
        for output in vulnerability["source_outputs"]:
            evidence.append({
                "type": "PREDICTION" if output["likelihood_source"] == "PREDICTION" else "ASSUMPTION",
                "reference_id": vulnerability["source_case_ids"][0],
                "detail": f"likelihood={output['likelihood']} ({output['likelihood_source']})",
            })
            for assumption in output.get("assumptions", []):
                evidence.append({
                    "type": "ASSUMPTION",
                    "reference_id": vulnerability["source_case_ids"][0],
                    "detail": f"{assumption['variable_name']}: {assumption['reason']}",
                })
            evidence.append({
                "type": "FACT",
                "reference_id": vulnerability["source_case_ids"][0],
                "detail": output["citizen_impact"]["basis"],
            })
        return evidence

    # =================================================================
    # 4. LLM-PHRASED EXPLANATION ONLY -- validated, top-K only
    # =================================================================

    def _template_explanation(self, vulnerability):
        if self.lang == "ar":
            return (
                f"{vulnerability['vulnerability_type']} عند {vulnerability['target']}: "
                f"{vulnerability['severity_basis']} (severity حتمية من محاكاة ZERO X-RAY بقيمة "
                f"{round(vulnerability['severity'], 2)} وليست توقعًا إحصائيًا)."
            )
        return (
            f"{vulnerability['vulnerability_type'].replace('_', ' ').title()} at "
            f"{vulnerability['target']}: {vulnerability['severity_basis']} "
            f"(deterministic ZERO X-RAY simulation severity {round(vulnerability['severity'], 2)}, "
            f"not a statistical forecast)."
        )

    def _validate_llm_explanation(self, text, vulnerability):
        if not text or not text.strip() or len(text) > 800:
            return False
        if is_placeholder_or_generic(text):
            return False
        allowed_numbers = {
            round(float(match), 2)
            for match in re.findall(r"\d+(?:\.\d+)?", vulnerability["severity_basis"])
        }
        allowed_numbers.add(round(vulnerability["severity"], 2))
        allowed_numbers.add(float(len(vulnerability["source_case_ids"])))
        claimed_numbers = {round(float(match), 2) for match in re.findall(r"\d+(?:\.\d+)?", text)}
        for number in claimed_numbers:
            if number in allowed_numbers:
                continue
            if number == int(number) and number <= len(vulnerability["source_case_ids"]):
                continue
            return False
        return True

    def _generate_explanation(self, vulnerability):
        template = self._template_explanation(vulnerability)
        if self.llm is None:
            return template, "template"
        try:
            system_prompt = (
                "You rephrase an already-computed vulnerability finding into one "
                "natural sentence for a government analyst. Do not invent any new "
                "number, step, or severity not given to you."
            )
            user_prompt = (
                f"Vulnerability type: {vulnerability['vulnerability_type']}\n"
                f"Target: {vulnerability['target']}\n"
                f"Severity: {round(vulnerability['severity'], 2)}\n"
                f"Basis: {vulnerability['severity_basis']}\n"
                "Write one clear sentence summarizing this. Do not add new numbers."
            )
            if self.lang == "ar":
                user_prompt += "\nWrite the explanation in Arabic. Keep enum values, field names, identifiers, and technical IDs unchanged."
            raw = self.llm.generate(system_prompt, user_prompt, max_new_tokens=180,
                                     temperature=0, timeout=30)
        except Exception:
            return template, "template"

        candidate = extract_clean_explanation(raw)
        if candidate and self._validate_llm_explanation(candidate, vulnerability):
            return candidate, "ai"
        return template, "template"

    # =================================================================
    # 5. TOP-LEVEL ENTRY POINT
    # =================================================================

    def run(self, strategies, service_graph, linked_prediction=None):
        cases = self.generate_cases(strategies, service_graph)
        executed = self.execute_cases(cases, service_graph, linked_prediction=linked_prediction)

        step_by_id, total_steps = self._step_lookup(service_graph)

        base_vulnerabilities = []
        base_vulnerabilities += self._derive_single_point_of_failure(executed, total_steps)
        base_vulnerabilities += self._derive_cascading_failure_path(executed, step_by_id)
        base_vulnerabilities += self._derive_sla_fragility(executed)
        base_vulnerabilities += self._derive_demand_fragility(executed)
        base_vulnerabilities += self._derive_critical_path_exposure(executed)

        customer_facing = self._derive_customer_facing_exposure(base_vulnerabilities, step_by_id)

        all_vulnerabilities = base_vulnerabilities + customer_facing
        ranked = self._rank_vulnerabilities(all_vulnerabilities, step_by_id)

        # Attach evidence + explanation; LLM phrasing only for the
        # top-K ranked vulnerabilities, deterministic template for
        # the rest -- keeps LLM cost flat and ranking wholly
        # unaffected by whether an LLM is configured.
        finalized = []
        fact_count = prediction_count = assumption_count = 0
        for index, vulnerability in enumerate(ranked):
            evidence = self._build_evidence(vulnerability)
            for entry in evidence:
                if entry["type"] == "FACT":
                    fact_count += 1
                elif entry["type"] == "PREDICTION":
                    prediction_count += 1
                else:
                    assumption_count += 1

            if index < CHALLENGE_EXPLANATION_TOP_K:
                explanation, explanation_source = self._generate_explanation(vulnerability)
            else:
                explanation, explanation_source = self._template_explanation(vulnerability), "template"

            # ADDITIVE (citizen/outcome impact audit fix): relay --
            # never re-derive -- FutureSimulationAgent's own
            # citizen_outcome_affected/outcome_impact_reason from
            # whichever of this vulnerability's source_outputs already
            # carries it, exactly the same relay pattern
            # _build_evidence() already uses for citizen_impact.basis
            # just above. A vulnerability can aggregate more than one
            # source_output (e.g. SINGLE_POINT_OF_FAILURE across
            # several occurrences) -- True if ANY of them found outcome
            # impact, consistent with how severity itself is already
            # aggregated via max() elsewhere in this file.
            outcome_affected_sources = [
                output for output in vulnerability["source_outputs"]
                if output.get("citizen_outcome_affected")
            ]
            citizen_outcome_affected = bool(outcome_affected_sources)
            outcome_impact_reason = (
                outcome_affected_sources[0]["outcome_impact_reason"]
                if outcome_affected_sources
                else vulnerability["source_outputs"][0].get("outcome_impact_reason", "")
            )

            finalized.append({
                "vulnerability_id": f"{vulnerability['vulnerability_type']}:{vulnerability['target']}",
                "vulnerability_type": vulnerability["vulnerability_type"],
                "target": vulnerability["target"],
                "source_case_ids": vulnerability["source_case_ids"],
                "severity": round(vulnerability["severity"], 2),
                "severity_basis": vulnerability["severity_basis"],
                "evidence": evidence,
                "explanation": explanation,
                "explanation_source": explanation_source,
                "citizen_outcome_affected": citizen_outcome_affected,
                "outcome_impact_reason": outcome_impact_reason,
            })

        cases_executed_summary = [
            {
                "case_id": item["case"]["case_id"],
                "strategy": item["case"]["strategy"],
                "scenario_type": item["case"]["scenario_type"],
                "target": item["case"]["target"],
                "overall_risk_score": item["output"]["overall_risk_score"],
            }
            for item in executed
        ]

        generated_at = _now_iso()
        ai_used = any(item.get("explanation_source") == "ai" for item in finalized)
        evidence_refs = [entry.get("reference_id") for item in finalized for entry in item.get("evidence", []) if entry.get("reference_id")]
        return {
            "generated_at": generated_at,
            "provenance": provenance_for_mixed_result(llm_present=self.llm is not None, ai_used=ai_used, evidence_references=evidence_refs, generated_at=generated_at),
            "cases_executed": cases_executed_summary,
            "vulnerabilities": finalized,
            "grounding_summary": {
                "fact_count": fact_count,
                "prediction_count": prediction_count,
                "assumption_count": assumption_count,
            },
            "score_methodology": SCORE_METHODOLOGY_MARKER,
        }
