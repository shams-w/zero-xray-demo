"""Meaning-based (semantic) grounding check, without a heavy embedding
model dependency.

ROOT-CAUSE CONTEXT: agents/service_agent.py used to grade a candidate
AI-produced step/evidence phrase as "grounded" only if a meaningful
fraction of its own significant words appeared as an EXACT vocabulary
match somewhere in the raw source text (`word in source_lower`). Real
qwen3:4b output legitimately REWORDS the source instead of echoing its
exact vocabulary -- different verb conjugation, a synonym, an Arabic
word with a different attached prefix/suffix ("الموظف" vs "موظف"), or
English "uploading" vs source "upload" -- none of which changes the
meaning, but every one of which failed the old exact-string check and
sent a perfectly correct AI output to the deterministic fallback.

This module replaces the exact-vocabulary check with a grounding check
that tolerates that kind of paraphrase while still rejecting content
that has no real basis in the source text at all (the actual
anti-hallucination guarantee this exists for). It combines three
signals per significant word in the candidate text, in increasing
order of tolerance:

  1. Exact match against the source's own words.
  2. Light stemming (Arabic prefix/suffix stripping + normalization of
     hamza/alef/yeh variants; a minimal English suffix stripper) so
     the same root counts as a match regardless of conjugation/affix.
  3. A close fuzzy match (difflib) against the source's words, which
     tolerates minor spelling/conjugation differences without
     requiring a shared root, but is deliberately conservative (a high
     similarity cutoff) so unrelated words never match by accident.

No network calls, no model loading, no new dependency -- this has to
run inline on every agent call, including on a low-memory machine that
is already tight on resources running the LLM itself.
"""

import difflib
import re

_WORD_PATTERN = re.compile(r"[\w\u0600-\u06FF]{3,}")

_ARABIC_DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u0640]")

# Longest affixes first so e.g. "وال" strips as one unit instead of
# leaving a dangling "ال" pass unhandled.
_AR_PREFIXES = ("بال", "كال", "فال", "وال", "لل", "ال", "و", "ف", "ب", "ل", "ك")
_AR_SUFFIXES = ("تين", "ات", "ون", "ين", "ها", "هم", "كم", "نا", "ية", "ه", "ة", "ي", "ت")

_EN_SUFFIXES = ("ing", "edly", "ed", "es", "s")


def _normalize_arabic(word):
    word = _ARABIC_DIACRITICS.sub("", word)
    word = (
        word.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
    )
    return word


def light_stem(word):
    """Cheap, deterministic root-approximation. Not linguistically
    complete -- it only has to be good enough to stop conjugation/
    affixes from defeating a grounding check, not to do real
    lemmatization.

    ROOT-CAUSE FIX (real qwen3:4b Arabic run): this used to strip at
    most ONE prefix and ONE suffix per call. Real Arabic words
    routinely stack more than one affix layer at once (e.g. "وبالعنوان"
    = و + ب + ال + عنوان, or a word with both a attached conjunction
    AND a possessive suffix), so a single pass left a lot of
    "obviously the same word to a human reader" pairs not matching --
    exactly the kind of correct AI paraphrase that should be accepted.
    Strip iteratively (bounded, so this can't runaway on a short word)
    until no further affix applies."""
    word = str(word).lower().strip()
    if not word:
        return word
    if re.search(r"[\u0600-\u06FF]", word):
        word = _normalize_arabic(word)
        for _ in range(3):
            changed = False
            for suffix in _AR_SUFFIXES:
                if len(word) - len(suffix) >= 3 and word.endswith(suffix):
                    word = word[: -len(suffix)]
                    changed = True
                    break
            for prefix in _AR_PREFIXES:
                if len(word) - len(prefix) >= 3 and word.startswith(prefix):
                    word = word[len(prefix):]
                    changed = True
                    break
            if not changed:
                break
        return word
    for suffix in _EN_SUFFIXES:
        if len(word) - len(suffix) >= 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def significant_words(text):
    return [w for w in _WORD_PATTERN.findall(str(text or "").lower())]


def is_semantically_grounded(
    candidate_text,
    source_text,
    min_fraction=1 / 3,
    fuzzy_cutoff=0.8,
):
    """True if `candidate_text` is meaning-grounded in `source_text`:
    at least `min_fraction` of the candidate's own significant words
    correspond to real words in the source, either exactly, after
    light stemming, or via a conservative fuzzy match -- tolerating
    rewording/conjugation/affixes while still rejecting text that has
    no real relationship to the source at all.

    Returns True when the candidate has no significant (3+ char)
    words at all -- too short to judge either way, so it should not be
    penalized (mirrors the previous behaviour for very short phrases).
    """
    cand_words = significant_words(candidate_text)
    if not cand_words:
        return True

    source_words = significant_words(source_text)
    if not source_words:
        return False

    source_word_set = set(source_words)
    source_stem_set = {light_stem(w) for w in source_words}

    matches = 0
    for word in cand_words:
        if word in source_word_set:
            matches += 1
            continue
        if light_stem(word) in source_stem_set:
            matches += 1
            continue
        if difflib.get_close_matches(word, source_words, n=1, cutoff=fuzzy_cutoff):
            matches += 1

    required = max(1, len(cand_words) // 3) if min_fraction == 1 / 3 else max(
        1, int(len(cand_words) * min_fraction)
    )
    return matches >= required


def ungrounded_items(candidates, source_text, **kwargs):
    """Return the subset of `candidates` that fail
    `is_semantically_grounded` against `source_text`."""
    return [c for c in candidates if not is_semantically_grounded(c, source_text, **kwargs)]
