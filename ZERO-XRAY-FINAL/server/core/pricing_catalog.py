import re


def _text(service):
    fields = [
        service.get("service_name", ""),
        service.get("description", ""),
        *(service.get("steps") or []),
    ]
    return " ".join(str(item) for item in fields if str(item).strip()).lower()


def _fixed_fee(text):
    patterns = [
        # Labeled fee followed by an amount. Accept both common UAE formats:
        # "Fees online: AED 199.50" and "الرسوم أونلاين: 199.50 درهم".
        r"(?:online\s+fees?|fees?|service\s+fee|renewal\s+fee|application\s+fee|price|cost|الرسوم(?:\s+أونلاين)?|رسوم\s+(?:الخدمة|التجديد|التقديم|الطلب|الإصدار|اصدار)|السعر|التكلفة)[^\d]{0,30}(?:aed|درهم)?\s*([\d,]+(?:\.\d+)?)\s*(?:aed|درهم)?",
        r"(?:customer|applicant|العميل|المتعامل).{0,30}(?:pays?|يدفع|يسدد)[^\d]{0,15}(?:aed|درهم)?\s*([\d,]+(?:\.\d+)?)\s*(?:aed|درهم)?",
        r"(?:aed|درهم)\s*([\d,]+(?:\.\d+)?)\s*(?:service\s+fee|fees?|رسوم\s+الخدمة|الرسوم)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _tax_policy(text, lang):
    rate_match = re.search(
        r"(?:vat|value\s+added\s+tax|ضريبة\s+القيمة\s+المضافة)[^\d%]{0,20}(\d+(?:\.\d+)?)\s*%",
        text,
        flags=re.IGNORECASE,
    )
    inclusive = bool(re.search(
        r"(?:inclusive\s+of\s+vat|vat\s+included|شامل(?:ة)?\s+ضريبة|الأسعار\s+شاملة\s+الضريبة)",
        text,
        flags=re.IGNORECASE,
    ))
    if not rate_match:
        return {
            "status": "NOT_CONFIRMED",
            "rate_percent": None,
            "included_in_displayed_prices": None,
            "label": (
                "لم تُحدد الضريبة في بيانات الخدمة؛ لن يضيف النظام ضريبة تقديرية."
                if lang == "ar"
                else "Tax was not supplied; the system will not invent an estimated tax."
            ),
        }
    rate = float(rate_match.group(1))
    return {
        "status": "CONFIRMED",
        "rate_percent": rate,
        "included_in_displayed_prices": inclusive,
        "label": (
            f"ضريبة قيمة مضافة {rate:g}%" + (" مشمولة في الأسعار" if inclusive else " تُضاف إلى الإجمالي")
            if lang == "ar"
            else f"{rate:g}% VAT" + (" included in displayed prices" if inclusive else " added to the total")
        ),
    }


def build_pricing_catalog(service, classification, lang="en"):
    """Separate packages, one-time fees, add-ons and tax.

    The P.O. Box catalogue below comes only from the service-owner content
    supplied with this project. Other services use a conservative fixed-fee
    detector and never turn every number on a page into a package.
    """

    text = _text(service)
    is_po_box = (
        ("p.o. box" in text or "po box" in text or "صندوق بريد" in text)
        and classification.get("service_kind") == "GENERAL"
    )
    is_corporate = is_po_box and (
        "corporate" in text
        or "business" in text
        or "الشركات" in text
        or "للشركات" in text
        or "المؤسسات الحكومية" in text
    )
    is_individual = is_po_box and not is_corporate and (
        "individual" in text
        or "personal" in text
        or "الأفراد" in text
        or "الافراد" in text
        or "فردي" in text
        or "صندوقي" in text
        or "منزلي" in text
    )

    packages = []
    if is_corporate:
        packages = [
            {
                "id": "corporate-basic",
                "name": "صندوق بريد أساسي" if lang == "ar" else "Basic P.O. Box",
                "description": "استلام البريد من الفرع" if lang == "ar" else "Collect mail from the branch",
                "price_per_year": 995.0,
                "billing_period": "YEAR",
            },
            {
                "id": "corporate-premium",
                "name": "صندوق بريد بريميوم" if lang == "ar" else "Premium P.O. Box",
                "description": "توصيل أسبوعي إلى الموقع" if lang == "ar" else "Weekly delivery to the location",
                "price_per_year": 2495.0,
                "billing_period": "YEAR",
            },
            {
                "id": "corporate-premium-plus",
                "name": "صندوق بريد بريميوم بلس" if lang == "ar" else "Premium Plus P.O. Box",
                "description": "توصيل يومي إلى الموقع" if lang == "ar" else "Daily delivery to the location",
                "price_per_year": 11995.0,
                "billing_period": "YEAR",
            },
        ]
    elif is_individual:
        packages = [
            {
                "id": "individual-mybox",
                "name": "صندوقي" if lang == "ar" else "MyBox",
                "description": "صندوق في أحد مواقع بريد الإمارات" if lang == "ar" else "A box at an Emirates Post location",
                "price_per_year": 300.0,
                "billing_period": "YEAR",
            },
            {
                "id": "individual-home",
                "name": "منزلي" if lang == "ar" else "MyHome",
                "description": "توصيل منزلي أسبوعي" if lang == "ar" else "Weekly home delivery",
                "price_per_year": 695.0,
                "billing_period": "YEAR",
            },
            {
                "id": "individual-home-instant",
               "name": "منزلي الفوري" if lang == "ar" else "MyHome Instant",
                "description": "توصيل إلى المنزل في اليوم التالي" if lang == "ar" else "Next-day home delivery",
                "price_per_year": 995.0,
                "billing_period": "YEAR",
            },
        ]
    else:
        amount = _fixed_fee(text)
        if amount is not None:
            packages = [{
                "id": "fixed-service-fee",
                "name": "رسوم الخدمة" if lang == "ar" else "Service fee",
                "price_per_year": amount,
                "billing_period": "YEAR" if classification.get("service_archetype") == "RENEWAL" else "ONCE",
            }]

    one_time_fees = []
    if is_po_box and re.search(r"رسوم\s+تسجيل|registration\s+fee", text, flags=re.IGNORECASE):
        one_time_fees.append({
            "id": "registration-fee",
            "name": "رسوم التسجيل" if lang == "ar" else "Registration fee",
            "amount": 70.0,
            "billing_period": "ONCE",
            "mandatory": True,
        })

    add_ons = []
    has_additional_agent = bool(re.search(
        r"(?:توكيل\s+بريدي\s+إضافي|وكيل(?:\s+بريدي)?\s+إضافي|إضافة\s+كل\s+وكيل\s+إضافي)|additional\s+postal\s+agent",
        text,
        flags=re.IGNORECASE,
    ))
    if has_additional_agent and (is_corporate or is_individual):
        add_ons.append({
            "id": "additional-postal-agent",
            "name": "توكيل بريدي إضافي" if lang == "ar" else "Additional postal agent",
            "unit_price": 100.0 if is_corporate else 50.0,
            "billing_period": "ONCE",
            "default_quantity": 0,
        })
    if is_corporate and re.search(r"رخصة\s+تجارية\s+إضافية|additional\s+trade\s+licen[cs]e", text, flags=re.IGNORECASE):
        add_ons.append({
            "id": "additional-trade-licence",
            "name": "رخصة تجارية إضافية" if lang == "ar" else "Additional trade licence",
            "unit_price": 995.0,
            "billing_period": "ONCE",
            "default_quantity": 0,
        })
            # قواعد مؤكدة لخدمة صندوق بريد الأفراد.
    is_new_individual_po_box = (
        is_individual
        and classification.get("service_archetype") == "PURCHASE"
    )

    # رسوم التسجيل تُضاف مرة واحدة عند الاستئجار الجديد.
    if (
        is_new_individual_po_box
        and not any(
            item.get("id") == "registration-fee"
            for item in one_time_fees
        )
    ):
        one_time_fees.append({
            "id": "registration-fee",
            "category": "registration_fee",
            "name": (
                "رسوم التسجيل"
                if lang == "ar"
                else "Registration fee"
            ),
            "amount": 70.0,
            "billing_period": "ONCE",
            "mandatory": True,
        })

    # الوكيل البريدي خدمة إضافية وليس باقة.
    if (
        is_individual
        and not any(
            item.get("id") == "additional-postal-agent"
            for item in add_ons
        )
    ):
        add_ons.append({
            "id": "additional-postal-agent",
            "category": "add_on",
            "name": (
                "وكيل بريدي إضافي"
                if lang == "ar"
                else "Additional postal agent"
            ),
            "unit_price": 50.0,
            "billing_period": "ONCE",
            "default_quantity": 0,
        })

    if is_individual:
        tax_policy = {
            "category": "tax",
            "status": "CONFIRMED",
            "rate_percent": 5.0,
            "included_in_displayed_prices": False,
            "label": (
                "ضريبة القيمة المضافة 5%"
                if lang == "ar"
                else "5% VAT"
            ),
        }
    else:
        tax_policy = _tax_policy(text, lang)

    return {
        "packages": packages,
        "contract_durations": [1, 2, 3, 5, 10] if is_po_box or classification.get("service_archetype") == "RENEWAL" else [],
        "auto_renewal_available": is_po_box or classification.get("service_archetype") == "RENEWAL",
        "one_time_fees": one_time_fees,
        "add_ons": add_ons,
        "tax": tax_policy,
        "currency": "AED",
        "catalog_source": "SERVICE_OWNER_INPUT",
    }


def calculate_price_breakdown(pricing, selected_package_id=None, years=1, add_on_quantities=None):
    packages = pricing.get("packages") or []
    selected = next(
        (item for item in packages if item.get("id") == selected_package_id),
        packages[0] if packages else None,
    )
    years = max(1, int(years or 1))
    quantities = add_on_quantities or {}
    line_items = []
    subtotal = 0.0

    if selected and selected.get("price_per_year") is not None:
        unit = float(selected["price_per_year"])
        multiplier = years if selected.get("billing_period") == "YEAR" else 1
        amount = unit * multiplier
        subtotal += amount
        line_items.append({
            "type": "PACKAGE",
            "id": selected.get("id"),
            "name": selected.get("name"),
            "unit_price": unit,
            "quantity": multiplier,
            "amount": amount,
        })

    for fee in pricing.get("one_time_fees") or []:
        if not fee.get("mandatory", True):
            continue
        amount = float(fee.get("amount") or 0)
        subtotal += amount
        line_items.append({
            "type": "ONE_TIME_FEE",
            "id": fee.get("id"),
            "name": fee.get("name"),
            "unit_price": amount,
            "quantity": 1,
            "amount": amount,
        })

    normalized_quantities = {}
    for add_on in pricing.get("add_ons") or []:
        quantity = max(0, min(99, int(quantities.get(add_on.get("id"), add_on.get("default_quantity", 0)) or 0)))
        normalized_quantities[add_on.get("id")] = quantity
        if not quantity:
            continue
        multiplier = years if add_on.get("billing_period") == "YEAR" else 1
        unit = float(add_on.get("unit_price") or 0)
        amount = unit * quantity * multiplier
        subtotal += amount
        line_items.append({
            "type": "ADD_ON",
            "id": add_on.get("id"),
            "name": add_on.get("name"),
            "unit_price": unit,
            "quantity": quantity * multiplier,
            "amount": amount,
        })

    tax_policy = pricing.get("tax") or {}
    tax_amount = 0.0
    if tax_policy.get("status") == "CONFIRMED" and not tax_policy.get("included_in_displayed_prices"):
        tax_amount = round(subtotal * float(tax_policy.get("rate_percent") or 0) / 100, 2)
        if tax_amount:
            line_items.append({
                "type": "TAX",
                "id": "vat",
                "name": tax_policy.get("label"),
                "unit_price": tax_amount,
                "quantity": 1,
                "amount": tax_amount,
            })

    total = round(subtotal + tax_amount, 2) if line_items else None
    return {
        "selected_package": selected,
        "contract_years": years,
        "add_on_quantities": normalized_quantities,
        "line_items": line_items,
        "subtotal": round(subtotal, 2) if line_items else None,
        "tax_amount": tax_amount if line_items else None,
        "total": total,
        "currency": pricing.get("currency", "AED"),
    }
