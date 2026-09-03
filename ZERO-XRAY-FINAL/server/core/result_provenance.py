"""Safe provenance metadata for generated ZERO X-RAY results.

Stores only result-origin metadata. Never stores prompts, chain-of-thought,
raw model responses, tokens, or credentials.
"""
from datetime import datetime, timezone
from core.llm import OLLAMA_MODEL

ALLOWED_RESULT_SOURCES = {"AI", "DETERMINISTIC", "HYBRID", "FALLBACK"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_provenance(source, *, model_name=None, evidence_references=None,
                     fallback_reason=None, generated_at=None):
    normalized = str(source or "DETERMINISTIC").upper()
    if normalized not in ALLOWED_RESULT_SOURCES:
        normalized = "DETERMINISTIC"
    item = {
        "source": normalized,
        "generated_at": generated_at or now_iso(),
    }
    if model_name:
        item["model_name"] = str(model_name)
    refs = [str(v) for v in (evidence_references or []) if v not in (None, "")]
    if refs:
        item["evidence_references"] = refs
    if fallback_reason:
        item["fallback_reason"] = str(fallback_reason)
    return item


def provenance_for_mixed_result(*, llm_present, ai_used, evidence_references=None,
                                generated_at=None):
    if ai_used:
        return build_provenance(
            "HYBRID", model_name=OLLAMA_MODEL,
            evidence_references=evidence_references, generated_at=generated_at,
        )
    if llm_present:
        return build_provenance(
            "FALLBACK", evidence_references=evidence_references,
            fallback_reason="AI output was unavailable or invalid; deterministic fallback was used.",
            generated_at=generated_at,
        )
    return build_provenance(
        "DETERMINISTIC", evidence_references=evidence_references,
        generated_at=generated_at,
    )


def attach_analysis_provenance(result):
    """Attach safe top-level provenance to an analysis result, preserving all existing fields."""
    if not isinstance(result, dict) or "provenance" in result:
        return result
    sources = []
    refs = []
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"analysis_source", "explanation_source", "description_source"}:
                    sources.append(str(item).lower())
                elif key in {"source_reference", "reference_id", "standard_id"} and item:
                    refs.append(str(item))
                elif key not in {"ai_overall_reasoning"}:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(result)
    ai_used = any(v in {"ai", "mock_ai"} for v in sources)
    fallback_used = any(v in {"template", "fallback", "unavailable"} for v in sources)
    if ai_used and fallback_used:
        source = "HYBRID"
    elif ai_used:
        source = "AI"
    elif fallback_used:
        source = "FALLBACK"
    else:
        source = "DETERMINISTIC"
    result["provenance"] = build_provenance(
        source,
        model_name=OLLAMA_MODEL if ai_used else None,
        evidence_references=refs,
        fallback_reason=("AI output was unavailable or invalid; deterministic fallback was used." if source == "FALLBACK" else None),
        generated_at=result.get("generated_at"),
    )
    return result
