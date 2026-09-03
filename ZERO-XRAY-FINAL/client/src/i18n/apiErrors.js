// Centralized translation for backend error strings shown directly to the
// user (HTTPException `detail` text and ValueError messages surfaced as-is
// by the API). Single source of truth so every component that displays a
// caught request error does it the same way instead of each one keeping
// its own partial copy.
//
// SCOPE: this covers every FIXED (non-interpolated) English message raised
// by the customer/staff journey and Sandbox-execution paths --
// server/main.py's public + journey endpoints, server/core/runtime_store.py
// (edit_plan/approve_plan/pay/prepare_payment_assessment/start_execution/
// control_journey/create_journey/register_customer/issue_journey_capability),
// and server/core/integration_execution.py (IntegrationExecutionError).
// Verified against the backend source that none of these raise an
// f-string/interpolated message -- every one is a fixed literal, so this
// map can be complete rather than a best-effort guess. If the backend ever
// adds a new fixed message here without a translation, or raises a
// genuinely dynamic (data-dependent) message, translateApiError() falls
// back to the original English text -- the user still sees a real error,
// just not localized, which is strictly better than the old behavior of
// throwing the whole flow's error state away.
export const API_ERROR_TRANSLATIONS = {
  // main.py -- public/customer endpoints
  "Journey session is invalid or expired.": "انتهت صلاحية جلسة الرحلة أو أنها غير صالحة.",
  "Name and email are required.": "الاسم والبريد الإلكتروني مطلوبان.",
  "Published service not found.": "الخدمة المنشورة غير موجودة.",
  "Service Blueprint not found.": "مخطط الخدمة غير موجود.",
  "Service not found.": "الخدمة غير موجودة.",
  "Journey not found.": "الرحلة غير موجودة.",
  "Unknown journey action.": "إجراء غير معروف لهذه الرحلة.",
  "Live execution is disabled. Connect approved identity, payment and service adapters before enabling it.":
    "التنفيذ المباشر معطّل حالياً. يجب ربط موصلات الهوية والدفع والخدمة المعتمدة قبل تفعيله.",

  // core/runtime_store.py -- Blueprint lifecycle
  "Unsupported Blueprint status.": "حالة مخطط الخدمة غير مدعومة.",
  "Approve the Blueprint before publishing it.": "يجب اعتماد مخطط الخدمة قبل نشره.",

  // core/runtime_store.py -- customer/journey session
  "Customer session was not found.": "لم يتم العثور على جلسة المتعامل.",
  "No approved service Blueprint matches this request.": "لا يوجد مخطط خدمة معتمد يطابق هذا الطلب.",
  "Customer and service do not belong to the same tenant.": "المتعامل والخدمة لا ينتميان إلى نفس الجهة.",
  "Customer session TTL must be positive.": "مدة صلاحية جلسة المتعامل يجب أن تكون قيمة موجبة.",
  "Journey/customer session mismatch.": "عدم تطابق بين جلسة الرحلة وجلسة المتعامل.",

  // core/runtime_store.py -- plan editing
  "This plan cannot be edited in its current state.": "لا يمكن تعديل هذه الخطة في حالتها الحالية.",
  "Unsupported renewal duration.": "مدة التجديد غير مدعومة.",
  "Unsupported inquiry topic.": "موضوع الاستفسار غير مدعوم.",
  "Unsupported response channel.": "طريقة استلام الرد غير مدعومة.",
  "Choose at least one plan change.": "اختر تعديلاً واحداً على الأقل في الخطة.",

  // core/runtime_store.py -- approval / payment
  "This plan cannot be approved in its current state.": "لا يمكن اعتماد هذه الخطة في حالتها الحالية.",
  "Approve the final plan before the payment assessment.": "يجب اعتماد الخطة النهائية قبل تقييم الدفع.",
  "This service does not use a deferred payment assessment.": "هذه الخدمة لا تستخدم تقييم دفع مؤجّل.",
  "Journey was not found.": "لم يتم العثور على الرحلة.",
  "Approve the final plan before payment.": "يجب اعتماد الخطة النهائية قبل الدفع.",
  "Confirmed payment is required before execution.": "يلزم تأكيد الدفع قبل التنفيذ.",
  "Approved consent is required before execution.": "تلزم الموافقة المعتمدة قبل التنفيذ.",

  // core/runtime_store.py -- journey control
  "Unsupported journey control action.": "إجراء تحكم غير مدعوم لهذه الرحلة.",
  "Only a paused journey can be resumed.": "لا يمكن استئناف إلا رحلة متوقفة مؤقتاً.",

  // core/integration_execution.py -- Sandbox execution readiness
  "Service is not available for this tenant.": "الخدمة غير متاحة لهذه الجهة.",
  "A configured service integration is not available for this tenant.": "أحد تكاملات الخدمة المُعدّة غير متاح لهذه الجهة.",
  "A required service integration is not connected.": "أحد تكاملات الخدمة المطلوبة غير متصل.",
  "Integration is not assigned to this service.": "هذا التكامل غير مرتبط بهذه الخدمة.",
  "Integration is not CONNECTED for real-world execution.": "هذا التكامل ليس بحالة \"متصل\" اللازمة للتنفيذ الفعلي.",
  "Integration configuration is incomplete.": "إعدادات هذا التكامل غير مكتملة.",
  "Integration does not grant execution permission.": "هذا التكامل لا يمنح صلاحية التنفيذ.",
};

// message: the raw string caught from a request error (requestError.message
// or an Error thrown with the backend's `detail`/`state.message` text).
// lang: the active UI language ("ar" | "en").
// Returns the Arabic translation when lang is "ar" and a mapping exists;
// otherwise returns the original message unchanged -- never undefined,
// never empty, so a caller can always safely render the result.
export function translateApiError(message, lang) {
  if (!message) return message;
  if (lang !== "ar") return message;
  return API_ERROR_TRANSLATIONS[message] || message;
}
