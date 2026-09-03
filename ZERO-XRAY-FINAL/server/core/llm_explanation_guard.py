"""Shared, additive guard against generic/placeholder/empty LLM
responses being mistaken for a genuine explanation.

Used by Predict/Simulate/Challenge/Evolve/Prevent's own
`_validate_llm_explanation`/`_validate_llm_description` methods as one
extra, additive check -- it does not replace their existing
anti-hallucination number checks, and it changes nothing about any
deterministic calculation, confidence, severity, threshold, exposure
value, ranking, or ID anywhere in the codebase. It only decides
whether a candidate LLM string is substantive enough to be labeled
`explanation_source`/`description_source` = "ai"; anything rejected
here falls back to the caller's own already-existing deterministic
template, with the source correctly recorded as "template".

Added after a real observed case: a test/mock AI backend
(tools/mock_ollama_server.py) that doesn't recognize a caller's system
prompt returns a generic `{"note": "MOCK_AI: no specific response
template matched this caller."}` placeholder. That placeholder
contains no numbers, so a validator that only checks "did the LLM
invent a new number" trivially accepts it. This guard adds the
missing check: is this text a real, on-topic explanation at all, or a
generic non-answer?
"""

import json
import re

# Known placeholder/non-answer substrings, matched case-insensitively.
# Deliberately generic phrases an LLM (mock or real) uses when it has
# nothing genuine to say, never phrases that could appear inside a
# real explanation of a government-service finding.
_PLACEHOLDER_MARKERS = (
    "no specific response template matched",
    "no template matched",
    "not implemented",
    "no response available",
    "unable to generate",
    "todo:",
)

# A real explanation of a finding is always more than a few characters
# -- this rejects empty/near-empty strings without needing a marker
# match.
_MIN_EXPLANATION_LENGTH = 8


def is_placeholder_or_generic(text):
    """Returns True if `text` looks like a generic/placeholder/empty
    non-answer rather than a real, on-topic explanation. Callers
    should treat True as "fall back to the deterministic template",
    exactly like any other validation failure they already handle."""
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < _MIN_EXPLANATION_LENGTH:
        return True
    lowered = stripped.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in lowered:
            return True
    return False


# =====================================================================
# Raw Ollama prompt/JSON leakage guard (root-cause fix)
# =====================================================================
# Every Future Engine narration call (Predict/Simulate/Challenge/
# Evolve/Prevent) sends a system_prompt telling the model to "rephrase"
# an already-computed result -- a misbehaving or confused model
# response can echo pieces of that internal request back instead of
# actually answering it (e.g. `{"task": "Rephrase an already-computed
# simulation result...", "constraints": [...]}` or a plain-text prompt
# echo containing "Do not invent..."). None of the existing per-agent
# validators reject this: it isn't empty, it isn't a known placeholder
# marker, and a prompt-echo about a *simulation result* typically
# contains no digits at all, so the "did it invent a new number"
# check trivially passes it. This never reaches a real number
# fabrication -- it reaches the UI as literal internal-prompt JSON.
#
# Quoted-key patterns (only ever appear in JSON/prompt structure, never
# in natural prose about a government-service finding).
_INSTRUCTION_KEY_PATTERN = re.compile(
    r'["\'](?:task|constraints|required_output)["\']\s*:', re.IGNORECASE
)
# Natural-language instruction/prompt-echo phrases -- the exact
# wording every system_prompt/user_prompt in this codebase uses
# ("Rephrase an already-computed ...", "Do not invent any new ...",
# "Do not add any new ...", "Write one clear sentence/paragraph
# summarizing this/this change ..."). Not phrases a genuine finding
# explanation would ever use.
#
# ROOT-CAUSE ADDITION (placeholder-leakage audit): a real observed
# Challenge result showed "One clear sentence summarizing the
# vulnerability finding" -- the model paraphrased the user_prompt's
# own closing instruction line ("Write one clear sentence summarizing
# this. Do not add new numbers.") in its own words instead of
# answering it. The prior marker set ("rephrase", "do not invent",
# "do not add any new"/"do not add new") only matched the SYSTEM
# prompt's wording; it missed this paraphrase of the USER prompt's
# own "Write one clear sentence/paragraph summarizing ..." instruction
# line, which every one of Predict/Simulate/Challenge/Evolve/Prevent's
# narration prompts ends with (see each agent's own _generate_
# explanation/_generate_description). These phrases describe the
# INSTRUCTION ITSELF ("a sentence/paragraph that summarizes
# something"), never a real finding -- a genuine explanation states
# facts about the finding, it never describes itself as "summarizing".
_INSTRUCTION_PHRASE_MARKERS = (
    "rephrase",
    "do not invent",
    "do not add any new",
    "do not add new",
    "do not add new numbers",
    "do not add new facts",
    "clear sentence",
    "clear paragraph",
    "sentence summarizing",
    "paragraph summarizing",
    "summarizing this",
    "summarizing the",
)


def _looks_like_prompt_or_instruction_leak(text):
    if _INSTRUCTION_KEY_PATTERN.search(text):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _INSTRUCTION_PHRASE_MARKERS)


def extract_clean_explanation(raw_text):
    """Root-cause fix for raw Ollama prompt/JSON leakage. Given the RAW
    text an LLM call returned, decide whether it is safe to treat as a
    candidate natural-language explanation, unwrapping a genuine
    `{"output": "..."}` envelope if present.

    Returns the cleaned candidate string to pass on to the caller's
    OWN existing `_validate_llm_explanation`/`_validate_llm_description`
    (unchanged, still runs on top of this), or None to mean REJECT
    outright -- the caller must fall back to its deterministic
    template exactly like any other validation failure.

    Rules (in order):
      1. Empty/whitespace-only -> reject.
      2. A JSON object (parses as one) ->
         - a real, non-empty string "output" field -> unwrap it and
           re-check THAT string for a leaked instruction/prompt before
           trusting it;
         - any other JSON shape (the request itself, an internal
           instruction object, no usable "output") -> reject; a raw
           request/response envelope must never partially pass through.
      3. Plain text containing a JSON-key-shaped instruction marker
         (`"task":`, `"constraints":`, `"required_output":`) or a
         literal prompt/instruction phrase ("Rephrase...",
         "Do not invent...", "Do not add any new...", "...clear
         sentence/paragraph summarizing...") -> reject.
      4. Otherwise -> the text is returned unchanged (still subject to
         the caller's own existing checks).

    Never invents text: it only passes through the model's own words
    unchanged, extracts an already-stated "output" value unchanged, or
    rejects.
    """
    if not raw_text:
        return None
    text = str(raw_text).strip()
    if not text:
        return None

    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None  # looked like JSON, didn't parse -- malformed/suspicious, reject
        if not isinstance(parsed, dict):
            return None
        output_value = parsed.get("output")
        if isinstance(output_value, str) and output_value.strip():
            inner = output_value.strip()
            if _looks_like_prompt_or_instruction_leak(inner):
                return None
            return inner
        return None  # any other JSON shape -- never partially trusted

    if _looks_like_prompt_or_instruction_leak(text):
        return None

    return text
