"""PredictionAgent -- Step 1 ("Predict") of the ZERO X-RAY ->
Government Future Engine evolution.

SCOPE (deliberately narrow, per the approved design):
This agent does NOT ask an LLM to "predict" anything. It looks for
PATTERNS THAT HAVE ALREADY RECURRED in a service's own stored
history (repeated compliance gaps, repeated friction points, repeated
citizen intents in Sandbox journeys) and reports those recurrences as
predictions that they are likely to continue -- with a confidence
number computed from the actual occurrence count, never from the LLM.

HARD RULE (matches the task's "Most important rule"):
The LLM is NEVER used to decide:
  - confidence
  - signal frequency / occurrence counts
  - data sufficiency
  - whether a prediction is valid
All of those are computed here in plain Python from real stored rows.
The LLM's ONLY allowed job is to rephrase an already-computed,
already-validated statement into a more natural sentence
(`explanation`), and even that rephrasing is checked afterwards
(`_validate_llm_explanation`) so it cannot introduce a new number or
fact that isn't already in the deterministic `signals`. If the LLM is
unavailable, fails, or its output doesn't pass validation, the
agent falls back to a deterministic template explanation -- the
prediction itself (statement/confidence/signals) is completely
unaffected either way, exactly as `analysis_source` elsewhere in this
codebase (core/llm.py's `ai_label()`) never changes whether an agent
falls back, only how it's labeled.

ISOLATION:
This agent does not read or write anything in graph/workflow.py's
state, does not call agents/orchestrator.py, and does not touch the
`blueprints`, `journeys`, `services`, or `analyses` tables. It only
reads them (via ServiceStore, already-existing methods, and one
read-only SQL SELECT joining `journeys` to `blueprints` -- no ALTER,
no INSERT/UPDATE against either table) and writes only to its own new
`predictions` table (core/prediction_store.py).
"""

import re
from collections import defaultdict
from datetime import datetime, timezone

from core.database import connect_database
from core.score_methodology import SCORE_METHODOLOGY_MARKER
from core.result_provenance import provenance_for_mixed_result
from core.backend_language import normalize_lang
from core.llm_explanation_guard import is_placeholder_or_generic, extract_clean_explanation


# =====================================================================
# DETERMINISTIC THRESHOLDS
# =====================================================================
# A "recurring" signal requires the same thing to appear in at least
# this many DISTINCT analyses/journeys -- a single occurrence is not a
# pattern, it's an anecdote, and predicting from one data point is
# exactly the "LLM guess dressed as a forecast" this design forbids.
MIN_OCCURRENCES_FOR_RECURRENCE = 2

# Below this many stored analyses, recurrence cannot be established at
# all (there isn't even a second data point to compare against), so
# the agent refuses to produce predictions rather than guess.
MIN_ANALYSES_FOR_PREDICTION = 2

# At or above this many stored analyses, a detected recurring pattern
# is reported as SUFFICIENT rather than LIMITED.
SUFFICIENT_ANALYSES_THRESHOLD = 4

# MODEL_INFERRED predictions are intentionally not produced by this
# Step-1 implementation (see class docstring / audit limitations) --
# kept as a named constant so the ceiling is documented in one place
# for when that type is added later.
MODEL_INFERRED_CONFIDENCE_CEILING = 0.4


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _clamp01(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def fetch_journeys_for_service(database_path, service_id, tenant_id):
    """Read-only lookup of Sandbox journeys belonging to this service.

    `journeys` does not carry `service_id` directly -- it is reached
    via `journeys.blueprint_id -> blueprints.id`, and `blueprints`
    already carries `service_id`/`tenant_id` (added by an existing,
    already-shipped additive migration in core/runtime_store.py, see
    `link_blueprint_to_service_analysis`). This function only SELECTs;
    it never creates, alters, or writes to either table.
    """
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT j.id AS id, j.intent AS intent, j.state AS state,
                   j.created_at AS created_at
            FROM journeys j
            JOIN blueprints b ON j.blueprint_id = b.id
            WHERE b.service_id = ? AND b.tenant_id = ?
            ORDER BY j.created_at DESC
            """,
            (service_id, tenant_id),
        ).fetchall()
    return [dict(row) for row in rows]


class PredictionAgent:

    def __init__(self, llm=None, lang="en"):
        self.llm = llm
        self.lang = normalize_lang(lang)

    # =================================================================
    # 1. INPUT ASSEMBLY (deterministic -- no LLM involved)
    # =================================================================

    def gather_input(self, service_id, tenant_id, service_store, database_path):
        analyses = service_store.list_analyses_for_service(service_id, tenant_id)
        journeys = fetch_journeys_for_service(database_path, service_id, tenant_id)
        return {
            "service_id": service_id,
            "tenant_id": tenant_id,
            "as_of": _now_iso(),
            "analyses": [
                {
                    "id": item.get("id"),
                    "created_at": item.get("created_at"),
                    "result": item.get("result") or {},
                }
                for item in analyses
            ],
            "journeys": [
                {
                    "id": item.get("id"),
                    "intent": item.get("intent"),
                    "state": item.get("state"),
                    "created_at": item.get("created_at"),
                }
                for item in journeys
            ],
        }

    # =================================================================
    # 2. DETERMINISTIC RECURRENCE DETECTION
    # =================================================================

    def _collect_gap_groups(self, analyses):
        """Group gaps (from agents/gap_agent.py's stored output, under
        result["gaps"]["gaps"]) by standard_id, counting DISTINCT
        analyses a given standard_id's gap appeared in -- not raw gap
        instance count, so one analysis listing the same gap twice
        cannot inflate the recurrence signal."""
        groups = defaultdict(lambda: {
            "analysis_ids": set(),
            "category": "General",
            "description": "",
            "severity": "MEDIUM",
            "occurrences": [],  # (analysis_id, gap_id, description)
        })
        for analysis in analyses:
            analysis_id = analysis.get("id")
            gaps = (
                (analysis.get("result") or {})
                .get("gaps", {})
                .get("gaps", [])
            )
            if not isinstance(gaps, list):
                continue
            seen_in_this_analysis = set()
            for gap in gaps:
                if not isinstance(gap, dict):
                    continue
                standard_id = gap.get("standard_id")
                description = str(gap.get("description", "")).strip()
                key = standard_id or _normalize_text(description)
                if not key:
                    continue
                group = groups[key]
                group["category"] = gap.get("category") or group["category"]
                group["description"] = description or group["description"]
                group["severity"] = gap.get("severity") or group["severity"]
                if key not in seen_in_this_analysis:
                    group["analysis_ids"].add(analysis_id)
                    seen_in_this_analysis.add(key)
                group["occurrences"].append(
                    (analysis_id, gap.get("gap_id", ""), description)
                )
        return groups

    def _collect_friction_groups(self, analyses):
        groups = defaultdict(lambda: {
            "analysis_ids": set(),
            "sample_text": "",
            "occurrences": [],  # (analysis_id, friction_text)
        })
        for analysis in analyses:
            analysis_id = analysis.get("id")
            friction_points = (
                (analysis.get("result") or {})
                .get("service_analysis", {})
                .get("friction_points", [])
            )
            if not isinstance(friction_points, list):
                continue
            seen_in_this_analysis = set()
            for item in friction_points:
                text = str(item).strip()
                if not text:
                    continue
                key = _normalize_text(text)
                group = groups[key]
                group["sample_text"] = group["sample_text"] or text
                if key not in seen_in_this_analysis:
                    group["analysis_ids"].add(analysis_id)
                    seen_in_this_analysis.add(key)
                group["occurrences"].append((analysis_id, text))
        return groups

    def _collect_journey_intent_groups(self, journeys):
        groups = defaultdict(lambda: {
            "journey_ids": set(),
            "sample_text": "",
            "occurrences": [],  # (journey_id, intent_text)
        })
        for journey in journeys:
            intent = str(journey.get("intent", "")).strip()
            if not intent:
                continue
            key = _normalize_text(intent)
            group = groups[key]
            group["sample_text"] = group["sample_text"] or intent
            group["journey_ids"].add(journey.get("id"))
            group["occurrences"].append((journey.get("id"), intent))
        return groups

    def _build_predictions(self, prediction_input):
        analyses = prediction_input["analyses"]
        journeys = prediction_input["journeys"]
        analyses_count = len(analyses)
        journeys_count = len(journeys)

        predictions = []
        counter = 1

        if analyses_count >= MIN_ANALYSES_FOR_PREDICTION:
            gap_groups = self._collect_gap_groups(analyses)
            for group in gap_groups.values():
                occurrence_count = len(group["analysis_ids"])
                if occurrence_count < MIN_OCCURRENCES_FOR_RECURRENCE:
                    continue
                confidence = _clamp01(occurrence_count / analyses_count)
                signals = [
                    {
                        "source": "gap",
                        "reference_id": analysis_id,
                        "detail": (
                            f"gap_id={gap_id or 'N/A'}: {description}"
                            if description else f"gap_id={gap_id or 'N/A'}"
                        ),
                    }
                    for (analysis_id, gap_id, description) in group["occurrences"]
                ]
                statement = (
                    f"The compliance gap \"{group['description'] or group['category']}\" "
                    f"has recurred in {occurrence_count} of {analyses_count} recorded "
                    f"analyses for this service."
                )
                predictions.append(self._finalize_prediction(
                    counter, "EVIDENCE_BASED", statement,
                    category=group["category"] or "General",
                    confidence=confidence,
                    confidence_basis=f"{occurrence_count} of {analyses_count} analyses",
                    signals=signals,
                    numeric_facts={occurrence_count, analyses_count},
                ))
                counter += 1

            friction_groups = self._collect_friction_groups(analyses)
            for group in friction_groups.values():
                occurrence_count = len(group["analysis_ids"])
                if occurrence_count < MIN_OCCURRENCES_FOR_RECURRENCE:
                    continue
                confidence = _clamp01(occurrence_count / analyses_count)
                signals = [
                    {
                        "source": "friction_point",
                        "reference_id": analysis_id,
                        "detail": text,
                    }
                    for (analysis_id, text) in group["occurrences"]
                ]
                statement = (
                    f"The friction point \"{group['sample_text']}\" has recurred in "
                    f"{occurrence_count} of {analyses_count} recorded analyses for "
                    f"this service."
                )
                predictions.append(self._finalize_prediction(
                    counter, "EVIDENCE_BASED", statement,
                    category="CUSTOMER_FRICTION",
                    confidence=confidence,
                    confidence_basis=f"{occurrence_count} of {analyses_count} analyses",
                    signals=signals,
                    numeric_facts={occurrence_count, analyses_count},
                ))
                counter += 1

        if journeys_count >= MIN_ANALYSES_FOR_PREDICTION:
            intent_groups = self._collect_journey_intent_groups(journeys)
            for group in intent_groups.values():
                occurrence_count = len(group["journey_ids"])
                if occurrence_count < MIN_OCCURRENCES_FOR_RECURRENCE:
                    continue
                confidence = _clamp01(occurrence_count / journeys_count)
                signals = [
                    {
                        "source": "journey_intent",
                        "reference_id": journey_id,
                        "detail": text,
                    }
                    for (journey_id, text) in group["occurrences"]
                ]
                statement = (
                    f"Citizens have repeatedly requested \"{group['sample_text']}\" "
                    f"in {occurrence_count} of {journeys_count} recorded Sandbox "
                    f"journeys for this service."
                )
                predictions.append(self._finalize_prediction(
                    counter, "EVIDENCE_BASED", statement,
                    category="CITIZEN_INTENT",
                    confidence=confidence,
                    confidence_basis=f"{occurrence_count} of {journeys_count} journeys",
                    signals=signals,
                    numeric_facts={occurrence_count, journeys_count},
                ))
                counter += 1

        # --- data_sufficiency: computed purely from counts, never the LLM ---
        if analyses_count < MIN_ANALYSES_FOR_PREDICTION:
            verdict = "INSUFFICIENT"
            predictions = []  # hard rule: never compensate with a guess
        elif not predictions:
            verdict = "LIMITED"
        elif analyses_count >= SUFFICIENT_ANALYSES_THRESHOLD:
            verdict = "SUFFICIENT"
        else:
            verdict = "LIMITED"

        return predictions, {
            "analyses_count": analyses_count,
            "journeys_count": journeys_count,
            "verdict": verdict,
        }

    # =================================================================
    # 3. LLM-PHRASED EXPLANATION (explanation text ONLY -- validated)
    # =================================================================

    def _template_explanation(self, statement, confidence_basis):
        if self.lang == "ar":
            return (
                f"الاستنتاج: {statement} يعتمد هذا على {confidence_basis} من السجل المحفوظ "
                f"لهذه الخدمة؛ وتعكس confidence معدل التكرار فقط وقد حُسبت من البيانات "
                f"المحفوظة وليست تقديرًا."
            )
        return (
            f"{statement} This is based on {confidence_basis} of recorded "
            f"history for this service; confidence reflects the recurrence "
            f"rate only and was computed from stored data, not estimated."
        )

    def _validate_llm_explanation(self, text, numeric_facts):
        """Reject any LLM phrasing that introduces a count-like claim
        not already present in the deterministically computed
        `numeric_facts`. This is the concrete anti-hallucination check:
        the LLM may reword the statement, but it may not invent a new
        number of occurrences/analyses/journeys."""
        if not text or not text.strip():
            return False
        if len(text) > 800:
            return False
        if is_placeholder_or_generic(text):
            return False
        claimed_counts = {
            int(match.group(1))
            for match in re.finditer(
                r"(\d+)\s*(times|occurrence|occurrences|analys[ie]s|journeys?)",
                text,
                flags=re.IGNORECASE,
            )
        }
        if not claimed_counts:
            return True
        return claimed_counts.issubset(numeric_facts)

    def _generate_explanation(self, statement, confidence_basis, signals, numeric_facts):
        template = self._template_explanation(statement, confidence_basis)

        if self.llm is None:
            return template, "template"

        try:
            system_prompt = (
                "You rephrase an already-verified factual statement into one "
                "natural sentence for a government analyst. You must NOT add "
                "any new fact, number, standard, or claim that is not already "
                "in the statement given to you. Do not invent counts."
            )
            user_prompt = (
                f"Statement: {statement}\n"
                f"Evidence basis: {confidence_basis}\n"
                "Rewrite the statement as one clear sentence. Do not add new "
                "numbers or facts."
            )
            if self.lang == "ar":
                user_prompt += "\nWrite the explanation in Arabic. Keep enum values, field names, identifiers, and technical IDs unchanged."
            raw = self.llm.generate(
                system_prompt,
                user_prompt,
                max_new_tokens=180,
                temperature=0,
                timeout=30,
            )
        except Exception:
            return template, "template"

        candidate = extract_clean_explanation(raw)
        if candidate and self._validate_llm_explanation(candidate, numeric_facts):
            return candidate, "ai"
        return template, "template"

    def _finalize_prediction(self, index, prediction_type, statement, category,
                              confidence, confidence_basis, signals, numeric_facts):
        explanation, explanation_source = self._generate_explanation(
            statement, confidence_basis, signals, numeric_facts
        )
        return {
            "prediction_id": f"PRED-{index:03d}",
            "prediction_type": prediction_type,
            "statement": statement,
            "category": category,
            "confidence": round(confidence, 2),
            "confidence_basis": confidence_basis,
            "signals": signals,
            "explanation": explanation,
            "explanation_source": explanation_source,
            "recommendation": None,
        }

    # =================================================================
    # 4. TOP-LEVEL ENTRY POINT
    # =================================================================

    def run(self, prediction_input):
        predictions, data_sufficiency = self._build_predictions(prediction_input)
        generated_at = _now_iso()
        ai_used = any(item.get("explanation_source") == "ai" for item in predictions)
        evidence_refs = [signal.get("reference_id") for item in predictions for signal in item.get("signals", []) if signal.get("reference_id")]
        return {
            "service_id": prediction_input["service_id"],
            "generated_at": generated_at,
            "provenance": provenance_for_mixed_result(llm_present=self.llm is not None, ai_used=ai_used, evidence_references=evidence_refs, generated_at=generated_at),
            "predictions": predictions,
            "data_sufficiency": data_sufficiency,
            "score_methodology": SCORE_METHODOLOGY_MARKER,
        }
