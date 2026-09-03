from core.service_classifier import classify_service
from core.pricing_catalog import build_pricing_catalog, calculate_price_breakdown


def _idp_service(lang="ar"):
    return {
        "service_name": "إصدار رخصة قيادة دولية" if lang == "ar" else "International Driving Permit",
        "description": (
            "الرسوم أونلاين: 199.50 درهم شاملة التوصيل والضريبة، والرخصة صالحة لمدة سنة."
            if lang == "ar"
            else "Online fees: AED 199.50 inclusive of delivery and tax. The permit is valid for one year."
        ),
        "steps": [
            "تسجيل الدخول باستخدام UAE PASS" if lang == "ar" else "Sign in using UAE PASS",
            "دفع الرسوم" if lang == "ar" else "Pay the fee",
            "إصدار الرخصة" if lang == "ar" else "Issue the permit",
        ],
        "lang": lang,
    }


def test_idp_arabic_fixed_online_fee_is_detected():
    service = _idp_service("ar")
    classification = classify_service(service)
    pricing = build_pricing_catalog(service, classification, "ar")
    assert pricing["packages"][0]["price_per_year"] == 199.50
    breakdown = calculate_price_breakdown(pricing, "fixed-service-fee", years=1)
    assert breakdown["total"] == 199.50
    assert breakdown["currency"] == "AED"


def test_idp_english_fixed_online_fee_is_detected():
    service = _idp_service("en")
    classification = classify_service(service)
    pricing = build_pricing_catalog(service, classification, "en")
    assert pricing["packages"][0]["price_per_year"] == 199.50
