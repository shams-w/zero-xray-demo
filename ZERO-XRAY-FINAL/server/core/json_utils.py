import ast
import json
import re
from typing import Any


def _clean_json_text(text: str) -> str:
    """Normalize common small-model JSON formatting mistakes safely."""
    text = str(text or "").strip()

    # Remove Qwen-style reasoning blocks if a backend/version emits one even
    # when thinking was disabled (think:false), plus ordinary markdown fences.
    #
    # ROOT-CAUSE FIX: observed directly against Ollama 0.32.15 + qwen3:4b
    # with think:false explicitly sent -- the model still reasons at
    # length, but emits ONLY the closing "</think>" tag right before the
    # real answer, with NO matching opening "<think>" tag anywhere in the
    # response. The paired regex below (<think>...</think>) never matches
    # in that case, so hundreds of tokens of reasoning prose were left in
    # front of the actual JSON, guaranteeing every downstream json.loads()
    # (and even the raw_decode/ast.literal_eval fallbacks further down in
    # this file) fails and every agent silently drops to its deterministic
    # "template" baseline -- with no exception raised anywhere to explain
    # why. Handle the unpaired case first: if a closing tag exists at all,
    # keep only what follows the LAST one, regardless of whether an
    # opening tag was ever present. This also correctly handles the
    # well-formed <think>...</think> case (a prefix ending in the last
    # </think> still includes any opening tag, which is discarded too).
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1].strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    # Smart quotes copied/generated around JSON keys/values are invalid JSON.
    text = text.translate(str.maketrans({
        "“": '"', "”": '"', "„": '"',
        "‘": "'", "’": "'",
    }))

    # Trailing commas before a closing object/array are a frequent harmless
    # small-model error and can be repaired deterministically.
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text.strip()


def extract_json(value: Any):
    if isinstance(value, (dict, list)):
        return value

    if value is None:
        return {"parse_error": True, "raw_response": ""}

    text = _clean_json_text(str(value))

    # First: strict JSON, which is the expected path with Ollama format=json.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Second/third: locate the first plausible outer JSON object/array.
    # IMPORTANT: try strict JSON *and then* Python-literal parsing at each
    # opening delimiter before moving on to a nested delimiter. Otherwise a
    # response such as "{'steps': [1, 2]}" can incorrectly return only the
    # nested [1, 2] array after strict JSON fails on the outer single quotes.
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "{[":
            continue
        candidate = text[index:].strip()
        try:
            result, _ = decoder.raw_decode(candidate)
            return result
        except json.JSONDecodeError:
            pass

        # Tolerate Python-style dict/list output (single quotes, True/False)
        # without eval(). ast.literal_eval only accepts Python literals.
        try:
            result = ast.literal_eval(candidate)
            if isinstance(result, (dict, list)):
                return result
        except (ValueError, SyntaxError):
            continue

    return {"parse_error": True, "raw_response": text}


def has_parse_error(result):
    return isinstance(result, dict) and result.get("parse_error") is True


# =====================================================================
# ROOT-CAUSE FIX: truncation salvage
# =====================================================================
# Real Ollama 0.32.15 + qwen3:4b runs (not the mock server) showed a
# recurring failure signature across the Service / Standards / Gaps /
# Journey agents: the model produces genuinely correct JSON content but
# is cut off before the final closing brackets because the requested
# output ran up against num_predict/context budget on a small local
# model. `json.loads` (and the raw_decode/ast.literal_eval fallbacks
# above) reject the WHOLE response in that case, even though every
# object up to the cut point is completely well-formed -- so a real,
# usable 4-out-of-5 gaps response was being thrown away entirely and
# replaced by the deterministic baseline. This salvage pass only
# triggers after every strict-parse strategy above has already failed;
# it never changes behavior for a response that parses cleanly.
def _salvage_truncated_json(text: str):
    """Best-effort recovery of a JSON object/array that was cut off
    mid-stream. Walks the text tracking bracket depth (correctly
    skipping over string contents so a brace/bracket inside a quoted
    value is never mistaken for structure), remembers the last point
    at which a value was fully written (right after a top-level comma
    or a closing '}'/']' at depth > 0), truncates there, closes every
    still-open bracket in the correct order, and tries to parse that.
    Returns None if there is nothing safely salvageable."""
    stack = []
    in_string = False
    escape = False
    last_safe_index = None
    last_safe_stack = None

    for index, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append(ch)
            continue
        if ch in "}]":
            if stack:
                stack.pop()
            if stack:
                last_safe_index = index
                last_safe_stack = list(stack)
            continue
        if ch == "," and stack:
            last_safe_index = index
            last_safe_stack = list(stack)

    if not stack:
        # Already balanced -- a real parse failure unrelated to
        # truncation (e.g. genuinely malformed JSON), not this
        # function's job to fix.
        return None
    if last_safe_index is None or not last_safe_stack:
        return None

    prefix = text[: last_safe_index + 1].rstrip()
    if prefix.endswith(","):
        prefix = prefix[:-1]

    closers = {"{": "}", "[": "]"}
    repaired = prefix + "".join(closers[opener] for opener in reversed(last_safe_stack))

    try:
        candidate = json.loads(repaired)
    except json.JSONDecodeError:
        return None

    if isinstance(candidate, (dict, list)):
        return candidate
    return None


def extract_json_with_salvage(value: Any):
    """Same contract as extract_json(), but if the response is not
    already valid JSON, first tries to salvage a truncated top-level
    object/array (see _salvage_truncated_json) BEFORE falling back to
    extract_json()'s own nested-delimiter search.

    Ordering matters here: extract_json()'s nested-delimiter fallback
    happily returns the FIRST inner object it can parse (e.g. just the
    first element of a "gaps" array, when the array itself never
    closes) -- that's a plausible-looking dict, not a parse_error, so
    a naive "salvage only after has_parse_error()" check never even
    attempts to recover the actual top-level object the caller wanted
    (the whole {"gaps": [...]} envelope). Trying the top-level salvage
    first ensures a truncated response is completed as originally
    shaped instead of silently narrowing to whichever inner fragment
    happened to parse."""
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {"parse_error": True, "raw_response": ""}

    text = _clean_json_text(str(value))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    salvaged = _salvage_truncated_json(text)
    if salvaged is not None:
        return salvaged

    return extract_json(value)


def match_known_id(raw_value, allowed_ids):
    """Match a model-produced id string against a known set of valid
    ids, tolerating the common small-model habit of echoing the id
    together with its title/label (e.g. "STD-01 - Outcome Before
    Procedure" or "STD-01: ...") instead of the bare id alone. Exact
    membership is tried first; if that fails, every allowed id is
    checked as a case-insensitive substring/prefix of the raw value.
    Returns the canonical allowed id, or None if nothing matches."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None

    if text in allowed_ids:
        return text

    upper_text = text.upper()
    for allowed in allowed_ids:
        if allowed.upper() == upper_text:
            return allowed

    # Substring match: handles "STD-01 - Outcome Before Procedure",
    # "STD-01)", "(STD-01)", "id: STD-01", etc. Longest ids are
    # checked first so e.g. "STAGE-01" can't accidentally get matched
    # by a shorter, unrelated prefix.
    for allowed in sorted(allowed_ids, key=len, reverse=True):
        if allowed.upper() in upper_text:
            return allowed

    return None
