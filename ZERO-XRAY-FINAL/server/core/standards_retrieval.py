import re


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\-\u0600-\u06ff]+")


def _tokens(value):
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(str(value))
        if len(token) > 2
    }


def _chunks(text):
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks = []
    for index, paragraph in enumerate(paragraphs, start=1):
        page_match = re.search(r"\[PAGE\s+(\d+)\]", paragraph, flags=re.IGNORECASE)
        chunks.append({
            "evidence_id": f"GUIDE-{index:03d}",
            "source_location": (
                f"Page {page_match.group(1)}" if page_match else f"Text section {index}"
            ),
            "text": paragraph,
        })
    return chunks


def retrieve_standard_evidence(standards_text, query, limit=6):
    """Retrieve reviewable guide passages without inventing a requirement."""

    if not standards_text or not str(standards_text).strip():
        return []

    query_tokens = _tokens(query)
    ranked = []
    for chunk in _chunks(str(standards_text)):
        chunk_tokens = _tokens(chunk["text"])
        overlap = len(query_tokens.intersection(chunk_tokens))
        coverage = overlap / max(1, min(len(query_tokens), 25))
        standards_bonus = 0.08 if re.search(
            r"customer|assistant|payment|approval|exception|متعامل|مساعد|دفع|موافقة|استثناء",
            chunk["text"],
            flags=re.IGNORECASE,
        ) else 0
        score = round(min(1, coverage + standards_bonus), 4)
        if score > 0:
            ranked.append({**chunk, "score": score})

    ranked.sort(key=lambda item: (-item["score"], item["evidence_id"]))
    if not ranked:
        ranked = [{**item, "score": 0} for item in _chunks(str(standards_text))[:limit]]
    return ranked[: max(1, int(limit))]
