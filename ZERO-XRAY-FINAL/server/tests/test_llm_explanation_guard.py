"""Focused regression tests for the placeholder/generic-LLM-response
guard fix (core/llm_explanation_guard.py) applied additively to
Predict/Simulate/Challenge/Evolve/Prevent's explanation validators.

Proves:
  1. The exact real placeholder observed from
     tools/mock_ollama_server.py's "no template matched" fallback is
     now rejected by every one of the 5 agents -> explanation_source
     falls back to "template".
  2. A genuine, on-topic, grounded LLM explanation is still accepted
     -> explanation_source == "ai" (nothing over-tightened).
  3. No deterministic value (confidence, severity, threshold,
     exposure, ranking, ids) is affected by this fix.

Isolated the same way every other focused test file is: pure unit
tests, no database, no real network call to any LLM.
"""

import os
import unittest

os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:19999")  # deliberately unreachable
os.environ.setdefault("ZX_LLM_MODE", "ollama")

from core.llm_explanation_guard import is_placeholder_or_generic, extract_clean_explanation
from agents.prediction_agent import PredictionAgent
from agents.future_simulation_agent import FutureSimulationAgent
from agents.challenge_agent import ChallengeAgent
from agents.evolve_agent import EvolveAgent
from agents.prevent_agent import PreventAgent


# The exact real placeholder observed from
# tools/mock_ollama_responses.py::_route_response's fallback branch.
REAL_MOCK_PLACEHOLDER = (
    '{"note": "MOCK_AI: no specific response template matched this caller."}'
)


class GuardUnitTestCase(unittest.TestCase):
    """Direct tests of the shared guard function."""

    def test_real_mock_placeholder_is_rejected(self):
        self.assertTrue(is_placeholder_or_generic(REAL_MOCK_PLACEHOLDER))

    def test_empty_string_is_rejected(self):
        self.assertTrue(is_placeholder_or_generic(""))
        self.assertTrue(is_placeholder_or_generic("   "))
        self.assertTrue(is_placeholder_or_generic(None))

    def test_too_short_is_rejected(self):
        self.assertTrue(is_placeholder_or_generic("ok"))

    def test_other_placeholder_phrasings_are_rejected(self):
        self.assertTrue(is_placeholder_or_generic("Not implemented yet."))
        self.assertTrue(is_placeholder_or_generic("No response available."))
        self.assertTrue(is_placeholder_or_generic("Unable to generate a response."))

    def test_genuine_explanation_is_accepted(self):
        self.assertFalse(is_placeholder_or_generic(
            "This step has recurred as a compliance gap in both stored analyses, "
            "so it is likely to keep occurring unless addressed."
        ))


def _fabricating_mock_llm_text():
    return REAL_MOCK_PLACEHOLDER


class FabricatingMockLLM:
    """Mimics the real tools/mock_ollama_server.py behavior for a
    caller it doesn't recognize: returns the exact real placeholder
    text observed in the practical E2E verification."""

    def generate(self, *args, **kwargs):
        return REAL_MOCK_PLACEHOLDER


class HonestLLM:
    """A well-behaved LLM that returns a real, on-topic, grounded
    sentence -- must still be accepted after this fix."""

    def __init__(self, text):
        self._text = text

    def generate(self, *args, **kwargs):
        return self._text


class PredictPlaceholderRegressionTestCase(unittest.TestCase):
    def test_mock_placeholder_falls_back_to_template(self):
        agent = PredictionAgent(llm=FabricatingMockLLM())
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t1", "result": {
                    "gaps": {"gaps": [{"gap_id": "GAP-1", "standard_id": "STD-01",
                                        "description": "Missing digital ID check", "category": "General",
                                        "severity": "MEDIUM"}]},
                    "service_analysis": {"friction_points": []},
                }},
                {"id": "an-2", "created_at": "t2", "result": {
                    "gaps": {"gaps": [{"gap_id": "GAP-2", "standard_id": "STD-01",
                                        "description": "Missing digital ID check", "category": "General",
                                        "severity": "MEDIUM"}]},
                    "service_analysis": {"friction_points": []},
                }},
            ],
            "journeys": [],
        }
        result = agent.run(prediction_input)
        self.assertEqual(len(result["predictions"]), 1)
        prediction = result["predictions"][0]
        self.assertEqual(prediction["explanation_source"], "template")
        self.assertNotIn("MOCK_AI", prediction["explanation"])
        # Deterministic value completely unaffected by this fix.
        self.assertEqual(prediction["confidence"], 1.0)

    def test_genuine_ai_explanation_still_accepted(self):
        agent = PredictionAgent(llm=HonestLLM(
            "This gap has recurred in both stored analyses for this service."
        ))
        prediction_input = {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t1", "result": {
                    "gaps": {"gaps": [{"gap_id": "GAP-1", "standard_id": "STD-01",
                                        "description": "Missing digital ID check", "category": "General",
                                        "severity": "MEDIUM"}]},
                    "service_analysis": {"friction_points": []},
                }},
                {"id": "an-2", "created_at": "t2", "result": {
                    "gaps": {"gaps": [{"gap_id": "GAP-2", "standard_id": "STD-01",
                                        "description": "Missing digital ID check", "category": "General",
                                        "severity": "MEDIUM"}]},
                    "service_analysis": {"friction_points": []},
                }},
            ],
            "journeys": [],
        }
        result = agent.run(prediction_input)
        self.assertEqual(result["predictions"][0]["explanation_source"], "ai")


class SimulatePlaceholderRegressionTestCase(unittest.TestCase):
    def _graph(self):
        return {
            "steps": [
                {"step_id": "STEP-1", "name": "Customer states the request", "type": "CUSTOMER", "order": 0},
                {"step_id": "STEP-2", "name": "System verifies identity", "type": "SYSTEM", "order": 1},
            ],
            "integrations": [], "journeys_count": 0, "source_analysis_id": "an-x",
        }

    def test_mock_placeholder_falls_back_to_template(self):
        agent = FutureSimulationAgent(llm=FabricatingMockLLM())
        graph = self._graph()
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 0.8}, graph
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, graph)
        outcome = result["possible_outcomes"][0]
        self.assertEqual(outcome["description_source"], "template")
        self.assertNotIn("MOCK_AI", outcome["description"])
        self.assertEqual(result["likelihood"], 0.8)  # deterministic value unaffected

    def test_genuine_ai_explanation_still_accepted(self):
        agent = FutureSimulationAgent(llm=HonestLLM(
            "This cascading failure blocks the downstream step."
        ))
        graph = self._graph()
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 0.8}, graph
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, graph)
        self.assertEqual(result["possible_outcomes"][0]["description_source"], "ai")


class ChallengePlaceholderRegressionTestCase(unittest.TestCase):
    def _graph(self):
        return {
            "steps": [
                {"step_id": "STEP-1", "name": "Customer states the request", "type": "CUSTOMER", "order": 0},
                {"step_id": "STEP-2", "name": "System verifies identity", "type": "SYSTEM", "order": 1},
            ],
            "integrations": [], "journeys_count": 0, "source_analysis_id": "an-x",
        }

    def test_mock_placeholder_falls_back_to_template(self):
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(future_simulation_agent=simulation_agent, llm=FabricatingMockLLM())
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self._graph())
        self.assertGreater(len(result["vulnerabilities"]), 0)
        vulnerability = result["vulnerabilities"][0]
        self.assertEqual(vulnerability["explanation_source"], "template")
        self.assertNotIn("MOCK_AI", vulnerability["explanation"])

    def test_genuine_ai_explanation_still_accepted(self):
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(
            future_simulation_agent=simulation_agent,
            llm=HonestLLM("This step is a critical single point of failure for the service."),
        )
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self._graph())
        self.assertTrue(any(v["explanation_source"] == "ai" for v in result["vulnerabilities"]))


class EvolvePlaceholderRegressionTestCase(unittest.TestCase):
    def _challenge_output(self):
        return {
            "vulnerabilities": [{
                "vulnerability_id": "SLA_FRAGILITY:STEP-1",
                "vulnerability_type": "SLA_FRAGILITY",
                "target": "STEP-1",
                "source_case_ids": ["CASE-1"],
                "severity": 70.0,
                "severity_basis": "stub basis",
                "evidence": [],
                "explanation": "stub",
                "explanation_source": "template",
            }],
        }

    def _graph(self):
        return {
            "steps": [{"step_id": "STEP-1", "name": "Employee reviews", "type": "HUMAN", "order": 0}],
            "integrations": [],
        }

    def test_mock_placeholder_falls_back_to_template(self):
        agent = EvolveAgent(llm=FabricatingMockLLM())
        result = agent.run(self._challenge_output(), self._graph(), "CHAL-1")
        self.assertEqual(len(result["proposals"]), 1)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["explanation_source"], "template")
        self.assertNotIn("MOCK_AI", proposal["explanation"])
        self.assertEqual(proposal["exposure_before"], 70.0)  # deterministic value unaffected

    def test_genuine_ai_explanation_still_accepted(self):
        agent = EvolveAgent(llm=HonestLLM(
            "The step remains unchanged, with a new monitored SLA threshold."
        ))
        result = agent.run(self._challenge_output(), self._graph(), "CHAL-1")
        self.assertEqual(result["proposals"][0]["explanation_source"], "ai")


class PreventPlaceholderRegressionTestCase(unittest.TestCase):
    def _evolve_output(self):
        return {"proposals": [{
            "proposal_id": "ADD_SLA_SAFEGUARD:X",
            "evolution_type": "ADD_SLA_SAFEGUARD",
            "fixes_vulnerability_id": "SLA_FRAGILITY:STEP-1",
            "target": "STEP-1",
            "current_state": "stub", "proposed_state": "STEP-1 remains unchanged; a safeguard is added.",
            "protected": False, "exposure_before": 70.0, "exposure_after_estimate": None,
            "exposure_calculation_basis": None, "grounding": [], "explanation": "stub",
            "explanation_source": "template",
        }]}

    def test_mock_placeholder_falls_back_to_template(self):
        agent = PreventAgent(llm=FabricatingMockLLM())
        result = agent.run(self._evolve_output(), "EVO-1")
        self.assertEqual(len(result["triggers"]), 1)
        trigger = result["triggers"][0]
        self.assertEqual(trigger["explanation_source"], "template")
        self.assertNotIn("MOCK_AI", trigger["explanation"])
        self.assertEqual(trigger["status"], "DEFINED")  # deterministic value unaffected

    def test_genuine_ai_explanation_still_accepted(self):
        agent = PreventAgent(llm=HonestLLM(
            "Watch this step's severity and apply the safeguard if it recurs."
        ))
        result = agent.run(self._evolve_output(), "EVO-1")
        self.assertEqual(result["triggers"][0]["explanation_source"], "ai")


class PromptLeakageExtractionUnitTestCase(unittest.TestCase):
    """Direct unit tests of extract_clean_explanation() -- root-cause
    fix for raw Ollama prompt/JSON leakage."""

    def test_raw_request_json_is_rejected(self):
        leaked = (
            '{"task": "Rephrase an already-computed simulation result into one '
            'natural sentence for a government analyst.", "constraints": '
            '["Do not invent any new number, step name, or score not given to '
            'you."], "required_output": "one sentence"}'
        )
        self.assertIsNone(extract_clean_explanation(leaked))

    def test_vulnerability_prompt_echo_json_is_rejected(self):
        leaked = (
            '{"task": "Rephrase a vulnerability finding into one natural '
            'sentence for a government analyst.", "constraints": '
            '["Do not invent any new number, step, or severity not given to '
            'you."]}'
        )
        self.assertIsNone(extract_clean_explanation(leaked))

    def test_evolve_state_pair_prompt_echo_json_is_rejected(self):
        leaked = (
            '{"task": "Rephrase an already-decided CURRENT and PROPOSED state '
            'pair into one natural paragraph for a government analyst.", '
            '"required_output": "one paragraph"}'
        )
        self.assertIsNone(extract_clean_explanation(leaked))

    def test_plain_text_prompt_echo_is_rejected(self):
        leaked = (
            "You rephrase an already-computed simulation result into one "
            "natural sentence for a government analyst. Do not invent any "
            "new number, step name, or score not given to you."
        )
        self.assertIsNone(extract_clean_explanation(leaked))

    def test_plain_text_do_not_add_variant_is_rejected(self):
        leaked = (
            "Do not add any new fact, number, or claim not already given to you."
        )
        self.assertIsNone(extract_clean_explanation(leaked))

    def test_exact_observed_placeholder_leak_is_rejected(self):
        # ROOT-CAUSE FIX (placeholder-leakage audit): the exact text
        # observed in a real Challenge result -- a paraphrase of the
        # user_prompt's own closing instruction line ("Write one clear
        # sentence summarizing this. Do not add new numbers.") that
        # the prior marker set did not catch, since the model reworded
        # it away from "rephrase"/"do not invent"/"do not add any new".
        leaked = "One clear sentence summarizing the vulnerability finding"
        self.assertIsNone(extract_clean_explanation(leaked))

    def test_paragraph_summarizing_variant_is_rejected(self):
        # Evolve's own prompt closes with "Write one clear paragraph
        # summarizing this change. Do not add new facts." -- same
        # paraphrase failure mode, one clause over.
        leaked = "A clear paragraph summarizing this change to the step."
        self.assertIsNone(extract_clean_explanation(leaked))

    def test_summarizing_this_and_summarizing_the_variants_are_rejected(self):
        self.assertIsNone(extract_clean_explanation("A sentence summarizing this finding."))
        self.assertIsNone(extract_clean_explanation("A paragraph summarizing the proposed change."))

    def test_json_with_valid_output_field_is_unwrapped(self):
        wrapped = '{"output": "This step will be blocked if the upstream integration fails."}'
        self.assertEqual(
            extract_clean_explanation(wrapped),
            "This step will be blocked if the upstream integration fails.",
        )

    def test_json_output_field_that_itself_leaks_is_still_rejected(self):
        wrapped = '{"output": "{\\"task\\": \\"Rephrase this.\\"}"}'
        self.assertIsNone(extract_clean_explanation(wrapped))

    def test_json_without_output_field_is_rejected(self):
        # Any OTHER JSON shape -- not the specifically-supported
        # {"output": "..."} envelope -- is never partially trusted.
        self.assertIsNone(extract_clean_explanation('{"note": "some other field"}'))
        self.assertIsNone(extract_clean_explanation('{"task": "x", "output": 5}'))  # output not a string
        self.assertIsNone(extract_clean_explanation('{"output": ""}'))  # empty output

    def test_malformed_json_looking_text_is_rejected(self):
        self.assertIsNone(extract_clean_explanation('{"task": "unterminated'))

    def test_empty_and_none_are_rejected(self):
        self.assertIsNone(extract_clean_explanation(""))
        self.assertIsNone(extract_clean_explanation("   "))
        self.assertIsNone(extract_clean_explanation(None))

    def test_clean_natural_language_response_passes_through_unchanged(self):
        clean = "This step has recurred as a compliance gap in both stored analyses."
        self.assertEqual(extract_clean_explanation(clean), clean)

    def test_benign_use_of_similar_words_still_passes_through(self):
        # Guards against over-matching: legitimate explanations that
        # happen to use "clear" or "summary" in an unrelated sense
        # (not the exact instruction-echo phrases) must still pass.
        clean_one = "The backlog is now clear after the integration recovered."
        clean_two = "In summary, the review step is the recurring bottleneck."
        self.assertEqual(extract_clean_explanation(clean_one), clean_one)
        self.assertEqual(extract_clean_explanation(clean_two), clean_two)


class PromptLeakingMockLLM:
    """Simulates a misbehaving Ollama backend that echoes the internal
    request/prompt structure back instead of answering it -- the exact
    real-world failure mode this fix targets."""

    def __init__(self, leaked_text):
        self._leaked_text = leaked_text

    def generate(self, *args, **kwargs):
        return self._leaked_text


class OutputEnvelopeMockLLM:
    """Simulates a well-behaved backend that wraps its real answer in
    a {"output": "..."} JSON envelope -- must still be accepted."""

    def __init__(self, inner_text):
        self._inner_text = inner_text

    def generate(self, *args, **kwargs):
        return '{"output": "%s"}' % self._inner_text


PREDICT_TASK_LEAK = (
    '{"task": "Rephrase an already-verified factual statement into one '
    'natural sentence for a government analyst.", "constraints": '
    '["Do not invent any new fact, number, or claim."], "required_output": '
    '"one sentence"}'
)
SIMULATE_TASK_LEAK = (
    '{"task": "Rephrase an already-computed simulation result into one '
    'natural sentence for a government analyst.", "constraints": '
    '["Do not invent any new number, step name, or score not given to you."]}'
)
CHALLENGE_TASK_LEAK = (
    '{"task": "Rephrase a vulnerability finding into one natural sentence '
    'for a government analyst.", "required_output": "one sentence"}'
)
EVOLVE_TASK_LEAK = (
    '{"task": "Rephrase an already-decided CURRENT and PROPOSED state pair '
    'into one natural paragraph for a government analyst.", "constraints": '
    '["Do not add any new fact, number, or claim not already given to you."]}'
)
PREVENT_TASK_LEAK = (
    '{"task": "Rephrase an already-decided prevention trigger into one '
    'natural sentence for a government analyst.", "required_output": '
    '"one sentence"}'
)


class PredictPromptLeakageRegressionTestCase(unittest.TestCase):
    def _prediction_input(self):
        return {
            "service_id": "svc-1", "tenant_id": "t-1", "as_of": "now",
            "analyses": [
                {"id": "an-1", "created_at": "t1", "result": {
                    "gaps": {"gaps": [{"gap_id": "GAP-1", "standard_id": "STD-01",
                                        "description": "Missing digital ID check", "category": "General",
                                        "severity": "MEDIUM"}]},
                    "service_analysis": {"friction_points": []},
                }},
                {"id": "an-2", "created_at": "t2", "result": {
                    "gaps": {"gaps": [{"gap_id": "GAP-2", "standard_id": "STD-01",
                                        "description": "Missing digital ID check", "category": "General",
                                        "severity": "MEDIUM"}]},
                    "service_analysis": {"friction_points": []},
                }},
            ],
            "journeys": [],
        }

    def test_raw_prompt_json_never_reaches_the_explanation_field(self):
        agent = PredictionAgent(llm=PromptLeakingMockLLM(PREDICT_TASK_LEAK))
        result = agent.run(self._prediction_input())
        prediction = result["predictions"][0]
        self.assertEqual(prediction["explanation_source"], "template")
        self.assertNotIn('"task"', prediction["explanation"])
        self.assertNotIn("Rephrase", prediction["explanation"])
        self.assertEqual(prediction["confidence"], 1.0)  # deterministic value unaffected

    def test_output_envelope_is_unwrapped_and_accepted(self):
        agent = PredictionAgent(llm=OutputEnvelopeMockLLM(
            "This gap has recurred in both stored analyses for this service."
        ))
        result = agent.run(self._prediction_input())
        prediction = result["predictions"][0]
        self.assertEqual(prediction["explanation_source"], "ai")
        self.assertEqual(
            prediction["explanation"],
            "This gap has recurred in both stored analyses for this service.",
        )

    def test_exact_observed_placeholder_never_reaches_the_explanation_field(self):
        # ROOT-CAUSE FIX (placeholder-leakage audit): the real leak
        # observed in production -- a paraphrase of the prompt's own
        # closing instruction line, not a JSON echo -- must fall back
        # to the deterministic template exactly like any other
        # rejected candidate.
        agent = PredictionAgent(llm=PromptLeakingMockLLM(
            "One clear sentence summarizing the vulnerability finding"
        ))
        result = agent.run(self._prediction_input())
        prediction = result["predictions"][0]
        self.assertEqual(prediction["explanation_source"], "template")
        self.assertNotIn("summarizing", prediction["explanation"].lower())
        self.assertEqual(prediction["confidence"], 1.0)  # deterministic value unaffected


class SimulatePromptLeakageRegressionTestCase(unittest.TestCase):
    def _graph(self):
        return {
            "steps": [
                {"step_id": "STEP-1", "name": "Customer states the request", "type": "CUSTOMER", "order": 0},
                {"step_id": "STEP-2", "name": "System verifies identity", "type": "SYSTEM", "order": 1},
            ],
            "integrations": [], "journeys_count": 0, "source_analysis_id": "an-x",
        }

    def test_raw_prompt_json_never_reaches_the_description_field(self):
        agent = FutureSimulationAgent(llm=PromptLeakingMockLLM(SIMULATE_TASK_LEAK))
        graph = self._graph()
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 0.8}, graph
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, graph)
        outcome = result["possible_outcomes"][0]
        self.assertEqual(outcome["description_source"], "template")
        self.assertNotIn('"task"', outcome["description"])
        self.assertNotIn("Rephrase", outcome["description"])
        self.assertEqual(result["likelihood"], 0.8)  # deterministic value unaffected

    def test_output_envelope_is_unwrapped_and_accepted(self):
        agent = FutureSimulationAgent(llm=OutputEnvelopeMockLLM(
            "This cascading failure blocks the downstream step."
        ))
        graph = self._graph()
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 0.8}, graph
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, graph)
        outcome = result["possible_outcomes"][0]
        self.assertEqual(outcome["description_source"], "ai")
        self.assertEqual(outcome["description"], "This cascading failure blocks the downstream step.")

    def test_exact_observed_placeholder_never_reaches_the_description_field(self):
        agent = FutureSimulationAgent(llm=PromptLeakingMockLLM(
            "One clear sentence summarizing the vulnerability finding"
        ))
        graph = self._graph()
        variables = agent.validate_scenario(
            "CASCADING_STEP_FAILURE", {"origin_step_id": "STEP-1", "failure_probability": 0.8}, graph
        )
        result = agent.run("CASCADING_STEP_FAILURE", variables, graph)
        outcome = result["possible_outcomes"][0]
        self.assertEqual(outcome["description_source"], "template")
        self.assertNotIn("summarizing", outcome["description"].lower())
        self.assertEqual(result["likelihood"], 0.8)  # deterministic value unaffected


class ChallengePromptLeakageRegressionTestCase(unittest.TestCase):
    def _graph(self):
        return {
            "steps": [
                {"step_id": "STEP-1", "name": "Customer states the request", "type": "CUSTOMER", "order": 0},
                {"step_id": "STEP-2", "name": "System verifies identity", "type": "SYSTEM", "order": 1},
            ],
            "integrations": [], "journeys_count": 0, "source_analysis_id": "an-x",
        }

    def test_raw_prompt_json_never_reaches_the_explanation_field(self):
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(
            future_simulation_agent=simulation_agent,
            llm=PromptLeakingMockLLM(CHALLENGE_TASK_LEAK),
        )
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self._graph())
        self.assertGreater(len(result["vulnerabilities"]), 0)
        vulnerability = result["vulnerabilities"][0]
        self.assertEqual(vulnerability["explanation_source"], "template")
        self.assertNotIn('"task"', vulnerability["explanation"])
        self.assertNotIn("Rephrase", vulnerability["explanation"])

    def test_output_envelope_is_unwrapped_and_accepted(self):
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(
            future_simulation_agent=simulation_agent,
            llm=OutputEnvelopeMockLLM("This step is a critical single point of failure for the service."),
        )
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self._graph())
        self.assertTrue(any(v["explanation_source"] == "ai" for v in result["vulnerabilities"]))

    def test_exact_observed_placeholder_never_reaches_the_explanation_field(self):
        # ROOT-CAUSE FIX (placeholder-leakage audit): this is the
        # real production case that surfaced the gap -- a Challenge
        # vulnerability's explanation literally showed this text.
        simulation_agent = FutureSimulationAgent(llm=None)
        agent = ChallengeAgent(
            future_simulation_agent=simulation_agent,
            llm=PromptLeakingMockLLM("One clear sentence summarizing the vulnerability finding"),
        )
        result = agent.run(["EXHAUSTIVE_STEP_FAILURE"], self._graph())
        self.assertGreater(len(result["vulnerabilities"]), 0)
        vulnerability = result["vulnerabilities"][0]
        self.assertEqual(vulnerability["explanation_source"], "template")
        self.assertNotIn("summarizing", vulnerability["explanation"].lower())


class EvolvePromptLeakageRegressionTestCase(unittest.TestCase):
    def _challenge_output(self):
        return {
            "vulnerabilities": [{
                "vulnerability_id": "SLA_FRAGILITY:STEP-1",
                "vulnerability_type": "SLA_FRAGILITY",
                "target": "STEP-1",
                "source_case_ids": ["CASE-1"],
                "severity": 70.0,
                "severity_basis": "stub basis",
                "evidence": [],
                "explanation": "stub",
                "explanation_source": "template",
            }],
        }

    def _graph(self):
        return {
            "steps": [{"step_id": "STEP-1", "name": "Employee reviews", "type": "HUMAN", "order": 0}],
            "integrations": [],
        }

    def test_raw_prompt_json_never_reaches_the_explanation_field(self):
        agent = EvolveAgent(llm=PromptLeakingMockLLM(EVOLVE_TASK_LEAK))
        result = agent.run(self._challenge_output(), self._graph(), "CHAL-1")
        self.assertEqual(len(result["proposals"]), 1)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["explanation_source"], "template")
        self.assertNotIn('"task"', proposal["explanation"])
        self.assertNotIn("Rephrase", proposal["explanation"])
        self.assertEqual(proposal["exposure_before"], 70.0)  # deterministic value unaffected

    def test_output_envelope_is_unwrapped_and_accepted(self):
        agent = EvolveAgent(llm=OutputEnvelopeMockLLM(
            "The step remains unchanged, with a new monitored SLA threshold."
        ))
        result = agent.run(self._challenge_output(), self._graph(), "CHAL-1")
        proposal = result["proposals"][0]
        self.assertEqual(proposal["explanation_source"], "ai")
        self.assertEqual(
            proposal["explanation"],
            "The step remains unchanged, with a new monitored SLA threshold.",
        )

    def test_paragraph_summarizing_placeholder_never_reaches_the_explanation_field(self):
        # Evolve's own prompt closes with "Write one clear paragraph
        # summarizing this change. Do not add new facts." -- the
        # paragraph variant of the same leak.
        agent = EvolveAgent(llm=PromptLeakingMockLLM(
            "A clear paragraph summarizing this change to the step."
        ))
        result = agent.run(self._challenge_output(), self._graph(), "CHAL-1")
        proposal = result["proposals"][0]
        self.assertEqual(proposal["explanation_source"], "template")
        self.assertNotIn("summarizing", proposal["explanation"].lower())
        self.assertEqual(proposal["exposure_before"], 70.0)  # deterministic value unaffected


class PreventPromptLeakageRegressionTestCase(unittest.TestCase):
    def _evolve_output(self):
        return {"proposals": [{
            "proposal_id": "ADD_SLA_SAFEGUARD:X",
            "evolution_type": "ADD_SLA_SAFEGUARD",
            "fixes_vulnerability_id": "SLA_FRAGILITY:STEP-1",
            "target": "STEP-1",
            "current_state": "stub", "proposed_state": "STEP-1 remains unchanged; a safeguard is added.",
            "protected": False, "exposure_before": 70.0, "exposure_after_estimate": None,
            "exposure_calculation_basis": None, "grounding": [], "explanation": "stub",
            "explanation_source": "template",
        }]}

    def test_raw_prompt_json_never_reaches_the_explanation_field(self):
        agent = PreventAgent(llm=PromptLeakingMockLLM(PREVENT_TASK_LEAK))
        result = agent.run(self._evolve_output(), "EVO-1")
        self.assertEqual(len(result["triggers"]), 1)
        trigger = result["triggers"][0]
        self.assertEqual(trigger["explanation_source"], "template")
        self.assertNotIn('"task"', trigger["explanation"])
        self.assertNotIn("Rephrase", trigger["explanation"])
        self.assertEqual(trigger["status"], "DEFINED")  # deterministic value unaffected

    def test_output_envelope_is_unwrapped_and_accepted(self):
        agent = PreventAgent(llm=OutputEnvelopeMockLLM(
            "Watch this step's severity and apply the safeguard if it recurs."
        ))
        result = agent.run(self._evolve_output(), "EVO-1")
        trigger = result["triggers"][0]
        self.assertEqual(trigger["explanation_source"], "ai")
        self.assertEqual(
            trigger["explanation"],
            "Watch this step's severity and apply the safeguard if it recurs.",
        )

    def test_exact_observed_placeholder_never_reaches_the_explanation_field(self):
        agent = PreventAgent(llm=PromptLeakingMockLLM(
            "One clear sentence summarizing the vulnerability finding"
        ))
        result = agent.run(self._evolve_output(), "EVO-1")
        trigger = result["triggers"][0]
        self.assertEqual(trigger["explanation_source"], "template")
        self.assertNotIn("summarizing", trigger["explanation"].lower())
        self.assertEqual(trigger["status"], "DEFINED")  # deterministic value unaffected


if __name__ == "__main__":
    unittest.main()
