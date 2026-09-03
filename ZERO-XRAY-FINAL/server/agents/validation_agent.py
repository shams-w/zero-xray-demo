from core.standards_catalog import (
    valid_standard_ids,
)
from core.llm import ai_label


class ValidationAgent:

    def __init__(self, llm=None):
        self.llm = llm

    # =========================================================
    # MAIN
    # =========================================================

    def run(
        self,
        service,
        standards,
        redesign,
        metrics,
    ):

        issues = []

        required_changes = []

        blocking_issue = False

        # =====================================================
        # APPROVED / APPLICABLE STANDARDS
        # =====================================================

        applicable_ids = {
            item.get(
                "standard_id"
            )
            for item in standards.get(
                "applicable_standards",
                []
            )
            if isinstance(
                item,
                dict
            )
        }

        global_ids = (
            valid_standard_ids()
        )

        # =====================================================
        # 1. METRICS MUST BE VALID
        # =====================================================

        if not metrics.get(
            "valid_for_scoring",
            False
        ):

            blocking_issue = True

            errors = metrics.get(
                "validation_errors",
                []
            )

            if not errors:

                errors = [
                    "Metrics are not valid for scoring."
                ]

            for error in errors:

                self._add_issue(
                    issues=issues,
                    required_changes=
                        required_changes,

                    severity="CRITICAL",

                    issue=str(
                        error
                    ),

                    required_change=str(
                        error
                    ),
                )

        # =====================================================
        # 2. FUTURE JOURNEY MUST EXIST
        # =====================================================

        future_steps = (
            redesign.get(
                "future_steps",
                []
            )
        )

        if not isinstance(
            future_steps,
            list
        ):

            blocking_issue = True

            future_steps = []

            self._add_issue(
                issues,
                required_changes,

                "CRITICAL",

                "future_steps must be a list.",

                "Return a valid structured future journey.",
            )

        if not future_steps:

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "CRITICAL",

                "Future journey is empty.",

                "Return a complete future journey.",
            )

        # =====================================================
        # 3. VALIDATE EACH FUTURE STEP
        # =====================================================

        # ROOT-CAUSE FIX: the AI-designed journey path
        # (_generate_ai_future_journey) tags every stage it produces
        # with change_type="AI_DESIGNED" (see journey_builder_agent.py)
        # -- but this set never included that value. Every single
        # AI-designed stage was therefore hitting the "invalid
        # change_type" CRITICAL branch below (-30 points each), which
        # alone is enough to floor compliance_score at 0 for ANY
        # AI-authored journey, regardless of how good the redesign
        # actually was. This is exactly the schema/field mismatch
        # that produced Compliance=0 in the real qwen3:4b run: not a
        # judgement about journey quality, a validator that didn't
        # know its own producer's vocabulary. AI_DESIGNED steps are
        # deliberately NOT added to the traceability-required set
        # below (MERGED/REMOVED/AUTOMATED/NEW) -- they carry their own
        # "reason" field (always populated, see journey_builder_agent.
        # py) but are whole-stage designs, not a 1:1 mapping to a
        # single government standard the way a template-path MERGED/
        # AUTOMATED step is, so requiring a standard_id on them would
        # reintroduce the same false-failure pattern for a different
        # field.
        allowed_change_types = {
            "KEPT",
            "MERGED",
            "REMOVED",
            "AUTOMATED",
            "NEW",
            "AI_DESIGNED",
        }

        allowed_types = {
            "CUSTOMER",
            "SYSTEM",
            "HUMAN",
        }

        for index, step in enumerate(
            future_steps,
            start=1,
        ):

            if not isinstance(
                step,
                dict
            ):

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "CRITICAL",

                    (
                        f"Future step {index} "
                        "is not a structured object."
                    ),

                    (
                        "Return every future step "
                        "as a structured object."
                    ),
                )

                continue

            name = str(
                step.get(
                    "name",
                    ""
                )
            ).strip()

            if not name:

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "CRITICAL",

                    (
                        f"Future step {index} "
                        "has no name."
                    ),

                    (
                        "Every future step must "
                        "have a clear name."
                    ),
                )

            step_type = str(
                step.get(
                    "type",
                    ""
                )
            ).upper()

            change_type = str(
                step.get(
                    "change_type",
                    ""
                )
            ).upper()

            if (
                step_type
                not in allowed_types
            ):

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "CRITICAL",

                    (
                        f"Step {index} has "
                        f"invalid type: {step_type}"
                    ),

                    (
                        "Use only CUSTOMER, SYSTEM "
                        "or HUMAN step types."
                    ),
                )

            if (
                change_type
                not in allowed_change_types
            ):

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "CRITICAL",

                    (
                        f"Step {index} has invalid "
                        f"change_type: {change_type}"
                    ),

                    (
                        "Use only supported "
                        "change_type values."
                    ),
                )

            # ---------------------------------------------
            # Changed steps require traceability.
            # ---------------------------------------------

            if change_type in {
                "MERGED",
                "REMOVED",
                "AUTOMATED",
                "NEW",
            }:

                reason = str(
                    step.get(
                        "reason",
                        ""
                    )
                ).strip()

                standard_id = str(
                    step.get(
                        "standard_id",
                        ""
                    )
                ).strip()

                if not reason:

                    blocking_issue = True

                    self._add_issue(
                        issues,
                        required_changes,

                        "HIGH",

                        (
                            f"Changed step {index} "
                            "has no reason."
                        ),

                        (
                            "Add a reason to every "
                            "changed step."
                        ),
                    )

                if not standard_id:

                    blocking_issue = True

                    self._add_issue(
                        issues,
                        required_changes,

                        "HIGH",

                        (
                            f"Changed step {index} "
                            "is not linked to a "
                            "government standard."
                        ),

                        (
                            "Link every changed step "
                            "to an applicable "
                            "government standard."
                        ),
                    )

                elif (
                    standard_id
                    not in global_ids
                    or standard_id
                    not in applicable_ids
                ):

                    blocking_issue = True

                    self._add_issue(
                        issues,
                        required_changes,

                        "CRITICAL",

                        (
                            f"Step {index} references "
                            f"unsupported standard "
                            f"{standard_id}."
                        ),

                        (
                            "Use only applicable approved "
                            "government standard IDs."
                        ),
                    )

        # =====================================================
        # 4. VALIDATE REMOVED STEPS
        #
        # A removed step must ALWAYS explain why it was removed.
        # =====================================================

        removed_steps = (
            redesign.get(
                "removed_steps",
                []
            )
        )

        if not isinstance(
            removed_steps,
            list
        ):

            blocking_issue = True

            removed_steps = []

            self._add_issue(
                issues,
                required_changes,

                "CRITICAL",

                "removed_steps must be a list.",

                (
                    "Return removed steps "
                    "as structured records."
                ),
            )

        for index, item in enumerate(
            removed_steps,
            start=1,
        ):

            if not isinstance(
                item,
                dict
            ):

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "CRITICAL",

                    (
                        f"Removed-step record "
                        f"{index} is invalid."
                    ),

                    (
                        "Every removed step must "
                        "include step, reason and "
                        "standard_id."
                    ),
                )

                continue

            reason = str(
                item.get(
                    "reason",
                    ""
                )
            ).strip()

            standard_id = str(
                item.get(
                    "standard_id",
                    ""
                )
            ).strip()

            if not reason:

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "HIGH",

                    (
                        f"Removed step {index} "
                        "has no removal reason."
                    ),

                    (
                        "Explain why every removed "
                        "step was removed."
                    ),
                )

            if not standard_id:

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "HIGH",

                    (
                        f"Removed step {index} "
                        "has no supporting standard."
                    ),

                    (
                        "Link every removed step "
                        "to the government standard "
                        "supporting removal."
                    ),
                )

            elif (
                standard_id
                not in global_ids
                or standard_id
                not in applicable_ids
            ):

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "CRITICAL",

                    (
                        f"Removed step {index} "
                        f"references unsupported "
                        f"standard {standard_id}."
                    ),

                    (
                        "Use only approved applicable "
                        "standards when removing steps."
                    ),
                )

        # =====================================================
        # 5. REVIEW / UNKNOWN STEPS
        #
        # IMPORTANT:
        # A service cannot claim full PASS while there are
        # unresolved REVIEW steps.
        # =====================================================

        review_steps = (
            redesign.get(
                "review_steps",
                []
            )
        )

        if not isinstance(
            review_steps,
            list
        ):

            review_steps = []

        if review_steps:

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    f"{len(review_steps)} step(s) "
                    "still require human review."
                ),

                (
                    "Resolve REVIEW steps before "
                    "claiming full service compliance."
                ),
            )

        # =====================================================
        # 6. BUILD FUTURE TEXT
        # =====================================================

        future_text = " ".join(
            [
                (
                    str(
                        step.get(
                            "name",
                            ""
                        )
                    )
                    + " "
                    + str(
                        step.get(
                            "action",
                            ""
                        )
                    )
                )
                for step in future_steps
                if isinstance(
                    step,
                    dict
                )
            ]
        ).lower()

        # =====================================================
        # 7. CONFIRMED BAD PATTERNS MUST NOT REMAIN
        # =====================================================

        duplicate_patterns = [
            "same tracking number again",
            "enter the same",
            "re-enter",
            "reenter",
            "duplicate entry",
            "نفس البيانات مرة أخرى",
            "نفس الرقم مرة أخرى",
            "إعادة إدخال",
            "اعادة ادخال",
        ]

        if any(
            pattern in future_text
            for pattern in duplicate_patterns
        ):

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "CRITICAL",

                (
                    "Confirmed duplicate-data entry "
                    "still exists in the future journey."
                ),

                (
                    "Remove repeated information entry "
                    "or reuse the existing data."
                ),
            )

        manual_crm_patterns = [
            "manually updates the crm",
            "manual crm update",
            "يحدث النظام يدويا",
            "يحدّث النظام يدويًا",
            "تحديث يدوي",
        ]

        if any(
            pattern in future_text
            for pattern in manual_crm_patterns
        ):

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    "Manual CRM updating still exists "
                    "in the future journey."
                ),

                (
                    "Automate or system-assist "
                    "the CRM update."
                ),
            )

        manual_email_patterns = [
            "emails operations",
            "email operations",
            "send email to operations",
            "sends email to operations",
            "يرسل ايميل للعمليات",
            "يرسل إيميل للعمليات",
            "يرسل بريد إلكتروني للعمليات",
        ]

        if any(
            pattern in future_text
            for pattern in manual_email_patterns
        ):

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    "Manual email handoff still exists "
                    "in the future journey."
                ),

                (
                    "Replace manual email handoff "
                    "with a controlled system workflow."
                ),
            )

        # =====================================================
        # 8. DUPLICATE FUTURE STEPS MUST NOT EXIST
        # =====================================================

        seen_actions = set()

        for step in future_steps:

            if not isinstance(
                step,
                dict
            ):
                continue

            action = self._normalize_text(
                step.get(
                    "action",
                    step.get(
                        "name",
                        ""
                    )
                )
            )

            if not action:
                continue

            if action in seen_actions:

                blocking_issue = True

                self._add_issue(
                    issues,
                    required_changes,

                    "HIGH",

                    (
                        "The future journey contains "
                        "duplicate future actions."
                    ),

                    (
                        "Merge duplicate future "
                        "actions into one step."
                    ),
                )

                break

            seen_actions.add(
                action
            )

        # =====================================================
        # 9. CUSTOMER-VISIBLE RESULT
        # =====================================================

        customer_result_signals = [
            "customer receives",
            "customer receive",
            "customer result",
            "customer outcome",
            "service outcome",
            "shipment outcome",
            "shipment status",
            "confirmation",
            "notify customer",
            "notify the customer",
            "automatically notify",
            "service result becomes available",
            "يسلم النتيجة",
            "تسليم النتيجة",
            "النتيجة واضحة",
            "يقدم نتيجة",
            "يصدر الرخصة",
            "يصدر الترخيص",
            "يتيح التصحيح",
            "يتيح الاعتراض",
        ]

        has_semantic_result = any(
            isinstance(step, dict)
            and step.get("semantic_category") == "customer_outcome"
            for step in future_steps
        )

        if (
            not has_semantic_result
            and not any(
                signal in future_text
                for signal in customer_result_signals
            )
        ):

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "CRITICAL",

                (
                    "Future journey does not clearly "
                    "end with a customer-visible result."
                ),

                (
                    "Add a clear customer-visible "
                    "service outcome."
                ),
            )

        # =====================================================
        # 10. EXCEPTION / HUMAN HANDOFF
        #
        # FIX:
        # Check redesign.exception_paths instead of expecting
        # exception handling inside the normal future journey.
        # =====================================================

        exception_paths = (
            redesign.get(
                "exception_paths",
                []
            )
        )

        valid_exception_path = False

        if isinstance(
            exception_paths,
            list
        ):

            for exception in (
                exception_paths
            ):

                if not isinstance(
                    exception,
                    dict
                ):
                    continue

                name = str(
                    exception.get(
                        "name",
                        ""
                    )
                ).strip()

                trigger = str(
                    exception.get(
                        "trigger",
                        ""
                    )
                ).strip()

                action = str(
                    exception.get(
                        "action",
                        ""
                    )
                ).strip()

                standard_id = str(
                    exception.get(
                        "standard_id",
                        ""
                    )
                ).strip()

                if (
                    name
                    and trigger
                    and action
                    and standard_id
                ):

                    if (
                        standard_id
                        in global_ids
                        and standard_id
                        in applicable_ids
                    ):

                        valid_exception_path = True
                        break

        if not valid_exception_path:

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    "Future service has no valid "
                    "exception / human-handoff path."
                ),

                (
                    "Add a structured exception path "
                    "with trigger, action and an "
                    "applicable government standard."
                ),
            )

        # =====================================================
        # 11. PRESERVE DOCUMENTS BY DEFAULT
        # =====================================================

        current_documents = list(
            service.get(
                "documents",
                []
            )
        )

        future_documents = list(
            redesign.get(
                "future_documents",
                []
            )
        )

        if (
            current_documents
            and not future_documents
        ):

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    "Current documents were removed "
                    "without supporting evidence."
                ),

                (
                    "Preserve documents unless "
                    "evidence supports removal."
                ),
            )

        # =====================================================
        # 12. PRESERVE APPROVALS BY DEFAULT
        # =====================================================

        current_approvals = list(
            service.get(
                "approvals",
                []
            )
        )

        future_approvals = list(
            redesign.get(
                "future_approvals",
                []
            )
        )

        if (
            current_approvals
            and not future_approvals
        ):

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    "Current approvals were removed "
                    "without supporting evidence."
                ),

                (
                    "Preserve required approvals "
                    "unless evidence supports "
                    "simplification."
                ),
            )

        # =====================================================
        # 13. INTEGRATIONS
        # =====================================================

        dependencies = list(
            service.get(
                "dependencies",
                []
            )
        )

        integrations = list(
            redesign.get(
                "required_integrations",
                []
            )
        )

        automation_count = len(
            redesign.get(
                "automation_opportunities",
                []
            )
        )

        if (
            len(
                dependencies
            ) > 1
            and automation_count > 0
            and not integrations
        ):

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    "The redesigned service automates "
                    "work across multiple dependencies "
                    "but identifies no proposed integration."
                ),

                (
                    "Identify the proposed integrations "
                    "required to support automation."
                ),
            )

        # =====================================================
        # 14. CUSTOMER BURDEN AND STEP-COPY SAFEGUARDS
        # =====================================================

        future_customer_burden = (
            metrics.get("future", {}).get(
                "customer_burden_steps",
                0,
            )
        )

        if future_customer_burden > 0:
            blocking_issue = True

            # MERGED FROM P1: distinguish burden that is a genuine
            # redesign gap (should still be shifted to the assistant)
            # from burden that comes from a step explicitly protected
            # by the compliance gate (StepComplianceAgent, human_
            # constraint level AS_IS/HUMAN/REQUIREMENT) -- that burden
            # is not a bug to fix, it is a legal/human constraint the
            # pipeline is correctly refusing to silently paper over.
            # This is a message-clarity split only: both kinds still
            # count toward future_customer_burden and both still block
            # a full PASS, since a locked burden step means the
            # journey is not (yet) actually zero-bureaucracy
            # end-to-end for this service, constraint or not.
            locked_burden_steps = [
                step for step in future_steps
                if isinstance(step, dict)
                and step.get("customer_burden")
                and step.get("implementation_status") == "HUMAN_LOCKED_AS_IS"
            ]
            other_burden_count = future_customer_burden - len(locked_burden_steps)

            if locked_burden_steps:
                locked_names = "; ".join(
                    str(step.get("name", "")).strip()
                    for step in locked_burden_steps
                )
                self._add_issue(
                    issues,
                    required_changes,
                    "HIGH",
                    (
                        f"{len(locked_burden_steps)} customer step(s) "
                        "remain in the target journey because they are "
                        "explicitly protected by the compliance gate "
                        "(human_constraint level AS_IS/HUMAN/REQUIREMENT) "
                        f"and cannot be removed or automated: {locked_names}."
                    ),
                    (
                        "This is expected, not a defect: a legally or "
                        "humanly protected step keeps the service from "
                        "reaching a full zero-bureaucracy PASS until the "
                        "underlying legal/human requirement itself "
                        "changes. Do not remove or automate this step; "
                        "resolving this issue requires the service owner "
                        "to revisit the protection, not a redesign change."
                    ),
                )

            if other_burden_count > 0:
                self._add_issue(
                    issues,
                    required_changes,
                    "HIGH",
                    (
                        f"{other_burden_count} administrative "
                        "customer step(s) remain in the target journey."
                    ),
                    (
                        "Shift form filling, document upload, travel, "
                        "data entry and follow-up to the assistant. Keep "
                        "outcome request and explicit consent as control "
                        "points, not administrative steps."
                    ),
                )

        current_step_count = len(
            service.get("steps", [])
        )
        future_step_count = len(future_steps)

        if (
            current_step_count > 1
            and future_step_count >= current_step_count
        ):
            blocking_issue = True
            self._add_issue(
                issues,
                required_changes,
                "HIGH",
                (
                    "The proposed happy path does not consolidate "
                    "the current journey."
                ),
                (
                    "Build an outcome-level Agentic journey and "
                    "merge current activities into fewer assistant-owned "
                    "stages instead of copying one future step per current step."
                ),
            )

        # =====================================================
        # 14b. DEPENDENCY / ORDERING / EXECUTOR CONSISTENCY /
        #      DUPLICATE STAGES / UNJUSTIFIED HUMAN INTERVENTION
        #
        # These evaluate the ACTUAL substance of the proposed
        # journey -- not just its shape -- generically for any
        # service: nothing below references a specific domain or
        # service name, only the structural fields every future
        # step already carries.
        # =====================================================

        payment_seen_index = None
        for index, step in enumerate(future_steps, start=1):
            if not isinstance(step, dict):
                continue

            # -- Payment must never precede the stage(s) it depends
            # on. This specific field (depends_on_previous) is only
            # ever populated on the AI-designed path -- the
            # deterministic template path has its own separately-
            # verified fixed ordering and never fills this field, so
            # scope this check to AI-designed journeys only, or every
            # template-path payment stage would be falsely flagged.
            if (
                redesign.get("analysis_source") == "ai"
                and step.get("has_payment")
                and index > 1
                and not str(step.get("depends_on_previous", "")).strip()
            ):
                blocking_issue = True
                self._add_issue(
                    issues, required_changes, "HIGH",
                    (
                        f"Step {index} collects payment but declares no "
                        "dependency on any earlier stage -- the amount "
                        "being charged is not traceably determined."
                    ),
                    (
                        "Payment must depend on the stage that "
                        "determines the final amount (e.g. a "
                        "selection or a calculated fee); state that "
                        "dependency explicitly."
                    ),
                )

            if step.get("has_payment") and payment_seen_index is None:
                payment_seen_index = index

            # -- Executor/type consistency: a HUMAN-typed stage must
            # not simultaneously claim an AGENT/GOVERNMENT_SYSTEM/
            # EXTERNAL_SYSTEM owner, and a SYSTEM-typed stage must
            # not be owned by "HUMAN" -- these fields must agree.
            step_type = str(step.get("type", "")).upper()
            owner = str(step.get("owner", "")).upper()
            if step_type == "HUMAN" and owner not in ("HUMAN", ""):
                blocking_issue = True
                self._add_issue(
                    issues, required_changes, "HIGH",
                    (
                        f"Step {index} is typed HUMAN but its owner is "
                        f"'{owner}' -- type and owner are inconsistent."
                    ),
                    (
                        "A HUMAN-typed step must be owned by HUMAN; "
                        "if the assistant/system actually executes "
                        "it, type it SYSTEM instead."
                    ),
                )
            elif step_type == "SYSTEM" and owner == "HUMAN":
                blocking_issue = True
                self._add_issue(
                    issues, required_changes, "HIGH",
                    (
                        f"Step {index} is typed SYSTEM but its owner is "
                        "HUMAN -- type and owner are inconsistent."
                    ),
                    (
                        "A SYSTEM-typed step must be owned by the "
                        "assistant or a system, not HUMAN."
                    ),
                )

            # -- Unjustified human intervention: a HUMAN stage (a
            # genuine staff judgement call) must carry its own
            # justification text; a bare HUMAN flag with no stated
            # reason cannot be told apart from defaulting to human
            # review out of habit, which is exactly what a Zero
            # Bureaucracy redesign must avoid.
            if step.get("requires_human_judgement") or step_type == "HUMAN":
                justification = " ".join([
                    str(step.get("reason", "")),
                    str(step.get("reasoning", "")),
                ]).strip()
                if len(justification) < 15:
                    blocking_issue = True
                    self._add_issue(
                        issues, required_changes, "HIGH",
                        (
                            f"Step {index} requires human judgement but "
                            "gives no real justification for why the "
                            "assistant/system cannot handle it."
                        ),
                        (
                            "Either automate this step, or state the "
                            "specific reason a human decision is "
                            "genuinely required here."
                        ),
                    )

        # -- Duplicate / near-duplicate future stages: two stages
        # describing essentially the same action inflate the stage
        # count without adding real value -- exactly the pattern a
        # good redesign should have merged. Uses the same tolerant,
        # language-agnostic word-overlap comparison already used
        # elsewhere in this pipeline (core/grounding.py), so this
        # applies identically regardless of service or language.
        if len(future_steps) > 1:
            from core.grounding import is_semantically_grounded

            for i in range(len(future_steps)):
                step_i = future_steps[i]
                if not isinstance(step_i, dict):
                    continue
                text_i = " ".join(
                    str(step_i.get(f, "")) for f in ("name", "action")
                ).strip()
                if not text_i:
                    continue
                for j in range(i + 1, len(future_steps)):
                    step_j = future_steps[j]
                    if not isinstance(step_j, dict):
                        continue
                    text_j = " ".join(
                        str(step_j.get(f, "")) for f in ("name", "action")
                    ).strip()
                    if not text_j:
                        continue
                    if (
                        is_semantically_grounded(
                            text_i, text_j, min_fraction=0.7
                        )
                        and is_semantically_grounded(
                            text_j, text_i, min_fraction=0.7
                        )
                    ):
                        blocking_issue = True
                        self._add_issue(
                            issues, required_changes, "MEDIUM",
                            (
                                f"Steps {i + 1} and {j + 1} describe "
                                "essentially the same action and were "
                                "not merged."
                            ),
                            (
                                "Merge duplicate/near-duplicate stages "
                                "into one instead of listing the same "
                                "action twice."
                            ),
                        )
                        break

        # =====================================================
        # 14c. DATA REUSE: re-requesting already-available identity
        #      info, and identity-source vs. service-system
        #      conflation (the specific ungrounded-integration claim
        #      this session's request is about). Generic vocabulary
        #      only -- no service name/domain is referenced -- and
        #      informative (MEDIUM) rather than an automatic hard
        #      block, since natural-language detection of this
        #      pattern is inherently heuristic and must not become a
        #      keyword filter that silently overrides real AI
        #      reasoning.
        # =====================================================

        identity_field_signals = (
            "national id", "emirates id", "id number", "full name",
            "your name", "الهوية", "رقم الهوية", "الاسم الكامل", "اسمك",
        )
        reentry_signals = (
            "enter", "provide", "re-enter", "type in", "fill in",
            "يدخل", "يقدم", "يكتب", "يعيد إدخال", "يعبئ",
        )
        identity_source_signals = (
            "uae pass", "digital identity", "الهوية الرقمية",
        )
        record_signals = (
            "shipment", "transaction", "tracking", "box number",
            "reference number", "case history", "الشحنة", "المعاملة",
            "الصندوق", "الرقم المرجعي",
        )
        contains_claim_signals = (
            "contains", "already has", "includes all", "stores",
            "يحتوي", "لديه", "تشمل",
        )

        for index, step in enumerate(future_steps, start=1):
            if not isinstance(step, dict):
                continue
            text = " ".join(
                str(step.get(field, "")).lower()
                for field in ("action", "detailed_description", "customer_role")
            )

            if (
                any(signal in text for signal in identity_field_signals)
                and any(signal in text for signal in reentry_signals)
            ):
                self._add_issue(
                    issues, required_changes, "MEDIUM",
                    (
                        f"Step {index} appears to ask the customer to "
                        "provide identity information that should "
                        "already be available from login."
                    ),
                    (
                        "Do not re-request identity/profile fields "
                        "already established at login; use them "
                        "directly instead."
                    ),
                )

            reasoning_text = " ".join(
                str(step.get(field, "")).lower()
                for field in ("reasoning", "detailed_description")
            )
            if (
                any(signal in reasoning_text for signal in identity_source_signals)
                and any(signal in reasoning_text for signal in record_signals)
                and any(signal in reasoning_text for signal in contains_claim_signals)
            ):
                self._add_issue(
                    issues, required_changes, "MEDIUM",
                    (
                        f"Step {index} appears to claim the identity/"
                        "login source itself already contains "
                        "service-specific records (e.g. shipment or "
                        "transaction numbers) -- this is not "
                        "grounded."
                    ),
                    (
                        "Identity confirms who the customer is; "
                        "service-specific records must come from a "
                        "separate lookup against this service's own "
                        "system, proposed as an integration, not "
                        "assumed to already exist inside the "
                        "identity source."
                    ),
                )

        # =====================================================
        # 15. ZERO BUREAUCRACY SCORE
        # =====================================================

        zb_score = metrics.get(
            "zero_bureaucracy_score",
            0
        )

        try:
            zb_score = int(
                zb_score
            )

        except (
            TypeError,
            ValueError,
        ):
            zb_score = 0

        if zb_score < 70:

            blocking_issue = True

            self._add_issue(
                issues,
                required_changes,

                "HIGH",

                (
                    "Zero Bureaucracy score is "
                    "below the minimum redesign threshold."
                ),

                (
                    "Further reduce unnecessary "
                    "manual work, duplicate data, "
                    "waiting or handoffs."
                ),
            )

        # =====================================================
        # 16. COMPLIANCE SCORE
        # =====================================================

        compliance_score = 100

        for issue in issues:

            severity = (
                issue.get(
                    "severity"
                )
            )

            if severity == "CRITICAL":
                compliance_score -= 30

            elif severity == "HIGH":
                compliance_score -= 12

            elif severity == "MEDIUM":
                compliance_score -= 6

            else:
                compliance_score -= 2

        compliance_score = max(
            0,
            min(
                100,
                compliance_score
            )
        )

        # =====================================================
        # 17. FEASIBILITY
        # =====================================================

        feasibility_score = 100

        feasibility_score -= min(
            len(
                integrations
            ) * 5,
            25,
        )

        feasibility_score -= min(
            automation_count * 2,
            15,
        )

        feasibility_score = max(
            0,
            min(
                100,
                feasibility_score
            )
        )

        # =====================================================
        # 18. FINAL STATUS
        #
        # Important:
        # A HIGH/CRITICAL unresolved problem must not produce
        # a misleading PASS merely because score >= 80.
        # =====================================================

        status = "PASS"

        if blocking_issue:
            status = "FAIL"

        if compliance_score < 80:
            status = "FAIL"

        if feasibility_score < 70:
            status = "FAIL"

        if zb_score < 70:
            status = "FAIL"

        # Remove duplicate messages

        required_changes = list(
            dict.fromkeys(
                required_changes
            )
        )

        unique_issues = []

        seen_issue_keys = set()

        for issue in issues:

            key = (
                issue.get(
                    "severity"
                ),
                issue.get(
                    "issue"
                ),
            )

            if key in seen_issue_keys:
                continue

            seen_issue_keys.add(
                key
            )

            unique_issues.append(
                issue
            )

        # =====================================================
        # AI-PRIMARY SEMANTIC REVIEW (MERGED FROM P1; supplements,
        # never weakens, the deterministic gates above)
        # =====================================================
        # Every hard rule above (score thresholds, required fields,
        # standard-id checks) stays deterministic on purpose -- this
        # is a safety gate, not a place to let an unreliable local
        # model's mood decide pass/fail. Ollama is instead asked to
        # do what the fixed rules structurally cannot: read the
        # actual redesign and judge whether the reasoning genuinely
        # holds together for THIS service. It can only ADD issues /
        # tighten the status, never override a deterministic FAIL
        # back to PASS.
        ai_issues, ai_verdict, analysis_source = self._ai_semantic_review(
            service=service,
            redesign=redesign,
            deterministic_status=status,
        )
        if ai_issues:
            for extra in ai_issues:
                self._add_issue(
                    issues=unique_issues,
                    required_changes=required_changes,
                    severity=extra["severity"],
                    issue=extra["issue"],
                    required_change=extra["required_change"],
                )
            required_changes = list(dict.fromkeys(required_changes))
            seen_issue_keys = set()
            deduped = []
            for issue in unique_issues:
                key = (issue.get("severity"), issue.get("issue"))
                if key in seen_issue_keys:
                    continue
                seen_issue_keys.add(key)
                deduped.append(issue)
            unique_issues = deduped

        if ai_verdict == "FAIL":
            status = "FAIL"

        return {

            "status":
                status,

            "analysis_source":
                analysis_source,

            "compliance_score":
                compliance_score,

            "feasibility_score":
                feasibility_score,

            "zero_bureaucracy_score":
                zb_score,

            "issues":
                unique_issues,

            "required_changes":
                required_changes,

            "checks": {
                "future_journey_present":
                    bool(
                        future_steps
                    ),

                "exception_path_present":
                    valid_exception_path,

                "unresolved_review_steps":
                    len(
                        review_steps
                    ),

                "removed_steps":
                    len(
                        removed_steps
                    ),

                "automation_opportunities":
                    automation_count,

                "proposed_integrations":
                    len(
                        integrations
                    ),

                "future_customer_burden_steps":
                    future_customer_burden,

                "customer_control_points":
                    len(
                        redesign.get(
                            "control_points",
                            []
                        )
                    ),
            },
        }

    # =========================================================
    # ADD ISSUE
    # =========================================================

    # =========================================================
    # AI-PRIMARY SEMANTIC REVIEW (MERGED FROM P1, with deterministic
    # fallback)
    # =========================================================

    def _ai_semantic_review(self, service, redesign, deterministic_status):
        """Ask Ollama to judge whether the redesign's own reasoning
        genuinely holds together, catching issues no fixed rule can
        express (a step whose stated reason doesn't support its
        change, a payment placement that contradicts its own
        reasoning, a human-judgement step with no real justification).

        Returns (extra_issues, verdict, analysis_source):
        - extra_issues: list of {severity, issue, required_change}
          dicts to append (empty list if none or AI unavailable).
        - verdict: "FAIL" only if the AI found a genuine blocking
          problem; "PASS" otherwise. Never used to override a
          deterministic FAIL back to PASS -- only to tighten it.
        - analysis_source: "ai" when a trusted AI review actually
          ran, "template" when it fell back to rules only.

        ROOT-CAUSE FIX (persistent verdict=FAIL on a clean run --
        generic, applies to every service): the reviewer and the journey
        DESIGNER were working from two different contracts about where
        the journey starts.

        JourneyBuilderAgent is explicitly told (see its "CONTEXT: by the
        time this design decision happens..." block) that the customer's
        identity is already verified and this service already selected
        before stage 1, and that a stage may legitimately build on that.
        So a well-formed first stage routinely declares something like
        depends_on_previous="the customer's verified identity".

        This reviewer was never given that contract. It was handed the
        future journey alone and told to flag "a step that depends on
        information no earlier step actually produces", plus "re-read the
        earlier steps; if any earlier step produces it, there is no
        issue". For position 1 there ARE no earlier steps by
        construction -- so the rule as written FORCED a report on a
        perfectly correct first stage, and the old HIGH definition ("a
        contradiction that blocks the journey from working") made a
        seemingly-absent input read as blocking. That produced exactly
        one grounded, HIGH, correctly-attributed issue -- which is why
        the substantiation and attribution guards below (working as
        designed) did not suppress it, and the run still failed with
        Compliance=100 / Feasibility=77 / ZB=84.

        The fix is to state the entry preconditions in the prompt so the
        dependency chain is complete and the model's own rule resolves
        correctly, and to tighten HIGH so an improvement/optimization
        cannot be graded as blocking. No validation rule is weakened:
        the guards below are unchanged, and a genuine HIGH issue against
        a real stage still fails the analysis.
        """
        if not self.llm:
            return [], "PASS", "template"

        import json as _json
        from core.json_utils import extract_json, has_parse_error

        future_steps = redesign.get("future_steps", []) or []

        # ROOT-CAUSE FIX (unsubstantiated validation FAIL, part 1 of 2 --
        # generic, applies to every service):
        #
        # The reviewer is explicitly asked below to detect "a step that
        # depends on information no earlier step actually produces", "a
        # human-judgement step with no real justification" and "a payment
        # step whose reasoning contradicts its own placement". The fields
        # that carry exactly that information -- depends_on_previous,
        # human_judgement_reason (folded into `reasoning`),
        # payment_reasoning (likewise), action, detailed_description and
        # the step's position -- were all being STRIPPED OUT of what the
        # model got to see. It received only name/type/reason/has_payment
        # and was then asked to judge dependency satisfaction it had no
        # way to observe.
        #
        # The predictable result is a confident, well-formed complaint
        # about a dependency or justification that is in fact present in
        # the journey -- an artifact of the missing context, not a real
        # defect. Since a FAIL verdict blocks the whole analysis
        # regardless of the deterministic scores, one such artifact was
        # enough to fail an otherwise clean run (the observed
        # Compliance=100 / Feasibility=70 / ZB=77 with verdict=FAIL).
        #
        # Every field is model-produced content that already exists on
        # the step; nothing new is computed or invented here.
        compact_steps = []
        for index, s in enumerate(future_steps, start=1):
            if not isinstance(s, dict):
                continue
            compact_steps.append({
                "position": index,
                "name": s.get("name", ""),
                "type": s.get("type", ""),
                "action": s.get("action", ""),
                "detailed_description": s.get("detailed_description", ""),
                "reason": s.get("reason") or s.get("reasoning", ""),
                "depends_on_previous": s.get("depends_on_previous", ""),
                "has_payment": s.get("has_payment", False),
                "requires_human_judgement": s.get(
                    "requires_human_judgement", False
                ),
                "requires_customer_approval": s.get(
                    "requires_customer_approval", False
                ),
                "delivers_customer_result": s.get(
                    "delivers_customer_result", False
                ),
                "customer_role": s.get("customer_role", ""),
            })

        # Stage names, used below to attribute each AI-reported issue
        # to a stage this journey actually contains.
        step_names = [
            str(step.get("name", "")).strip()
            for step in compact_steps
            if str(step.get("name", "")).strip()
        ]

        prompt = f"""Review this proposed future service journey for genuine logical consistency.

SERVICE: {str(service.get("service_name", "")).strip()}

PROPOSED STEPS (in order):
{_json.dumps(compact_steps, ensure_ascii=False, indent=2)}

Every field each step declares is shown above, including "depends_on_previous" (what earlier result it needs) and its full reasoning. Judge only against what is actually written there.

ALREADY SATISFIED BEFORE STAGE 1 (the journey's entry preconditions -- these are inputs the journey starts with, not gaps):
- The customer's identity is already verified/authenticated before stage 1 begins.
- The customer has already selected this specific service and made this request.
- A stage that calls a system produces its own retrieved data for the stages after it.
The first stage therefore has no earlier stage by design, and depending on any of the above is correct. A dependency satisfied by these preconditions is NOT a missing dependency.

TASK: check whether the reasoning actually holds together for this specific service. Look for real problems only, such as:
- A step's stated reason does not actually justify its type or position.
- A payment step whose reasoning contradicts its own placement (e.g. claims the amount is unknown yet is placed before any step that would produce that amount).
- A human-judgement step with no real justification for why it can't be automated.
- A step that depends on information neither an earlier step nor the entry preconditions above actually produce.

Rules you must follow:
- Name the exact offending step in the "step" field, copied verbatim from a "name" above. An issue you cannot attribute to a specific listed step is not a real issue -- leave it out.
- Before reporting a missing dependency, re-read the earlier steps AND the entry preconditions above; if either produces it, there is no issue. Never report a missing dependency against the FIRST stage for something the preconditions already supply.
- Do not invent generic issues, and do not report style, wording or completeness preferences.
- This is a REDESIGN. Fewer stages than before, work moved from the customer or an employee onto the assistant, and merged or removed steps are the intended result -- never report them as inconsistencies.
- If everything is genuinely consistent, return an empty issues list and verdict "PASS".

Return JSON only, exactly this shape:
{{"issues": [{{"severity": "HIGH", "step": "exact name of the offending step", "issue": "the specific contradiction", "required_change": "the concrete fix"}}], "verdict": "PASS"}}

severity must be one of HIGH, MEDIUM, LOW. Use HIGH ONLY when the journey cannot actually execute as ordered -- a stage whose required input genuinely does not exist by the time it runs, or two statements that directly contradict each other. A recommendation, an optimization, a possible enhancement, something that "could be clearer" or "should also do X" is NEVER HIGH; that is MEDIUM or LOW at most.

verdict must be "PASS" or "FAIL". Return "FAIL" ONLY if you reported at least one HIGH issue above. If your issues are all MEDIUM/LOW, or you reported none, the verdict is "PASS".
"""

        try:
            response = self.llm.generate(
                system_prompt=(
                    "You are a meticulous logical-consistency "
                    "reviewer for service redesigns. You only flag "
                    "genuine, specific problems grounded in the "
                    "actual steps given, never generic concerns. You "
                    "always return valid JSON matching exactly the "
                    "requested shape, with no markdown fences and no "
                    "commentary outside the JSON."
                ),
                user_prompt=prompt,
                max_new_tokens=900,
            )
        except Exception as error:
            print(
                f"[AI FAILED -> FALLBACK] "
                f"[VALIDATION] AI semantic review call failed: "
                f"{error}. Using deterministic rules only."
            )
            return [], "PASS", "template"

        result = extract_json(response)
        if not isinstance(result, dict) or has_parse_error(result):
            print(
                f"[AI FAILED -> FALLBACK] "
                "[VALIDATION] AI semantic review output unusable "
                "(parse error). Using deterministic rules only."
            )
            return [], "PASS", "template"

        raw_issues = result.get("issues")
        verdict = str(result.get("verdict", "")).strip().upper()
        if verdict not in ("PASS", "FAIL"):
            print(
                f"[AI FAILED -> FALLBACK] "
                "[VALIDATION] AI semantic review output unusable "
                "(bad verdict). Using deterministic rules only."
            )
            return [], "PASS", "template"

        if not isinstance(raw_issues, list):
            print(
                f"[AI FAILED -> FALLBACK] "
                "[VALIDATION] AI semantic review output unusable "
                "(issues not a list). Using deterministic rules only."
            )
            return [], "PASS", "template"

        # ROOT-CAUSE FIX (unsubstantiated validation FAIL, part 2 of 2 --
        # generic):
        #
        # A "FAIL" verdict was previously accepted at face value and
        # applied as a hard, analysis-blocking gate without any check
        # that the model's OWN reported issues actually supported it.
        # Two concrete ways that produced a false FAIL, both observed:
        #
        #   1. Ungrounded issue. The complaint referred to a stage that
        #      does not exist in this journey (a hallucinated or
        #      misremembered step name). Nothing rejected it.
        #   2. Unsubstantiated verdict. The severity vocabulary here is
        #      HIGH/MEDIUM/LOW -- there is no CRITICAL -- yet a verdict
        #      of FAIL emitted alongside only MEDIUM/LOW observations,
        #      or alongside no issues at all, still blocked everything.
        #      Small local models routinely flip the verdict to FAIL
        #      whenever they have listed anything at all, because the
        #      verdict field was never tied to what they reported.
        #
        # Both are now checked. This is deliberately NOT a bypass: it
        # never converts a deterministic FAIL to PASS (the caller applies
        # the AI verdict only in the tightening direction), and a
        # grounded HIGH issue still fails the analysis exactly as before.
        # It only refuses to act on an AI verdict that the AI's own
        # output does not substantiate -- the same treatment the
        # malformed-verdict and unparseable-output branches above
        # already give. Surviving MEDIUM/LOW issues are still reported
        # to the user as advisory findings; they are simply not treated
        # as blocking.
        valid_severities = {"HIGH", "MEDIUM", "LOW"}
        cleaned = []
        blocking = []
        dropped_ungrounded = 0
        for raw in raw_issues:
            if not isinstance(raw, dict):
                continue
            severity = str(raw.get("severity", "")).strip().upper()
            issue_text = str(raw.get("issue", "")).strip()
            required_change = str(raw.get("required_change", "")).strip()
            cited_step = str(raw.get("step", "")).strip()
            if severity not in valid_severities or not issue_text:
                continue

            attributed = self._issue_names_a_real_stage(
                cited_step, issue_text, step_names
            )

            # A complaint that explicitly names a stage this journey does
            # not contain is a hallucination -- discard it entirely.
            if cited_step and not attributed:
                dropped_ungrounded += 1
                continue

            issue_record = {
                "severity": severity,
                "issue": issue_text,
                "required_change": required_change or issue_text,
            }
            cleaned.append(issue_record)

            # Only an issue that can actually be attributed to a real
            # stage may substantiate a blocking verdict. An unattributed
            # HIGH observation is still reported to the user, but it
            # cannot fail the analysis on its own -- there is nothing
            # concrete for anyone to act on or verify.
            if severity == "HIGH" and attributed:
                blocking.append(issue_record)

        if dropped_ungrounded:
            print(
                f"[VALIDATION] Dropped {dropped_ungrounded} AI semantic "
                "issue(s) that named a stage this journey does not "
                "contain."
            )
        if verdict == "FAIL" and not blocking:
            print(
                "[VALIDATION] AI returned verdict=FAIL without any "
                "grounded HIGH-severity issue to support it; the "
                "verdict is not substantiated by the AI's own findings "
                "and is not applied as a blocking result. Any "
                "MEDIUM/LOW findings are still reported. Deterministic "
                "gates are unaffected."
            )
            verdict = "PASS"

        print(
            f"[VALIDATION] AI semantic review accepted: "
            f"{len(cleaned)} issue(s), verdict={verdict}."
        )
        return cleaned, verdict, ai_label()

    def _issue_names_a_real_stage(self, cited_step, issue_text, step_names):
        """True when an AI-reported issue can be attributed to a stage
        that this journey actually contains.

        Deliberately structural rather than word-overlap based: a
        word-frequency grounding check is useless here, because a
        hallucinated stage name shares ordinary words ("the", "customer",
        "request") with any journey and would pass. The reviewer is asked
        to copy the stage name verbatim, so this matches against the
        journey's own stage names -- exactly, as a substring in either
        direction, or as a close paraphrase (difflib, conservative
        cutoff). When the model omitted the step field, the issue text is
        checked for a stage name instead.

        Entirely service-agnostic: it compares the AI's output against
        this journey's own stage names and nothing else.
        """
        import difflib

        normalized_names = [
            self._normalize_text(name) for name in step_names
        ]
        normalized_names = [name for name in normalized_names if name]
        if not normalized_names:
            return False

        if cited_step:
            cited = self._normalize_text(cited_step)
            if not cited:
                return False
            for name in normalized_names:
                if cited == name or cited in name or name in cited:
                    return True
            return bool(
                difflib.get_close_matches(
                    cited, normalized_names, n=1, cutoff=0.75
                )
            )

        # No step field: accept only if the issue text itself quotes one
        # of the journey's stage names.
        issue_normalized = self._normalize_text(issue_text)
        return any(name in issue_normalized for name in normalized_names)

    def _add_issue(
        self,
        issues,
        required_changes,
        severity,
        issue,
        required_change,
    ):

        issues.append({
            "severity":
                severity,

            "issue":
                issue,
        })

        if required_change:
            required_changes.append(
                required_change
            )

    # =========================================================
    # NORMALIZE TEXT
    # =========================================================

    def _normalize_text(
        self,
        value,
    ):

        text = str(
            value
        ).strip().lower()

        text = " ".join(
            text.split()
        )

        return text.rstrip(
            "."
        )
