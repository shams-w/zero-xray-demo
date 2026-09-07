from typing import TypedDict
from langgraph.graph import (
    StateGraph,
    START,
    END,
)
from core.rules import (
    calculate_metrics,
)

from core.scoring import (
    calculate_zero_bureaucracy_score,
)

from agents.service_agent import (
    ServiceAnalystAgent,
)

from agents.standards_agent import (
    StandardsAgent,
)

from agents.gap_agent import (
    GapAnalysisAgent,
)

from agents.zero_bureaucracy_agent import (
    ZeroBureaucracyAgent,
)

from agents.step_compliance_agent import (
    StepComplianceAgent,
)

from agents.journey_builder_agent import (
    JourneyBuilderAgent,
)

from agents.simulation_agent import (
    SimulationAgent,
)

from agents.validation_agent import (
    ValidationAgent,
)

from core.llm import IS_GROQ


# ============================================================
# LANGGRAPH STATE
# ============================================================

class ServiceState(
    TypedDict,
    total=False,
):

    # Original service entered by the user
    service: dict

    # Fixed government standards
    standards_text: str
    standards: dict

    # Current-service analysis
    service_analysis: dict

    # Standards applicable to this service
    relevant_standards: dict

    # Detected service gaps
    gaps: dict

    # Zero Bureaucracy findings
    bureaucracy_findings: dict

    # NEW:
    # Individual assessment for every current step
    step_compliance: dict

    # Proposed future journey
    redesign: dict

    # Simulation result
    simulation: dict

    # Deterministic metrics
    metrics: dict

    # Final validation
    validation: dict

    # Agent execution status
    agent_status: dict

    # Final API result
    final_result: dict


# ============================================================
# BUILD WORKFLOW
# ============================================================

def build_workflow(
    llm
):

    # ========================================================
    # INITIALIZE AGENTS
    # ========================================================

    # Groq Free-tier orchestration: preserve the full 9-agent workflow,
    # but reserve cloud inference for the one stage where generative
    # reasoning is essential: Journey Builder. The remaining agents keep
    # their existing deterministic/evidence-grounded logic. This avoids
    # firing several 700-900 token requests in the same minute and then
    # silently degrading half the pipeline to fallback after 429s.
    # Local Ollama/mock modes are unchanged and still receive the LLM in
    # every agent exactly as before.
    support_llm = None if IS_GROQ else llm

    service_agent = (
        ServiceAnalystAgent(
            support_llm
        )
    )

    standards_agent = (
        StandardsAgent(
            support_llm
        )
    )

    gap_agent = (
        GapAnalysisAgent(
            support_llm
        )
    )

    zero_agent = (
        ZeroBureaucracyAgent(
            support_llm
        )
    )

    step_compliance_agent = (
        StepComplianceAgent(
            support_llm
        )
    )

    journey_builder_agent = (
        JourneyBuilderAgent(
            llm
        )
    )

    simulation_agent = (
        SimulationAgent(
            support_llm
        )
    )

    validation_agent = (
        ValidationAgent(
            support_llm
        )
    )

    # ========================================================
    # 1/9 — GOVERNMENT STANDARDS
    # ========================================================

    def prepare_standards_node(
        state
    ):

        print(
            "\n[1/9] Government Standards ready."
        )

        text = state.get(
            "standards_text",
            ""
        )

        if not text:

            raise ValueError(
                "Government standards are missing."
            )

        return {

            "standards": {

                "source": (
                    "Government AI Assistant "
                    "Service Design Guide"
                ),

                "source_text":
                    text,
            },

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "government_standards":
                    "completed",
            },
        }

    # ========================================================
    # 2/9 — SERVICE ANALYSIS
    # ========================================================

    def service_node(
        state
    ):

        print(
            "[2/9] Service Agent..."
        )

        service = state.get(
            "service"
        )

        if not service:

            raise ValueError(
                "Service input is missing."
            )

        result = (
            service_agent.run(
                service
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Service Agent returned "
                "an invalid result."
            )

        # Keep the original service metadata, but replace only the raw
        # current-journey step list with ServiceAnalystAgent's accepted
        # semantic steps. This makes every downstream stage (step compliance,
        # journey design, metrics, and final result) use the same reviewed
        # Current Journey instead of falling back to the original noisy line
        # count. Capabilities are carried forward for the Journey Builder's
        # existing evidence gates. No other service field is changed.
        updated_service = dict(service)
        semantic_steps = result.get("steps")
        if isinstance(semantic_steps, list) and semantic_steps:
            updated_service["steps"] = semantic_steps
        updated_service["capabilities"] = result.get("capabilities", {})

        return {

            "service":
                updated_service,

            "service_analysis":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "service":
                    "completed",
            },
        }

    # ========================================================
    # 3/9 — APPLICABLE GOVERNMENT STANDARDS
    # ========================================================

    def standards_node(
        state
    ):

        print(
            "[3/9] Standards Agent..."
        )

        result = (
            standards_agent.run(

                state.get(
                    "service_analysis",
                    {}
                ),

                state.get(
                    "standards",
                    {}
                ),
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Standards Agent returned "
                "an invalid result."
            )

        return {

            "relevant_standards":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "standards":
                    "completed",
            },
        }

    # ========================================================
    # 4/9 — GAP ANALYSIS
    # ========================================================

    def gap_node(
        state
    ):

        print(
            "[4/9] Gap Analysis Agent..."
        )

        result = (
            gap_agent.run(

                state.get(
                    "service_analysis",
                    {}
                ),

                state.get(
                    "relevant_standards",
                    {}
                ),
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Gap Analysis Agent returned "
                "an invalid result."
            )

        return {

            "gaps":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "gap":
                    "completed",
            },
        }

    # ========================================================
    # 5/9 — ZERO BUREAUCRACY ANALYSIS
    # ========================================================

    def bureaucracy_node(
        state
    ):

        print(
            "[5/9] Zero Bureaucracy Agent..."
        )

        result = (
            zero_agent.run(

                state.get(
                    "service_analysis",
                    {}
                ),

                state.get(
                    "gaps",
                    {}
                ),
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Zero Bureaucracy Agent returned "
                "an invalid result."
            )

        return {

            "bureaucracy_findings":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "zero_bureaucracy":
                    "completed",
            },
        }

    # ========================================================
    # 6/9 — STEP-BY-STEP COMPLIANCE
    # ========================================================

    def step_compliance_node(
        state
    ):

        print(
            "[6/9] Step Compliance Agent..."
        )

        result = (
            step_compliance_agent.run(

                service=state.get(
                    "service",
                    {}
                ),

                service_analysis=state.get(
                    "service_analysis",
                    {}
                ),

                relevant_standards=state.get(
                    "relevant_standards",
                    {}
                ),
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Step Compliance Agent "
                "returned an invalid result."
            )

        assessments = (
            result.get(
                "step_assessment",
                []
            )
        )

        if not isinstance(
            assessments,
            list
        ):

            raise ValueError(
                "step_assessment must be a list."
            )

        # --------------------------------------------
        # Log each decision clearly
        # --------------------------------------------

        for assessment in assessments:

            if not isinstance(
                assessment,
                dict
            ):
                continue

            step_number = (
                assessment.get(
                    "step_number",
                    "?"
                )
            )

            decision = (
                assessment.get(
                    "decision",
                    "UNKNOWN"
                )
            )

            status = (
                assessment.get(
                    "status",
                    "UNKNOWN"
                )
            )

            standard_id = (
                assessment.get(
                    "standard_id",
                    ""
                )
            )

            print(
                f"    Step {step_number}: "
                f"{status} → {decision} "
                f"[{standard_id or 'NO STANDARD'}]"
            )

        return {

            "step_compliance":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "step_compliance":
                    "completed",
            },
        }

    # ========================================================
    # 7/9 — BUILD FUTURE JOURNEY
    # ========================================================

    def journey_builder_node(
        state
    ):

        print(
            "[7/9] Journey Builder..."
        )

        result = (
            journey_builder_agent.run(

                service=state.get(
                    "service",
                    {}
                ),

                step_compliance=state.get(
                    "step_compliance",
                    {}
                ),

                relevant_standards=state.get(
                    "relevant_standards",
                    {}
                ),

                gaps=state.get(
                    "gaps",
                    {}
                ),
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Journey Builder returned "
                "an invalid result."
            )

        future_steps = (
            result.get(
                "future_steps",
                []
            )
        )

        if not isinstance(
            future_steps,
            list
        ):

            raise ValueError(
                "future_steps must be a list."
            )

        if not future_steps:

            raise ValueError(
                "Journey Builder returned "
                "an empty future journey."
            )

        # --------------------------------------------
        # Important safeguard:
        # unknown/review steps must not disappear
        # --------------------------------------------

        review_steps = (
            result.get(
                "review_steps",
                []
            )
        )

        if review_steps:

            print(
                f"    Human review required for "
                f"{len(review_steps)} step(s)."
            )

        removed_steps = (
            result.get(
                "removed_steps",
                []
            )
        )

        print(
            f"    Proposed future journey: "
            f"{len(future_steps)} step(s)"
        )

        print(
            f"    Removed current steps: "
            f"{len(removed_steps)}"
        )

        return {

            "redesign":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "journey_builder":
                    "completed",

                # Keep this key for frontend compatibility
                "redesign":
                    "completed",
            },
        }

    # ========================================================
    # 8A — SIMULATION
    # ========================================================

    def simulation_node(
        state
    ):

        print(
            "[8/9] Simulation Agent..."
        )

        result = (
            simulation_agent.run(

                state.get(
                    "service",
                    {}
                ),

                state.get(
                    "redesign",
                    {}
                ),
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Simulation Agent returned "
                "an invalid result."
            )

        return {

            "simulation":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "simulation":
                    "completed",
            },
        }

    # ========================================================
    # METRICS ENGINE
    # ========================================================

    def metrics_node(
        state
    ):

        print(
            "[METRICS] Calculating..."
        )

        metrics = (
            calculate_metrics(

                state.get(
                    "service",
                    {}
                ),

                state.get(
                    "redesign",
                    {}
                ),
            )
        )

        zero_score = (
            calculate_zero_bureaucracy_score(
                metrics
            )
        )

        metrics[
            "zero_bureaucracy_score"
        ] = zero_score

        current_steps = (
            metrics.get(
                "current",
                {}
            ).get(
                "steps",
                0
            )
        )

        future_steps = (
            metrics.get(
                "future",
                {}
            ).get(
                "steps",
                0
            )
        )

        reduction = (
            metrics.get(
                "reduction",
                {}
            ).get(
                "steps_percent"
            )
        )

        print(
            f"    Current steps: {current_steps}"
        )

        print(
            f"    Future steps: {future_steps}"
        )

        print(
            f"    Step reduction: {reduction}%"
        )

        print(
            f"    Zero Bureaucracy Score: "
            f"{zero_score}/100"
        )

        return {

            "metrics":
                metrics,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "metrics":
                    "completed",
            },
        }

    # ========================================================
    # 9/9 — VALIDATION
    # ========================================================

    def validation_node(
        state
    ):

        print(
            "[9/9] Validation Agent..."
        )

        result = (
            validation_agent.run(

                state.get(
                    "service",
                    {}
                ),

                state.get(
                    "relevant_standards",
                    {}
                ),

                state.get(
                    "redesign",
                    {}
                ),

                state.get(
                    "metrics",
                    {}
                ),
            )
        )

        if not isinstance(
            result,
            dict
        ):

            raise ValueError(
                "Validation Agent returned "
                "an invalid result."
            )

        print(
            "[VALIDATION]",
            result.get(
                "status",
                "UNKNOWN"
            ),
            "| Compliance:",
            result.get(
                "compliance_score",
                0
            ),
            "| Feasibility:",
            result.get(
                "feasibility_score",
                0
            ),
            "| Zero Bureaucracy:",
            result.get(
                "zero_bureaucracy_score",
                0
            ),
        )

        return {

            "validation":
                result,

            "agent_status": {

                **state.get(
                    "agent_status",
                    {}
                ),

                "validation":
                    "completed",
            },
        }

    # ========================================================
    # FINAL RESULT
    # ========================================================

    def final_node(
        state
    ):

        print(
            "\n========================================"
        )

        print(
            "ANALYSIS COMPLETE"
        )

        print(
            "========================================\n"
        )

        validation = (
            state.get(
                "validation",
                {}
            )
        )

        step_compliance = (
            state.get(
                "step_compliance",
                {}
            )
        )

        step_summary = (
            step_compliance.get(
                "summary",
                {}
            )
        )

        return {

            "final_result": {

                # =============================================
                # SERVICE
                # =============================================

                "service_name":
                    state.get(
                        "service",
                        {}
                    ).get(
                        "service_name",
                        "Unknown Service"
                    ),

                "service":
                    state.get(
                        "service",
                        {}
                    ),

                # =============================================
                # CURRENT-STATE ANALYSIS
                # =============================================

                "service_analysis":
                    state.get(
                        "service_analysis",
                        {}
                    ),

                # =============================================
                # GOVERNMENT STANDARDS
                # =============================================

                "relevant_standards":
                    state.get(
                        "relevant_standards",
                        {}
                    ),

                # =============================================
                # GAPS
                # =============================================

                "gaps":
                    state.get(
                        "gaps",
                        {}
                    ),

                # =============================================
                # ZERO BUREAUCRACY FINDINGS
                # =============================================

                "zero_bureaucracy_findings":
                    state.get(
                        "bureaucracy_findings",
                        {}
                    ),

                # =============================================
                # NEW: EACH STEP AGAINST STANDARDS
                # =============================================

                "step_compliance":
                    step_compliance,

                # Convenient summary for frontend
                "step_compliance_summary":
                    step_summary,

                # =============================================
                # PROPOSED JOURNEY
                # =============================================

                "redesign":
                    state.get(
                        "redesign",
                        {}
                    ),

                # =============================================
                # SIMULATION
                # =============================================

                "simulation":
                    state.get(
                        "simulation",
                        {}
                    ),

                # =============================================
                # METRICS
                # =============================================

                "metrics":
                    state.get(
                        "metrics",
                        {}
                    ),

                # =============================================
                # VALIDATION
                # =============================================

                "validation":
                    validation,

                "status":
                    validation.get(
                        "status",
                        "UNKNOWN"
                    ),

                # =============================================
                # EXECUTION STATUS
                # =============================================

                "agent_status":
                    state.get(
                        "agent_status",
                        {}
                    ),
            }
        }

    # ========================================================
    # BUILD LANGGRAPH
    # ========================================================

    graph = StateGraph(
        ServiceState
    )

    # --------------------------------------------------------
    # Nodes
    # --------------------------------------------------------

    graph.add_node(
        "prepare_standards",
        prepare_standards_node,
    )

    graph.add_node(
        "service",
        service_node,
    )

    graph.add_node(
        "standards",
        standards_node,
    )

    graph.add_node(
        "gap",
        gap_node,
    )

    graph.add_node(
        "bureaucracy",
        bureaucracy_node,
    )

    graph.add_node(
        "step_compliance",
        step_compliance_node,
    )

    graph.add_node(
        "journey_builder",
        journey_builder_node,
    )

    graph.add_node(
        "simulation",
        simulation_node,
    )

    graph.add_node(
        "metrics",
        metrics_node,
    )

    graph.add_node(
        "validation",
        validation_node,
    )

    graph.add_node(
        "final",
        final_node,
    )

    # ========================================================
    # WORKFLOW EDGES
    # ========================================================

    graph.add_edge(
        START,
        "prepare_standards",
    )

    graph.add_edge(
        "prepare_standards",
        "service",
    )

    graph.add_edge(
        "service",
        "standards",
    )

    graph.add_edge(
        "standards",
        "gap",
    )

    graph.add_edge(
        "gap",
        "bureaucracy",
    )

    # NEW:
    # Assess every service step individually
    graph.add_edge(
        "bureaucracy",
        "step_compliance",
    )

    # NEW:
    # Build the future journey only from
    # grounded step decisions
    graph.add_edge(
        "step_compliance",
        "journey_builder",
    )

    graph.add_edge(
        "journey_builder",
        "simulation",
    )

    graph.add_edge(
        "simulation",
        "metrics",
    )

    graph.add_edge(
        "metrics",
        "validation",
    )

    graph.add_edge(
        "validation",
        "final",
    )

    graph.add_edge(
        "final",
        END,
    )

    return graph.compile()
