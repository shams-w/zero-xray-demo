const PROCEDURE_HEADINGS = new Set([
  "إجراءات الخدمة",
  "اجراءات الخدمة",
  "خطوات الخدمة",
  "service steps",
  "service procedure",
  "process steps",
  "how to apply",
]);

const STOP_HEADINGS = new Set([
  "الأسئلة الشائعة",
  "الاسئلة الشائعة",
  "الشروط والأحكام",
  "الشروط و الأحكام",
  "المساعدة والدعم",
  "faq",
  "terms and conditions",
]);

const NOISE = new Set([
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
  "start service",
  "show features",
]);

function cleanLine(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .replace(/^\s*(?:الخطوة\s*)?\d+[\s.)،:-]+/i, "")
    .replace(/^[\s•–—-]+|[\s•–—-]+$/g, "")
    .trim();
}

function key(value) {
  return cleanLine(value).toLowerCase().replace(/[:：]$/, "");
}

function isNoise(value) {
  const text = cleanLine(value);
  const normalized = key(text);
  return !text
    || NOISE.has(normalized)
    || PROCEDURE_HEADINGS.has(normalized)
    || /^\d+$/.test(text)
    || /^(?:aed|a|درهم|د\.?إ\.?)$/i.test(normalized)
    || /معد[ّ]?ل\s+التقييم|\d+\s+من\s+\d+\s+مستخدم/.test(normalized)
    || normalized.startsWith("لمعرفة المزيد")
    || normalized.startsWith("للاطلاع على الأسئلة");
}

function unique(lines) {
  const seen = new Set();
  return lines.filter((line) => {
    const normalized = key(line);
    if (!normalized || seen.has(normalized) || isNoise(line)) return false;
    seen.add(normalized);
    return true;
  });
}

function looksLikeStep(value) {
  const text = cleanLine(value);

  return /^(العميل|المتعامل|المستخدم|مقدم الطلب|الموظف|النظام|تسجيل|إنشاء|اختيار|إدخال|تعبئة|إرفاق|رفع|دفع|سداد|استلام|إرسال|مراجعة|تقديم|زيارة|customer|applicant|employee|system|register|login|select|enter|upload|attach|pay|receive|submit|review)/i.test(
    text
  );
}

export function deriveJourneyFromText(rawText, fallbackName = "") {
  const originalText = String(rawText || "").trim();

  // يفصل الخطوات المكتوبة بهذا الشكل:
  // 1. الخطوة أو 2- الخطوة
  const preparedText = originalText.replace(
    /\s+(?=\d+\s*[.)-]\s*)/g,
    "\n"
  );

  const lines = preparedText
    .split(/\r?\n/)
    .map(cleanLine)
    .filter(Boolean);

  const headingIndex = lines.findIndex((line) =>
    PROCEDURE_HEADINGS.has(key(line))
  );

  const meaningful = lines.filter((line) =>
    !isNoise(line)
  );

  let serviceName = fallbackName;
  let steps = [];

  // أول سطر قصير وغير إجرائي غالبًا يكون اسم الخدمة.
  const possibleTitle = meaningful.find(
    (line, index) =>
      index < 3 &&
      line.length <= 150 &&
      !looksLikeStep(line)
  );

  if (possibleTitle) {
    serviceName = possibleTitle;
  }

  // لو النص يحتوي على عنوان "إجراءات الخدمة".
  if (headingIndex >= 0) {
    for (const line of lines.slice(headingIndex + 1)) {
      const normalized = key(line);

      if (
        STOP_HEADINGS.has(normalized) ||
        normalized.startsWith("لمعرفة المزيد")
      ) {
        break;
      }

      if (!isNoise(line)) {
        steps.push(line);
      }
    }
  } else {
    // No explicit procedure heading: only keep lines that clearly look
    // like actions. Public service pages contain package names, prices,
    // benefits and marketing copy; those are service facts, not journey
    // steps, and must never inflate the Current Journey count.
    steps = meaningful.filter(
      (line) =>
        line !== serviceName &&
        looksLikeStep(line)
    );
  }

  return {
    serviceName,
    description: originalText,
    steps: unique(steps),
  };
}