from core.result_provenance import build_provenance, attach_analysis_provenance
from agents.prevent_agent import PreventAgent
from agents.monitoring_agent import MonitoringAgent


def test_provenance_only_allows_supported_sources_and_safe_fields():
    item = build_provenance("AI", model_name="qwen3:4b", evidence_references=["AN-1"], generated_at="2026-01-01T00:00:00+00:00")
    assert item == {
        "source": "AI",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "model_name": "qwen3:4b",
        "evidence_references": ["AN-1"],
    }
    assert "prompt" not in item and "reasoning" not in item and "token" not in item


def test_analysis_provenance_marks_hybrid_without_copying_reasoning():
    result = {
        "service_analysis": {"analysis_source": "ai"},
        "future_journey": {"analysis_source": "template", "source_reference": "SRC-1"},
        "ai_overall_reasoning": "existing visible rationale",
    }
    out = attach_analysis_provenance(result)
    assert out["provenance"]["source"] == "HYBRID"
    assert out["provenance"]["evidence_references"] == ["SRC-1"]
    assert "reasoning" not in out["provenance"]


def test_arabic_prevent_template_keeps_technical_values_untranslated():
    agent = PreventAgent(llm=None, lang="ar")
    text = agent._template_explanation("prediction_confidence", "SERVICE-1", 0.8, "KEEP_STATUS")
    assert "راقب" in text
    assert "prediction_confidence" in text
    assert "SERVICE-1" in text
    assert "KEEP_STATUS" in text


def test_monitoring_arabic_and_english_fallback_text():
    ar = MonitoringAgent(lang="ar").check_trigger({"watch_metric": "UNKNOWN_ENUM"}, "S1", "T1", None, None)
    en = MonitoringAgent(lang="xx").check_trigger({"watch_metric": "UNKNOWN_ENUM"}, "S1", "T1", None, None)
    assert "غير معروفة" in ar["evidence"]
    assert "UNKNOWN_ENUM" in ar["evidence"]
    assert en["evidence"].startswith("Unknown watch_metric")
