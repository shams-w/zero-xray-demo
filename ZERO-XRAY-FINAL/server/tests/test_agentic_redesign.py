import unittest

from agents.journey_builder_agent import JourneyBuilderAgent
from agents.step_compliance_agent import StepComplianceAgent
from agents.validation_agent import ValidationAgent
from core.rules import calculate_metrics
from core.scoring import calculate_zero_bureaucracy_score
from core.standards_catalog import STANDARDS_CATALOG


STANDARDS = {
    "applicable_standards": STANDARDS_CATALOG,
}


def service(name, steps):
    return {
        "service_name": name,
        "description": "\n".join(steps),
        "steps": steps,
        "documents": [],
        "actors": [],
        "approvals": [],
        "waiting_times": [],
        "manual_actions": [],
        "digital_actions": [],
        "dependencies": [],
        "branch_visits": 0,
    }


def analyze(value):
    compliance = StepComplianceAgent().run(
        value,
        {},
        STANDARDS,
    )
    redesign = JourneyBuilderAgent().run(
        value,
        compliance,
        STANDARDS,
    )
    metrics = calculate_metrics(value, redesign)
    metrics["zero_bureaucracy_score"] = (
        calculate_zero_bureaucracy_score(metrics)
    )
    validation = ValidationAgent().run(
        value,
        STANDARDS,
        redesign,
        metrics,
    )
    return compliance, redesign, metrics, validation


class AgenticRedesignTests(unittest.TestCase):
    def test_arabic_license_renewal_is_consolidated(self):
        value = service(
            "تجديد رخصة تجارية",
            [
                "العميل يطلب تجديد الرخصة",
                "العميل يرفع صورة من الرخصة الحالية",
                "الموظف يراجع البيانات",
                "الموظف يتأكد من عدم وجود مخالفات معلقة",
                "العميل يروح الفرع عشان يدفع رسوم التجديد",
                "الموظف يصدر الرخصة المجددة",
            ],
        )

        compliance, redesign, metrics, validation = analyze(value)

        self.assertEqual(metrics["current"]["steps"], 6)
        self.assertEqual(metrics["future"]["steps"], 5)
        self.assertEqual(metrics["future"]["customer_burden_steps"], 0)
        self.assertEqual(compliance["summary"]["review"], 0)
        self.assertEqual(validation["status"], "PASS")
        self.assertGreaterEqual(metrics["zero_bureaucracy_score"], 70)
        self.assertTrue(redesign["removed_steps"])

    def test_long_arabic_service_does_not_copy_steps(self):
        steps = [
            "العميل يحدد نوع النشاط التجاري المطلوب",
            "العميل يتأكد من توفر اسم الشركة التجاري",
            "العميل يحجز الاسم التجاري في الجهة المختصة",
            "العميل يحدد الشكل القانوني للشركة",
            "العميل يجهز عقد التأسيس",
            "العميل يوقع العقد أمام كاتب العدل",
            "العميل يحدد موقع النشاط ويجهز عقد إيجار المكتب",
            "العميل يسجل عقد الإيجار في نظام إيجاري أو ما يعادله",
            "العميل يقدم طلب الموافقة المبدئية للترخيص",
            "الموظف يراجع طلب الموافقة المبدئية",
            "العميل يرفع المستندات المطلوبة",
            "الموظف يتحقق من المستندات",
            "العميل يدفع رسوم الموافقة",
            "النظام ينشئ رقم طلب جديد",
            "الموظف يرسل الطلب لقسم الترخيص",
            "قسم الترخيص يراجع الطلب",
            "المشرف يعتمد الطلب",
            "العميل يذهب للفرع لدفع الرسوم النهائية",
            "الموظف يصدر الرخصة التجارية",
            "العميل يستلم الرخصة",
        ]

        _, redesign, metrics, validation = analyze(
            service("إصدار رخصة نشاط تجاري", steps)
        )

        self.assertEqual(metrics["future"]["steps"], 7)
        self.assertEqual(metrics["reduction"]["steps_percent"], 65)
        self.assertEqual(metrics["future"]["customer_burden_steps"], 0)
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(
            redesign["future_steps"][-1]["semantic_category"],
            "customer_outcome",
        )

    def test_english_manual_handoffs_are_orchestrated(self):
        value = service(
            "Delayed shipment",
            [
                "Customer contacts Customer Service about a delayed shipment",
                "Agent asks the customer for the tracking number",
                "Agent enters the customer information in CRM manually",
                "Agent enters the same tracking number again",
                "Agent emails Operations",
                "Operations employee searches another internal system",
                "Operations sends the result back by email",
                "Agent copies the result into CRM manually",
                "Supervisor approves the customer update",
                "Agent sends the update to the customer",
                "Customer follows up again",
                "Agent closes the case manually",
            ],
        )

        compliance, _, metrics, validation = analyze(value)

        # MERGE UPDATE: this scenario has no payment and no CUSTOMER
        # plan-approval evidence -- "Supervisor approves the customer
        # update" is an internal STAFF approval, not a customer
        # approval (merge task requirement: never conflate
        # human_approval with customer_approval). The future journey
        # therefore no longer includes the generic customer
        # plan-review/approval stage that used to be added
        # unconditionally to every service (root-cause fix), so the
        # expected stage count drops from 5 to 4. customer_burden_steps
        # stays 0 either way since that stage never carried customer
        # burden.
        self.assertEqual(metrics["future"]["steps"], 4)
        self.assertEqual(metrics["future"]["customer_burden_steps"], 0)
        self.assertEqual(compliance["summary"]["review"], 0)
        self.assertEqual(validation["status"], "PASS")

    def test_short_journey_never_grows(self):
        value = service(
            "Simple result",
            [
                "Customer requests the outcome",
                "Employee verifies the data",
                "Customer receives the result",
            ],
        )

        _, _, metrics, validation = analyze(value)

        self.assertLess(metrics["future"]["steps"], 3)
        self.assertEqual(validation["status"], "PASS")

    def test_individual_po_box_renewal_gets_service_specific_stages(self):
        value = service(
            "تجديد صندوق بريد الأفراد",
            [
                "العميل يدخل إلى موقع بريد الإمارات أو تطبيق الهاتف المتحرك",
                "العميل يسجل الدخول باستخدام الهوية الرقمية",
                "العميل يبحث عن خدمة تجديد صندوق بريد فردي ويختارها",
                "العميل يختار باقة صندوقي أو منزلي أو منزلي إنستانت",
                "العميل يختار مدة العقد المطلوبة",
                "العميل يدخل بياناته ويراجع بيانات صندوق البريد الحالي",
                "العميل يقدم الهوية الإماراتية المطلوبة",
                "العميل يحدد ما إذا كان يرغب في التجديد التلقائي",
                "النظام يعرض تفاصيل الباقة والرسوم والمبلغ الإجمالي",
                "العميل يختار وسيلة الدفع ويدفع رسوم التجديد",
                "العميل يراجع الطلب ويؤكد التجديد",
                "النظام يجدد صندوق البريد ويرسل تأكيد التجديد",
            ],
        )

        _, redesign, metrics, validation = analyze(value)

        self.assertEqual(metrics["current"]["steps"], 12)
        self.assertEqual(metrics["future"]["steps"], 7)
        self.assertEqual(metrics["future"]["customer_burden_steps"], 0)
        self.assertEqual(metrics["future"]["customer_control_points"], 3)
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(
            [
                step["semantic_category"]
                for step in redesign["future_steps"]
            ],
            [
                "intent_context",
                "package_selection",
                "data_completion",
                "plan_review",
                "payment",
                "execution_continuity",
                "customer_outcome",
            ],
        )
        self.assertTrue(all(
            step["type"] == "SYSTEM"
            for step in redesign["future_steps"]
        ))
        self.assertEqual(
            [
                action["code"]
                for action in redesign["customer_only_actions"]
            ],
            [
                "PACKAGE_SELECTION",
                "PLAN_APPROVAL_OR_EDIT",
                "PAYMENT",
            ],
        )
        self.assertEqual(
            redesign["agent_execution_explanation"]
                ["pre_payment_preview"]["options"],
            ["موافق", "تعديل"],
        )
        transfers = redesign["ownership_transfers"]
        self.assertEqual(len(transfers), 10)
        self.assertTrue(all(item["how"] for item in transfers))
        self.assertEqual(
            {
                item["source_step_number"]
                for item in transfers
                if item["future_owner"] == "CUSTOMER_CONTROL"
            },
            {4, 10, 11},
        )
        self.assertTrue(all(
            item["future_owner"] == "ASSISTANT"
            for item in transfers
            if item["source_step_number"] not in {4, 10, 11}
        ))


if __name__ == "__main__":
    unittest.main()
