class SimulationAgent:

    def __init__(self, llm):
        self.llm = llm

    def run(
        self,
        service,
        redesign,
    ):

        current_journey = list(
            service.get(
                "steps",
                []
            )
        )

        future_journey = []

        for step in redesign.get(
            "future_steps",
            []
        ):

            if isinstance(
                step,
                dict
            ):
                future_journey.append(
                    step.get(
                        "name",
                        step.get(
                            "action",
                            ""
                        )
                    )
                )

        operational_changes = []

        for item in redesign.get(
            "removed_steps",
            []
        ):
            operational_changes.append(
                f"Removed/consolidated: {item}"
            )

        for item in redesign.get(
            "automation_opportunities",
            []
        ):
            operational_changes.append(
                f"Automation opportunity: {item}"
            )

        risks = []

        if redesign.get(
            "required_integrations"
        ):
            risks.append(
                "Proposed integrations require "
                "technical, security and policy "
                "validation."
            )

        if not future_journey:
            risks.append(
                "Future journey is incomplete."
            )

        bottlenecks = list(
            service.get(
                "waiting_times",
                []
            )
        )

        return {
            "current_customer_journey":
                current_journey,
            "future_customer_journey":
                future_journey,
            "operational_changes":
                operational_changes,
            "risks":
                risks,
            "bottlenecks":
                bottlenecks,
            "required_integrations":
                redesign.get(
                    "required_integrations",
                    []
                ),
            "implementation_dependencies":
                list(
                    service.get(
                        "dependencies",
                        []
                    )
                ),
            # MERGED FROM P1: pass through where the underlying
            # journey design came from (AI-primary or the
            # deterministic template fallback) -- this agent only
            # reshapes already-decided data, so it has no reasoning of
            # its own to attribute.
            "analysis_source":
                redesign.get("analysis_source", "template"),
        }