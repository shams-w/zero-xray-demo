def safe_reduction(
    current,
    future,
):
    """
    Percentage reduction between current and future values.

    Returns 0 when the current value is zero because
    there is no existing burden to reduce.
    """

    try:
        current = int(current or 0)
        future = int(future or 0)

    except (TypeError, ValueError):
        return 0

    if current <= 0:
        return 0

    reduction = (
        (current - future)
        / current
    ) * 100

    return max(
        0,
        min(
            100,
            round(reduction)
        )
    )


def _count_matching_steps(service, signals):
    return sum(
        1
        for step in service.get("steps", [])
        if any(
            signal in str(step).lower()
            for signal in signals
        )
    )


def count_current_customer_burden_steps(service):
    """Count administrative customer work, not outcome/consent touchpoints."""
    actors = [
        "customer", "applicant", "client", "user", "العميل",
        "المتعامل", "المستخدم", "مقدم الطلب",
    ]
    non_burden = [
        "requests", "asks for", "approves", "consent", "receives",
        "العميل يطلب", "المتعامل يطلب", "العميل يوافق", "المتعامل يوافق",
        "يؤكد", "تأكيد الطلب", "يستلم", "يتسلم", "استلام رسالة تأكيد",
        "استلام النتيجة", "استلام الرخصة", "استلام رقم التتبع",
    ]
    burden = [
        "upload", "attach", "fill", "form", "enter", "re-enter", "visit",
        "branch", "service center", "search", "follow up", "call", "email",
        "provide", "submit", "pay", "payment", "يرفع", "يرفق", "يعبئ",
        "يملا", "يدخل", "يعيد", "يروح", "يذهب", "يزور", "الفرع",
        "مركز الخدمة", "مركز الخدمه", "يبحث", "يتابع", "يتصل", "يرسل",
        "يقدم", "يسدد", "يدفع", "رسوم", "تسجيل الدخول", "إنشاء حساب",
        "انشاء حساب", "تعبئة", "إدخال", "ادخال", "إرفاق", "ارفاق",
        "رفع", "زيارة", "مراجعة الطلب", "الحصول على موافقة",
    ]
    count = 0
    for step in service.get("steps", []):
        text = str(step).lower()
        has_actor = any(actor in text for actor in actors)
        if any(signal in text for signal in non_burden):
            continue
        is_package_choice = (
            any(signal in text for signal in [
                "package", "bundle", "tier", "باقة", "باقه",
                "الحزمة", "الحزمه",
            ])
            and any(signal in text for signal in [
                "choose", "select", "يختار", "يحدد",
            ])
        )
        if is_package_choice:
            continue
        is_payment_control = any(signal in text for signal in [
            "payment", "pay ", "pays", "fee", "يدفع", "يسدد",
            "دفع", "سداد", "رسوم",
        ])
        has_payment_admin_work = any(signal in text for signal in [
            "visit", "branch", "service center", "goes to", "يروح",
            "يذهب", "يزور", "الفرع", "مركز الخدمة", "مركز الخدمه",
            "fill", "upload", "attach", "enter", "يعبئ", "يرفع",
            "يرفق", "يدخل",
        ])
        if is_payment_control and not has_payment_admin_work:
            continue
        if any(signal in text for signal in burden):
            count += 1
            continue
        # Imperative public-service procedures often omit the actor entirely
        # (for example: "تسجيل الدخول" or "إرفاق الوثائق"). Only count an
        # otherwise unknown step when the customer/applicant is explicit.
        if has_actor:
            count += 1
    return count


def count_future_customer_burden_steps(redesign):
    explicit = redesign.get("future_customer_burden_steps")
    if explicit is not None:
        try:
            return max(0, int(explicit))
        except (TypeError, ValueError):
            pass

    return sum(
        1
        for step in redesign.get("future_steps", [])
        if isinstance(step, dict)
        and (
            step.get("customer_burden") is True
            or (
                "customer_burden" not in step
                and str(step.get("type", "")).upper() == "CUSTOMER"
            )
        )
    )


def count_future_step_types(
    redesign,
):
    """
    Count CUSTOMER, SYSTEM and HUMAN steps
    in the redesigned future journey.
    """

    counts = {
        "CUSTOMER": 0,
        "SYSTEM": 0,
        "HUMAN": 0,
    }

    for step in redesign.get(
        "future_steps",
        []
    ):

        if not isinstance(
            step,
            dict
        ):
            continue

        step_type = str(
            step.get(
                "type",
                ""
            )
        ).upper()

        if step_type in counts:
            counts[step_type] += 1

    return counts


def count_change_types(
    redesign,
):
    """
    Count how the redesigned journey changed.
    """

    counts = {
        "KEPT": 0,
        "MERGED": 0,
        "REMOVED": 0,
        "AUTOMATED": 0,
        "NEW": 0,
        # ROOT-CAUSE FIX: the AI-designed journey path tags every
        # stage "AI_DESIGNED" -- without a bucket for it here, every
        # AI-authored stage silently vanished from change_summary
        # (the `if change_type in counts` guard below just skipped
        # it), making the change-summary report look empty/misleading
        # for the exact journeys that matter most.
        "AI_DESIGNED": 0,
    }

    for step in redesign.get(
        "future_steps",
        []
    ):

        if not isinstance(
            step,
            dict
        ):
            continue

        change_type = str(
            step.get(
                "change_type",
                ""
            )
        ).upper()

        if change_type in counts:
            counts[change_type] += 1

    # Removed steps may exist outside future_steps
    counts["REMOVED"] += len(
        redesign.get(
            "removed_steps",
            []
        )
    )

    counts["MERGED"] += len(
        redesign.get(
            "merged_steps",
            []
        )
    )

    return counts


def calculate_duplicate_elimination(
    service,
    redesign,
):
    """
    Estimate whether duplicate information-entry steps
    were removed from the future journey.
    """

    duplicate_signals = [
        "again",
        "same",
        "duplicate",
        "repeat",
        "re-enter",
        "reenter",
        "مرة اخرى",
        "مرة أخرى",
        "تاني",
        "نفس البيانات",
        "نفس الرقم",
        "اعادة ادخال",
        "إعادة إدخال",
    ]

    current_duplicate_steps = []

    for step in service.get(
        "steps",
        []
    ):

        lowered = str(
            step
        ).lower()

        if any(
            signal in lowered
            for signal in duplicate_signals
        ):
            current_duplicate_steps.append(
                step
            )

    if not current_duplicate_steps:
        return None

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
            for step in redesign.get(
                "future_steps",
                []
            )
            if isinstance(
                step,
                dict
            )
        ]
    ).lower()

    remaining = 0

    for original_step in (
        current_duplicate_steps
    ):

        lowered = str(
            original_step
        ).lower()

        duplicate_keywords_found = any(
            signal in lowered
            and signal in future_text
            for signal in duplicate_signals
        )

        if duplicate_keywords_found:
            remaining += 1

    return safe_reduction(
        len(
            current_duplicate_steps
        ),
        remaining,
    )


def calculate_handoff_reduction(
    service,
    redesign,
):
    """
    Measures reduction of manual transfer/handoff signals
    such as emails and manual copying.
    """

    handoff_signals = [
        "email",
        "emails",
        "send",
        "sends",
        "copy",
        "copies",
        "manually",
        "manual",
        "handoff",
        "ايميل",
        "إيميل",
        "بريد إلكتروني",
        "بريد الكتروني",
        "يدويا",
        "يدويًا",
        "ينسخ",
        "يرسل",
    ]

    current_handoffs = 0

    for step in service.get(
        "steps",
        []
    ):

        lowered = str(
            step
        ).lower()

        if any(
            signal in lowered
            for signal in handoff_signals
        ):
            current_handoffs += 1

    if current_handoffs <= 0:
        return None

    future_manual_handoffs = 0

    for step in redesign.get(
        "future_steps",
        []
    ):

        if not isinstance(
            step,
            dict
        ):
            continue

        step_type = str(
            step.get(
                "type",
                ""
            )
        ).upper()

        name_action = (
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
        ).lower()

        # Count only handoffs that remain manual/human
        if (
            step_type == "HUMAN"
            and any(
                signal in name_action
                for signal in handoff_signals
            )
        ):
            future_manual_handoffs += 1

    return safe_reduction(
        current_handoffs,
        future_manual_handoffs,
    )


def calculate_waiting_reduction(
    service,
    redesign,
):
    """
    Uses current waiting points and redesigned bottlenecks
    when available.
    """

    current_waiting = len(
        service.get("waiting_times", [])
    )

    if current_waiting <= 0:
        current_waiting = _count_matching_steps(
            service,
            [
                "wait", "waiting", "pending", "ينتظر", "انتظار",
                "قيد الانتظار", "معلق", "معلّق",
            ],
        )

    if current_waiting <= 0:
        return None

    # If redesign explicitly has waiting points,
    # use them. Otherwise assume no confirmed reduction.
    future_waiting = len(
        redesign.get(
            "future_waiting_times",
            []
        )
    )

    return safe_reduction(
        current_waiting,
        future_waiting,
    )


def calculate_automation_rate(
    redesign,
):
    """
    Percentage of future operational steps executed
    by SYSTEM rather than HUMAN.
    """

    counts = count_future_step_types(
        redesign
    )

    system_steps = counts[
        "SYSTEM"
    ]

    human_steps = counts[
        "HUMAN"
    ]

    operational_steps = (
        system_steps
        + human_steps
    )

    if operational_steps <= 0:
        return 0

    rate = (
        system_steps
        / operational_steps
    ) * 100

    return max(
        0,
        min(
            100,
            round(rate)
        )
    )


def validate_redesign_for_metrics(
    service,
    redesign,
):
    """
    Protect metrics from incomplete or suspicious redesigns.
    """

    errors = []
    warnings = []

    current_steps = (
        service.get(
            "steps",
            []
        )
    )

    future_steps = (
        redesign.get(
            "future_steps",
            []
        )
    )

    if (
        current_steps
        and not future_steps
    ):
        errors.append(
            "Future journey is empty."
        )

    if not isinstance(
        future_steps,
        list
    ):
        errors.append(
            "future_steps must be a list."
        )

    if isinstance(
        future_steps,
        list
    ):

        for step in future_steps:

            if not isinstance(
                step,
                dict
            ):

                errors.append(
                    "Every future step must "
                    "be a structured object."
                )

                break

            if not step.get(
                "name"
            ):

                errors.append(
                    "Every future step must "
                    "have a name."
                )

                break

    current_count = len(
        current_steps
    )

    future_count = (
        len(
            future_steps
        )
        if isinstance(
            future_steps,
            list
        )
        else 0
    )

    if current_count >= 5:

        reduction = (
            safe_reduction(
                current_count,
                future_count,
            )
        )

        explained_changes = (
            len(
                redesign.get(
                    "removed_steps",
                    []
                )
            )
            +
            len(
                redesign.get(
                    "merged_steps",
                    []
                )
            )
        )

        if (
            reduction > 70
            and explained_changes == 0
        ):

            errors.append(
                "Extreme step reduction is "
                "not supported by documented "
                "removed or merged steps."
            )

    return {
        "valid":
            len(
                errors
            ) == 0,

        "errors":
            errors,

        "warnings":
            warnings,
    }


def calculate_metrics(
    service,
    redesign,
):
    """
    Calculate raw service transformation metrics.

    Important:
    This does not calculate the final Zero Bureaucracy
    score. scoring.py uses these metrics afterwards.
    """

    validation = (
        validate_redesign_for_metrics(
            service,
            redesign,
        )
    )

    current_steps = len(
        service.get(
            "steps",
            []
        )
    )

    future_steps = len(
        redesign.get(
            "future_steps",
            []
        )
    )

    current_documents = len(
        service.get(
            "documents",
            []
        )
    )

    if current_documents <= 0:
        current_documents = _count_matching_steps(
            service,
            [
                "document", "upload", "attachment", "certificate", "copy of",
                "مستند", "وثيقة", "وثيقه", "يرفع", "يرفق", "صورة من",
            ],
        )

    future_documents = len(
        redesign.get(
            "future_documents",
            []
        )
    )

    current_manual = len(
        service.get(
            "manual_actions",
            []
        )
    )

    if current_manual <= 0:
        current_manual = _count_matching_steps(
            service,
            [
                "employee", "agent", "staff", "supervisor", "manually", "manual",
                "الموظف", "المشرف", "المدير", "يدويا", "يدويًا",
            ],
        )

    future_manual = len(
        redesign.get(
            "future_manual_actions",
            []
        )
    )

    current_visits = (
        service.get(
            "branch_visits",
            0
        )
    )

    if current_visits <= 0:
        current_visits = _count_matching_steps(
            service,
            [
                "branch", "service center", "physical visit", "الفرع",
                "مركز الخدمة", "مركز الخدمه", "الحضور شخصيا", "الحضور شخصيًا",
            ],
        )

    future_visits = (
        redesign.get(
            "future_branch_visits",
            current_visits
        )
    )

    future_types = (
        count_future_step_types(
            redesign
        )
    )

    change_types = (
        count_change_types(
            redesign
        )
    )

    duplicate_elimination = (
        calculate_duplicate_elimination(
            service,
            redesign,
        )
    )

    handoff_reduction = (
        calculate_handoff_reduction(
            service,
            redesign,
        )
    )

    waiting_reduction = (
        calculate_waiting_reduction(
            service,
            redesign,
        )
    )

    automation_rate = (
        calculate_automation_rate(
            redesign
        )
    )

    current_customer_burden = (
        count_current_customer_burden_steps(service)
    )

    future_customer_burden = (
        count_future_customer_burden_steps(redesign)
    )

    result = {
        "valid_for_scoring":
            validation[
                "valid"
            ],

        "validation_errors":
            validation[
                "errors"
            ],

        "validation_warnings":
            validation[
                "warnings"
            ],

        "constraints": {
            "required_human_decision": bool(
                redesign.get("service_classification", {}).get(
                    "requires_human_decision",
                    redesign.get("design_profile", {}).get(
                        "requires_human_decision",
                        False,
                    ),
                )
            ),
            "note": (
                "Required documentary evidence and legally necessary human judgement are preserved, not scored as removable bureaucracy."
            ),
        },

        "current": {
            "steps":
                current_steps,

            "documents":
                current_documents,

            "manual_actions":
                current_manual,

            "branch_visits":
                current_visits,

            "customer_burden_steps":
                current_customer_burden,
        },

        "future": {
            "steps":
                future_steps,

            "documents":
                future_documents,

            "manual_actions":
                future_manual,

            "branch_visits":
                future_visits,

            "customer_steps":
                future_types[
                    "CUSTOMER"
                ],

            "system_steps":
                future_types[
                    "SYSTEM"
                ],

            "human_steps":
                future_types[
                    "HUMAN"
                ],

            "customer_burden_steps":
                future_customer_burden,

            "customer_control_points":
                len(
                    redesign.get(
                        "customer_only_actions",
                        []
                    )
                ),
        },

        "change_summary":
            change_types,

        "transformation": {
            "automation_rate_percent":
                automation_rate,

            "duplicate_elimination_percent":
                duplicate_elimination,

            "handoff_reduction_percent":
                handoff_reduction,

            "waiting_reduction_percent":
                waiting_reduction,

            "customer_effort_reduction_percent":
                (
                    safe_reduction(
                        current_customer_burden,
                        future_customer_burden,
                    )
                    if current_customer_burden > 0
                    else None
                ),
        },
    }

    if not validation[
        "valid"
    ]:

        result[
            "reduction"
        ] = {
            "steps_percent":
                None,

            "documents_percent":
                None,

            "manual_actions_percent":
                None,

            "branch_visits_percent":
                None,

            "customer_burden_percent":
                None,
        }

        return result

    result[
        "reduction"
    ] = {
        "steps_percent":
            safe_reduction(
                current_steps,
                future_steps,
            ),

        "documents_percent":
            safe_reduction(
                current_documents,
                future_documents,
            ),

        "manual_actions_percent":
            safe_reduction(
                current_manual,
                future_manual,
            ),

        "branch_visits_percent":
            safe_reduction(
                current_visits,
                future_visits,
            ),

        "customer_burden_percent":
            (
                safe_reduction(
                    current_customer_burden,
                    future_customer_burden,
                )
                if current_customer_burden > 0
                else None
            ),
    }

    return result


# ================================================================
# MERGED FROM P1 (core/rules.py): future-stage customer-burden
# detection by TEXT, not by a hardcoded flag.
# ------------------------------------------------------------------
# Root-cause fix for a real scoring bug: future (AI-designed and
# template) journey stages used to hardcode customer_burden=False
# regardless of what the stage's own customer_role text actually
# said, so any genuine remaining customer administrative work in the
# redesigned journey was invisible to customer_effort_reduction_percent
# (and, through it, to the Zero Bureaucracy score). These helpers let
# a caller (journey_builder_agent) classify a single future stage's
# customer_role text with the same generic burden vocabulary used for
# the CURRENT journey, instead of assuming the future side is zero.
#
# NOTE: adding these functions here is step 1 of the merge (safe,
# self-contained, non-breaking). Wiring them into every
# customer_burden assignment site inside journey_builder_agent.py
# (the ~2500-line file where the hardcoded False values actually
# live) is tracked separately and not yet done in this pass.
# ================================================================
import re as _re_burden

_ROLE_BURDEN_NON_BURDEN_SIGNALS = [
    "requests", "asks for", "approves", "consent", "receives",
    "العميل يطلب", "المتعامل يطلب", "العميل يوافق", "المتعامل يوافق",
    "يؤكد", "تأكيد الطلب", "يستلم", "يتسلم",
]
_ROLE_BURDEN_SIGNALS = [
    "upload", "attach", "fill", "form", "enter", "re-enter", "visit",
    "branch", "service center", "search", "follow up", "call", "email",
    "provide", "submit", "pay", "payment", "يرفع", "يرفق", "يعبئ",
    "يملا", "يدخل", "يعيد", "يروح", "يذهب", "يزور", "الفرع",
    "مركز الخدمة", "مركز الخدمه", "يبحث", "يتابع", "يتصل", "يرسل",
    "يقدم", "يسدد", "يدفع", "رسوم",
    "in person", "travel", "attend in person", "physically present",
    "شخصيًا", "شخصيا", "حضور شخصي", "يسافر",
]
_ROLE_PAYMENT_CONTROL_SIGNALS = [
    "payment", "pay ", "pays", "fee", "يدفع", "يسدد", "دفع", "سداد", "رسوم",
]
_ROLE_PAYMENT_ADMIN_WORK_SIGNALS = [
    "visit", "branch", "service center", "goes to", "يروح",
    "يذهب", "يزور", "الفرع", "مركز الخدمة", "مركز الخدمه",
    "fill", "upload", "attach", "enter", "يعبئ", "يرفع", "يرفق", "يدخل",
]
_ROLE_NEGATION_MARKERS = [
    "no ", "not ", "none", "without", "never", "n't", "eliminat",
    "no longer", "cannot", "isn't", "doesn't", "don't", "won't",
    "لا ", "لا يوجد", "ليس", "بدون", "دون", "لن ", "غير", "لا يحتاج",
    "لا داعي", "لا يلزم",
]


def _clause_has_negation(clause):
    return any(marker in clause for marker in _ROLE_NEGATION_MARKERS)


def _role_text_has_signal(text, signals):
    """Whether any of `signals` appears in `text` as a live
    (non-negated) administrative action. Text is split into clauses
    on sentence/comma boundaries so a negation earlier in a longer
    sentence does not blind the check to genuine burden mentioned
    later in the same sentence (and vice versa)."""
    for clause in _re_burden.split(r"[.!؟؛,،]", text):
        if _clause_has_negation(clause):
            continue
        padded_clause = clause + " "
        if any(signal in padded_clause for signal in signals):
            return True
    return False


def step_customer_role_is_burden(customer_role):
    """
    Whether a SINGLE future stage's own ``customer_role`` text (what
    the customer actually does in that stage, as produced by either
    the AI-designed journey or a template) still describes genuine
    administrative work -- using the same generic burden vocabulary
    count_current_customer_burden_steps applies to the CURRENT
    journey, so both sides of a before/after comparison are judged by
    the same rule instead of the future side being assumed to be zero
    regardless of what it actually says.

    An unmatched customer_role defaults to "no burden": this is a
    short, structured field written specifically to describe one
    stage's customer work, so silence about administrative effort
    means there genuinely is none.
    """
    text = str(customer_role or "").strip().lower()
    if not text:
        return False

    if any(signal in text for signal in _ROLE_BURDEN_NON_BURDEN_SIGNALS):
        return False

    is_package_choice = (
        any(signal in text for signal in [
            "package", "bundle", "tier", "باقة", "باقه",
            "الحزمة", "الحزمه",
        ])
        and any(signal in text for signal in [
            "choose", "select", "يختار", "يحدد",
        ])
    )
    if is_package_choice:
        return False

    is_payment_control = _role_text_has_signal(
        text, _ROLE_PAYMENT_CONTROL_SIGNALS
    )
    has_payment_admin_work = _role_text_has_signal(
        text, _ROLE_PAYMENT_ADMIN_WORK_SIGNALS
    )
    if is_payment_control and not has_payment_admin_work:
        return False

    return _role_text_has_signal(text, _ROLE_BURDEN_SIGNALS)
