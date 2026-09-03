"""EvolveAgent -- Step 4 ("Evolve") of the ZERO X-RAY -> Government
Future Engine evolution.

Reads a stored Challenge output (Step 3, read-only, unmodified) and
proposes structural fixes for its vulnerabilities. Does NOT re-run
Challenge or Simulate, does NOT call agents/orchestrator.py or
graph/workflow.py, and does NOT write to any table except its own new
`evolutions` table.

======================================================================
DETERMINISM
======================================================================
Every proposal comes from a closed table of 5 evolution_types, each
gated by a plain condition over already-stored data (a vulnerability's
own `vulnerability_type`/`target`, and the target's real `type`/
`order` in the service graph). No LLM call decides whether a
vulnerability gets a proposal, which evolution_type it gets, or what
`exposure_before`/`exposure_after_estimate` are. The LLM, if
available, is only ever asked to rephrase an already-computed
`current_state`/`proposed_state` pair into `explanation` -- and even
that is validated (`_validate_llm_explanation`) before being trusted,
exactly like Predict/Simulate/Challenge's own explanation generators.

======================================================================
WHY NONE OF THE 5 EVOLUTION TYPES CAN VIOLATE PROTECTION
======================================================================
Every evolution_type below is structurally ADDITIVE ONLY: it adds
redundancy, decouples a downstream blocking dependency, adds a
monitored threshold, adds capacity buffering, or adds a citizen-facing
safeguard. None of them removes a step, changes a step's `type`
(CUSTOMER/HUMAN/SYSTEM), or reorders a step to happen before another
step that used to precede it. This is what makes "never remove/bypass
a protected step" true by construction for this closed set, not just
enforced by a lookup.

A `protected` flag is still computed and surfaced on every proposal
(see `_is_protected`) as an explicit, HONEST safety marker for any
evolution_type added later: a future step is marked `protected: true`
if its own stored `type == "HUMAN"`. This is NOT a precise
reconstruction of the original REQUIREMENT/HUMAN/AS_IS designation
from `service.protected_steps` -- that mapping does not exist in
stored data (future_steps use the future journey's own step_number,
a different index space from the current-journey step_number that
`protected_steps` references, and `human_constraint`/
`implementation_status` are never copied onto future_steps by
agents/redesign_agent.py or agents/step_compliance_agent.py). Marking
every HUMAN-type step protected is the conservative, honestly-labeled
superset instead of a fragile, unverifiable guess at an exact match.
"""

import re
from datetime import datetime, timezone
from core.result_provenance import provenance_for_mixed_result
from core.backend_language import normalize_lang

from core.score_methodology import SCORE_METHODOLOGY_MARKER
from core.llm_explanation_guard import is_placeholder_or_generic, extract_clean_explanation


# =====================================================================
# CLOSED SET OF EVOLUTION TYPES -- fixed, deterministic mapping
# =====================================================================
EVOLUTION_TYPES = {
    "ADD_REDUNDANCY", "DECOUPLE_DEPENDENCY", "ADD_SLA_SAFEGUARD",
    "ADD_CAPACITY_BUFFER", "ADD_CITIZEN_SAFEGUARD",
}

# vulnerability_type -> the set of evolution_types that MAY apply,
# further gated by the target's real stored type (see _select below).
# A vulnerability_type not present here always lands in
# skipped_vulnerabilities -- never a guessed proposal.
_STRUCTURAL_VULNERABILITY_TYPES = {
    "SINGLE_POINT_OF_FAILURE", "CASCADING_FAILURE_PATH", "CRITICAL_PATH_EXPOSURE",
}

CUSTOMER_FACING_STEP_TYPES = {"CUSTOMER", "HUMAN"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _clamp(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, value))


class EvolveAgent:

    def __init__(self, llm=None, lang="en"):
        self.llm = llm
        self.lang = normalize_lang(lang)

    # =================================================================
    # 1. TARGET CLASSIFICATION (deterministic, over real graph data)
    # =================================================================

    def _is_protected(self, target, step_by_id):
        step = step_by_id.get(target)
        return bool(step and step.get("type") == "HUMAN")

    def _select_evolution_type(self, vulnerability, step_by_id, integration_ids):
        vtype = vulnerability["vulnerability_type"]
        target = vulnerability["target"]

        if vtype == "SINGLE_POINT_OF_FAILURE" and target in integration_ids:
            return "ADD_REDUNDANCY", None

        if vtype in _STRUCTURAL_VULNERABILITY_TYPES and target in step_by_id:
            total_steps = len(step_by_id)
            step = step_by_id[target]
            if step["order"] >= total_steps - 1:
                return None, "Target step has no downstream steps to decouple from."
            return "DECOUPLE_DEPENDENCY", None

        if vtype == "SLA_FRAGILITY" and target in step_by_id:
            return "ADD_SLA_SAFEGUARD", None

        if vtype == "DEMAND_FRAGILITY" and target in step_by_id:
            if step_by_id[target]["type"] not in CUSTOMER_FACING_STEP_TYPES:
                return None, "Target step is not customer/human-facing; no capacity buffer applies."
            return "ADD_CAPACITY_BUFFER", None

        if vtype == "CUSTOMER_FACING_EXPOSURE" and target in step_by_id:
            if step_by_id[target]["type"] not in CUSTOMER_FACING_STEP_TYPES:
                return None, "Target step is not customer/human-facing."
            return "ADD_CITIZEN_SAFEGUARD", None

        if target not in step_by_id and target not in integration_ids:
            return None, "Target no longer exists in the current service graph."

        return None, f"No applicable evolution type for {vtype} on this target."

    # =================================================================
    # 2. CURRENT -> PROPOSED STATE TEMPLATES (deterministic)
    # =================================================================

    def _target_name(self, target, step_by_id, integration_ids_to_names):
        if target in step_by_id:
            return step_by_id[target]["name"] or target
        return integration_ids_to_names.get(target, target)

    def _state_pair(self, evolution_type, vulnerability, step_by_id, integration_ids_to_names):
        target = vulnerability["target"]
        name = self._target_name(target, step_by_id, integration_ids_to_names)

        if evolution_type == "ADD_REDUNDANCY":
            return (
                f"{name} is the only path for this integration; its failure degrades "
                f"every step that depends on it.",
                f"{name} remains the primary integration; a backup/alternate path is "
                f"added (flagged PROPOSED) so its failure no longer single-handedly "
                f"degrades dependent steps.",
            )
        if evolution_type == "DECOUPLE_DEPENDENCY":
            return (
                f"{name} ({target}) currently blocks downstream steps if it fails, "
                f"because later steps strictly depend on its completion.",
                f"{name} remains in the journey unchanged; downstream steps are "
                f"restructured so they no longer treat {name}'s completion as a "
                f"strict blocking prerequisite, containing a failure to {name} alone.",
            )
        if evolution_type == "ADD_SLA_SAFEGUARD":
            return (
                f"{name} has no monitored duration threshold; a delay here can "
                f"silently propagate to downstream steps.",
                f"{name} remains unchanged; an explicit monitored SLA threshold and "
                f"early-warning alert are added so a delay is caught before it "
                f"propagates.",
            )
        if evolution_type == "ADD_CAPACITY_BUFFER":
            return (
                f"{name} has fixed capacity; a demand surge degrades it directly.",
                f"{name} remains unchanged; a queueing/overflow-routing buffer is "
                f"added to absorb surge periods without degrading the step itself.",
            )
        if evolution_type == "ADD_CITIZEN_SAFEGUARD":
            return (
                f"{name} gives the citizen no visibility if this step fails or is "
                f"delayed.",
                f"{name} remains unchanged; a proactive status/fallback notification "
                f"path is added so the citizen is informed rather than left waiting "
                f"silently.",
            )
        raise ValueError(f"Unhandled evolution_type '{evolution_type}'.")

    # =================================================================
    # 3. EXPOSURE BEFORE/AFTER -- only when the data actually supports it
    # =================================================================

    def _extract_affected_count(self, vulnerability):
        """Only SINGLE_POINT_OF_FAILURE and CASCADING_FAILURE_PATH
        severity_basis strings carry an explicit affected-step count
        (see agents/challenge_agent.py's own deterministic templates).
        CRITICAL_PATH_EXPOSURE's basis describes a case count, not an
        affected-step count, so it has nothing usable here -- returns
        None rather than guessing."""
        basis = vulnerability.get("severity_basis", "")
        match = re.search(r"(\d+) of \d+ steps affected", basis)
        if match:
            return int(match.group(1))
        match = re.search(r"blocked (\d+) step", basis)
        if match:
            return int(match.group(1))
        return None

    def _compute_exposure(self, evolution_type, vulnerability, total_steps):
        exposure_before = vulnerability["severity"]
        if evolution_type != "DECOUPLE_DEPENDENCY" or total_steps <= 0:
            return exposure_before, None, None

        affected_count_before = self._extract_affected_count(vulnerability)
        if affected_count_before is None or affected_count_before <= 0:
            return exposure_before, None, None

        ratio_before = affected_count_before / total_steps
        ratio_after = 1 / total_steps
        if ratio_before <= 0:
            return exposure_before, None, None

        # Deterministic, bounded, proportional-scaling heuristic:
        # assumes the same per-affected-step contribution to severity,
        # scaled down by the ratio of affected step counts. This is a
        # ZERO X-RAY engineering estimate (see score_methodology),
        # never a statistical projection.
        exposure_after_estimate = _clamp(exposure_before * (ratio_after / ratio_before))
        basis = (
            f"Estimated by scaling the original severity ({round(exposure_before, 2)}) "
            f"by the ratio of affected steps after decoupling ({affected_count_before} "
            f"-> 1) out of {total_steps} total steps. Deterministic proportional "
            f"heuristic, not a statistical projection."
        )
        return exposure_before, round(exposure_after_estimate, 2), basis

    # =================================================================
    # 4. GROUNDING -- relay, never re-tag
    # =================================================================

    def _build_grounding(self, vulnerability, exposure_after_basis, vulnerability_id):
        grounding = list(vulnerability.get("evidence", []))
        if exposure_after_basis is not None:
            grounding.append({
                "type": "ASSUMPTION",
                "reference_id": vulnerability_id,
                "detail": exposure_after_basis,
            })
        return grounding

    # =================================================================
    # 5. LLM-PHRASED EXPLANATION ONLY -- validated
    # =================================================================

    def _template_explanation(self, current_state, proposed_state):
        if self.lang == "ar":
            return f"الحالة الحالية: {current_state} الحالة المقترحة: {proposed_state}"
        return f"Currently: {current_state} Proposed: {proposed_state}"

    def _validate_llm_explanation(self, text, current_state, proposed_state):
        if not text or not text.strip() or len(text) > 900:
            return False
        if is_placeholder_or_generic(text):
            return False
        allowed_numbers = {
            float(match) for match in re.findall(r"\d+(?:\.\d+)?", current_state + proposed_state)
        }
        claimed_numbers = {float(match) for match in re.findall(r"\d+(?:\.\d+)?", text)}
        return claimed_numbers.issubset(allowed_numbers)

    def _generate_explanation(self, current_state, proposed_state):
        template = self._template_explanation(current_state, proposed_state)
        if self.llm is None:
            return template, "template"
        try:
            system_prompt = (
                "You rephrase an already-decided CURRENT and PROPOSED state pair "
                "into one natural paragraph for a government analyst. Do not add "
                "any new fact, number, or claim not already given to you."
            )
            user_prompt = (
                f"Current: {current_state}\nProposed: {proposed_state}\n"
                "Write one clear paragraph summarizing this change. Do not add new facts."
            )
            if self.lang == "ar":
                user_prompt += "\nWrite the explanation in Arabic. Keep enum values, field names, identifiers, and technical IDs unchanged."
            raw = self.llm.generate(system_prompt, user_prompt, max_new_tokens=220,
                                     temperature=0, timeout=30)
        except Exception:
            return template, "template"

        candidate = extract_clean_explanation(raw)
        if candidate and self._validate_llm_explanation(candidate, current_state, proposed_state):
            return candidate, "ai"
        return template, "template"

    # =================================================================
    # 6. TOP-LEVEL ENTRY POINT
    # =================================================================

    def run(self, challenge_output, service_graph, challenge_id):
        step_by_id = {step["step_id"]: step for step in service_graph["steps"]}
        integration_ids = {item["integration_id"] for item in service_graph["integrations"]}
        integration_names = {
            item["integration_id"]: item["name"] for item in service_graph["integrations"]
        }
        total_steps = len(step_by_id)

        proposals = []
        skipped = []

        for vulnerability in challenge_output.get("vulnerabilities", []):
            evolution_type, skip_reason = self._select_evolution_type(
                vulnerability, step_by_id, integration_ids
            )
            if evolution_type is None:
                skipped.append({
                    "vulnerability_id": vulnerability["vulnerability_id"],
                    "reason": skip_reason,
                })
                continue

            current_state, proposed_state = self._state_pair(
                evolution_type, vulnerability, step_by_id, integration_names
            )
            exposure_before, exposure_after_estimate, exposure_basis = self._compute_exposure(
                evolution_type, vulnerability, total_steps
            )
            grounding = self._build_grounding(
                vulnerability, exposure_basis, vulnerability["vulnerability_id"]
            )
            explanation, explanation_source = self._generate_explanation(
                current_state, proposed_state
            )

            proposals.append({
                "proposal_id": f"{evolution_type}:{vulnerability['vulnerability_id']}",
                "evolution_type": evolution_type,
                "fixes_vulnerability_id": vulnerability["vulnerability_id"],
                "target": vulnerability["target"],
                "current_state": current_state,
                "proposed_state": proposed_state,
                "protected": self._is_protected(vulnerability["target"], step_by_id),
                "exposure_before": exposure_before,
                "exposure_after_estimate": exposure_after_estimate,
                "exposure_calculation_basis": exposure_basis,
                "grounding": grounding,
                "explanation": explanation,
                "explanation_source": explanation_source,
            })

        generated_at = _now_iso()
        ai_used = any(item.get("explanation_source") == "ai" for item in proposals)
        evidence_refs = [entry.get("reference_id") for item in proposals for entry in item.get("grounding", []) if entry.get("reference_id")]
        return {
            "generated_at": generated_at,
            "provenance": provenance_for_mixed_result(llm_present=self.llm is not None, ai_used=ai_used, evidence_references=evidence_refs, generated_at=generated_at),
            "challenge_id": challenge_id,
            "proposals": proposals,
            "skipped_vulnerabilities": skipped,
            "score_methodology": SCORE_METHODOLOGY_MARKER,
        }
