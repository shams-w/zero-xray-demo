def clamp(
    value
):
    try:
        value = float(
            value
            if value is not None
            else 0
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0

    return max(
        0,
        min(
            100,
            value
        )
    )


def calculate_zero_bureaucracy_score(
    metrics
):
    """
    Zero Bureaucracy score based on actual burden reduction,
    not raw step count alone.

    N/A dimensions are excluded from the denominator.
    """

    if not metrics.get(
        "valid_for_scoring",
        False
    ):
        return 0

    current = (
        metrics.get(
            "current",
            {}
        )
    )

    reduction = (
        metrics.get(
            "reduction",
            {}
        )
    )

    transformation = (
        metrics.get(
            "transformation",
            {}
        )
    )

    dimensions = []

    # =========================================================
    # 0. CUSTOMER ADMINISTRATIVE BURDEN
    # =========================================================

    if (
        current.get(
            "customer_burden_steps",
            0
        ) > 0
        or metrics.get(
            "future",
            {}
        ).get(
            "customer_burden_steps",
            0
        ) > 0
    ):

        dimensions.append({
            "name":
                "customer_effort_reduction",

            "value":
                clamp(
                    transformation.get(
                        "customer_effort_reduction_percent",
                        0
                    )
                ),

            "weight":
                0.30,
        })

    # =========================================================
    # 1. STEP REDUCTION
    # =========================================================

    if current.get(
        "steps",
        0
    ) > 0:

        dimensions.append({
            "name":
                "step_reduction",

            "value":
                clamp(
                    reduction.get(
                        "steps_percent",
                        0
                    )
                ),

            "weight":
                0.15,
        })

    # =========================================================
    # 2. MANUAL WORK REDUCTION
    # =========================================================

    required_human_decision = bool(
        metrics.get("constraints", {}).get("required_human_decision")
    )

    if current.get(
        "manual_actions",
        0
    ) > 0 and not required_human_decision:

        dimensions.append({
            "name":
                "manual_reduction",

            "value":
                clamp(
                    reduction.get(
                        "manual_actions_percent",
                        0
                    )
                ),

            "weight":
                0.25,
        })

    # =========================================================
    # 3. DOCUMENT REDUCTION
    # =========================================================

    document_reduction = reduction.get("documents_percent")
    if current.get(
        "documents",
        0
    ) > 0 and document_reduction not in {None, 0}:

        dimensions.append({
            "name":
                "document_reduction",

            "value":
                clamp(
                    document_reduction
                ),

            "weight":
                0.10,
        })

    # =========================================================
    # 4. BRANCH VISIT REDUCTION
    # =========================================================

    if current.get(
        "branch_visits",
        0
    ) > 0:

        dimensions.append({
            "name":
                "branch_reduction",

            "value":
                clamp(
                    reduction.get(
                        "branch_visits_percent",
                        0
                    )
                ),

            "weight":
                0.10,
        })

    # =========================================================
    # 5. DUPLICATE DATA ELIMINATION
    # =========================================================

    duplicate = (
        transformation.get(
            "duplicate_elimination_percent"
        )
    )

    if duplicate is not None:

        dimensions.append({
            "name":
                "duplicate_elimination",

            "value":
                clamp(
                    duplicate
                ),

            "weight":
                0.15,
        })

    # =========================================================
    # 6. HANDOFF REDUCTION
    # =========================================================

    handoff = (
        transformation.get(
            "handoff_reduction_percent"
        )
    )

    if handoff is not None:

        dimensions.append({
            "name":
                "handoff_reduction",

            "value":
                clamp(
                    handoff
                ),

            "weight":
                0.15,
        })

    # =========================================================
    # 7. WAITING REDUCTION
    # =========================================================

    waiting = (
        transformation.get(
            "waiting_reduction_percent"
        )
    )

    if waiting is not None:

        dimensions.append({
            "name":
                "waiting_reduction",

            "value":
                clamp(
                    waiting
                ),

            "weight":
                0.10,
        })

    # =========================================================
    # 8. AUTOMATION RATE
    # =========================================================

    dimensions.append({
        "name":
            "automation_rate",

        "value":
            clamp(
                transformation.get(
                    "automation_rate_percent",
                    0
                )
            ),

        "weight":
            0.10,
    })

    # =========================================================
    # NORMALIZED WEIGHTED SCORE
    # =========================================================

    if not dimensions:
        return 0

    total_weight = sum(
        dimension[
            "weight"
        ]
        for dimension
        in dimensions
    )

    if total_weight <= 0:
        return 0

    weighted_sum = sum(
        dimension[
            "value"
        ]
        * dimension[
            "weight"
        ]
        for dimension
        in dimensions
    )

    score = (
        weighted_sum
        / total_weight
    )

    return round(
        max(
            0,
            min(
                100,
                score
            )
        )
    )
