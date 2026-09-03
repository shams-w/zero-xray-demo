import json

from core.json_utils import (
    extract_json_with_salvage,
    has_parse_error,
    match_known_id,
)
from core.framework import classify_gap
from core.llm import ai_label, log_raw_response


ALLOWED_SEVERITIES = {
    "HIGH",
    "MEDIUM",
    "LOW",
}

# ROOT-CAUSE FIX: these used to ALL be mandatory -- REQUIRED_GAP_FIELDS
# was checked with .issubset(raw_gap.keys()), so a gap object missing
# even one field (e.g. the model left out "expected_impact" on one gap
# out of five, or wrote "affected step" instead of "affected_step")
# silently discarded that ENTIRE gap. Against real Ollama 0.32.15 +
# qwen3:4b, small formatting misses on a secondary field were common
# even when the gap's actual substance (which standard, what's wrong,
# why) was completely sound -- so real, usable AI-identified gaps were
# being thrown away wholesale and the agent fell back to the baseline
# every time. The two fields that actually gate correctness/anti-
# hallucination (a real standard_id, a non-empty description) stay
# mandatory; everything else is now backfilled with a safe default
# instead of discarding the whole gap.
REQUIRED_GAP_FIELDS = {
    "standard_id",
    "description",
}

OPTIONAL_GAP_FIELD_DEFAULTS = {
    "category": "General",
    "evidence": "",
    "affected_step": "",
    "severity": "MEDIUM",
    "recommendation": "",
    "expected_impact": "",
}


class GapAnalysisAgent:

    def __init__(self, llm):
        self.llm = llm

    # =========================================================
    # MAIN RUN
    # =========================================================

    def run(
        self,
        service_analysis,
        relevant_standards,
    ):

        applicable_standards = (
            relevant_standards.get(
                "applicable_standards",
                []
            )
        )

        allowed_ids = {
            item["standard_id"]
            for item in applicable_standards
        }

        # =====================================================
        # 1. BUILD SAFE DETERMINISTIC BASELINE
        # =====================================================

        baseline_gaps = self._baseline_gaps(
            service_analysis,
            allowed_ids,
        )

        baseline = {
            "gaps": baseline_gaps,
            "analysis_source": "template",
        }

        if not allowed_ids:
            return baseline

        # =====================================================
        # 2. ASK AI TO IDENTIFY GAPS
        # =====================================================

        prompt = f"""
You are identifying compliance gaps in a government service's
CURRENT journey, using ONLY the applicable standards supplied
below.

APPLICABLE GOVERNMENT STANDARDS:
{json.dumps(
    applicable_standards,
    ensure_ascii=False,
    indent=2
)}

CURRENT SERVICE ANALYSIS:
{json.dumps(
    service_analysis,
    ensure_ascii=False,
    indent=2
)}

CRITICAL RULES:

1. Every gap's standard_id MUST be one of the standard_id
   values listed in APPLICABLE GOVERNMENT STANDARDS above.
   Never invent a standard_id.

2. Every gap must be grounded in specific evidence taken
   from the CURRENT SERVICE ANALYSIS (a step, a manual
   action, a waiting point, an approval, a document, a
   friction point, or a branch visit). Do not invent evidence.

3. Do not report a gap that has no real evidence in the
   CURRENT SERVICE ANALYSIS.

4. severity must be one of: HIGH, MEDIUM, LOW.

5. Each gap must include a concrete, actionable
   recommendation and its expected_impact.

6. Every field must be filled in with real content about THIS
   service. The structure below is a FIELD LIST describing what
   to write, not text to copy: never return a gap whose fields
   are empty strings, placeholder text, or the field
   descriptions themselves. A gap with an empty description or
   an empty standard_id is discarded.

7. If this service genuinely has no compliance gap against the
   standards above, return {{"gaps": []}} -- an empty list is a
   valid, correct answer. Never pad the list with empty objects
   to make it look complete.

Return valid JSON only, using exactly these field names:

{{
  "gaps": [
    {{
      "category": "the area this gap falls in",
      "description": "what specifically is missing or wrong in the current journey",
      "evidence": "the exact step, manual action, waiting point, approval, document or friction point this is based on",
      "affected_step": "the step it applies to",
      "standard_id": "one standard_id copied exactly from the list above",
      "severity": "HIGH or MEDIUM or LOW",
      "recommendation": "the concrete change that would close it",
      "expected_impact": "what improves once it is closed"
    }}
  ]
}}
"""

        # MERGED FROM P1 (defensive restore): safe to instantiate
        # this agent directly with llm=None (tests, ad-hoc scripts)
        # without changing behavior when llm is a real client.
        if not self.llm:
            print(
                f"[AI FAILED -> FALLBACK] "
                "[GAPS] No LLM configured. "
                "Using deterministic baseline."
            )
            return baseline

        # ROOT-CAUSE FIX: 700 tokens is enough for maybe 2-3 gaps with
        # all 8 fields filled out; a real service commonly has 5-8
        # applicable standards, each potentially producing its own
        # gap. Against real Ollama 0.32.15 + qwen3:4b this reliably
        # cut the response off mid-object well before every applicable
        # standard had a chance to be evaluated. Scale with how many
        # standards the model actually has to reason about.
        gaps_max_new_tokens = max(700, len(applicable_standards) * 180)

        response = self.llm.generate(
            system_prompt=(
                "You are a government service gap analysis "
                "agent. Your only source of truth is the "
                "supplied applicable standards and service "
                "analysis."
            ),
            user_prompt=prompt,
            max_new_tokens=gaps_max_new_tokens,
        )

        log_raw_response("GAPS.identify", response)

        ai_result = extract_json_with_salvage(
            response
        )

        # =====================================================
        # 3. INVALID AI OUTPUT -> SAFE BASELINE
        # =====================================================

        if has_parse_error(
            ai_result
        ):
            print(
                "[GAPS] AI JSON invalid. "
                "Using deterministic baseline."
            )

            return baseline

        ai_gaps = self._validate_ai_gaps(
            ai_result,
            allowed_ids,
        )

        # ROOT-CAUSE FIX (invalid/empty gap object -- generic):
        #
        # Two distinct outcomes were previously collapsed into one
        # "no valid gaps -> baseline" branch, which hid the actual
        # failure and made it look like the model had nothing to say:
        #
        #   a) The model returned gap OBJECTS that all failed validation.
        #      The dominant cause was the prompt itself: the JSON
        #      structure above used to be shown with every value as an
        #      empty string (`"description": ""`), which a small model
        #      reliably treats as the literal answer to produce. It
        #      echoed the skeleton back, every object failed the
        #      non-empty-description / known-standard_id checks, and the
        #      whole AI result was thrown away. That is fixed at source
        #      by the descriptive field list above, and a single
        #      corrective retry is given here for the residual cases.
        #   b) The model correctly returned zero gaps. That is a valid
        #      analytical answer, not a failure -- but it was reported as
        #      an AI failure and silently replaced with baseline gaps the
        #      model had implicitly rejected.
        #
        # The deterministic fallback is fully preserved: it still applies
        # whenever the AI genuinely cannot produce usable output.
        raw_gap_count = self._raw_gap_count(ai_result)

        if not ai_gaps and raw_gap_count:
            print(
                f"[GAPS] AI returned {raw_gap_count} gap object(s) but "
                "none were valid (empty description, placeholder text, "
                "or an unknown standard_id). Retrying once with "
                "corrective feedback."
            )

            retry_response = self.llm.generate(
                system_prompt=(
                    "You are a government service gap analysis "
                    "agent. Your only source of truth is the "
                    "supplied applicable standards and service "
                    "analysis."
                ),
                user_prompt=(
                    prompt
                    + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED. Every "
                    "gap you returned was unusable: a gap was either "
                    "missing its description, still contained the "
                    "placeholder/field-description text instead of "
                    "real content, or used a standard_id that is not "
                    "in the APPLICABLE GOVERNMENT STANDARDS list "
                    "above.\n"
                    "Answer again. For each gap, write a real "
                    "description of what is actually wrong in THIS "
                    "service's current journey, and copy its "
                    "standard_id character-for-character from the "
                    "list above. If there is genuinely no gap, "
                    'return {"gaps": []} rather than empty objects.'
                ),
                max_new_tokens=gaps_max_new_tokens,
            )

            log_raw_response("GAPS.identify.retry", retry_response)

            retry_result = extract_json_with_salvage(retry_response)

            if not has_parse_error(retry_result):
                ai_gaps = self._validate_ai_gaps(
                    retry_result,
                    allowed_ids,
                )
                raw_gap_count = self._raw_gap_count(retry_result)

        if ai_gaps:
            return {
                "gaps": ai_gaps,
                "analysis_source": ai_label(),
            }

        if not raw_gap_count:
            # The model reviewed the service against the standards and
            # concluded there is no gap. That is an answer, and it is
            # the AI's answer -- report it as such instead of
            # substituting deterministic gaps it did not identify.
            print(
                "[GAPS] AI reviewed the service and identified no "
                "compliance gaps against the applicable standards."
            )

            return {
                "gaps": [],
                "analysis_source": ai_label(),
            }

        print(
            "[AI FAILED -> FALLBACK] "
            "[GAPS] AI returned no valid gaps after a corrective "
            "retry. Using deterministic baseline."
        )

        return baseline

    @staticmethod
    def _raw_gap_count(ai_result):
        """How many gap objects the model actually returned, before
        validation -- used only to tell "the AI found nothing" apart
        from "the AI produced unusable objects"."""
        if not isinstance(ai_result, dict):
            return 0
        raw_gaps = ai_result.get("gaps", [])
        if not isinstance(raw_gaps, list):
            return 0
        return len([item for item in raw_gaps if isinstance(item, dict)])

    # =========================================================
    # AI OUTPUT VALIDATION
    # =========================================================

    def _validate_ai_gaps(
        self,
        ai_result,
        allowed_ids,
    ):

        if not isinstance(
            ai_result,
            dict
        ):
            return []

        raw_gaps = ai_result.get(
            "gaps",
            [],
        )

        if not isinstance(
            raw_gaps,
            list
        ):
            return []

        valid_gaps = []
        counter = 1

        for raw_gap in raw_gaps:

            if not isinstance(
                raw_gap,
                dict
            ):
                continue

            # Only the two fields that actually matter for
            # correctness/anti-hallucination are mandatory now (see
            # REQUIRED_GAP_FIELDS comment above) -- a gap missing one
            # of the secondary fields is backfilled, not discarded.
            if not REQUIRED_GAP_FIELDS.issubset(
                raw_gap.keys()
            ):
                continue

            # ROOT-CAUSE FIX: exact-match against allowed_ids rejected
            # real gaps whenever the model echoed the id with its
            # title attached (same failure mode as standards_agent).
            matched_standard_id = match_known_id(
                raw_gap.get("standard_id"), allowed_ids
            )
            if not matched_standard_id:
                continue

            severity = str(
                raw_gap.get("severity", "")
            ).upper()

            if severity not in ALLOWED_SEVERITIES:
                severity = OPTIONAL_GAP_FIELD_DEFAULTS["severity"]

            description = str(
                raw_gap["description"]
            ).strip()
            if not description:
                continue

            def _field(key):
                value = raw_gap.get(key, OPTIONAL_GAP_FIELD_DEFAULTS[key])
                text = str(value).strip() if value is not None else ""
                return text or OPTIONAL_GAP_FIELD_DEFAULTS[key]

            valid_gaps.append({
                "gap_id":
                    f"GAP-{counter:03d}",
                "category":
                    _field("category"),
                "description":
                    description,
                "evidence":
                    _field("evidence"),
                "affected_step":
                    _field("affected_step"),
                "standard_id":
                    matched_standard_id,
                "severity": severity,
                "recommendation":
                    _field("recommendation"),
                "expected_impact":
                    _field("expected_impact"),
                # MERGED FROM P1: same fixed 8-category classification
                # used for current-journey steps (core/framework.py),
                # so gaps and steps report through one consistent
                # vocabulary.
                "framework_categories":
                    classify_gap({
                        "category": _field("category"),
                        "description": description,
                        "recommendation": _field("recommendation"),
                        "expected_impact": _field("expected_impact"),
                        "severity": severity,
                    }),
            })

            counter += 1

        return valid_gaps

    # =========================================================
    # DETERMINISTIC BASELINE (fallback logic)
    # =========================================================

    def _baseline_gaps(
        self,
        service_analysis,
        allowed_ids,
    ):

        gaps = []
        counter = 1

        def add_gap(
            category,
            description,
            evidence,
            affected_step,
            preferred_standard,
            severity,
            recommendation,
            impact,
        ):

            nonlocal counter

            if (
                preferred_standard
                not in allowed_ids
            ):
                return

            gaps.append({
                "gap_id":
                    f"GAP-{counter:03d}",
                "category": category,
                "description": description,
                "evidence": evidence,
                "affected_step":
                    affected_step,
                "standard_id":
                    preferred_standard,
                "severity": severity,
                "recommendation":
                    recommendation,
                "expected_impact":
                    impact,
                # MERGED FROM P1: same fixed 8-category classification
                # used for current-journey steps -- applies equally to
                # this deterministic baseline path.
                "framework_categories":
                    classify_gap({
                        "category": category,
                        "description": description,
                        "recommendation": recommendation,
                        "expected_impact": impact,
                        "severity": severity,
                    }),
            })

            counter += 1

        steps = (
            service_analysis.get(
                "steps",
                []
            )
        )

        for step in steps:

            lowered = step.lower()

            repeated_signals = [
                "again",
                "same",
                "repeat",
                "duplicate",
                "re-enter",
                "reenter",
            ]

            if any(
                signal in lowered
                for signal in repeated_signals
            ):

                add_gap(
                    category=
                        "Duplicate Data",
                    description=(
                        "The journey appears to "
                        "repeat information entry."
                    ),
                    evidence=step,
                    affected_step=step,
                    preferred_standard=
                        "STD-02",
                    severity="HIGH",
                    recommendation=(
                        "Reuse the previously "
                        "captured information where "
                        "permitted."
                    ),
                    impact=(
                        "Reduces repeated customer "
                        "or employee effort."
                    ),
                )

        for action in (
            service_analysis.get(
                "manual_actions",
                []
            )
        ):

            add_gap(
                category="Manual Work",
                description=(
                    "The journey contains a "
                    "manual operational action "
                    "that should be assessed for "
                    "automation."
                ),
                evidence=action,
                affected_step=action,
                preferred_standard=
                    "STAGE-05",
                severity="MEDIUM",
                recommendation=(
                    "Automate or assist this action "
                    "where technically and "
                    "operationally feasible; retain "
                    "human control if required."
                ),
                impact=(
                    "Reduces manual handling and "
                    "handoff effort."
                ),
            )

        for waiting in (
            service_analysis.get(
                "waiting_points",
                []
            )
        ):

            add_gap(
                category="Waiting",
                description=(
                    "A waiting point exists in "
                    "the current journey."
                ),
                evidence=waiting,
                affected_step=waiting,
                preferred_standard=
                    "STD-05",
                severity="MEDIUM",
                recommendation=(
                    "Connect the relevant actors "
                    "or systems and provide "
                    "automatic status continuation "
                    "where feasible."
                ),
                impact=(
                    "Reduces delay and manual "
                    "follow-up."
                ),
            )

        for approval in (
            service_analysis.get(
                "approvals",
                []
            )
        ):

            add_gap(
                category="Approval Review",
                description=(
                    "An approval exists and should "
                    "be verified as necessary."
                ),
                evidence=approval,
                affected_step=approval,
                preferred_standard=
                    "STAGE-04",
                severity="MEDIUM",
                recommendation=(
                    "Retain the approval if legally "
                    "or operationally required; "
                    "otherwise simplify it."
                ),
                impact=(
                    "Avoids unnecessary approval "
                    "layers without removing "
                    "required controls."
                ),
            )

        branch_visits = (
            service_analysis.get(
                "branch_visits",
                0
            )
        )

        if branch_visits > 0:
            add_gap(
                category="Branch Visit",
                description=(
                    "The current journey includes "
                    "a physical branch visit."
                ),
                evidence=(
                    f"{branch_visits} branch "
                    "visit(s)"
                ),
                affected_step=
                    "Physical branch visit",
                preferred_standard="STD-02",
                severity="MEDIUM",
                recommendation=(
                    "Assess whether the visit can "
                    "be replaced by a permitted "
                    "digital or assisted action."
                ),
                impact=(
                    "Reduces customer travel and "
                    "effort."
                ),
            )

        return gaps