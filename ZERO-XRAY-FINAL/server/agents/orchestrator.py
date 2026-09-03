from core.llm import LocalLLM
from core.service_input_normalizer import normalize_service_input
from core.result_provenance import attach_analysis_provenance

from graph.workflow import (
    build_workflow
)


class ServiceOrchestrator:

    def __init__(
        self,
        standards_text,
    ):

        self.llm = LocalLLM()

        self.standards_text = (
            standards_text
        )

        self.workflow = (
            build_workflow(
                self.llm
            )
        )

    def analyze(
        self,
        service,
    ):

        service = normalize_service_input(service)

        initial_state = {
            "service":
                service,

            "standards_text":
                self.standards_text,

            "iteration":
                0,

            "agent_status":
                {},

            "redesign_history":
                [],
        }

        result = (
            self.workflow.invoke(
                initial_state
            )
        )

        return attach_analysis_provenance(result[
            "final_result"
        ])
