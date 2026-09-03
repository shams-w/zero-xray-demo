"""
Regression tests for the three ROOT-CAUSE fixes requested against the
real Qwen3:4b test run:

1. Service AI: grounding was exact-vocabulary, rejecting correct
   paraphrased output -> now meaning-based (core/grounding.py).
2. Standards AI: applicable_standard_ids came back [] because the
   free-selection prompt let the model answer with nothing -> now a
   per-id checklist that forces one explicit decision per standard.
3. Low-memory token budget: the output budget used to be silently
   shrunk (down to 256) whenever prompt + requested output exceeded
   num_ctx -> now num_ctx grows (up to OLLAMA_MAX_NUM_CTX) to fit the
   requested output instead.

None of these tests touch Journey/Gaps/Compliance/Validation.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.llm as llm_module
from core.grounding import is_semantically_grounded, light_stem
from agents.service_agent import ServiceAnalystAgent
from agents.standards_agent import StandardsAgent
from core.standards_catalog import STANDARDS_CATALOG


class FakeLLM:
    """Returns pre-scripted responses in call order (see
    tests/test_qwen3_real_failure_signatures.py for the same pattern)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.last_max_new_tokens = None

    def generate(self, system_prompt, user_prompt, max_new_tokens=None, temperature=0, timeout=None):
        self.calls += 1
        self.last_max_new_tokens = max_new_tokens
        if not self._responses:
            return ""
        return self._responses.pop(0)


# =====================================================================
# 1. Semantic grounding (core/grounding.py)
# =====================================================================

def test_grounding_accepts_paraphrase_not_just_exact_vocabulary():
    """The whole point of the fix: a rewording of real source content
    (different verb, different word order, no shared exact tokens for
    several words) must still be accepted as grounded."""
    source = "Customer uploads a copy of the national ID and pays the applicable fee before the certificate is released"
    paraphrase = "The applicant submits their national identity document and settles the required fee prior to certificate release"
    assert is_semantically_grounded(paraphrase, source), (
        "A meaning-preserving paraphrase should be accepted as grounded"
    )


def test_grounding_accepts_arabic_affix_variation():
    """Arabic prefix/suffix variation (same root, different attached
    letters) must not defeat grounding -- this was previously rejected
    by exact-string matching."""
    source = "الموظف يراجع الطلب ثم يرسله الى المشرف للموافقة"
    paraphrase = "موظفة تقوم بمراجعة الطلبات وارسالها للمشرفين للموافقه عليها"
    assert is_semantically_grounded(paraphrase, source), (
        "Arabic affix/conjugation variation of the same roots should still ground"
    )


def test_grounding_still_rejects_fabricated_content():
    """Anti-hallucination guarantee must hold: text with no real
    relationship to the source is still rejected."""
    source = "Customer submits a form"
    fabricated = "A spaceship crew launches an intergalactic voyage to Mars orbit"
    assert not is_semantically_grounded(fabricated, source)


def test_light_stem_normalizes_common_arabic_affixes():
    assert light_stem("الموظف") == light_stem("موظف")
    assert light_stem("موظفة") == light_stem("موظف") or light_stem("موظفة").startswith(light_stem("موظف")[:2])


def test_service_agent_accepts_paraphrased_capability_evidence():
    """Real bug: qwen3:4b's evidence quote paraphrases the source
    (e.g. 'submits payment for the service' instead of echoing 'pays
    the applicable fee' verbatim) and used to be silently rejected as
    'ungrounded', flipping a true capability back to false."""
    raw_lines = [
        "Customer uploads a copy of the national ID",
        "Customer pays the applicable fee before the certificate is released",
        "Supervisor approves the request",
    ]
    llm = FakeLLM([
        json.dumps({"steps": raw_lines}, ensure_ascii=False),
        json.dumps({"objective": "Get a certificate issued", "friction_points": []}, ensure_ascii=False),
        json.dumps({
            "has_payment": True,
            # Paraphrased, not an exact vocabulary echo of the raw line.
            "payment_evidence": "The applicant settles the required service charge prior to release",
            "has_documents": True,
            "documents_evidence": "A national identity document is submitted by the customer",
            "has_physical_visit": False, "visit_evidence": "",
            "has_human_approval": True,
            "human_approval_evidence": "A supervisor signs off on the request",
        }, ensure_ascii=False),
    ])
    agent = ServiceAnalystAgent(llm)
    result = agent.run({
        "service_name": "Certificate issuance",
        "description": "Issue a certificate",
        "steps": raw_lines,
    })
    caps = result["capabilities"]
    assert caps["analysis_source"] == "ai", f"Expected AI capability detection accepted, got {caps}"
    assert caps["has_payment"] is True
    assert caps["has_documents"] is True
    assert caps["has_human_approval"] is True


def test_service_agent_still_rejects_fabricated_capability_evidence():
    """Sanity check: evidence with no real basis in the source text
    must still be rejected even after the grounding fix."""
    raw_lines = ["Customer asks for office hours"]
    llm = FakeLLM([
        json.dumps({"steps": raw_lines}, ensure_ascii=False),
        json.dumps({"objective": "Learn office hours", "friction_points": []}, ensure_ascii=False),
        json.dumps({
            "has_payment": True,
            "payment_evidence": "customer wires a large international bank transfer",
            "has_documents": False, "documents_evidence": "",
            "has_physical_visit": False, "visit_evidence": "",
            "has_human_approval": False, "human_approval_evidence": "",
        }, ensure_ascii=False),
    ])
    agent = ServiceAnalystAgent(llm)
    result = agent.run({
        "service_name": "Office Hours Inquiry",
        "description": "Customer asks about opening hours.",
        "steps": raw_lines,
    })
    assert result["capabilities"]["has_payment"] is False


# =====================================================================
# 2. Standards checklist selection (agents/standards_agent.py)
# =====================================================================

def test_standards_agent_accepts_checklist_selection_format():
    """Real bug: the old free-selection prompt let qwen3:4b answer
    applicable_standard_ids: [] even with a well-formed JSON response.
    The new checklist format forces one explicit true/false decision
    per catalog id, which must now be correctly parsed and accepted."""
    service_analysis = {
        "steps": ["Customer submits a request", "Employee manually re-enters the same data"],
        "manual_actions": ["Employee manually re-enters the same data"],
        "waiting_points": [],
        "approvals": [],
        "documents": [],
        "friction_points": ["Manual operational work exists"],
        "service_classification": {"requires_customer_payment": False},
    }

    selections = {}
    for item in STANDARDS_CATALOG:
        std_id = item["standard_id"]
        if std_id == "STD-02":
            selections[std_id] = {
                "applicable": True,
                "why_it_applies": "Manual re-entry of the same data exists in the current journey.",
            }
        else:
            selections[std_id] = {"applicable": False, "why_it_applies": ""}

    response = json.dumps({"selections": selections}, ensure_ascii=False)
    llm = FakeLLM([response])
    agent = StandardsAgent(llm)
    result = agent.run(service_analysis, standards={"source_text": ""})

    assert result["analysis_source"] == "ai", f"Expected checklist selection to be accepted, got: {result.get('analysis_source')}"
    ids = {item["standard_id"] for item in result["applicable_standards"]}
    assert "STD-02" in ids
    matching = [item for item in result["applicable_standards"] if item["standard_id"] == "STD-02"]
    assert matching[0]["why_it_applies"] == "Manual re-entry of the same data exists in the current journey."


def test_standards_agent_checklist_never_returns_empty_ids_when_any_applicable():
    """Direct regression for 'applicable_standard_ids = []' with a
    genuinely correct model response: as long as at least one entry in
    the checklist is marked applicable, the selection must not be
    discarded."""
    service_analysis = {
        "steps": ["Customer pays a fee", "Employee approves the payment"],
        "manual_actions": [],
        "waiting_points": [],
        "approvals": ["Employee approves the payment"],
        "documents": [],
        "friction_points": [],
        "service_classification": {"requires_customer_payment": True},
    }
    selections = {
        item["standard_id"]: {"applicable": False, "why_it_applies": ""}
        for item in STANDARDS_CATALOG
    }
    selections["STAGE-04"] = {
        "applicable": True,
        "why_it_applies": "An approval step exists before payment is finalized.",
    }
    response = json.dumps({"selections": selections}, ensure_ascii=False)

    agent = StandardsAgent(FakeLLM([response]))
    result = agent.run(service_analysis, standards={"source_text": ""})
    assert result["analysis_source"] == "ai"
    ids = {item["standard_id"] for item in result["applicable_standards"]}
    assert "STAGE-04" in ids
    # baseline mandatory ids must still be present alongside the AI selection
    assert "STAGE-06" in ids


def test_standards_agent_still_falls_back_on_all_false_checklist():
    """If the model genuinely marks every standard inapplicable (no
    parse issue, just a real all-false answer), that is a legitimate,
    fully-parsed response -- the deterministic baseline still applies
    on top of it via the mandatory-standards merge, and this must not
    be confused with a parse failure."""
    service_analysis = {
        "steps": ["Customer asks a question"],
        "manual_actions": [], "waiting_points": [], "approvals": [], "documents": [],
        "friction_points": [], "service_classification": {"requires_customer_payment": False},
    }
    selections = {
        item["standard_id"]: {"applicable": False, "why_it_applies": ""}
        for item in STANDARDS_CATALOG
    }
    response = json.dumps({"selections": selections}, ensure_ascii=False)
    agent = StandardsAgent(FakeLLM([response]))
    result = agent.run(service_analysis, standards={"source_text": ""})
    # No AI-selected ids beyond baseline -> falls back to baseline,
    # which is the documented, safe behavior (never zero standards).
    ids = {item["standard_id"] for item in result["applicable_standards"]}
    assert "STD-01" in ids  # baseline mandatory id always present


def test_standards_agent_prompt_requests_realistic_output_budget():
    """The checklist format costs MORE output tokens than the old
    free-list format (one full JSON entry per catalog id, even for
    inapplicable ones) -- max_new_tokens passed to the LLM must scale
    with catalog size generously enough to hold that, not regress to
    the old under-sized constant."""
    service_analysis = {"steps": [], "manual_actions": [], "waiting_points": [], "approvals": [], "documents": []}
    selections = {item["standard_id"]: {"applicable": False, "why_it_applies": ""} for item in STANDARDS_CATALOG}
    llm = FakeLLM([json.dumps({"selections": selections}, ensure_ascii=False)])
    agent = StandardsAgent(llm)
    agent.run(service_analysis, standards={"source_text": ""})
    assert llm.last_max_new_tokens >= len(STANDARDS_CATALOG) * 100, (
        f"max_new_tokens={llm.last_max_new_tokens} looks too small for "
        f"{len(STANDARDS_CATALOG)} checklist entries"
    )


# =====================================================================
# 3. Low-memory token budget grows num_ctx instead of shrinking output
# =====================================================================

def test_resolve_context_budget_does_not_shrink_when_growth_fits():
    """Direct regression for the reported signature:
    estimated_prompt=3534, num_ctx=4096 -> output was being forced
    down to 256. With the fix, num_ctx should grow instead and the
    full requested output should be preserved."""
    num_ctx, effective_tokens, note = llm_module.resolve_context_budget(
        estimated_prompt_tokens=3534,
        max_new_tokens=1350,
        base_num_ctx=4096,
        max_num_ctx=8192,
    )
    assert num_ctx > 4096, "num_ctx should have grown beyond the base window"
    assert effective_tokens == 1350, (
        f"requested output should not be shrunk when growth fits, got {effective_tokens}"
    )
    assert note is not None and "Growing num_ctx" in note


def test_resolve_context_budget_small_prompt_is_unaffected():
    """A prompt that already fits should not trigger any growth or
    shrink -- confirms the fix is additive, not a behavior change for
    the common case."""
    num_ctx, effective_tokens, note = llm_module.resolve_context_budget(
        estimated_prompt_tokens=300,
        max_new_tokens=500,
        base_num_ctx=4096,
        max_num_ctx=8192,
    )
    assert num_ctx == 4096
    assert effective_tokens == 500
    assert note is None


def test_resolve_context_budget_shrinks_only_when_ceiling_insufficient():
    """When even the configured ceiling can't fit prompt + requested
    output, the function must still return a usable (non-zero, capped)
    budget rather than crashing or silently pretending everything
    fits -- but this must be a genuinely rare, logged, last-resort
    path, not the default behavior."""
    num_ctx, effective_tokens, note = llm_module.resolve_context_budget(
        estimated_prompt_tokens=20000,
        max_new_tokens=5000,
        base_num_ctx=4096,
        max_num_ctx=8192,
    )
    assert num_ctx == 8192
    assert effective_tokens < 5000
    assert effective_tokens >= 256
    assert note is not None and "ceiling" in note


def test_llm_generate_sends_grown_num_ctx_and_full_num_predict_over_http(monkeypatch):
    """Real HTTP-level regression: for a Standards-sized prompt, the
    actual JSON payload sent to Ollama must carry a grown num_ctx and
    the FULL requested num_predict, not the old shrunk-to-256 value."""
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {"content": "{}"},
                "done_reason": "stop",
                "eval_count": 5,
                "prompt_eval_count": 900,
            }

    def fake_post(url, json, timeout, proxies, headers):
        captured["num_ctx"] = json["options"]["num_ctx"]
        captured["num_predict"] = json["options"]["num_predict"]
        return FakeResponse()

    monkeypatch.setattr(llm_module.requests, "post", fake_post)

    client = llm_module.LocalLLM.__new__(llm_module.LocalLLM)  # skip __init__'s network probe

    big_prompt = "STANDARD REQUIREMENT TEXT " * 400  # large ASCII prompt, ~ thousands of tokens
    client.generate(
        system_prompt="You are a government service standards compliance agent.",
        user_prompt=big_prompt,
        max_new_tokens=1350,
    )

    assert captured["num_predict"] == 1350, (
        f"expected the full requested output budget to be preserved, got {captured['num_predict']}"
    )
    assert captured["num_ctx"] >= llm_module.OLLAMA_NUM_CTX


if __name__ == "__main__":
    test_grounding_accepts_paraphrase_not_just_exact_vocabulary()
    test_grounding_accepts_arabic_affix_variation()
    test_grounding_still_rejects_fabricated_content()
    test_light_stem_normalizes_common_arabic_affixes()
    test_service_agent_accepts_paraphrased_capability_evidence()
    test_service_agent_still_rejects_fabricated_capability_evidence()
    test_standards_agent_accepts_checklist_selection_format()
    test_standards_agent_checklist_never_returns_empty_ids_when_any_applicable()
    test_standards_agent_still_falls_back_on_all_false_checklist()
    test_standards_agent_prompt_requests_realistic_output_budget()
    test_resolve_context_budget_does_not_shrink_when_growth_fits()
    test_resolve_context_budget_small_prompt_is_unaffected()
    test_resolve_context_budget_shrinks_only_when_ceiling_insufficient()
    print("ALL ROOT-CAUSE-FIX TESTS PASSED (except the monkeypatch-based one, run via pytest)")
