"""Regression tests for the SIXTH root-cause-fix pass, based on a
confirmed real Ollama 0.32.15 + qwen3:4b production failure:

    JOURNEY.full_journey returns valid JSON containing ONLY
    "overall_reasoning" -- no "steps" key at all -- causing the
    journey to silently fall back to the deterministic template. Not
    a parse error, not a truncation: the model completed a
    syntactically valid response that just never got to the required
    array, most plausibly because the original prompt (~11.6K chars of
    static instructions before any service content) asked too much of
    a 4B model in one shot.

Fix: the prompt was substantially shortened and de-duplicated (steps
requested BEFORE overall_reasoning in the schema so a small model
prioritizes the load-bearing field), AND a distinct failure mode
("missing_steps"/"step_count_out_of_range" vs. a hard parse error) now
triggers exactly one compact, steps-only retry -- much shorter than
the original prompt -- before conceding to the template. Ollama stays
the sole author of the journey throughout; nothing here fabricates
steps or forces a template in its place.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.journey_builder_agent import JourneyBuilderAgent


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.prompts = []

    def generate(self, system_prompt, user_prompt, max_new_tokens=None, temperature=0, timeout=None):
        self.calls += 1
        self.prompts.append(user_prompt)
        if not self._responses:
            return ""
        return self._responses.pop(0)


GOOD_COMPACT_STEPS = [
    {
        "name": "Consolidated intake", "type": "SYSTEM", "executor": "AGENT",
        "action": "Assistant gathers the request using existing data.",
        "detailed_description": "The assistant collects everything needed using already-available profile data.",
        "reasoning": "Entry point.", "customer_role": "States intent", "has_payment": False,
        "payment_reasoning": "", "requires_human_judgement": False, "human_judgement_reason": "",
        "requires_customer_approval": False, "depends_on_previous": "", "delivers_customer_result": False,
    },
    {
        "name": "Automated check", "type": "SYSTEM", "executor": "AGENT",
        "action": "System checks eligibility automatically.",
        "detailed_description": "The assistant automatically checks eligibility instead of a manual employee review.",
        "reasoning": "Automates the manual step.", "customer_role": "None", "has_payment": False,
        "payment_reasoning": "", "requires_human_judgement": False, "human_judgement_reason": "",
        "requires_customer_approval": False, "depends_on_previous": "Intake complete", "delivers_customer_result": False,
    },
    {
        "name": "Deliver result", "type": "SYSTEM", "executor": "AGENT",
        "action": "Customer receives the result.",
        "detailed_description": "The assistant delivers the outcome to the customer with a reviewable record.",
        "reasoning": "Concludes the journey.", "customer_role": "Receives result", "has_payment": False,
        "payment_reasoning": "", "requires_human_judgement": False, "human_judgement_reason": "",
        "requires_customer_approval": False, "depends_on_previous": "Check complete", "delivers_customer_result": True,
    },
]

SERVICE = {
    "service_name": "Generic approval service",
    "description": "A generic government approval",
    "steps": ["Customer submits request", "Employee manually reviews it", "System issues decision"],
}


def test_journey_builder_recovers_from_reasoning_only_response_via_compact_retry():
    """Reproduces the EXACT confirmed real-world failure: the first
    response is valid JSON with only overall_reasoning, no steps at
    all. The agent must retry once with a compact prompt and end up
    with a real AI-designed journey -- never silently falling back to
    the template for this specific failure mode."""
    reasoning_only = json.dumps({
        "overall_reasoning": "This service should be redesigned to reduce customer effort."
    })
    good_compact = json.dumps({"steps": GOOD_COMPACT_STEPS, "overall_reasoning": "Compact retry design."})

    llm = FakeLLM([reasoning_only, good_compact])
    agent = JourneyBuilderAgent(llm)
    result = agent.run(SERVICE, {"steps": []}, relevant_standards={"applicable_standards": []})

    assert llm.calls == 2, f"Expected exactly one compact retry; got {llm.calls} call(s)."
    assert result["analysis_source"] == "ai", (
        "Expected the compact retry's real AI output to be used, not "
        f"a template fallback; got analysis_source={result['analysis_source']!r}"
    )
    assert len(result["future_steps"]) == 3
    # The retry prompt must be meaningfully shorter than the full prompt.
    assert len(llm.prompts[1]) < len(llm.prompts[0]) * 0.5, (
        f"Expected the compact retry prompt to be much shorter than the "
        f"full prompt; got {len(llm.prompts[1])} vs {len(llm.prompts[0])} chars."
    )


def test_journey_builder_falls_back_to_template_if_compact_retry_also_fails():
    """If even the compact retry can't produce a usable steps array,
    the agent must honestly fall back to the template -- not fabricate
    steps, not loop indefinitely."""
    reasoning_only = json.dumps({"overall_reasoning": "Still just reasoning."})
    still_reasoning_only = json.dumps({"overall_reasoning": "Compact retry also just reasoning."})

    llm = FakeLLM([reasoning_only, still_reasoning_only])
    agent = JourneyBuilderAgent(llm)
    result = agent.run(SERVICE, {"steps": []}, relevant_standards={"applicable_standards": []})

    assert llm.calls == 2, "Must not retry more than once for this failure mode."
    assert result["analysis_source"] == "template"
    assert result["future_steps"], "Template fallback must still produce a usable journey."


def test_journey_builder_does_not_compact_retry_on_hard_parse_error():
    """A genuinely malformed response (not valid JSON at all) is a
    different failure mode and must go straight to the template --
    the compact retry exists specifically for the 'valid JSON, no
    steps' pattern, not for garbage output."""
    llm = FakeLLM(["not json at all {{{"])
    agent = JourneyBuilderAgent(llm)
    result = agent.run(SERVICE, {"steps": []}, relevant_standards={"applicable_standards": []})
    assert llm.calls == 1, "A hard parse error should not trigger the compact retry."
    assert result["analysis_source"] == "template"


def test_full_journey_prompt_is_substantially_smaller_than_before():
    """Locks in the actual prompt-size reduction (not just a retry
    safety net) -- the static prompt template itself must be
    meaningfully smaller than the pre-fix ~11.6K character version."""
    import re
    text = Path(__file__).resolve().parents[1].joinpath(
        "agents", "journey_builder_agent.py"
    ).read_text()
    match = re.search(r'prompt = f""".*?\n"""\n', text, re.S)
    assert match, "Could not locate the main journey prompt template."
    assert len(match.group(0)) < 9500, (
        f"Expected the main prompt template to stay well under the "
        f"pre-fix ~11.6K chars; got {len(match.group(0))} chars."
    )


def test_full_journey_schema_requests_steps_before_overall_reasoning():
    """The JSON shape shown to the model must ask for 'steps' before
    'overall_reasoning' -- so a model that runs out of budget mid-
    response has already emitted the load-bearing field."""
    text = Path(__file__).resolve().parents[1].joinpath(
        "agents", "journey_builder_agent.py"
    ).read_text()
    steps_shape_index = text.index('"steps": [\n    {{\n      "name"')
    reasoning_shape_index = text.index('"overall_reasoning": "1-2 sentences')
    assert steps_shape_index < reasoning_shape_index, (
        "'steps' must appear before 'overall_reasoning' in the "
        "requested JSON shape."
    )


def test_compact_retry_prompt_supports_arabic_and_english():
    """The compact retry path must still honor is_arabic -- the site
    must keep working correctly in both languages, not just English."""
    reasoning_only = json.dumps({"overall_reasoning": "فقط استدلال، بدون خطوات."})
    good_compact = json.dumps({
        "steps": [
            {
                "name": "الاستقبال الموحد", "type": "SYSTEM", "executor": "AGENT",
                "action": "يجمع المساعد الطلب.", "detailed_description": "يجمع المساعد كل ما يلزم باستخدام بيانات الملف الشخصي.",
                "reasoning": "نقطة البداية.", "customer_role": "يوضح نيته", "has_payment": False,
                "payment_reasoning": "", "requires_human_judgement": False, "human_judgement_reason": "",
                "requires_customer_approval": False, "depends_on_previous": "", "delivers_customer_result": False,
            },
            {
                "name": "تسليم النتيجة", "type": "SYSTEM", "executor": "AGENT",
                "action": "يستلم المتعامل النتيجة.", "detailed_description": "يسلم المساعد النتيجة النهائية للمتعامل مع سجل قابل للمراجعة.",
                "reasoning": "يختتم الرحلة.", "customer_role": "يستلم النتيجة", "has_payment": False,
                "payment_reasoning": "", "requires_human_judgement": False, "human_judgement_reason": "",
                "requires_customer_approval": False, "depends_on_previous": "", "delivers_customer_result": True,
            },
        ],
        "overall_reasoning": "تصميم مختصر.",
    }, ensure_ascii=False)

    llm = FakeLLM([reasoning_only, good_compact])
    agent = JourneyBuilderAgent(llm)
    service = {
        "service_name": "خدمة موافقة عامة",
        "description": "خدمة حكومية عامة",
        "steps": ["العميل يقدم الطلب", "الموظف يراجع الطلب يدويًا", "النظام يصدر القرار"],
        "lang": "ar",
    }
    result = agent.run(service, {"steps": []}, relevant_standards={"applicable_standards": []})
    assert llm.calls == 2
    assert result["analysis_source"] == "ai"
    assert len(result["future_steps"]) == 2
    # The compact retry prompt itself must have been written in Arabic.
    assert "اكتب كل النصوص بالعربية" in llm.prompts[1]


if __name__ == "__main__":
    test_journey_builder_recovers_from_reasoning_only_response_via_compact_retry()
    test_journey_builder_falls_back_to_template_if_compact_retry_also_fails()
    test_journey_builder_does_not_compact_retry_on_hard_parse_error()
    test_full_journey_prompt_is_substantially_smaller_than_before()
    test_full_journey_schema_requests_steps_before_overall_reasoning()
    test_compact_retry_prompt_supports_arabic_and_english()
    print("ALL SESSION-6 ROOT-CAUSE-FIX TESTS PASSED")
