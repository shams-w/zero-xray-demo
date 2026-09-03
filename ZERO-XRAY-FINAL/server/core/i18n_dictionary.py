# English -> Arabic dictionary for the deterministic / template text
# authored inside the rule-based agents (service_agent, gap_agent,
# standards_agent + standards_catalog, step_compliance_agent,
# validation_agent, simulation_agent) plus a couple of top-level
# messages in main.py.
#
# These agents generate their fallback / baseline content as fixed
# English sentences regardless of the language the customer typed the
# service in. translate_result() (below) walks the final API response
# and swaps any string that matches a key here for its Arabic
# translation whenever the request asked for lang="ar".
#
# NOTE: JourneyBuilderAgent is handled differently - it already
# authors both an English and an Arabic version of every template it
# can produce, and simply needs to be told which one to use (see
# agents/journey_builder_agent.py, "requested_lang"). Its output is
# therefore NOT part of this dictionary; translating it again here
# would do nothing (the strings simply won't match) and is harmless.
#
# It is safe for this dictionary to contain entries that never show
# up in a particular response - translate_result() only replaces an
# exact match, so unused entries are simply never triggered.

EN_TO_AR = {

    # ---------------------------------------------------------------
    # main.py
    # ---------------------------------------------------------------
    "ZERO X-RAY Agentic AI Service Reengineering Engine":
        "محرك ZERO X-RAY لإعادة هندسة الخدمات بالذكاء الاصطناعي المساعد",
    "AI engine is not ready.":
        "محرك الذكاء الاصطناعي غير جاهز بعد.",
    "Loading local AI model...":
        "جارٍ تحميل نموذج الذكاء الاصطناعي المحلي...",

    # ---------------------------------------------------------------
    # agents/service_agent.py - friction points
    # ---------------------------------------------------------------
    "Manual operational work exists":
        "توجد أعمال تشغيلية يدوية",
    "Physical branch visit exists":
        "توجد زيارة فرع فعلية",
    "Possible repeated data entry":
        "احتمال تكرار إدخال البيانات",
    "Waiting points exist in the journey":
        "توجد نقاط انتظار ضمن الرحلة",

    # ---------------------------------------------------------------
    # agents/simulation_agent.py
    # ---------------------------------------------------------------
    "Future journey is incomplete.":
        "الرحلة المستقبلية غير مكتملة.",
    "Proposed integrations require technical, security and policy validation.":
        "التكاملات المقترحة تتطلب تحققاً تقنياً وأمنياً وسياسياً.",

    # ---------------------------------------------------------------
    # agents/gap_agent.py - deterministic baseline gaps
    # ---------------------------------------------------------------
    "A waiting point exists in the current journey.":
        "توجد نقطة انتظار في الرحلة الحالية.",
    "An approval exists and should be verified as necessary.":
        "توجد موافقة وينبغي التحقق من ضرورتها.",
    "Assess whether the visit can be replaced by a permitted digital or assisted action.":
        "تقييم إمكانية استبدال الزيارة بإجراء رقمي أو مُساعَد مسموح به.",
    "Automate or assist this action where technically and operationally feasible; retain human control if required.":
        "أتمتة هذا الإجراء أو مساعدته حيثما كان ذلك ممكناً تقنياً وتشغيلياً، مع الإبقاء على التحكم البشري إذا لزم الأمر.",
    "Avoids unnecessary approval layers without removing required controls.":
        "يتجنب طبقات الموافقة غير الضرورية دون إزالة الضوابط المطلوبة.",
    "Connect the relevant actors or systems and provide automatic status continuation where feasible.":
        "ربط الجهات أو الأنظمة ذات الصلة وتوفير استمرارية تلقائية للحالة حيثما أمكن.",
    "Reduces customer travel and effort.":
        "يقلل من تنقل المتعامل والجهد المبذول.",
    "Reduces delay and manual follow-up.":
        "يقلل من التأخير والمتابعة اليدوية.",
    "Reduces manual handling and handoff effort.":
        "يقلل من المعالجة اليدوية وجهد التحويل.",
    "Reduces repeated customer or employee effort.":
        "يقلل من تكرار الجهد على المتعامل أو الموظف.",
    "Retain the approval if legally or operationally required; otherwise simplify it.":
        "الإبقاء على الموافقة إذا كانت مطلوبة قانونياً أو تشغيلياً، وإلا فتبسيطها.",
    "Reuse the previously captured information where permitted.":
        "إعادة استخدام المعلومات التي تم جمعها مسبقاً حيثما كان ذلك مسموحاً.",
    "The current journey includes a physical branch visit.":
        "تتضمن الرحلة الحالية زيارة فرع فعلية.",
    "The journey appears to repeat information entry.":
        "يبدو أن الرحلة تكرر إدخال المعلومات.",
    "The journey contains a manual operational action that should be assessed for automation.":
        "تتضمن الرحلة إجراءً تشغيلياً يدوياً ينبغي تقييمه لأتمتته.",

    # ---------------------------------------------------------------
    # agents/standards_agent.py - "why it applies" fallback reasons
    # ---------------------------------------------------------------
    "A complete redesigned service must include an exception and human handoff path.":
        "يجب أن تتضمن الخدمة المعاد تصميمها مساراً للاستثناء والتحويل البشري.",
    "Applicable to the service journey.":
        "ينطبق على رحلة الخدمة.",
    "Approval points exist in the journey.":
        "توجد نقاط موافقة ضمن الرحلة.",
    "Every complete journey must end with a clear result and an objection or correction path.":
        "يجب أن تنتهي كل رحلة كاملة بنتيجة واضحة ومسار للاعتراض أو التصحيح.",
    "Manual or repeated administrative work exists in the current journey.":
        "توجد أعمال إدارية يدوية أو متكررة في الرحلة الحالية.",
    "The assistant must understand intent and permitted context before planning execution.":
        "يجب أن يفهم المساعد النية والسياق المسموح به قبل التخطيط للتنفيذ.",
    "The journey contains approval or customer-control considerations.":
        "تتضمن الرحلة اعتبارات موافقة أو تحكّم من المتعامل.",
    "The journey contains manual work, dependencies, or waiting.":
        "تتضمن الرحلة أعمالاً يدوية أو تبعيات أو فترات انتظار.",
    "The journey must be designed around the customer's intended outcome.":
        "يجب أن تُصمَّم الرحلة حول النتيجة المقصودة للمتعامل.",
    "The journey must start from the intended outcome rather than a service form.":
        "يجب أن تبدأ الرحلة من النتيجة المقصودة بدلاً من نموذج الخدمة.",
    "The redesigned service requires a baseline and measurable impact indicators before launch.":
        "تتطلب الخدمة المعاد تصميمها خط أساس ومؤشرات أثر قابلة للقياس قبل الإطلاق.",
    "The service contains information or data collection that should be checked for reuse and duplication.":
        "تتضمن الخدمة جمع معلومات أو بيانات ينبغي مراجعتها من حيث إعادة الاستخدام والتكرار.",
    "The service crosses multiple systems, actors, or waiting points.":
        "تمتد الخدمة عبر عدة أنظمة أو جهات أو نقاط انتظار.",
    "The service includes direct customer interaction.":
        "تتضمن الخدمة تفاعلاً مباشراً مع المتعامل.",
    "The service must define exception and handoff behaviour.":
        "يجب أن تحدد الخدمة سلوك الاستثناء والتحويل.",
    "The supplied journey contains a payment or fee requirement.":
        "تتضمن الرحلة المقدَّمة متطلب دفع أو رسوم.",

    # ---------------------------------------------------------------
    # core/standards_catalog.py - title / requirement / measurable_test
    # ---------------------------------------------------------------
    "Outcome Before Procedure":
        "النتيجة أولاً قبل الإجراء",
    "The customer should express the desired outcome rather than being required to identify the exact government service, procedure, or channel.":
        "يجب أن يعبّر المتعامل عن النتيجة المطلوبة بدلاً من إلزامه بتحديد الخدمة الحكومية أو الإجراء أو القناة بدقة.",
    "The journey can begin from the customer's intended outcome without requiring knowledge of the internal service structure.":
        "يمكن أن تبدأ الرحلة من النتيجة المقصودة للمتعامل دون الحاجة لمعرفة البنية الداخلية للخدمة.",

    "Burden Shifts to the Assistant":
        "انتقال العبء إلى المساعد",
    "The assistant should collect and connect available information instead of requiring unnecessary administrative work or repeated data entry.":
        "يجب أن يقوم المساعد بجمع وربط المعلومات المتاحة بدلاً من إلزام المتعامل بأعمال إدارية غير ضرورية أو إعادة إدخال البيانات.",
    "Customers are not required to repeat information already available and permitted for reuse.":
        "لا يُطلب من المتعاملين تكرار معلومات متاحة بالفعل ومسموح بإعادة استخدامها.",

    "Natural Language as Primary Interface":
        "اللغة الطبيعية كواجهة أساسية",
    "The customer should be able to communicate naturally without understanding complex government structures, menus, forms, or technical terminology.":
        "يجب أن يتمكن المتعامل من التواصل بشكل طبيعي دون الحاجة لفهم الهياكل الحكومية المعقدة أو القوائم أو النماذج أو المصطلحات التقنية.",
    "A customer can request the intended outcome using natural language.":
        "يمكن للمتعامل طلب النتيجة المقصودة باستخدام اللغة الطبيعية.",

    "Customer Control":
        "تحكّم المتعامل",
    "The customer must understand what the assistant is doing and must be able to approve, reject, pause, or stop actions when appropriate.":
        "يجب أن يفهم المتعامل ما يقوم به المساعد، وأن يكون قادراً على الموافقة أو الرفض أو الإيقاف المؤقت أو إلغاء الإجراءات عند الحاجة.",
    "Required consent and control points are visible in the journey.":
        "نقاط الموافقة والتحكم المطلوبة ظاهرة بوضوح ضمن الرحلة.",

    "Continuous Experience":
        "تجربة متواصلة",
    "The experience should remain continuous across relevant channels and touchpoints without forcing the customer to restart unnecessarily.":
        "يجب أن تظل التجربة متواصلة عبر القنوات ونقاط التواصل ذات الصلة دون إجبار المتعامل على البدء من جديد دون داعٍ.",
    "Context and information continue across systems, channels, and employees where permitted.":
        "يستمر السياق والمعلومات عبر الأنظمة والقنوات والموظفين حيثما كان ذلك مسموحاً.",

    "Exceptions Are Designed":
        "الاستثناءات مصمَّمة مسبقاً",
    "The journey must account for exceptions, failures, delays, objections, and cases requiring human intervention.":
        "يجب أن تراعي الرحلة الاستثناءات والأعطال والتأخيرات والاعتراضات والحالات التي تتطلب تدخلاً بشرياً.",
    "Important exception and human-handoff paths are defined.":
        "مسارات الاستثناء والتحويل إلى موظف بشري محددة بوضوح.",

    "Journey Start":
        "بداية الرحلة",
    "The journey starts from a natural-language outcome request, or from a clear proactive need, without requiring the customer to know the service name.":
        "تبدأ الرحلة من طلب نتيجة بلغة طبيعية أو من احتياج استباقي واضح، دون الحاجة لمعرفة المتعامل باسم الخدمة.",
    "The initial request is treated as an outcome and not as an administrative customer step.":
        "يُعامَل الطلب الأولي كنتيجة مقصودة وليس كخطوة إدارية على المتعامل.",

    "Understand Intent and Context":
        "فهم النية والسياق",
    "The assistant understands the intended outcome and uses the permitted customer context before choosing the service path.":
        "يفهم المساعد النتيجة المقصودة ويستخدم سياق المتعامل المسموح به قبل تحديد مسار الخدمة.",
    "Only one targeted clarification is requested when the available context is genuinely insufficient.":
        "لا يُطلب سوى استيضاح واحد محدد عندما يكون السياق المتاح غير كافٍ فعلياً.",

    "Complete Information":
        "اكتمال المعلومات",
    "Request only necessary information that is not already available through permitted government data sources.":
        "لا يُطلب سوى المعلومات الضرورية غير المتاحة أصلاً عبر مصادر البيانات الحكومية المسموح بها.",
    "Repeated information collection is avoided.":
        "يتم تجنّب تكرار جمع المعلومات.",

    "Determine Journey and Approvals":
        "تحديد الرحلة والموافقات",
    "Determine required actions, dependencies and approvals, and avoid unnecessary approvals.":
        "تحديد الإجراءات والتبعيات والموافقات المطلوبة، وتجنّب الموافقات غير الضرورية.",
    "Each approval has a clear reason and unnecessary approvals are not introduced.":
        "لكل موافقة سبب واضح، ولا يتم استحداث موافقات غير ضرورية.",

    "Execution and Continuity":
        "التنفيذ والاستمرارية",
    "Eligible actions should be executed through government systems without unnecessary customer intervention or manual information transfer.":
        "يجب تنفيذ الإجراءات المؤهلة عبر الأنظمة الحكومية دون تدخل غير ضروري من المتعامل أو نقل يدوي للمعلومات.",
    "Manual transfers, unnecessary waiting and repeated follow-up are minimized.":
        "يتم تقليل عمليات النقل اليدوي والانتظار غير الضروري والمتابعة المتكررة.",

    "Exceptions and Human Handoff":
        "الاستثناءات والتحويل البشري",
    "When the assistant cannot continue, the case should be transferred to a human with the relevant context.":
        "عندما لا يستطيع المساعد المتابعة، يجب تحويل الحالة إلى موظف بشري مع السياق ذي الصلة.",
    "Human handoff does not require the customer to restart or repeat information.":
        "لا يتطلب التحويل البشري من المتعامل البدء من جديد أو تكرار المعلومات.",

    "Payment Through UAE Government Payment":
        "الدفع عبر منظومة الدفع الحكومي الإماراتي",
    "When payment is required, the assistant presents the fees and beneficiary clearly, obtains explicit consent, and completes the payment through the approved UAE government payment journey.":
        "عند الحاجة للدفع، يعرض المساعد الرسوم والمستفيد بوضوح، ويحصل على موافقة صريحة، ويُتم الدفع عبر منظومة الدفع الحكومي الإماراتي المعتمدة.",
    "Payment does not require a branch visit or a separate customer-operated journey, and failed or incomplete payments have a recovery path.":
        "لا يتطلب الدفع زيارة فرع أو رحلة منفصلة يديرها المتعامل، وتتوفر آلية معالجة للمدفوعات الفاشلة أو غير المكتملة.",

    "Result, Objection and Customer Pulse":
        "النتيجة والاعتراض ونبض المتعامل",
    "The assistant delivers a clear result and provides a direct path to ask, correct, object or request a human from the same experience.":
        "يقدّم المساعد نتيجة واضحة ويوفر مساراً مباشراً للاستفسار أو التصحيح أو الاعتراض أو طلب التحدث إلى موظف من ضمن التجربة نفسها.",
    "The result, effective date, document location, next action and objection path are visible to the customer.":
        "تظهر للمتعامل النتيجة وتاريخ السريان وموقع المستند والإجراء التالي ومسار الاعتراض.",

    "Testing, Measurement and Improvement":
        "الاختبار والقياس والتحسين",
    "The target journey is tested with real users and its customer effort, completion, trust, exceptions and outcomes are measured against a baseline.":
        "يتم اختبار الرحلة المستهدفة مع مستخدمين حقيقيين، وقياس جهد المتعامل ومعدل الإتمام والثقة والاستثناءات والنتائج مقارنة بخط أساس.",
    "A baseline and auditable impact indicators are included in the redesign output.":
        "يتضمن مخرج إعادة التصميم خط أساس ومؤشرات أثر قابلة للتدقيق.",

    # ---------------------------------------------------------------
    # agents/step_compliance_agent.py
    # ---------------------------------------------------------------
    "A customer-provided document exists in the current journey.":
        "يوجد مستند مقدَّم من المتعامل في الرحلة الحالية.",
    "A manual verification activity exists, but no technical or policy evidence confirms safe automated verification.":
        "يوجد نشاط تحقق يدوي، لكن لا يوجد دليل تقني أو سياسي يؤكد إمكانية التحقق الآلي الآمن.",
    "A previous step already contains the":
        "خطوة سابقة تتضمن بالفعل",
    "Assess system-assisted verification and retain human review where required.":
        "تقييم إمكانية التحقق بمساعدة النظام مع الإبقاء على المراجعة البشرية عند الحاجة.",
    "Automate objective checks and transfer only sensitive, exceptional or authority-limited cases to a human with full context.":
        "أتمتة الفحوصات الموضوعية وتحويل الحالات الحساسة أو الاستثنائية أو المقيّدة بالصلاحية فقط إلى موظف بشري مع كامل السياق.",
    "Automatically issue the payment request when required conditions are satisfied.":
        "إصدار طلب الدفع تلقائياً عند استيفاء الشروط المطلوبة.",
    "Compare package price, benefits and fit, recommend one, and let the customer select or change it.":
        "مقارنة سعر الباقة ومزاياها وملاءمتها، والتوصية بواحدة، والسماح للمتعامل باختيارها أو تغييرها.",
    "Complete the action through a PROPOSED approved digital integration and route only genuine exceptions to an assisted channel.":
        "إتمام الإجراء عبر تكامل رقمي معتمد مقترح، وتحويل الاستثناءات الحقيقية فقط إلى قناة مُساعَدة.",
    "Continue monitoring the dependency automatically and resume processing when it is resolved.":
        "الاستمرار في مراقبة التبعية تلقائياً واستئناف المعالجة عند حلّها.",
    "Deliver or notify the customer of the service outcome through a permitted digital channel where feasible.":
        "تسليم نتيجة الخدمة أو إشعار المتعامل بها عبر قناة رقمية مسموح بها حيثما أمكن.",
    "Document upload is administrative customer work. The target journey retrieves or verifies the document from an authorized source, asking the customer only when it is genuinely unavailable.":
        "رفع المستندات هو عمل إداري على المتعامل. تقوم الرحلة المستهدفة باسترجاع أو التحقق من المستند من مصدر معتمد، وتطلبه من المتعامل فقط عند عدم توفره فعلياً.",
    "Document verification may be necessary, but the supplied evidence does not establish whether it can be fully automated or must remain a controlled human check.":
        "قد يكون التحقق من المستند ضرورياً، لكن الأدلة المقدَّمة لا تحدد ما إذا كان يمكن أتمتته بالكامل أو يجب أن يبقى فحصاً بشرياً منضبطاً.",
    "Embed the necessary approval in the assistant's plan with action, data and cost clearly identified.":
        "إدراج الموافقة اللازمة ضمن خطة المساعد مع تحديد الإجراء والبيانات والتكلفة بوضوح.",
    "Human intervention should remain available where automation cannot safely continue.":
        "يجب أن يظل التدخل البشري متاحاً في الحالات التي لا يمكن فيها للأتمتة الاستمرار بأمان.",
    "Issue and deliver the service result digitally, with correction, objection and human-help paths.":
        "إصدار نتيجة الخدمة وتسليمها رقمياً، مع توفير مسارات للتصحيح والاعتراض وطلب مساعدة بشرية.",
    "Manual transfers and repeated follow-up should be minimized.":
        "يجب تقليل عمليات النقل اليدوي والمتابعة المتكررة.",
    "Necessary information may be requested when required and not already available.":
        "يمكن طلب المعلومات الضرورية عند الحاجة وعدم توفرها مسبقاً.",
    "Orchestrate this activity through the assistant and route only genuine exceptions to a human with the complete context.":
        "تنسيق هذا النشاط عبر المساعد وتحويل الاستثناءات الحقيقية فقط إلى موظف بشري مع كامل السياق.",
    "Package selection remains a customer control point, while the assistant performs comparison and recommendation.":
        "يبقى اختيار الباقة نقطة تحكم للمتعامل، بينما يقوم المساعد بالمقارنة والتوصية.",
    "Pass the previously captured":
        "تمرير ما تم جمعه مسبقاً من",
    "Payment authorization remains with the customer, but it is merged into the unified journey after the assistant shows the complete editable plan, fees and beneficiary.":
        "تبقى صلاحية اعتماد الدفع مع المتعامل، لكنها تُدمَج ضمن الرحلة الموحدة بعد أن يعرض المساعد الخطة الكاملة القابلة للتعديل والرسوم والمستفيد.",
    "Prepare the transaction and show fees and beneficiary. The customer authorizes and pays; the assistant verifies the result and follows up on failure or incomplete debit.":
        "تجهيز المعاملة وعرض الرسوم والمستفيد. يقوم المتعامل بالاعتماد والدفع، ويتحقق المساعد من النتيجة ويتابع حالات الفشل أو الخصم غير المكتمل.",
    "Recommend the best-fit option in the pre-payment plan and let the customer change it through Edit.":
        "التوصية بأنسب خيار ضمن خطة ما قبل الدفع، والسماح للمتعامل بتغييره عبر التعديل.",
    "Repeated information entry creates unnecessary customer or employee effort.":
        "يؤدي تكرار إدخال المعلومات إلى جهد غير ضروري على المتعامل أو الموظف.",
    "Retrieve or verify the required document from an authorized source; request it only as an explained exception when unavailable.":
        "استرجاع المستند المطلوب أو التحقق منه من مصدر معتمد، وطلبه فقط كاستثناء موضّح عند عدم توفره.",
    "Reuse permitted government data and request only the single genuinely missing item with its reason.":
        "إعادة استخدام البيانات الحكومية المسموح بها وطلب العنصر الناقص فعلياً فقط مع ذكر السبب.",
    "Reuse the previously captured information through the existing service context.":
        "إعادة استخدام المعلومات التي تم جمعها مسبقاً من خلال سياق الخدمة الحالي.",
    "Synchronize the Compliance result automatically with the licensing system.":
        "مزامنة نتيجة الامتثال تلقائياً مع نظام التراخيص.",
    "Synchronize the result automatically with CRM.":
        "مزامنة النتيجة تلقائياً مع نظام إدارة علاقات العملاء.",
    "Synchronize this specific service update automatically with the relevant system.":
        "مزامنة هذا التحديث الخاص بالخدمة تلقائياً مع النظام ذي الصلة.",
    "The approval requirement is preserved as a specific control point, but it must not remain a separate customer or routing journey step.":
        "يتم الإبقاء على متطلب الموافقة كنقطة تحكم محددة، لكن يجب ألا تبقى خطوة منفصلة على المتعامل أو ضمن مسار التوجيه.",
    "The assistant should orchestrate the normal path. Human judgement remains an exception or controlled subtask and receives the complete case context.":
        "يجب أن يدير المساعد المسار الطبيعي، بينما يبقى التقدير البشري استثناءً أو مهمة فرعية منضبطة تحصل على كامل سياق الحالة.",
    "The assistant should recommend this preference from permitted context and show it inside the editable plan instead of requiring a separate customer step.":
        "يجب أن يوصي المساعد بهذا التفضيل من السياق المسموح به ويعرضه ضمن الخطة القابلة للتعديل بدلاً من إلزام المتعامل بخطوة منفصلة.",
    "The current journey contains a manual information-transfer activity.":
        "تتضمن الرحلة الحالية نشاط نقل معلومات يدوياً.",
    "The current journey contains a physical branch visit.":
        "تتضمن الرحلة الحالية زيارة فرع فعلية.",
    "The current journey contains a waiting point.":
        "تتضمن الرحلة الحالية نقطة انتظار.",
    "The customer-facing outcome is necessary, but delivery should be automated or digital where the service and policy permit.":
        "النتيجة الظاهرة للمتعامل ضرورية، لكن يجب أن يكون التسليم آلياً أو رقمياً حيثما تسمح الخدمة والسياسة بذلك.",
    "The exact implementation needs validation, but the current activity must be absorbed into the assistant-orchestrated target journey instead of being copied into the future happy path.":
        "يحتاج التنفيذ الدقيق إلى تحقق، لكن يجب استيعاب النشاط الحالي ضمن الرحلة المستهدفة التي يديرها المساعد بدلاً من نسخه إلى المسار المستقبلي المثالي.",
    "The information may be required, but collection must shift to permitted context and data sources instead of a separate customer entry step.":
        "قد تكون المعلومة مطلوبة، لكن يجب أن ينتقل جمعها إلى السياق ومصادر البيانات المسموح بها بدلاً من خطوة إدخال منفصلة على المتعامل.",
    "The journey begins from the customer's intended outcome.":
        "تبدأ الرحلة من النتيجة المقصودة للمتعامل.",
    "The payment instruction is necessary, but it should be generated automatically when the service reaches the payment stage.":
        "تعليمات الدفع ضرورية، لكن يجب أن تُولَّد تلقائياً عند وصول الخدمة إلى مرحلة الدفع.",
    "The physical visit is administrative customer work. The target Agentic journey completes the underlying action digitally; unavailable integration becomes an exception path.":
        "الزيارة الفعلية هي عمل إداري على المتعامل. تُتم الرحلة الوكيلة المستهدفة الإجراء الأساسي رقمياً، ويصبح غياب التكامل مساراً استثنائياً.",
    "The service already contains a digital payment stage.":
        "تتضمن الخدمة بالفعل مرحلة دفع رقمية.",
    "The service must provide a clear customer-visible outcome.":
        "يجب أن توفر الخدمة نتيجة واضحة وظاهرة للمتعامل.",
    "The service result is required, but issuance and delivery should be system-executed in the happy path.":
        "نتيجة الخدمة مطلوبة، لكن يجب أن يتم إصدارها وتسليمها آلياً عبر النظام ضمن المسار المثالي.",
    "The step exists in the supplied current journey.":
        "الخطوة موجودة ضمن الرحلة الحالية المقدَّمة.",
    "The supplied service explicitly contains an approval dependency.":
        "تتضمن الخدمة المقدَّمة صراحةً تبعية موافقة.",
    "The supplied service journey explicitly requires customer payment.":
        "تتطلب رحلة الخدمة المقدَّمة صراحةً دفعاً من المتعامل.",
    "The underlying business update may be required, but the manual system entry should be automated or system-assisted where feasible.":
        "قد يكون تحديث النظام الأساسي مطلوباً، لكن يجب أتمتة الإدخال اليدوي في النظام أو مساعدته حيثما أمكن.",
    "This is a manual internal information handoff. The handoff should use a controlled digital workflow where feasible.":
        "هذا تحويل معلومات داخلي يدوي. يجب أن يستخدم التحويل سير عمل رقمياً منضبطاً حيثما أمكن.",
    "This is a valid service initiation step representing the customer's intended outcome.":
        "هذه خطوة بدء صالحة للخدمة تمثل النتيجة المقصودة للمتعامل.",
    "This is an objective data or eligibility check. The assistant should perform it through permitted sources and send only conflicts or sensitive cases to a human with the full context.":
        "هذا فحص موضوعي للبيانات أو الأهلية. يجب أن يقوم المساعد بتنفيذه عبر المصادر المسموح بها، وإحالة حالات التعارض أو الحساسية فقط إلى موظف بشري مع كامل السياق.",
    "This step explicitly repeats information that has already been captured earlier in the journey.":
        "تكرر هذه الخطوة صراحةً معلومات تم جمعها مسبقاً في وقت سابق من الرحلة.",
    "Transfer the case or result digitally with the existing service context.":
        "نقل الحالة أو النتيجة رقمياً مع سياق الخدمة الحالي.",
    "Update the application status automatically when the preceding service event is completed.":
        "تحديث حالة الطلب تلقائياً عند اكتمال الحدث السابق للخدمة.",
    "Verify the data and eligibility automatically through authorized sources; route exceptions to a human with full context.":
        "التحقق من البيانات والأهلية تلقائياً عبر مصادر معتمدة، وتحويل الاستثناءات إلى موظف بشري مع كامل السياق.",
    "Waiting is not customer work and should not be represented as an active service step.":
        "الانتظار ليس عملاً على المتعامل ولا ينبغي تمثيله كخطوة خدمة نشطة.",
    "to the relevant system through a PROPOSED digital integration or system-assisted transfer.":
        "إلى النظام ذي الصلة عبر تكامل رقمي مقترح أو نقل بمساعدة النظام.",
    "was already captured earlier in the journey. The business activity may still be required, but manual re-entry should be avoided.":
        "تم جمعها بالفعل في وقت سابق من الرحلة. قد يظل النشاط التجاري مطلوباً، لكن يجب تجنّب إعادة الإدخال اليدوي.",

    # ---------------------------------------------------------------
    # agents/validation_agent.py
    # ---------------------------------------------------------------
    "Add a clear customer-visible service outcome.":
        "إضافة نتيجة خدمة واضحة وظاهرة للمتعامل.",
    "Add a reason to every changed step.":
        "إضافة سبب لكل خطوة تم تغييرها.",
    "Add a structured exception path with trigger, action and an applicable government standard.":
        "إضافة مسار استثناء منظّم يتضمن المُحفِّز والإجراء والمعيار الحكومي المنطبق.",
    "Automate or system-assist the CRM update.":
        "أتمتة أو مساعدة تحديث نظام إدارة علاقات العملاء (CRM).",
    "Build an outcome-level Agentic journey and merge current activities into fewer assistant-owned stages instead of copying one future step per current step.":
        "بناء رحلة وكيلة على مستوى النتيجة ودمج الأنشطة الحالية في عدد أقل من المراحل التي يديرها المساعد بدلاً من نسخ خطوة مستقبلية لكل خطوة حالية.",
    "Confirmed duplicate-data entry still exists in the future journey.":
        "تم تأكيد وجود تكرار في إدخال البيانات ضمن الرحلة المستقبلية.",
    "Current approvals were removed without supporting evidence.":
        "تمت إزالة موافقات حالية دون دليل داعم.",
    "Current documents were removed without supporting evidence.":
        "تمت إزالة مستندات حالية دون دليل داعم.",
    "Every future step must have a clear name.":
        "يجب أن يكون لكل خطوة مستقبلية اسم واضح.",
    "Every removed step must include step, reason and standard_id.":
        "يجب أن تتضمن كل خطوة محذوفة: الخطوة والسبب ومعرّف المعيار.",
    "Explain why every removed step was removed.":
        "توضيح سبب حذف كل خطوة.",
    "Further reduce unnecessary manual work, duplicate data, waiting or handoffs.":
        "زيادة تقليل الأعمال اليدوية غير الضرورية أو تكرار البيانات أو الانتظار أو التحويلات.",
    "Future journey does not clearly end with a customer-visible result.":
        "لا تنتهي الرحلة المستقبلية بوضوح بنتيجة ظاهرة للمتعامل.",
    "Future journey is empty.":
        "الرحلة المستقبلية فارغة.",
    "Future service has no valid exception / human-handoff path.":
        "لا تحتوي الخدمة المستقبلية على مسار استثناء / تحويل بشري صالح.",
    "Identify the proposed integrations required to support automation.":
        "تحديد التكاملات المقترحة اللازمة لدعم الأتمتة.",
    "Link every changed step to an applicable government standard.":
        "ربط كل خطوة تم تغييرها بمعيار حكومي منطبق.",
    "Link every removed step to the government standard supporting removal.":
        "ربط كل خطوة محذوفة بالمعيار الحكومي الذي يدعم حذفها.",
    "Manual CRM updating still exists in the future journey.":
        "لا يزال التحديث اليدوي لنظام CRM موجوداً في الرحلة المستقبلية.",
    "Manual email handoff still exists in the future journey.":
        "لا يزال التحويل اليدوي عبر البريد الإلكتروني موجوداً في الرحلة المستقبلية.",
    "Merge duplicate future actions into one step.":
        "دمج الإجراءات المستقبلية المكررة في خطوة واحدة.",
    "Metrics are not valid for scoring.":
        "المؤشرات غير صالحة للتقييم.",
    "Preserve documents unless evidence supports removal.":
        "الإبقاء على المستندات ما لم يدعم الدليل حذفها.",
    "Preserve required approvals unless evidence supports simplification.":
        "الإبقاء على الموافقات المطلوبة ما لم يدعم الدليل تبسيطها.",
    "Remove repeated information entry or reuse the existing data.":
        "إزالة تكرار إدخال المعلومات أو إعادة استخدام البيانات الموجودة.",
    "Replace manual email handoff with a controlled system workflow.":
        "استبدال التحويل اليدوي عبر البريد الإلكتروني بسير عمل نظامي منضبط.",
    "Resolve REVIEW steps before claiming full service compliance.":
        "معالجة الخطوات قيد المراجعة قبل اعتماد التوافق الكامل للخدمة.",
    "Return a complete future journey.":
        "إرجاع رحلة مستقبلية كاملة.",
    "Return a valid structured future journey.":
        "إرجاع رحلة مستقبلية منظّمة وصالحة.",
    "Return every future step as a structured object.":
        "إرجاع كل خطوة مستقبلية ككائن منظّم.",
    "Return removed steps as structured records.":
        "إرجاع الخطوات المحذوفة كسجلات منظّمة.",
    "Shift form filling, document upload, travel, data entry and follow-up to the assistant. Keep outcome request and explicit consent as control points, not administrative steps.":
        "نقل تعبئة النماذج ورفع المستندات والتنقل وإدخال البيانات والمتابعة إلى المساعد، مع الإبقاء على طلب النتيجة والموافقة الصريحة كنقاط تحكم لا كخطوات إدارية.",
    "The future journey contains duplicate future actions.":
        "تحتوي الرحلة المستقبلية على إجراءات مستقبلية مكررة.",
    "The proposed happy path does not consolidate the current journey.":
        "المسار المقترح المثالي لا يقوم بدمج الرحلة الحالية.",
    "The redesigned service automates work across multiple dependencies but identifies no proposed integration.":
        "تقوم الخدمة المعاد تصميمها بأتمتة العمل عبر عدة تبعيات دون تحديد أي تكامل مقترح.",
    "Use only CUSTOMER, SYSTEM or HUMAN step types.":
        "استخدام أنواع الخطوات: عميل أو نظام أو بشري فقط.",
    "Use only applicable approved government standard IDs.":
        "استخدام معرّفات المعايير الحكومية المعتمدة المنطبقة فقط.",
    "Use only approved applicable standards when removing steps.":
        "استخدام المعايير المعتمدة المنطبقة فقط عند حذف الخطوات.",
    "Use only supported change_type values.":
        "استخدام قيم نوع التغيير المدعومة فقط.",
    "Zero Bureaucracy score is below the minimum redesign threshold.":
        "نتيجة انعدام البيروقراطية أقل من الحد الأدنى المطلوب لإعادة التصميم.",
    "administrative customer step(s) remain in the target journey.":
        "لا تزال هناك خطوة/خطوات إدارية على المتعامل ضمن الرحلة المستهدفة.",
    "is not linked to a government standard.":
        "غير مرتبطة بمعيار حكومي.",
    "service result becomes available":
        "أصبحت نتيجة الخدمة متاحة",
    "step(s) still require human review.":
        "لا تزال هناك خطوة/خطوات تتطلب مراجعة بشرية.",
}


def _translate_string(value):
    return EN_TO_AR.get(value, value)


def translate_error(message, lang):
    """Translate a single top-level error/status message."""
    if lang != "ar":
        return message
    return _translate_string(message)


def translate_result(data, lang):
    """Recursively translate every string in `data` that matches a
    known English template phrase, when lang == "ar". Any string not
    found in EN_TO_AR (free text typed by the customer, or content
    JourneyBuilderAgent already generated directly in Arabic) is left
    untouched. When lang != "ar" the data is returned unchanged.
    """

    if lang != "ar":
        return data

    if isinstance(data, dict):
        return {key: translate_result(value, lang) for key, value in data.items()}

    if isinstance(data, list):
        return [translate_result(item, lang) for item in data]

    if isinstance(data, str):
        return _translate_string(data)

    return data
