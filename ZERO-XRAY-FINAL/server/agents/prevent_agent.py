"""PreventAgent -- Step 5 ("Prevent") of the ZERO X-RAY -> Government
Future Engine evolution.

Reads a stored Evolve output (Step 4, read-only, unmodified) and
DEFINES re-checkable prevention triggers for each proposal. Does NOT
re-run Evolve, Challenge, Simulate, or Predict; does NOT call
agents/orchestrator.py or graph/workflow.py; does NOT schedule,
monitor, or execute anything -- it only produces a deterministic
trigger DEFINITION, `status` is always the fixed constant "DEFINED".

======================================================================
DETERMINISM
======================================================================
Every trigger comes from a closed table of 2 trigger_types, each
gated by a plain condition over already-stored data (a proposal's own
`exposure_before`, and whether its `grounding` contains a parseable
PREDICTION-sourced likelihood). No LLM call decides whether a trigger
is generated, what its threshold is, or what its action is. The LLM,
if available, is only ever asked to rephrase an already-computed
threshold/action pair into `explanation` -- and even that is
validated (`_validate_llm_explanation`) before being trusted, exactly
like Predict/Simulate/Challenge/Evolve's own explanation generators.

======================================================================
WHY action_if_triggered CAN NEVER VIOLATE PROTECTION OR INVENT ACTIONS
======================================================================
`action_if_triggered` is a VERBATIM copy of the source
EvolutionProposal's own `proposed_state` -- Prevent has no code path
that generates new action text. Since every Evolve proposal is itself
additive-only and respects `protected` steps by construction (Step 4),
relaying that same text unchanged means Prevent inherits the same
safety guarantee without re-deriving it.

======================================================================
WHY PREDICTION_EARLY_WARNING_TRIGGER IS SERVICE-SCOPED, NOT SIGNAL-SCOPED
======================================================================
A Challenge vulnerability's evidence records that a case's likelihood
came from a linked Prediction (`likelihood_source == "PREDICTION"`)
and the resulting numeric confidence, but the original `prediction_id`
/ signal source is not persisted onto that evidence string (see
agents/challenge_agent.py::_build_evidence). Watching for a future
Predict run for this SERVICE to report a confidence at/above the
threshold is honest given the data; claiming to watch a specific
prediction or signal by id would not be.
"""

import re
from datetime import datetime, timezone
from core.result_provenance import provenance_for_mixed_result
from core.backend_language import normalize_lang, text as backend_text

from core.score_methodology import SCORE_METHODOLOGY_MARKER
from core.llm_explanation_guard import is_placeholder_or_generic, extract_clean_explanation


# =====================================================================
# FIXED TRIGGER TYPES -- closed set, no LLM involvement
# =====================================================================
TRIGGER_TYPES = {"CHALLENGE_RECURRENCE_TRIGGER", "PREDICTION_EARLY_WARNING_TRIGGER"}

# Single named, documented engineering constant applied identically to
# both trigger types -- not statistically derived (see
# core/score_methodology.py, reused unmodified below).
EARLY_WARNING_RATIO = 0.8

# Prevent only ever DEFINES a trigger in this implementation -- never
# activates, fires, or executes one. Fixed constant, never any other
# value.
TRIGGER_STATUS = "DEFINED"

_LIKELIHOOD_PATTERN = re.compile(r"likelihood=([\d.]+)")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class PreventAgent:

    def __init__(self, llm=None, lang="en"):
        self.llm = llm
        self.lang = normalize_lang(lang)

    # =================================================================
    # 1. DETERMINISTIC TRIGGER EXTRACTION FROM A SINGLE PROPOSAL
    # =================================================================

    def _extract_prediction_confidence(self, grounding):
        """Only a PREDICTION-typed evidence entry with a parseable
        `likelihood=<float>` (see agents/challenge_agent.py's own
        detail string format) counts -- never guessed."""
        for entry in grounding or []:
            if entry.get("type") != "PREDICTION":
                continue
            match = _LIKELIHOOD_PATTERN.search(entry.get("detail", ""))
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None

    def _build_challenge_recurrence_trigger(self, proposal):
        exposure_before = proposal.get("exposure_before")
        if exposure_before is None:
            return None
        threshold_value = round(exposure_before * EARLY_WARNING_RATIO, 2)
        watch_scope = (
            f"vulnerability {proposal['fixes_vulnerability_id']} on target {proposal['target']}"
        )
        threshold_basis = (
            f"{int(EARLY_WARNING_RATIO * 100)}% of original severity "
            f"{round(exposure_before, 2)} = {threshold_value}"
        )
        return {
            "trigger_type": "CHALLENGE_RECURRENCE_TRIGGER",
            "watch_metric": "challenge_severity",
            "watch_scope": watch_scope,
            "threshold_value": threshold_value,
            "threshold_basis": threshold_basis,
        }

    def _build_prediction_early_warning_trigger(self, proposal):
        confidence = self._extract_prediction_confidence(proposal.get("grounding", []))
        if confidence is None:
            return None
        threshold_value = round(confidence * EARLY_WARNING_RATIO, 2)
        watch_scope = "any Predict run for this service"
        threshold_basis = (
            f"{int(EARLY_WARNING_RATIO * 100)}% of linked prediction confidence "
            f"{round(confidence, 2)} = {threshold_value}"
        )
        return {
            "trigger_type": "PREDICTION_EARLY_WARNING_TRIGGER",
            "watch_metric": "prediction_confidence",
            "watch_scope": watch_scope,
            "threshold_value": threshold_value,
            "threshold_basis": threshold_basis,
        }

    # =================================================================
    # 2. GROUNDING -- relay, never re-tag; threshold gets its own entry
    # =================================================================

    def _build_grounding(self, proposal, threshold_basis, proposal_id):
        grounding = list(proposal.get("grounding", []))
        grounding.append({
            "type": "ASSUMPTION",
            "reference_id": proposal_id,
            "detail": (
                f"threshold_value derived via the fixed EARLY_WARNING_RATIO "
                f"({EARLY_WARNING_RATIO}) engineering heuristic: {threshold_basis}."
            ),
        })
        return grounding

    # =================================================================
    # 3. LLM-PHRASED EXPLANATION ONLY -- validated
    # =================================================================

    def _template_explanation(self, watch_metric, watch_scope, threshold_value, action):
        return backend_text("prevent_explanation", self.lang, metric=watch_metric, scope=watch_scope, threshold=threshold_value, action=action)

    def _validate_llm_explanation(self, text, watch_scope, threshold_value, action):
        if not text or not text.strip() or len(text) > 900:
            return False
        if is_placeholder_or_generic(text):
            return False
        allowed_numbers = {float(match) for match in re.findall(r"\d+(?:\.\d+)?", action)}
        allowed_numbers.add(float(threshold_value))
        claimed_numbers = {float(match) for match in re.findall(r"\d+(?:\.\d+)?", text)}
        return claimed_numbers.issubset(allowed_numbers)

    def _generate_explanation(self, watch_metric, watch_scope, threshold_value, action):
        template = self._template_explanation(watch_metric, watch_scope, threshold_value, action)
        if self.llm is None:
            return template, "template"
        try:
            system_prompt = (
                "You rephrase an already-decided prevention trigger (what to watch, "
                "the threshold, and the action to take) into one natural sentence for "
                "a government analyst. Do not add any new fact, number, or claim not "
                "already given to you."
            )
            user_prompt = (
                f"Watch: {watch_metric} for {watch_scope}\n"
                f"Threshold: {threshold_value}\n"
                f"Action if triggered: {action}\n"
                "Write one clear sentence. Do not add new facts or numbers."
            )
            if self.lang == "ar":
                user_prompt += "\nWrite the explanation in Arabic. Keep enum values, field names, identifiers, and technical IDs unchanged."
            raw = self.llm.generate(system_prompt, user_prompt, max_new_tokens=200,
                                     temperature=0, timeout=30)
        except Exception:
            return template, "template"

        candidate = extract_clean_explanation(raw)
        if candidate and self._validate_llm_explanation(candidate, watch_scope, threshold_value, action):
            return candidate, "ai"
        return template, "template"

    # =================================================================
    # 4. TOP-LEVEL ENTRY POINT
    # =================================================================

    def run(self, evolve_output, evolution_id):
        proposals = evolve_output.get("proposals", [])
        triggers = []
        skipped = []

        for proposal in proposals:
            proposal_id = proposal["proposal_id"]
            built_any = False

            recurrence = self._build_challenge_recurrence_trigger(proposal)
            if recurrence is not None:
                built_any = True
                triggers.append(self._finalize_trigger(recurrence, proposal, proposal_id))

            prediction_warning = self._build_prediction_early_warning_trigger(proposal)
            if prediction_warning is not None:
                built_any = True
                triggers.append(self._finalize_trigger(prediction_warning, proposal, proposal_id))

            if not built_any:
                skipped.append({
                    "proposal_id": proposal_id,
                    "reason": backend_text("prevent_no_exposure", self.lang),
                })

        generated_at = _now_iso()
        ai_used = any(item.get("explanation_source") == "ai" for item in triggers)
        evidence_refs = [entry.get("reference_id") for item in triggers for entry in item.get("grounding", []) if entry.get("reference_id")]
        return {
            "generated_at": generated_at,
            "provenance": provenance_for_mixed_result(llm_present=self.llm is not None, ai_used=ai_used, evidence_references=evidence_refs, generated_at=generated_at),
            "evolution_id": evolution_id,
            "triggers": triggers,
            "skipped_proposals": skipped,
            "score_methodology": SCORE_METHODOLOGY_MARKER,
        }

    def _finalize_trigger(self, built, proposal, proposal_id):
        grounding = self._build_grounding(proposal, built["threshold_basis"], proposal_id)
        action = proposal["proposed_state"]
        explanation, explanation_source = self._generate_explanation(
            built["watch_metric"], built["watch_scope"], built["threshold_value"], action
        )
        return {
            "trigger_id": f"{built['trigger_type']}:{proposal_id}",
            "trigger_type": built["trigger_type"],
            "source_proposal_id": proposal_id,
            "source_vulnerability_id": proposal["fixes_vulnerability_id"],
            "watch_metric": built["watch_metric"],
            "watch_scope": built["watch_scope"],
            "threshold_value": built["threshold_value"],
            "threshold_basis": built["threshold_basis"],
            "action_if_triggered": action,
            "protected": proposal.get("protected", False),
            "status": TRIGGER_STATUS,
            "grounding": grounding,
            "explanation": explanation,
            "explanation_source": explanation_source,
        }
