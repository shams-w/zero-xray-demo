from core.json_utils import extract_json
from core.llm import ai_label


class DocumentAnalystAgent:

    def __init__(self, llm):
        self.llm = llm

    def run(self, standards_text):

        prompt = f"""
Analyze ONLY the government standards contained
in the document below.

Do not invent additional standards.
Do not use external standards.

GOVERNMENT STANDARDS DOCUMENT:

{standards_text}

Extract the standards into structured JSON.

Return exactly this structure:

{{
    "standards": [
        {{
            "standard_id": "",
            "title": "",
            "requirement": "",
            "principle": "",
            "measurable_criteria": [],
            "mandatory_conditions": [],
            "source_page": null
        }}
    ]
}}

If the document does not provide an ID,
create a neutral internal ID such as STD-001.

Return JSON only.
"""

        # MERGED FROM P1 (defensive restore + analysis_source
        # tagging). This agent has no meaningful deterministic
        # alternative (a keyword scan cannot reconstruct structured
        # standards from an arbitrary document), so there is no
        # template fallback to fall back to -- but callers should
        # still be able to tell whether a usable AI extraction
        # actually happened, and calling with no LLM configured must
        # not crash.
        if not self.llm:
            print(
                "[DOCUMENT] No LLM configured. "
                "Cannot extract standards from the document."
            )
            return {
                "standards": [],
                "analysis_source": "unavailable",
            }

        response = self.llm.generate(
            system_prompt=(
                "You are a government standards "
                "document intelligence agent. "
                "Your only source of truth is the "
                "provided document."
            ),
            user_prompt=prompt,
            max_new_tokens=1800,
        )

        result = extract_json(response)
        if isinstance(result, dict) and not result.get("parse_error"):
            result.setdefault("analysis_source", ai_label())
        elif isinstance(result, dict):
            result.setdefault("analysis_source", "unavailable")
            result.setdefault("standards", [])
        return result