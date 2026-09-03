import json

from core.json_utils import (
    extract_json_with_salvage,
    has_parse_error,
    match_known_id,
)

from core.standards_catalog import (
    STANDARDS_CATALOG,
    STANDARDS_BY_ID,
    valid_standard_ids,
)
from core.standards_retrieval import (
    retrieve_standard_evidence,
)
from core.llm import ai_label, log_raw_response


class StandardsAgent:

    def __init__(self, llm):
        self.llm = llm

    # =========================================================
    # MAIN RUN
    # =========================================================

    def run(
        self,
        service_analysis,
        standards=None,
    ):

        standards = standards or {}
        retrieval_evidence = retrieve_standard_evidence(
            standards.get("source_text", ""),
            json.dumps(service_analysis, ensure_ascii=False),
            limit=6,
        )

        # =====================================================
        # 1. BUILD SAFE DETERMINISTIC BASELINE
        # =====================================================

        baseline_ids = self._baseline_ids(
            service_analysis
        )

        baseline = self._build_result(
            selected_ids=baseline_ids,
            reasons={
                standard_id: self._reason(
                    standard_id,
                    service_analysis,
                )
                for standard_id in baseline_ids
            },
        )
        baseline["retrieval_evidence"] = retrieval_evidence
        # This gap (no analysis_source at all on standards_agent's
        # result) predates this audit pass -- other agents already
        # carried the field. Added here for consistency with the rest
        # of the pipeline and so this agent is distinguishable in the
        # "which agents used AI successfully" report.
        baseline["analysis_source"] = "template"

        # =====================================================
        # 2. ASK AI TO SELECT APPLICABLE STANDARDS
        # =====================================================
        # ROOT-CAUSE FIX: the previous prompt asked the model to
        # independently CONSTRUCT a list of ids ("select which of
        # these apply and write them out"). Against real qwen3:4b that
        # open-ended "select and type out ids" framing reliably
        # collapsed to an empty applicable_standard_ids: [] even when
        # the JSON itself was well-formed -- a small model faced with
        # a 15-entry catalog and a free-form selection task has an
        # easy escape hatch (answer with nothing) that a fill-in-every-
        # blank task does not. Reframing this as a CHECKLIST -- one
        # explicit true/false decision per catalog id, with every id
        # named for the model instead of left for it to recall and
        # type -- removes that escape hatch: every id must get an
        # entry, so the model can no longer silently skip the whole
        # exercise. This is a prompt/response-shape fix, not a token-
        # budget workaround (that is handled separately, see
        # standards_max_new_tokens below).
        checklist_ids = "\n".join(
            f'- {item["standard_id"]}: {item["title"]} -- {item["requirement"]}'
            for item in STANDARDS_CATALOG
        )

        prompt = f"""
You are deciding, ONE BY ONE, whether each government standard
below applies to a specific service, using ONLY the standards
catalog and service analysis supplied here.

STANDARDS CHECKLIST (id: title -- requirement):
{checklist_ids}

CURRENT SERVICE ANALYSIS:
{json.dumps(
    service_analysis,
    ensure_ascii=False,
    indent=2
)}

RETRIEVED GUIDE EVIDENCE:
{json.dumps(
    retrieval_evidence,
    ensure_ascii=False,
    indent=2
)}

CRITICAL RULES:

1. You MUST include EVERY standard_id from the checklist above
   in your answer, even the ones that do not apply -- for those,
   set "applicable" to false and "why_it_applies" to "".
   Never omit an id and never invent an id that is not in the
   checklist.

2. Set "applicable" to true only when the CURRENT SERVICE
   ANALYSIS (manual actions, waiting points, approvals,
   dependencies, documents, friction points, customer
   interaction) gives real, specific evidence that this
   standard's requirement is genuinely relevant to THIS
   service.

3. For every standard_id marked applicable, give a short
   why_it_applies explanation grounded in specific evidence
   from the CURRENT SERVICE ANALYSIS (not a generic
   restatement of the requirement).

4. Do NOT mark a standard applicable if the service analysis
   gives no real evidence for it.

Return exactly this JSON structure, with one entry per
standard_id from the checklist (do not add or remove ids):

{{
  "selections": {{
    "STD-01": {{"applicable": true or false, "why_it_applies": ""}},
    "STD-02": {{"applicable": true or false, "why_it_applies": ""}}
  }}
}}

Return valid JSON only.
"""

        # MERGED FROM P1 (defensive restore): P2 had dropped this
        # guard, relying on the orchestrator always constructing a
        # real LocalLLM instance. Restoring it so this agent is also
        # safe to instantiate directly with llm=None (as tests and
        # ad-hoc scripts commonly do to exercise the deterministic
        # fallback path), without changing behavior when llm is a
        # real client.
        if not self.llm:
            print(
                f"[AI FAILED -> FALLBACK] "
                "[STANDARDS] No LLM configured. "
                "Using deterministic baseline."
            )
            return baseline

        # ROOT-CAUSE FIX: the checklist response shape (above) asks for
        # ONE JSON object per catalog id -- {"applicable": ..,
        # "why_it_applies": ..} -- for all 15 ids, which is more output
        # than the old free-selection shape, not less: every id now
        # costs its own JSON braces/keys even when "applicable" is
        # false. Under-budgeting this again would just recreate the
        # original truncation failure in a new shape, so the per-id
        # allowance is sized for a full entry (braces, both keys, and
        # a short reason sentence for the applicable ones) rather than
        # the old one-line-reason estimate. core/llm.py is responsible
        # for making sure this budget actually fits inside num_ctx
        # (growing num_ctx rather than silently shrinking this number)
        # -- this is just the realistic target size for the task.
        standards_max_new_tokens = max(900, len(STANDARDS_CATALOG) * 140)

        response = self.llm.generate(
            system_prompt=(
                "You are a government service standards "
                "compliance agent. Your only source of truth "
                "is the supplied standards catalog and service "
                "analysis."
            ),
            user_prompt=prompt,
            max_new_tokens=standards_max_new_tokens,
        )

        log_raw_response("STANDARDS.select", response)

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
                "[STANDARDS] AI JSON invalid. "
                "Using deterministic baseline."
            )

            return baseline

        selected_ids, reasons = (
            self._validate_ai_result(
                ai_result
            )
        )

        if not selected_ids:
            print(
                "[STANDARDS] AI returned no valid "
                "standard_ids. Using deterministic baseline."
            )

            return baseline

        # =====================================================
        # 4. ENFORCE MANDATORY STANDARDS
        # =====================================================
        # STAGE-06 (exception & human handoff) is a mandatory
        # invariant for every redesigned service, regardless of
        # what the AI selected.

        # The AI may omit standards, especially for Arabic input or
        # when the local model returns a very small selection.  The
        # deterministic baseline is the minimum design contract, so
        # AI selection can add to it but can never remove from it.
        selected_ids.update(
            baseline_ids
        )

        for standard_id in selected_ids:

            if standard_id not in reasons:

                reasons[standard_id] = self._reason(
                    standard_id,
                    service_analysis,
                )

        result = self._build_result(
            selected_ids=selected_ids,
            reasons=reasons,
        )
        result["retrieval_evidence"] = retrieval_evidence
        result["analysis_source"] = ai_label()
        return result

    # =========================================================
    # AI OUTPUT VALIDATION
    # =========================================================

    def _validate_ai_result(
        self,
        ai_result,
    ):

        if not isinstance(
            ai_result,
            dict
        ):
            return set(), {}

        allowed_ids = (
            valid_standard_ids()
        )

        selected_ids = set()
        reasons = {}

        # ---------------------------------------------------------
        # Format A (current): checklist -- one entry per catalog id.
        # {"selections": {"STD-01": {"applicable": bool, "why_it_applies": str}}}
        # ---------------------------------------------------------
        raw_selections = ai_result.get("selections")
        if isinstance(raw_selections, dict):
            for raw_key, entry in raw_selections.items():
                matched = match_known_id(raw_key, allowed_ids)
                if not matched:
                    continue
                if isinstance(entry, dict):
                    applicable = bool(entry.get("applicable", False))
                    reason = entry.get("why_it_applies", "")
                elif isinstance(entry, bool):
                    # Tolerate a model collapsing the entry to a bare
                    # boolean instead of the requested object shape.
                    applicable = entry
                    reason = ""
                else:
                    applicable = False
                    reason = ""
                if applicable:
                    selected_ids.add(matched)
                    reason = str(reason).strip() if isinstance(reason, str) else ""
                    if reason:
                        reasons[matched] = reason

        # ---------------------------------------------------------
        # Format B (legacy, still tolerated): free-form id list.
        # {"applicable_standard_ids": [...], "why_it_applies": {...}}
        # Kept so an older/different model that answers in this shape
        # is still accepted -- ROOT-CAUSE FIX (unchanged from before):
        # this used to require an EXACT string match between a raw
        # list entry and a catalog id. Real qwen3:4b output observed
        # against Ollama 0.32.15 routinely echoes the id together with
        # its title (e.g. "STD-01 - Outcome Before Procedure") even
        # though the prompt asks for the bare id -- every one of those
        # entries silently matched nothing, so a response that
        # correctly identified the right standards still produced zero
        # valid selected_ids and fell back to the baseline.
        # match_known_id() extracts the real catalog id from that kind
        # of text instead of discarding it.
        # ---------------------------------------------------------
        raw_ids = ai_result.get("applicable_standard_ids", [])
        raw_reasons = ai_result.get("why_it_applies", {})
        if isinstance(raw_ids, list):
            id_map = {}
            for raw_id in raw_ids:
                matched = match_known_id(raw_id, allowed_ids)
                if matched:
                    id_map[raw_id] = matched
                    selected_ids.add(matched)
            if isinstance(raw_reasons, dict):
                for raw_key, reason in raw_reasons.items():
                    matched = id_map.get(raw_key) or match_known_id(raw_key, allowed_ids)
                    if (
                        matched
                        and isinstance(reason, str)
                        and reason.strip()
                    ):
                        reasons[matched] = reason

        return selected_ids, reasons

    # =========================================================
    # RESULT BUILDING
    # =========================================================

    def _build_result(
        self,
        selected_ids,
        reasons,
    ):

        applicable = []

        for standard_id in sorted(
            selected_ids
        ):

            standard = (
                STANDARDS_BY_ID[
                    standard_id
                ]
            )

            applicable.append({
                **standard,
                "why_it_applies":
                    reasons.get(
                        standard_id,
                        self._reason(
                            standard_id,
                            {},
                        ),
                    ),
            })

        return {
            "applicable_standards":
                applicable
        }

    # =========================================================
    # DETERMINISTIC BASELINE (fallback logic)
    # =========================================================

    def _baseline_ids(
        self,
        service_analysis,
    ):

        # These requirements describe the target assisted journey,
        # not optional keyword matches.  They therefore apply to every
        # service redesign.
        selected_ids = {
            "STD-01",
            "STD-02",
            "STD-03",
            "STD-04",
            "STD-05",
            "STD-06",
            "STAGE-01",
            "STAGE-02",
            "STAGE-03",
            "STAGE-04",
            "STAGE-05",
            "STAGE-06",
            "STAGE-08",
            "READY-01",
        }

        manual_actions = (
            service_analysis.get(
                "manual_actions",
                []
            )
        )

        waiting_points = (
            service_analysis.get(
                "waiting_points",
                []
            )
        )

        approvals = (
            service_analysis.get(
                "approvals",
                []
            )
        )

        dependencies = (
            service_analysis.get(
                "dependencies",
                []
            )
        )

        documents = (
            service_analysis.get(
                "documents",
                []
            )
        )

        friction_points = " ".join(
            service_analysis.get(
                "friction_points",
                []
            )
        ).lower()

        all_text = " ".join(
            service_analysis.get("steps", [])
            + manual_actions
            + waiting_points
            + approvals
            + documents
        ).lower()

        payment_signals = [
            "payment",
            "pay ",
            "fee",
            "fees",
            "دفع",
            "يدفع",
            "سداد",
            "يسدد",
            "رسوم",
        ]

        classification = service_analysis.get("service_classification")
        payment_required = (
            bool(classification.get("requires_customer_payment"))
            if isinstance(classification, dict)
            else any(signal in all_text for signal in payment_signals)
        )

        if payment_required:
            selected_ids.add(
                "STAGE-07"
            )

        return selected_ids

    def _reason(
        self,
        standard_id,
        service,
    ):

        reasons = {
            "STD-01":
                "The journey must be designed around "
                "the customer's intended outcome.",

            "STD-02":
                "Manual or repeated administrative "
                "work exists in the current journey.",

            "STD-03":
                "The service includes direct customer "
                "interaction.",

            "STD-04":
                "The journey contains approval or "
                "customer-control considerations.",

            "STD-05":
                "The service crosses multiple systems, "
                "actors, or waiting points.",

            "STD-06":
                "The service must define exception and "
                "handoff behaviour.",

            "STAGE-03":
                "The service contains information or "
                "data collection that should be checked "
                "for reuse and duplication.",

            "STAGE-04":
                "Approval points exist in the journey.",

            "STAGE-05":
                "The journey contains manual work, "
                "dependencies, or waiting.",

            "STAGE-06":
                "A complete redesigned service must "
                "include an exception and human "
                "handoff path.",

            "STAGE-01":
                "The journey must start from the intended "
                "outcome rather than a service form.",

            "STAGE-02":
                "The assistant must understand intent and "
                "permitted context before planning execution.",

            "STAGE-07":
                "The supplied journey contains a payment or "
                "fee requirement.",

            "STAGE-08":
                "Every complete journey must end with a clear "
                "result and an objection or correction path.",

            "READY-01":
                "The redesigned service requires a baseline and "
                "measurable impact indicators before launch.",
        }

        return reasons.get(
            standard_id,
            "Applicable to the service journey."
        )
