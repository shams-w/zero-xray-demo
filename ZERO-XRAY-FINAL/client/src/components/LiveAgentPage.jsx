import { useEffect, useRef, useState } from "react";
import {
  approveJourneyPlan,
  controlJourney,
  createJourney,
  editJourneyPlan,
  executeJourney,
  getJourneyEventsUrl,
  payJourney,
  prepareJourneyPaymentAssessment,
  registerSandboxCustomer,
} from "../api";
import { useLanguage } from "../i18n/useLanguage";
import { translateApiError } from "../i18n/apiErrors";
import PlanOptionsEditor from "./PlanOptionsEditor";


const COPY = {
  en: {
    back: "Back to Blueprint",
    badge: "LIVE AGENT · SANDBOX",
    title: "Experience the redesigned service",
    subtitle: "The same approved Blueprint now becomes an agent-led customer journey.",
    customerJourney: "Customer journey",
    agentJourney: "Agent journey",
    customerTitle: "A zero-step customer experience",
    customerSubtitle: "The customer keeps control of identity, choices, approval and payment. The agent handles the administrative work.",
    customerStepsPaid: ["UAE PASS", "Review", "Payment", "Done"],
    customerStepsNoPayment: ["UAE PASS", "Review", "Done"],
    planKicker: "PLAN",
    readyForConsent: "READY FOR CONSENT",
    securePaymentKicker: "SECURE PAYMENT · SANDBOX",
    agentExecutionKicker: "AGENT EXECUTION",
    outcomeDeliveredKicker: "OUTCOME DELIVERED",
    emxCheckpointKicker: "EMX · PHYSICAL CHECKPOINT",
    licenceCheckpointKicker: "LICENCE · APPROVAL CHECKPOINT",
    quoteReadyKicker: "EMX · QUOTE READY",
    stepsPaid: ["Sign in", "Plan", "Payment", "Execution"],
    stepsNoPayment: ["Sign in", "Plan", "Execution"],
    stepsShipment: ["Sign in", "Plan", "Prepare", "Weigh & quote", "Payment", "Tracking"],
    stepsLicence: ["Sign in", "Plan", "Approval & assessment", "Bank transfer", "Activation"],
    identityKicker: "DIGITAL IDENTITY · SANDBOX",
    registerTitle: "Continue with UAE PASS",
    registerText: "Authenticate once. The agent retrieves only the approved information required for this service.",
    identityNote: "Sandbox simulation only — no real UAE PASS account or personal data is used.",
    signInUaePass: "Sign in with UAE PASS",
    documentsLoadingTitle: "Retrieving your documents securely...",
    documentsLoadingText: "Please wait while the AI Agent retrieves and verifies the required documents using UAE PASS.",
    name: "Full name",
    email: "Email address",
    continue: "Continue securely",
    customerReviewTitle: "Review your service",
    customerReviewText: "Only the service name and confirmed amount are shown. Approve the plan or change the available choices.",
    service: "Service",
    amount: "Amount",
    noFee: "No fee",
    changeChoices: "Change choices",
    approveContinue: "Approve and continue",
    approveComplete: "Approve and complete",
    planTitle: "Your editable execution plan",
    planTextPaid: "Review exactly what the agent will do before payment and execution.",
    planTextAction: "Review exactly what the agent will submit or execute before any binding action.",
    recommended: "Agent recommendation",
    actions: "Planned agent actions",
    fee: "Fee",
    sla: "Expected timing",
    integrations: "Execution connections",
    protected: "Human-protected controls",
    edit: "Edit plan",
    approve: "Approve this plan",
    approveSubmission: "Approve case submission",
    editTitle: "Tell the agent what to change",
    editPlaceholderPaid: "For example: use the lowest-cost package and disable auto-renewal",
    editPlaceholderCase: "For example: correct the incident date or change the requested resolution",
    editPlaceholderAction: "For example: change the option or requested timing",
    applyEdit: "Rebuild plan",
    cancelEdit: "Cancel",
    paymentTitle: "Authorize Sandbox payment",
    paymentText: "The approved plan is locked. This screen simulates a secure government payment confirmation.",
    beneficiary: "Service provider in the approved Blueprint",
    unknownFee: "Fee confirmation required before payment",
    journeyType: "Journey type",
    noPayment: "No customer payment is required",
    feeNeedsReview: "Fee requirement needs Blueprint review",
    paymentApprove: "I approve the shown payment and beneficiary",
    pay: "Complete Sandbox payment",
    customerPaymentTitle: "Confirm payment",
    customerPaymentText: "Review the service and amount, then authorize the secure Sandbox payment.",
    customerPaymentConsent: "I approve this service and the amount shown.",
    customerProcessingTitle: "Your request is being completed",
    customerProcessingText: "No further action is required. The agent is completing the approved work in the background.",
    customerSuccessTitle: "Everything is complete",
    customerSuccessPaid: "Payment was successful and the service outcome is ready.",
    customerSuccessNoPayment: "Your inquiry or request is complete. No payment was required.",
    receipt: "Reference",
    deferredPlanText: "Review what the agent completes before the service-specific assessment and payment checkpoint.",
    shipmentHandoffTitle: "The agent has prepared the shipment for EMX pickup",
    shipmentHandoffText: "Data, customs documents, booking and the provisional label are ready. The physical item must now be handed to the courier so EMX can verify weight and dimensions before issuing the final price.",
    shipmentHandoffButton: "Simulate pickup, weighing and EMX quote",
    licenceAssessmentTitle: "Application prepared, submitted and approved for fee assessment",
    licenceAssessmentText: "The agent retrieved the company documents and followed the application through approval. The connected fee assessment now applies 10% of annual postal-activity sales with AED 100,000 as the minimum payable upfront.",
    licenceAssessmentButton: "Simulate approval and fee assessment",
    completedBeforePayment: "Completed before payment",
    quoteTitle: "EMX confirmed the Sandbox quote after weighing",
    quoteText: "The amount is now available for customer authorization. In production it comes directly from EMX after physical verification.",
    continuePayment: "Review and pay the confirmed quote",
    bankTransferTitle: "Authorize Sandbox bank transfer",
    bankTransferText: "The approved fee assessment is locked. This screen simulates the required bank transfer and receipt confirmation.",
    bankTransferApprove: "I approve the assessed annual fee and bank transfer",
    bankTransferPay: "Confirm Sandbox bank transfer",
    executingTitle: "The agent is executing your service",
    executingText: "Every action is verified and written to the case audit trail.",
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    case: "Case",
    planVersion: "Approved plan version",
    paymentReference: "Payment reference",
    consentReference: "Consent reference",
    handoff: "Request a human",
    cancel: "Cancel journey",
    successTitle: "Service completed successfully",
    successText: "The outcome is ready and the full journey remains traceable from the same place.",
    result: "Outcome",
    reference: "Journey reference",
    timing: "Follow-up timing",
    objection: "Ask, correct or object",
    objectionAvailable: "Available in the same journey",
    newJourney: "Return to Blueprint",

    caseIntakeKicker: "AGENT UNDERSTANDING",
    complaintIntakeTitle: "Tell me what happened — in your own words",
    inquiryIntakeTitle: "Ask your question naturally",
    complaintIntakeText: "No forms or priority selection. Write naturally — including Arabic dialects — and the agent will understand the issue, classify it, assess urgency, and try to resolve it first.",
    inquiryIntakeText: "Ask naturally — including Arabic dialects. The agent identifies what you need, prepares the right answer or action, and only asks for clarification when it is genuinely needed.",
    caseMessageLabel: "Your message",
    complaintPlaceholder: "Example: My shipment still hasn't arrived, it's been a week and nobody got back to me.",
    inquiryPlaceholder: "Example: I want to know what documents I need and how much the service costs.",
    caseReferenceLabel: "Reference number (optional)",
    caseReferencePlaceholder: "Shipment, application or case number",
    understandAndSolve: "Understand & try to solve",
    understandInquiry: "Understand & answer inquiry",
    agentUnderstanding: "The agent is understanding your message...",
    dialectNote: "Natural-language understanding supports formal Arabic, common Arabic dialects and English phrasing.",

    detectedIssue: "What I understood",
    detectedPriority: "Priority",
    detectedReason: "Why",
    proposedResolution: "Agent action",
    normalPriority: "NORMAL",
    mediumPriority: "MEDIUM",
    highPriority: "HIGH",
    continueResolution: "Continue with this resolution",
    continueEscalation: "Prepare smart escalation",
    continueInquiry: "Continue with the answer/action",
    autoResolveBadge: "RESOLUTION FIRST",
    escalationBadge: "SMART ESCALATION",
    inquiryBadge: "INQUIRY UNDERSTOOD",
    resolvePossible: "I can try to handle this without creating a manual complaint.",
    escalationNeeded: "This needs specialist intervention. I prepared the classification, priority and routing automatically.",
    inquiryUnderstood: "I understood what you need and prepared the next best action.",
    changeMessage: "Edit message",
    proposed: "PROPOSED",
    simulated: "SIMULATED",

    linkedOrdersFound: "I found two recent shipments linked to your UAE PASS account.",
    chooseLinkedOrder: "Which shipment do you mean?",
    orderStatus: "Status",
    orderDate: "Order date",
    selectOrder: "Select this shipment",
    checkingShipment: "Checking the latest shipment status...",
    shipmentAnswerTitle: "I checked your shipment",
    shipmentDelayAnswer: "Your shipment is delayed because of an operational delay at the sorting center. The latest update shows that delivery is expected to continue on the next business day.",
    expectedDelivery: "Expected delivery",
    expectedDeliveryValue: "Tomorrow before 6:00 PM",
    answeredQuestion: "Did this answer your inquiry?",
    inquiryResolved: "Yes, my inquiry is resolved",
    talkToCustomerService: "No, I want customer service",
    resolvedTitle: "Inquiry resolved",
    resolvedText: "No complaint was created because the inquiry was resolved directly.",
    humanHandoffTitle: "I’ll send this to customer service for you",
    humanHandoffText: "I’ll pass your identity context, shipment number and conversation details automatically. You won’t need to enter the information again.",
    createFollowUp: "Send to customer service",
    caseCreatedTitle: "Your follow-up request has been created",
    caseReference: "Follow-up reference",
    caseReferenceValue: "CS-10482",
    contactWithin48: "Customer service will contact you within 48 hours.",
    noRepeatData: "Your details, shipment number and inquiry context were attached automatically.",
    startNewInquiry: "Back to Home",
  },

  ar: {
    back: "العودة إلى مخطط الخدمة",
    badge: "وكيل مباشر · بيئة تجريبية",
    title: "تجربة الخدمة بعد إعادة تصميمها",
    subtitle: "يتحول مخطط الخدمة المعتمد إلى رحلة يقودها الوكيل الذكي للمتعامل.",
    customerJourney: "رحلة المتعامل",
    agentJourney: "رحلة الوكيل الذكي",
    
    customerSubtitle: "يحتفظ المتعامل بالتحكم في الهوية والاختيارات والموافقة والدفع، بينما يتولى الوكيل الذكي الأعمال الإدارية.",
    customerStepsPaid: ["الهوية الرقمية", "المراجعة", "الدفع", "الإنجاز"],
    customerStepsNoPayment: ["الهوية الرقمية", "المراجعة", "الإنجاز"],
    planKicker: "الخطة",
    readyForConsent: "جاهزة للموافقة",
    securePaymentKicker: "دفع آمن · بيئة تجريبية",
    agentExecutionKicker: "تنفيذ الوكيل الذكي",
    outcomeDeliveredKicker: "تم تسليم النتيجة",
    emxCheckpointKicker: "نقطة التحقق المادية · EMX",
    licenceCheckpointKicker: "نقطة الموافقة على الترخيص",
    quoteReadyKicker: "عرض سعر EMX جاهز",
    stepsPaid: ["تسجيل الدخول", "الخطة", "الدفع", "التنفيذ"],
    stepsNoPayment: ["تسجيل الدخول", "الخطة", "التنفيذ"],
    stepsShipment: ["تسجيل الدخول", "الخطة", "التجهيز", "الوزن والتسعير", "الدفع", "التتبع"],
    stepsLicence: ["تسجيل الدخول", "الخطة", "الموافقة والتقييم", "التحويل البنكي", "التفعيل"],
    identityKicker: "الهوية الرقمية · بيئة تجريبية",
    registerTitle: "المتابعة باستخدام الهوية الرقمية",
    registerText: "يُسجَّل الدخول مرة واحدة، ثم يسترجع الوكيل الذكي المعلومات المصرح بها واللازمة لهذه الخدمة فقط.",
    identityNote: "هذه محاكاة داخل البيئة التجريبية، ولا تستخدم حساب هوية رقمية أو بيانات شخصية حقيقية.",
    signInUaePass: "الدخول بالهوية الرقمية",
    documentsLoadingTitle: "جارٍ استرجاع مستنداتك بشكل آمن...",
    documentsLoadingText: "يرجى الانتظار بينما يقوم الوكيل الذكي باسترجاع المستندات المطلوبة والتحقق منها عبر الهوية الرقمية.",
    name: "الاسم الكامل",
    email: "البريد الإلكتروني",
    continue: "متابعة آمنة",
    customerReviewTitle: "مراجعة الخدمة",
    customerReviewText: "يظهر اسم الخدمة والمبلغ المؤكد فقط. يمكن الموافقة على الخطة أو تعديل الاختيارات المتاحة.",
    service: "الخدمة",
    amount: "المبلغ",
    noFee: "لا توجد رسوم",
    changeChoices: "تعديل الاختيارات",
    approveContinue: "الموافقة والمتابعة",
    approveComplete: "الموافقة والإنجاز",
    planTitle: "خطة التنفيذ القابلة للتعديل",
    planTextPaid: "راجع كل ما سينفذه الوكيل الذكي قبل الدفع والتنفيذ.",
    planTextAction: "راجع ما سيرسله أو ينفذه الوكيل الذكي قبل أي إجراء ملزم.",
    recommended: "توصية الوكيل الذكي",
    actions: "إجراءات الوكيل الذكي المخططة",
    fee: "الرسوم",
    sla: "المدة المتوقعة",
    integrations: "اتصالات التنفيذ",
    protected: "الضوابط المحمية بواسطة الموظف",
    edit: "تعديل الخطة",
    approve: "موافق على الخطة",
    approveSubmission: "موافق على إرسال الحالة",
    editTitle: "حدد ما تريد تغييره في الخطة",
    editPlaceholderPaid: "مثال: اختر الباقة الأقل تكلفة، وألغِ التجديد التلقائي",
    editPlaceholderCase: "مثال: صحح تاريخ الواقعة أو غيّر النتيجة المطلوبة من الشكوى",
    editPlaceholderAction: "مثال: غيّر الاختيار أو الموعد المطلوب",
    applyEdit: "إعادة بناء الخطة",
    cancelEdit: "إلغاء",
    paymentTitle: "اعتماد الدفع التجريبي",
    paymentText: "تم تثبيت نسخة الخطة المعتمدة. تحاكي هذه الشاشة تأكيد دفع حكومي آمن.",
    beneficiary: "مقدم الخدمة المحدد في مخطط الخدمة المعتمد",
    unknownFee: "يجب تأكيد الرسوم قبل الدفع",
    journeyType: "نوع الرحلة",
    noPayment: "لا تتطلب الرحلة دفعًا من المتعامل",
    feeNeedsReview: "حالة الرسوم تحتاج مراجعة مالك الخدمة",
    paymentApprove: "أوافق على المبلغ والجهة المستفيدة الموضحين",
    pay: "إتمام الدفع التجريبي",
    customerPaymentTitle: "تأكيد الدفع",
    customerPaymentText: "راجع اسم الخدمة والمبلغ، ثم اعتمد الدفع الآمن داخل البيئة التجريبية.",
    customerPaymentConsent: "أوافق على هذه الخدمة والمبلغ الموضح.",
    customerProcessingTitle: "جارٍ إنجاز الطلب",
    customerProcessingText: "لا يلزم اتخاذ أي إجراء إضافي. ينفذ الوكيل الذكي الأعمال المعتمدة في الخلفية.",
    customerSuccessTitle: "اكتملت الخدمة",
    customerSuccessPaid: "تم الدفع بنجاح، وأصبحت نتيجة الخدمة جاهزة.",
    customerSuccessNoPayment: "اكتمل الاستفسار أو الطلب، ولم تكن هناك رسوم مستحقة.",
    receipt: "الرقم المرجعي",
    deferredPlanText: "راجع ما سينجزه الوكيل الذكي قبل نقطة تقييم الخدمة ثم الدفع.",
    shipmentHandoffTitle: "جهّز الوكيل الذكي الشحنة لتسليمها إلى مندوب EMX",
    shipmentHandoffText: "تم تجهيز البيانات ومستندات الجمارك والحجز والملصق المبدئي. الآن يلزم فقط تسليم الشحنة فعليًا للمندوب حتى تؤكد EMX الوزن والأبعاد وتصدر السعر النهائي.",
    shipmentHandoffButton: "محاكاة استلام المندوب والوزن وتسعير EMX",
    licenceAssessmentTitle: "تم تجهيز الطلب وتقديمه واعتماده لتقييم الرسوم",
    licenceAssessmentText: "استرجع الوكيل الذكي مستندات الشركة وتابع الطلب حتى الموافقة. يطبق نظام الرسوم الآن 10% سنويًا من مبيعات الأنشطة البريدية، بحد أدنى 100,000 درهم يُدفع مقدمًا.",
    licenceAssessmentButton: "محاكاة الموافقة وتقييم الرسوم",
    completedBeforePayment: "تم إنجازه قبل الدفع",
    quoteTitle: "أكدت EMX السعر التجريبي بعد الوزن",
    quoteText: "أصبح المبلغ جاهزًا لاعتماد المتعامل. في التشغيل الحقيقي يصل السعر مباشرة من EMX بعد الفحص المادي.",
    continuePayment: "مراجعة السعر المعتمد والدفع",
    bankTransferTitle: "اعتماد التحويل البنكي التجريبي",
    bankTransferText: "تم تثبيت تقييم الرسوم المعتمد. تحاكي هذه الشاشة التحويل البنكي المطلوب وتأكيد الإيصال.",
    bankTransferApprove: "أوافق على الرسوم السنوية المحسوبة والتحويل البنكي",
    bankTransferPay: "تأكيد التحويل البنكي التجريبي",
    executingTitle: "ينفذ الوكيل الذكي الخدمة الآن",
    executingText: "يتم التحقق من كل إجراء وحفظه في سجل المعاملة.",
    queued: "في الانتظار",
    running: "يُنفذ الآن",
    completed: "تم",
    case: "المعاملة",
    planVersion: "نسخة الخطة المعتمدة",
    paymentReference: "مرجع الدفع",
    consentReference: "مرجع الموافقة",
    handoff: "طلب موظف",
    cancel: "إلغاء الرحلة",
    successTitle: "تمت الخدمة بنجاح",
    successText: "النتيجة جاهزة، ويمكن تتبع الرحلة بالكامل من نفس المكان.",
    result: "النتيجة",
    reference: "رقم الرحلة",
    timing: "موعد المتابعة",
    objection: "استفسار أو تصحيح أو اعتراض",
    objectionAvailable: "متاح ضمن الرحلة نفسها",
    newJourney: "العودة إلى مخطط الخدمة",

    caseIntakeKicker: "فهم الوكيل الذكي",
    complaintIntakeTitle: "صِف لي ما حدث بطريقتك",
    inquiryIntakeTitle:"اكتب استفسارك بأسلوبك",
    complaintIntakeText: "من دون نموذج أو الحاجة إلى تحديد الأولوية. اكتب بالعربية الفصحى أو بأي لهجة عربية، وسيفهم الوكيل المشكلة ويصنفها ويحدد أهميتها ويحاول حلها أولًا.",
    inquiryIntakeText: "اطرح استفسارك بأسلوبك وبأي لهجة عربية. سيفهم الوكيل طلبك ويحدد نوع الاستفسار ويجهز الإجابة أو الإجراء المناسب، ولن يطلب توضيحًا إلا عند الحاجة.",
   complaintPlaceholder: "مثال: لم تصل شحنتي حتى الآن، وأرغب في معرفة سبب التأخير",
    inquiryPlaceholder: "مثال: أرغب في معرفة المستندات المطلوبة وقيمة الرسوم",
    caseReferenceLabel: "الرقم المرجعي — اختياري",
    caseReferencePlaceholder: "رقم الشحنة أو الطلب أو الحالة",
    understandAndSolve: "فهم المشكلة ومحاولة حلها",
    understandInquiry: "فهم الاستفسار والإجابة عنه",
    agentUnderstanding: "الوكيل يفهم رسالتك ويحللها الآن...",
    dialectNote: "يفهم الفصحى واللهجات العربية الشائعة وصياغات الإنجليزية الطبيعية.",

    detectedIssue: "ما فهمه الوكيل",
    detectedPriority: "الأولوية",
    detectedReason: "السبب",
    proposedResolution: "إجراء الوكيل",
    normalPriority: "عادية",
    mediumPriority: "مهمة",
    highPriority: "مرتفعة",
    continueResolution: "متابعة الحل المقترح",
    continueEscalation: "تجهيز التصعيد الذكي",
    continueInquiry: "متابعة الإجابة أو الإجراء",
    autoResolveBadge: "الحل أولًا",
    escalationBadge: "تصعيد ذكي",
    inquiryBadge: "تم فهم الاستفسار",
    resolvePossible: "يمكنني محاولة حل المشكلة دون إنشاء شكوى يدوية.",
    escalationNeeded: "المشكلة تحتاج تدخل مختص. جهزت التصنيف والأولوية والتوجيه تلقائيًا.",
    inquiryUnderstood: "فهمت المطلوب وجهزت أفضل إجابة أو إجراء تالي.",
    changeMessage: "تعديل الرسالة",
    proposed: "مقترح",
    simulated: "محاكاة",

    linkedOrdersFound: "وجدت شحنتين حديثتين مرتبطتين بحسابك في الهوية الرقمية.",
    chooseLinkedOrder: "أي شحنة تقصد؟",
    orderStatus: "الحالة",
    orderDate: "تاريخ الطلب",
    selectOrder: "اختيار هذه الشحنة",
    checkingShipment: "جارٍ التحقق من آخر حالة للشحنة...",
    shipmentAnswerTitle: "تحققت من شحنتك",
    shipmentDelayAnswer: "الشحنة متأخرة بسبب تأخير تشغيلي في مركز الفرز. آخر تحديث يوضح أن التوصيل متوقع أن يستكمل خلال يوم العمل التالي.",
    expectedDelivery: "موعد التسليم المتوقع",
    expectedDeliveryValue: "غدًا قبل الساعة 6:00 مساءً",
    answeredQuestion: "هل أجبت عن استفسارك؟",
    inquiryResolved: "نعم، تم حل الاستفسار",
    talkToCustomerService: "لا، أريد التواصل مع خدمة العملاء",
    resolvedTitle: "تم حل الاستفسار",
    resolvedText: "لن يتم إنشاء شكوى لأن الاستفسار تم حله مباشرة.",
    humanHandoffTitle: "سأرسل الطلب إلى خدمة العملاء بالنيابة عنك",
    humanHandoffText: "سأرسل بيانات الهوية ورقم الشحنة وسياق المحادثة تلقائيًا. لن تحتاج إلى إدخال البيانات مرة أخرى.",
    createFollowUp: "إرسال إلى خدمة العملاء",
    caseCreatedTitle: "تم إنشاء طلب المتابعة",
    caseReference: "رقم المتابعة",
    caseReferenceValue: "CS-10482",
    contactWithin48: "سيتواصل معك فريق خدمة العملاء خلال 48 ساعة.",
    noRepeatData: "تم إرفاق بياناتك ورقم الشحنة وتفاصيل الاستفسار تلقائيًا.",
    startNewInquiry: "العودة إلى الصفحة الرئيسية",
  },
};


function normalizeCustomerLanguage(value = "") {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[\u064B-\u065F\u0670]/g, "")
    .replace(/[إأآا]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/ؤ/g, "و")
    .replace(/ئ/g, "ي")
    .replace(/\s+/g, " ")
    .trim();
}


function hasAny(text, phrases) {
  return phrases.some((phrase) =>
    text.includes(normalizeCustomerLanguage(phrase))
  );
}


function understandCustomerMessage(
  message,
  lang,
  isComplaint,
  isInquiry
) {
  const text =
    normalizeCustomerLanguage(message);


  const delay = hasAny(text, [
    "متأخر",
    "متاخر",
    "اتأخر",
    "اتاخر",
    "تأخير",
    "تاخير",
    "لسه موصلش",
    "ماوصلش",
    "ما وصلش",
    "لم تصل",
    "لم يصل",
    "مو واصل",
    "مب واصل",
    "ما جاني",
    "ماجاني",
    "delayed",
    "delay",
    "late",
    "still not arrived",
    "not arrived",
  ]);


  const missing = hasAny(text, [
    "ضاع",
    "ضاعت",
    "مفقود",
    "مش لاقي",
    "مو لاقي",
    "مب لاقي",
    "لم أجد",
    "lost",
    "missing",
    "not found",
  ]);


  const damaged = hasAny(text, [
    "تالف",
    "متضرر",
    "مكسور",
    "خربان",
    "مخرب",
    "damaged",
    "broken",
  ]);


  const payment = hasAny(text, [
    "اتخصم",
    "خصم",
    "دفعت",
    "فلوس",
    "مبلغ",
    "استرداد",
    "استرجاع",
    "payment",
    "charged",
    "refund",
    "money",
  ]);


  const noResponse = hasAny(text, [
    "محدش رد",
    "ماحد رد",
    "ما حد رد",
    "محد تواصل",
    "ما تواصلوا",
    "ما ردوا",
    "no one replied",
    "no response",
    "nobody contacted",
  ]);


  const urgent = hasAny(text, [
    "عاجل",
    "ضروري",
    "اليوم",
    "سفر",
    "موعد",
    "ضروره",
    "urgent",
    "today",
    "deadline",
    "travel",
  ]);


  const fees = hasAny(text, [
    "رسوم",
    "السعر",
    "بكام",
    "كام",
    "كم",
    "تكلف",
    "price",
    "fee",
    "cost",
    "how much",
  ]);


  const documents = hasAny(text, [
    "مستند",
    "اوراق",
    "أوراق",
    "وثائق",
    "مطلوب",
    "documents",
    "papers",
    "requirements",
  ]);


  const status = hasAny(text, [
    "حاله",
    "حالة",
    "وين",
    "فين",
    "وصل",
    "status",
    "where",
    "track",
    "tracking",
  ]);


  const eligibility = hasAny(text, [
    "ينفع",
    "اقدر",
    "أقدر",
    "مؤهل",
    "شروط",
    "eligib",
    "can i",
    "allowed",
  ]);


  let issue =
    lang === "ar"
      ? "طلب مساعدة عام"
      : "General assistance request";


  let action =
    lang === "ar"
      ? "سأستخدم سياق الخدمة والبيانات المتاحة لتحديد الإجراء الأنسب."
      : "I’ll use the service context and available data to determine the best next action.";


  if (missing) {
    issue =
      lang === "ar"
        ? "شحنة مفقودة أو غير مستلمة"
        : "Missing or undelivered shipment";

    action =
      lang === "ar"
        ? "بدء تتبع موسع وربط آخر نقاط المسح بالحالة ثم تجهيز تصعيد للفريق المختص."
        : "Start extended tracing, connect the latest scan history, then prepare specialist escalation.";
  } else if (damaged) {
    issue =
      lang === "ar"
        ? "شحنة أو خدمة متضررة"
        : "Damaged shipment or service outcome";

    action =
      lang === "ar"
        ? "تجميع تفاصيل الضرر والأدلة المتاحة وتجهيز مسار المعالجة أو التعويض."
        : "Collect damage context and available evidence, then prepare the resolution or compensation path.";
  } else if (payment) {
    issue =
      lang === "ar"
        ? "مشكلة دفع أو استرداد"
        : "Payment or refund issue";

    action =
      lang === "ar"
        ? "مطابقة العملية المالية والتحقق من حالة الخصم أو الاسترداد قبل التصعيد."
        : "Reconcile the transaction and verify charge/refund status before escalation.";
  } else if (delay) {
    issue =
      lang === "ar"
        ? "تأخر في الخدمة أو الشحنة"
        : "Service or shipment delay";

    action =
      lang === "ar"
        ? "التحقق من آخر حالة للشحنة ومحاولة حل الاستفسار قبل إنشاء أي شكوى."
        : "Check the latest shipment status and try to resolve the inquiry before creating any complaint.";
  } else if (fees) {
    issue =
      lang === "ar"
        ? "استفسار عن الرسوم والتكلفة"
        : "Fees and cost inquiry";

    action =
      lang === "ar"
        ? "استرجاع الرسوم المعتمدة من مخطط الخدمة وعرض المبلغ أو قاعدة التسعير بوضوح."
        : "Retrieve the approved fee information from the service blueprint and present the amount or pricing rule.";
  } else if (documents) {
    issue =
      lang === "ar"
        ? "استفسار عن المستندات والمتطلبات"
        : "Documents and requirements inquiry";

    action =
      lang === "ar"
        ? "تحديد المستندات المطلوبة فقط وبيان ما يمكن استرجاعه تلقائيًا عبر الهوية الرقمية."
        : "Identify only the required documents and show what can be retrieved automatically through digital identity.";
  } else if (status) {
    issue =
      lang === "ar"
        ? "استفسار عن حالة طلب أو شحنة"
        : "Application or shipment status inquiry";

    action =
      lang === "ar"
        ? "استخدام سياق المتعامل لاسترجاع آخر حالة وتحديد الإجراء التالي."
        : "Use the customer context to retrieve the latest status and determine the next action.";
  } else if (eligibility) {
    issue =
      lang === "ar"
        ? "استفسار عن الأهلية أو الشروط"
        : "Eligibility or conditions inquiry";

    action =
      lang === "ar"
        ? "مطابقة حالة المتعامل مع شروط الخدمة وشرح ما إذا كان مؤهلًا وما المطلوب بعد ذلك."
        : "Match the customer context against service conditions and explain eligibility and next requirements.";
  }


  let priority = "NORMAL";
  const reasons = [];


  if (missing || damaged || payment) {
    priority = "HIGH";

    reasons.push(
      lang === "ar"
        ? "يوجد فقد أو ضرر أو أثر مالي يحتاج حماية المتعامل"
        : "Loss, damage or financial impact requires customer protection"
    );
  } else if (delay || noResponse) {
    priority = "MEDIUM";

    reasons.push(
      lang === "ar"
        ? "يوجد تأخر أو عدم استجابة يحتاج متابعة"
        : "Delay or lack of response requires follow-up"
    );
  }


  if (urgent) {
    priority = "HIGH";

    reasons.push(
      lang === "ar"
        ? "الرسالة تشير إلى احتياج عاجل أو موعد حساس"
        : "The message indicates an urgent or time-sensitive need"
    );
  }


  if (isInquiry) {
    priority = "NORMAL";
  }


  const canAutoResolve =
    isInquiry ||
    (
      isComplaint &&
      !missing &&
      !damaged &&
      !payment &&
      !urgent
    );


  return {
    issue,
    priority,
    reason:
      reasons.join(
        lang === "ar"
          ? "، "
          : ", "
      ) ||
      (
        lang === "ar"
          ? "تم تحديدها تلقائيًا من معنى الرسالة وسياق الخدمة"
          : "Automatically assessed from the message meaning and service context"
      ),
    action,
    canAutoResolve,
  };
}


function langLabels(copy) {
  const isArabic =
    copy.back ===
    "العودة إلى مخطط الخدمة";

  return isArabic
    ? [
        "الهوية الرقمية",
        "فهم الرسالة",
        "الحل أو الإجراء",
        "الإنجاز",
      ]
    : [
        "UAE PASS",
        "Understand",
        "Resolution / action",
        "Done",
      ];
}


function StageRail({
  screen,
  copy,
  requiresPayment,
  serviceKind,
  journeyView,
  conversationalService,
  messageAgentPhase,
}) {
  let order;
  let labels;


  if (
    journeyView === "customer" &&
    conversationalService
  ) {
    order = [
      "register",
      "intake",
      "plan",
      "execution",
    ];

    labels =
      langLabels(copy);
  } else if (
    journeyView === "customer"
  ) {
    order =
      requiresPayment
        ? [
            "register",
            "plan",
            "payment",
            "execution",
          ]
        : [
            "register",
            "plan",
            "execution",
          ];

    labels =
      requiresPayment
        ? copy.customerStepsPaid
        : copy.customerStepsNoPayment;
  } else if (
    serviceKind ===
    "INTERNATIONAL_SHIPMENT"
  ) {
    order = [
      "register",
      "plan",
      "handoff",
      "quote",
      "payment",
      "execution",
    ];

    labels =
      copy.stepsShipment;
  } else if (
    serviceKind ===
    "POSTAL_ACTIVITY_LICENSE"
  ) {
    order = [
      "register",
      "plan",
      "handoff",
      "payment",
      "execution",
    ];

    labels =
      copy.stepsLicence;
  } else {
    order =
      requiresPayment
        ? [
            "register",
            "plan",
            "payment",
            "execution",
          ]
        : [
            "register",
            "plan",
            "execution",
          ];

    labels =
      requiresPayment
        ? copy.stepsPaid
        : copy.stepsNoPayment;
  }


  let normalized =
    screen === "complete"
      ? "execution"
      : screen;


  if (
    journeyView === "customer" &&
    conversationalService
  ) {
    if (
      screen === "intake" &&
      [
        "checking",
        "result",
        "handoff",
      ].includes(
        messageAgentPhase
      )
    ) {
      normalized = "plan";
    }

    if (
      screen === "intake" &&
      [
        "resolved",
        "caseCreated",
      ].includes(
        messageAgentPhase
      )
    ) {
      normalized =
        "execution";
    }
  } else if (
    journeyView === "customer" &&
    [
      "handoff",
      "quote",
    ].includes(normalized)
  ) {
    normalized =
      "payment";
  }


  const activeIndex =
    Math.max(
      0,
      order.indexOf(normalized)
    );


  return (
    <div
      className="live-stage-rail"
      style={{
        "--stage-count":
          labels.length,
      }}
    >
      {labels.map(
        (label, index) => (
          <div
            className={`live-stage ${
              index ===
              activeIndex
                ? "active"
                : ""
            } ${
              index <
              activeIndex
                ? "done"
                : ""
            }`}
            key={label}
          >
            <span>
              {index <
              activeIndex
                ? "✓"
                : index + 1}
            </span>

            <small>
              {label}
            </small>
          </div>
        )
      )}
    </div>
  );
}


function LiveAgentPage({
  result,
  onBack,
  customerOnly = false,
  onSessionStart,
  demoIdentity = null,
}) {
  const { lang } =
    useLanguage();

  const copy =
    COPY[lang] ||
    COPY.en;

  const eventSourceRef =
    useRef(null);

  const [
    journeyView,
    setJourneyView,
  ] = useState("customer");

  const [
    screen,
    setScreen,
  ] = useState("register");

  const [
    busy,
    setBusy,
  ] = useState(false);

  const [
    error,
    setError,
  ] = useState("");

  const [
    customer,
    setCustomer,
  ] = useState(null);

  const [
    journey,
    setJourney,
  ] = useState(null);

  const [
    editOpen,
    setEditOpen,
  ] = useState(false);

  const [
    paymentApproved,
    setPaymentApproved,
  ] = useState(false);

  const [
    events,
    setEvents,
  ] = useState([]);

  const [
    customerMessage,
    setCustomerMessage,
  ] = useState("");

  const [
    customerReference,
    setCustomerReference,
  ] = useState("");

  const [
    messageAnalysis,
    setMessageAnalysis,
  ] = useState(null);

  const [
    messageAgentPhase,
    setMessageAgentPhase,
  ] = useState("input");

  const [
    selectedOrder,
    setSelectedOrder,
  ] = useState(null);


  const blueprintClassification =
    result?.redesign
      ?.service_classification ||
    result?.redesign
      ?.design_profile ||
    {};


  const requiresPayment =
    Boolean(
      journey?.plan
        ?.requires_payment ??
        blueprintClassification
          .requires_customer_payment
    );


  const serviceArchetype =
    journey?.plan
      ?.service_archetype ||
    blueprintClassification
      .service_archetype ||
    "APPLICATION";


  const isCase =
    [
      "COMPLAINT",
      "DISPUTE_REFUND",
    ].includes(
      serviceArchetype
    );


  const serviceKind =
    journey?.plan
      ?.service_kind ||
    blueprintClassification
      .service_kind ||
    "GENERAL";


  const serviceIdentity = `
    ${result?.service_name || ""}
    ${blueprintClassification.service_archetype || ""}
    ${blueprintClassification.service_kind || ""}
    ${journey?.plan?.service_type_label || ""}
  `.toLowerCase();


  const isInquiry =
    [
      "INFORMATION",
      "INQUIRY",
    ].includes(
      serviceArchetype
    ) ||
    serviceIdentity.includes(
      "inquiry"
    ) ||
    serviceIdentity.includes(
      "استفسار"
    );


  const conversationalService =
    isCase ||
    isInquiry;


  useEffect(
    () => () =>
      eventSourceRef.current
        ?.close(),
    []
  );


  async function run(action) {
    setBusy(true);
    setError("");

    try {
      return await action();
    } catch (
      requestError
    ) {
      setError(
        translateApiError(requestError.message, lang) ||
          (lang === "ar" ? "تعذّر إتمام الطلب." : "Request failed.")
      );

      return null;
    } finally {
      setBusy(false);
    }
  }
    async function handleRegister() {
    const sandboxIdentity = {
      name:
        demoIdentity?.name ||
        (lang === "ar"
          ? "متعامل الهوية الرقمية"
          : "UAE PASS Customer"),

      email:
        demoIdentity?.email ||
        `uae-pass-${Date.now()}@sandbox.invalid`,

      blueprint_id: result?.blueprint_id,
    };


    const registered =
      await run(() =>
        registerSandboxCustomer(
          sandboxIdentity,
          !customerOnly
        )
      );


    if (!registered) return;


    setCustomer(registered);
    onSessionStart?.();


    const automaticIntent =
      lang === "ar"
        ? `أرغب في إنجاز ${
            result?.service_name ||
            "هذه الخدمة"
          }`
        : `I want to complete ${
            result?.service_name ||
            "this service"
          }`;


    const created =
      await run(() =>
        createJourney({
          customer_id:
            registered.id,

          intent:
            automaticIntent,

          blueprint_id:
            result.blueprint_id,

          lang,

          sandbox: true,
        })
      );


    if (created) {
      setJourney(created);


      if (
        conversationalService
      ) {
        setCustomerReference(
          ""
        );

        setMessageAnalysis(
          null
        );

        setSelectedOrder(
          null
        );

        // UAE PASS is complete.
        // Now move to the message screen.
        setMessageAgentPhase(
          "input"
        );

        setScreen(
          "intake"
        );

        return;
      }


      setScreen(
        "documents"
      );


      await new Promise(
        (resolve) =>
          setTimeout(
            resolve,
            10000
          )
      );


      setScreen(
        "plan"
      );
    }
  }


  async function handleCustomerMessage(
    event
  ) {
    event.preventDefault();


    if (
      !customerMessage.trim()
    ) {
      setError(
        lang === "ar"
          ? "اكتب رسالتك أو مشكلتك أولًا."
          : "Write your message or issue first."
      );

      return;
    }


    setError("");

    setMessageAnalysis(
      null
    );

    setSelectedOrder(
      null
    );


    // UAE PASS already happened
    // before reaching this screen.
    setMessageAgentPhase(
      "thinking"
    );


    await new Promise(
      (resolve) =>
        setTimeout(
          resolve,
          1200
        )
    );


    const understood =
      understandCustomerMessage(
        customerMessage,
        lang,
        isCase,
        isInquiry
      );


    setMessageAnalysis(
      understood
    );


if (isInquiry) {
  setMessageAgentPhase("result");
  return;
}

if (isCase) {
  setMessageAgentPhase("orders");
}
  }


  const demoLinkedOrders = [
    {
      id: "EP-28491",

      route:
        lang === "ar"
          ? "دبي ← أبوظبي"
          : "Dubai → Abu Dhabi",

      status:
        lang === "ar"
          ? "قيد التوصيل — متأخرة"
          : "In transit — delayed",

      date:
        "17 Aug 2026",
    },

    {
      id: "EP-38126",

      route:
        lang === "ar"
          ? "أبوظبي ← دبي"
          : "Abu Dhabi → Dubai",

      status:
        lang === "ar"
          ? "تم التسليم"
          : "Delivered",

      date:
        "15 Aug 2026",
    },
  ];


  async function handleSelectLinkedOrder(
    order
  ) {
    setSelectedOrder(
      order
    );


    setMessageAgentPhase(
      "checking"
    );


    await new Promise(
      (resolve) =>
        setTimeout(
          resolve,
          1200
        )
    );


    const understood =
      understandCustomerMessage(
        customerMessage,
        lang,
        isCase,
        isInquiry
      );


    setMessageAnalysis(
      understood
    );


    setMessageAgentPhase(
      "result"
    );
  }


  function restartConversation() {
    setCustomerMessage(
      ""
    );

    setCustomerReference(
      ""
    );

    setMessageAnalysis(
      null
    );

    setSelectedOrder(
      null
    );

    setMessageAgentPhase(
      "input"
    );

    setCustomer(
      null
    );

    setJourney(
      null
    );

    setScreen(
      "register"
    );
  }


  function continueFromMessageAnalysis() {
    if (
      !messageAnalysis
    ) {
      return;
    }


    setScreen(
      "plan"
    );
  }


  async function handleEdit(
    editPayload
  ) {
    const updated =
      await run(() =>
        editJourneyPlan(
          journey.id,
          editPayload
        )
      );


    if (
      updated
    ) {
      setJourney(
        updated
      );

      setEditOpen(
        false
      );


      if (
        updated.plan
          ?.requires_payment
      ) {
        const approved =
          await run(() =>
            approveJourneyPlan(
              updated.id
            )
          );


        if (
          approved
        ) {
          setJourney(
            approved
          );

          advanceAfterApproval(
            approved
          );
        }
      }
    }
  }


  function advanceAfterApproval(
    updated
  ) {
    if (
      updated.plan
        ?.requires_payment
    ) {
      if (
        updated.plan
          ?.payment_timing !==
        "BEFORE_EXECUTION"
      ) {
        setScreen(
          "handoff"
        );
      } else {
        setScreen(
          "payment"
        );
      }


      return;
    }


    beginExecution(
      updated
    );
  }


  async function handleApprovePlan() {
    const updated =
      await run(() =>
        approveJourneyPlan(
          journey.id
        )
      );


    if (
      !updated
    ) {
      return;
    }


    setJourney(
      updated
    );


    advanceAfterApproval(
      updated
    );
  }


  async function handlePaymentAssessment() {
    const assessed =
      await run(() =>
        prepareJourneyPaymentAssessment(
          journey.id
        )
      );


    if (
      !assessed
    ) {
      return;
    }


    setJourney(
      assessed
    );


    setScreen(
      assessed.plan
        ?.service_kind ===
        "INTERNATIONAL_SHIPMENT"
        ? "quote"
        : "payment"
    );
  }


  function startEventStream(
    journeyId
  ) {
    eventSourceRef.current
      ?.close();


    const source =
      new EventSource(
        getJourneyEventsUrl(
          journeyId
        ),
        { withCredentials: true }
      );


    eventSourceRef.current =
      source;


    source.addEventListener(
      "agent_event",
      (event) => {
        const incoming =
          JSON.parse(
            event.data
          );


        setEvents(
          (current) => {
            const existing =
              current.findIndex(
                (item) =>
                  item.id ===
                  incoming.id
              );


            if (
              existing < 0
            ) {
              return [
                ...current,
                incoming,
              ];
            }


            return current.map(
              (
                item,
                index
              ) =>
                index ===
                existing
                  ? incoming
                  : item
            );
          }
        );
      }
    );


    source.addEventListener(
      "journey_complete",
      (event) => {
        const completed =
          JSON.parse(
            event.data
          );


        setJourney(
          completed
        );


        setScreen(
          "complete"
        );


        source.close();
      }
    );


    source.addEventListener(
      "journey_controlled",
      (event) => {
        setJourney(
          JSON.parse(
            event.data
          )
        );


        source.close();
      }
    );


    source.onerror =
      () => {
        source.close();
      };
  }


  async function beginExecution(
    approvedJourney
  ) {
    const executing =
      await run(() =>
        executeJourney(
          approvedJourney.id
        )
      );


    if (
      !executing
    ) {
      return;
    }


    setJourney(
      executing
    );


    setEvents(
      []
    );


    setScreen(
      "execution"
    );


    startEventStream(
      executing.id
    );
  }


  async function handlePayment() {
    if (
      !paymentApproved ||
      !paymentReady
    ) {
      return;
    }


    const paymentMethod =
      plan.payment_method ===
      "BANK_TRANSFER"
        ? "SANDBOX_BANK_TRANSFER"
        : "SANDBOX_CARD";


    const paid =
      await run(() =>
        payJourney(
          journey.id,
          paymentMethod
        )
      );


    if (
      !paid
    ) {
      return;
    }


    await beginExecution(
      paid
    );
  }


  async function handleControl(
    action
  ) {
    const updated =
      await run(() =>
        controlJourney(
          journey.id,
          action
        )
      );


    if (
      updated
    ) {
      eventSourceRef.current
        ?.close();


      setJourney(
        updated
      );
    }
  }


  const plan =
    journey?.plan ||
    {};


  const payment =
    journey?.payment ||
    {};


  const feeLabel =
    plan.fee_display ||
    (
      plan.fee_amount ==
      null
        ? plan.fee_status ===
          "VERIFY"
          ? copy.feeNeedsReview
          : copy.unknownFee
        : `${plan.fee_amount.toLocaleString()} ${
            plan.fee_currency ||
            "AED"
          }`
    );


  const authoritativeAmount =
    plan.pricing_breakdown?.total ??
    plan.fee_amount ??
    null;


  const paymentReady =
    !requiresPayment ||
    (
      !["VERIFY", "UNKNOWN", "PENDING"].includes(
        String(plan.fee_status || "").toUpperCase()
      ) &&
      authoritativeAmount != null
    );


  const isBankTransfer =
    plan.payment_method ===
    "BANK_TRANSFER";


  return (
    <div className="live-agent-page">

      <header className="live-agent-header">

        <button
          type="button"
          onClick={onBack}
        >
          ← {copy.back}
        </button>


        <div>

          <span className="live-agent-badge">
            {copy.badge}
          </span>


          <h2>
            {journeyView ===
            "customer"
              ? copy.customerTitle
              : copy.title}
          </h2>


          <p>
            {journeyView ===
            "customer"
              ? copy.customerSubtitle
              : copy.subtitle}
          </p>


          {!customerOnly && (
            <div
              className="journey-view-switcher"
              role="tablist"
              aria-label={
                copy.title
              }
            >

              <button
                aria-selected={
                  journeyView ===
                  "customer"
                }
                className={
                  journeyView ===
                  "customer"
                    ? "active"
                    : ""
                }
                onClick={() =>
                  setJourneyView(
                    "customer"
                  )
                }
                role="tab"
                type="button"
              >

                <span
                  aria-hidden="true"
                >
                  ◎
                </span>


                {copy.customerJourney}

              </button>


              <button
                aria-selected={
                  journeyView ===
                  "agent"
                }
                className={
                  journeyView ===
                  "agent"
                    ? "active"
                    : ""
                }
                onClick={() =>
                  setJourneyView(
                    "agent"
                  )
                }
                role="tab"
                type="button"
              >

                <span
                  aria-hidden="true"
                >
                  Ø
                </span>


                {copy.agentJourney}

              </button>

            </div>
          )}

        </div>


        <div className="live-agent-orb">
          <span />
        </div>

      </header>


      <StageRail
        screen={screen}
        copy={copy}
        requiresPayment={
          requiresPayment
        }
        serviceKind={
          serviceKind
        }
        journeyView={
          journeyView
        }
        conversationalService={
          conversationalService
        }
        messageAgentPhase={
          messageAgentPhase
        }
      />


      {error && (
        <div className="live-agent-error">
          {error}
        </div>
      )}

      {customer && demoIdentity && (
        <section className="live-focus-card compact-live-card">
          <span className="live-card-kicker">
            {lang === "ar" ? "تم التحقق من الهوية الرقمية" : "Digital Identity Verified"}
          </span>
          <h3>{demoIdentity.name}</h3>
          <div style={{ display: "grid", gap: "8px", marginTop: "12px" }}>
            <div><strong>{lang === "ar" ? "رقم الهوية: " : "Emirates ID: "}</strong>{demoIdentity.emirates_id}</div>
            <div><strong>{lang === "ar" ? "البريد الإلكتروني: " : "Email: "}</strong>{demoIdentity.email}</div>
            <div><strong>{lang === "ar" ? "رقم الهاتف: " : "Mobile: "}</strong>{demoIdentity.phone}</div>
            <div><strong>{lang === "ar" ? "العنوان: " : "Address: "}</strong>{demoIdentity.address}</div>
          </div>
        </section>
      )}
            {screen === "register" && (
        <section className="live-focus-card compact-live-card uae-pass-card">

          <div
            className="uae-pass-mark"
            aria-hidden="true"
          >
            <span>UAE</span>
            <strong>PASS</strong>
          </div>


          <span className="live-card-kicker">
            {copy.identityKicker}
          </span>


          <h3>
            {copy.registerTitle}
          </h3>


          <p>
              {isCase
    ? (
        lang === "ar"
          ? "سجّل الدخول بالهوية الرقمية حتى أتمكن من الوصول إلى طلباتك المرتبطة بحسابك دون الحاجة إلى إدخال رقم الطلب يدويًا."
          : "Sign in with UAE PASS so I can retrieve the orders linked to your account without asking you to enter the order number manually."
      )
    : isInquiry
      ? (
          lang === "ar"
            ? "سجّل الدخول بالهوية الرقمية للوصول إلى المعلومات المصرح بها والمرتبطة بخدمتك عند الحاجة."
            : "Sign in with UAE PASS to securely access the authorized information relevant to your inquiry when needed."
        )
      : copy.registerText}

          </p>


          <button
            className="uae-pass-button"
            disabled={busy}
            onClick={handleRegister}
            type="button"
          >
            <span
              className="uae-pass-button-icon"
              aria-hidden="true"
            >
              ✓
            </span>

            {busy
              ? "…"
              : copy.signInUaePass}
          </button>


          <small className="uae-pass-note">
            {copy.identityNote}
          </small>

        </section>
      )}


      {screen === "documents" && (
        <section className="live-focus-card document-loading-card">

          <div className="document-loader">

            <div className="document-loader-ring" />

            <span>
              ✓
            </span>

          </div>


          <span className="live-card-kicker">

            {lang === "ar"
              ? "UAE PASS · الهوية الرقمية"
              : "UAE PASS · DIGITAL IDENTITY"}

          </span>


          <h3>
            {copy.documentsLoadingTitle}
          </h3>


          <p>
            {copy.documentsLoadingText}
          </p>


          <div className="document-loading-progress">
            <span />
          </div>


          <small>

            {lang === "ar"
              ? "يتم الوصول إلى البيانات المصرح بها فقط."
              : "Only authorized information is being accessed."}

          </small>

        </section>
      )}


      {screen === "intake" &&
        journeyView === "customer" &&
        conversationalService &&
        messageAgentPhase === "input" && (

          <section className="live-focus-card customer-review-card">

            <span className="live-card-kicker">
              {copy.caseIntakeKicker}
            </span>


            <h3>
              {isCase
                ? copy.complaintIntakeTitle
                : copy.inquiryIntakeTitle}
            </h3>


            <p>
              {isCase
                ? copy.complaintIntakeText
                : copy.inquiryIntakeText}
            </p>


            <form
              onSubmit={handleCustomerMessage}
              style={{
                display: "grid",
                gap: "14px",
                marginTop: "22px",
              }}
            >

              <label className="form-field">

                <span>
                  {copy.caseMessageLabel}
                </span>


                <textarea
                  rows={7}
                  value={customerMessage}
                  onChange={(event) =>
                    setCustomerMessage(
                      event.target.value
                    )
                  }
                  placeholder={
                    isCase
                      ? copy.complaintPlaceholder
                      : copy.inquiryPlaceholder
                  }
                  style={{
                    width: "100%",
                  }}
                />


                <small>
                  {copy.dialectNote}
                </small>

              </label>


              <button
                className="payment-submit"
                disabled={busy}
                type="submit"
              >
                {isInquiry
                    ? copy.understandInquiry
                    : copy.understandAndSolve}
              </button>

            </form>

          </section>
        )}


      {screen === "intake" &&
        journeyView === "customer" &&
        conversationalService &&
        messageAgentPhase !== "input" && (

          <section className="live-focus-card customer-review-card">

            <span className="live-card-kicker">
              {copy.caseIntakeKicker}
            </span>


            {messageAgentPhase === "thinking" && (

              <div
                className="document-loading-card"
                style={{
                  minHeight: "280px",
                }}
              >

                <div className="document-loader">

                  <div className="document-loader-ring" />

                  <span>
                    Ø
                  </span>

                </div>


                <h3>
                  {lang === "ar"
                    ? "أفهم رسالتك وأبحث عن الطلبات المرتبطة بحسابك..."
                    : "Understanding your message and finding the orders linked to your account..."}
                </h3>


                <p>
                  {customerMessage}
                </p>


                <div className="document-loading-progress">
                  <span />
                </div>

              </div>

            )}


            {messageAgentPhase === "orders" && (

              <div
                style={{
                  display: "grid",
                  gap: "18px",
                }}
              >

                <div
                  className="success-check"
                  style={{
                    width: "54px",
                    height: "54px",
                    margin: 0,
                  }}
                >
                  ✓
                </div>


                <div>

                  <h3
                    style={{
                      marginBottom: "8px",
                    }}
                  >
                    {lang === "ar"
                      ? "تم التحقق من هويتك"
                      : "Identity verified"}
                  </h3>


                  <p>
                    {copy.linkedOrdersFound}
                  </p>


                  <h4
                    style={{
                      marginTop: "18px",
                    }}
                  >
                    {copy.chooseLinkedOrder}
                  </h4>

                </div>


                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fit, minmax(260px, 1fr))",
                    gap: "14px",
                  }}
                >

                  {demoLinkedOrders.map(
                    (order) => (

                      <button
                        key={order.id}
                        className="live-side-card"
                        onClick={() =>
                          handleSelectLinkedOrder(
                            order
                          )
                        }
                        style={{
                          textAlign:
                            lang === "ar"
                              ? "right"
                              : "left",
                          cursor: "pointer",
                          border:
                            "1px solid rgba(102, 76, 255, .22)",
                        }}
                        type="button"
                      >

                        <span>
                          {copy.reference}
                        </span>


                        <strong
                          style={{
                            fontSize: "20px",
                          }}
                        >
                          {order.id}
                        </strong>


                        <p
                          style={{
                            margin: "8px 0",
                          }}
                        >
                          {order.route}
                        </p>


                        <small>
                          {copy.orderStatus}:{" "}
                          {order.status}
                        </small>


                        <small
                          style={{
                            display: "block",
                          }}
                        >
                          {copy.orderDate}:{" "}
                          {order.date}
                        </small>


                        <b
                          style={{
                            display: "block",
                            marginTop: "12px",
                            color: "#6b4cff",
                          }}
                        >
                          {copy.selectOrder}
                        </b>

                      </button>

                    )
                  )}

                </div>

              </div>

            )}


            {messageAgentPhase === "checking" && (

              <div
                className="document-loading-card"
                style={{
                  minHeight: "280px",
                }}
              >

                <div className="document-loader">

                  <div className="document-loader-ring" />

                  <span>
                    Ø
                  </span>

                </div>


                <h3>
                  {copy.checkingShipment}
                </h3>


                <p>
                  {selectedOrder?.id}
                  {" · "}
                  {selectedOrder?.route}
                </p>


                <div className="document-loading-progress">
                  <span />
                </div>

              </div>

            )}
            {messageAgentPhase === "result" &&
  messageAnalysis &&
  isInquiry && (

  <div
    style={{
      display: "grid",
      gap: "16px",
    }}
  >
    <div className="plan-heading-row">
      <div>
        <span className="live-card-kicker">
          {copy.inquiryBadge}
        </span>

        <h3>
          {lang === "ar"
            ? "إجابة الوكيل الذكي"
            : "Agent answer"}
        </h3>
      </div>

      <span className="plan-ready-badge">
        ✓
      </span>
    </div>

    <div className="plan-recommendation">
      <span>
        {copy.detectedIssue}
      </span>

      <strong>
        {messageAnalysis.issue}
      </strong>

      <p>
        {messageAnalysis.action}
      </p>
    </div>

    <div
      style={{
        borderTop:
          "1px solid rgba(110, 92, 220, .14)",
        paddingTop: "18px",
      }}
    >
      <h3
        style={{
          fontSize: "22px",
        }}
      >
        {copy.answeredQuestion}
      </h3>

      <div className="customer-plan-actions">
        <button
          className="secondary"
          onClick={() =>
            setMessageAgentPhase("resolved")
          }
          type="button"
        >
          ✓ {copy.inquiryResolved}
        </button>

        <button
          onClick={() =>
            setMessageAgentPhase("handoff")
          }
          type="button"
        >
          {copy.talkToCustomerService}
        </button>
      </div>
    </div>
  </div>
)}


{messageAgentPhase === "result" &&
  messageAnalysis &&
  isCase &&
  selectedOrder && (

                <div
                  style={{
                    display: "grid",
                    gap: "16px",
                  }}
                >

                  <div className="plan-heading-row">

                    <div>

                      <span className="live-card-kicker">
                        {copy.autoResolveBadge}
                      </span>


                      <h3>
                        {copy.shipmentAnswerTitle}
                      </h3>

                    </div>


                    <span className="plan-ready-badge">
                      ✓
                    </span>

                  </div>


                  <div className="customer-service-receipt">

                    <div>

                      <span>
                        {copy.reference}
                      </span>

                      <strong>
                        {selectedOrder.id}
                      </strong>

                    </div>


                    <div>

                      <span>
                        {copy.orderStatus}
                      </span>

                      <strong>
                        {selectedOrder.status}
                      </strong>

                    </div>

                  </div>


                  <div className="plan-recommendation">

                    <span>
                      {copy.proposedResolution}
                    </span>


                    <p>
                      {copy.shipmentDelayAnswer}
                    </p>


                    <small>
                      ↳ {copy.expectedDelivery}:{" "}
                      {copy.expectedDeliveryValue}
                    </small>

                  </div>


                  <div
                    style={{
                      borderTop:
                        "1px solid rgba(110, 92, 220, .14)",
                      paddingTop: "18px",
                    }}
                  >

                    <h3
                      style={{
                        fontSize: "22px",
                      }}
                    >
                      {copy.answeredQuestion}
                    </h3>


                    <div className="customer-plan-actions">

                      <button
                        className="secondary"
                        onClick={() =>
                          setMessageAgentPhase(
                            "resolved"
                          )
                        }
                        type="button"
                      >
                        ✓ {copy.inquiryResolved}
                      </button>


                      <button
                        onClick={() =>
                          setMessageAgentPhase(
                            "handoff"
                          )
                        }
                        type="button"
                      >
                        {copy.talkToCustomerService}
                      </button>

                    </div>

                  </div>

                </div>

              )}


            {messageAgentPhase === "resolved" && (
  <div
    style={{
      display: "grid",
      gap: "16px",
      textAlign: "center",
    }}
  >
    <div
      className="success-check"
      style={{ margin: "0 auto" }}
    >
      ✓
    </div>

    <h3>{copy.resolvedTitle}</h3>

    <p>{copy.resolvedText}</p>

    {isCase && selectedOrder && (
      <div className="customer-service-receipt">
        <div>
          <span>
            {lang === "ar"
              ? "شكاوى تم إنشاؤها"
              : "Complaints created"}
          </span>

          <strong>0</strong>
        </div>

        <div>
          <span>{copy.reference}</span>
          <strong>{selectedOrder.id}</strong>
        </div>
      </div>
    )}

    {isInquiry && (
      <div className="customer-service-receipt">
        <div>
          <span>
            {lang === "ar"
              ? "حالة الاستفسار"
              : "Inquiry status"}
          </span>

          <strong>
            {lang === "ar"
              ? "تمت الإجابة"
              : "Answered"}
          </strong>
        </div>

        <div>
          <span>
            {lang === "ar"
              ? "تم إنشاء شكوى"
              : "Complaint created"}
          </span>

          <strong>
            {lang === "ar" ? "لا" : "No"}
          </strong>
        </div>
      </div>
    )}

    <button
      className="payment-submit"
      onClick={onBack}
      type="button"
    >
      {copy.startNewInquiry}
    </button>
  </div>
)}


            {messageAgentPhase === "handoff" && (

              <div
                style={{
                  display: "grid",
                  gap: "16px",
                }}
              >

                <span className="live-card-kicker">
                  {copy.escalationBadge}
                </span>


                <h3>
                  {copy.humanHandoffTitle}
                </h3>


                <p>
                  {copy.humanHandoffText}
                </p>


                <div className="plan-recommendation">

                  <span>
                    {lang === "ar"
                      ? "سيتم إرسال"
                      : "The agent will send"}
                  </span>


                  <p>
                    ✓{" "}
                    {lang === "ar"
                      ? "بيانات الهوية الرقمية"
                      : "UAE PASS identity context"}
                  </p>


                  {isCase && selectedOrder && (
  <p>
    ✓{" "}
    {lang === "ar"
      ? `رقم الشحنة ${selectedOrder.id}`
      : `Shipment ${selectedOrder.id}`}
  </p>
)}

{isInquiry && (
  <p>
    ✓{" "}
    {lang === "ar"
      ? "تفاصيل الاستفسار"
      : "Inquiry details"}
  </p>
)}

                  <p>
                    ✓{" "}
                    {lang === "ar"
                      ? "رسالتك وسياق المحادثة"
                      : "Your message and conversation context"}
                  </p>

                </div>


                <button
                  className="payment-submit"
                  onClick={() =>
                    setMessageAgentPhase(
                      "caseCreated"
                    )
                  }
                  type="button"
                >
                  {copy.createFollowUp}
                </button>

              </div>

            )}


            {messageAgentPhase === "caseCreated" && (

              <div
                style={{
                  display: "grid",
                  gap: "16px",
                  textAlign: "center",
                }}
              >

                <div
                  className="success-check"
                  style={{
                    margin: "0 auto",
                  }}
                >
                  ✓
                </div>


                <h3>
                  {copy.caseCreatedTitle}
                </h3>


                <div className="customer-service-receipt">

                  <div>

                    <span>
                      {copy.caseReference}
                    </span>

                    <strong>
                      {copy.caseReferenceValue}
                    </strong>

                  </div>


                  {isCase && selectedOrder && (
  <div>
    <span>
      {copy.reference}
    </span>

    <strong>
      {selectedOrder.id}
    </strong>
  </div>
)}

{isInquiry && (
  <div>
    <span>
      {lang === "ar"
        ? "نوع الطلب"
        : "Request type"}
    </span>

    <strong>
      {lang === "ar"
        ? "استفسار"
        : "Inquiry"}
    </strong>
  </div>
)}

                </div>


                <p
                  style={{
                    fontSize: "20px",
                    fontWeight: 800,
                  }}
                >
                  {copy.contactWithin48}
                </p>


                <small>
                  {copy.noRepeatData}
                </small>


                <button
                  className="payment-submit"
                  onClick={onBack}
                  type="button"
                >
                  {copy.startNewInquiry}
                </button>

              </div>

            )}

          </section>
        )}
              {screen === "plan" &&
        journeyView === "customer" && (
          <section className="live-focus-card customer-review-card">

            <span className="live-card-kicker">
              {copy.customerJourney}
            </span>


            <h3>
              {copy.customerReviewTitle}
            </h3>


            <p>
              {copy.customerReviewText}
            </p>


            <div className="customer-service-receipt">

              <div>

                <span>
                  {copy.service}
                </span>

                <strong>
                  {plan.service_name}
                </strong>

              </div>


              <div>

                <span>
                  {copy.amount}
                </span>

                <strong>
                  {requiresPayment
                    ? feeLabel
                    : copy.noFee}
                </strong>

              </div>

            </div>


            {editOpen ? (

              <PlanOptionsEditor
                key={`${journey.id}-${journey.plan_version}`}
                plan={plan}
                lang={lang}
                busy={busy}
                onSubmit={handleEdit}
                onCancel={() =>
                  setEditOpen(false)
                }
              />

            ) : (

              <div className="customer-plan-actions">

                <button
                  className="secondary"
                  onClick={() =>
                    setEditOpen(true)
                  }
                >
                  {copy.changeChoices}
                </button>


                <button
                  disabled={busy}
                  onClick={handleApprovePlan}
                >
                  {busy
                    ? "…"
                    : requiresPayment
                      ? copy.approveContinue
                      : copy.approveComplete}
                </button>

              </div>

            )}

          </section>
        )}


      {screen === "plan" &&
        journeyView === "agent" && (
          <section className="live-plan-layout">

            <div className="live-focus-card plan-main-card">

              <div className="plan-heading-row">

                <div>

                  <span className="live-card-kicker">
                    {copy.planKicker} v
                    {journey.plan_version}
                  </span>


                  <h3>
                    {copy.planTitle}
                  </h3>


                  <p>
                    {plan.payment_timing !==
                    "BEFORE_EXECUTION"
                      ? copy.deferredPlanText
                      : requiresPayment
                        ? copy.planTextPaid
                        : copy.planTextAction}
                  </p>

                </div>


                <span className="plan-ready-badge">
                  {copy.readyForConsent}
                </span>

              </div>


              <div className="plan-service-summary">

                <small>
                  {plan.requested_outcome}
                </small>

                <strong>
                  {plan.service_name}
                </strong>

                <span>
                  {plan.service_type_label}
                </span>

              </div>


              <div className="plan-recommendation">

                <span>
                  {copy.recommended}
                </span>

                <p>
                  {plan.recommended_option}
                </p>

                {plan.customer_edit_instruction && (
                  <small>
                    ↳{" "}
                    {plan.customer_edit_instruction}
                  </small>
                )}

              </div>


              <h4 className="live-section-title">
                {copy.actions}
              </h4>


              <div className="live-action-list">

                {(plan.actions || []).map(
                  (action, index) => (

                    <article
                      key={`${action.sequence}-${index}`}
                    >

                      <span>
                        {String(
                          index + 1
                        ).padStart(
                          2,
                          "0"
                        )}
                      </span>


                      <div>

                        <strong>
                          {action.title}
                        </strong>


                        <p>
                          {action.detail}
                        </p>


                        <small>
                          {action.evidence}
                        </small>

                      </div>

                    </article>

                  )
                )}

              </div>


              {(plan.protected_steps || [])
                .length > 0 && (

                <div className="protected-plan-box">

                  <span>
                    {copy.protected}
                  </span>


                  {plan.protected_steps.map(
                    (item) => (

                      <p key={item.step_number}>
                        🔒 {item.step} ·{" "}
                        {item.level}
                      </p>

                    )
                  )}

                </div>

              )}


              {editOpen ? (

                <PlanOptionsEditor
                  key={`${journey.id}-${journey.plan_version}`}
                  plan={plan}
                  lang={lang}
                  busy={busy}
                  onSubmit={handleEdit}
                  onCancel={() =>
                    setEditOpen(false)
                  }
                />

              ) : (

                <div className="plan-approval-actions">

                  <button
                    className="secondary"
                    onClick={() =>
                      setEditOpen(true)
                    }
                  >
                    {copy.edit}
                  </button>


                  <button
                    onClick={
                      handleApprovePlan
                    }
                    disabled={busy}
                  >
                    {isCase
                      ? copy.approveSubmission
                      : copy.approve}
                  </button>

                </div>

              )}

            </div>


            <aside className="plan-side-stack">

              {requiresPayment ? (

                <div className="live-side-card">

                  <span>
                    {copy.fee}
                  </span>

                  <strong>
                    {feeLabel}
                  </strong>

                  <small>
                    {plan.fee_source}
                  </small>

                </div>

              ) : (

                <div className="live-side-card">

                  <span>
                    {copy.journeyType}
                  </span>

                  <strong>
                    {plan.service_type_label}
                  </strong>

                  <small>
                    {plan.fee_status ===
                    "VERIFY"
                      ? copy.feeNeedsReview
                      : copy.noPayment}
                  </small>

                </div>

              )}


              <div className="live-side-card">

                <span>
                  {copy.sla}
                </span>


                {(plan.sla || []).map(
                  (item) => (

                    <strong key={item}>
                      {item}
                    </strong>

                  )
                )}

              </div>


              <div className="live-side-card">

                <span>
                  {copy.integrations}
                </span>


                {(plan.integrations || []).map(
                  (item, index) => (

                    <p key={index}>

                      <b>
                        {item.status ||
                          copy.proposed}
                      </b>

                      {item.description}

                    </p>

                  )
                )}

              </div>

            </aside>

          </section>
        )}


      {screen === "handoff" &&
        requiresPayment && (
          <section className="live-focus-card payment-live-card service-checkpoint-card">

            <span className="live-card-kicker">

              {serviceKind ===
              "INTERNATIONAL_SHIPMENT"
                ? copy.emxCheckpointKicker
                : copy.licenceCheckpointKicker}

            </span>


            <h3>

              {serviceKind ===
              "INTERNATIONAL_SHIPMENT"
                ? copy.shipmentHandoffTitle
                : copy.licenceAssessmentTitle}

            </h3>


            <p>

              {serviceKind ===
              "INTERNATIONAL_SHIPMENT"
                ? copy.shipmentHandoffText
                : copy.licenceAssessmentText}

            </p>


            <div className="checkpoint-action-list">

              {(plan.actions || [])
                .filter(
                  (action) =>
                    action.phase ===
                    "PRE_PAYMENT"
                )
                .map(
                  (action) => (

                    <div key={action.sequence}>

                      <span>
                        ✓
                      </span>


                      <div>

                        <strong>
                          {action.title}
                        </strong>


                        <small>
                          {copy.completedBeforePayment}
                        </small>

                      </div>

                    </div>

                  )
                )}

            </div>


            <button
              className="payment-submit"
              disabled={busy}
              onClick={
                handlePaymentAssessment
              }
            >

              {busy
                ? "…"
                : serviceKind ===
                  "INTERNATIONAL_SHIPMENT"
                  ? copy.shipmentHandoffButton
                  : copy.licenceAssessmentButton}

            </button>

          </section>
        )}


      {screen === "quote" &&
        serviceKind ===
          "INTERNATIONAL_SHIPMENT" && (

          <section className="live-focus-card payment-live-card service-checkpoint-card quote-ready-card">

            <span className="live-card-kicker">
              {copy.quoteReadyKicker}
            </span>


            <h3>
              {copy.quoteTitle}
            </h3>


            <p>
              {copy.quoteText}
            </p>


            <div className="payment-amount-panel">

              <span>
                {copy.fee}
              </span>

              <strong>
                {feeLabel}
              </strong>

              <small>
                {plan.fee_source}
              </small>

            </div>


            <button
              className="payment-submit"
              onClick={() =>
                setScreen("payment")
              }
            >
              {copy.continuePayment}
            </button>

          </section>
        )}


      {screen === "payment" &&
        requiresPayment &&
        journeyView === "customer" && (

          <section className="live-focus-card payment-live-card customer-payment-card">

            <span className="live-card-kicker">
              {copy.customerJourney}
            </span>


            <h3>
              {copy.customerPaymentTitle}
            </h3>


            <p>
              {copy.customerPaymentText}
            </p>


            <div className="customer-service-receipt payment-receipt">

              <div>

                <span>
                  {copy.service}
                </span>

                <strong>
                  {plan.service_name}
                </strong>

              </div>


              <div>

                <span>
                  {copy.amount}
                </span>

                <strong>
                  {feeLabel}
                </strong>

              </div>

            </div>


            <label className="payment-consent">

              <input
                checked={paymentApproved}
                disabled={!paymentReady}
                onChange={(event) =>
                  setPaymentApproved(
                    event.target.checked
                  )
                }
                type="checkbox"
              />


              <span>
                {copy.customerPaymentConsent}
              </span>

            </label>


            <button
              className="payment-submit"
              disabled={
                !paymentApproved ||
                !paymentReady ||
                busy
              }
              onClick={handlePayment}
            >
              {busy
                ? "…"
                : copy.pay}
            </button>

          </section>
        )}


      {screen === "payment" &&
        requiresPayment &&
        journeyView === "agent" && (

          <section className="live-focus-card payment-live-card">

            <span className="live-card-kicker">
              {copy.securePaymentKicker}
            </span>


            <h3>
              {isBankTransfer
                ? copy.bankTransferTitle
                : copy.paymentTitle}
            </h3>


            <p>
              {isBankTransfer
                ? copy.bankTransferText
                : copy.paymentText}
            </p>


            <div className="payment-amount-panel">

              <span>
                {copy.fee}
              </span>

              <strong>
                {feeLabel}
              </strong>

              <small>
                {copy.beneficiary}
              </small>

            </div>


            <div className="sandbox-card-visual">

              <span>
                {isBankTransfer
                  ? "SANDBOX BANK TRANSFER"
                  : "ZERO GOVERNMENT PAYMENT"}
              </span>

              <strong>
                {isBankTransfer
                  ? "BANK · TRANSFER"
                  : "•••• 2026"}
              </strong>

              <small>
                {customer?.name}
              </small>

            </div>


            <label className="payment-consent">

              <input
                type="checkbox"
                checked={paymentApproved}
                disabled={!paymentReady}
                onChange={(event) =>
                  setPaymentApproved(
                    event.target.checked
                  )
                }
              />


              <span>
                {isBankTransfer
                  ? copy.bankTransferApprove
                  : copy.paymentApprove}
              </span>

            </label>


            <button
              className="payment-submit"
              disabled={
                !paymentApproved ||
                !paymentReady ||
                busy
              }
              onClick={handlePayment}
            >

              {busy
                ? "…"
                : isBankTransfer
                  ? copy.bankTransferPay
                  : copy.pay}

            </button>

          </section>
        )}


      {screen === "execution" &&
        journeyView === "customer" && (

          <section className="live-focus-card compact-live-card customer-processing-card">

            <div
              className="customer-processing-orb"
              aria-hidden="true"
            >
              <span />
            </div>


            <span className="live-card-kicker">
              {copy.customerJourney}
            </span>


            <h3>
              {copy.customerProcessingTitle}
            </h3>


            <p>
              {copy.customerProcessingText}
            </p>

          </section>
        )}


      {screen === "execution" &&
        journeyView === "agent" && (

          <section className="execution-live-layout">

            <div className="live-focus-card execution-main-card">

              <div className="execution-heading">

                <div className="agent-executing-orb">
                  <span />
                </div>


                <div>

                  <span className="live-card-kicker">
                    {copy.agentExecutionKicker}
                  </span>


                  <h3>
                    {copy.executingTitle}
                  </h3>


                  <p>
                    {copy.executingText}
                  </p>

                </div>

              </div>


              <div className="execution-event-list">

                {(plan.actions || []).map(
                  (action, index) => {

                    const liveEvent =
                      events.find(
                        (item) =>
                          item.sequence ===
                          index + 1
                      );


                    const status =
                      liveEvent?.status ||
                      (
                        plan.payment_timing !==
                          "BEFORE_EXECUTION" &&
                        action.phase ===
                          "PRE_PAYMENT"
                          ? "COMPLETED"
                          : "QUEUED"
                      );


                    return (
                      <article
                        className={`execution-event ${status.toLowerCase()}`}
                        key={index}
                      >

                        <span className="event-status-dot" />


                        <div>

                          <strong>
                            {action.title}
                          </strong>


                          <p>
                            {action.detail}
                          </p>

                        </div>


                        <small>

                          {status === "COMPLETED"
                            ? copy.completed
                            : status === "RUNNING"
                              ? copy.running
                              : copy.queued}

                        </small>

                      </article>
                    );
                  }
                )}

              </div>

            </div>


            <aside className="execution-case-card">

              <span>
                {copy.case}
              </span>


              <strong>
                {journey.id
                  .slice(0, 13)
                  .toUpperCase()}
              </strong>


              <dl>

                <div>

                  <dt>
                    {copy.planVersion}
                  </dt>

                  <dd>
                    v{journey.plan_version}
                  </dd>

                </div>


                <div>

                  <dt>
                    {requiresPayment
                      ? copy.paymentReference
                      : copy.consentReference}
                  </dt>

                  <dd>
                    {requiresPayment
                      ? payment.reference
                      : plan.consent_reference}
                  </dd>

                </div>

              </dl>


              <button
                onClick={() =>
                  handleControl(
                    "handoff"
                  )
                }
              >
                {copy.handoff}
              </button>


              <button
                className="danger-control"
                onClick={() =>
                  handleControl(
                    "cancel"
                  )
                }
              >
                {copy.cancel}
              </button>

            </aside>

          </section>
        )}


      {screen === "complete" &&
        journeyView === "customer" && (

          <section className="live-focus-card success-live-card customer-success-card">

            <div className="success-check">
              ✓
            </div>


            <span className="live-card-kicker">
              {copy.customerJourney}
            </span>


            <h3>
              {copy.customerSuccessTitle}
            </h3>


            <p>
              {requiresPayment
                ? copy.customerSuccessPaid
                : copy.customerSuccessNoPayment}
            </p>


            <div className="customer-service-receipt completion-receipt">

              <div>

                <span>
                  {copy.service}
                </span>

                <strong>
                  {plan.service_name}
                </strong>

              </div>


              <div>

                <span>
                  {copy.receipt}
                </span>

                <strong>
                  {journey.id.toUpperCase()}
                </strong>

              </div>

            </div>


            <button onClick={onBack}>
              {copy.newJourney}
            </button>

          </section>
        )}


      {screen === "complete" &&
        journeyView === "agent" && (

          <section className="live-focus-card success-live-card">

            <div className="success-check">
              ✓
            </div>


            <span className="live-card-kicker">
              {copy.outcomeDeliveredKicker}
            </span>


            <h3>
              {copy.successTitle}
            </h3>


            <p>
              {copy.successText}
            </p>


            <div className="success-details-grid">

              <div>

                <span>
                  {copy.result}
                </span>

                <strong>
                  {plan.expected_outcome}
                </strong>

              </div>


              <div>

                <span>
                  {copy.reference}
                </span>

                <strong>
                  {journey.id.toUpperCase()}
                </strong>

              </div>


              <div>

                <span>
                  {copy.timing}
                </span>

                <strong>
                  {(plan.sla || []).join(
                    " · "
                  )}
                </strong>

              </div>


              <div>

                <span>
                  {copy.objection}
                </span>

                <strong>
                  {copy.objectionAvailable}
                </strong>

              </div>

            </div>


            <button onClick={onBack}>
              {copy.newJourney}
            </button>

          </section>
        )}


    </div>
  );
}


export default LiveAgentPage;