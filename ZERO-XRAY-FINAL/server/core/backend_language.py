"""Small backend text helper for user-facing generated explanations only.

Enum values, API/database field names, identifiers, and technical IDs are never
translated. Missing Arabic text intentionally falls back to English.
"""
TEXT = {
    "monitor_unknown": {"en": "Unknown watch_metric '{metric}'; nothing to check.", "ar": "قيمة watch_metric غير معروفة '{metric}'؛ لا يوجد ما يمكن فحصه."},
    "monitor_no_predict": {"en": "No stored Predict result exists yet for this service.", "ar": "لا توجد نتيجة Predict محفوظة لهذه الخدمة حتى الآن."},
    "monitor_predict_empty": {"en": "Latest stored Predict result (id={id}) has no predictions.", "ar": "أحدث نتيجة Predict محفوظة (id={id}) لا تحتوي على predictions."},
    "monitor_predict_value": {"en": "Latest stored Predict result (id={id}) reports max confidence {value} against threshold {threshold}.", "ar": "أحدث نتيجة Predict محفوظة (id={id}) تسجل أعلى confidence بقيمة {value} مقارنة بالحد {threshold}."},
    "monitor_no_challenge": {"en": "No stored Challenge result exists yet for this service.", "ar": "لا توجد نتيجة Challenge محفوظة لهذه الخدمة حتى الآن."},
    "monitor_challenge_missing": {"en": "Vulnerability {target} did not recur in the latest stored Challenge (id={id}).", "ar": "لم تتكرر vulnerability {target} في أحدث Challenge محفوظ (id={id})."},
    "monitor_challenge_value": {"en": "Latest stored Challenge (id={id}) reports severity {value} for {target} against threshold {threshold}.", "ar": "أحدث Challenge محفوظ (id={id}) يسجل severity بقيمة {value} لـ {target} مقارنة بالحد {threshold}."},
    "prevent_explanation": {"en": "Watch {metric} for {scope}. If it reaches {threshold}, apply: {action}", "ar": "راقب {metric} للنطاق {scope}. إذا وصل إلى {threshold}، طبّق: {action}"},
    "prevent_no_exposure": {"en": "No exposure_before value available to derive a trigger threshold.", "ar": "لا توجد قيمة exposure_before متاحة لاشتقاق حد تشغيل."},
}


def normalize_lang(lang):
    return "ar" if str(lang or "en").lower() == "ar" else "en"


def text(key, lang="en", **values):
    lang = normalize_lang(lang)
    entry = TEXT.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    return template.format(**values)
