import json

from core.json_utils import (
    extract_json,
    has_parse_error,
)

from core.standards_catalog import (
    valid_standard_ids,
)


class RedesignAgent:

    def __init__(self, llm):
        self.llm = llm

    # =========================================================
    # MAIN RUN
    # =========================================================

    def run(
        self,
        service,
        service_analysis,
        standards,
        gaps,
        bureaucracy_findings,
        validation_feedback=None,
        iteration=1,
    ):

        validation_feedback = (
            validation_feedback or {}
        )

        # =====================================================
        # 1. BUILD SAFE DETERMINISTIC BASELINE
        # =====================================================

        baseline = self._build_baseline(
            service=service,
            gaps=gaps,
            standards=standards,
        )

        # =====================================================
        # 2. ASK AI TO IMPROVE BASELINE
        # =====================================================

        prompt = f"""
You are improving a government service redesign.

REDESIGN ITERATION:
{iteration}

CURRENT SERVICE:
{json.dumps(
    service,
    ensure_ascii=False,
    indent=2
)}

CONFIRMED GAPS:
{json.dumps(
    gaps.get(
        "gaps",
        []
    ),
    ensure_ascii=False,
    indent=2
)}

ZERO BUREAUCRACY FINDINGS:
{json.dumps(
    bureaucracy_findings,
    ensure_ascii=False,
    indent=2
)}

APPLICABLE GOVERNMENT STANDARDS:
{json.dumps(
    standards.get(
        "applicable_standards",
        []
    ),
    ensure_ascii=False,
    indent=2
)}

SAFE BASELINE REDESIGN:
{json.dumps(
    baseline,
    ensure_ascii=False,
    indent=2
)}

PREVIOUS VALIDATION REQUIRED CHANGES:
{json.dumps(
    validation_feedback.get(
        "required_changes",
        []
    ),
    ensure_ascii=False,
    indent=2
)}

YOUR OBJECTIVE:

Improve the SAFE BASELINE REDESIGN while preserving
service completeness and government controls.

CRITICAL RULES:

1. Return the COMPLETE future happy-path journey.

2. Reduce unnecessary steps by MERGING related activities
   where this is supported by the confirmed gaps.

3. Do not return one future step for every current step.

4. Never restore confirmed duplicate-data collection.

5. Never keep unnecessary manual email handoffs when a
   controlled digital handoff is proposed.

6. Never keep unnecessary manual system updates when
   automation is supported.

7. Preserve mandatory or uncertain documents and approvals.

8. Do not remove a legal, policy, security or operational
   control unless supplied evidence supports removal.

9. Use ONLY standard IDs supplied in
   APPLICABLE GOVERNMENT STANDARDS.

10. Never invent an existing system integration.

11. When an integration is required, label it as PROPOSED.

12. Every MERGED, REMOVED, AUTOMATED or NEW step must have:
    - reason
    - standard_id

13. Allowed future step type values:
    CUSTOMER
    SYSTEM
    HUMAN

14. Allowed change_type values:
    KEPT
    MERGED
    REMOVED
    AUTOMATED
    NEW

15. The future happy path must end with a clear
    customer-visible result.

16. Exception handling must be placed inside exception_paths.
    Do NOT add exception handling as an ordinary happy-path
    future step unless it is genuinely part of the normal path.

17. If previous validation required changes exist, address them.

Return exactly one valid JSON object:

{{
  "future_steps": [
    {{
      "step_number": 1,
      "name": "",
      "type": "CUSTOMER",
      "action": "",
      "change_type": "KEPT",
      "reason": "",
      "standard_id": ""
    }}
  ],
  "future_documents": [],
  "future_manual_actions": [],
  "future_digital_actions": [],
  "future_approvals": [],
  "future_branch_visits": 0,
  "removed_steps": [],
  "merged_steps": [],
  "required_integrations": [],
  "automation_opportunities": [],
  "exception_paths": [],
  "customer_experience": "",
  "implementation_notes": []
}}

Return valid JSON only.
"""

        response = self.llm.generate(
            system_prompt=(
                "You are a conservative government service "
                "reengineering agent. Improve the supplied "
                "baseline without sacrificing service completeness, "
                "government controls, traceability or feasibility."
            ),
            user_prompt=prompt,
            max_new_tokens=700,
        )

        ai_result = extract_json(
            response
        )

        # =====================================================
        # 3. INVALID AI OUTPUT -> SAFE BASELINE
        # =====================================================

        if has_parse_error(
            ai_result
        ):
            print(
                "[REDESIGN] AI JSON invalid. "
                "Using deterministic baseline."
            )

            return baseline

        if not self._validate_structure(
            ai_result
        ):
            print(
                "[REDESIGN] AI structure invalid. "
                "Using deterministic baseline."
            )

            return baseline

        # =====================================================
        # 4. STANDARD-ID VALIDATION
        # =====================================================

        applicable_ids = {
            item.get(
                "standard_id"
            )
            for item in standards.get(
                "applicable_standards",
                []
            )
        }

        approved_ids = (
            valid_standard_ids()
        )

        for step in ai_result.get(
            "future_steps",
            []
        ):

            if not isinstance(
                step,
                dict
            ):
                print(
                    "[REDESIGN] Invalid future step. "
                    "Using baseline."
                )

                return baseline

            standard_id = (
                step.get(
                    "standard_id",
                    ""
                )
            )

            if standard_id:

                if (
                    standard_id
                    not in approved_ids
                ):
                    print(
                        "[REDESIGN] Unknown standard ID "
                        f"{standard_id}. Using baseline."
                    )

                    return baseline

                if (
                    standard_id
                    not in applicable_ids
                ):
                    print(
                        "[REDESIGN] Standard ID "
                        f"{standard_id} is not applicable "
                        "to this service. Using baseline."
                    )

                    return baseline

        # =====================================================
        # 5. CHECK CRITICAL GAPS
        # =====================================================

        if not self._addresses_critical_gaps(
            service=service,
            redesign=ai_result,
        ):
            print(
                "[REDESIGN] AI redesign did not address "
                "critical gaps. Using deterministic baseline."
            )

            return baseline

        return ai_result

    # =========================================================
    # SAFE DETERMINISTIC BASELINE
    # =========================================================

    def _build_baseline(
        self,
        service,
        gaps,
        standards,
    ):

        original_steps = list(
            service.get(
                "steps",
                []
            )
        )

        applicable_ids = {
            item.get(
                "standard_id"
            )
            for item in standards.get(
                "applicable_standards",
                []
            )
        }

        future_steps = []

        removed_steps = []

        merged_steps = []

        automation_opportunities = []

        required_integrations = []

        step_number = 1

        # =====================================================
        # HELPERS
        # =====================================================

        def add_future_step(
            name,
            step_type,
            action,
            change_type,
            reason,
            standard_id="",
        ):

            nonlocal step_number

            future_steps.append({
                "step_number":
                    step_number,

                "name":
                    name,

                "type":
                    step_type,

                "action":
                    action,

                "change_type":
                    change_type,

                "reason":
                    reason,

                "standard_id":
                    standard_id,
            })

            step_number += 1

        def standard_available(
            standard_id
        ):

            return (
                standard_id
                in applicable_ids
            )

        # =====================================================
        # CLASSIFY CURRENT STEPS
        # =====================================================

        customer_start_steps = []

        duplicate_steps = []

        email_handoffs = []

        manual_updates = []

        human_review_steps = []

        customer_result_steps = []

        other_steps = []

        for step in original_steps:

            text = str(
                step
            ).strip()

            lowered = (
                text.lower()
            )

            # -------------------------------------------------
            # DUPLICATE DATA
            # -------------------------------------------------

            if (
                "again" in lowered
                or "same tracking number"
                in lowered
                or "duplicate" in lowered
                or "re-enter" in lowered
                or "reenter" in lowered
            ):

                duplicate_steps.append(
                    text
                )

                if standard_available(
                    "STD-02"
                ):

                    removed_steps.append({
                        "step":
                            text,

                        "reason": (
                            "Duplicate information should be "
                            "reused instead of entered again."
                        ),

                        "standard_id":
                            "STD-02",
                    })

                continue

            # -------------------------------------------------
            # EMAIL / MANUAL HANDOFF
            # -------------------------------------------------

            if (
                "email" in lowered
                or "emails" in lowered
            ):

                if (
                    "operations" in lowered
                    or "team" in lowered
                    or "department" in lowered
                    or "result" in lowered
                ):

                    email_handoffs.append(
                        text
                    )

                    if standard_available(
                        "STAGE-05"
                    ):

                        removed_steps.append({
                            "step":
                                text,

                            "reason": (
                                "Manual email handoff can be "
                                "replaced by a controlled "
                                "digital workflow."
                            ),

                            "standard_id":
                                "STAGE-05",
                        })

                    continue

            # -------------------------------------------------
            # MANUAL UPDATE / COPY / ENTRY
            # -------------------------------------------------

            if (
                "manual" in lowered
                or "manually" in lowered
            ):

                if (
                    "update" in lowered
                    or "copy" in lowered
                    or "enter" in lowered
                    or "record" in lowered
                ):

                    manual_updates.append(
                        text
                    )

                    if standard_available(
                        "STAGE-05"
                    ):

                        removed_steps.append({
                            "step":
                                text,

                            "reason": (
                                "Manual system updating can be "
                                "automated when the necessary "
                                "data already exists."
                            ),

                            "standard_id":
                                "STAGE-05",
                        })

                    continue

            # -------------------------------------------------
            # CUSTOMER-VISIBLE RESULT
            # -------------------------------------------------

            if (
                "customer" in lowered
                and (
                    "receive" in lowered
                    or "receives" in lowered
                    or "notify" in lowered
                    or "notifies" in lowered
                    or "update to the customer" in lowered
                    or "result" in lowered
                    or "confirmation" in lowered
                    or "outcome" in lowered
                )
            ):

                customer_result_steps.append(
                    text
                )

                continue

            # -------------------------------------------------
            # CUSTOMER START / INPUT
            # -------------------------------------------------

            if (
                "customer" in lowered
                and (
                    "contact" in lowered
                    or "contacts" in lowered
                    or "request" in lowered
                    or "requests" in lowered
                    or "provide" in lowered
                    or "provides" in lowered
                    or "submit" in lowered
                    or "submits" in lowered
                    or "enter" in lowered
                    or "enters" in lowered
                )
            ):

                customer_start_steps.append(
                    text
                )

                continue

            # -------------------------------------------------
            # HUMAN REVIEW / INVESTIGATION
            # -------------------------------------------------

            if (
                "operations" in lowered
                or "investigate" in lowered
                or "investigates" in lowered
                or "review" in lowered
                or "reviews" in lowered
                or "verify" in lowered
                or "verifies" in lowered
            ):

                human_review_steps.append(
                    text
                )

                continue

            # -------------------------------------------------
            # OTHER STEP
            # -------------------------------------------------

            other_steps.append(
                text
            )

        # =====================================================
        # 1. CONSOLIDATE CUSTOMER START
        # =====================================================

        if customer_start_steps:

            if (
                len(
                    customer_start_steps
                ) > 1
                and standard_available(
                    "STD-01"
                )
            ):

                add_future_step(
                    name=(
                        "Customer states the service request"
                    ),

                    step_type=
                        "CUSTOMER",

                    action=(
                        "The customer states the required "
                        "outcome and provides essential "
                        "information once."
                    ),

                    change_type=
                        "MERGED",

                    reason=(
                        "Consolidates service initiation "
                        "and essential customer input into "
                        "one interaction."
                    ),

                    standard_id=
                        "STD-01",
                )

                merged_steps.append({
                    "from":
                        customer_start_steps,

                    "into": (
                        "Customer states the service request"
                    ),

                    "standard_id":
                        "STD-01",
                })

            else:

                first_customer_step = (
                    customer_start_steps[0]
                )

                add_future_step(
                    name=
                        first_customer_step,

                    step_type=
                        "CUSTOMER",

                    action=
                        first_customer_step,

                    change_type=
                        "KEPT",

                    reason=(
                        "Preserved as the required "
                        "customer initiation step."
                    ),

                    standard_id="",
                )

        # =====================================================
        # 2. REUSE SERVICE CONTEXT
        # =====================================================

        if (
            duplicate_steps
            or manual_updates
            or email_handoffs
        ):

            if standard_available(
                "STD-02"
            ):

                add_future_step(
                    name=(
                        "System retrieves and reuses "
                        "service context"
                    ),

                    step_type=
                        "SYSTEM",

                    action=(
                        "The service reuses information "
                        "already provided or available "
                        "in the current case instead of "
                        "requiring repeated manual entry."
                    ),

                    change_type=
                        "AUTOMATED",

                    reason=(
                        "Reduces duplicate information "
                        "entry and administrative burden."
                    ),

                    standard_id=
                        "STD-02",
                )

                automation_opportunities.append({
                    "current_step": (
                        "Repeated data entry and "
                        "manual coordination"
                    ),

                    "proposed_action": (
                        "Reuse existing case context "
                        "across relevant systems."
                    ),

                    "standard_id":
                        "STD-02",
                })

        # =====================================================
        # 3. PRESERVE OTHER NECESSARY ACTIVITIES
        # =====================================================

        for step in other_steps:

            add_future_step(
                name=
                    step,

                step_type=
                    "SYSTEM",

                action=
                    step,

                change_type=
                    "KEPT",

                reason=(
                    "Preserved because there is "
                    "insufficient evidence to "
                    "safely remove this activity."
                ),

                standard_id="",
            )

        # =====================================================
        # 4. CONSOLIDATE HUMAN REVIEW
        # =====================================================

        if human_review_steps:

            if (
                len(
                    human_review_steps
                ) > 1
                and standard_available(
                    "STAGE-06"
                )
            ):

                add_future_step(
                    name=(
                        "Human reviews exception "
                        "when required"
                    ),

                    step_type=
                        "HUMAN",

                    action=(
                        "An authorized human specialist "
                        "reviews the case only when "
                        "automated processing cannot "
                        "safely complete it."
                    ),

                    change_type=
                        "MERGED",

                    reason=(
                        "Consolidates human investigation "
                        "into one controlled exception step."
                    ),

                    standard_id=
                        "STAGE-06",
                )

                merged_steps.append({
                    "from":
                        human_review_steps,

                    "into": (
                        "Human reviews exception "
                        "when required"
                    ),

                    "standard_id":
                        "STAGE-06",
                })

            else:

                first_review = (
                    human_review_steps[0]
                )

                add_future_step(
                    name=
                        first_review,

                    step_type=
                        "HUMAN",

                    action=
                        first_review,

                    change_type=
                        "KEPT",

                    reason=(
                        "Human review is preserved "
                        "where evidence does not "
                        "support its removal."
                    ),

                    standard_id="",
                )

        # =====================================================
        # 5. AUTOMATE MANUAL HANDOFF / UPDATES
        # =====================================================

        if (
            email_handoffs
            or manual_updates
        ):

            if standard_available(
                "STAGE-05"
            ):

                add_future_step(
                    name=(
                        "System coordinates the case "
                        "automatically"
                    ),

                    step_type=
                        "SYSTEM",

                    action=(
                        "The service routes the case "
                        "and synchronizes results without "
                        "unnecessary email handoffs or "
                        "manual copying."
                    ),

                    change_type=
                        "AUTOMATED",

                    reason=(
                        "Reduces manual handoffs and "
                        "improves service continuity."
                    ),

                    standard_id=
                        "STAGE-05",
                )

                automation_opportunities.append({
                    "current_step": (
                        "Manual handoffs and "
                        "manual system updates"
                    ),

                    "proposed_action": (
                        "Use a proposed system-managed "
                        "workflow for routing and "
                        "synchronization."
                    ),

                    "standard_id":
                        "STAGE-05",
                })

                required_integrations.append(
                    "PROPOSED: Relevant service systems "
                    "workflow integration"
                )

        # =====================================================
        # 6. CUSTOMER-VISIBLE RESULT
        # =====================================================

        if standard_available(
            "STD-05"
        ):

            add_future_step(
                name=(
                    "Customer receives the service outcome"
                ),

                step_type=
                    "SYSTEM",

                action=(
                    "The customer receives the final "
                    "result, status or confirmation "
                    "when processing is complete."
                ),

                change_type=
                    "AUTOMATED",

                reason=(
                    "Ensures the redesigned journey "
                    "ends with a clear customer-visible "
                    "result without unnecessary "
                    "manual follow-up."
                ),

                standard_id=
                    "STD-05",
            )

        elif customer_result_steps:

            result_step = (
                customer_result_steps[0]
            )

            add_future_step(
                name=
                    result_step,

                step_type=
                    "HUMAN",

                action=
                    result_step,

                change_type=
                    "KEPT",

                reason=(
                    "Preserved to ensure a clear "
                    "customer-visible result."
                ),

                standard_id="",
            )

        else:

            add_future_step(
                name=(
                    "Customer receives the service outcome"
                ),

                step_type=
                    "HUMAN",

                action=(
                    "The customer receives the final "
                    "service result or confirmation."
                ),

                change_type=
                    "KEPT",

                reason=(
                    "A complete journey must end "
                    "with a customer-visible outcome."
                ),

                standard_id="",
            )

        # =====================================================
        # 7. EXCEPTION PATH
        # =====================================================

        exception_paths = []

        if (
            standard_available(
                "STAGE-06"
            )
            or standard_available(
                "STD-06"
            )
        ):

            exception_standard = (
                "STAGE-06"
                if standard_available(
                    "STAGE-06"
                )
                else "STD-06"
            )

            exception_paths.append({
                "name":
                    "Human handoff",

                "trigger": (
                    "The automated journey cannot "
                    "safely complete the service."
                ),

                "action": (
                    "Transfer the case to an authorized "
                    "human employee with the existing "
                    "service context and history."
                ),

                "standard_id":
                    exception_standard,
            })

        # =====================================================
        # FUTURE MANUAL / DIGITAL ACTIONS
        # =====================================================

        future_manual_actions = [
            step.get(
                "name",
                ""
            )
            for step in future_steps
            if step.get(
                "type"
            ) == "HUMAN"
        ]

        future_digital_actions = [
            step.get(
                "name",
                ""
            )
            for step in future_steps
            if step.get(
                "type"
            ) == "SYSTEM"
        ]

        required_integrations = list(
            dict.fromkeys(
                required_integrations
            )
        )

        # =====================================================
        # RETURN BASELINE
        # =====================================================

        return {
            "future_steps":
                future_steps,

            "future_documents":
                list(
                    service.get(
                        "documents",
                        []
                    )
                ),

            "future_manual_actions":
                future_manual_actions,

            "future_digital_actions":
                future_digital_actions,

            "future_approvals":
                list(
                    service.get(
                        "approvals",
                        []
                    )
                ),

            "future_branch_visits":
                service.get(
                    "branch_visits",
                    0
                ),

            "removed_steps":
                removed_steps,

            "merged_steps":
                merged_steps,

            "required_integrations":
                required_integrations,

            "automation_opportunities":
                automation_opportunities,

            "exception_paths":
                exception_paths,

            "customer_experience": (
                "The customer states the required "
                "outcome once. The service reuses "
                "available context, coordinates "
                "processing behind the scenes and "
                "returns a clear result. Human "
                "support remains available for "
                "exception cases."
            ),

            "implementation_notes": [
                (
                    "All proposed integrations require "
                    "technical, security, legal and "
                    "policy validation."
                ),
                (
                    "No existing integration is assumed "
                    "unless supported by supplied evidence."
                ),
                (
                    "Mandatory controls remain unless "
                    "evidence supports their removal."
                ),
            ],
        }

    # =========================================================
    # STRUCTURE VALIDATION
    # =========================================================

    def _validate_structure(
        self,
        result,
    ):

        if not isinstance(
            result,
            dict
        ):
            return False

        steps = result.get(
            "future_steps"
        )

        if not isinstance(
            steps,
            list
        ):
            return False

        if len(
            steps
        ) < 2:
            return False

        allowed_types = {
            "CUSTOMER",
            "SYSTEM",
            "HUMAN",
        }

        allowed_changes = {
            "KEPT",
            "MERGED",
            "REMOVED",
            "AUTOMATED",
            "NEW",
        }

        for index, step in enumerate(
            steps,
            start=1,
        ):

            if not isinstance(
                step,
                dict
            ):
                return False

            step.setdefault(
                "step_number",
                index,
            )

            if not step.get(
                "name"
            ):
                return False

            if (
                step.get(
                    "type"
                )
                not in allowed_types
            ):
                return False

            if (
                step.get(
                    "change_type"
                )
                not in allowed_changes
            ):
                return False

            if (
                step.get(
                    "change_type"
                )
                in {
                    "MERGED",
                    "REMOVED",
                    "AUTOMATED",
                    "NEW",
                }
            ):

                if not step.get(
                    "reason"
                ):
                    return False

                if not step.get(
                    "standard_id"
                ):
                    return False

        exception_paths = result.get(
            "exception_paths",
            []
        )

        if not isinstance(
            exception_paths,
            list
        ):
            return False

        for exception in (
            exception_paths
        ):

            if not isinstance(
                exception,
                dict
            ):
                return False

        return True

    # =========================================================
    # CRITICAL GAP VALIDATION
    # =========================================================

    def _addresses_critical_gaps(
        self,
        service,
        redesign,
    ):

        future_steps = redesign.get(
            "future_steps",
            []
        )

        if not isinstance(
            future_steps,
            list
        ):
            return False

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

        # -----------------------------------------------------
        # DUPLICATE DATA MUST NOT REMAIN
        # -----------------------------------------------------

        duplicate_patterns = [
            "same tracking number again",
            "enter the same",
            "re-enter",
            "reenter",
            "duplicate entry",
        ]

        if any(
            pattern in future_text
            for pattern in duplicate_patterns
        ):
            return False

        # -----------------------------------------------------
        # MANUAL CRM UPDATE MUST NOT REMAIN UNCHANGED
        # -----------------------------------------------------

        if (
            "manually updates the crm"
            in future_text
        ):
            return False

        if (
            "manual crm update"
            in future_text
        ):
            return False

        # -----------------------------------------------------
        # MANUAL EMAIL HANDOFF MUST NOT REMAIN
        # -----------------------------------------------------

        manual_email_patterns = [
            "emails operations",
            "email operations",
            "send email to operations",
            "sends email to operations",
        ]

        if any(
            pattern in future_text
            for pattern in manual_email_patterns
        ):
            return False

        # -----------------------------------------------------
        # CUSTOMER-VISIBLE RESULT MUST EXIST
        # -----------------------------------------------------

        result_signals = [
            "customer receives",
            "customer outcome",
            "customer result",
            "service outcome",
            "final result",
            "confirmation",
            "shipment outcome",
            "shipment status",
        ]

        if not any(
            signal in future_text
            for signal in result_signals
        ):
            return False

        # -----------------------------------------------------
        # EXCEPTION / HUMAN HANDOFF MUST EXIST
        # -----------------------------------------------------

        exception_paths = redesign.get(
            "exception_paths",
            []
        )

        has_exception_path = (
            isinstance(
                exception_paths,
                list
            )
            and len(
                exception_paths
            ) > 0
        )

        handoff_signals = [
            "handoff",
            "exception",
            "human",
        ]

        has_handoff_in_steps = any(
            signal in future_text
            for signal in handoff_signals
        )

        if not (
            has_exception_path
            or has_handoff_in_steps
        ):
            return False

        return True