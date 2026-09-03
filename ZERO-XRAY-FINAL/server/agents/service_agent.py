from core.json_utils import extract_json, has_parse_error
from core.service_classifier import classify_service
from core.llm import ai_label, log_raw_response
from core.grounding import is_semantically_grounded


class ServiceAnalystAgent:
    """Understands the raw service input and produces the structured
    "current journey" analysis every downstream agent builds on.

    MERGE NOTE (P1 -> P2, surgical functional merge):
    P2's version of this agent had been reduced to pure keyword
    heuristics with no AI call at all -- semantic step extraction,
    AI-driven objective/friction understanding, and evidence-gated
    capability detection (all present in P1) had been dropped when
    P2 moved procedure-cleaning into core/service_input_normalizer.py.
    That normalizer only strips noise from the RAW TEXT; it does not
    decide how many real semantic steps that text represents, nor
    does it detect capabilities. Both are restored here, AI-primary,
    with P1's anti-hallucination guards intact, layered on top of
    P2's richer heuristic metadata (waiting times / approvals /
    branch-visit inference / friction points / customer touchpoints)
    and P2's classify_service() call, none of which are removed.
    """

    def __init__(self, llm):
        self.llm = llm

    def run(self, service):

        raw_steps = list(service.get("steps", []))

        # ============================================================
        # SEMANTIC CURRENT JOURNEY (restored from P1, AI-primary)
        # ============================================================
        # "steps" as supplied by the caller (typed text split into
        # lines, or text extracted from an uploaded PDF/DOCX/image, or
        # already narrowed to the procedure section by
        # service_input_normalizer) is NOT reliably one line == one
        # real step: a step's own description, its listed options, or
        # a wrapped sentence can all land as separate array entries.
        # Every downstream count (current-journey count, step-by-step
        # compliance, the journey builder's understanding of the
        # current journey) must operate on the actual semantic steps,
        # not the raw line count -- so extraction happens exactly
        # once, here, and the corrected list becomes "steps" for
        # everything that follows.
        semantic_result = self._extract_semantic_steps(
            raw_steps=raw_steps,
            description=str(service.get("description", "")),
            service_name=str(service.get("service_name", "")),
        )
        steps = semantic_result["steps"]
        steps_analysis_source = semantic_result["analysis_source"]

        manual_actions = list(service.get("manual_actions", []))
        waiting_times = list(service.get("waiting_times", []))
        approvals = list(service.get("approvals", []))
        actors = list(service.get("actors", []))
        dependencies = list(service.get("dependencies", []))
        documents = list(service.get("documents", []))
        digital_actions = list(service.get("digital_actions", []))

        step_texts = [str(step) for step in steps]

        def containing(signals):
            return [
                step
                for step in step_texts
                if any(signal in step.lower() for signal in signals)
            ]

        if not manual_actions:
            manual_actions = containing([
                "employee", "agent", "manually", "manual", "supervisor",
                "staff", "الموظف", "المشرف", "المدير", "يدويا", "يدويًا",
            ])

        if not waiting_times:
            waiting_times = containing([
                "wait", "waiting", "pending", "ينتظر", "انتظار",
                "قيد الانتظار", "معلق", "معلّق",
            ])

        if not approvals:
            approvals = containing([
                "approval", "approve", "supervisor", "موافقة", "موافقه",
                "اعتماد", "المشرف", "المدير",
            ])

        if not documents:
            documents = containing([
                "document", "upload", "attachment", "certificate", "copy of",
                "مستند", "وثيقة", "وثيقه", "يرفع", "يرفق", "صورة من",
            ])

        inferred_branch_steps = containing([
            "branch", "service center", "physical visit", "الفرع",
            "مركز الخدمة", "مركز الخدمه", "الحضور شخصيا", "الحضور شخصيًا",
        ])

        branch_visits = int(service.get("branch_visits", 0) or 0)
        if branch_visits <= 0:
            branch_visits = len(inferred_branch_steps)

        friction_points = []
        combined = " ".join(steps + manual_actions).lower()
        repeated_words = [
            "again", "same", "repeat", "duplicate", "re-enter", "reenter",
            "مرة اخرى", "مرة أخرى", "تاني", "نفس البيانات", "نفس الرقم",
            "إعادة إدخال",
        ]
        if any(word in combined for word in repeated_words):
            friction_points.append("Possible repeated data entry")
        if manual_actions:
            friction_points.append("Manual operational work exists")
        if waiting_times:
            friction_points.append("Waiting points exist in the journey")
        if approvals:
            friction_points.append("Approval dependency exists")
        if service.get("branch_visits", 0) > 0:
            friction_points.append("Physical branch visit exists")

        customer_touchpoints = [
            step
            for step in steps
            if any(
                actor in step.lower()
                for actor in [
                    "customer", "applicant", "client", "user",
                    "العميل", "المتعامل", "المستخدم", "مقدم الطلب",
                ]
            )
        ]

        # ============================================================
        # AI-PRIMARY OBJECTIVE / FRICTION UNDERSTANDING (restored, P1)
        # ============================================================
        ai_result = self._analyze_with_ai(
            service=service,
            steps=steps,
            manual_actions=manual_actions,
            waiting_times=waiting_times,
            approvals=approvals,
            documents=documents,
        )

        objective = service.get("description", "")
        analysis_source = "template"

        if ai_result is not None:
            if ai_result.get("objective"):
                objective = ai_result["objective"]
            if ai_result.get("friction_points"):
                seen = set()
                merged_friction = []
                for item in friction_points + ai_result["friction_points"]:
                    key = str(item).strip().lower()
                    if key and key not in seen:
                        seen.add(key)
                        merged_friction.append(item)
                friction_points = merged_friction
            analysis_source = ai_label()

        # ============================================================
        # CAPABILITY DETECTION (restored, AI-primary, evidence-gated)
        # ============================================================
        capabilities = self._detect_capabilities(
            steps=steps,
            description=str(service.get("description", "")),
            service_name=str(service.get("service_name", "")),
        )

        return {
            "objective": objective,
            "actors": actors,
            "steps": steps,
            "raw_steps": raw_steps,
            "steps_analysis_source": steps_analysis_source,
            "documents": documents,
            "approvals": approvals,
            "waiting_points": waiting_times,
            "manual_actions": manual_actions,
            "digital_actions": digital_actions,
            "dependencies": dependencies,
            "branch_visits": branch_visits,
            "customer_touchpoints": customer_touchpoints,
            "friction_points": friction_points,
            "analysis_source": analysis_source,
            "capabilities": capabilities,
            "service_classification": classify_service(service),
        }

    # ================================================================
    # SEMANTIC CURRENT JOURNEY EXTRACTION (AI-primary, restored)
    # ================================================================

    def _extract_semantic_steps(self, raw_steps, description, service_name):
        cleaned_raw = [
            str(item).strip() for item in raw_steps if str(item).strip()
        ]
        if not cleaned_raw:
            return {"steps": [], "analysis_source": "template"}

        if self.llm:
            numbered = "\n".join(
                f"{i}. {s}" for i, s in enumerate(cleaned_raw, start=1)
            )
            prompt = f"""Read these raw lines describing a service journey (they may come from typed text or an extracted document, so a single real step can be split across several lines, and a step's listed options can appear as separate lines).

Service name: {service_name or "(not provided)"}
Description: {description or "(not provided)"}

RAW LINES:
{numbered}

TASK: identify the actual sequence of semantic steps a customer/employee goes through. Rules:
- A step's own description or a wrapped continuation of the same sentence is part of THAT step, not a new one.
- Options or choices listed under a step (e.g. "Standard / Express / Premium", bullet points, "or ...") belong to that one step, not separate steps.
- Multiple raw lines describing the same action belong to ONE step.
- Never invent a step that isn't actually described in the raw lines.
- The result must never contain MORE steps than there are meaningfully distinct actions -- when in doubt, merge rather than split.

Return JSON only, exactly this shape:
{{"steps": ["first real step, folding in its own description/options", "second real step", "..."]}}
"""
            try:
                response = self.llm.generate(
                    system_prompt=(
                        "You are a meticulous process analyst who "
                        "reads raw, possibly noisy journey text and "
                        "identifies the real semantic steps, "
                        "correctly folding a step's description and "
                        "its listed options into that same step "
                        "instead of counting them separately. You "
                        "always return valid JSON matching exactly "
                        "the requested shape, with no markdown "
                        "fences and no commentary outside the JSON."
                    ),
                    user_prompt=prompt,
                    max_new_tokens=1400,
                )
            except Exception as error:
                print(
                    f"[AI FAILED -> FALLBACK] "
                    f"[SERVICE] Semantic-steps AI call failed: "
                    f"{error}. Falling back to heuristic merge."
                )
                response = ""

            log_raw_response("SERVICE.semantic_steps", response)

            result = extract_json(response) if response else None
            reason = "empty response"
            if isinstance(result, list):
                raw_result_steps = result
            elif isinstance(result, dict) and not has_parse_error(result):
                raw_result_steps = result.get("steps")
                if not isinstance(raw_result_steps, list):
                    raw_result_steps = None
                    reason = "'steps' was not a list"
            elif isinstance(result, dict):
                raw_result_steps = None
                reason = "JSON parse error"
            else:
                raw_result_steps = None

            if isinstance(raw_result_steps, list):
                ai_steps = [
                    str(item).strip()
                    for item in raw_result_steps
                    if str(item).strip()
                ]
                if not ai_steps:
                    reason = "empty steps list"
                elif len(ai_steps) > len(cleaned_raw) * 4:
                    # ROOT-CAUSE FIX: a real observed Ollama 0.32.15 +
                    # qwen3:4b run produced 14 semantic steps from 8
                    # raw lines and was rejected outright by a strict
                    # "steps must never exceed raw lines" rule -- but
                    # that premise doesn't hold for real input: a
                    # single raw line/paragraph legitimately often
                    # bundles several distinct real actions (numbered
                    # sub-steps flattened by document extraction, a
                    # compound sentence like "upload the document,
                    # then wait for review, then receive the
                    # decision"). The model splitting one dense raw
                    # line into several genuine steps is CORRECT
                    # behaviour, not hallucination. What actually
                    # matters is whether each proposed step is
                    # grounded in the real raw text, not the raw line
                    # count. Replace the count ceiling with a grounding
                    # check per step (below); keep only a generous
                    # sanity cap (4x) to catch genuine runaway
                    # invention.
                    reason = (
                        f"returned {len(ai_steps)} steps, implausibly "
                        f"more than 4x the {len(cleaned_raw)} raw "
                        "line(s) given -- likely invented content"
                    )
                elif not all(len(s) >= 3 for s in ai_steps):
                    reason = "one or more steps were trivially short"
                else:
                    # ROOT-CAUSE FIX: this used to be all-or-nothing --
                    # if even ONE of e.g. 14 real, grounded steps
                    # failed the per-step check, the WHOLE batch of 14
                    # was thrown away and replaced with the crude
                    # heuristic merge. A real qwen3:4b run legitimately
                    # produces a couple of steps per batch that are
                    # slightly more elaborated paraphrases (a compound
                    # step correctly split into "specify the home
                    # address and delivery preference" / "add an
                    # additional postal agent" from one dense raw
                    # line) that can sit right at the edge of the
                    # grounding threshold -- losing 13 good steps to
                    # save 1 questionable one is the wrong trade.
                    # Drop only the individual ungrounded step(s) and
                    # keep every step that IS grounded; only discard
                    # the entire batch (fall back to the heuristic
                    # merge) when ungrounded steps are the majority,
                    # which is the actual signal of a genuinely
                    # unreliable/invented response rather than a few
                    # borderline paraphrases.
                    ungrounded = self._ungrounded_steps(ai_steps, cleaned_raw)
                    ungrounded_set = set(ungrounded)
                    kept_steps = [
                        s for s in ai_steps if s not in ungrounded_set
                    ]
                    if not ungrounded_set:
                        print(
                            f"[SERVICE] Semantic steps accepted: "
                            f"{len(cleaned_raw)} raw line(s) -> "
                            f"{len(ai_steps)} step(s)."
                        )
                        return {"steps": ai_steps, "analysis_source": ai_label()}
                    elif kept_steps and len(ungrounded_set) <= len(ai_steps) // 2:
                        print(
                            f"[SERVICE] Semantic steps partially accepted: "
                            f"{len(cleaned_raw)} raw line(s) -> "
                            f"{len(ai_steps)} AI step(s), dropped "
                            f"{len(ungrounded_set)} ungrounded step(s) "
                            f"(e.g. {next(iter(ungrounded_set))!r}) -> "
                            f"{len(kept_steps)} step(s) kept."
                        )
                        return {
                            "steps": kept_steps,
                            "analysis_source": ai_label(),
                        }
                    else:
                        reason = (
                            f"{len(ungrounded_set)} of {len(ai_steps)} "
                            "step(s) (a majority) had no real overlap "
                            "with the raw lines "
                            f"(e.g. {next(iter(ungrounded_set))!r}) -- "
                            "likely invented"
                        )
            print(
                f"[AI FAILED -> FALLBACK] "
                f"[SERVICE] Semantic-steps AI output unusable ({reason}). "
                "Falling back to heuristic merge."
            )

        return {
            "steps": self._heuristic_merge_steps(cleaned_raw),
            "analysis_source": "template",
        }

    def _ungrounded_steps(self, ai_steps, cleaned_raw):
        """Return the subset of ai_steps that cannot be tied back to
        real content from cleaned_raw -- the actual anti-hallucination
        guard for semantic-step extraction (see the comment at the
        call site for why a raw-line count ceiling was the wrong
        check).

        ROOT-CAUSE FIX: this used to require an EXACT vocabulary match
        between a step's own significant words and the raw source
        text. Real qwen3:4b output routinely REWORDS the source
        (different conjugation, a synonym, an Arabic word with a
        different attached prefix/suffix) while preserving its
        meaning -- every one of those correct, real outputs used to
        fail this check and get discarded. is_semantically_grounded()
        (core/grounding.py) tolerates that kind of paraphrase via
        light stemming and a conservative fuzzy match, while still
        rejecting a step that has no real relationship to the source
        text at all -- the anti-hallucination property this guard
        exists for is unchanged, only the definition of "grounded" is
        now meaning-based instead of exact-string-based."""
        source_text = " ".join(cleaned_raw)
        return [
            step for step in ai_steps
            if not is_semantically_grounded(step, source_text)
        ]

    def _heuristic_merge_steps(self, cleaned_raw):
        option_prefixes = (
            "-", "*", "•", "‣", "◦", "·", "or ", "either", "option",
            "choice", "e.g", "i.e", "أو ", "خيار", "مثال", "مثل ",
        )

        merged = []
        for line in cleaned_raw:
            stripped = line.lstrip("-*•‣◦· \t")
            lowered = line.lower()
            looks_like_bullet = stripped != line
            looks_like_option_word = any(
                lowered.startswith(prefix) for prefix in option_prefixes
            )
            word_count = len(line.split())
            looks_like_fragment = word_count <= 3 and bool(merged)

            if merged and (
                looks_like_bullet or looks_like_option_word
                or looks_like_fragment
            ):
                addition = stripped if looks_like_bullet else line
                merged[-1] = f"{merged[-1]} ({addition})"
            else:
                merged.append(line)

        return merged or list(cleaned_raw)

    # ================================================================
    # CAPABILITY DETECTION (AI-primary, evidence-gated, restored)
    # ================================================================

    def _detect_capabilities(self, steps, description, service_name):
        source_text = " ".join(steps) + " " + description + " " + service_name

        if self.llm:
            numbered = "\n".join(
                f"{i}. {s}" for i, s in enumerate(steps, start=1)
            ) or "(no steps provided)"

            prompt = f"""Determine, for THIS specific service only, whether each capability below is genuinely required -- grounded in real evidence from the text, never assumed.

Service name: {service_name or "(not provided)"}
Description: {description or "(not provided)"}

Steps:
{numbered}

CAPABILITIES TO EVALUATE:
- payment: does the CUSTOMER actually need to pay something to complete THIS request? A complaint, dispute or refund about a charge that already happened is NOT a new payment -- do not mark payment true just because money/fee/charge is mentioned in that context.
- documents: does the customer need to submit/upload a specific document or certificate?
- physical_visit: does the customer need to physically go to a branch/office/service center?
- human_approval: does a NAMED HUMAN ROLE (an employee, officer, supervisor, manager, committee) have to make a discretionary decision -- approve, reject, authorise or sign off -- that a system could not make on its own? Verifying, validating, checking, matching, authenticating or confirming data against a record is NOT human approval: it is a deterministic check, and it stays false even when a person happens to perform it today. Mark this true only if the evidence shows a real judgement call, not a check.

For every capability you mark true, quote or closely paraphrase the exact evidence from the text above. Never invent evidence. If you cannot point to real evidence, mark it false.

Return JSON only, exactly this shape:
{{
  "has_payment": true or false, "payment_evidence": "",
  "has_documents": true or false, "documents_evidence": "",
  "has_physical_visit": true or false, "visit_evidence": "",
  "has_human_approval": true or false, "human_approval_evidence": ""
}}
"""
            try:
                response = self.llm.generate(
                    system_prompt=(
                        "You are a strict, evidence-only service "
                        "capability analyst. You never mark a "
                        "capability true without being able to point "
                        "to real evidence in the given text, and you "
                        "never infer a customer payment from a "
                        "complaint or dispute about a past charge. "
                        "You always return valid JSON matching "
                        "exactly the requested shape, with no "
                        "markdown fences and no commentary outside "
                        "the JSON."
                    ),
                    user_prompt=prompt,
                    max_new_tokens=700,
                )
            except Exception as error:
                print(
                    f"[AI FAILED -> FALLBACK] "
                    f"[SERVICE] Capability-detection AI call failed: "
                    f"{error}. Falling back to keyword-based "
                    "detection."
                )
                response = ""

            log_raw_response("SERVICE.capabilities", response)

            result = extract_json(response) if response else None
            if isinstance(result, dict) and not has_parse_error(result):
                validated = self._validate_capabilities(result, source_text)
                if validated is not None:
                    validated["analysis_source"] = ai_label()
                    print(
                        "[SERVICE] Capability detection accepted: "
                        f"payment={validated['has_payment']}, "
                        f"documents={validated['has_documents']}, "
                        f"visit={validated['has_physical_visit']}, "
                        f"human_approval={validated['has_human_approval']}."
                    )
                    return validated
            print(
                f"[AI FAILED -> FALLBACK] "
                "[SERVICE] Capability-detection AI output unusable. "
                "Falling back to keyword-based detection."
            )

        return self._keyword_capabilities(steps, source_text)

    def _validate_capabilities(self, raw, source_text):
        pairs = [
            ("has_payment", "payment_evidence"),
            ("has_documents", "documents_evidence"),
            ("has_physical_visit", "visit_evidence"),
            ("has_human_approval", "human_approval_evidence"),
        ]
        out = {}
        for flag_key, evidence_key in pairs:
            flag = bool(raw.get(flag_key, False))
            evidence = str(raw.get(evidence_key, "")).strip()
            if flag and not self._evidence_is_grounded(evidence, source_text):
                flag = False
                evidence = ""
            # ROOT-CAUSE FIX (verification misread as human approval --
            # generic): grounding alone only proves the quoted evidence
            # EXISTS in the source text. It says nothing about whether
            # that evidence actually denotes the capability it was
            # offered for. A verification/validation step ("the officer
            # verifies the submitted data against the register") is
            # genuinely present in the text, so it passed grounding and
            # was accepted as human_approval -- which then propagated as
            # ground truth into the journey builder (capabilities are
            # explicitly "treat as ground truth" there) and produced a
            # HUMAN approval stage for a service that only ever needed
            # a deterministic check. A check is automatable; a
            # discretionary approval is not, so conflating them changes
            # the entire redesign. Verified below against the meaning of
            # the evidence itself.
            if flag and flag_key == "has_human_approval":
                if not self._evidence_is_human_approval(evidence):
                    flag = False
                    evidence = ""
            if not flag:
                evidence = ""
            out[flag_key] = flag
            out[evidence_key] = evidence
        return out

    # Discretionary-decision wording. A human approval requires an actual
    # decision verb -- something that can be granted or withheld.
    _APPROVAL_DECISION_SIGNALS = (
        "approve", "approval", "approves", "approved", "authorise",
        "authorize", "authorisation", "authorization", "sign off",
        "sign-off", "signs off", "endorse", "endorsement", "grant",
        "reject", "rejection", "decline", "discretion", "judgement",
        "judgment", "adjudicate", "committee", "escalate", "escalation",
        # Explicit decision wording. A step that reaches or issues a
        # DECISION is exercising discretion, whatever the domain -- this
        # is the outcome side of the same distinction, and omitting it
        # would misclassify a genuine judgement call as a mere check.
        "decision", "decides", "decide", "determination", "determines",
        "rules on", "verdict", "resolution", "resolves",
        "موافقة", "موافقه", "يوافق", "الموافقة", "اعتماد", "يعتمد",
        "المصادقة", "مصادقة", "يصادق", "تفويض", "رفض", "يرفض",
        "تقدير", "اجتهاد", "لجنة", "اللجنة", "تصعيد",
        "قرار", "القرار", "يقرر", "البت", "يبت", "يحسم", "تسوية",
    )

    # Deterministic-check wording. Present in a step that a system can
    # perform, even when a person performs it today.
    _VERIFICATION_ONLY_SIGNALS = (
        "verify", "verifies", "verified", "verification", "validate",
        "validates", "validation", "check", "checks", "checking",
        "confirm data", "authenticate", "authentication", "match",
        "matching", "screen", "screening", "review the data", "inspect",
        "تحقق", "التحقق", "يتحقق", "تدقيق", "التدقيق", "يدقق", "فحص",
        "الفحص", "يفحص", "مطابقة", "المطابقة", "يطابق", "التأكد",
        "مراجعة البيانات",
    )

    # Human actors. An approval is only a HUMAN approval when a person
    # is the one deciding.
    _HUMAN_ACTOR_SIGNALS = (
        "employee", "officer", "supervisor", "manager", "staff",
        "reviewer", "inspector", "committee", "head of", "director",
        "specialist", "agent reviews", "human",
        "الموظف", "موظف", "المشرف", "مشرف", "المدير", "مدير", "المسؤول",
        "المختص", "المفتش", "لجنة", "اللجنة", "رئيس", "بشري", "يدوي",
        "يدويا", "يدويًا",
    )

    def _evidence_is_human_approval(self, evidence):
        """True only when the evidence describes a discretionary decision
        made by a human, rather than a deterministic check.

        Entirely vocabulary-driven and domain-agnostic -- it inspects the
        wording of whatever evidence was supplied and applies the same
        test to every service. It never looks at the service name, type
        or domain.
        """
        text = str(evidence or "").strip().lower()
        if not text:
            return False

        has_decision = any(
            signal in text for signal in self._APPROVAL_DECISION_SIGNALS
        )
        has_verification = any(
            signal in text for signal in self._VERIFICATION_ONLY_SIGNALS
        )
        has_human_actor = any(
            signal in text for signal in self._HUMAN_ACTOR_SIGNALS
        )

        if not has_decision:
            # Nothing that can be granted or withheld -- at most a check.
            return False
        if has_verification and not has_human_actor:
            # Reads as a verification/validation activity with approval
            # wording attached but no human decision-maker.
            return False
        return True

    def _evidence_is_grounded(self, evidence, source_text):
        """ROOT-CAUSE FIX: replaced exact-vocabulary word matching with
        meaning-based grounding (core/grounding.py) so a real qwen3:4b
        capability-evidence quote that rewords the source (rather than
        echoing its exact vocabulary) is accepted, while evidence that
        shares no real basis with the source text is still rejected.
        Unlike step-grounding, empty evidence must still fail here --
        an unsupported capability flag has no evidence to fall back
        on, so an empty string is never "too short to judge"."""
        if not evidence:
            return False
        return is_semantically_grounded(evidence, source_text)

    def _keyword_capabilities(self, steps, source_text):
        lowered = source_text.lower()

        no_fee_signals = [
            "no fee", "no fees", "free of charge", "without charge",
            "fees: none", "fee: none", "no charge", "not charged",
            "بدون رسوم", "لا توجد رسوم", "لا يوجد رسوم", "مجاناً",
            "مجانا", "الرسوم: لا يوجد", "بدون مقابل", "دون مقابل",
        ]
        complaint_signals = [
            "complaint", "dispute", "refund", "grievance", "objection",
            "شكوى", "نزاع", "استرداد", "اعتراض", "تظلم",
        ]
        payment_signals = [
            "payment", "pay ", "fee", "fees", "دفع", "يدفع",
            "سداد", "يسدد", "رسوم",
        ]
        is_complaint_context = any(s in lowered for s in complaint_signals)
        has_payment = (
            not is_complaint_context
            and not any(s in lowered for s in no_fee_signals)
            and any(s in lowered for s in payment_signals)
        )

        document_signals = [
            "document", "upload", "attachment", "certificate", "copy of",
            "مستند", "وثيقة", "وثيقه", "يرفع", "يرفق", "صورة من",
        ]
        has_documents = any(s in lowered for s in document_signals)

        visit_signals = [
            "branch", "service center", "physical visit", "in person",
            "الفرع", "مركز الخدمة", "مركز الخدمه", "الحضور شخصيا",
            "الحضور شخصيًا",
        ]
        has_visit = any(s in lowered for s in visit_signals)

        # ROOT-CAUSE FIX (same verification-vs-approval distinction as the
        # AI path above, applied to the deterministic fallback so both
        # paths agree): a single approval-ish keyword anywhere in the
        # source text used to set has_human_approval on its own, so a
        # service whose only "approval" wording sat inside a verification
        # step was classified as needing human approval. The evidence
        # sentence is now tested with the same generic discriminator.
        approval_signals = [
            "approval", "approve", "committee", "judgement", "judgment",
            "موافقة", "موافقه", "اعتماد", "لجنة",
        ]

        def evidence_for(signals):
            for step in steps:
                step_lower = step.lower()
                if any(s in step_lower for s in signals):
                    return step
            return ""

        approval_evidence = evidence_for(approval_signals)
        # Judge the specific sentence the signal was found in. When the
        # signal only appears outside the step list (description-level
        # wording with no step to attribute it to), fall back to the
        # whole source text so the decision is still evidence-based.
        has_approval = (
            any(s in lowered for s in approval_signals)
            and self._evidence_is_human_approval(approval_evidence or lowered)
        )

        return {
            "has_payment": has_payment,
            "payment_evidence": evidence_for(payment_signals) if has_payment else "",
            "has_documents": has_documents,
            "documents_evidence": evidence_for(document_signals) if has_documents else "",
            "has_physical_visit": has_visit,
            "visit_evidence": evidence_for(visit_signals) if has_visit else "",
            "has_human_approval": has_approval,
            "human_approval_evidence": evidence_for(approval_signals) if has_approval else "",
            "analysis_source": "template",
        }

    def _analyze_with_ai(
        self, service, steps, manual_actions, waiting_times,
        approvals, documents,
    ):
        if not self.llm:
            return None

        description = str(service.get("description", "")).strip()
        service_name = str(service.get("service_name", "")).strip()
        numbered_steps = "\n".join(
            f"{i}. {s}" for i, s in enumerate(steps, start=1)
        ) or "(no steps provided)"

        prompt = f"""Read this service and understand it in context -- do not just scan for keywords.

Service name: {service_name or "(not provided)"}
Description: {description or "(not provided)"}

Current steps:
{numbered_steps}

Already detected mechanically (for context, do not just repeat these): manual actions={manual_actions}, waiting points={waiting_times}, approvals={approvals}, documents={documents}

Return JSON only, exactly this shape:
{{
  "objective": "one clear sentence stating what the customer is actually trying to accomplish",
  "friction_points": ["short phrase describing a real friction point in this specific journey", "..."]
}}

List only friction points you can genuinely support from the text above (e.g. redundant steps, unclear ownership, a step that blocks on another unnecessarily, unclear eligibility, an implicit physical visit). Return an empty list if there is genuinely no friction. Do not invent generic friction that could apply to any service.
"""

        try:
            response = self.llm.generate(
                system_prompt=(
                    "You are a careful service-analysis expert. You "
                    "read the actual text and reason about this "
                    "specific service rather than pattern-matching "
                    "keywords. You always return valid JSON matching "
                    "exactly the requested shape, with no markdown "
                    "fences and no commentary outside the JSON."
                ),
                user_prompt=prompt,
                max_new_tokens=500,
            )
        except Exception as error:
            print(
                f"[AI FAILED -> FALLBACK] "
                f"[SERVICE] AI analysis call failed: {error}. "
                "Falling back to keyword-based analysis."
            )
            return None

        log_raw_response("SERVICE.objective_friction", response)

        result = extract_json(response)
        if not isinstance(result, dict) or has_parse_error(result):
            print(
                f"[AI FAILED -> FALLBACK] "
                "[SERVICE] AI analysis output unusable (parse error). "
                "Falling back to keyword-based analysis."
            )
            return None

        objective = result.get("objective")
        objective = str(objective).strip() if isinstance(objective, str) else ""

        raw_friction = result.get("friction_points")
        friction = []
        if isinstance(raw_friction, list):
            for item in raw_friction:
                text = str(item).strip()
                if text:
                    friction.append(text)

        if not objective and not friction:
            print(
                f"[AI FAILED -> FALLBACK] "
                "[SERVICE] AI analysis output empty/unusable. "
                "Falling back to keyword-based analysis."
            )
            return None

        return {"objective": objective, "friction_points": friction}
