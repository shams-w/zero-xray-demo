import re
from copy import deepcopy


PROCEDURE_HEADINGS = {
    "إجراءات الخدمة",
    "اجراءات الخدمة",
    "خطوات الخدمة",
    "طريقة التقديم",
    "service steps",
    "service procedure",
    "process steps",
    "how to apply",
}

STOP_HEADINGS = {
    "الأسئلة الشائعة",
    "الاسئلة الشائعة",
    "الشروط والأحكام",
    "الشروط و الأحكام",
    "المساعدة والدعم",
    "ساعات العمل",
    "faq",
    "frequently asked questions",
    "terms and conditions",
    "help and support",
}

EXACT_NOISE = {
    "ابدأ الخدمة",
    "إبدأ الخدمة",
    "ابدا الخدمة",
    "ابدء الخدمة",
    "إظهار الميزات",
    "اظهار الميزات",
    "تقديم",
    "اضغط هنا",
    "تقييم الخدمة",
    "خيارات الاشتراك",
    "الرجاء الاختيار من الباقات التالية",
    "target audience",
    "required docs",
    "start service",
    "show features",
    "apply",
}

METADATA_HEADINGS = {
    "الجمهور المستهدف",
    "اسم الخدمة",
    "قنوات الخدمة",
    "قنوات تقديم الخدمة",
    "قنوات الدفع",
    "رسوم الخدمة",
    "مدة إنجاز الخدمة",
    "مدة إتمام الخدمة",
    "مدة تقديم الخدمة",
    "المستندات المطلوبة",
    "الوثائق المطلوبة",
    "أماكن استلام الخدمة",
    "طريقة الدفع",
    "مدة العقد",
    "التجديد التلقائي الاختياري",
    "المكتب الرئيسي",
}


def _clean_line(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-–—•")
    text = re.sub(r"^\s*(?:الخطوة\s*)?\d+[\s.)،:-]+", "", text, flags=re.IGNORECASE)
    return text.strip()


def _key(value):
    return _clean_line(value).lower().rstrip(":：")


def _is_noise(value):
    text = _clean_line(value)
    key = _key(text)
    if not text or key in EXACT_NOISE or key in METADATA_HEADINGS or key in PROCEDURE_HEADINGS:
        return True
    if re.fullmatch(r"\d+", text):
        return True
    if re.fullmatch(r"(?:aed|a|درهم|د\.?‏?إ\.?)", key, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"(?:aed\s*)?[\d,.]+(?:\s*(?:aed|a|درهم))?", key, flags=re.IGNORECASE):
        return True
    if re.search(r"معد[ّ]?ل\s+التقييم|\d+\s+من\s+\d+\s+مستخدم", key):
        return True
    if key.startswith("لمعرفة المزيد") or key.startswith("للاطلاع على الأسئلة"):
        return True
    return False


def _deduplicate(lines):
    result = []
    seen = set()
    for line in lines:
        cleaned = _clean_line(line)
        key = cleaned.casefold()
        if not cleaned or key in seen or _is_noise(cleaned):
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _extract_procedure(text):
    lines = [_clean_line(line) for line in str(text or "").splitlines()]
    start = None
    for index, line in enumerate(lines):
        if _key(line) in PROCEDURE_HEADINGS:
            start = index + 1
            break
    if start is None:
        return []

    extracted = []
    for line in lines[start:]:
        key = _key(line)
        if key in STOP_HEADINGS or key.startswith("لمعرفة المزيد"):
            break
        if key in METADATA_HEADINGS:
            break
        if not _is_noise(line):
            extracted.append(line)
    return _deduplicate(extracted)


def _input_quality(original_steps, normalized_steps, used_procedure):
    original_count = len([item for item in original_steps if _clean_line(item)])
    removed = max(0, original_count - len(normalized_steps))
    warnings = []
    if not normalized_steps:
        warnings.append("لم يتم العثور على خطوات خدمة واضحة؛ راجع البيانات قبل الاعتماد.")
    if removed:
        warnings.append(f"تم استبعاد {removed} سطرًا غير إجرائي من قائمة الخطوات.")
    return {
        "status": "REVIEW" if warnings else "READY",
        "source_steps": original_count,
        "normalized_steps": len(normalized_steps),
        "procedure_section_detected": used_procedure,
        "warnings": warnings,
    }


def normalize_service_input(service):
    """Return a conservative, reviewable service payload.

    Public service pages contain package cards, ratings, fees and navigation
    labels alongside the actual procedure. Those lines must never be treated as
    customer steps. If a labelled procedure section exists, it is the source of
    truth; otherwise the supplied steps are cleaned without inventing content.
    """

    normalized = deepcopy(service or {})
    original_steps = list(normalized.get("steps") or [])
    description = str(normalized.get("description") or "")
    procedure_steps = _extract_procedure(description)

    if procedure_steps:
        steps = procedure_steps
    else:
        steps = _deduplicate(original_steps)

    normalized["service_name"] = _clean_line(normalized.get("service_name"))
    normalized["description"] = description.strip()
    normalized["steps"] = steps
    for field in (
        "documents",
        "actors",
        "approvals",
        "waiting_times",
        "manual_actions",
        "digital_actions",
        "dependencies",
    ):
        normalized[field] = _deduplicate(normalized.get(field) or [])
    normalized["input_quality"] = _input_quality(
        original_steps,
        steps,
        bool(procedure_steps),
    )
    return normalized
