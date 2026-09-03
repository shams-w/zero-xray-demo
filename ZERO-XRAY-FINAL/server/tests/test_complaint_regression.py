"""
Regression test for the merge task's specific reported bugs (no
Ollama configured in this environment, so this exercises the
deterministic fallback path only -- see core/llm.py / MERGE_REPORT.md
for what still needs local Ollama verification):

1. A complaint service must never get a fabricated payment,
   physical-visit, or human-approval capability (evidence-gated
   capability detection, agents/service_agent.py).
2. A complaint's raw input lines must be reduced to real semantic
   steps (not "N raw lines -> 1 step", and not "N raw lines -> N fake
   steps") by agents/service_agent.py's semantic step extraction.
3. The redesigned (TO-BE) journey must NOT contain a generic customer
   "review plan / approve or modify" control point unless the service
   has real evidence of one (agents/journey_builder_agent.py) -- and,
   as a contrasting case, a service that DOES have payment evidence
   must keep that control point. This is a general rule, not a
   complaint-specific hardcoded exception -- both cases below run
   through the exact same code path.

Runs the same agent order graph/workflow.py wires for the "current
journey -> future journey" portion of the pipeline:
service_agent -> step_compliance_agent -> journey_builder_agent.
"""

import unittest

from agents.service_agent import ServiceAnalystAgent
from agents.step_compliance_agent import StepComplianceAgent
from agents.journey_builder_agent import JourneyBuilderAgent
from core.rules import calculate_metrics
from core.standards_catalog import STANDARDS_CATALOG


STANDARDS = {"applicable_standards": STANDARDS_CATALOG}


def _run_pipeline(service_name, description, steps, branch_visits=0):
    service = {
        "service_name": service_name,
        "description": description,
        "steps": steps,
        "documents": [],
        "actors": [],
        "approvals": [],
        "waiting_times": [],
        "manual_actions": [],
        "digital_actions": [],
        "dependencies": [],
        "branch_visits": branch_visits,
    }

    analysis = ServiceAnalystAgent(llm=None).run(service)

    # Mirrors graph/workflow.py's service_node state merge-back: the
    # semantic steps and evidence-gated capabilities computed by
    # service_agent become part of the service object every
    # downstream agent (including journey_builder_agent) receives.
    enriched_service = {
        **service,
        "steps": analysis["steps"],
        "capabilities": analysis["capabilities"],
    }

    compliance = StepComplianceAgent(llm=None).run(
        enriched_service, analysis, STANDARDS,
    )
    redesign = JourneyBuilderAgent(llm=None).run(
        enriched_service, compliance, STANDARDS,
    )
    metrics = calculate_metrics(enriched_service, redesign)

    return analysis, compliance, redesign, metrics


class ComplaintRegressionTests(unittest.TestCase):

    def test_complaint_has_no_fabricated_capabilities(self):
        analysis, _, redesign, _ = _run_pipeline(
            "تقديم شكوى",
            "تقديم شكوى بخصوص تأخير شحنة بريدية بدون رسوم",
            [
                "العميل يشرح المشكلة ونوع الشحنة المتأخرة",
                "الموظف يسجل الشكوى في النظام ويعطي رقم مرجعي",
                "الموظف يحقق في سبب التأخير مع قسم العمليات",
                "النظام يرسل الرد النهائي للعميل خلال 5 ايام عمل",
            ],
        )

        capabilities = analysis["capabilities"]
        self.assertFalse(capabilities["has_payment"])
        self.assertFalse(capabilities["has_physical_visit"])
        self.assertFalse(capabilities["has_human_approval"])

        # No future step should carry an invented payment flag either.
        for step in redesign["future_steps"]:
            self.assertFalse(step.get("has_payment"))

    def test_complaint_semantic_steps_are_multiple_not_collapsed(self):
        analysis, _, _, _ = _run_pipeline(
            "تقديم شكوى",
            "شكوى بخصوص فاتورة غير صحيحة",
            [
                "العميل يدخل رقم الفاتورة",
                "العميل يوضح سبب الاعتراض على المبلغ",
                "الموظف يراجع تفاصيل الفاتورة والمعاملات المرتبطة",
                "الموظف يحدد ما اذا كانت هناك حاجة لتعديل",
                "النظام يرسل نتيجة المراجعة للعميل",
            ],
        )

        # Must not collapse 5 distinct semantic actions into 1 step,
        # and (in the no-LLM fallback path) must not blow up 5 lines
        # into more steps than were given either.
        self.assertGreater(len(analysis["steps"]), 1)
        self.assertLessEqual(len(analysis["steps"]), len(analysis["raw_steps"]))

    def test_complaint_journey_has_no_generic_plan_approval_step(self):
        _, _, redesign, _ = _run_pipeline(
            "تقديم شكوى",
            "شكوى بخصوص تأخير شحنة",
            [
                "العميل يشرح المشكلة",
                "الموظف يسجل الشكوى",
                "الموظف يحقق في السبب",
                "النظام يرسل الرد للعميل",
            ],
        )

        control_points = [
            point
            for step in redesign["future_steps"]
            for point in (step.get("customer_control_points") or [])
        ]
        approval_like = [
            point for point in control_points
            if "الموافقة على الخطة" in point or "approve" in point.lower()
            and "plan" in point.lower()
        ]
        self.assertEqual(
            approval_like, [],
            "Complaint journey must not contain a generic customer "
            "plan-approval control point without explicit evidence.",
        )

    def test_payment_service_keeps_plan_approval_step(self):
        """Contrasting case, same code path, no hardcoded exception:
        a service that DOES have real payment evidence must keep the
        customer plan-approval control point."""
        _, _, redesign, _ = _run_pipeline(
            "استئجار صندوق بريد",
            "استئجار صندوق بريد جديد للأفراد",
            [
                "العميل يقدم طلب استئجار صندوق بريد",
                "العميل يرفع صورة الهوية",
                "العميل يدفع رسوم الاستئجار",
                "النظام يصدر رقم الصندوق",
            ],
        )

        control_points = [
            point
            for step in redesign["future_steps"]
            for point in (step.get("customer_control_points") or [])
        ]
        self.assertTrue(
            any("الموافقة على الخطة" in point for point in control_points),
            "A payment-bearing service should still show the plan "
            "approval control point when it has real evidence.",
        )

    def test_document_service_detects_documents_without_false_positive(self):
        analysis, _, _, _ = _run_pipeline(
            "تجديد رخصة تجارية",
            "تجديد رخصة تجارية للشركات",
            [
                "العميل يرفع صورة من الرخصة الحالية",
                "العميل يرفع شهادة عدم الممانعة",
                "الموظف يراجع المستندات",
                "النظام يصدر الرخصة المجددة",
            ],
        )
        self.assertTrue(analysis["capabilities"]["has_documents"])

    def test_visit_only_detected_with_evidence(self):
        analysis, _, _, _ = _run_pipeline(
            "تقديم شكوى",
            "شكوى عبر الهاتف بدون اي حضور للفرع",
            [
                "العميل يتصل بمركز الاتصال",
                "الموظف يسجل الشكوى",
                "النظام يرسل الرد",
            ],
        )
        self.assertFalse(analysis["capabilities"]["has_physical_visit"])


if __name__ == "__main__":
    unittest.main()
