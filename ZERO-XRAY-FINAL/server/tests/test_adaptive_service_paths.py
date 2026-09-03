import tempfile
import unittest
from pathlib import Path

from agents.journey_builder_agent import JourneyBuilderAgent
from core.runtime_store import RuntimeStore
from core.service_classifier import classify_service
from core.service_input_normalizer import normalize_service_input
from core.pricing_catalog import build_pricing_catalog, calculate_price_breakdown


class AdaptiveServiceClassificationTests(unittest.TestCase):
    def test_customer_inquiry_is_information_service_without_payment(self):
        service = {
            "service_name": "Customer Inquiry Service",
            "description": "Ask about service requirements, fees, documents or application status. No fee.",
            "steps": [
                "Sign in with UAE PASS",
                "Select the inquiry topic",
                "Receive a sourced answer",
            ],
            "service_type": "INFORMATION",
            "payment_requirement": "NOT_REQUIRED",
        }

        classification = classify_service(service)

        self.assertEqual(classification["service_archetype"], "INFORMATION")
        self.assertEqual(classification["payment_context"], "NONE")
        self.assertFalse(classification["requires_customer_payment"])

    def test_new_po_box_is_not_misclassified_by_auto_renewal_text(self):
        service = {
            "service_name": "استأجر صندوق بريد الأفراد",
            "description": "رسوم التسجيل 70 درهم. التجديد التلقائي الاختياري متاح.",
            "steps": ["تسجيل الدخول", "اختيار الباقة", "دفع رسوم الخدمة"],
        }
        self.assertEqual(classify_service(service)["service_archetype"], "PURCHASE")

    def test_international_shipment_is_not_reduced_to_tracking_information(self):
        service = {
            "service_name": "إرسال شحنة دولية",
            "description": "شحن دولي مع رقم تتبع",
            "steps": ["تجهيز الشحنة", "دفع رسوم الشحن", "استلام رقم التتبع"],
        }
        self.assertEqual(classify_service(service)["service_archetype"], "PURCHASE")

    def test_raw_page_extracts_only_the_procedure(self):
        raw = """استأجر صندوق بريد الشركات
تقييم الخدمة
صندوق بريد أساسي
995 A
إظهار الميزات
رسوم تسجيل 70 A
إجراءات الخدمة
1
تسجيل الدخول بالهوية الرقمية
2
اختيار الخدمة
3
إدخال البيانات
4
الدفع وتأكيد الطلب
الأسئلة الشائعة
تحقق من الأسئلة الشائعة"""
        normalized = normalize_service_input({
            "service_name": "استأجر صندوق بريد الشركات",
            "description": raw,
            "steps": raw.splitlines(),
        })
        self.assertEqual(normalized["steps"], [
            "تسجيل الدخول بالهوية الرقمية",
            "اختيار الخدمة",
            "إدخال البيانات",
            "الدفع وتأكيد الطلب",
        ])
        self.assertTrue(normalized["input_quality"]["procedure_section_detected"])

    def test_po_box_price_breakdown_keeps_fee_types_separate(self):
        service = {
            "service_name": "استأجر صندوق بريد الشركات",
            "description": "رسوم تسجيل 70 درهم. توكيل بريدي إضافي 100 درهم. رخصة تجارية إضافية 995 درهم.",
            "steps": ["اختيار الخدمة", "دفع رسوم الخدمة"],
        }
        classification = classify_service(service)
        pricing = build_pricing_catalog(service, classification, "ar")
        self.assertEqual([item["price_per_year"] for item in pricing["packages"]], [995.0, 2495.0, 11995.0])
        self.assertEqual(pricing["one_time_fees"][0]["amount"], 70.0)
        self.assertEqual(len(pricing["add_ons"]), 2)
        self.assertIsNone(pricing["tax"]["rate_percent"])
        breakdown = calculate_price_breakdown(
            pricing,
            "corporate-basic",
            years=2,
            add_on_quantities={"additional-postal-agent": 1},
        )
        self.assertEqual(breakdown["total"], 2160.0)
        self.assertEqual(
            [item["type"] for item in breakdown["line_items"]],
            ["PACKAGE", "ONE_TIME_FEE", "ADD_ON"],
        )

    def test_money_in_refund_complaint_does_not_create_payment(self):
        service = {
            "service_name": "تقديم شكوى عن خصم مبلغ مرتين",
            "description": "العميل دفع 100 درهم وتم الخصم مرتين ويريد استرداد المبلغ",
            "steps": [
                "العميل يرسل الشكوى",
                "الموظف يراجع المعاملة",
                "النظام يعيد المبلغ ويرسل القرار",
            ],
            "lang": "ar",
        }

        classification = classify_service(service)
        redesign = JourneyBuilderAgent().run(service, {}, {})

        self.assertEqual(classification["service_archetype"], "DISPUTE_REFUND")
        self.assertEqual(classification["payment_context"], "REFUND_OR_DISPUTE")
        self.assertFalse(classification["requires_customer_payment"])
        self.assertFalse(any(
            "payment" in step.get("component_categories", [])
            for step in redesign["future_steps"]
        ))
        self.assertEqual(
            [item["code"] for item in redesign["customer_only_actions"]],
            ["PLAN_APPROVAL_OR_EDIT"],
        )
        self.assertNotIn(
            "الدفع",
            redesign["agent_execution_explanation"]["pre_action_preview"]["title"],
        )

    def test_package_complaint_is_not_package_selection(self):
        service = {
            "service_name": "Track a package complaint",
            "description": "The customer complains that a parcel is delayed.",
            "steps": [
                "Customer provides the package tracking reference",
                "Case officer investigates the complaint",
                "System sends the complaint decision",
            ],
        }

        classification = classify_service(service)
        redesign = JourneyBuilderAgent().run(service, {}, {})

        self.assertEqual(classification["service_archetype"], "COMPLAINT")
        self.assertFalse(classification["has_package_stage"])
        self.assertNotIn(
            "PACKAGE_SELECTION",
            [item["code"] for item in redesign["customer_only_actions"]],
        )

    def test_paid_renewal_keeps_payment_path(self):
        service = {
            "service_name": "تجديد صندوق بريد",
            "description": "رسوم الخدمة 995 درهم",
            "steps": [
                "العميل يختار الباقة",
                "العميل يدفع رسوم التجديد",
                "النظام يجدد صندوق البريد",
            ],
            "lang": "ar",
        }

        classification = classify_service(service)
        redesign = JourneyBuilderAgent().run(service, {}, {})

        self.assertTrue(classification["requires_customer_payment"])
        self.assertEqual(classification["payment_context"], "COLLECT_FEE")
        self.assertIn(
            "PAYMENT",
            [item["code"] for item in redesign["customer_only_actions"]],
        )

    def test_unknown_fee_is_flagged_without_fake_payment(self):
        service = {
            "service_name": "طلب تصريح جديد",
            "description": "تقديم طلب تصريح",
            "steps": [
                "العميل يرفع المستندات",
                "الموظف يراجع الطلب",
                "النظام يصدر النتيجة",
            ],
            "lang": "ar",
        }

        classification = classify_service(service)

        self.assertEqual(classification["payment_context"], "UNKNOWN")
        self.assertTrue(classification["payment_verification_required"])
        self.assertFalse(classification["requires_customer_payment"])

    def test_international_shipment_uses_post_weighing_quote(self):
        service = {
            "service_name": "إرسال شحنة دولية",
            "description": "إرسال مستندات أو طرود خارج دولة الإمارات عبر EMX",
            "steps": [
                "تحديد الوجهة ونوع الشحنة والوزن والأبعاد",
                "اختيار باقة الشحن ستاندرد أو إكسبريس أو بريميوم",
                "استلام المندوب للشحنة والتحقق من الوزن والأبعاد",
                "دفع رسوم الشحن بعد تأكيد السعر",
                "استلام رقم التتبع",
            ],
            "lang": "ar",
        }

        classification = classify_service(service)

        self.assertEqual(classification["service_kind"], "INTERNATIONAL_SHIPMENT")
        self.assertEqual(classification["fee_model"], "WEIGHT_BASED_QUOTE")
        self.assertEqual(
            classification["payment_timing"],
            "AFTER_PHYSICAL_VERIFICATION",
        )
        self.assertTrue(classification["requires_customer_payment"])
        self.assertTrue(classification["physical_handoff_required"])

    def test_postal_activity_license_uses_percentage_with_minimum(self):
        service = {
            "service_name": "إصدار ترخيص مزاولة الأنشطة البريدية",
            "description": "ترخيص الشركات لمزاولة نقل الوثائق والطرود",
            "steps": [
                "تقديم الطلب والمستندات",
                "استلام الموافقة",
                "دفع الرسوم عن طريق التحويل البنكي",
                "الرسوم 10% سنويًا من إجمالي مبيعات الأنشطة البريدية بحد أدنى 100,000 درهم",
            ],
            "lang": "ar",
        }

        classification = classify_service(service)

        self.assertEqual(classification["service_kind"], "POSTAL_ACTIVITY_LICENSE")
        self.assertEqual(
            classification["fee_model"],
            "ANNUAL_REVENUE_PERCENTAGE_WITH_MINIMUM",
        )
        self.assertEqual(classification["annual_fee_rate"], 10.0)
        self.assertEqual(classification["minimum_fee"], 100000.0)
        self.assertEqual(classification["payment_method"], "BANK_TRANSFER")


class AdaptiveRuntimeTests(unittest.TestCase):
    def _journey_for(self, store, service):
        redesign = JourneyBuilderAgent().run(service, {}, {})
        blueprint = store.save_blueprint(service, {"redesign": redesign})
        customer = store.register_customer("Demo User", "demo@example.com")
        return store.create_journey(
            customer["id"],
            f"Complete {service['service_name']}",
            blueprint_id=blueprint["id"],
            lang=service.get("lang", "en"),
            sandbox=True,
        )

    def test_complaint_executes_after_consent_without_payment(self):
        service = {
            "service_name": "تقديم شكوى",
            "description": "تقديم شكوى ومتابعتها حتى القرار",
            "steps": [
                "العميل يكتب تفاصيل الشكوى ويرفق الدليل",
                "الموظف يحقق في الشكوى",
                "النظام يرسل القرار النهائي",
            ],
            "waiting_times": ["5 أيام عمل"],
            "lang": "ar",
        }
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            journey = self._journey_for(store, service)

            self.assertFalse(journey["plan"]["requires_payment"])
            self.assertEqual(journey["plan"]["service_archetype"], "COMPLAINT")
            approved = store.approve_plan(journey["id"])
            self.assertTrue(approved["plan"]["consent_reference"].startswith("CNS-"))
            with self.assertRaisesRegex(ValueError, "not required"):
                store.pay(journey["id"], "SANDBOX_CARD")
            executing = store.start_execution(journey["id"])
            self.assertEqual(executing["state"], "EXECUTING")

    def test_paid_service_still_requires_confirmed_payment(self):
        service = {
            "service_name": "Renew subscription",
            "description": "Customer pays AED 120 service fee",
            "steps": [
                "Customer selects a subscription plan",
                "Customer pays the service fee",
                "System renews the subscription",
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            journey = self._journey_for(store, service)

            self.assertTrue(journey["plan"]["requires_payment"])
            store.approve_plan(journey["id"])
            with self.assertRaisesRegex(ValueError, "Confirmed payment"):
                store.start_execution(journey["id"])
            paid = store.pay(journey["id"], "SANDBOX_CARD")
            self.assertEqual(paid["state"], "PAID")
            executing = store.start_execution(journey["id"])
            self.assertEqual(executing["state"], "EXECUTING")

    def test_international_shipment_waits_for_emx_quote_before_payment(self):
        service = {
            "service_name": "إرسال شحنة دولية",
            "description": "خدمة شحن دولي تديرها EMX",
            "steps": [
                "اختيار باقة الشحن ستاندرد أو إكسبريس أو بريميوم",
                "تسليم الشحنة للمندوب ليؤكد الوزن والأبعاد",
                "دفع رسوم الشحن",
                "استلام رقم التتبع",
            ],
            "lang": "ar",
        }
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            journey = self._journey_for(store, service)

            plan = journey["plan"]
            self.assertIsNone(plan["fee_amount"])
            self.assertEqual(plan["fee_status"], "PENDING_PHYSICAL_VERIFICATION")
            self.assertEqual(
                [item["id"] for item in plan["edit_options"]["packages"]],
                ["standard", "express", "premium"],
            )

            approved = store.approve_plan(journey["id"])
            with self.assertRaises(ValueError):
                store.pay(approved["id"], "SANDBOX_CARD")
            assessed = store.prepare_payment_assessment(approved["id"])
            self.assertEqual(assessed["state"], "AWAITING_PAYMENT")
            self.assertEqual(assessed["plan"]["fee_amount"], 185.0)
            self.assertEqual(
                assessed["plan"]["physical_checkpoint"]["status"],
                "COMPLETED",
            )
            paid = store.pay(assessed["id"], "SANDBOX_CARD")
            executing = store.start_execution(paid["id"])
            statuses = [item["status"] for item in store.list_events(executing["id"])]
            self.assertIn("COMPLETED", statuses)
            self.assertIn("QUEUED", statuses)

    def test_postal_license_shows_annual_rule_and_bank_transfer(self):
        service = {
            "service_name": "إصدار ترخيص مزاولة الأنشطة البريدية",
            "description": "إصدار ترخيص للشركات",
            "steps": [
                "استرجاع مستندات الشركة وتقديم الطلب",
                "استلام الموافقة",
                "دفع الرسوم عن طريق التحويل البنكي",
                "10% سنويًا من إجمالي مبيعات الأنشطة البريدية بحد أدنى 100,000 درهم",
                "استلام الرخصة وتفعيلها",
            ],
            "lang": "ar",
        }
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStore(Path(directory) / "runtime.db")
            journey = self._journey_for(store, service)

            plan = journey["plan"]
            self.assertEqual(plan["fee_amount"], 100000.0)
            self.assertEqual(plan["annual_fee_rate"], 10.0)
            self.assertEqual(plan["minimum_fee"], 100000.0)
            self.assertEqual(plan["payment_method"], "BANK_TRANSFER")
            self.assertEqual(plan["edit_options"]["packages"], [])
            self.assertIn("10%", plan["fee_source"])

            approved = store.approve_plan(journey["id"])
            assessed = store.prepare_payment_assessment(approved["id"])
            paid = store.pay(assessed["id"], "SANDBOX_BANK_TRANSFER")
            self.assertEqual(paid["payment"]["method"], "SANDBOX_BANK_TRANSFER")


if __name__ == "__main__":
    unittest.main()
