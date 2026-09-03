from core.standards_catalog import (
    STANDARDS_BY_ID,
)
from core.service_classifier import classify_service
from core.llm import ai_label


class StepComplianceAgent:

    def __init__(self, llm=None):
        self.llm = llm

    # =========================================================
    # MAIN
    # =========================================================

    def run(
        self,
        service,
        service_analysis,
        relevant_standards,
    ):

        steps = list(
            service.get(
                "steps",
                []
            )
        )

        applicable_ids = {
            item.get(
                "standard_id"
            )
            for item in relevant_standards.get(
                "applicable_standards",
                []
            )
            if isinstance(
                item,
                dict
            )
        }

        assessments = []
        classification = classify_service(service)

        previous_steps = []

        for index, step in enumerate(
            steps,
            start=1,
        ):

            result = self._assess_step(
                step_number=index,
                step=step,
                service=service,
                applicable_ids=applicable_ids,
                previous_steps=previous_steps,
                total_steps=len(steps),
                classification=classification,
            )

            result = self._apply_human_constraint(
                result=result,
                service=service,
                step_number=index,
                step=step,
            )

            assessments.append(
                result
            )

            previous_steps.append(
                str(step).strip()
            )

        # MERGED FROM P1: AI-primary review of the deterministic
        # baseline above, run once over all non-locked steps. Never
        # overrides a step already forced by a human_constraint.
        assessments = self._apply_ai_review(
            steps=steps,
            baseline_assessments=assessments,
            applicable_ids=applicable_ids,
            service=service,
        )

        return {
            "step_assessment":
                assessments,

            "analysis_source": (
                ai_label()
                if assessments
                and any(
                    item.get("analysis_source") == ai_label()
                    for item in assessments
                )
                else "template"
            ),

            "summary":
                self._build_summary(
                    assessments
                ),
        }

    def _apply_ai_review(
        self, steps, baseline_assessments, applicable_ids, service,
    ):
        """MERGED FROM P1. Ask Ollama to review the SAME steps with
        real understanding and confirm or correct each step's status/
        decision/reason -- the deterministic baseline above only
        catches issues phrased with specific fixed keywords (e.g.
        "repeat"/"again"), so it can miss a real problem phrased
        differently. The AI's answer is used only when it is a fully
        valid, complete replacement for every non-locked step;
        otherwise the deterministic baseline stands as the fallback.

        Steps already forced by a human_constraint (protection level
        REQUIREMENT/HUMAN/AS_IS -- see _apply_human_constraint) are
        left untouched here: the AI review must never be able to
        override a legally/humanly protected step, so those entries
        are excluded from what is sent to the model and kept exactly
        as the protection logic set them.
        """
        if not self.llm or not steps:
            return baseline_assessments

        locked_numbers = {
            item["step_number"]
            for item in baseline_assessments
            if isinstance(item, dict) and item.get("human_constraint")
        }
        reviewable = [
            (i, s) for i, s in enumerate(steps, start=1)
            if i not in locked_numbers
        ]
        if not reviewable:
            return baseline_assessments

        import json as _json
        from core.json_utils import extract_json, has_parse_error

        numbered_steps = "\n".join(
            f"{i}. {s}" for i, s in reviewable
        )
        baseline_compact = [
            {
                "step_number": item["step_number"],
                "status": item["status"],
                "decision": item["decision"],
                "reason": item["reason"],
                "standard_id": item["standard_id"],
            }
            for item in baseline_assessments
            if item["step_number"] not in locked_numbers
        ]
        prompt = f"""You are reviewing step-by-step compliance findings for a service's CURRENT journey.
SERVICE: {str(service.get("service_name", "")).strip()}
CURRENT STEPS (only the non-protected ones you may re-assess):
{numbered_steps}
A deterministic keyword scan already produced this baseline assessment (it only catches issues phrased with specific words like "again"/"repeat", so it can miss real problems phrased differently):
{_json.dumps(baseline_compact, ensure_ascii=False)}
Applicable standard IDs you may cite (never invent others): {sorted(x for x in applicable_ids if x)}
TASK: review EVERY listed step using genuine understanding of what each step actually does and how it relates to the others, not just keyword matching. For each step, decide:
- status: PASS (no issue), PARTIAL (partially problematic, can be improved), or FAIL (should not remain as-is)
- decision: KEEP, REMOVE, MERGE, AUTOMATE, or REVIEW
- reason: a specific, concrete reason grounded in this step's actual content (not generic)
- standard_id: one of the applicable IDs above if relevant, or "" if none applies
Return JSON only, exactly this shape, with one entry per listed step number:
{{"assessments": [{{"step_number": 1, "status": "PASS", "decision": "KEEP", "reason": "", "standard_id": ""}}]}}
"""
        try:
            response = self.llm.generate(
                system_prompt=(
                    "You are a meticulous compliance reviewer who "
                    "reasons about each step's real content and its "
                    "relationship to other steps, instead of pattern-"
                    "matching keywords. You always return valid, "
                    "complete JSON matching exactly the requested "
                    "shape, covering every listed step, with no "
                    "markdown fences and no commentary outside the "
                    "JSON."
                ),
                user_prompt=prompt,
                max_new_tokens=1800,
            )
        except Exception as error:
            print(
                f"[AI FAILED -> FALLBACK] "
                f"[COMPLIANCE] AI review call failed: {error}. "
                "Using deterministic baseline."
            )
            return baseline_assessments

        result = extract_json(response)
        if not isinstance(result, dict) or has_parse_error(result):
            print(
                f"[AI FAILED -> FALLBACK] "
                "[COMPLIANCE] AI review output unusable (parse "
                "error). Using deterministic baseline."
            )
            return baseline_assessments

        raw_items = result.get("assessments")
        # ROOT-CAUSE FIX (same anti-pattern as service_agent's semantic
        # steps and journey_builder's per-stage validation): this used
        # to require the AI's assessments list to be a list AND match
        # `reviewable` step-for-step exactly, or it discarded ALL of
        # them -- even when the model correctly reviewed, say, 7 of 8
        # steps and only truncated or skipped the last one. A partial,
        # genuinely AI-reasoned review of most steps is strictly
        # better than discarding it wholesale for the steps it DID
        # cover; the per-step baseline is still the safety net for
        # whatever it didn't. Only bail out here if there's nothing
        # list-shaped to even look at.
        if not isinstance(raw_items, list):
            print(
                f"[AI FAILED -> FALLBACK] "
                "[COMPLIANCE] AI review output unusable (not a "
                "list). Using deterministic baseline."
            )
            return baseline_assessments

        valid_statuses = {"PASS", "PARTIAL", "FAIL"}
        valid_decisions = {"KEEP", "REMOVE", "MERGE", "AUTOMATE", "REVIEW"}
        reviewable_numbers = {n for n, _ in reviewable}
        by_number = {}
        skipped = 0
        for raw in raw_items:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            try:
                number = int(raw.get("step_number"))
            except (TypeError, ValueError):
                skipped += 1
                continue
            if number not in reviewable_numbers:
                # Hallucinated/duplicate/out-of-range step_number --
                # drop just this one entry, not the whole review.
                skipped += 1
                continue
            status = str(raw.get("status", "")).strip().upper()
            decision = str(raw.get("decision", "")).strip().upper()
            reason = str(raw.get("reason", "")).strip()
            standard_id = str(raw.get("standard_id", "")).strip()
            if status not in valid_statuses or decision not in valid_decisions:
                skipped += 1
                continue
            if standard_id and standard_id not in applicable_ids:
                standard_id = ""
            by_number[number] = {
                "status": status,
                "decision": decision,
                "reason": reason or (
                    "AI-reviewed compliance decision for this step."
                ),
                "standard_id": standard_id,
            }

        if not by_number:
            print(
                f"[AI FAILED -> FALLBACK] "
                "[COMPLIANCE] AI review output unusable (no valid "
                "assessment survived). Using deterministic baseline."
            )
            return baseline_assessments

        if skipped:
            print(
                f"[COMPLIANCE] AI review partially accepted: "
                f"{len(by_number)} of {len(reviewable)} step(s) "
                f"usable, {skipped} malformed entr(y/ies) dropped -- "
                "the deterministic baseline covers the rest."
            )

        merged = []
        for item in baseline_assessments:
            number = item["step_number"]
            if number in locked_numbers or number not in by_number:
                merged.append(item)
                continue
            updated = dict(item)
            updated.update(by_number[number])
            updated["analysis_source"] = ai_label()
            merged.append(updated)

        print(
            "[COMPLIANCE] AI review accepted: "
            f"{len(by_number)} step(s) reviewed."
        )
        return merged

    def _apply_human_constraint(self, result, service, step_number, step):
        constraint = next(
            (
                item
                for item in service.get("protected_steps", [])
                if isinstance(item, dict)
                and int(item.get("step_number", 0) or 0) == step_number
            ),
            None,
        )
        if not constraint:
            return result

        level = str(constraint.get("level", "REQUIREMENT")).upper()
        if level not in {"REQUIREMENT", "HUMAN", "AS_IS"}:
            return result

        # ROOT-CAUSE FIX: Application Language (the request's `lang`,
        # driven by the UI language switcher) is the sole source of
        # truth for output language -- auto-detecting from `step`'s
        # own text let a Protected Step's REASON text end up in
        # whichever language the step happened to be typed in,
        # independently of and potentially contradicting the current
        # UI language. Matches the same precedence already used in
        # agents/journey_builder_agent.py's run(): explicit lang wins;
        # auto-detect from text is only a last-resort fallback for the
        # rare case lang is genuinely absent.
        requested_lang = service.get("lang")
        if requested_lang == "ar":
            is_arabic = True
        elif requested_lang == "en":
            is_arabic = False
        else:
            is_arabic = any("\u0600" <= character <= "\u06ff" for character in str(step))
        reason = str(constraint.get("reason", "")).strip()
        source_reference = str(constraint.get("source_reference", "")).strip()
        constrained = dict(result)

        if level == "AS_IS":
            constrained.update({
                "status": "PARTIAL",
                "decision": "KEEP",
                "reason": (
                    "قيد بشري ملزم يحافظ على الخطوة كما هي. "
                    if is_arabic
                    else "A binding human constraint preserves this step as-is. "
                ) + (reason or ("لم يُذكر سبب إضافي." if is_arabic else "No additional reason supplied.")),
                "replacement": str(step),
                "implementation_status": "HUMAN_LOCKED_AS_IS",
            })
        elif level == "HUMAN":
            constrained.update({
                "status": "PARTIAL",
                "decision": "KEEP",
                "reason": (
                    "يجب أن تبقى هذه الخطوة تحت قرار أو تنفيذ بشري. "
                    if is_arabic
                    else "This step must remain under human judgement or execution. "
                ) + (reason or ("لم يُذكر سبب إضافي." if is_arabic else "No additional reason supplied.")),
                "replacement": str(step),
                "implementation_status": "HUMAN_REQUIRED",
            })
        else:
            if constrained.get("decision") == "REMOVE":
                constrained["decision"] = "AUTOMATE"
                constrained["replacement"] = (
                    "الحفاظ على المتطلب مع نقل تنفيذه الإداري إلى المساعد."
                    if is_arabic
                    else "Preserve the requirement while shifting its administrative execution to the assistant."
                )
            constrained["reason"] = (
                "المتطلب محمي ولا يمكن حذفه، ويمكن فقط تحسين طريقة تنفيذه. "
                if is_arabic
                else "The requirement is protected and cannot be removed; only its execution may be improved. "
            ) + (reason or ("لم يُذكر سبب إضافي." if is_arabic else "No additional reason supplied."))
            constrained["implementation_status"] = "REQUIREMENT_PROTECTED"

        constrained["human_constraint"] = {
            "level": level,
            "reason": reason,
            "source_reference": source_reference,
            "step_number": step_number,
        }
        return constrained

    # =========================================================
    # ASSESS ONE STEP
    # =========================================================

    def _assess_step(
        self,
        step_number,
        step,
        service,
        applicable_ids,
        previous_steps,
        total_steps,
        classification,
    ):

        original_step = str(
            step
        ).strip()

        lowered = (
            original_step.lower()
        )

        # =====================================================
        # 1. EXPLICIT DUPLICATE DATA
        # =====================================================

        duplicate_signals = [
            "same",
            "again",
            "duplicate",
            "re-enter",
            "reenter",
            "repeat",
            "repeated",
            "مرة اخرى",
            "مرة أخرى",
            "مره اخرى",
            "تاني",
            "نفس البيانات",
            "نفس الرقم",
            "اعادة ادخال",
            "إعادة إدخال",
        ]

        if any(
            signal in lowered
            for signal in duplicate_signals
        ):

            return self._result(
                step_number,
                original_step,

                status="FAIL",
                decision="REMOVE",

                reason=(
                    "This step explicitly repeats information "
                    "that has already been captured earlier "
                    "in the journey."
                ),

                standard_id=self._choose_standard(
                    "STD-02",
                    applicable_ids,
                ),

                evidence=(
                    "Repeated information entry creates "
                    "unnecessary customer or employee effort."
                ),

                replacement=(
                    "Reuse the previously captured information "
                    "through the existing service context."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 2. CROSS-STEP RE-ENTRY
        # =====================================================

        reused_data = (
            self._detect_reused_data(
                current_step=original_step,
                previous_steps=previous_steps,
            )
        )

        if reused_data:

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    f"The {reused_data} was already captured "
                    "earlier in the journey. The business activity "
                    "may still be required, but manual re-entry "
                    "should be avoided."
                ),

                standard_id=self._choose_standard(
                    "STD-02",
                    applicable_ids,
                ),

                evidence=(
                    f"A previous step already contains "
                    f"the {reused_data}."
                ),

                replacement=(
                    f"Pass the previously captured {reused_data} "
                    "to the relevant system through a PROPOSED "
                    "digital integration or system-assisted transfer."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 3. PHYSICAL BRANCH VISIT
        # =====================================================

        branch_signals = [
            "visits the service center",
            "visit the service center",
            "visits the branch",
            "visit the branch",
            "goes to the branch",
            "collect at branch",
            "collect from branch",
            "physical branch",
            "يروح الفرع",
            "يذهب الى الفرع",
            "يذهب إلى الفرع",
            "يزور الفرع",
            "زيارة الفرع",
            "زياره الفرع",
            "مركز الخدمة",
            "مركز الخدمه",
            "الحضور شخصيا",
            "الحضور شخصيًا",
        ]

        if any(
            signal in lowered
            for signal in branch_signals
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "The physical visit is administrative customer "
                    "work. The target Agentic journey completes the "
                    "underlying action digitally; unavailable "
                    "integration becomes an exception path."
                ),

                standard_id=self._choose_standard(
                    (
                        "STAGE-07"
                        if classification["requires_customer_payment"]
                        and any(
                            signal in lowered
                            for signal in [
                                "payment", "pay ", "fee",
                                "دفع", "يدفع", "سداد", "رسوم",
                            ]
                        )
                        else "STD-02"
                    ),
                    applicable_ids,
                ),

                evidence=(
                    "The current journey contains a physical "
                    "branch visit."
                ),

                replacement=(
                    "Complete the action through a PROPOSED approved "
                    "digital integration and route only genuine "
                    "exceptions to an assisted channel."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 4. PAYMENT COMPLETION
        # =====================================================

        payment_completion_signals = [
            "completes the payment",
            "complete the payment",
            "pays online",
            "pay online",
            "makes payment",
            "makes the payment",
            "payment online",
            "يدفع",
            "يسدد",
            "دفع الرسوم",
            "سداد الرسوم",
        ]

        if (
            classification["requires_customer_payment"]
            and any(
                signal in lowered
                for signal in payment_completion_signals
            )
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="MERGE",

                reason=(
                    "Payment authorization remains with the customer, "
                    "but it is merged into the unified journey after "
                    "the assistant shows the complete editable plan, "
                    "fees and beneficiary."
                ),

                standard_id=self._choose_standard(
                    "STAGE-07",
                    applicable_ids,
                ),

                evidence=(
                    "The supplied service journey explicitly "
                    "requires customer payment."
                ),

                replacement=(
                    "Prepare the transaction and show fees and beneficiary. "
                    "The customer authorizes and pays; the assistant verifies "
                    "the result and follows up on failure or incomplete debit."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 5. PAYMENT REQUEST / PROMPT
        # =====================================================

        if classification["requires_customer_payment"] and (
            "payment request" in lowered
            or "payment link" in lowered
            or "requested to pay" in lowered
            or "رابط الدفع" in lowered
            or "طلب الدفع" in lowered
            or "مطلوب منه الدفع" in lowered
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "The payment instruction is necessary, "
                    "but it should be generated automatically "
                    "when the service reaches the payment stage."
                ),

                standard_id=self._choose_standard(
                    "STAGE-07",
                    applicable_ids,
                ),

                evidence=(
                    "The service already contains a digital "
                    "payment stage."
                ),

                replacement=(
                    "Automatically issue the payment request "
                    "when required conditions are satisfied."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 6. INTERNAL EMAIL HANDOFF
        # =====================================================

        if (
            "email" in lowered
            or "emails" in lowered
            or "by email" in lowered
            or "ايميل" in lowered
            or "إيميل" in lowered
            or "بريد الكتروني" in lowered
            or "بريد إلكتروني" in lowered
        ):

            internal_terms = [
                "operations",
                "compliance",
                "department",
                "team",
                "supervisor",
                "employee",
                "internal",
                "result back",
                "verification result",
                "العمليات",
                "قسم",
                "فريق",
                "المشرف",
                "الموظف",
                "داخلي",
            ]

            if any(
                target in lowered
                for target in internal_terms
            ):

                return self._result(
                    step_number,
                    original_step,

                    status="FAIL",
                    decision="AUTOMATE",

                    reason=(
                        "This is a manual internal information "
                        "handoff. The handoff should use a "
                        "controlled digital workflow where feasible."
                    ),

                    standard_id=self._choose_standard(
                        "STAGE-05",
                        applicable_ids,
                    ),

                    evidence=(
                        "Manual transfers and repeated follow-up "
                        "should be minimized."
                    ),

                    replacement=(
                        "Transfer the case or result digitally "
                        "with the existing service context."
                    ),

                    implementation_status="PROPOSED",
                )

        # =====================================================
        # 7. ROUTINE DATA / ELIGIBILITY VERIFICATION
        #
        # Objective checks belong to the assistant/system in the target
        # happy path.  Subjective, sensitive or exceptional judgement is
        # still covered by the separate human-handoff path.
        # =====================================================

        routine_verification_signals = [
            "reviews the data",
            "review the data",
            "checks the data",
            "checks for outstanding",
            "verifies the data",
            "verify eligibility",
            "الموظف يراجع البيانات",
            "يراجع البيانات",
            "يتحقق من البيانات",
            "يتأكد من البيانات",
            "يتاكد من البيانات",
            "يتأكد من عدم وجود",
            "يتاكد من عدم وجود",
            "يتحقق من الاهلية",
            "يتحقق من الأهلية",
            "يتحقق من المخالفات",
            "يتأكد من عدم وجود مخالفات",
        ]

        if any(
            signal in lowered
            for signal in routine_verification_signals
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "This is an objective data or eligibility check. "
                    "The assistant should perform it through permitted "
                    "sources and send only conflicts or sensitive cases "
                    "to a human with the full context."
                ),

                standard_id=self._choose_standard(
                    "STAGE-05",
                    applicable_ids,
                ),

                evidence=original_step,

                replacement=(
                    "Verify the data and eligibility automatically "
                    "through authorized sources; route exceptions "
                    "to a human with full context."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 8. MANUAL DOCUMENT CHECK
        # =====================================================

        document_check_signals = [
            "manually checks",
            "manual check",
            "manually verifies",
            "manual verification",
        ]

        document_terms = [
            "document",
            "license",
            "certificate",
            "attachment",
            "uploaded",
        ]

        if (
            any(
                signal in lowered
                for signal in document_check_signals
            )
            and any(
                term in lowered
                for term in document_terms
            )
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="REVIEW",

                reason=(
                    "Document verification may be necessary, "
                    "but the supplied evidence does not establish "
                    "whether it can be fully automated or must "
                    "remain a controlled human check."
                ),

                standard_id=self._choose_standard(
                    "STAGE-05",
                    applicable_ids,
                ),

                evidence=(
                    "A manual verification activity exists, "
                    "but no technical or policy evidence confirms "
                    "safe automated verification."
                ),

                replacement=(
                    "Assess system-assisted verification and "
                    "retain human review where required."
                ),

                implementation_status="REVIEW",
            )

        # =====================================================
        # 9. MANUAL SYSTEM UPDATE
        # =====================================================

        manual_signals = [
            "manual",
            "manually",
            "copy",
            "copies",
            "paste",
            "pastes",
            "يدويا",
            "يدويًا",
            "يدوي",
            "ينسخ",
            "لصق",
        ]

        update_signals = [
            "update",
            "updates",
            "enter",
            "enters",
            "record",
            "records",
            "copy",
            "يحدث",
            "يحدّث",
            "يدخل",
            "يسجل",
            "ينسخ",
        ]

        if (
            any(
                signal in lowered
                for signal in manual_signals
            )
            and any(
                signal in lowered
                for signal in update_signals
            )
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "The underlying business update may be required, "
                    "but the manual system entry should be automated "
                    "or system-assisted where feasible."
                ),

                standard_id=self._choose_standard(
                    "STAGE-05",
                    applicable_ids,
                ),

                evidence=(
                    "The current journey contains a manual "
                    "information-transfer activity."
                ),

                replacement=self._specific_update_replacement(
                    lowered
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 10. CUSTOMER PREFERENCE / CHOICE
        # =====================================================

        customer_actor_signals = [
            "customer",
            "applicant",
            "client",
            "user",
            "العميل",
            "المتعامل",
            "المستخدم",
            "مقدم الطلب",
        ]

        customer_choice_signals = [
            "chooses",
            "selects",
            "decides",
            "specifies",
            "يختار",
            "يحدد",
            "يقرر",
            "يسمي",
        ]

        if (
            any(actor in lowered for actor in customer_actor_signals)
            and any(choice in lowered for choice in customer_choice_signals)
        ):

            is_package_choice = classification["has_package_stage"] and any(
                signal in lowered
                for signal in [
                    "package", "bundle", "tier", "باقة", "باقه",
                    "الحزمة", "الحزمه",
                ]
            )

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="MERGE",

                reason=(
                    "Package selection remains a customer control point, "
                    "while the assistant performs comparison and recommendation."
                    if is_package_choice
                    else "The assistant should recommend this preference from "
                    "permitted context and show it inside the editable plan "
                    "instead of requiring a separate customer step."
                ),

                standard_id=self._choose_standard(
                    "STAGE-02",
                    applicable_ids,
                ),

                evidence=original_step,

                replacement=(
                    "Compare package price, benefits and fit, recommend one, "
                    "and let the customer select or change it."
                    if is_package_choice
                    else "Recommend the best-fit option in the pre-action "
                    "plan and let the customer change it through Edit."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 11. CUSTOMER DATA COLLECTION
        # =====================================================

        if (
            any(
                actor in lowered
                for actor in customer_actor_signals
            )
            and any(
                word in lowered
                for word in [
                    "provide",
                    "provides",
                    "submit",
                    "submits",
                    "enter",
                    "enters",
                    "upload",
                    "uploads",
                    "يرفع",
                    "يرفق",
                    "يقدم",
                    "يدخل",
                    "يعبئ",
                    "يملا",
                ]
            )
        ):

            # Uploading a document is NOT the same thing
            # as a manual system update.
            if (
                "upload" in lowered
                or "uploads" in lowered
                or "يرفع" in lowered
                or "يرفق" in lowered
            ):

                return self._result(
                    step_number,
                    original_step,

                    status="PARTIAL",
                    decision="AUTOMATE",

                    reason=(
                        "Document upload is administrative customer "
                        "work. The target journey retrieves or verifies "
                        "the document from an authorized source, asking "
                        "the customer only when it is genuinely unavailable."
                    ),

                    standard_id=self._choose_standard(
                        "STAGE-03",
                        applicable_ids,
                    ),

                    evidence=(
                        "A customer-provided document exists "
                        "in the current journey."
                    ),

                    replacement=(
                        "Retrieve or verify the required document from "
                        "an authorized source; request it only as an "
                        "explained exception when unavailable."
                    ),

                    implementation_status="PROPOSED",
                )

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "The information may be required, but collection "
                    "must shift to permitted context and data sources "
                    "instead of a separate customer entry step."
                ),

                standard_id=self._choose_standard(
                    "STAGE-03",
                    applicable_ids,
                ),

                evidence=(
                    "Necessary information may be requested "
                    "when required and not already available."
                ),

                replacement=(
                    "Reuse permitted government data and request only "
                    "the single genuinely missing item with its reason."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 12. CUSTOMER INITIATION
        #
        # Only near the START of the journey.
        # =====================================================

        initiation_signals = [
            "requests",
            "request",
            "contacts",
            "contact",
            "asks for",
            "applies for",
            "يطلب",
            "يتواصل",
            "يتقدم بطلب",
            "يبدأ",
            "يبدا",
        ]

        if (
            step_number <= 2
            and any(
                actor in lowered
                for actor in customer_actor_signals
            )
            and any(
                signal in lowered
                for signal in initiation_signals
            )
        ):

            return self._result(
                step_number,
                original_step,

                status="PASS",
                decision="KEEP",

                reason=(
                    "This is a valid service initiation step "
                    "representing the customer's intended outcome."
                ),

                standard_id=self._choose_standard(
                    "STD-01",
                    applicable_ids,
                ),

                evidence=(
                    "The journey begins from the customer's "
                    "intended outcome."
                ),

                replacement=None,

                implementation_status="CURRENT",
            )

        # =====================================================
        # 11. APPROVAL ROUTING
        # =====================================================

        if (
            "approval" in lowered
            or "approve" in lowered
            or "approves" in lowered
            or "supervisor" in lowered
            or "موافقة" in lowered
            or "موافقه" in lowered
            or "اعتماد" in lowered
            or "المشرف" in lowered
            or "المدير" in lowered
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="MERGE",

                reason=(
                    "The approval requirement is preserved as a "
                    "specific control point, but it must not remain "
                    "a separate customer or routing journey step."
                ),

                standard_id=self._choose_standard(
                    "STAGE-04",
                    applicable_ids,
                ),

                evidence=(
                    "The supplied service explicitly contains "
                    "an approval dependency."
                ),

                replacement=(
                    "Embed the necessary approval in the assistant's "
                    "plan with action, data and cost clearly identified."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 14. SERVICE RESULT / ISSUANCE
        # =====================================================

        issuance_signals = [
            "issues the renewed",
            "issues the license",
            "generates the certificate",
            "service is completed",
            "يصدر الرخصة",
            "يصدر الترخيص",
            "يصدر الشهادة",
            "اصدار الرخصة",
            "إصدار الرخصة",
            "اصدار الترخيص",
            "إصدار الترخيص",
            "يتم انجاز الخدمة",
            "يتم إنجاز الخدمة",
        ]

        if any(
            signal in lowered
            for signal in issuance_signals
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "The service result is required, but issuance and "
                    "delivery should be system-executed in the happy path."
                ),

                standard_id=self._choose_standard(
                    "STAGE-08",
                    applicable_ids,
                ),

                evidence=original_step,

                replacement=(
                    "Issue and deliver the service result digitally, "
                    "with correction, objection and human-help paths."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 15. HUMAN REVIEW / INVESTIGATION
        # =====================================================

        human_review_signals = [
            "investigate",
            "investigates",
            "review",
            "reviews",
            "verify",
            "verifies",
            "compliance employee",
            "الموظف يراجع",
            "الموظف يتحقق",
            "الموظف يتأكد",
            "الموظف يتاكد",
            "تحقيق",
            "لجنة",
            "تفتيش ميداني",
        ]

        if any(
            signal in lowered
            for signal in human_review_signals
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "The assistant should orchestrate the normal path. "
                    "Human judgement remains an exception or controlled "
                    "subtask and receives the complete case context."
                ),

                standard_id=self._choose_standard(
                    "STAGE-06",
                    applicable_ids,
                ),

                evidence=(
                    "Human intervention should remain available "
                    "where automation cannot safely continue."
                ),

                replacement=(
                    "Automate objective checks and transfer only "
                    "sensitive, exceptional or authority-limited cases "
                    "to a human with full context."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 13. CUSTOMER RESULT / NOTIFICATION
        # =====================================================

        if (
            any(
                actor in lowered
                for actor in customer_actor_signals
            )
            and any(
                signal in lowered
                for signal in [
                    "receives",
                    "receive",
                    "notified",
                    "notify",
                    "update",
                    "confirmation",
                    "result",
                    "outcome",
                    "collect",
                    "يستلم",
                    "يتسلم",
                    "يستقبل",
                    "النتيجة",
                    "النتيجه",
                    "اشعار",
                    "إشعار",
                    "تأكيد",
                ]
            )
        ):

            return self._result(
                step_number,
                original_step,

                status="PARTIAL",
                decision="AUTOMATE",

                reason=(
                    "The customer-facing outcome is necessary, "
                    "but delivery should be automated or digital "
                    "where the service and policy permit."
                ),

                standard_id=self._choose_standard(
                    "STD-05",
                    applicable_ids,
                ),

                evidence=(
                    "The service must provide a clear "
                    "customer-visible outcome."
                ),

                replacement=(
                    "Deliver or notify the customer of the "
                    "service outcome through a permitted "
                    "digital channel where feasible."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # 14. WAITING
        # =====================================================

        if any(
            word in lowered
            for word in [
                "wait",
                "waiting",
                "pending",
                "ينتظر",
                "انتظار",
                "قيد الانتظار",
                "معلق",
                "معلّق",
            ]
        ):

            return self._result(
                step_number,
                original_step,

                status="FAIL",
                decision="REMOVE",

                reason=(
                    "Waiting is not customer work and should not "
                    "be represented as an active service step."
                ),

                standard_id=self._choose_standard(
                    "STD-05",
                    applicable_ids,
                ),

                evidence=(
                    "The current journey contains a waiting point."
                ),

                replacement=(
                    "Continue monitoring the dependency "
                    "automatically and resume processing "
                    "when it is resolved."
                ),

                implementation_status="PROPOSED",
            )

        # =====================================================
        # DEFAULT
        # =====================================================

        return self._result(
            step_number,
            original_step,

            status="PARTIAL",
            decision="AUTOMATE",

            reason=(
                "The exact implementation needs validation, but "
                "the current activity must be absorbed into the "
                "assistant-orchestrated target journey instead of "
                "being copied into the future happy path."
            ),

            standard_id=self._choose_standard(
                "STAGE-05",
                applicable_ids,
            ),

            evidence=(
                "The step exists in the supplied current journey."
            ),

            replacement=(
                "Orchestrate this activity through the assistant "
                "and route only genuine exceptions to a human with "
                "the complete context."
            ),

            implementation_status="PROPOSED",
        )

    # =========================================================
    # SPECIFIC UPDATE REPLACEMENT
    # =========================================================

    def _specific_update_replacement(
        self,
        lowered,
    ):

        if (
            "application status" in lowered
        ):
            return (
                "Update the application status automatically "
                "when the preceding service event is completed."
            )

        if (
            "compliance result" in lowered
        ):
            return (
                "Synchronize the Compliance result automatically "
                "with the licensing system."
            )

        if (
            "crm" in lowered
        ):
            return (
                "Synchronize the result automatically with CRM."
            )

        return (
            "Synchronize this specific service update "
            "automatically with the relevant system."
        )

    # =========================================================
    # REUSED DATA DETECTION
    # =========================================================

    def _detect_reused_data(
        self,
        current_step,
        previous_steps,
    ):

        current = str(
            current_step
        ).lower()

        previous_text = " ".join(
            str(step).lower()
            for step in previous_steps
        )

        entry_signals = [
            "enter",
            "enters",
            "input",
            "inputs",
            "record",
            "records",
            "copy",
            "copies",
        ]

        if not any(
            signal in current
            for signal in entry_signals
        ):
            return None

        if "customer" in current:
            return None

        concepts = {
            "tracking number": [
                "tracking number",
                "tracking id",
                "shipment number",
            ],

            "emirates id": [
                "emirates id",
                "identity number",
            ],

            "business license number": [
                "business license number",
                "license number",
            ],

            "phone number": [
                "phone number",
                "mobile number",
            ],

            "email address": [
                "email address",
            ],

            "application number": [
                "application number",
                "application id",
            ],

            "reference number": [
                "reference number",
                "reference id",
            ],
        }

        for concept_name, keywords in (
            concepts.items()
        ):

            current_has = any(
                keyword in current
                for keyword in keywords
            )

            if not current_has:
                continue

            previous_has = any(
                keyword in previous_text
                for keyword in keywords
            )

            if previous_has:
                return concept_name

        return None

    # =========================================================
    # RESULT
    # =========================================================

    def _result(
        self,
        step_number,
        step,
        status,
        decision,
        reason,
        standard_id,
        evidence,
        replacement,
        implementation_status,
    ):

        standard_title = ""

        if standard_id:

            standard = (
                STANDARDS_BY_ID.get(
                    standard_id
                )
            )

            if standard:

                standard_title = (
                    standard.get(
                        "title",
                        ""
                    )
                )

        return {
            "step_number":
                step_number,

            "current_step":
                step,

            "status":
                status,

            "decision":
                decision,

            "reason":
                reason,

            "standard_id":
                standard_id,

            "standard_title":
                standard_title,

            "evidence":
                evidence,

            "replacement":
                replacement,

            "implementation_status":
                implementation_status,
        }

    # =========================================================
    # CHOOSE STANDARD
    # =========================================================

    def _choose_standard(
        self,
        preferred,
        applicable_ids,
    ):

        if preferred in applicable_ids:
            return preferred

        return ""

    # =========================================================
    # SUMMARY
    # =========================================================

    def _build_summary(
        self,
        assessments,
    ):

        summary = {
            "total_steps":
                len(
                    assessments
                ),

            "pass": 0,
            "partial": 0,
            "fail": 0,
            "unknown": 0,

            "keep": 0,
            "remove": 0,
            "merge": 0,
            "automate": 0,
            "review": 0,
        }

        for item in assessments:

            status = str(
                item.get(
                    "status",
                    ""
                )
            ).lower()

            decision = str(
                item.get(
                    "decision",
                    ""
                )
            ).lower()

            if status in summary:
                summary[
                    status
                ] += 1

            if decision in summary:
                summary[
                    decision
                ] += 1

        return summary
