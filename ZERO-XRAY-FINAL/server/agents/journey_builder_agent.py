from core.service_classifier import classify_service
from core.json_utils import extract_json_with_salvage, has_parse_error
from core.rules import step_customer_role_is_burden
from core.llm import ai_label, log_raw_response, detect_language_mismatch


class JourneyBuilderAgent:
    """Build a service-specific Agentic target journey.

    The number of future stages is derived from actual journey capabilities
    (data, choices, payment, controlled human judgement, execution and result),
    not from a fixed four-step template. Customer consent remains a control
    point and is not counted as administrative customer work.
    """

    def __init__(self, llm=None):
        self.llm = llm

    def run(self, service, step_compliance, relevant_standards=None, gaps=None):
        source_steps = [
            str(step).strip()
            for step in service.get("steps", [])
            if str(step).strip()
        ]
        source_text = (
            " ".join(source_steps)
            + " "
            + str(service.get("description", ""))
            + " "
            + str(service.get("service_name", ""))
        )

        # An explicit "lang" on the request (driven by the UI language
        # switch) always wins over auto-detecting the language of the
        # submitted text. This lets a customer type the service in
        # Arabic while viewing (or later switching to) the English UI
        # and still get an English-language redesigned journey, and
        # vice versa. When no explicit lang is supplied, fall back to
        # detecting the language of the submitted service text.
        requested_lang = service.get("lang")
        if requested_lang == "ar":
            is_arabic = True
        elif requested_lang == "en":
            is_arabic = False
        else:
            is_arabic = self._is_arabic(source_text)
        profile = self._service_profile(service, source_text)
        protected_constraints = self._protected_constraint_map(service)

        # MERGED FROM P1: evidence-gated capability detection
        # (service_agent) is more specific than this file's own
        # generic keyword scan for "does this service have payment" --
        # when it has made an explicit determination, it is
        # authoritative here too, so every downstream use (templates,
        # ownership transfers, control points, the AI-generated
        # future journey prompt, and the capability veto below) agrees
        # with it instead of potentially contradicting it.
        capabilities = service.get("capabilities")
        if isinstance(capabilities, dict) and "has_payment" in capabilities:
            profile["has_payment_stage"] = bool(capabilities.get("has_payment"))
            # BUG FIX: requires_explicit_customer_approval was computed
            # inside _service_profile() using only classify_service()'s
            # own (less specific) payment heuristic, BEFORE this
            # evidence-gated override runs -- so an evidence-confirmed
            # payment service could still incorrectly end up with no
            # customer plan-approval stage. Keep it in sync with the
            # authoritative capability the same way has_payment_stage
            # just was.
            profile["requires_explicit_customer_approval"] = (
                profile.get("requires_explicit_customer_approval", False)
                or profile["has_payment_stage"]
            )

        # ============================================================
        # PRIMARY PATH (MERGED FROM P1): ask Ollama to design the
        # entire future journey for THIS specific service -- stage
        # count, order, ownership, payment timing, human intervention
        # and a real detailed explanation per stage -- instead of
        # filling a fixed template. Only when this is unavailable or
        # its output can't be trusted does the deterministic template
        # system below run, as the safety-net fallback it was always
        # meant to be. Either path is then passed through the SAME
        # capability veto and protected-step system (P2), so Blueprint
        # step protection is never bypassed by the AI path.
        # ============================================================
        ai_future_steps, ai_overall_reasoning = self._generate_ai_future_journey(
            service=service,
            step_compliance=step_compliance,
            relevant_standards=relevant_standards,
            gaps=gaps,
            source_steps=source_steps,
            source_text=source_text,
            is_arabic=is_arabic,
            capabilities=capabilities,
        )

        if ai_future_steps is not None:
            future_steps = self._apply_capability_veto(
                ai_future_steps, capabilities
            )
            analysis_source = ai_label()
        else:
            future_steps, analysis_source = self._build_template_future_steps(
                service=service,
                source_steps=source_steps,
                profile=profile,
                is_arabic=is_arabic,
            )
            future_steps = self._apply_capability_veto(
                future_steps, capabilities
            )

        future_steps = self._apply_protected_steps(
            future_steps=future_steps,
            source_steps=source_steps,
            constraints=protected_constraints,
            is_arabic=is_arabic,
        )

        ownership_transfers = self._ownership_transfer_map(
            source_steps,
            is_arabic,
            protected_constraints,
            profile,
        )
        removed_steps = self._removed_customer_burden_steps(
            source_steps,
            is_arabic,
            protected_constraints,
            profile,
        )
        control_points = self._control_points(profile, is_arabic)
        agent_explanation = self._build_agent_explanation(
            future_steps=future_steps,
            ownership_transfers=ownership_transfers,
            profile=profile,
            is_arabic=is_arabic,
        )

        return {
            "future_steps": future_steps,
            "future_documents": list(service.get("documents", [])),
            "future_manual_actions": [
                step["name"]
                for step in future_steps
                if step["type"] == "HUMAN"
            ],
            "future_digital_actions": [
                step["name"]
                for step in future_steps
                if step["type"] == "SYSTEM"
            ],
            "future_approvals": list(service.get("approvals", [])),
            "future_branch_visits": 0,
            "future_waiting_times": [],
            "future_customer_burden_steps": sum(
                1
                for step in future_steps
                if step.get("customer_burden") is True
            ),
            "customer_only_actions": agent_explanation[
                "customer_only_actions"
            ],
            "ownership_transfers": ownership_transfers,
            "agent_execution_explanation": agent_explanation,
            "removed_steps": removed_steps,
            "merged_steps": self._merged_trace(
                future_steps, removed_steps, is_arabic
            ),
            "required_integrations": self._required_integrations(
                profile, is_arabic
            ),
            "automation_opportunities": self._automation_trace(future_steps),
            "review_steps": [
                {
                    "step_number": number,
                    "step": source_steps[number - 1],
                    **constraint,
                }
                for number, constraint in protected_constraints.items()
                if constraint.get("level") == "HUMAN"
                and 0 < number <= len(source_steps)
            ],
            "protected_steps": [
                {
                    "step_number": number,
                    "step": source_steps[number - 1],
                    **constraint,
                }
                for number, constraint in protected_constraints.items()
                if 0 < number <= len(source_steps)
            ],
            "service_classification": {
                key: profile[key]
                for key in [
                    "service_archetype",
                    "service_kind",
                    "archetype_evidence",
                    "payment_context",
                    "payment_evidence",
                    "requires_customer_payment",
                    "payment_verification_required",
                    "has_package_stage",
                    "requires_human_decision",
                    "consent_mode",
                    "fee_model",
                    "payment_timing",
                    "payment_method",
                    "payment_provider",
                    "annual_fee_rate",
                    "minimum_fee",
                    "physical_handoff_required",
                ]
            },
            "design_profile": profile,
            "design_assumptions": [
                (
                    "يجب التحقق قبل الإطلاق من صلاحيات استخدام البيانات "
                    "والتنفيذ والتكاملات المقترحة. فشل التكامل يدخل مسار "
                    "تعافٍ ولا يعيد العمل اليدوي للمتعامل."
                    if is_arabic
                    else "Data-use authority, execution permissions and proposed "
                    "integrations require pre-launch validation. Integration "
                    "failure enters recovery instead of returning work to the customer."
                )
            ],
            "control_points": control_points,
            "exception_paths": [
                {
                    "name": (
                        "نقل الحالة لموظف مع كامل السياق"
                        if is_arabic
                        else "Human handoff with full context"
                    ),
                    "trigger": (
                        "تعطل أو تعارض أو عدم أهلية أو حساسية أو تجاوز "
                        "صلاحية أو طلب المتعامل التدخل البشري."
                        if is_arabic
                        else "Failure, conflict, ineligibility, sensitivity, "
                        "authority limit, or a customer request."
                    ),
                    "action": (
                        "ينقل المساعد الطلب والسياق والبيانات والموافقات "
                        "وسجل الإجراءات للموظف دون إعادة القصة."
                        if is_arabic
                        else "Transfer the request, context, data, approvals and "
                        "action log without making the customer restart."
                    ),
                    "standard_id": "STAGE-06",
                }
            ],
            "post_result_paths": [
                {
                    "name": (
                        "استفسار أو تصحيح أو اعتراض من المكان نفسه"
                        if is_arabic
                        else "Question, correction or objection in the same place"
                    ),
                    "standard_id": "STAGE-08",
                }
            ],
            "measurement_plan": {
                "baseline": {
                    "current_total_steps": len(source_steps),
                    "current_customer_burden_steps": sum(
                        self._is_customer_burden_step(step, profile)
                        for step in source_steps
                    ),
                },
                "indicators": [
                    "customer_burden_steps",
                    "completion_rate",
                    "time_to_outcome",
                    "manual_intervention_rate",
                    "exception_recovery_rate",
                    "customer_trust_and_satisfaction",
                ],
                "standard_id": "READY-01",
            },
            "customer_experience": (
                # ROOT-CAUSE FIX (genericity): when the journey was
                # actually designed by the AI, describe what the
                # customer really does by reading it off the AI's OWN
                # stages -- never the fixed, service_kind-keyed canned
                # narrative below, which special-cases specific
                # service types (e.g. shipment, postal licensing) and
                # is only appropriate as part of the deterministic
                # template's own fallback narrative.
                self._customer_experience_from_ai_journey(
                    future_steps, is_arabic,
                )
                if analysis_source == ai_label()
                else self._customer_experience(profile, is_arabic)
            ),
            "implementation_notes": [
                (
                    "عدد المراحل ليس ثابتًا؛ يتغير حسب البيانات والاختيارات "
                    "والدفع والموافقات البشرية والتنفيذ والنتيجة."
                    if is_arabic
                    else "Stage count is dynamic and depends on data, choices, "
                    "payment, controlled human judgement, execution and result."
                ),
                (
                    "كل تكامل غير مثبت مصنف كمقترح ويحتاج تحققًا قبل الإطلاق."
                    if is_arabic
                    else "Every unverified integration is PROPOSED and requires "
                    "pre-launch validation."
                ),
            ],
            # MERGED FROM P1: which path actually produced this
            # journey ("ai" or "template"), and the model's own
            # explanation of its overall design logic when AI-designed.
            # Surfaced to the Dashboard / audit trail so it is always
            # visible whether a given journey was AI-reasoned or the
            # deterministic fallback -- never silently indistinguishable.
            "analysis_source": analysis_source,
            "ai_overall_reasoning": (
                ai_overall_reasoning if analysis_source == "ai" else ""
            ),
        }

    # ================================================================
    # TEMPLATE-BASED FUTURE JOURNEY (deterministic fallback, P2)
    # ================================================================
    def _build_template_future_steps(self, service, source_steps, profile, is_arabic):
        """Deterministic fallback used only when the AI is unavailable
        or its full-journey output can't be trusted. Extracted as its
        own method (previously inline in run()) so run() can call it
        as the fallback branch after attempting AI-first generation.
        """
        templates = self._dynamic_templates(
            profile=profile,
            is_arabic=is_arabic,
        )
        templates = self._compress_to_limit(
            templates=templates,
            limit=self._maximum_target_steps(len(source_steps)),
            is_arabic=is_arabic,
        )

        grouped_sources = [[] for _ in templates]
        for step in source_steps:
            category = self._classify_source_step(step)
            grouped_sources[
                self._find_stage_index(category, templates)
            ].append(step)

        future_steps = []
        for number, template in enumerate(templates, start=1):
            sources = grouped_sources[number - 1]
            step_type = template.get("type", "SYSTEM")
            if len(sources) > 1:
                change_type = "MERGED"
            elif step_type == "SYSTEM":
                change_type = "AUTOMATED" if sources else "NEW"
            else:
                change_type = "KEPT" if sources else "NEW"

            template_customer_role = template.get(
                "customer_role",
                (
                    "لا يوجد عمل إداري على المتعامل"
                    if is_arabic
                    else "No administrative customer work"
                ),
            )

            future_steps.append({
                "step_number": number,
                "name": template["name"],
                "type": step_type,
                "action": template["action"],
                "change_type": change_type,
                "reason": template["reason"],
                "standard_id": template["standard_id"],
                "related_standard_ids": template["related_standard_ids"],
                "source_steps": sources,
                "semantic_category": template["semantic_category"],
                "component_categories": template["component_categories"],
                "implementation_status": "PROPOSED",
                # MERGED FROM P1 (root-cause fix): this used to be
                # hardcoded False for every template stage regardless
                # of its own customer_role text, which silently made
                # ANY remaining customer administrative work in the
                # future journey invisible to the Zero Bureaucracy
                # score. Derive it from the stage's own customer_role
                # instead -- the same generic administrative-burden
                # vocabulary already used to measure the CURRENT
                # journey (core/rules.py), applied here to the FUTURE
                # stage's own description of what the customer does.
                "customer_burden": step_customer_role_is_burden(
                    template_customer_role
                ),
                "customer_control_points": template.get(
                    "customer_control_points", []
                ),
                "owner": (
                    "HUMAN"
                    if step_type == "HUMAN"
                    else "ASSISTANT"
                ),
                "assistant_action": template["action"],
                "customer_role": template_customer_role,
                "visible_before_payment": template.get(
                    "visible_before_payment",
                    True,
                ),
                "completion_evidence": template.get(
                    "completion_evidence",
                    (
                        "سجل تنفيذ قابل للمراجعة"
                        if is_arabic
                        else "Reviewable execution log"
                    ),
                ),
                "detailed_description": self._template_detailed_description(
                    template, is_arabic,
                ),
                "reasoning": template["reason"],
                "has_payment": "payment" in (
                    template.get("component_categories") or []
                ),
                "requires_human_judgement": step_type == "HUMAN",
                "depends_on_previous": "",
                "analysis_source": "template",
            })

        return future_steps, "template"

    def _template_detailed_description(self, template, is_arabic):
        """Turn a fallback template's (action, reason) pair into a
        single, richer explanatory paragraph, so every step -- whether
        AI-designed or produced by the deterministic fallback -- has a
        populated detailed_description field in the same shape.
        MERGED FROM P1.
        """
        action = str(template.get("action", "")).strip()
        reason = str(template.get("reason", "")).strip()
        parts = [part for part in (action, reason) if part]
        return " ".join(parts)

    # ================================================================
    # AI-PRIMARY FULL JOURNEY GENERATION (MERGED FROM P1)
    # ================================================================
    def _generate_ai_future_journey(
        self,
        service,
        step_compliance,
        relevant_standards,
        source_steps,
        source_text,
        is_arabic,
        capabilities=None,
        gaps=None,
    ):
        """Ask Ollama to design the entire future journey end-to-end:
        how many stages it needs, their names/order/ownership, payment
        timing, human intervention, dependencies between stages, and a
        real, service-specific detailed explanation for every stage.

        This is the PRIMARY path for the proposed journey. Nothing
        here is specific to any one service type -- the model is
        given the actual service description, its current steps, the
        documented problems with them, and the applicable standards,
        and reasons about THIS service's own logic.

        Returns a (future_steps, overall_reasoning) tuple, or
        (None, "") on failure (AI unavailable, unreachable, or its
        response can't be trusted), in which case the caller falls
        back to the deterministic template-based journey unchanged.
        """
        if not self.llm:
            return None, ""

        service_name = str(service.get("service_name", "")).strip()
        description = str(service.get("description", "")).strip()

        # ROOT-CAUSE FIX (AI hallucination -- generic): the journey
        # designer previously had NO structured knowledge of which
        # systems, data sources or API operations actually exist for
        # this Service. It only ever saw them as free text that had
        # been concatenated onto `description` upstream, which both
        # contaminated the current-journey extraction (see main.py)
        # and gave the model no signal that this material was a
        # closed, authoritative inventory rather than more prose to
        # riff on. So it invented plausible-sounding lookups,
        # registries and endpoints that no evidence supported.
        #
        # The same context is now delivered as an explicitly labelled,
        # closed EVIDENCE section with an explicit anti-invention rule.
        # It is entirely data-driven from whatever this Service happens
        # to have linked -- no service, domain or specification is
        # named anywhere here.
        organization_context = str(
            service.get("organization_context", "")
        ).strip()
        if organization_context:
            evidence_text = organization_context
            evidence_instruction = (
                "القائمة أعلاه هي الجرد الكامل والمغلق للأنظمة ومصادر "
                "البيانات وعمليات الـAPI المتاحة فعليًا لهذه الخدمة. "
                "صمّم الأتمتة اعتمادًا على ما هو مذكور فيها فقط. لا "
                "تخترع أبدًا نظامًا أو سجلًا أو تكاملًا أو endpoint غير "
                "مذكور، ولا تفترض أن نظامًا ما يحتوي بيانات لم يُذكر "
                "أنه يحتويها. هذه العناصر أدلة على القدرات المتاحة "
                "وليست خطوات في رحلة المتعامل -- لا تحوّل أي وصف "
                "عملية API أو بيانات وصفية إلى مرحلة بحد ذاتها؛ "
                "المراحل تُشتق من منطق الخدمة نفسها."
                if is_arabic
                else "The list above is the COMPLETE, CLOSED inventory "
                "of systems, data sources and API operations that "
                "actually exist for this service. Design automation "
                "only around what it contains. Never invent a system, "
                "registry, integration or endpoint that is not listed, "
                "and never assume a listed system holds data it was "
                "not stated to hold. These entries are EVIDENCE of "
                "available capability, not steps in the customer's "
                "journey -- never turn an API operation description or "
                "any other metadata into a stage of its own; stages "
                "are derived from this service's own logic."
            )
        else:
            evidence_text = (
                "لم يتم ربط أي أنظمة أو عمليات API بهذه الخدمة."
                if is_arabic
                else "No systems or API operations are linked to this "
                "service."
            )
            evidence_instruction = (
                "بما أنه لا يوجد أي نظام أو تكامل مؤكد، صف الأتمتة "
                "بصيغة مقترحة عامة، ولا تدّعي وجود تكامل أو مصدر "
                "بيانات محدد."
                if is_arabic
                else "Since no system or integration is confirmed, "
                "describe automation as a generic proposal and never "
                "claim a specific existing integration or data source."
            )

        numbered_steps = "\n".join(
            f"{i}. {s}" for i, s in enumerate(source_steps, start=1)
        ) or (
            "لا توجد خطوات حالية موثقة."
            if is_arabic
            else "No current steps documented."
        )

        problems = []
        for item in (step_compliance or {}).get("step_assessment", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("status") in ("FAIL", "PARTIAL"):
                reason = str(item.get("reason", "")).strip()
                if reason:
                    problems.append(f"- {reason}")
        problems_text = "\n".join(problems[:5]) or (
            "لا توجد مشاكل موثقة صراحة."
            if is_arabic
            else "No explicitly documented problems."
        )

        applicable = (
            (relevant_standards or {}).get("applicable_standards", []) or []
        )
        standards_lines = []
        for item in applicable[:8]:
            if isinstance(item, dict):
                std_id = str(item.get("standard_id", "")).strip()
                title = str(
                    item.get("title") or item.get("name") or ""
                ).strip()
                if std_id or title:
                    standards_lines.append(f"- {std_id}: {title}".strip(": "))
        standards_text = "\n".join(standards_lines) or (
            "لا توجد معايير محددة." if is_arabic else "No specific standards supplied."
        )

        # ROOT-CAUSE FIX (generic, not service-specific): the journey
        # builder used to only see FAIL/PARTIAL step-compliance
        # reasons, never the actual structured gaps GapAnalysisAgent
        # identified (each with its own standard_id, severity and
        # concrete recommendation). That meant journey quality could
        # only be judged by proxies like step count, never by whether
        # the redesign actually closes the specific compliance gaps
        # this service has. Feeding the real gap list in lets the
        # model design stages that concretely resolve them -- this is
        # entirely data-driven from whatever GapAnalysisAgent found
        # for THIS service, so it applies identically to any service
        # domain.
        gap_list = (gaps or {}).get("gaps", []) if isinstance(gaps, dict) else []
        gap_lines = []
        for item in gap_list[:6]:
            if not isinstance(item, dict):
                continue
            std_id = str(item.get("standard_id", "")).strip()
            description = str(item.get("description", "")).strip()
            severity = str(item.get("severity", "")).strip()
            recommendation = str(item.get("recommendation", "")).strip()
            if not description:
                continue
            line = f"- [{severity or 'N/A'}] {description}"
            if std_id:
                line += f" (standard: {std_id})"
            if recommendation:
                line += f" -- recommended fix: {recommendation}"
            gap_lines.append(line)
        gaps_text = "\n".join(gap_lines) or (
            "لم يتم تحديد فجوات امتثال صريحة لهذه الخدمة."
            if is_arabic
            else "No explicit compliance gaps were identified for this service."
        )

        capability_lines = []
        if isinstance(capabilities, dict):
            capability_specs = [
                ("has_payment", "payment_evidence", "PAYMENT"),
                ("has_documents", "documents_evidence", "SUPPORTING DOCUMENTS"),
                ("has_physical_visit", "visit_evidence", "PHYSICAL VISIT"),
                ("has_human_approval", "human_approval_evidence", "HUMAN APPROVAL"),
            ]
            for flag_key, evidence_key, label in capability_specs:
                if flag_key not in capabilities:
                    continue
                if capabilities.get(flag_key):
                    evidence = str(capabilities.get(evidence_key, "")).strip()
                    capability_lines.append(
                        f"- {label}: CONFIRMED for this service"
                        + (f" (evidence: {evidence})" if evidence else "")
                        + ". You MUST reflect this in the journey."
                    )
                else:
                    capability_lines.append(
                        f"- {label}: NOT present in this service -- no "
                        "evidence was found. Do NOT add a stage for "
                        "this under any circumstance, even if a "
                        "related word appears elsewhere in the text "
                        "(e.g. a complaint about a past charge is not "
                        "a new payment)."
                    )
        capabilities_text = "\n".join(capability_lines) or (
            "لم يتم تحديد قدرات صريحة؛ استنتج فقط ما تدعمه النصوص أعلاه."
            if is_arabic else
            "No capabilities were explicitly pre-determined; infer only "
            "what the text above actually supports."
        )

        # MERGED FROM P1 + hardened further: the customer-approval
        # rule the merge task specifically requires. The model must
        # only add a customer plan-review/approval interaction when
        # the CURRENT journey or service intent gives real evidence
        # of one -- never as a generic default for every service, and
        # never specifically hardcoded for/against any one archetype
        # such as complaints.
        approval_instruction = (
            "مهم جدًا: لا تضف خطوة \"مراجعة الخطة والموافقة/التعديل\" "
            "للمتعامل إلا إذا وجدت دليلاً حقيقيًا في وصف الخدمة أو "
            "خطواتها الحالية على أن المتعامل يوافق فعليًا على خطة أو "
            "مبلغ قبل التنفيذ (مثل الدفع، أو التزام ملزم). لا تفترض "
            "هذه الخطوة تلقائيًا لكل خدمة، ولا تحذفها تلقائيًا لأن "
            "الخدمة شكوى أو غير ذلك -- القرار يعتمد على أدلة هذه "
            "الخدمة تحديدًا فقط."
            if is_arabic
            else "IMPORTANT: only add a customer \"review plan and "
            "approve/modify\" interaction if you find real evidence in "
            "the service description or its current steps that the "
            "customer actually approves a plan or amount before "
            "execution (e.g. payment, or a binding commitment). Do not "
            "assume this step by default for every service, and do not "
            "remove it by default just because the service is a "
            "complaint or any other specific type -- base the decision "
            "only on this service's own evidence."
        )

        # ROOT-CAUSE FIX: verified by direct trace that `is_arabic` was
        # already correctly computed and reaching this function -- the
        # actual weakness is prompt-compliance, not a plumbing bug. The
        # ~700+ words of English design-rule scaffolding below vastly
        # outweigh a single one-line Arabic directive placed only once,
        # near the very end, right before the JSON schema -- a known
        # weak-instruction-following failure mode for a small (4B)
        # model on an open-ended generation task: it tends to continue
        # in the context's dominant language. Fixed by (1) stating the
        # requirement here in stronger, unambiguous, non-negotiable
        # terms, (2) repeating it at the very START of the prompt too
        # (primacy) in addition to its existing position at the end
        # (recency) -- standard reinforcement for weak-compliance
        # cases -- and (3) making the system_prompt itself
        # language-aware below, since system-role content is weighted
        # more heavily by chat-formatted LLM APIs. This does not
        # change what the model is asked to design, only how firmly
        # the output-language requirement is communicated.
        language_instruction = (
            "إلزامي وغير قابل للتفاوض: كل حقل نصي في الناتج (name، "
            "action، detailed_description، reasoning، customer_role، "
            "payment_reasoning، human_judgement_reason) يجب أن يكون "
            "مكتوبًا بالكامل باللغة العربية الفصحى الواضحة، بدون أي "
            "كلمة أو جملة إنجليزية. لا تستخدم أسماء خطوات إنجليزية "
            "كقوالب أو كأساس تُترجم عنه؛ فكّر وصُغ المحتوى بالعربية "
            "مباشرة من البداية."
            if is_arabic
            else "MANDATORY AND NON-NEGOTIABLE: every text field in "
            "the output (name, action, detailed_description, "
            "reasoning, customer_role, payment_reasoning, "
            "human_judgement_reason) must be written entirely in "
            "clear English, with no other language mixed in."
        )

        prompt = f"""{language_instruction}

You are redesigning the future (target) journey for a real service. Design the proposed FUTURE journey based on THIS service's own logic -- do not reuse a generic template from another domain.

SERVICE NAME: {service_name or "(not provided)"}

SERVICE DESCRIPTION:
{description or "(not provided)"}

CURRENT JOURNEY STEPS:
{numbered_steps}

DOCUMENTED PROBLEMS WITH THE CURRENT JOURNEY:
{problems_text}

RELEVANT STANDARDS TO ALIGN WITH:
{standards_text}

IDENTIFIED COMPLIANCE GAPS THIS REDESIGN MUST CONCRETELY CLOSE (this is the real measure of a good redesign, not stage count -- every stage-reduction decision you make should trace back to actually resolving one of these, and if a gap doesn't apply to a decision you're making, don't force it):
{gaps_text}

VERIFIED CAPABILITIES FOR THIS SERVICE (evidence-gated -- treat as ground truth, overriding any assumption you might otherwise make):
{capabilities_text}

AVAILABLE SYSTEMS, DATA SOURCES AND API OPERATIONS FOR THIS SERVICE (evidence only -- NOT journey steps):
{evidence_text}

{evidence_instruction}

{approval_instruction}

CONTEXT: by the time this design decision happens, the customer has already logged in (e.g. UAE PASS) and selected this specific service -- never ask the customer to log in, enter credentials, or say "which service do you want"; start from the customer's actual request for THIS service. You MAY include a brief internal stage where the system confirms/uses the already-verified identity to proceed -- that is not a login stage, it requires no customer action. The CURRENT JOURNEY STEPS above are EVIDENCE to understand what this service actually involves (its data, decisions, payment, dependencies) -- they are NOT a blueprint to reorder. Determine this service's own nature from its description/steps/standards and design accordingly; do not force every service into the same shape. Two common patterns, given only as reference points (adapt or depart from them entirely if this service is neither):
- A service where the customer wants a concrete deliverable/status change (e.g. a renewal, a license, a registration): the assistant retrieves the customer's existing data, checks eligibility, builds the plan and calculates the fee itself, then presents a ready plan for the customer to approve-and-pay in one action, or edit via a small number of specific structured choices (not free-form re-entry) which the assistant then rebuilds the plan around.
- A service where the customer has a problem or question (e.g. a complaint or inquiry): there is no package/payment shape here. The assistant understands the issue, pulls the customer's related records from their available context, analyzes and attempts a resolution itself; if a customer decision is genuinely needed, offer specific choices rather than asking them to re-supply data the system already has. A human handoff for what the assistant cannot resolve is already handled automatically outside these steps -- do not add a filler "human review" stage for this; only add a HUMAN stage if a human decision is an expected, necessary part of THIS service's own journey.

DATA REUSE (graded distinction) -- classify every piece of info the CURRENT journey asks for into exactly one bucket, using only this service's own evidence:
- ALREADY AVAILABLE (never ask again): identity/profile fields from login itself -- name, Emirates ID, nationality, verified contact -- when the current journey shows these came from login rather than being typed fresh for this service.
- RETRIEVABLE VIA THIS SERVICE'S OWN SYSTEM (propose, don't assume it already happened): records tied to this service specifically -- prior transactions, shipments, case history, a reference/box number the current journey shows the customer typing by hand. If so, design a SEPARATE stage (after identity, executor AGENT/GOVERNMENT_SYSTEM/EXTERNAL_SYSTEM) where the assistant looks up the customer's related records by identity and lets them select one, instead of asking them to type it. This is a proposed integration -- never claim the login/identity step itself already contains these records.
- GENUINELY MISSING (ask only these): what no system could know in advance -- the actual problem description, complaint details, a resolution choice, optional attachments.
Critical error to avoid: never claim the identity source (e.g. "UAE PASS") itself already contains service-specific records like shipment/transaction numbers. The chain is always identity first, THEN a separate lookup against this service's own system -- never collapse those into one unevidenced claim.

DESIGN RULES (a journey that just restates current steps with different wording is REJECTED):
1. Start from the customer's OUTCOME, not the current step order. Never one future stage per current step.
2. Reuse data already known (profile, UAE PASS, prior submissions, registries) instead of asking the customer to re-enter or navigate for it.
3. Merge steps that are logically one action into one stage (e.g. login+select+fill+upload -> one intake stage). If fee-confirmation and payment have no separate decision between them, make them ONE stage.
4. Automate backend checks (AGENT/GOVERNMENT_SYSTEM) instead of manual employee review, unless this service's own evidence shows a real judgement call that cannot be automated.
5. type="HUMAN" or requires_human_judgement=true ONLY for a genuine staff judgement call the assistant cannot make -- never because the current journey routed it through an employee. requires_customer_approval=true ONLY for a real confirmation/payment/personal choice the system cannot infer -- if a choice (package/tier/duration/etc.) can be defaulted from context, let the assistant propose it instead of asking.
6. Ordering: a stage can never depend on a value not yet determined. Typical order: selection/options (only if the customer must decide) -> calculate fee -> summary -> confirmation/payment (if any) -> execute -> deliver result. Skip stages this service doesn't need; never invent stages to fill this shape.
7. Payment timing: if the amount is only known after execution (e.g. weight, usage), payment comes AFTER that result -- never before.
7b. A stage's reasoning/detailed_description must NEVER claim the final payment/fee amount is already known, clear, or justified unless has_payment=true for that exact stage, or an earlier stage already produced that amount as its result. A plan-review/approval-elimination stage that comes BEFORE the payment stage must justify itself only by what it actually controls at that point (e.g. scope, eligibility, the submitted data) -- never by amount clarity it does not have yet. The stage where has_payment=true is the one that confirms the final amount and authorizes/executes the payment; amount-clarity language belongs there, not earlier.
8. executor for SYSTEM stages: "AGENT" (default), "GOVERNMENT_SYSTEM" (calls another government registry), or "EXTERNAL_SYSTEM" (bank/courier/telecom) -- only when the service's own text implies it.
9. Fewer stages than the current journey, and less customer effort overall, unless the current journey already has <=3 steps or every step is protected (say so in overall_reasoning if so). Judge quality by whether every stage is justified by this service's own logic/standards/gaps above -- not by stage count alone.

For every stage, detailed_description: 1-2 concrete sentences specific to THIS service (what happens, who's responsible, what it depends on/produces) -- never a generic sentence that could apply to any service. The LAST stage must deliver a customer-visible result (delivers_customer_result=true); every other stage: false.

{language_instruction}

Return JSON only, no commentary, no markdown fences. Put "steps" FIRST in the object. Exactly this shape:
{{
  "steps": [
    {{
      "name": "short stage name",
      "type": "SYSTEM or HUMAN",
      "executor": "AGENT, GOVERNMENT_SYSTEM or EXTERNAL_SYSTEM (SYSTEM stages only)",
      "action": "1 sentence: what happens",
      "detailed_description": "1-2 sentences, specific to this service",
      "reasoning": "1 sentence: why this stage exists here",
      "customer_role": "what the customer does, or 'None'",
      "has_payment": true or false,
      "payment_reasoning": "if has_payment: why now / what determines the amount; else ''",
      "requires_human_judgement": true or false,
      "human_judgement_reason": "if true: why this can't be automated; else ''",
      "requires_customer_approval": true or false,
      "depends_on_previous": "what earlier result this needs, or ''",
      "delivers_customer_result": true or false
    }}
  ],
  "overall_reasoning": "1-2 sentences on the overall design logic"
}}

Write "steps" completely first, THEN "overall_reasoning" -- steps are the required, load-bearing part of this response; a response with reasoning but no steps is useless. Keep the JSON compact: at most 6 stages unless the service genuinely needs more, and do not repeat the same point across multiple fields.
"""

        # Scales with the actual size of the CURRENT journey -- never
        # a fixed number, never service-specific -- with 2200 kept as
        # an explicit floor so small services are unaffected, and a
        # ceiling so this can't grow unbounded for a pathological
        # input. Addresses the truncation failure mode
        # ([AI FAILED -> FALLBACK] ... "response looks truncated
        # mid-JSON") by giving Ollama enough num_predict budget for a
        # multi-field, multi-sentence explanation per stage; core/llm.py
        # separately ensures num_ctx is sized to fit prompt + this
        # budget together (see core/llm.py's Arabic-aware token
        # estimate and context-exhaustion retry).
        # ROOT-CAUSE FIX (journey quality, not just journey validity):
        # a real qwen3:4b response could be perfectly well-formed JSON
        # that VALIDATES cleanly (every stage has a name, a real
        # description, a type) while still being a poor redesign --
        # essentially the current steps copied 1:1 with light
        # rewording, no consolidation, no shift of work onto the
        # assistant. That is a prompt/design-quality failure, not a
        # parsing failure, so it must not be silently accepted as a
        # good journey. Give the model exactly one corrective retry,
        # with concrete feedback about what it did wrong, before
        # accepting whatever it produces -- this still keeps Ollama as
        # the PRIMARY author of the journey (never substituted with a
        # template, never discarded) while giving it a real chance to
        # fix the specific defect instead of us silently downgrading
        # its output.
        future_steps, overall_reasoning, failure_reason = self._run_ai_journey_attempt(
            prompt, source_steps, is_arabic, relevant_standards
        )

        # ROOT-CAUSE FIX (real Ollama 0.32.15 + qwen3:4b failure
        # signature reported in production): the model sometimes
        # returns syntactically valid JSON with "overall_reasoning"
        # filled in but "steps" missing/empty -- a genuinely different
        # failure mode from a parse error or a low-quality journey.
        # This is not fixed by growing context further (the model DID
        # finish its response); it is a prompt-complexity problem. Try
        # exactly once more with a short, steps-only prompt that
        # strips every explanatory principle down to the minimum a 4B
        # model needs to reliably emit the required array -- still
        # Ollama as the sole author, never a template substituted in
        # its place.
        if future_steps is None and failure_reason in (
            "missing_steps", "step_count_out_of_range",
        ):
            print(
                "[JOURNEY] First attempt produced no usable 'steps' "
                "array -- retrying once with a compact, steps-only "
                "prompt sized for a small model."
            )
            compact_prompt = self._build_compact_journey_prompt(
                service_name=service_name,
                description=description,
                numbered_steps=numbered_steps,
                capabilities_text=capabilities_text,
                is_arabic=is_arabic,
            )
            future_steps, overall_reasoning, failure_reason = (
                self._run_ai_journey_attempt(
                    compact_prompt, source_steps, is_arabic, relevant_standards
                )
            )

        if future_steps is not None and self._journey_is_near_copy(
            future_steps, source_steps
        ):
            print(
                "[JOURNEY] AI journey looks like an uncompressed copy "
                "of the current journey (no real consolidation) -- "
                "retrying once with corrective feedback."
            )
            near_copy_names = ", ".join(
                str(step.get("name", "")).strip() for step in future_steps[:8]
            )
            feedback = (
                "\n\nCORRECTIVE FEEDBACK ON YOUR PREVIOUS ATTEMPT: the "
                f"journey you returned had {len(future_steps)} stages "
                f"({near_copy_names}) that closely mirror the "
                f"{len(source_steps)} CURRENT JOURNEY STEPS above, in "
                "the same order, without real consolidation -- this is "
                "not an acceptable redesign (see DESIGN RULES above). "
                "Re-design this journey from the "
                "customer's outcome: merge steps that are logically one "
                "action, remove navigation/re-entry the assistant can "
                "handle on the customer's behalf, and automate backend "
                "checks that do not require genuine human judgement. "
                "Return a genuinely more efficient journey this time."
                if not is_arabic
                else
                "\n\nملاحظات تصحيحية على محاولتك السابقة: الرحلة التي "
                f"أرجعتها تضم {len(future_steps)} مرحلة ({near_copy_names}) "
                f"تكاد تطابق خطوات الرحلة الحالية الـ{len(source_steps)} "
                "بنفس الترتيب دون دمج حقيقي -- وهذا غير مقبول كإعادة "
                "تصميم (راجع قواعد التصميم أعلاه). أعد تصميم هذه "
                "الرحلة انطلاقًا من نتيجة المتعامل: ادمج الخطوات التي "
                "تمثل منطقيًا إجراءً واحدًا، واحذف التنقل/إعادة الإدخال "
                "التي يمكن للمساعد القيام بها نيابة عن المتعامل، وأتمت "
                "الفحوصات الخلفية التي لا تتطلب حكمًا بشريًا حقيقيًا. "
                "أرجع رحلة أكثر كفاءة فعليًا هذه المرة."
            )
            retry_future_steps, retry_reasoning, _retry_failure = (
                self._run_ai_journey_attempt(
                    prompt + feedback, source_steps, is_arabic, relevant_standards
                )
            )
            if retry_future_steps is not None:
                future_steps, overall_reasoning = (
                    retry_future_steps, retry_reasoning
                )
                if self._journey_is_near_copy(future_steps, source_steps):
                    print(
                        "[JOURNEY] Retry still did not consolidate the "
                        "journey -- keeping the AI's own (second) "
                        "attempt as-is; a genuinely uncompressed "
                        "journey should surface as a real validation "
                        "issue, not be hidden."
                    )
            # else: the retry itself hard-failed (parse error / too few
            # usable stages) -- keep the first attempt's real output
            # rather than losing it, since it was at least usable.

        # ROOT-CAUSE FIX (confirmed in real production use, not just
        # mock testing -- see the report this fix was written for):
        # the language_instruction/system_prompt strengthening alone
        # was NOT sufficient to reliably stop qwen3:4b from generating
        # English content when Arabic was requested (and vice versa).
        # Rather than accept unreliable compliance, this is now a HARD
        # gate: if a majority of the accepted stages are in the wrong
        # language, retry ONCE with explicit corrective feedback
        # naming the exact violation (a stronger signal than the
        # original instruction, which the model evidently didn't
        # weight heavily enough) using the SAME compact prompt already
        # proven to get better compliance from a 4B model on a smaller
        # ask (see _build_compact_journey_prompt). Ollama remains the
        # sole author across both attempts -- this is a corrective
        # retry, not a template substitution. If the retry STILL
        # doesn't comply, this function returns (None, "") so run()
        # falls through to the deterministic template path -- which is
        # ALWAYS correctly language-matched (see _template()/
        # _dynamic_templates()) -- rather than ever returning
        # known-wrong-language AI content. This never loops more than
        # once and never silently accepts a language violation.
        if future_steps:
            expected_lang = "ar" if is_arabic else "en"
            mismatched = [
                step for step in future_steps
                if detect_language_mismatch(
                    " ".join(str(step.get(field, "")) for field in
                             ("name", "action", "detailed_description", "reasoning")),
                    expected_lang,
                )
            ]
            if len(mismatched) > len(future_steps) / 2:
                mismatched_names = ", ".join(
                    str(s.get("name", ""))[:40] for s in mismatched[:5]
                )
                print(
                    "[JOURNEY] Language-compliance check: "
                    f"{len(mismatched)} of {len(future_steps)} stage(s) "
                    f"are not in the requested language ({expected_lang}) "
                    f"-- retrying once with an explicit corrective prompt: "
                    f"{mismatched_names}"
                )
                language_retry_prompt = self._build_compact_journey_prompt(
                    service_name=service_name,
                    description=description,
                    numbered_steps=numbered_steps,
                    capabilities_text=capabilities_text,
                    is_arabic=is_arabic,
                ) + (
                    "\n\nYOUR PREVIOUS RESPONSE VIOLATED A HARD "
                    "REQUIREMENT: it was written in the wrong language. "
                    "Every single text field must be written ENTIRELY IN "
                    "ARABIC (\u0627\u0644\u0639\u0631\u0628\u064a\u0629 "
                    "\u0627\u0644\u0641\u0635\u062d\u0649) this time -- no "
                    "English words, no transliteration. This is "
                    "non-negotiable."
                    if is_arabic
                    else "\n\nYOUR PREVIOUS RESPONSE VIOLATED A HARD "
                    "REQUIREMENT: it was written in the wrong language. "
                    "Every single text field must be written ENTIRELY IN "
                    "ENGLISH this time -- no Arabic words. This is "
                    "non-negotiable."
                )
                retry_steps, retry_reasoning, _ = self._run_ai_journey_attempt(
                    language_retry_prompt, source_steps, is_arabic, relevant_standards
                )
                if retry_steps:
                    retry_mismatched = [
                        step for step in retry_steps
                        if detect_language_mismatch(
                            " ".join(str(step.get(field, "")) for field in
                                     ("name", "action", "detailed_description", "reasoning")),
                            expected_lang,
                        )
                    ]
                    if len(retry_mismatched) <= len(retry_steps) / 2:
                        print(
                            "[JOURNEY] Language-compliance retry succeeded: "
                            f"{len(retry_steps) - len(retry_mismatched)} of "
                            f"{len(retry_steps)} stage(s) now in the "
                            "requested language."
                        )
                        return retry_steps, retry_reasoning
                print(
                    "[AI FAILED -> FALLBACK] [JOURNEY] AI output still "
                    "not in the requested language after one corrective "
                    "retry -- falling back to the template-based journey "
                    "(always correctly language-matched) rather than "
                    "returning known-wrong-language AI content."
                )
                return None, ""

        return future_steps, overall_reasoning

    def _build_compact_journey_prompt(
        self, service_name, description, numbered_steps,
        capabilities_text, is_arabic,
    ):
        """Minimal, steps-only retry prompt for when the full prompt
        (with every design principle and the gaps/standards context)
        didn't get a usable 'steps' array out of the model -- a
        genuinely different, much smaller ask, sized for a 4B model
        under real output pressure. Deliberately drops the standards/
        gaps context and most design nuance; the goal here is ONLY to
        recover a valid, minimally-reasonable steps array so the
        service still gets an AI-authored (not template) journey. The
        richer design rules already shaped the first attempt; this
        pass exists purely to get the required structure out."""
        language_line = (
            "اكتب كل النصوص بالعربية الفصحى الواضحة."
            if is_arabic
            else "Write all text fields in clear English."
        )
        return f"""Redesign the future journey for this service. Output the "steps" array -- that is the required part of this task.

SERVICE: {service_name or "(not provided)"}
{description or ""}

CURRENT STEPS:
{numbered_steps}

CAPABILITIES:
{capabilities_text}

Rules: start from the customer's outcome, not the current step order. Merge steps that are one action. Automate what doesn't need a human. type="HUMAN" only for a real staff judgement call. Payment (if any) comes after the amount is known. Last stage delivers the result.

{language_line}

Output ONLY this JSON object, "steps" first, at most 5 stages, 1 short sentence per text field:
{{"steps": [{{"name": "", "type": "SYSTEM or HUMAN", "executor": "AGENT", "action": "", "detailed_description": "", "reasoning": "", "customer_role": "", "has_payment": false, "payment_reasoning": "", "requires_human_judgement": false, "human_judgement_reason": "", "requires_customer_approval": false, "depends_on_previous": "", "delivers_customer_result": false}}], "overall_reasoning": ""}}"""

    def _infer_change_type_and_sources(self, stage_text, source_steps):
        """Generic (no service-specific logic) classification of an
        AI-designed stage against the CURRENT journey's own steps,
        reusing the exact same vocabulary the template path already
        uses (KEPT / MERGED / AUTOMATED / NEW) instead of inventing a
        new change_type value outside the validator's contract.

        For each current step, checks how much of ITS OWN
        DISCRIMINATING vocabulary (stemmed, tolerant of Arabic/English
        paraphrase -- core/grounding.py) is reflected inside this
        stage's text. Words that recur across most of THIS service's
        own current steps (e.g. "system", "customer", "service" in an
        English service, or their Arabic equivalents) are down-
        weighted first -- purely statistically, computed fresh from
        this redesign's own current-step list, never a fixed
        stopword list -- so a generic word shared by every step
        doesn't make every future stage look related to every current
        step. Returns the list of matched current steps."""
        from collections import Counter
        from core.grounding import significant_words, light_stem

        if not source_steps:
            return []

        per_source_stems = [
            {light_stem(w) for w in significant_words(source)}
            for source in source_steps
        ]
        doc_freq = Counter()
        for stems in per_source_stems:
            doc_freq.update(stems)
        n = len(source_steps)
        generic_stems = (
            {stem for stem, freq in doc_freq.items() if freq / n > 0.5}
            if n > 2 else set()
        )

        stage_words = significant_words(stage_text)
        stage_stems = {light_stem(w) for w in stage_words}

        matched = []
        for source, stems in zip(source_steps, per_source_stems):
            discriminating = stems - generic_stems or stems
            if not discriminating:
                continue
            hits = sum(1 for stem in discriminating if stem in stage_stems)
            if hits / len(discriminating) >= 0.6:
                matched.append(source)
        return matched

    def _pick_generic_standard_id(self, change_type, applicable_standards):
        """Pick the best-fitting applicable standard id for a
        MERGED/AUTOMATED/NEW stage using only generic keyword
        matching against each catalog entry's OWN title/requirement/
        measurable_test text -- this is driven entirely by whatever
        standards this service's own StandardsAgent run marked
        applicable, never a fixed per-service or per-domain mapping.
        Returns "" when nothing genuinely fits, which is the honest
        outcome: validation_agent will then correctly flag that
        structural change as unjustified rather than being silently
        excused."""
        if not isinstance(applicable_standards, list) or not applicable_standards:
            return ""
        keyword_sets = {
            "AUTOMATED": (
                "burden", "administrative", "manual", "repeated",
                "intervention", "execut",
            ),
            "MERGED": (
                "repeat", "already available", "duplicate", "burden",
            ),
            "NEW": (
                "outcome", "proactive", "intent",
            ),
        }
        keywords = keyword_sets.get(change_type, ())
        if not keywords:
            return ""
        for item in applicable_standards:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                str(item.get(field, ""))
                for field in ("title", "requirement", "measurable_test")
            ).lower()
            if any(kw in text for kw in keywords):
                return str(item.get("standard_id", "")).strip()
        return ""

    def _run_ai_journey_attempt(self, prompt, source_steps, is_arabic, relevant_standards=None):
        """Single attempt at the full-journey generation call: sends
        `prompt` to the model, parses and validates the response, and
        returns (future_steps, overall_reasoning) on success or
        (None, "") if this attempt could not produce a usable journey
        at all (hard parse failure / too few usable stages). Split out
        of _generate_ai_future_journey() so it can be called a second
        time with corrective feedback appended to the prompt when the
        first attempt looks like an uncompressed copy of the current
        journey (see _journey_is_near_copy())."""
        journey_max_new_tokens = max(
            2200, min(6000, len(source_steps) * 220 + 1600),
        )

        try:
            response = self.llm.generate(
                system_prompt=(
                    # ROOT-CAUSE FIX: this was a fixed, English-only
                    # system prompt regardless of the requested output
                    # language -- system-role content is typically
                    # weighted more heavily than user-role content by
                    # chat-formatted LLM APIs, so an all-English system
                    # prompt could itself bias a small model toward
                    # English continuation even when the user prompt
                    # (correctly) asks for Arabic output. See the
                    # language_instruction comment above for the full
                    # trace.
                    "أنت خبير دقيق في تصميم الخدمات، تفكر بمنطق كل "
                    "خدمة الخاص بها (الاعتماديات، توقيت الدفع، "
                    "الأهلية، القرار البشري، وهل يوافق المتعامل تحديدًا "
                    "على خطة) بدلاً من تطبيق قالب ثابت أو افتراضي عام. "
                    "تُعيد دائمًا JSON صالحًا وكاملًا يطابق الشكل "
                    "المطلوب تمامًا، بدون أسوار markdown وبدون أي "
                    "تعليق خارج الـJSON. كل النصوص داخل الـJSON التي "
                    "تكتبها يجب أن تكون باللغة العربية الفصحى الواضحة "
                    "بالكامل -- هذا أمر إلزامي."
                    if is_arabic
                    else "You are a meticulous service-design expert who "
                    "reasons about each service's own real logic "
                    "(dependencies, payment timing, eligibility, "
                    "human judgement, and whether the CUSTOMER "
                    "specifically approves a plan) instead of applying "
                    "a fixed template or a generic default. You always "
                    "return valid, complete JSON matching exactly the "
                    "requested shape, with no markdown fences and no "
                    "commentary outside the JSON."
                ),
                user_prompt=prompt,
                max_new_tokens=journey_max_new_tokens,
                temperature=0.2,
            )
        except Exception as error:
            print(
                f"[AI FAILED -> FALLBACK] "
                f"[JOURNEY] AI full-journey call failed: {error}. "
                "Falling back to template-based journey."
            )
            return None, "", "call_failed"

        log_raw_response("JOURNEY.full_journey", response)

        # ROOT-CAUSE FIX: extract_json_with_salvage() recovers a
        # response that is genuinely valid JSON up to the point it was
        # cut off (num_predict/context exhausted mid-object on a real
        # Ollama 0.32.15 + qwen3:4b run) instead of discarding the
        # whole thing -- the trailing incomplete stage is dropped, but
        # every stage the model finished writing survives and is
        # validated normally below.
        result = extract_json_with_salvage(response)
        if not isinstance(result, dict) or has_parse_error(result):
            raw_text = (
                result.get("raw_response", "") if isinstance(result, dict) else ""
            ) or str(response)
            looks_truncated = bool(raw_text) and not raw_text.rstrip().endswith(
                ("}", "]")
            )
            print(
                f"[AI FAILED -> FALLBACK] "
                "[JOURNEY] AI full-journey output unusable (parse "
                f"error{', response looks truncated mid-JSON -- consider '
                'raising journey_max_new_tokens further' if looks_truncated else ''}"
                "). Falling back to template-based journey."
            )
            return None, "", "parse_error"

        raw_steps = result.get("steps")
        max_reasonable_steps = max(20, len(source_steps) * 2)
        # ROOT-CAUSE FIX (real Ollama 0.32.15 + qwen3:4b failure
        # signature): the model sometimes returns perfectly valid JSON
        # containing ONLY "overall_reasoning" -- no "steps" key at
        # all, or an empty/malformed one -- as if it treated writing
        # the reasoning as completing the task. This is distinguished
        # from a genuine parse failure (above) specifically so the
        # caller can retry once with a shorter, steps-only prompt
        # instead of giving up immediately (see
        # _generate_ai_future_journey's compact-retry path).
        if not isinstance(raw_steps, list) or not raw_steps:
            print(
                f"[AI FAILED -> FALLBACK] "
                "[JOURNEY] AI full-journey output unusable (no "
                "'steps' array in an otherwise valid response -- "
                "the model likely spent its output on "
                "overall_reasoning only)."
            )
            return None, "", "missing_steps"
        if not (2 <= len(raw_steps) <= max_reasonable_steps):
            print(
                f"[AI FAILED -> FALLBACK] "
                "[JOURNEY] AI full-journey output unusable (step "
                f"count {len(raw_steps)} outside sane range "
                f"2-{max_reasonable_steps} for a "
                f"{len(source_steps)}-step current journey). Falling "
                "back to template-based journey."
            )
            return None, "", "step_count_out_of_range"

        # ROOT-CAUSE FIX: this used to discard the ENTIRE AI-designed
        # journey the moment a single stage was malformed or had a
        # thin detailed_description -- so one weak stage out of six
        # good ones threw away all six and fell back to the generic
        # template. Real Ollama 0.32.15 + qwen3:4b responses observed
        # in testing were "unusable" almost exclusively for this
        # reason: one stage short on detail, not the whole design
        # being wrong. Skip only the individual bad stage now (with a
        # named field default good enough to still be genuinely
        # useful) and keep every other stage the model actually
        # reasoned about; only fall back to the template if too few
        # usable stages remain to form a real journey.
        future_steps = []
        skipped_steps = 0
        for number, raw in enumerate(raw_steps, start=1):
            if not isinstance(raw, dict):
                print(
                    f"[JOURNEY] Skipping AI stage {number}: not an "
                    "object."
                )
                skipped_steps += 1
                continue

            name = str(raw.get("name", "")).strip()
            detailed_description = str(
                raw.get("detailed_description", "")
            ).strip()
            action = str(raw.get("action", "")).strip() or detailed_description
            reasoning_fallback = str(raw.get("reasoning", "")).strip()

            # A short/missing detailed_description no longer discards
            # the stage outright -- fall back to the stage's own
            # action/reasoning text (still real, model-produced
            # content grounded in this specific service) if it's
            # substantial enough to be useful; only skip the stage if
            # there's truly nothing usable to describe it with.
            if not name:
                print(
                    f"[JOURNEY] Skipping AI stage {number}: no name."
                )
                skipped_steps += 1
                continue
            if len(detailed_description) < 30:
                best_fallback = max(
                    (action, reasoning_fallback), key=len, default=""
                )
                if len(best_fallback) >= 15:
                    detailed_description = best_fallback
                else:
                    print(
                        f"[JOURNEY] Skipping AI stage {number} "
                        f"({name!r}): no usable description."
                    )
                    skipped_steps += 1
                    continue

            step_type = str(raw.get("type", "")).strip().upper()
            if step_type not in ("SYSTEM", "HUMAN"):
                step_type = (
                    "HUMAN" if raw.get("requires_human_judgement") else "SYSTEM"
                )

            raw_executor = str(raw.get("executor", "")).strip().upper()
            if step_type == "SYSTEM" and raw_executor in (
                "GOVERNMENT_SYSTEM", "EXTERNAL_SYSTEM",
            ):
                step_owner = raw_executor
            else:
                step_owner = "ASSISTANT"

            has_payment = bool(raw.get("has_payment", False))
            # MERGED, hardened further per the merge task: a step is
            # only ever a genuine customer plan-approval control point
            # when the model explicitly marked it so AND that stage
            # also has real evidence of payment or an explicit
            # customer-approval reason -- a bare unsupported flag from
            # the model is not enough on its own to create a control
            # point (mirrors the capability-veto anti-hallucination
            # gate applied to the whole journey below).
            requires_customer_approval = bool(
                raw.get("requires_customer_approval", False)
            )
            delivers_customer_result = bool(
                raw.get("delivers_customer_result", False)
            )
            reasoning = str(raw.get("reasoning", "")).strip()
            payment_reasoning = str(raw.get("payment_reasoning", "")).strip()
            human_reason = str(raw.get("human_judgement_reason", "")).strip()
            depends_on = str(raw.get("depends_on_previous", "")).strip()
            customer_role = str(raw.get("customer_role", "")).strip() or (
                "لا يوجد عمل إداري على المتعامل"
                if is_arabic
                else "No administrative customer work"
            )

            combined_reasoning = reasoning
            if has_payment and payment_reasoning:
                combined_reasoning = (
                    combined_reasoning + " " + payment_reasoning
                ).strip()
            if step_type == "HUMAN" and human_reason:
                combined_reasoning = (
                    combined_reasoning + " " + human_reason
                ).strip()

            # ROOT-CAUSE FIX: this used to hardcode
            # change_type="AI_DESIGNED" -- a value outside the
            # backend/frontend's existing change_type contract
            # (KEPT/MERGED/REMOVED/AUTOMATED/NEW). Classify each
            # AI-designed stage against the CURRENT journey using the
            # exact same generic vocabulary the deterministic template
            # path already uses, so the Dashboard, the traceability
            # rules and the Zero Bureaucracy change-summary all treat
            # AI-designed and template-designed stages identically --
            # no new value to add to any schema/UI, on either path.
            stage_text_for_matching = " ".join([
                name, action, detailed_description, reasoning,
            ])
            matched_sources = self._infer_change_type_and_sources(
                stage_text_for_matching, source_steps
            )
            source_was_manual = any(
                self._contains(source, [
                    "employee", "agent", "supervisor", "officer", "staff",
                    "manually", "manual", "الموظف", "موظف", "المشرف",
                    "المدير", "يدويا", "يدويًا",
                ])
                for source in matched_sources
            )
            if len(matched_sources) > 1:
                change_type = "MERGED"
            elif step_type == "SYSTEM":
                change_type = (
                    "AUTOMATED"
                    if matched_sources and source_was_manual
                    else "KEPT" if matched_sources else "NEW"
                )
            else:
                change_type = "KEPT" if matched_sources else "NEW"

            applicable_standards_list = (
                (relevant_standards or {}).get("applicable_standards", [])
                if isinstance(relevant_standards, dict) else []
            )
            derived_standard_id = (
                self._pick_generic_standard_id(
                    change_type, applicable_standards_list
                )
                if change_type in ("MERGED", "AUTOMATED", "NEW")
                else ""
            )

            future_steps.append({
                "step_number": len(future_steps) + 1,
                "name": name,
                "type": step_type,
                "action": action,
                "change_type": change_type,
                "reason": reasoning or (
                    "قرار مصمم بواسطة الذكاء الاصطناعي بناءً على منطق "
                    "الخدمة الفعلي."
                    if is_arabic
                    else "AI-designed based on this specific service's "
                    "own logic."
                ),
                "standard_id": derived_standard_id or None,
                "related_standard_ids": (
                    [derived_standard_id] if derived_standard_id else []
                ),
                "source_steps": matched_sources,
                "semantic_category": (
                    "customer_outcome"
                    if delivers_customer_result
                    else "payment"
                    if has_payment
                    else "plan_review"
                    if requires_customer_approval
                    else "human_control"
                    if step_type == "HUMAN"
                    else "execution_continuity"
                ),
                "component_categories": (
                    ["payment"] if has_payment else []
                ),
                "implementation_status": "PROPOSED",
                # MERGED FROM P1 (same root-cause fix as the template
                # path): derive customer_burden from the stage's own
                # customer_role text instead of hardcoding it.
                "customer_burden": step_customer_role_is_burden(
                    customer_role
                ),
                "customer_control_points": (
                    ["Approve or edit the plan"]
                    if requires_customer_approval
                    else []
                ),
                "owner": "HUMAN" if step_type == "HUMAN" else step_owner,
                "assistant_action": action,
                "customer_role": customer_role,
                "visible_before_payment": True,
                "completion_evidence": (
                    "سجل تنفيذ قابل للمراجعة"
                    if is_arabic
                    else "Reviewable execution log"
                ),
                "has_payment": has_payment,
                "requires_human_judgement": step_type == "HUMAN",
                "requires_customer_approval": requires_customer_approval,
                "depends_on_previous": depends_on,
                "detailed_description": detailed_description,
                "reasoning": combined_reasoning or reasoning,
                "analysis_source": ai_label(),
            })

        if skipped_steps:
            print(
                f"[JOURNEY] {skipped_steps} of {len(raw_steps)} AI "
                f"stage(s) were skipped as unusable; {len(future_steps)} "
                "usable stage(s) kept."
            )

        # Only fall back to the generic template if too little of the
        # AI's design survived to call it a real journey -- a handful
        # of usable, service-specific stages is still far better than
        # discarding all of them for the fixed template.
        if len(future_steps) < 2:
            print(
                f"[AI FAILED -> FALLBACK] "
                "[JOURNEY] AI full-journey output unusable (only "
                f"{len(future_steps)} usable stage(s) survived "
                "validation out of "
                f"{len(raw_steps)}). Falling back to template-based "
                "journey."
            )
            return None, "", "too_few_usable_stages"

        if future_steps and not any(
            step.get("semantic_category") == "customer_outcome"
            for step in future_steps
        ):
            future_steps[-1]["semantic_category"] = "customer_outcome"

        # ROOT-CAUSE FIX (structural safety net, not a content
        # override): the prompt now explicitly instructs package/tier
        # selection to precede fee confirmation and payment, but a
        # real qwen3:4b response occasionally still orders a payment
        # stage before the package-selection stage it depends on. This
        # reorders the AI's own stages (never rewrites their content,
        # never invents a stage) to enforce that hard business rule
        # deterministically, the same way payment-after-result timing
        # is a hard rule elsewhere in this file.
        future_steps = self._enforce_package_before_payment_order(
            future_steps
        )

        # ROOT-CAUSE FIX (structural safety net, generic): the prompt
        # now explicitly asks the model to combine fee-confirmation
        # and payment into one stage when there is no independent
        # customer decision between them, but a real response
        # occasionally still splits them into two thin, redundant
        # stages ("explain the fee" then "collect payment"). Detect
        # that specific pattern purely by generic keyword signal (fee/
        # amount vocabulary immediately followed by a payment stage,
        # neither service- nor language-specific) and merge them,
        # keeping every field's real content rather than discarding
        # either stage's description.
        future_steps = self._merge_redundant_consecutive_fee_stages(
            future_steps
        )

        # ROOT-CAUSE FIX (structural safety net, same pattern as the
        # two safety nets above): the prompt now explicitly forbids a
        # pre-payment stage from claiming the final amount is known
        # (rule 7b above), but a real qwen3:4b response occasionally
        # still gives a plan-review/approval-elimination stage a
        # reasoning sentence that borrows payment-amount-clarity
        # language it hasn't earned yet at that point in the journey
        # (e.g. "eliminates unnecessary approvals... provides clear
        # reasons for the payment amount" on a stage before the one
        # that actually has_payment=true). The AI-primary semantic
        # review (validation_agent.py) correctly flags this as a
        # logical contradiction. This corrects only that specific
        # stated claim, deterministically and generically (bilingual
        # keyword signal, not service-specific) -- it never removes
        # the approval-elimination stage itself, never invents a
        # stage, and never touches the actual payment stage or any
        # stage after it.
        future_steps = self._prevent_premature_payment_amount_claims(
            future_steps
        )

        overall_reasoning = str(result.get("overall_reasoning", "")).strip()

        # Lightweight, NON-BLOCKING language-consistency diagnostic (no
        # retry): checks the accepted stages' user-facing text against
        # the language that was actually requested (is_arabic above),
        # using the same character-range detector already used for
        # is_arabic itself (core/llm.py's detect_language_mismatch --
        # a ratio over alphabetic characters, resistant to false
        # positives from proper nouns/technical loanwords like "UAE
        # PASS" or "EMX"). Deliberately does NOT retry the generation:
        # a retry would re-run the full journey prompt (this project's
        # heaviest LLM call, with its own carefully tuned token
        # budget -- see core/llm.py's resolve_context_budget) for a
        # failure mode with no confirmed real-world frequency yet.
        # This only makes the failure visible in the same honest
        # [AI FAILED -> FALLBACK]-style log used everywhere else in
        # this file, without changing what's returned to the caller or
        # adding latency/token cost to every request. If logs show
        # this firing in practice, a bounded single-retry is the
        # natural next enhancement -- deliberately not implemented
        # here; see the Phase-2 localization report for the rationale.
        expected_lang = "ar" if is_arabic else "en"
        mismatched_steps = [
            step.get("name", f"stage {i + 1}")
            for i, step in enumerate(future_steps)
            if detect_language_mismatch(step.get("detailed_description", ""), expected_lang)
        ]
        if mismatched_steps:
            print(
                "[JOURNEY] Language-consistency check: "
                f"{len(mismatched_steps)} of {len(future_steps)} stage(s) "
                f"look like they may not be in the requested language "
                f"({expected_lang}): {mismatched_steps}. Not retried "
                "(see comment above) -- returning as generated."
            )

        print(
            "[JOURNEY] AI-designed future journey accepted: "
            f"{len(future_steps)} stages."
        )
        return future_steps, overall_reasoning, None

    def _merge_redundant_consecutive_fee_stages(self, future_steps):
        """If a stage that only explains/confirms the fee/amount is
        immediately followed by the actual payment-collection stage,
        with no distinct customer decision in between, merge them into
        one -- avoids an artificially inflated stage count for what is
        really a single "review and pay" interaction. Purely generic
        keyword detection (fee/amount vs. payment vocabulary, English
        and Arabic); never touches stages that aren't adjacent or that
        involve a real intervening decision."""
        if not future_steps or len(future_steps) < 2:
            return future_steps

        fee_signals = (
            "fee", "amount", "price", "cost", "total",
            "رسوم", "مبلغ", "سعر", "تكلفة", "إجمالي",
        )
        payment_signals = ("payment", "pay", "دفع", "سداد", "يدفع")

        def text_of(step):
            return " ".join(
                str(step.get(field, "")) for field in ("name", "action")
            ).lower()

        merged = []
        skip_next = False
        for index, step in enumerate(future_steps):
            if skip_next:
                skip_next = False
                continue
            if not isinstance(step, dict) or index + 1 >= len(future_steps):
                merged.append(step)
                continue

            nxt = future_steps[index + 1]
            if not isinstance(nxt, dict):
                merged.append(step)
                continue

            cur_text = text_of(step)
            nxt_text = text_of(nxt)
            cur_is_fee_only = (
                not step.get("has_payment")
                and not step.get("requires_customer_approval")
                and any(s in cur_text for s in fee_signals)
                and not any(s in cur_text for s in payment_signals)
            )
            nxt_is_payment = bool(nxt.get("has_payment")) or any(
                s in nxt_text for s in payment_signals
            )

            if cur_is_fee_only and nxt_is_payment:
                print(
                    "[JOURNEY] Merging redundant consecutive stages: "
                    f"{step.get('name')!r} + {nxt.get('name')!r} -- "
                    "fee confirmation with no independent decision "
                    "before payment."
                )
                combined = dict(nxt)
                combined["detailed_description"] = " ".join(
                    filter(None, [
                        str(step.get("detailed_description", "")).strip(),
                        str(nxt.get("detailed_description", "")).strip(),
                    ])
                ).strip()
                combined["action"] = " ".join(
                    filter(None, [
                        str(step.get("action", "")).strip(),
                        str(nxt.get("action", "")).strip(),
                    ])
                ).strip()
                combined["reasoning"] = " ".join(
                    filter(None, [
                        str(step.get("reasoning", "")).strip(),
                        str(nxt.get("reasoning", "")).strip(),
                    ])
                ).strip()
                combined_sources = list(dict.fromkeys(
                    list(step.get("source_steps") or [])
                    + list(nxt.get("source_steps") or [])
                ))
                combined["source_steps"] = combined_sources
                if len(combined_sources) > 1:
                    combined["change_type"] = "MERGED"
                merged.append(combined)
                skip_next = True
                continue

            merged.append(step)

        for idx, step in enumerate(merged, start=1):
            if isinstance(step, dict):
                step["step_number"] = idx
        return merged

    def _prevent_premature_payment_amount_claims(self, future_steps):
        """A stage that runs BEFORE the actual payment stage must never
        claim the final payment/fee amount is already known, clear, or
        justified -- that claim only belongs to the stage that actually
        has_payment=true (see design rule 7b in the prompt above). A
        generated plan-review/approval-elimination stage occasionally
        borrows payment-amount-clarity language it hasn't earned yet at
        that point in the journey (e.g. "eliminates unnecessary
        approvals ... provides clear reasons for the payment amount" on
        a stage before the payment stage), which the AI-primary semantic
        review (validation_agent.py) correctly flags as a logical
        contradiction. Detected purely by generic, bilingual keyword
        signal -- never service-specific -- and only ever rewrites the
        offending stage's own stated reasoning; it never removes the
        stage, never invents one, and never touches the payment stage
        itself or anything after it.
        """
        if not future_steps:
            return future_steps

        payment_index = next(
            (
                i for i, step in enumerate(future_steps)
                if isinstance(step, dict) and step.get("has_payment")
            ),
            None,
        )
        if payment_index is None:
            return future_steps

        amount_signals = (
            "payment amount", "amount of the payment", "amount of payment",
            "fee amount", "final amount", "amount due", "amount to be paid",
            "مبلغ الدفع", "مبلغ السداد", "المبلغ النهائي", "قيمة الدفع",
            "قيمة المبلغ",
        )
        clarity_signals = (
            "clear", "known", "determined", "confirms the amount",
            "reasons for the payment", "reason for the payment",
            "واضح", "واضحة", "محدد", "محددة", "معروف", "معروفة", "يؤكد",
            "أسباب", "سبب واضح",
        )

        for step in future_steps[:payment_index]:
            if not isinstance(step, dict) or step.get("has_payment"):
                continue
            for field in ("reason", "reasoning"):
                text = str(step.get(field, ""))
                if not text:
                    continue
                lower = text.lower()
                has_amount_claim = any(
                    signal in lower or signal in text
                    for signal in amount_signals
                )
                has_clarity_claim = any(
                    signal in lower or signal in text
                    for signal in clarity_signals
                )
                if not (has_amount_claim and has_clarity_claim):
                    continue

                is_ar = any("\u0600" <= ch <= "\u06ff" for ch in text)
                replacement = (
                    "تُلغي هذه الخطوة الموافقات غير الضرورية بمراجعة "
                    "المتعامل للخطة نفسها؛ المبلغ النهائي غير معروف بعد "
                    "في هذه المرحلة، ويُحدَّد ويُؤكَّد لاحقًا في خطوة "
                    "الدفع."
                    if is_ar
                    else "This stage removes unnecessary approvals by "
                    "letting the customer review the plan itself; the "
                    "final amount is not yet known at this point and is "
                    "determined and confirmed later, at the payment "
                    "stage."
                )
                print(
                    "[JOURNEY] Corrected a premature payment-amount "
                    f"claim in stage {step.get('name')!r} (payment is "
                    f"stage {payment_index + 1}): {field} rewritten to "
                    "remove the contradiction."
                )
                step[field] = replacement

        return future_steps

    def _enforce_package_before_payment_order(self, future_steps):
        """If a package/tier/plan-selection stage exists AND a payment
        stage exists, guarantee the package stage comes first -- the
        customer must choose (and have the fee confirmed) before being
        asked to pay. Only reorders when a violation actually exists;
        a journey with no package stage, no payment stage, or already
        correctly ordered is returned unchanged."""
        if not future_steps or len(future_steps) < 2:
            return future_steps

        package_signals = (
            "package", "tier", "plan", "bundle", "subscription",
            "duration", "باقة", "باقه", "الحزمة", "الحزمه", "خطة", "خطه",
        )

        def is_package_stage(step):
            if not isinstance(step, dict):
                return False
            if step.get("has_payment"):
                return False
            text = " ".join(
                str(step.get(field, ""))
                for field in ("name", "action", "customer_role")
            ).lower()
            return any(signal in text for signal in package_signals)

        package_index = next(
            (i for i, s in enumerate(future_steps) if is_package_stage(s)),
            None,
        )
        payment_index = next(
            (i for i, s in enumerate(future_steps) if isinstance(s, dict) and s.get("has_payment")),
            None,
        )

        if (
            package_index is None
            or payment_index is None
            or package_index < payment_index
        ):
            return future_steps

        print(
            "[JOURNEY] Reordering: package/tier selection stage was "
            "placed after the payment stage -- moving it before "
            "payment (fee must be confirmed before it is charged)."
        )
        reordered = list(future_steps)
        package_stage = reordered.pop(package_index)
        # We only reach here when package_index > payment_index (the
        # violation case, since the early-return above already
        # handles package_index < payment_index) -- popping an item
        # from AFTER payment_index doesn't shift payment_index itself.
        reordered.insert(payment_index, package_stage)
        for index, step in enumerate(reordered, start=1):
            if isinstance(step, dict):
                step["step_number"] = index
        return reordered

    def _journey_is_near_copy(self, future_steps, source_steps):
        """True when the AI-designed future journey looks like the
        current journey copied 1:1 with light rewording rather than a
        real redesign -- the exact real-world failure signature
        reported against qwen3:4b: same-or-larger stage count, most
        future stages textually near-identical to one current step
        each, in roughly the same order.

        Deliberately conservative on both sides: it only fires when
        there is NO real reduction in stage count AND a clear majority
        of stages individually match a current step almost verbatim,
        so a genuinely redesigned journey that happens to keep a
        similar stage count (e.g. a 3-step service that was already
        near-minimal) is not penalized -- only the "renamed but not
        reduced" pattern is."""
        if not future_steps or not source_steps:
            return False
        if len(source_steps) <= 3:
            # Too little to meaningfully consolidate further; the
            # prompt itself allows keeping a similar count here.
            return False
        if len(future_steps) < len(source_steps):
            return False

        import difflib

        unmatched_sources = list(source_steps)
        near_identical = 0
        for step in future_steps:
            if not isinstance(step, dict):
                continue
            text = " ".join(
                str(step.get(field, "")) for field in ("name", "action")
            ).strip()
            if not text:
                continue
            best_ratio = 0.0
            best_index = None
            for index, source in enumerate(unmatched_sources):
                ratio = difflib.SequenceMatcher(
                    None, text.lower(), str(source).lower()
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_index = index
            if best_ratio >= 0.5:
                near_identical += 1
                if best_index is not None:
                    unmatched_sources.pop(best_index)

        return near_identical >= max(2, (len(future_steps) * 2) // 3)

    def _apply_capability_veto(self, future_steps, capabilities):
        """Hard safety net (prevents hallucinations): if evidence-gated
        capability detection explicitly found NO evidence of payment
        for THIS service, strip that flag from any step the journey
        generation attached it to anyway -- whether that step came
        from the AI path or the deterministic fallback. MERGED FROM P1.

        Deliberately generic: driven entirely by the per-service
        evidence gathered upstream, never by service_type, a domain
        keyword, or any special-case for one kind of service (e.g.
        complaints). When capabilities is empty/unavailable, this is
        a no-op and the journey is returned unchanged.
        """
        if not isinstance(capabilities, dict) or not future_steps:
            return future_steps

        veto_payment = capabilities.get("has_payment") is False
        # Note: requires_customer_approval is intentionally NOT vetoed
        # by has_human_approval -- customer plan approval and human
        # (staff) approval are different things (merge task
        # requirement: do not conflate human_approval with
        # customer_approval). A genuinely non-evidenced customer
        # approval step on the AI path is a prompt-compliance matter,
        # handled by the prompt's own evidence requirement and by the
        # template path's has_payment_stage / requires_explicit_
        # customer_approval gate, not by this veto.

        for step in future_steps:
            if not isinstance(step, dict):
                continue
            if veto_payment and step.get("has_payment"):
                step["has_payment"] = False
                if step.get("semantic_category") == "payment":
                    step["semantic_category"] = "execution_continuity"
                components = step.get("component_categories")
                if isinstance(components, list) and "payment" in components:
                    step["component_categories"] = [
                        c for c in components if c != "payment"
                    ]
                print(
                    "[JOURNEY] Capability veto: stripped an invented "
                    f"payment flag from step '{step.get('name', '')}' "
                    "-- no evidence of payment for this service."
                )

        return future_steps

    def _service_profile(self, service, text):
        lowered = str(text).lower()
        classification = classify_service(service)
        return {
            **classification,
            "has_data_stage": self._contains(lowered, [
                "data", "document", "upload", "identity", "verify", "review",
                "بيانات", "مستند", "وثيق", "يرفع", "يرفق", "الهوية",
                "الهويه", "يتحقق", "يراجع", "يتأكد", "يتاكد",
            ]),
            "has_choice_stage": self._contains(lowered, [
                "choose", "select", "package", "plan", "duration", "term",
                "subscription", "legal form", "business activity", "auto-renew",
                "يختار", "يحدد", "باقة", "باقه", "خطة", "خطه", "مدة",
                "مده", "عقد", "اشتراك", "الشكل القانوني", "نوع النشاط",
                "التجديد التلقائي",
            ]),
            "has_payment_stage": classification[
                "requires_customer_payment"
            ],
            "has_human_control_stage": classification[
                "requires_human_decision"
            ],
            # MERGED / BUG FIX (merge task section 2/3): a customer
            # plan-review/approval stage is only genuinely warranted
            # when there is real evidence the CUSTOMER (not staff, not
            # the agent, not a government reviewer) actually approves
            # a plan or amount before execution. Payment is treated as
            # sufficient evidence on its own (the customer inherently
            # approves an amount before it is charged), matching the
            # merge task's own example. Beyond that, only explicit
            # approval/consent/authorization language in the service's
            # own text counts -- never a default for every service,
            # and never a hardcoded exception keyed to any single
            # archetype (e.g. complaints) in either direction.
            "requires_explicit_customer_approval": (
                classification["requires_customer_payment"]
                or self._contains(lowered, [
                    "customer approves", "customer authorizes",
                    "customer signs", "customer confirms the plan",
                    "customer reviews and approves",
                    "يوافق المتعامل", "يعتمد المتعامل", "يوقع المتعامل",
                    "توقيع المتعامل", "موافقة المتعامل", "تفويض المتعامل",
                    "يفوض المتعامل",
                ])
            ),
        }

    def _customer_experience_from_ai_journey(self, future_steps, is_arabic):
        """Generic (no service-specific branching) summary of what
        the customer actually does across an AI-designed journey,
        derived entirely from the stages' own customer_role fields --
        this is what replaces the archetype-keyed canned narrative in
        _customer_experience() when the AI actually authored the
        journey, so the description always matches what THIS service's
        journey really asks of the customer."""
        no_work_phrases = (
            "none", "لا يوجد", "no administrative", "no additional",
        )
        customer_actions = []
        for step in future_steps or []:
            if not isinstance(step, dict):
                continue
            role = str(step.get("customer_role", "")).strip()
            if not role or role.lower() in no_work_phrases:
                continue
            if any(phrase in role for phrase in no_work_phrases):
                continue
            customer_actions.append(role)

        if not customer_actions:
            return (
                "المساعد ينفذ الرحلة بالكامل تلقائيًا دون أي عمل إداري "
                "على المتعامل."
                if is_arabic
                else "The assistant executes the entire journey "
                "automatically, with no administrative work left for "
                "the customer."
            )

        actions_text = "، ".join(customer_actions) if is_arabic else ", ".join(
            customer_actions
        )
        return (
            f"يقتصر دور المتعامل على: {actions_text}. يتولى المساعد "
            "كل بحث وإدخال وتحقق وتنسيق ومتابعة أخرى حتى النتيجة."
            if is_arabic
            else f"The customer's role is limited to: {actions_text}. "
            "The assistant handles all other search, entry, "
            "verification, coordination and follow-up through to the "
            "outcome."
        )

    def _customer_experience(self, profile, is_arabic):
        if profile.get("service_kind") == "INTERNATIONAL_SHIPMENT":
            return (
                "المساعد يجمع البيانات والمستندات ويجهز الحجز والجمارك والملصق. "
                "يسلّم المتعامل الشحنة فقط للمندوب؛ تؤكد EMX الوزن والأبعاد "
                "والسعر النهائي، ثم يعتمد المتعامل المبلغ ويدفع ويتولى المساعد "
                "التفعيل والتتبع حتى التسليم."
                if is_arabic
                else "The assistant gathers data and documents and prepares the "
                "booking, customs file and label. The customer only hands the item "
                "to the courier; EMX verifies weight, dimensions and the final quote, "
                "then the customer pays and the assistant tracks delivery."
            )
        if profile.get("service_kind") == "POSTAL_ACTIVITY_LICENSE":
            return (
                "المساعد يسترجع بيانات الشركة والمستندات ويقدم الطلب ويتابع "
                "الموافقة. بعد الموافقة يحسب النظام الرسوم السنوية بنسبة 10% من "
                "مبيعات الأنشطة البريدية وبحد أدنى 100,000 درهم مقدمًا، ويعتمد "
                "المتعامل التحويل البنكي فقط."
                if is_arabic
                else "The assistant retrieves company data and documents, submits "
                "the application and follows approval. After approval, the system "
                "calculates 10% of annual postal-activity sales with AED 100,000 "
                "payable upfront as the minimum; the customer only authorizes the bank transfer."
            )
        if profile["has_payment_stage"]:
            return (
                "المتعامل يختار الباقة عند وجودها، ويراجع الخطة فيوافق أو "
                "يعدلها، ثم يعتمد الدفع. المساعد ينفذ كل البحث والإدخال "
                "والتحقق والرفع والتنسيق والمتابعة حتى النتيجة."
                if is_arabic
                else "The customer selects a package when applicable, reviews "
                "and approves or edits the plan, then authorizes payment. The "
                "assistant performs all search, entry, verification, upload, "
                "coordination and follow-up through the outcome."
            )
        if profile["service_archetype"] in {"COMPLAINT", "DISPUTE_REFUND"}:
            return (
                "يشرح المتعامل النتيجة المطلوبة ثم يراجع صياغة الحالة ويوافق "
                "على إرسالها. يسترجع المساعد البيانات، يبني ملف الحالة، يرسله، "
                "يتابع المدة والتصعيد، ويسلم القرار ومسار الاعتراض دون دفع."
                if is_arabic
                else "The customer describes the desired outcome, reviews the "
                "case and approves its submission. The assistant retrieves data, "
                "builds and submits the case, monitors SLA and escalation, and "
                "delivers the decision and objection path without payment."
            )
        # BUG FIX (merge task section 2): this generic fallback branch
        # used to unconditionally describe a customer plan-review/
        # approval interaction for every remaining service type, which
        # is exactly the hardcoded-default behavior the merge task
        # flags as wrong. Only describe that interaction when the
        # service profile actually has evidence for it (same generic
        # flag used to gate the "review" template stage above);
        # otherwise describe direct execution with no invented
        # approval step.
        if profile.get("requires_explicit_customer_approval"):
            return (
                "يشرح المتعامل النتيجة المطلوبة ويراجع خطة الإجراء فيوافق أو "
                "يعدلها. ينفذ المساعد البحث والإدخال والتحقق والرفع والتنسيق "
                "والمتابعة حتى النتيجة، ولا ينشئ دفعًا غير مثبت."
                if is_arabic
                else "The customer describes the outcome and approves or edits "
                "the action plan. The assistant performs search, entry, "
                "verification, upload, coordination and follow-up through the "
                "result, without creating an unconfirmed payment."
            )
        return (
            "يشرح المتعامل النتيجة المطلوبة فقط. ينفذ المساعد البحث والإدخال "
            "والتحقق والتنسيق والمتابعة حتى النتيجة من غير أي خطوة موافقة "
            "على خطة أو مبلغ، لأن الخدمة لا تتضمن دليلاً على ذلك."
            if is_arabic
            else "The customer only describes the desired outcome. The "
            "assistant performs search, entry, verification, coordination "
            "and follow-up through to the result, with no plan- or "
            "amount-approval step, since this service has no evidence of one."
        )

    def _dynamic_templates(self, profile, is_arabic):
        if profile.get("service_kind") == "INTERNATIONAL_SHIPMENT":
            return self._international_shipment_templates(is_arabic)
        if profile.get("service_kind") == "POSTAL_ACTIVITY_LICENSE":
            return self._postal_license_templates(is_arabic)
        templates = [self._template("intent", is_arabic, profile)]
        if profile["has_package_stage"]:
            templates.append(self._template("package", is_arabic, profile))
        if profile["has_data_stage"]:
            templates.append(self._template("data", is_arabic, profile))
        # BUG FIX (merge task section 2): the "review" stage is a
        # customer plan-review/approval control point. It must only
        # appear when there is real evidence the customer approves a
        # plan/amount before execution -- previously added
        # unconditionally to every journey regardless of service type.
        if profile.get("requires_explicit_customer_approval"):
            templates.append(self._template("review", is_arabic, profile))
        if profile["has_payment_stage"]:
            templates.append(self._template("payment", is_arabic, profile))
        templates.append(self._template("execution", is_arabic, profile))
        if profile["has_human_control_stage"]:
            templates.append(self._template("human", is_arabic, profile))
        templates.append(self._template("result", is_arabic, profile))
        return templates

    def _special_template(
        self,
        name,
        action,
        reason,
        semantic_category,
        component_categories,
        customer_role,
        completion_evidence,
        standard_id="STAGE-05",
        step_type="SYSTEM",
        customer_control_points=None,
    ):
        return {
            "name": name,
            "action": action,
            "reason": reason,
            "standard_id": standard_id,
            "related_standard_ids": ["STD-04", "STD-05"],
            "semantic_category": semantic_category,
            "component_categories": component_categories,
            "type": step_type,
            "customer_control_points": customer_control_points or [],
            "customer_role": customer_role,
            "visible_before_payment": True,
            "completion_evidence": completion_evidence,
        }

    def _international_shipment_templates(self, is_arabic):
        if is_arabic:
            return [
                self._special_template(
                    "المساعد يفهم طلب الشحن ويحدد الوجهة والسياق",
                    "يحدد خدمة الشحن الدولي والوجهة ونوع الشحنة ويستخدم بيانات الشركة المصرح بها دون تنقل أو تسجيل متكرر.",
                    "بدء الرحلة من النتيجة المطلوبة.", "intent_context", ["initiation"],
                    "وصف نتيجة الشحن المطلوبة", "طلب شحن دولي مسجل", "STD-01",
                ),
                self._special_template(
                    "المساعد يسترجع بيانات الأطراف ومستندات الجمارك ويتحقق منها",
                    "يسترجع بيانات المرسل والمستلم والفاتورة ومستندات الجمارك من المصادر المتصلة، ويطلب فقط الاستثناء غير المتوفر.",
                    "إزالة الإدخال والرفع المتكرر.", "data_completion", ["data"],
                    "لا يعيد إدخال بيانات أو مستندات متاحة", "بيانات ومستندات موثقة", "STAGE-03",
                ),
                self._special_template(
                    "المساعد يقارن باقات الشحن ويوصي بالأنسب",
                    "يقارن ستاندرد وإكسبريس وبريميوم حسب السرعة والاحتياج، ويثبت اختيار المتعامل في الخطة دون افتراض السعر قبل الوزن.",
                    "فصل اختيار مستوى الخدمة عن السعر النهائي.", "package_selection", ["package"],
                    "اختيار الباقة المقترحة أو تغييرها", "الباقة والمدة المتوقعة محفوظتان", "STAGE-04",
                    customer_control_points=["اختيار باقة الشحن"],
                ),
                self._special_template(
                    "المتعامل يراجع الخطة قبل أن يبدأ المساعد الإجراءات الملزمة",
                    "يعرض المساعد الباقة والبيانات والمستندات وطريقة التسليم ونقطة الوزن والتسعير والدفع اللاحقة؛ يمكن الموافقة أو التعديل.",
                    "موافقة محددة على خطة واضحة.", "plan_review", ["planning", "review"],
                    "موافق أو تعديل", "نسخة خطة معتمدة", "STAGE-04",
                    customer_control_points=["الموافقة على الخطة أو تعديلها"],
                ),
                self._special_template(
                    "المساعد يجهز ملف الشحنة ويحجز الاستلام",
                    "ينشئ الشحنة مبدئيًا، يجهز الإفصاح والجمارك والملصق، ويحجز مندوب EMX أو نقطة التسليم المناسبة قبل طلب أي دفع.",
                    "إنهاء العمل الرقمي قبل النقطة المادية.", "shipment_preparation", ["execution"],
                    "لا يوجد عمل إداري", "مرجع حجز وملف شحنة جاهز", "STAGE-05",
                ),
                self._special_template(
                    "مندوب EMX يستلم الشحنة ويؤكد الوزن والأبعاد والسعر النهائي",
                    "تُسلّم الشحنة فعليًا للمندوب أو الفرع؛ تتحقق EMX من الوزن والأبعاد والمحتوى وتعيد عرض السعر النهائي المعتمد إلى الرحلة.",
                    "السعر لا يصبح ملزمًا قبل الفحص المادي.", "physical_quote", ["human", "execution"],
                    "تسليم الشحنة فقط للمندوب", "وزن وأبعاد وعرض سعر معتمد من EMX", "STAGE-06", "HUMAN",
                    ["تسليم الشحنة للمندوب"],
                ),
                self._special_template(
                    "المتعامل يدفع بعد التسعير والمساعد يفعّل الشحنة ويتابعها",
                    "يعرض المساعد السعر والجهة المستفيدة؛ يعتمد المتعامل الدفع، ثم يفعّل المساعد الملصق ورقم التتبع ويراقب الشحنة حتى التسليم وإثباته.",
                    "ربط الدفع بالسعر المعتمد ثم إكمال النتيجة.", "customer_outcome", ["payment", "result"],
                    "اعتماد السعر والدفع فقط", "مرجع دفع ورقم تتبع وإثبات تسليم", "STAGE-07",
                    customer_control_points=["اعتماد السعر النهائي وإتمام الدفع"],
                ),
            ]
        return [
            self._special_template("Assistant identifies the international-shipping outcome", "Identify destination, shipment type and permitted company context.", "Start from the outcome.", "intent_context", ["initiation"], "Describe the outcome", "Recorded shipping request", "STD-01"),
            self._special_template("Assistant retrieves party data and customs documents", "Retrieve and verify sender, recipient, invoice and customs data from connected sources.", "Remove repeated entry and uploads.", "data_completion", ["data"], "No repeated entry", "Verified data and documents", "STAGE-03"),
            self._special_template("Assistant compares shipping packages and recommends one", "Compare Standard, Express and Premium by speed and fit without inventing a pre-weighing price.", "Separate service level from the final quote.", "package_selection", ["package"], "Select or change the package", "Selected package and expected window", "STAGE-04", customer_control_points=["Select shipping package"]),
            self._special_template("Customer reviews the plan before binding preparation", "Show package, data, documents, handoff, weighing, quote and later payment checkpoints for approval or edit.", "Use specific informed consent.", "plan_review", ["planning", "review"], "Approve or edit", "Approved plan version", "STAGE-04", customer_control_points=["Approve or edit the plan"]),
            self._special_template("Assistant prepares the shipment file and books pickup", "Create the provisional shipment, prepare declaration, customs file and label, and book EMX pickup before payment.", "Complete digital work before the physical checkpoint.", "shipment_preparation", ["execution"], "No administrative work", "Booking reference and ready shipment file"),
            self._special_template("EMX receives the item and confirms weight, dimensions and quote", "At pickup or branch handoff, EMX verifies the physical item and returns the approved final quote.", "A binding price requires physical verification.", "physical_quote", ["human", "execution"], "Hand the parcel to the courier", "EMX-verified measurement and quote", "STAGE-06", "HUMAN", ["Hand parcel to courier"]),
            self._special_template("Customer pays the quote; assistant activates and tracks delivery", "Show the verified quote for payment, then activate the label and tracking number and monitor through proof of delivery.", "Complete payment and outcome in one traceable journey.", "customer_outcome", ["payment", "result"], "Approve the amount and pay", "Payment, tracking and proof-of-delivery references", "STAGE-07", customer_control_points=["Approve final quote and pay"]),
        ]

    def _postal_license_templates(self, is_arabic):
        if is_arabic:
            rows = [
                ("المساعد يفهم الأنشطة البريدية المطلوب ترخيصها", "يحدد الأنشطة ونطاق الترخيص من طلب الشركة وسياقها المصرح به.", "تحديد النتيجة بدقة.", "intent_context", ["initiation"], "اختيار الأنشطة المطلوب ترخيصها", "نطاق الترخيص المسجل", "STD-01", "SYSTEM"),
                ("المساعد يسترجع بيانات الشركة والوثائق ويتحقق منها", "يسترجع الرخصة التجارية وعقد التأسيس والهوية والجواز وعقد الإيجار والموافقات من المصادر المتصلة، ويطلب الاستثناء فقط.", "إلغاء الرفع والإدخال المتكرر.", "data_completion", ["data"], "لا يعيد تقديم بيانات متاحة", "ملف مستندات موثق", "STAGE-03", "SYSTEM"),
                ("المساعد يعبئ طلب الترخيص ويعرضه للموافقة", "يجهز نموذج الطلب والأنشطة والوثائق ويعرض نسخة قابلة للتعديل قبل الإرسال.", "موافقة واعية قبل الإجراء الملزم.", "plan_review", ["planning", "review"], "موافق أو تعديل", "طلب معتمد للإرسال", "STAGE-04", "SYSTEM"),
                ("المساعد يقدم الطلب ويتابع مراجعة بريد الإمارات", "يرسل الطلب ويتابع حالته ويستكمل أي نقص من المصادر المصرح بها، مع تصعيد الاستثناء فقط للموظف.", "إزالة المتابعة اليدوية.", "execution", ["execution"], "لا توجد متابعة يدوية", "مرجع الطلب وسجل المتابعة", "STAGE-05", "SYSTEM"),
                ("بريد الإمارات يعتمد الطلب ويحدد وعاء الرسوم السنوي", "بعد اكتمال المتطلبات يعتمد الموظف المخول الطلب، ويؤكد النظام إجمالي مبيعات الأنشطة البريدية المستخدم للحساب.", "الحفاظ على الاعتماد البشري والوعاء المالي الموثق.", "human_control", ["human"], "لا يعيد شرح الطلب", "موافقة ووعاء رسوم معتمدان", "STAGE-06", "HUMAN"),
                ("النظام يحسب 10% سنويًا بحد أدنى 100,000 درهم والمتعامل يحوّل المبلغ", "يحسب المبلغ الأكبر بين 10% من إجمالي مبيعات الأنشطة البريدية و100,000 درهم، ويعرضه قبل تحويل بنكي تجريبي ثم يرفق المساعد الإيصال.", "تطبيق قاعدة الرسوم الصحيحة دون تحويل الحد الأدنى إلى سعر ثابت.", "payment", ["payment"], "اعتماد التحويل البنكي", "مرجع التحويل وإيصال الدفع", "STAGE-07", "SYSTEM"),
                ("المساعد يستلم الرخصة ويكمل التفعيل النهائي", "ينزل الرخصة البريدية، ينسق إضافة الأنشطة إلى الرخصة التجارية، يرفع النسخة المحدثة ويتابع تأكيد التفعيل النهائي.", "تسليم نتيجة مكتملة لا مجرد موافقة أولية.", "customer_outcome", ["result"], "استلام الرخصة والتأكيد", "الرخصة والتفعيل النهائي", "STAGE-08", "SYSTEM"),
            ]
        else:
            rows = [
                ("Assistant identifies the postal activities to license", "Determine licensed activities and scope from authorized company context.", "Define the outcome precisely.", "intent_context", ["initiation"], "Select activities", "Recorded licence scope", "STD-01", "SYSTEM"),
                ("Assistant retrieves and verifies company documents", "Retrieve the trade licence, memorandum, identity, passport, tenancy and approvals from connected sources.", "Remove repeated uploads and entry.", "data_completion", ["data"], "No repeated submission", "Verified document file", "STAGE-03", "SYSTEM"),
                ("Assistant prepares the editable licence application", "Populate the application, activities and documents and show it for approval or edit.", "Use informed consent.", "plan_review", ["planning", "review"], "Approve or edit", "Approved application", "STAGE-04", "SYSTEM"),
                ("Assistant submits and follows Emirates Post review", "Submit, monitor status and resolve missing data through authorized sources, escalating only exceptions.", "Remove manual follow-up.", "execution", ["execution"], "No manual follow-up", "Application reference and log", "STAGE-05", "SYSTEM"),
                ("Emirates Post approves and confirms the annual fee base", "The authorized officer approves the completed application and the system confirms postal-activity sales used for assessment.", "Preserve human approval and an authoritative fee base.", "human_control", ["human"], "No repeated explanation", "Approved application and fee base", "STAGE-06", "HUMAN"),
                ("System calculates 10% annually with an AED 100,000 minimum", "Charge the greater of 10% of annual postal-activity sales or AED 100,000, show it for authorization, then attach the bank-transfer receipt.", "Apply the percentage rule without treating the minimum as a flat price.", "payment", ["payment"], "Authorize bank transfer", "Transfer and receipt references", "STAGE-07", "SYSTEM"),
                ("Assistant obtains the licence and completes final activation", "Download the postal licence, coordinate the commercial-licence activity update, upload the updated copy and follow final activation.", "Deliver the complete outcome.", "customer_outcome", ["result"], "Receive licence and confirmation", "Licence and activation confirmation", "STAGE-08", "SYSTEM"),
            ]
        return [
            self._special_template(
                name, action, reason, semantic, components, role, evidence,
                standard, step_type,
                [role] if semantic in {"plan_review", "payment"} else [],
            )
            for name, action, reason, semantic, components, role, evidence, standard, step_type in rows
        ]

    def _template(self, key, is_arabic, profile=None):
        profile = profile or {}
        if is_arabic:
            values = {
                "intent": {
                    "name": "المساعد يفهم النتيجة المطلوبة وسياق المتعامل",
                    "action": "يستقبل الطلب باللغة الطبيعية ويحدد الخدمة والمقصود بالسياق المصرح به، ويسأل سؤالًا واحدًا فقط عند الضرورة.",
                    "reason": "بدء الرحلة من النتيجة بدل البحث عن الإجراء.",
                    "standard_id": "STD-01",
                    "related_standard_ids": ["STAGE-01", "STAGE-02", "STD-03"],
                    "semantic_category": "intent_context",
                    "component_categories": ["initiation"],
                    "type": "SYSTEM",
                    "customer_control_points": ["طلب النتيجة باللغة الطبيعية"],
                    "customer_role": "وصف النتيجة المطلوبة باللغة الطبيعية",
                    "visible_before_payment": True,
                    "completion_evidence": "النتيجة المطلوبة وسياق الطلب المسجل",
                },
                "data": {
                    "name": "المساعد يسترجع البيانات والمستندات ويتحقق منها",
                    "action": "يستخدم المصادر المصرح بها ويطبق الطلب مرة واحدة، ويطلب فقط المعلومة غير المتوفرة مع توضيح السبب.",
                    "reason": "إزالة الإدخال والرفع والتكرار من المتعامل.",
                    "standard_id": "STAGE-03",
                    "related_standard_ids": ["STD-02"],
                    "semantic_category": "data_completion",
                    "component_categories": ["data"],
                    "type": "SYSTEM",
                    "customer_role": "لا يرفع أو يعيد إدخال بيانات معروفة حكوميًا",
                    "visible_before_payment": True,
                    "completion_evidence": "مصدر كل بيان وحالة التحقق منه",
                },
                "package": {
                    "name": "المساعد يقارن الباقات والمتعامل يختار أو يغيّر الباقة",
                    "action": "يحلل احتياج المتعامل وبيانات الخدمة ويقارن مزايا وأسعار الباقات، ثم يوصي بالأنسب. يختار المتعامل الباقة المقترحة أو يغيرها فقط، دون طلب البيانات مجددًا.",
                    "reason": "الإبقاء على اختيار الباقة كقرار للمتعامل مع نقل البحث والمقارنة للمساعد.",
                    "standard_id": "STAGE-04",
                    "related_standard_ids": ["STD-04"],
                    "semantic_category": "package_selection",
                    "component_categories": ["package"],
                    "type": "SYSTEM",
                    "customer_control_points": ["اختيار الباقة المقترحة أو تغييرها"],
                    "customer_role": "اختيار الباقة أو تعديلها",
                    "visible_before_payment": True,
                    "completion_evidence": "الباقة المختارة وسبب التوصية محفوظان في الخطة",
                },
                "review": {
                    "name": "المساعد يعرض خطة التنفيذ كاملة قبل الدفع",
                    "action": "يحدد المسار والبيانات والأنظمة والإجراءات والرسوم والنتيجة المتوقعة، ويعرضها للمتعامل قبل الدفع. يستطيع المتعامل الموافقة أو تعديل أي اختيار ثم يعيد المساعد احتساب الخطة.",
                    "reason": "الموافقة تكون على خطة مفهومة وقابلة للتعديل، لا على صلاحية عامة مفتوحة.",
                    "standard_id": "STAGE-04",
                    "related_standard_ids": ["STD-04", "STAGE-05"],
                    "semantic_category": "plan_review",
                    "component_categories": ["planning", "review"],
                    "type": "SYSTEM",
                    "customer_control_points": ["الموافقة على الخطة أو طلب تعديلها"],
                    "customer_role": "موافق أو تعديل",
                    "visible_before_payment": True,
                    "completion_evidence": "نسخة الخطة التي وافق عليها المتعامل وسجل أي تعديل",
                },
                "payment": {
                    "name": "المساعد يجهز الدفع والمتعامل يعتمد المبلغ ويدفع",
                    "action": "يعرض البنود والمبلغ الإجمالي والجهة المستفيدة بعد اعتماد الخطة. يختار المتعامل وسيلة الدفع ويعتمد العملية، بينما يتولى المساعد تأكيد النتيجة ومتابعة أي فشل أو خصم غير مكتمل.",
                    "reason": "يبقى اعتماد الدفع بيد المتعامل، وتختفي الزيارة أو المتابعة المنفصلة.",
                    "standard_id": "STAGE-07",
                    "related_standard_ids": ["STD-04"],
                    "semantic_category": "payment",
                    "component_categories": ["payment"],
                    "type": "SYSTEM",
                    "customer_control_points": ["اعتماد المبلغ وإتمام الدفع"],
                    "customer_role": "مراجعة المبلغ والدفع",
                    "visible_before_payment": True,
                    "completion_evidence": "مرجع الدفع وحالة العملية",
                },
                "execution": {
                    "name": "المساعد ينفذ الخدمة ويتحقق ويحفظ حالة الطلب",
                    "action": "ينفذ الإجراءات عبر الأنظمة، يتحقق من نتيجة كل إجراء، يحفظ الحالة ويراقب الاعتماديات حتى الاكتمال.",
                    "reason": "نقل التنفيذ والمتابعة والاستمرارية من المتعامل للمساعد.",
                    "standard_id": "STAGE-05",
                    "related_standard_ids": ["STD-05"],
                    "semantic_category": "execution_continuity",
                    "component_categories": ["execution"],
                    "type": "SYSTEM",
                    "customer_role": "لا يوجد؛ يمكنه الإيقاف أو طلب موظف عند الحاجة",
                    "visible_before_payment": True,
                    "completion_evidence": "سجل الإجراءات ونتيجة التحقق من كل إجراء",
                },
                "human": {
                    "name": "الموظف المخول ينفذ القرار البشري الضروري بكامل السياق",
                    "action": "تصل للموظف الحالة والبيانات والموافقات وسجل الإجراءات، وينفذ فقط الحكم أو الاعتماد الذي لا يجوز أتمتته.",
                    "reason": "الحفاظ على الإشراف والمساءلة البشرية دون إعادة العمل للمتعامل.",
                    "standard_id": "STAGE-04",
                    "related_standard_ids": ["STAGE-06"],
                    "semantic_category": "human_control",
                    "component_categories": ["human"],
                    "type": "HUMAN",
                    "customer_role": "لا يعيد شرح الحالة أو تقديم البيانات",
                    "visible_before_payment": True,
                    "completion_evidence": "قرار الموظف المخول مضاف إلى سجل الحالة",
                },
                "result": {
                    "name": "المساعد يسلم النتيجة ويتيح التصحيح والاعتراض",
                    "action": "يقدم النتيجة ووقت السريان ومكان الوثيقة، ويتيح الاستفسار أو التصحيح أو الاعتراض أو طلب موظف من المكان نفسه.",
                    "reason": "إكمال الرحلة حتى النتيجة وما بعدها دون متابعة يدوية.",
                    "standard_id": "STAGE-08",
                    "related_standard_ids": ["STD-05", "READY-01"],
                    "semantic_category": "customer_outcome",
                    "component_categories": ["result"],
                    "type": "SYSTEM",
                    "customer_role": "استلام النتيجة أو طلب تصحيح أو اعتراض",
                    "visible_before_payment": True,
                    "completion_evidence": "الوثيقة أو التأكيد ووقت السريان ومسار الاعتراض",
                },
            }
        else:
            values = {
                "intent": {
                    "name": "Assistant understands the outcome and customer context",
                    "action": "Receive the natural-language outcome request, identify the service using permitted context and ask one targeted clarification only when necessary.",
                    "reason": "Starts from the outcome instead of making the customer find the procedure.",
                    "standard_id": "STD-01",
                    "related_standard_ids": ["STAGE-01", "STAGE-02", "STD-03"],
                    "semantic_category": "intent_context",
                    "component_categories": ["initiation"],
                    "type": "SYSTEM",
                    "customer_control_points": ["Natural-language outcome request"],
                    "customer_role": "Describe the desired outcome in natural language",
                    "visible_before_payment": True,
                    "completion_evidence": "Recorded outcome and request context",
                },
                "data": {
                    "name": "Assistant retrieves and verifies data and documents",
                    "action": "Use authorized sources, apply ask-once and request only genuinely unavailable information with its reason.",
                    "reason": "Removes entry, upload and repetition from the customer.",
                    "standard_id": "STAGE-03",
                    "related_standard_ids": ["STD-02"],
                    "semantic_category": "data_completion",
                    "component_categories": ["data"],
                    "type": "SYSTEM",
                    "customer_role": "No upload or re-entry of data already known to government",
                    "visible_before_payment": True,
                    "completion_evidence": "Source and verification status for every data item",
                },
                "package": {
                    "name": "Assistant compares packages; customer selects or changes the package",
                    "action": "Analyze the customer's need and service context, compare package benefits and prices, and recommend the best fit. The customer only selects the recommendation or changes it without re-entering data.",
                    "reason": "Keeps the package decision with the customer while shifting research and comparison to the assistant.",
                    "standard_id": "STAGE-04",
                    "related_standard_ids": ["STD-04"],
                    "semantic_category": "package_selection",
                    "component_categories": ["package"],
                    "type": "SYSTEM",
                    "customer_control_points": ["Select or change the recommended package"],
                    "customer_role": "Select or change the package",
                    "visible_before_payment": True,
                    "completion_evidence": "Selected package and recommendation rationale saved in the plan",
                },
                "review": {
                    "name": "Assistant shows the complete execution plan before payment",
                    "action": "Determine the path, data, systems, actions, fees and expected outcome, then show them before payment. The customer can approve or edit any option and the assistant recalculates the plan.",
                    "reason": "Consent applies to an understandable, editable plan rather than an open-ended permission.",
                    "standard_id": "STAGE-04",
                    "related_standard_ids": ["STD-04", "STAGE-05"],
                    "semantic_category": "plan_review",
                    "component_categories": ["planning", "review"],
                    "type": "SYSTEM",
                    "customer_control_points": ["Approve the plan or request an edit"],
                    "customer_role": "Approve or edit",
                    "visible_before_payment": True,
                    "completion_evidence": "Approved plan version and edit history",
                },
                "payment": {
                    "name": "Assistant prepares payment; customer approves the amount and pays",
                    "action": "Show fee items, total and beneficiary after plan approval. The customer selects a payment method and authorizes the transaction; the assistant verifies the result and follows up on failure or incomplete debit.",
                    "reason": "Keeps payment authorization with the customer while removing visits and separate follow-up.",
                    "standard_id": "STAGE-07",
                    "related_standard_ids": ["STD-04"],
                    "semantic_category": "payment",
                    "component_categories": ["payment"],
                    "type": "SYSTEM",
                    "customer_control_points": ["Approve the amount and complete payment"],
                    "customer_role": "Review the amount and pay",
                    "visible_before_payment": True,
                    "completion_evidence": "Payment reference and transaction status",
                },
                "execution": {
                    "name": "Assistant executes, verifies and preserves request state",
                    "action": "Execute through service systems, verify every action, preserve state and monitor dependencies until completion.",
                    "reason": "Shifts execution, follow-up and continuity to the assistant.",
                    "standard_id": "STAGE-05",
                    "related_standard_ids": ["STD-05"],
                    "semantic_category": "execution_continuity",
                    "component_categories": ["execution"],
                    "type": "SYSTEM",
                    "customer_role": "None; the customer can pause or request human help",
                    "visible_before_payment": True,
                    "completion_evidence": "Action log and verification result for every action",
                },
                "human": {
                    "name": "Authorized employee performs the necessary human judgement with full context",
                    "action": "Receive the case, data, consent and action log, and perform only the judgement or approval that cannot be automated.",
                    "reason": "Preserves human oversight without returning work to the customer.",
                    "standard_id": "STAGE-04",
                    "related_standard_ids": ["STAGE-06"],
                    "semantic_category": "human_control",
                    "component_categories": ["human"],
                    "type": "HUMAN",
                    "customer_role": "No need to repeat the case or resubmit data",
                    "visible_before_payment": True,
                    "completion_evidence": "Authorized decision recorded in the case log",
                },
                "result": {
                    "name": "Assistant delivers the result and enables correction or objection",
                    "action": "Provide the result, effective date and document location, with question, correction, objection and human-help paths in the same place.",
                    "reason": "Completes the journey through the outcome and what follows it.",
                    "standard_id": "STAGE-08",
                    "related_standard_ids": ["STD-05", "READY-01"],
                    "semantic_category": "customer_outcome",
                    "component_categories": ["result"],
                    "type": "SYSTEM",
                    "customer_role": "Receive the outcome or request correction or objection",
                    "visible_before_payment": True,
                    "completion_evidence": "Document or confirmation, effective date and objection path",
                },
            }
        if key == "review" and not profile.get("has_payment_stage"):
            is_case = profile.get("service_archetype") in {
                "COMPLAINT",
                "DISPUTE_REFUND",
            }
            if is_arabic:
                values["review"].update({
                    "name": (
                        "المساعد يعرض ملف الحالة وخطة المتابعة قبل الإرسال"
                        if is_case
                        else "المساعد يعرض خطة التنفيذ قبل الإجراء الملزم"
                    ),
                    "action": (
                        "يعرض تصنيف الحالة والبيانات والأدلة والجهة المختصة "
                        "والمدة ومسار التصعيد والنتيجة المطلوبة. يستطيع المتعامل "
                        "الموافقة على الإرسال أو طلب تعديل، ولا تظهر خطوة دفع."
                        if is_case
                        else "يحدد المسار والبيانات والأنظمة والإجراءات والنتيجة "
                        "المتوقعة، ويعرضها قبل الإجراء الملزم. يستطيع المتعامل "
                        "الموافقة أو تعديل أي اختيار، ولا يفترض وجود رسوم."
                    ),
                    "completion_evidence": (
                        "نسخة الحالة التي وافق المتعامل على إرسالها وسجل التعديل"
                        if is_case
                        else "نسخة خطة الإجراء المعتمدة وسجل أي تعديل"
                    ),
                })
            else:
                values["review"].update({
                    "name": (
                        "Assistant shows the case and follow-up plan before submission"
                        if is_case
                        else "Assistant shows the execution plan before a binding action"
                    ),
                    "action": (
                        "Show case classification, data, evidence, responsible team, "
                        "SLA, escalation path and requested outcome. The customer can "
                        "approve submission or request an edit; no payment is shown."
                        if is_case
                        else "Determine the path, data, systems, actions and expected "
                        "outcome, then show them before a binding action. The customer "
                        "can approve or edit; no unconfirmed fee is assumed."
                    ),
                    "completion_evidence": (
                        "Approved case submission and edit history"
                        if is_case
                        else "Approved action plan and edit history"
                    ),
                })
        return values[key]

    def _maximum_target_steps(self, current_count):
        if current_count <= 1:
            return 1
        return min(7, current_count - 1)

    def _compress_to_limit(self, templates, limit, is_arabic):
        result = [dict(item) for item in templates]
        priorities = [
            ("initiation", "data"),
            ("initiation", "package"),
            ("package", "data"),
            ("data", "planning"),
            ("execution", "human"),
            ("human", "result"),
            ("planning", "payment"),
            ("payment", "execution"),
        ]
        while len(result) > limit:
            pair_index = None
            for left_category, right_category in priorities:
                for index in range(len(result) - 1):
                    left = result[index].get("component_categories", [])
                    right = result[index + 1].get("component_categories", [])
                    if left_category in left and right_category in right:
                        pair_index = index
                        break
                if pair_index is not None:
                    break
            if pair_index is None:
                pair_index = 0
            combined = self._combine(
                [result[pair_index], result[pair_index + 1]],
                is_arabic,
            )
            result[pair_index:pair_index + 2] = [combined]
        return result

    def _combine(self, templates, is_arabic):
        separator = "؛ " if is_arabic else "; "
        components = list(dict.fromkeys(
            category
            for item in templates
            for category in item.get("component_categories", [])
        ))
        standards = list(dict.fromkeys(
            standard
            for item in templates
            for standard in [item["standard_id"]] + item.get("related_standard_ids", [])
        ))
        return {
            "name": separator.join(item["name"] for item in templates),
            "action": " ".join(item["action"] for item in templates),
            "reason": separator.join(item["reason"] for item in templates),
            "standard_id": templates[-1]["standard_id"],
            "related_standard_ids": standards,
            "semantic_category": (
                "customer_outcome"
                if "result" in components
                else templates[-1]["semantic_category"]
            ),
            "component_categories": components,
            "type": (
                "HUMAN"
                if any(item.get("type") == "HUMAN" for item in templates)
                else "SYSTEM"
            ),
            "customer_control_points": [
                point
                for item in templates
                for point in item.get("customer_control_points", [])
            ],
            "customer_role": separator.join(
                item.get("customer_role", "")
                for item in templates
                if item.get("customer_role")
            ),
            "visible_before_payment": all(
                item.get("visible_before_payment", True)
                for item in templates
            ),
            "completion_evidence": separator.join(
                item.get("completion_evidence", "")
                for item in templates
                if item.get("completion_evidence")
            ),
        }

    def _find_stage_index(self, category, templates):
        for index, template in enumerate(templates):
            if category in template.get("component_categories", []):
                return index
        fallbacks = {
            "initiation": 0,
            "data": 0,
            "package": 0,
            "planning": self._index_for_component(
                templates,
                "review",
                0,
            ),
            "review": self._index_for_component(
                templates,
                "review",
                0,
            ),
            "payment": max(0, len(templates) - 2),
            "execution": max(0, len(templates) - 2),
            "human": max(0, len(templates) - 2),
            "result": len(templates) - 1,
        }
        return fallbacks.get(category, max(0, len(templates) - 2))

    def _index_for_component(self, templates, category, default):
        for index, template in enumerate(templates):
            if category in template.get("component_categories", []):
                return index
        return default

    def _classify_source_step(self, step):
        text = str(step).lower()
        if self._contains(text, [
            "receives", "receive", "issued", "issue the", "result", "outcome",
            "confirmation", "notify", "close the case", "يستلم", "يتسلم",
            "يصدر", "إصدار", "اصدار", "النتيجة", "النتيجه", "إشعار",
            "اشعار", "تأكيد", "إغلاق", "اغلاق",
        ]):
            return "result"
        if self._contains(text, [
            "committee", "notary", "field inspection", "supervisor approves",
            "كاتب العدل", "لجنة", "لجنه", "تفتيش ميداني", "المشرف يعتمد",
            "المدير يعتمد",
        ]):
            return "human"
        if self._contains_payment(text):
            return "payment"
        if self._contains(text, [
            "package", "bundle", "tier", "subscription package",
            "باقة", "باقه", "الحزمة", "الحزمه",
        ]):
            return "package"
        if self._contains(text, [
            "approve the plan", "confirm the request", "edit the plan",
            "review the request", "consent", "الموافقة على الخطة",
            "الموافقه على الخطه", "يؤكد الطلب", "تأكيد الطلب",
            "مراجعة الطلب", "يراجع الطلب", "تعديل الخطة", "يوافق",
        ]):
            return "review"
        if self._contains(text, [
            "choose", "select", "package", "plan", "duration", "term",
            "subscription", "legal form", "business activity", "auto-renew",
            "يختار", "يحدد", "باقة", "باقه", "مدة", "مده", "عقد",
            "اشتراك", "الشكل القانوني", "نوع النشاط", "التجديد التلقائي",
        ]):
            return "planning"
        if self._contains(text, [
            "customer requests", "customer contacts", "applies for", "asks for",
            "starts the service", "العميل يطلب", "المتعامل يطلب",
            "مقدم الطلب يطلب", "يتقدم بطلب", "يتواصل", "يبدأ الخدمة",
        ]):
            return "initiation"
        if self._contains(text, [
            "upload", "provide", "enter", "form", "document", "data", "verify",
            "review", "check", "search", "identity", "يرفع", "يقدم", "يدخل",
            "يعبئ", "يملا", "يرفق", "مستند", "وثيق", "بيانات", "يراجع",
            "يتحقق", "يتاكد", "يتأكد", "يبحث", "الهويه", "الهوية",
        ]):
            return "data"
        return "execution"

    def _build_agent_explanation(
        self,
        future_steps,
        ownership_transfers,
        profile,
        is_arabic,
    ):
        customer_actions = []
        if profile["has_package_stage"]:
            customer_actions.append({
                "code": "PACKAGE_SELECTION",
                "label": (
                    "اختيار الباقة المقترحة أو تغييرها"
                    if is_arabic
                    else "Select or change the recommended package"
                ),
                "assistant_support": (
                    "المساعد يقارن السعر والمزايا والملاءمة ويشرح سبب التوصية."
                    if is_arabic
                    else "The assistant compares price, benefits and fit and explains the recommendation."
                ),
                "standard_id": "STAGE-04",
            })
        is_case = profile["service_archetype"] in {
            "COMPLAINT",
            "DISPUTE_REFUND",
        }
        if is_arabic:
            approval_label = (
                "مراجعة الحالة والموافقة على إرسالها أو تعديلها"
                if is_case
                else "مراجعة الخطة واختيار موافق أو تعديل"
            )
            approval_support = (
                "يعرض المساعد كل إجراء وبيان ودليل ومسار متابعة قبل الإرسال."
                if is_case
                else "يعرض المساعد كل ما سينفذه والبيانات والرسوم قبل أي التزام."
                if profile["has_payment_stage"]
                else "يعرض المساعد كل إجراء وبيان ونتيجة متوقعة قبل أي التزام."
            )
        else:
            approval_label = (
                "Review the case and approve submission or edit it"
                if is_case
                else "Review the plan and choose Approve or Edit"
            )
            approval_support = (
                "The assistant shows every action, data item, evidence and follow-up path before submission."
                if is_case
                else "The assistant shows every action, data item and fee before commitment."
                if profile["has_payment_stage"]
                else "The assistant shows every action, data item and expected outcome before commitment."
            )
        customer_actions.append({
            "code": "PLAN_APPROVAL_OR_EDIT",
            "label": approval_label,
            "assistant_support": approval_support,
            "standard_id": "STD-04",
        })
        if profile.get("service_kind") == "INTERNATIONAL_SHIPMENT":
            customer_actions.append({
                "code": "PHYSICAL_HANDOFF",
                "label": (
                    "تسليم الشحنة للمندوب ليؤكد الوزن والأبعاد"
                    if is_arabic
                    else "Hand the parcel to the courier for weight and dimension verification"
                ),
                "assistant_support": (
                    "المساعد يكون قد جهز الحجز والبيانات والجمارك والملصق قبل الاستلام."
                    if is_arabic
                    else "The assistant has already prepared the booking, data, customs file and label before pickup."
                ),
                "standard_id": "STAGE-06",
            })
        if profile["has_payment_stage"]:
            customer_actions.append({
                "code": "PAYMENT",
                "label": (
                    "اعتماد المبلغ وإتمام الدفع"
                    if is_arabic
                    else "Approve the amount and complete payment"
                ),
                "assistant_support": (
                    "المساعد يجهز العملية ويتحقق منها ويتابع الفشل أو الخصم غير المكتمل."
                    if is_arabic
                    else "The assistant prepares and verifies the transaction and follows up on failure or incomplete debit."
                ),
                "standard_id": "STAGE-07",
            })

        execution_plan = [
            {
                "phase_number": step["step_number"],
                "title": step["name"],
                "assistant_does": step["assistant_action"],
                "customer_role": step["customer_role"],
                "current_steps_replaced": step.get("source_steps", []),
                "completion_evidence": step["completion_evidence"],
                "visible_before_payment": step["visible_before_payment"],
                "owner": step["owner"],
                "standard_id": step["standard_id"],
            }
            for step in future_steps
        ]

        if profile.get("service_kind") == "INTERNATIONAL_SHIPMENT":
            summary = (
                "المساعد ينهي تجهيز البيانات والجمارك والحجز والملصق أولًا. "
                "بعد استلام المندوب للشحنة وقياسها ترسل EMX السعر النهائي؛ "
                "عندها فقط يعتمد المتعامل المبلغ ويدفع، ثم يفعّل المساعد "
                "الشحنة ويتابعها حتى التسليم."
                if is_arabic
                else "The assistant completes data, customs, booking and label "
                "preparation first. After courier pickup and measurement, EMX "
                "returns the final quote; only then does the customer pay and the "
                "assistant activate and track the shipment."
            )
            preview_title = (
                "الخطة قبل تجهيز الشحنة والاستلام والوزن"
                if is_arabic
                else "Plan before shipment preparation, pickup and weighing"
            )
            preview_description = (
                "تظهر الباقة والبيانات وكل ما سيجهزه المساعد، مع توضيح أن السعر "
                "غير نهائي حتى تستلم EMX الشحنة وتؤكد الوزن والأبعاد."
                if is_arabic
                else "The package, data and assistant preparation are shown, with "
                "the price explicitly pending until EMX receives and measures the item."
            )
        elif profile.get("service_kind") == "POSTAL_ACTIVITY_LICENSE":
            summary = (
                "المساعد يسترجع الوثائق ويقدم الطلب ويتابع الموافقة. بعد الاعتماد "
                "يطبق قاعدة الرسوم السنوية: 10% من إجمالي مبيعات الأنشطة البريدية "
                "وبحد أدنى 100,000 درهم مقدمًا، ثم يعتمد المتعامل التحويل البنكي."
                if is_arabic
                else "The assistant retrieves documents, submits the application "
                "and follows approval. It then applies the annual fee rule—10% of "
                "postal-activity sales with AED 100,000 upfront as the minimum—before "
                "the customer authorizes the bank transfer."
            )
            preview_title = (
                "خطة الترخيص وقاعدة الرسوم قبل الإرسال"
                if is_arabic
                else "Licence plan and fee rule before submission"
            )
            preview_description = (
                "تظهر الإجراءات والمستندات وطريقة حساب الرسوم والتحويل البنكي، "
                "مع عدم عرض 100,000 درهم كسعر ثابت بل كحد أدنى سنوي."
                if is_arabic
                else "Actions, documents, fee calculation and bank-transfer method "
                "are shown; AED 100,000 is presented as an annual minimum, not a flat price."
            )
        elif profile["has_payment_stage"]:
            summary = (
                "المساعد ينقل إليه كل العمل الإداري. المتعامل لا يبحث أو يدخل "
                "بيانات أو يرفع مستندات أو يتابع الطلب؛ يختار الباقة عند وجودها، "
                "يراجع الخطة فيوافق أو يعدل، ثم يعتمد الدفع."
                if is_arabic
                else "The assistant takes over all administrative work. The "
                "customer does not search, enter data, upload documents or follow "
                "up; they select a package when applicable, approve or edit the "
                "plan, then authorize payment."
            )
            preview_title = (
                "الخطة الظاهرة للمتعامل قبل الدفع"
                if is_arabic
                else "Plan shown to the customer before payment"
            )
            preview_description = (
                "تظهر الباقة والبيانات المستخدمة وكل إجراء سينفذه المساعد "
                "والرسوم والنتيجة المتوقعة. يمكن اختيار «موافق» أو «تعديل»، "
                "ولا يبدأ الدفع قبل اعتماد النسخة النهائية."
                if is_arabic
                else "The package, used data, every assistant action, fees and "
                "expected outcome are shown. The customer can choose Approve or "
                "Edit, and payment cannot start before final approval."
            )
        elif is_case:
            summary = (
                "المساعد يبني ملف الحالة ويتولى الإرسال والمتابعة والتصعيد. "
                "المتعامل يشرح النتيجة المطلوبة ثم يوافق على الصياغة النهائية "
                "أو يعدلها؛ لا توجد خطوة دفع."
                if is_arabic
                else "The assistant builds the case and handles submission, "
                "follow-up and escalation. The customer describes the outcome and "
                "approves or edits the final case; there is no payment step."
            )
            preview_title = (
                "ملف الحالة الظاهر قبل الإرسال"
                if is_arabic
                else "Case shown before submission"
            )
            preview_description = (
                "تظهر البيانات والأدلة وتصنيف الحالة والجهة المختصة والمدة "
                "ومسار التصعيد والنتيجة المطلوبة. يختار المتعامل «موافق على "
                "الإرسال» أو «تعديل»."
                if is_arabic
                else "The data, evidence, case classification, responsible team, "
                "SLA, escalation path and requested outcome are shown. The customer "
                "chooses Approve submission or Edit."
            )
        else:
            summary = (
                "المساعد يتولى البحث والإدخال والتحقق والتنفيذ والمتابعة. يراجع "
                "المتعامل خطة الإجراء فيوافق أو يعدلها، ولا تظهر دفعة غير مثبتة."
                if is_arabic
                else "The assistant handles search, entry, verification, execution "
                "and follow-up. The customer approves or edits the action plan, and "
                "no unconfirmed payment is shown."
            )
            preview_title = (
                "الخطة الظاهرة قبل الإجراء الملزم"
                if is_arabic
                else "Plan shown before a binding action"
            )
            preview_description = (
                "تظهر البيانات وكل إجراء سينفذه المساعد والنتيجة المتوقعة. يمكن "
                "اختيار «موافق» أو «تعديل»، وتُعرض حالة الرسوم كغير مؤكدة بدل "
                "إنشاء دفعة وهمية."
                if is_arabic
                else "The data, every assistant action and expected outcome are "
                "shown. The customer can choose Approve or Edit; an unknown fee is "
                "flagged instead of creating a fake payment."
            )

        preview = {
            "enabled": True,
            "title": preview_title,
            "description": preview_description,
            "context": (
                "PAYMENT"
                if profile["has_payment_stage"]
                else "SUBMISSION"
                if is_case
                else "ACTION"
            ),
            "options": [
                (
                    "موافق على الإرسال"
                    if is_arabic and is_case
                    else "موافق"
                    if is_arabic
                    else "Approve submission"
                    if is_case
                    else "Approve"
                ),
                "تعديل" if is_arabic else "Edit",
            ],
            "planned_actions": [
                step["name"]
                for step in future_steps
                if step["visible_before_payment"]
            ],
        }

        return {
            "title": (
                "كيف سينفذ المساعد الرحلة؟"
                if is_arabic
                else "How will the assistant execute the journey?"
            ),
            "summary": summary,
            "customer_only_actions": customer_actions,
            "pre_action_preview": preview,
            # Backward-compatible key for existing Blueprint consumers.
            "pre_payment_preview": preview,
            "execution_plan": execution_plan,
            "ownership_transfers": ownership_transfers,
        }

    def _ownership_transfer_map(
        self,
        source_steps,
        is_arabic,
        constraints=None,
        profile=None,
    ):
        constraints = constraints or {}
        profile = profile or {}
        transfers = []
        for number, step in enumerate(source_steps, start=1):
            if not self._is_customer_step(step):
                continue
            control_type = self._customer_control_type(step, profile)
            action, how = self._agent_action_for_source(
                step,
                is_arabic,
                profile,
            )
            constraint = constraints.get(number)
            if constraint and constraint.get("level") in {"AS_IS", "HUMAN"}:
                future_owner = "CUSTOMER"
                disposition = "PROTECTED_AS_IS"
                reason = (
                    "أبقى الموظف هذه الخطوة على المتعامل كقيد معتمد، ويظهر أثرها صراحة في قياس العبء."
                    if is_arabic
                    else "An approved human constraint keeps this customer step and its burden remains visible in the metrics."
                )
            elif control_type:
                future_owner = "CUSTOMER_CONTROL"
                disposition = "CONTROL_POINT"
                reason = (
                    "قرار أو موافقة تبقى بيد المتعامل، بينما يجهز المساعد كل ما يلزم حولها."
                    if is_arabic
                    else "A decision or consent stays with the customer while the assistant prepares everything around it."
                )
            else:
                future_owner = "ASSISTANT"
                disposition = "AGENT_EXECUTES"
                reason = (
                    "عمل إداري ينقل بالكامل من المتعامل إلى المساعد."
                    if is_arabic
                    else "Administrative work shifts completely from the customer to the assistant."
                )
            transfers.append({
                "source_step_number": number,
                "source_step": step,
                "current_owner": "CUSTOMER",
                "future_owner": future_owner,
                "disposition": disposition,
                "control_type": control_type,
                "assistant_action": action,
                "how": how,
                "reason": reason,
                "customer_burden": future_owner == "CUSTOMER",
                "human_constraint": constraint,
                "standard_id": (
                    "STAGE-07"
                    if control_type == "PAYMENT"
                    else "STD-04"
                    if control_type
                    else "STD-02"
                ),
            })
        return transfers

    def _customer_control_type(self, step, profile=None):
        profile = profile or {}
        text = str(step).lower()
        if (
            profile.get("has_payment_stage", True)
            and self._contains_payment(text)
            and not self._contains(text, [
            "branch", "service center", "الفرع", "مركز الخدمة", "مركز الخدمه",
            ])
        ):
            return "PAYMENT"
        if profile.get("has_package_stage", True) and self._contains(text, [
            "package", "bundle", "tier", "باقة", "باقه", "الحزمة", "الحزمه",
        ]):
            return "PACKAGE_SELECTION"
        if self._contains(text, [
            "approves", "approve", "consent", "confirm the request",
            "edit the plan", "يوافق", "موافقة", "موافقه", "يؤكد", "يؤكد الطلب",
            "تأكيد الطلب", "تعديل الخطة", "تعديل الخطه",
        ]):
            return "PLAN_APPROVAL_OR_EDIT"
        if self._contains(text, [
            "customer requests", "customer contacts", "asks for",
            "العميل يطلب", "المتعامل يطلب", "يتواصل",
        ]):
            return "OUTCOME_REQUEST"
        if self._contains(text, [
            "customer receives", "receives the result", "يستلم", "يتسلم",
        ]):
            return "OUTCOME_RECEIPT"
        return None

    def _agent_action_for_source(self, step, is_arabic, profile=None):
        profile = profile or {}
        text = str(step).lower()
        is_case = profile.get("service_archetype") in {
            "COMPLAINT",
            "DISPUTE_REFUND",
        }
        if is_case and self._contains(text, [
            "pay", "payment", "fee", "charge", "refund", "يدفع", "دفع",
            "سداد", "رسوم", "خصم", "مبلغ", "استرداد",
        ]):
            return (
                (
                    "تحليل المعاملة وبناء دليل الشكوى أو الاسترداد",
                    "يربط المساعد المعاملة بالحالة، يتحقق من المبلغ والسجل "
                    "والأدلة، ويطلب الاسترداد أو التصحيح دون إنشاء دفعة جديدة.",
                )
                if is_arabic
                else (
                    "Analyze the transaction and build dispute evidence",
                    "The assistant links the transaction to the case, verifies "
                    "amount, history and evidence, and requests correction or "
                    "refund without creating a new payment.",
                )
            )
        if is_case and self._contains(text, [
            "package", "parcel", "shipment", "شحنة", "شحنه", "طرد",
        ]):
            return (
                (
                    "ربط الشحنة بالحالة والتحقق من سجلها",
                    "يسترجع المساعد رقم الشحنة وحركتها والأحداث المرتبطة، ثم "
                    "يضيفها تلقائيًا إلى ملف الشكوى بدل مطالبة المتعامل بالبحث.",
                )
                if is_arabic
                else (
                    "Link the shipment and verify its event history",
                    "The assistant retrieves the shipment, tracking events and "
                    "related evidence and adds them to the case automatically.",
                )
            )
        cases = [
            (
                ["login", "log in", "sign in", "uae pass", "الهوية الرقمية", "يسجل الدخول", "تسجيل الدخول"],
                "بدء التحقق من الهوية والسياق",
                "يبدأ المساعد التحقق عبر الهوية الرقمية ويعيد استخدام جلسة موثقة وصلاحية محددة بدل مطالبة المتعامل بالتنقل وتسجيل الدخول من جديد.",
                "Initiate identity and context verification",
                "The assistant initiates trusted digital-identity verification and reuses a verified session and scoped permission instead of making the customer navigate and sign in again.",
            ),
            (
                ["website", "mobile app", "search for", "find the service", "موقع", "تطبيق", "يبحث عن خدمة", "يختار الخدمة"],
                "تحديد الخدمة والقناة آليًا",
                "يفهم المساعد النتيجة المطلوبة ويحدد الخدمة والجهة والمسار الصحيح دون بحث أو تنقل من المتعامل.",
                "Identify the service and channel automatically",
                "The assistant understands the desired outcome and identifies the correct service, entity and route without customer search or navigation.",
            ),
            (
                ["package", "bundle", "tier", "باقة", "باقه", "الحزمة", "الحزمه"],
                "مقارنة الباقات وتقديم توصية",
                "يقارن المساعد الأسعار والمزايا وملاءمة كل باقة، ويعرض توصية واضحة؛ المتعامل يختار التوصية أو يغيرها.",
                "Compare packages and recommend one",
                "The assistant compares price, benefits and fit and presents a clear recommendation; the customer accepts or changes it.",
            ),
            (
                ["upload", "attach", "document", "identity", "يرفع", "يرفق", "مستند", "وثيق", "الهوية الإماراتية", "الهويه الاماراتيه"],
                "استرجاع المستند والتحقق منه",
                "يسترجع المساعد المستند من مصدر حكومي مصرح به ويتحقق من الصلاحية. لا يطلبه من المتعامل إلا كاستثناء مفسر عند عدم توفره.",
                "Retrieve and verify the document",
                "The assistant retrieves the document from an authorized government source and verifies validity, requesting it only as an explained exception when unavailable.",
            ),
            (
                ["enter", "fill", "form", "provide", "submit", "data", "يدخل", "يعبئ", "يملا", "يقدم", "بيانات"],
                "استكمال البيانات وتعبئة الطلب",
                "يجمع المساعد البيانات المصرح بها من السياق الحكومي، يتحقق منها ويعبئ الطلب آليًا مع تطبيق «الطلب مرة واحدة».",
                "Complete data and populate the request",
                "The assistant gathers authorized government context, verifies it and populates the request while applying ask-once.",
            ),
            (
                ["duration", "term", "auto-renew", "legal form", "business activity", "مدة", "مده", "التجديد التلقائي", "الشكل القانوني", "نوع النشاط"],
                "اقتراح الاختيار داخل الخطة القابلة للتعديل",
                "يستنتج المساعد الخيار الأنسب من السياق ويعرضه داخل الخطة؛ يمكن للمتعامل تغييره من خيار «تعديل» قبل اعتماد الإجراء.",
                "Recommend the option inside the editable plan",
                "The assistant derives the best-fit option from context and shows it in the plan; the customer can change it through Edit before approving the action.",
            ),
            (
                ["pay", "payment", "fee", "يدفع", "يسدد", "دفع", "سداد", "رسوم"],
                "تجهيز عملية الدفع ومتابعتها",
                "يعرض المساعد البنود والمبلغ والجهة المستفيدة؛ المتعامل يعتمد ويدفع، ثم يتحقق المساعد من النتيجة ويتابع أي فشل.",
                "Prepare and monitor payment",
                "The assistant shows items, total and beneficiary; the customer authorizes and pays, then the assistant verifies the result and follows up on failure.",
            ),
            (
                ["approve", "consent", "confirm", "review the request", "يوافق", "موافقة", "موافقه", "يؤكد", "تأكيد", "يراجع الطلب"],
                "عرض الخطة للموافقة أو التعديل",
                "يعرض المساعد كل الإجراءات والبيانات والرسوم عند وجودها والنتيجة قبل الإجراء الملزم، ويعيد بناء الخطة إذا اختار المتعامل «تعديل».",
                "Show the plan for approval or editing",
                "The assistant shows all actions, data, applicable fees and outcome before a binding action and rebuilds the plan if the customer chooses Edit.",
            ),
            (
                ["branch", "service center", "الفرع", "مركز الخدمة", "مركز الخدمه"],
                "تنفيذ الإجراء عبر القناة الرقمية",
                "ينفذ المساعد الإجراء عبر التكامل المقترح، ويوجه الاستثناء فقط لموظف مع كامل السياق دون زيارة المتعامل للمسار الطبيعي.",
                "Execute through the digital channel",
                "The assistant executes through the proposed integration and routes only exceptions to an employee with full context, without a happy-path visit.",
            ),
            (
                ["follow up", "wait", "call", "email", "يتابع", "ينتظر", "يتصل", "يرسل"],
                "المتابعة وحفظ حالة الطلب",
                "يراقب المساعد حالة الطلب والاعتماديات، يحفظ آخر خطوة ويرسل إشعارًا عند التغيير دون متابعة يدوية.",
                "Follow up and preserve request state",
                "The assistant monitors state and dependencies, preserves the last completed action and notifies on change without manual follow-up.",
            ),
            (
                ["receives", "receive", "result", "confirmation", "يستلم", "يتسلم", "النتيجة", "تأكيد"],
                "تسليم النتيجة ومسار الاعتراض",
                "يسلم المساعد النتيجة ووقت السريان ومكان الوثيقة، ويتيح التصحيح أو الاعتراض أو طلب موظف من المكان نفسه.",
                "Deliver the outcome and objection path",
                "The assistant delivers the outcome, effective date and document location and enables correction, objection or human help in the same place.",
            ),
        ]
        for signals, ar_action, ar_how, en_action, en_how in cases:
            if self._contains(text, signals):
                return (
                    (ar_action, ar_how)
                    if is_arabic
                    else (en_action, en_how)
                )
        return (
            (
                "تنفيذ الإجراء والتحقق من نتيجته",
                "ينفذ المساعد الإجراء عبر أداة أو تكامل مصرح به، يسجل ما فعله ويتحقق من النتيجة قبل الانتقال للخطوة التالية.",
            )
            if is_arabic
            else (
                "Execute the action and verify its result",
                "The assistant executes through an authorized tool or integration, logs the action and verifies the result before continuing.",
            )
        )

    def _is_customer_step(self, step):
        return self._contains(str(step).lower(), [
            "customer", "applicant", "user", "client", "العميل",
            "المتعامل", "المستخدم", "مقدم الطلب",
        ])

    def _removed_customer_burden_steps(
        self,
        source_steps,
        is_arabic,
        constraints=None,
        profile=None,
    ):
        constraints = constraints or {}
        profile = profile or {}
        removed = []
        for number, step in enumerate(source_steps, start=1):
            if not self._is_customer_burden_step(step, profile):
                continue
            if number in constraints:
                continue
            assistant_action, how = self._agent_action_for_source(
                step,
                is_arabic,
                profile,
            )
            removed.append({
                "step": step,
                "status": "FAIL",
                "reason": (
                    "هذه خطوة بيروقراطية على المتعامل؛ ينفذها المساعد وتبقى الموافقة المحددة فقط كنقطة تحكم."
                    if is_arabic
                    else "This is administrative customer work; the assistant performs it and only action-specific consent remains."
                ),
                "standard_id": (
                    "STAGE-07"
                    if profile.get("has_payment_stage")
                    and self._contains_payment(step)
                    else "STD-02"
                ),
                "standard_title": "Burden Shifts to the Assistant",
                "evidence": step,
                "assistant_action": assistant_action,
                "how": how,
            })
        return removed

    def _protected_constraint_map(self, service):
        constraints = {}
        for item in service.get("protected_steps", []):
            if not isinstance(item, dict):
                continue
            try:
                step_number = int(item.get("step_number", 0))
            except (TypeError, ValueError):
                continue
            level = str(item.get("level", "REQUIREMENT")).upper()
            if step_number <= 0 or level not in {"REQUIREMENT", "HUMAN", "AS_IS"}:
                continue
            constraints[step_number] = {
                "level": level,
                "reason": str(item.get("reason", "")).strip(),
                "source_reference": str(item.get("source_reference", "")).strip(),
            }
        return constraints

    def _apply_protected_steps(self, future_steps, source_steps, constraints, is_arabic):
        if not constraints:
            return future_steps

        exact_steps = []
        for step_number, constraint in constraints.items():
            if not 0 < step_number <= len(source_steps):
                continue
            source = source_steps[step_number - 1]
            level = constraint.get("level")

            for future in future_steps:
                if source in future.get("source_steps", []):
                    future.setdefault("protected_constraints", []).append({
                        "step_number": step_number,
                        **constraint,
                    })
                    if level in {"AS_IS", "HUMAN"}:
                        future["source_steps"] = [
                            item for item in future.get("source_steps", []) if item != source
                        ]

            if level not in {"AS_IS", "HUMAN"}:
                continue

            current_type = self._protected_owner_type(source, level)
            customer_burden = (
                current_type == "CUSTOMER"
                and self._customer_control_type(source) is None
            )
            exact_steps.append({
                "step_number": 0,
                "name": source,
                "type": current_type,
                "action": (
                    "تنفيذ الخطوة كما اعتمدها الموظف دون حذف أو دمج."
                    if is_arabic
                    else "Execute the step exactly as approved by the employee, without removal or merging."
                ),
                "change_type": "KEPT",
                "reason": constraint.get("reason") or (
                    "خطوة محمية بقرار بشري."
                    if is_arabic
                    else "Protected by a human-authored constraint."
                ),
                "standard_id": "STD-04",
                "related_standard_ids": ["STD-04"],
                "source_steps": [source],
                "semantic_category": "protected_control",
                "component_categories": ["protected_control"],
                "implementation_status": (
                    "HUMAN_REQUIRED" if level == "HUMAN" else "HUMAN_LOCKED_AS_IS"
                ),
                "customer_burden": customer_burden,
                "customer_control_points": [],
                "owner": current_type,
                "assistant_action": (
                    "ينسق المساعد الخطوة ويحافظ على القيد البشري."
                    if is_arabic
                    else "The assistant coordinates the step while preserving the human constraint."
                ),
                "customer_role": source if current_type == "CUSTOMER" else (
                    "لا يوجد عمل إداري إضافي على المتعامل"
                    if is_arabic
                    else "No additional customer administrative work"
                ),
                "visible_before_payment": True,
                "completion_evidence": constraint.get("source_reference") or (
                    "سجل القيد والتنفيذ"
                    if is_arabic
                    else "Constraint and execution record"
                ),
                "human_constraint": {"step_number": step_number, **constraint},
            })

        result_index = next(
            (
                index
                for index, item in enumerate(future_steps)
                if item.get("semantic_category") == "customer_outcome"
            ),
            len(future_steps),
        )
        combined = future_steps[:result_index] + exact_steps + future_steps[result_index:]
        for index, step in enumerate(combined, start=1):
            step["step_number"] = index
        return combined

    def _protected_owner_type(self, step, level):
        if level == "HUMAN":
            return "HUMAN"
        lowered = str(step).lower()
        if self._is_customer_step(lowered):
            return "CUSTOMER"
        if self._contains(lowered, [
            "employee", "agent", "supervisor", "officer", "staff",
            "الموظف", "موظف", "المشرف", "المدير", "المخول",
        ]):
            return "HUMAN"
        return "SYSTEM"

    def _merged_trace(self, future_steps, removed_steps, is_arabic):
        removed_text = {item["step"] for item in removed_steps}
        return [
            {
                "from": source,
                "into": future["name"],
                "reason": (
                    "دمج النشاط داخل مرحلة خدمة يحددها تعقيد الرحلة الفعلي."
                    if is_arabic
                    else "Consolidated into a service stage derived from actual journey complexity."
                ),
                "standard_id": future["standard_id"],
                "semantic_category": future["semantic_category"],
            }
            for future in future_steps
            for source in future.get("source_steps", [])
            if source not in removed_text
        ]

    def _automation_trace(self, future_steps):
        return [
            {
                "current_step": source,
                "proposed_action": future["name"],
                "decision": (
                    "ORCHESTRATE_HUMAN_CONTROL"
                    if future["type"] == "HUMAN"
                    else "AUTOMATE_OR_ORCHESTRATE"
                ),
                "standard_id": future["standard_id"],
                "semantic_category": future["semantic_category"],
            }
            for future in future_steps
            for source in future.get("source_steps", [])
        ]

    def _required_integrations(self, profile, is_arabic):
        result = []
        if profile["has_data_stage"]:
            result.append({
                "status": "PROPOSED",
                "description": (
                    "طبقة تكامل مصرح بها لاسترجاع البيانات والتحقق منها"
                    if is_arabic
                    else "Authorized integration layer for data retrieval and verification"
                ),
                "supports": ["data_completion"],
            })
        result.append({
            "status": "PROPOSED",
            "description": (
                "تكامل تنفيذ الخدمة وحفظ الحالة وسجل الإجراءات"
                if is_arabic
                else "Service execution, state and action-log integration"
            ),
            "supports": ["execution_continuity", "customer_outcome"],
        })
        if profile["has_payment_stage"]:
            result.append({
                "status": "PROPOSED",
                "description": (
                    "تكامل سداد الإمارات مع الموافقة ومعالجة فشل الدفع"
                    if is_arabic
                    else "UAE government payment integration with consent and failure recovery"
                ),
                "supports": ["payment"],
            })
        return result

    def _control_points(self, profile, is_arabic):
        result = [
            {
                "name": (
                    "موافقة محددة قبل الإجراء الملزم"
                    if is_arabic
                    else "Action-specific consent before a binding action"
                ),
                "customer_burden": False,
                "standard_id": "STD-04",
            },
            {
                "name": (
                    "إيقاف أو سحب الصلاحية بخطوة واحدة"
                    if is_arabic
                    else "Pause or withdraw permission in one action"
                ),
                "customer_burden": False,
                "standard_id": "STD-04",
            },
        ]
        if profile["has_payment_stage"]:
            result.append({
                "name": (
                    "اعتماد الرسوم والمبلغ والجهة المستفيدة قبل الدفع"
                    if is_arabic
                    else "Approve fees, total and beneficiary before payment"
                ),
                "customer_burden": False,
                "standard_id": "STAGE-07",
            })
        if profile["has_package_stage"]:
            result.insert(0, {
                "name": (
                    "اختيار الباقة المقترحة أو تغييرها"
                    if is_arabic
                    else "Select or change the recommended package"
                ),
                "customer_burden": False,
                "standard_id": "STAGE-04",
            })
        return result

    def _is_customer_burden_step(self, step, profile=None):
        text = str(step).lower()
        actors = [
            "customer", "applicant", "user", "client", "العميل",
            "المتعامل", "المستخدم", "مقدم الطلب",
        ]
        if not self._contains(text, actors):
            return False
        return self._customer_control_type(step, profile) is None

    def _contains_payment(self, value):
        return self._contains(str(value).lower(), [
            "payment", "pay ", "fee", "fees", "دفع", "يدفع",
            "سداد", "يسدد", "رسوم",
        ])

    def _contains(self, value, signals):
        text = str(value).lower()
        return any(signal in text for signal in signals)

    def _is_arabic(self, value):
        return any("\u0600" <= char <= "\u06ff" for char in str(value))
