import re


SERVICE_ARCHETYPES = {
    "APPLICATION",
    "COMPLAINT",
    "DISPUTE_REFUND",
    "INFORMATION",
    "PURCHASE",
    "RENEWAL",
}

PAYMENT_CONTEXTS = {
    "COLLECT_FEE",
    "NONE",
    "REFUND_OR_DISPUTE",
    "UNKNOWN",
}


def _joined_service_text(service):
    fields = [
        service.get("service_name", ""),
        service.get("description", ""),
        *service.get("steps", []),
        *service.get("documents", []),
        *service.get("approvals", []),
        *service.get("manual_actions", []),
        *service.get("digital_actions", []),
        *service.get("dependencies", []),
    ]
    return " ".join(str(item) for item in fields if str(item).strip()).lower()


def _contains(text, signals):
    return any(signal in text for signal in signals)


def _matches(text, patterns):
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _explicit_archetype(value):
    normalized = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "CASE": "COMPLAINT",
        "GRIEVANCE": "COMPLAINT",
        "REFUND": "DISPUTE_REFUND",
        "DISPUTE": "DISPUTE_REFUND",
        "QUERY": "INFORMATION",
        "INQUIRY": "INFORMATION",
        "TRANSACTION": "APPLICATION",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in SERVICE_ARCHETYPES else None


def _explicit_payment_context(value):
    normalized = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "REQUIRED": "COLLECT_FEE",
        "PAYMENT_REQUIRED": "COLLECT_FEE",
        "NOT_REQUIRED": "NONE",
        "NO_FEE": "NONE",
        "FREE": "NONE",
        "REFUND": "REFUND_OR_DISPUTE",
        "DISPUTE": "REFUND_OR_DISPUTE",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in PAYMENT_CONTEXTS else None


def classify_service(service):
    """Return a conservative, bilingual capability profile for any service.

    The classifier deliberately separates money mentioned as the subject of a
    complaint/refund from money the customer must pay to execute the service.
    Only explicit fee-collection evidence creates a payment stage. An unknown
    fee never creates a simulated charge; it is flagged for Blueprint review.
    """

    text = _joined_service_text(service)
    name_text = str(service.get("service_name", "")).strip().lower()

    is_international_shipment = _matches(text, [
        r"international\s+(?:shipment|shipping|parcel)",
        r"send\s+(?:an?\s+)?international\s+(?:shipment|parcel)",
        r"إرسال\s+شحنة\s+دولية",
        r"شحن(?:ة|ه).{0,35}(?:دولي|خارج\s+دولة\s+الإمارات)",
        r"(?:دولي|خارج\s+دولة\s+الإمارات).{0,35}(?:شحن(?:ة|ه)|طرد)",
    ])
    is_postal_activity_license = _matches(text, [
        r"postal\s+activit(?:y|ies)\s+licen[cs]e",
        r"licen[cs]e.{0,30}postal\s+activit",
        r"ترخيص\s+مزاولة\s+الأنشطة\s+البريدية",
        r"ترخيص.{0,35}أنشط(?:ة|ه)\s+بريدية",
    ])
    service_kind = (
        "INTERNATIONAL_SHIPMENT"
        if is_international_shipment
        else "POSTAL_ACTIVITY_LICENSE"
        if is_postal_activity_license
        else "GENERAL"
    )

    complaint_signals = [
        "complaint", "complain", "grievance", "service issue",
        "شكوى", "شكوي", "بلاغ", "تظلم", "تظلّم",
    ]
    dispute_refund_signals = [
        "refund", "chargeback", "dispute", "unauthorized charge",
        "duplicate charge", "charged twice", "billing error", "appeal",
        "استرداد", "استرجاع المبلغ", "نزاع", "اعتراض", "خصم غير مصرح",
        "خصم مرتين", "خصم مبلغ", "تم الخصم", "مبلغ مخصوم",
    ]
    information_signals = [
        "information service", "inquiry", "enquiry", "check status",
        "track status", "tracking", "faq", "guidance",
        "خدمة معلومات", "استعلام", "استفسار", "تتبع", "متابعة الحالة",
        "معرفة حالة", "دليل إرشادي",
    ]
    renewal_signals = [
        "renew", "renewal", "extend subscription", "تجديد", "تمديد الاشتراك",
    ]
    purchase_signals = [
        "purchase", "buy", "rent", "book", "booking", "subscribe",
        "شراء", "استئجار", "استأجر", "استاجر", "حجز", "اشتراك جديد",
    ]

    explicit_archetype = _explicit_archetype(service.get("service_type"))
    name_has_complaint = _contains(name_text, complaint_signals)
    name_has_dispute_refund = _contains(name_text, dispute_refund_signals)
    name_has_renewal = _contains(name_text, renewal_signals)
    name_has_purchase = _contains(name_text, purchase_signals)
    name_has_information = _contains(name_text, information_signals)
    has_complaint = _contains(text, complaint_signals)
    has_dispute_refund = _contains(text, dispute_refund_signals)
    has_information = _contains(text, information_signals)
    has_renewal = _contains(text, renewal_signals)
    has_purchase = _contains(text, purchase_signals)

    if explicit_archetype:
        archetype = explicit_archetype
        archetype_evidence = "Explicit service_type supplied by the service owner."
    elif name_has_dispute_refund:
        archetype = "DISPUTE_REFUND"
        archetype_evidence = "The service name explicitly identifies a refund or dispute."
    elif name_has_complaint and has_dispute_refund:
        archetype = "DISPUTE_REFUND"
        archetype_evidence = "The complaint concerns a refund or financial dispute."
    elif name_has_complaint:
        archetype = "COMPLAINT"
        archetype_evidence = "The service name explicitly identifies a complaint."
    elif name_has_renewal:
        archetype = "RENEWAL"
        archetype_evidence = "The service name explicitly identifies a renewal."
    elif name_has_purchase:
        archetype = "PURCHASE"
        archetype_evidence = "The service name explicitly identifies a purchase, rental or booking."
    elif name_has_information and not is_international_shipment:
        archetype = "INFORMATION"
        archetype_evidence = "The service name explicitly identifies an inquiry or information service."
    elif is_international_shipment:
        archetype = "PURCHASE"
        archetype_evidence = "The service creates and executes an international shipment journey."
    elif has_dispute_refund:
        archetype = "DISPUTE_REFUND"
        archetype_evidence = "Refund, objection or financial-dispute language was detected."
    elif has_complaint:
        archetype = "COMPLAINT"
        archetype_evidence = "Complaint or grievance language was detected."
    elif has_purchase:
        archetype = "PURCHASE"
        archetype_evidence = "Purchase, booking, rental or subscription language was detected."
    elif has_renewal:
        archetype = "RENEWAL"
        archetype_evidence = "Renewal language was detected."
    elif has_information:
        archetype = "INFORMATION"
        archetype_evidence = "Inquiry, tracking or information language was detected."
    else:
        archetype = "APPLICATION"
        archetype_evidence = "No narrower pattern was confirmed; using the general application pattern."

    explicit_payment = _explicit_payment_context(
        service.get("payment_requirement")
        or service.get("payment_context")
    )
    explicit_no_fee = _contains(text, [
        "no fee", "no fees", "free of charge", "without charge",
        "fees: none", "fee: none", "بدون رسوم", "لا توجد رسوم",
        "لا يوجد رسوم", "مجاناً", "مجانا", "الرسوم: لا يوجد",
    ])
    fee_collection = _matches(text, [
        r"\b(customer|applicant|user|client)\s+(?:must\s+|will\s+)?(?:pay|pays|settles)\b",
        r"\b(?:pay|payment|settle)\s+(?:the\s+)?(?:service\s+)?fees?\b",
        r"\bservice\s+fees?\b",
        r"\bpayment\s+method\b",
        r"\bcomplete\s+(?:the\s+)?payment\b",
        r"\bcheckout\b",
        r"(?:العميل|المتعامل|مقدم الطلب).{0,30}(?:يدفع|يسدد)",
        r"(?:دفع|سداد)\s+(?:رسوم|المبلغ)",
        r"رسوم\s+(?:الخدمة|التقديم|الطلب|التجديد|الإصدار|اصدار|تقديم الشكوى)",
        r"وسيلة\s+الدفع",
        r"إتمام\s+الدفع",
        r"المبلغ\s+الإجمالي",
    ])
    has_currency_amount = _matches(text, [
        r"(?:aed|درهم(?:اً|ا)?)\s*[:\-]?\s*\d",
        r"\d[\d,]*(?:\.\d+)?\s*(?:aed|درهم)",
    ])

    if explicit_payment:
        payment_context = explicit_payment
        payment_evidence = "Explicit payment requirement supplied by the service owner."
    elif fee_collection:
        payment_context = "COLLECT_FEE"
        payment_evidence = "A customer fee-collection action was explicitly detected."
    elif archetype == "DISPUTE_REFUND":
        payment_context = "REFUND_OR_DISPUTE"
        payment_evidence = "Money is part of a refund/dispute outcome, not a new customer payment."
    elif explicit_no_fee:
        payment_context = "NONE"
        payment_evidence = "The supplied service explicitly states that no fee is required."
    elif archetype in {"COMPLAINT", "INFORMATION"}:
        payment_context = "NONE"
        payment_evidence = "No fee collection was found in this non-transactional service pattern."
    elif has_currency_amount and archetype in {"PURCHASE", "RENEWAL", "APPLICATION"}:
        payment_context = "COLLECT_FEE"
        payment_evidence = "A currency amount was found in a transactional service pattern."
    else:
        payment_context = "UNKNOWN"
        payment_evidence = "The supplied journey does not confirm whether a service fee applies."

    explicit_package_choice = _matches(text, [
        r"\b(?:choose|select|change|compare)\s+(?:a\s+|the\s+)?(?:service\s+|subscription\s+)?(?:package|plan|tier|bundle)\b",
        r"\bsubscription\s+package\b",
        r"\bpricing\s+(?:plan|tier)\b",
        r"(?:يختار|تغيير|يغير|يقارن).{0,20}(?:باقة|باقه|حزمة|حزمه|خطة اشتراك)",
    ])
    if is_international_shipment:
        explicit_package_choice = True

    human_decision_signals = [
        "committee", "notary", "field inspection", "supervisor approves",
        "authorized officer", "legal judgement", "investigation",
        "case officer", "manual review", "eligibility decision",
        "كاتب العدل", "لجنة", "لجنه", "تفتيش ميداني", "تحقيق",
        "المشرف يعتمد", "المدير يعتمد", "موظف مخول", "قرار قانوني",
        "مراجعة بشرية", "دراسة الشكوى", "الإدارة المختصة",
    ]
    requires_human_decision = (
        archetype in {"COMPLAINT", "DISPUTE_REFUND"}
        or is_postal_activity_license
        or _contains(text, human_decision_signals)
    )

    consent_mode = (
        "DEFERRED_PAYMENT_AND_EXECUTION"
        if is_international_shipment and payment_context == "COLLECT_FEE"
        else "PAYMENT_AND_EXECUTION"
        if payment_context == "COLLECT_FEE"
        else "CASE_SUBMISSION"
        if archetype in {"COMPLAINT", "DISPUTE_REFUND"}
        else "EXECUTION"
    )

    if is_international_shipment:
        fee_model = "WEIGHT_BASED_QUOTE"
        payment_timing = "AFTER_PHYSICAL_VERIFICATION"
        payment_method = "CARD_OR_DIGITAL"
        payment_provider = "EMX"
        annual_fee_rate = None
        minimum_fee = None
    elif is_postal_activity_license:
        fee_model = "ANNUAL_REVENUE_PERCENTAGE_WITH_MINIMUM"
        payment_timing = "AFTER_APPLICATION_APPROVAL"
        payment_method = "BANK_TRANSFER"
        payment_provider = "Emirates Post Group"
        annual_fee_rate = 10.0
        minimum_fee = 100000.0
    else:
        fee_model = "FIXED_OR_CATALOG"
        payment_timing = "BEFORE_EXECUTION"
        payment_method = "DIGITAL_PAYMENT"
        payment_provider = None
        annual_fee_rate = None
        minimum_fee = None

    return {
        "service_archetype": archetype,
        "service_kind": service_kind,
        "archetype_evidence": archetype_evidence,
        "payment_context": payment_context,
        "payment_evidence": payment_evidence,
        "requires_customer_payment": payment_context == "COLLECT_FEE",
        "payment_verification_required": payment_context == "UNKNOWN",
        "has_package_stage": explicit_package_choice,
        "requires_human_decision": requires_human_decision,
        "consent_mode": consent_mode,
        "fee_model": fee_model,
        "payment_timing": payment_timing,
        "payment_method": payment_method,
        "payment_provider": payment_provider,
        "annual_fee_rate": annual_fee_rate,
        "minimum_fee": minimum_fee,
        "physical_handoff_required": is_international_shipment,
    }


def service_type_label(archetype, lang="en"):
    labels = {
        "ar": {
            "APPLICATION": "طلب خدمة",
            "COMPLAINT": "شكوى",
            "DISPUTE_REFUND": "اعتراض أو استرداد",
            "INFORMATION": "خدمة معلوماتية",
            "PURCHASE": "شراء أو حجز",
            "RENEWAL": "تجديد",
        },
        "en": {
            "APPLICATION": "Service application",
            "COMPLAINT": "Complaint",
            "DISPUTE_REFUND": "Dispute or refund",
            "INFORMATION": "Information service",
            "PURCHASE": "Purchase or booking",
            "RENEWAL": "Renewal",
        },
    }
    selected = labels["ar" if lang == "ar" else "en"]
    return selected.get(archetype, selected["APPLICATION"])
