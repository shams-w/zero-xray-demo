import { useState } from "react";
import { useLanguage } from "../i18n/useLanguage";
import IntelligencePanel from "./IntelligencePanel";


const COPY = {
  en: {
    eyebrow: "SERVICE BLUEPRINT",
    needsReview: "Needs review",
    ready: "Ready",
    draft: "Draft",
    approved: "Approved",
    published: "Published",

    summary: (current, future) =>
      `The service was redesigned from ${current} current steps into ${future} outcome-focused steps.`,

    blueprintStatus: "Blueprint status",
    approve: "Approve & publish",
    launch: "Experience the live Agent",
    buildAgent: "BUILD THIS AGENT",

    overview: "Overview",
    journey: "Journey",
    technical: "Technical details",

    journeySteps: "Journey steps",
    customerControls: "Customer control points",
    automation: "Automation",
    zeroBureaucracy: "Zero Bureaucracy",
    reduction: "reduction",

    whatChanged: "What changed for the customer?",
    outcomeFallback:
      "The Agent takes over administrative work while the customer keeps control over choices, consent and payment only when required.",

    customerActions: "The customer’s only actions",
    customerActionsHint:
      "These are control points, not administrative work.",
    noCustomerActions: "No customer actions were identified.",

    readiness: "Decision readiness",
    validationReady:
      "The Blueprint passed the final validation checks.",
    validationReview:
      "Resolve the following points before treating the Blueprint as production-ready.",

    compliance: "Compliance",
    feasibility: "Feasibility",
    unresolved: "Unresolved reviews",
    noIssues: "No unresolved validation issues.",
    issues: (count) =>
      `${count} issue${count === 1 ? "" : "s"}`,

    beforeAction: (context) =>
      context === "PAYMENT"
        ? "What the customer sees before payment"
        : context === "SUBMISSION"
          ? "What the customer sees before case submission"
          : "What the customer sees before a binding action",

    proposedJourney: "Proposed Agent journey",
    proposedHint:
      "The future journey is shown first because it is the most important decision.",

    currentJourney: "View the current journey",
    currentHint:
      "For reference only — collapsed to keep the page simple.",

    executionPlan: "View the detailed Agent execution plan",

    evidenceTitle: "Government-guide evidence",
    evidenceHint:
      "The retrieved evidence remains available for audit without overwhelming the main page.",

    complianceTitle: "Step-by-step compliance",
    complianceHint:
      "Open this only when a reviewer needs the decision and evidence for every original step.",

    changesTitle: "Change register",
    impactTitle: "Transformation impact",
    ownershipTitle: "Customer-to-Agent ownership transfer",

    removed: "Confirmed removals",
    merged: "Consolidated steps",
    integrations: "Proposed integrations",

    currentStep: "Current customer step",
    agentAction: "Agent action",

    standard: "Government standard",
    evidence: "Evidence",
    proposedAction: "Proposed action",
    protected: "Human-protected step",

    assistantDoes: "What the Agent does",
    customerRole: "Customer role",
    completionEvidence: "Completion evidence",

    keep: "Keep",
    automate: "Automate",
    remove: "Remove",
    review: "Review",

    customerEffort: "Customer effort reduction",
    duplicateElimination: "Duplicate elimination",
    handoffReduction: "Handoff reduction",
    waitingReduction: "Waiting reduction",
    manualReduction: "Manual work reduction",

    steps: (count) =>
      `${count} step${count === 1 ? "" : "s"}`,

    items: (count) =>
      `${count} item${count === 1 ? "" : "s"}`,

    empty: "Nothing to show.",

    statuses: {
      PASS: "Pass",
      FAIL: "Fail",
      PARTIAL: "Partial",
      UNKNOWN: "Unknown",
      CRITICAL: "Critical",
      HIGH: "High",
      MEDIUM: "Medium",
      LOW: "Low",

      KEEP: "Keep",
      AUTOMATE: "Automate",
      REMOVE: "Remove",
      REVIEW: "Review",
      MERGE: "Merge",
      MERGED: "Merged",

      DRAFT: "Draft",
      APPROVED: "Approved",
      PUBLISHED: "Published",
      PROPOSED: "Proposed",

      SYSTEM: "System",
      AUTOMATED: "Automated",
      NEW: "New",

      REQUIREMENT: "Protected requirement",
      HUMAN: "Human decision",
      AS_IS: "Keep as-is",
    },
  },

  ar: {
    eyebrow: "مخطط الخدمة",
    needsReview: "تحتاج مراجعة",
    ready: "جاهزة",
    draft: "مسودة",
    approved: "معتمدة",
    published: "منشورة",

    summary: (current, future) =>
      `أُعيد تصميم الخدمة من ${current} خطوة حالية إلى ${future} خطوات تركز على النتيجة.`,

    blueprintStatus: "حالة مخطط الخدمة",
    approve: "اعتماد ونشر",
    launch: "تجربة رحلة المساعد",
    buildAgent: "إنشاء وكيل لهذه الخدمة",

    overview: "الخلاصة",
    journey: "الرحلة",
    technical: "التفاصيل الفنية",

    journeySteps: "خطوات الرحلة",
    customerControls: "نقاط تحكم المتعامل",
    automation: "الأتمتة",
    zeroBureaucracy: "صفر بيروقراطية",
    reduction: "تقليل",

    whatChanged: "ما الذي تغير للمتعامل؟",
    outcomeFallback:
      "يتولى المساعد العمل الإداري، بينما يحتفظ المتعامل بالاختيارات والموافقة والدفع عند الحاجة.",

    customerActions: "الإجراءات الوحيدة للمتعامل",
    customerActionsHint:
      "هذه نقاط تحكم وليست عملًا إداريًا.",
    noCustomerActions: "لا توجد إجراءات مطلوبة من المتعامل.",

    readiness: "جاهزية القرار",
    validationReady:
      "اجتاز مخطط الخدمة اختبارات التحقق النهائية.",
    validationReview:
      "راجع النقاط التالية قبل اعتبار مخطط الخدمة جاهزًا للإنتاج.",

    compliance: "الامتثال",
    feasibility: "قابلية التنفيذ",
    unresolved: "المراجعات غير المحسومة",
    noIssues: "لا توجد ملاحظات تحقق غير محسومة.",
    issues: (count) => `${count} ملاحظة`,

    beforeAction: (context) =>
      context === "PAYMENT"
        ? "ما الذي يراه المتعامل قبل الدفع؟"
        : context === "SUBMISSION"
          ? "ما الذي يراه المتعامل قبل إرسال الحالة؟"
          : "ما الذي يراه المتعامل قبل الإجراء الملزم؟",

    proposedJourney: "رحلة المساعد المقترحة",
    proposedHint:
      "نعرض رحلة المستقبل أولًا لأنها القرار الأهم.",

    currentJourney: "عرض الرحلة الحالية",
    currentHint:
      "للمرجع فقط — مخفية افتراضيًا للحفاظ على بساطة الصفحة.",

    executionPlan: "عرض خطة تنفيذ المساعد التفصيلية",

    evidenceTitle: "أدلة الدليل الحكومي",
    evidenceHint:
      "تظل الأدلة متاحة للتدقيق دون أن تشتت صفحة القرار.",

    complianceTitle: "التزام كل خطوة",
    complianceHint:
      "افتحي هذا القسم فقط عندما يحتاج المراجع إلى قرار ودليل كل خطوة أصلية.",

    changesTitle: "سجل التغييرات",
    impactTitle: "أثر التحول",
    ownershipTitle: "انتقال العمل من المتعامل إلى المساعد",

    removed: "الحذف المؤكد",
    merged: "الخطوات المدمجة",
    integrations: "التكاملات المقترحة",

    currentStep: "خطوة المتعامل الحالية",
    agentAction: "إجراء المساعد",

    standard: "المعيار الحكومي",
    evidence: "الدليل",
    proposedAction: "الإجراء المقترح",
    protected: "خطوة محمية بقرار بشري",

    assistantDoes: "ما الذي يفعله المساعد؟",
    customerRole: "دور المتعامل",
    completionEvidence: "دليل الإتمام",

    keep: "إبقاء",
    automate: "أتمتة",
    remove: "حذف",
    review: "مراجعة",

    customerEffort: "تقليل جهد المتعامل",
    duplicateElimination: "إزالة التكرار",
    handoffReduction: "تقليل التسليم بين الجهات",
    waitingReduction: "تقليل الانتظار",
    manualReduction: "تقليل العمل اليدوي",

    // Arabic numeral-noun agreement: plain "N خطوة" is grammatically wrong
    // for 3-10 (needs the plural "خطوات"). Standard Arabic counting rule:
    // 0 -> "لا توجد خطوات", 1 -> "خطوة واحدة" (singular), 2 -> "خطوتان"
    // (dual), 3-10 -> plural "خطوات", 11+ -> singular "خطوة" again.
    steps: (count) => {
      if (count === 0) return "لا توجد خطوات";
      if (count === 1) return "خطوة واحدة";
      if (count === 2) return "خطوتان";
      if (count >= 3 && count <= 10) return `${count} خطوات`;
      return `${count} خطوة`;
    },
    items: (count) => `${count} عنصر`,

    empty: "لا توجد عناصر للعرض.",

    statuses: {
      PASS: "ناجح",
      FAIL: "غير مجتاز",
      PARTIAL: "جزئي",
      UNKNOWN: "غير معروف",
      CRITICAL: "حرجة",
      HIGH: "عالية",
      MEDIUM: "متوسطة",
      LOW: "منخفضة",

      KEEP: "إبقاء",
      AUTOMATE: "أتمتة",
      REMOVE: "حذف",
      REVIEW: "مراجعة",
      MERGE: "دمج",
      MERGED: "مدمجة",

      DRAFT: "مسودة",
      APPROVED: "معتمدة",
      PUBLISHED: "منشورة",
      PROPOSED: "مقترح",

      SYSTEM: "النظام",
      AUTOMATED: "مؤتمتة",
      NEW: "جديدة",

      REQUIREMENT: "متطلب محمي",
      HUMAN: "قرار بشري",
      AS_IS: "تبقى كما هي",
    },
  },
};


function getStatusClass(value) {
  const status = String(value || "").toUpperCase();

  if (
    status === "PASS" ||
    status === "KEEP" ||
    status === "PUBLISHED" ||
    status === "APPROVED"
  ) {
    return "sd-status sd-status-good";
  }

  if (
    status === "FAIL" ||
    status === "REMOVE" ||
    status === "CRITICAL"
  ) {
    return "sd-status sd-status-bad";
  }

  if (
    status === "PARTIAL" ||
    status === "REVIEW" ||
    status === "DRAFT"
  ) {
    return "sd-status sd-status-warning";
  }

  if (
    status === "AUTOMATE" ||
    status === "AUTOMATED" ||
    status === "SYSTEM"
  ) {
    return "sd-status sd-status-info";
  }

  return "sd-status sd-status-purple";
}


function SummaryMetric({
  title,
  value,
  helper,
  color = "",
}) {
  return (
    <article className={`sd-metric ${color}`}>
      <span>{title}</span>
      <strong>{value}</strong>
      {helper && <small>{helper}</small>}
    </article>
  );
}


function Disclosure({
  title,
  hint,
  count,
  children,
}) {
  return (
    <details className="sd-disclosure">
      <summary>
        <span className="sd-chevron">⌄</span>

        <div>
          <strong>{title}</strong>
          {hint && <small>{hint}</small>}
        </div>

        {count && <b>{count}</b>}
      </summary>

      <div className="sd-disclosure-content">
        {children}
      </div>
    </details>
  );
}


function ProgressRow({
  label,
  value,
}) {
  const hasValue = value !== null && value !== undefined && Number.isFinite(Number(value));
  const safeValue = Math.max(
    0,
    Math.min(100, hasValue ? Number(value) : 0)
  );

  return (
    <div className="sd-progress">
      <div>
        <span>{label}</span>
        <strong>{hasValue ? `${safeValue}%` : "—"}</strong>
      </div>

      <div className="sd-progress-track">
        <span
          style={{
            width: `${safeValue}%`,
          }}
        />
      </div>
    </div>
  );
}


function Dashboard({
  result,
  onApprovePublish,
  onLaunchAgent,
  onBuildAgent,
  actionBusy = false,
  actionError = "",
}) {
  const { lang } = useLanguage();
  const copy = COPY[lang] || COPY.en;

  const [activeTab, setActiveTab] =
    useState("overview");

  const metrics =
    result?.metrics || {};

  const validation =
    result?.validation || {};

  const decisionSummary =
    result?.step_compliance_summary || {};

  const assessments =
    result?.step_compliance?.step_assessment || [];

  const currentSteps =
    result?.service?.steps || [];

  const futureSteps =
    result?.redesign?.future_steps || [];

  const removedSteps =
    result?.redesign?.removed_steps || [];

  const mergedSteps =
    result?.redesign?.merged_steps || [];

  const reviewSteps =
    result?.redesign?.review_steps || [];

  const integrations =
    result?.redesign?.required_integrations || [];

  const agentExplanation =
    result?.redesign?.agent_execution_explanation || {};

  const customerActions =
    agentExplanation?.customer_only_actions || [];

  const preActionPreview =
    agentExplanation?.pre_action_preview ||
    agentExplanation?.pre_payment_preview ||
    {};

  const executionPlan =
    agentExplanation?.execution_plan || [];

  const ownershipTransfers =
    agentExplanation?.ownership_transfers || [];

  const issues =
    validation?.issues || [];

  const guideEvidence =
    result?.relevant_standards?.retrieval_evidence || [];

  const currentCount =
    metrics?.current?.steps ??
    currentSteps.length;

  const futureCount =
    metrics?.future?.steps ??
    futureSteps.length;

  const controlCount =
    metrics?.future?.customer_control_points ??
    customerActions.length;

  const stepReduction =
    metrics?.reduction?.steps_percent ?? 0;

  const automation =
    metrics?.transformation
      ?.automation_rate_percent ?? 0;

  const zeroScore =
    metrics?.zero_bureaucracy_score ?? 0;

  const validationStatus =
    String(
      validation?.status || "UNKNOWN"
    ).toUpperCase();

  const blueprintStatus =
    String(
      result?.blueprint_status || "DRAFT"
    ).toUpperCase();

  const isPublished =
    blueprintStatus === "PUBLISHED";

  function statusLabel(value) {
    const normalized =
      String(
        value || "UNKNOWN"
      ).toUpperCase();

    return (
      copy.statuses[normalized] ||
      value ||
      copy.statuses.UNKNOWN
    );
  }

  const validationHeadline =
    validationStatus === "PASS"
      ? copy.ready
      : copy.needsReview;

  const tabs = [
    {
      id: "overview",
      label: copy.overview,
    },
    {
      id: "journey",
      label: copy.journey,
    },
    {
      id: "intelligence",
      label: "ZERO X-RAY Intelligence",
    },
    {
      id: "technical",
      label: copy.technical,
    },
  ];

  return (
    <div className="sd-page">

      <section className="sd-hero">

        <div className="sd-hero-copy">

          <div className="sd-hero-top">
            <span className="sd-kicker">
              {copy.eyebrow}
            </span>

            <span
              className={
                getStatusClass(
                  validationStatus
                )
              }
            >
              {validationHeadline}
            </span>
          </div>

          <h2>
            {
              result?.service_name ||
              "Service Analysis"
            }
          </h2>

          <p>
            {
              copy.summary(
                currentCount,
                futureCount
              )
            }
          </p>

          <div className="sd-blueprint-status">
            <span>
              {copy.blueprintStatus}
            </span>

            <strong
              className={
                getStatusClass(
                  blueprintStatus
                )
              }
            >
              {
                statusLabel(
                  blueprintStatus
                )
              }
            </strong>
          </div>

        </div>

        <div className="sd-hero-actions">

          <button
            className="sd-button sd-button-secondary"
            disabled={
              actionBusy ||
              isPublished
            }
            onClick={
              onApprovePublish
            }
            type="button"
          >
            {
              isPublished
                ? `✓ ${copy.published}`
                : copy.approve
            }
          </button>

          <button
            className="sd-button sd-button-secondary sd-build-agent-button"
            disabled={actionBusy}
            onClick={onBuildAgent}
            type="button"
          >
            ✦ {copy.buildAgent}
          </button>

          <button
            className="sd-button sd-button-primary"
            disabled={actionBusy}
            onClick={onLaunchAgent}
            type="button"
          >
            <span className="sd-live-dot" />
            {copy.launch}
          </button>

        </div>

        {
          actionError && (
            <p className="sd-action-error">
              {actionError}
            </p>
          )
        }

      </section>


      <section className="sd-metrics">

        <SummaryMetric
          title={copy.journeySteps}
          value={
            <>
              <i>{currentCount}</i>
              <em>→</em>
              {futureCount}
            </>
          }
          helper={
            `${stepReduction}% ${copy.reduction}`
          }
          color="purple"
        />

        <SummaryMetric
          title={copy.customerControls}
          value={controlCount}
          helper={
            copy.customerActionsHint
          }
        />

        <SummaryMetric
          title={copy.automation}
          value={`${automation}%`}
          color="blue"
        />

        <SummaryMetric
          title={copy.zeroBureaucracy}
          value={`${zeroScore}/100`}
          color="success"
        />

      </section>


      <nav
        className="sd-tabs"
        role="tablist"
      >
        {
          tabs.map(
            (tab) => (
              <button
                aria-selected={
                  activeTab === tab.id
                }
                className={
                  activeTab === tab.id
                    ? "active"
                    : ""
                }
                key={tab.id}
                onClick={
                  () =>
                    setActiveTab(
                      tab.id
                    )
                }
                role="tab"
                type="button"
              >
                {tab.label}
              </button>
            )
          )
        }
      </nav>


      {
        activeTab === "overview" && (

          <div className="sd-panel">

            <section className="sd-overview">

              <article className="sd-card">

                <span className="sd-kicker">
                  {copy.whatChanged}
                </span>

                <h3>
                  {
                    agentExplanation?.title ||
                    copy.whatChanged
                  }
                </h3>

                <p className="sd-card-description">
                  {
                    agentExplanation?.summary ||
                    copy.outcomeFallback
                  }
                </p>

                <div className="sd-section-heading">

                  <div>
                    <strong>
                      {copy.customerActions}
                    </strong>

                    <small>
                      {
                        copy.customerActionsHint
                      }
                    </small>
                  </div>

                  <b>
                    {controlCount}
                  </b>

                </div>

                <div className="sd-control-list">

                  {
                    customerActions.length > 0
                      ? customerActions.map(
                        (
                          action,
                          index
                        ) => (

                          <article
                            key={
                              action.code ||
                              index
                            }
                          >
                            <span>
                              {index + 1}
                            </span>

                            <div>
                              <strong>
                                {
                                  action.label
                                }
                              </strong>

                              <p>
                                {
                                  action
                                    .assistant_support
                                }
                              </p>
                            </div>
                          </article>
                        )
                      )
                      : (
                        <p className="sd-empty">
                          {
                            copy.noCustomerActions
                          }
                        </p>
                      )
                  }

                </div>

              </article>


              <article
                className={
                  `sd-card sd-validation ${validationStatus.toLowerCase()}`
                }
              >

                <div className="sd-validation-heading">

                  <div>
                    <span className="sd-kicker">
                      {copy.readiness}
                    </span>

                    <h3>
                      {
                        validationHeadline
                      }
                    </h3>
                  </div>

                  <span
                    className={
                      getStatusClass(
                        validationStatus
                      )
                    }
                  >
                    {
                      statusLabel(
                        validationStatus
                      )
                    }
                  </span>

                </div>

                <p className="sd-card-description">
                  {
                    validationStatus ===
                    "PASS"
                      ? copy.validationReady
                      : copy.validationReview
                  }
                </p>

                <div className="sd-score-grid">

                  <div>
                    <span>
                      {copy.compliance}
                    </span>

                    <strong>
                      {
                        validation
                          ?.compliance_score ??
                        0
                      }
                    </strong>
                  </div>

                  <div>
                    <span>
                      {copy.feasibility}
                    </span>

                    <strong>
                      {
                        validation
                          ?.feasibility_score ??
                        0
                      }
                    </strong>
                  </div>

                  <div>
                    <span>
                      {copy.unresolved}
                    </span>

                    <strong>
                      {
                        validation
                          ?.checks
                          ?.unresolved_review_steps ??
                        reviewSteps.length
                      }
                    </strong>
                  </div>

                </div>

                {
                  issues.length > 0
                    ? (
                      <div className="sd-issues">

                        <strong>
                          {
                            copy.issues(
                              issues.length
                            )
                          }
                        </strong>

                        {
                          issues.map(
                            (
                              issue,
                              index
                            ) => (

                              <div key={index}>

                                <span>
                                  {
                                    statusLabel(
                                      issue.severity
                                    )
                                  }
                                </span>

                                <p>
                                  {
                                    issue.issue
                                  }
                                </p>

                              </div>
                            )
                          )
                        }

                      </div>
                    )
                    : (
                      <div className="sd-validation-success">
                        {copy.noIssues}
                      </div>
                    )
                }

              </article>

            </section>


            {
              preActionPreview?.enabled && (

                <section className="sd-card sd-prepayment">

                  <div>
                    <span className="sd-kicker">
                      {copy.beforeAction(preActionPreview.context)}
                    </span>

                    <h3>
                      {
                        preActionPreview
                          .title
                      }
                    </h3>

                    <p>
                      {
                        preActionPreview
                          .description
                      }
                    </p>
                  </div>

                  <div className="sd-options">
                    {
                      (
                        preActionPreview
                          .options || []
                      ).map(
                        (
                          option,
                          index
                        ) => (
                          <span key={index}>
                            {option}
                          </span>
                        )
                      )
                    }
                  </div>

                </section>
              )
            }

          </div>
        )
      }


      {
        activeTab === "journey" && (

          <div className="sd-panel">

            <section className="sd-card">

              <div className="sd-section-heading">

                <div>
                  <span className="sd-kicker">
                    TO-BE
                  </span>

                  <h3>
                    {
                      copy.proposedJourney
                    }
                  </h3>

                  <small>
                    {
                      copy.proposedHint
                    }
                  </small>
                </div>

                <b>
                  {
                    copy.steps(
                      futureSteps.length
                    )
                  }
                </b>

              </div>

              <div className="sd-future-list">

                {
                  futureSteps.length > 0
                    ? futureSteps.map(
                      (
                        step,
                        index
                      ) => (

                        <article
                          key={
                            `${
                              step.step_number ||
                              index
                            }-${
                              step.name ||
                              "step"
                            }`
                          }
                        >

                          <span>
                            {
                              step.step_number ||
                              index + 1
                            }
                          </span>

                          <div>

                            <strong>
                              {step.name}
                            </strong>

                            {
                              step.action && (
                                <p>
                                  {
                                    step.action
                                  }
                                </p>
                              )
                            }

                            {
                              step
                                ?.customer_control_points
                                ?.length > 0 && (

                                <div className="sd-chips">
                                  {
                                    step
                                      .customer_control_points
                                      .map(
                                        (
                                          point,
                                          pointIndex
                                        ) => (
                                          <small
                                            key={
                                              pointIndex
                                            }
                                          >
                                            {point}
                                          </small>
                                        )
                                      )
                                  }
                                </div>
                              )
                            }

                            <div className="sd-meta">

                              {
                                step.type && (
                                  <span>
                                    {
                                      statusLabel(
                                        step.type
                                      )
                                    }
                                  </span>
                                )
                              }

                              {
                                step
                                  .change_type && (
                                  <span>
                                    {
                                      statusLabel(
                                        step
                                          .change_type
                                      )
                                    }
                                  </span>
                                )
                              }

                              {
                                step
                                  .standard_id && (
                                  <span>
                                    {
                                      step
                                        .standard_id
                                    }
                                  </span>
                                )
                              }

                            </div>

                          </div>

                        </article>
                      )
                    )
                    : (
                      <p className="sd-empty">
                        {copy.empty}
                      </p>
                    )
                }

              </div>

            </section>


            <Disclosure
              title={copy.currentJourney}
              hint={copy.currentHint}
              count={
                copy.steps(
                  currentSteps.length
                )
              }
            >
              <div className="sd-current-list">

                {
                  currentSteps.map(
                    (
                      step,
                      index
                    ) => (
                      <div key={index}>

                        <span>
                          {index + 1}
                        </span>

                        <p>
                          {step}
                        </p>

                      </div>
                    )
                  )
                }

              </div>
            </Disclosure>


            {
              executionPlan.length > 0 && (

                <Disclosure
                  title={
                    copy.executionPlan
                  }
                  count={
                    copy.steps(
                      executionPlan.length
                    )
                  }
                >

                  <div className="sd-execution-list">

                    {
                      executionPlan.map(
                        (
                          phase,
                          index
                        ) => (

                          <article
                            key={
                              phase
                                .phase_number ||
                              index
                            }
                          >

                            <div className="sd-execution-title">

                              <span>
                                {
                                  phase
                                    .phase_number ||
                                  index + 1
                                }
                              </span>

                              <strong>
                                {phase.title}
                              </strong>

                            </div>

                            <dl>

                              <div>
                                <dt>
                                  {
                                    copy
                                      .assistantDoes
                                  }
                                </dt>

                                <dd>
                                  {
                                    phase
                                      .assistant_does
                                  }
                                </dd>
                              </div>

                              <div>
                                <dt>
                                  {
                                    copy
                                      .customerRole
                                  }
                                </dt>

                                <dd>
                                  {
                                    phase
                                      .customer_role
                                  }
                                </dd>
                              </div>

                              <div>
                                <dt>
                                  {
                                    copy
                                      .completionEvidence
                                  }
                                </dt>

                                <dd>
                                  {
                                    phase
                                      .completion_evidence
                                  }
                                </dd>
                              </div>

                            </dl>

                          </article>
                        )
                      )
                    }

                  </div>

                </Disclosure>
              )
            }

          </div>
        )
      }


      {
        activeTab === "intelligence" && (
          <IntelligencePanel
            serviceId={result?.service_id}
            futureSteps={futureSteps}
            integrations={integrations}
          />
        )
      }


      {
        activeTab === "technical" && (

          <div className="sd-panel">

            <Disclosure
              title={
                copy.evidenceTitle
              }
              hint={
                copy.evidenceHint
              }
              count={
                copy.items(
                  guideEvidence.length
                )
              }
            >

              <div className="sd-evidence-grid">

                {
                  guideEvidence.length > 0
                    ? guideEvidence.map(
                      (item) => (

                        <article
                          key={
                            item.evidence_id
                          }
                        >

                          <div>
                            <strong>
                              {
                                item.evidence_id
                              }
                            </strong>

                            <small>
                              {
                                item
                                  .source_location
                              }
                            </small>
                          </div>

                          <p>
                            {item.text}
                          </p>

                          <span>
                            {
                              Math.round(
                                Number(
                                  item.score ||
                                  0
                                ) * 100
                              )
                            }%
                          </span>

                        </article>
                      )
                    )
                    : (
                      <p className="sd-empty">
                        {copy.empty}
                      </p>
                    )
                }

              </div>

            </Disclosure>


            <Disclosure
              title={
                copy.complianceTitle
              }
              hint={
                copy.complianceHint
              }
              count={
                copy.steps(
                  assessments.length
                )
              }
            >

              <div className="sd-decisions">

                <span>
                  {copy.keep} {
                    decisionSummary.keep ??
                    0
                  }
                </span>

                <span>
                  {copy.automate} {
                    decisionSummary
                      .automate ??
                    0
                  }
                </span>

                <span>
                  {copy.remove} {
                    decisionSummary.remove ??
                    0
                  }
                </span>

                <span>
                  {copy.review} {
                    decisionSummary.review ??
                    0
                  }
                </span>

              </div>


              <div className="sd-audit-list">

                {
                  assessments.map(
                    (item) => (

                      <details
                        className="sd-audit-step"
                        key={
                          item.step_number
                        }
                      >

                        <summary>

                          <b>
                            {
                              String(
                                item
                                  .step_number
                              ).padStart(
                                2,
                                "0"
                              )
                            }
                          </b>

                          <strong>
                            {
                              item.current_step
                            }
                          </strong>

                          <div>

                            <i
                              className={
                                getStatusClass(
                                  item.status
                                )
                              }
                            >
                              {
                                statusLabel(
                                  item.status
                                )
                              }
                            </i>

                            <i
                              className={
                                getStatusClass(
                                  item.decision
                                )
                              }
                            >
                              {
                                statusLabel(
                                  item.decision
                                )
                              }
                            </i>

                          </div>

                        </summary>


                        <div className="sd-audit-content">

                          <p>
                            {item.reason}
                          </p>

                          {
                            item
                              .human_constraint && (

                              <div className="sd-protected">

                                <span>
                                  🔒 {
                                    copy.protected
                                  }
                                </span>

                                <strong>
                                  {
                                    statusLabel(
                                      item
                                        .human_constraint
                                        .level
                                    )
                                  }
                                </strong>

                                {
                                  item
                                    .human_constraint
                                    .source_reference && (

                                    <small>
                                      {
                                        item
                                          .human_constraint
                                          .source_reference
                                      }
                                    </small>
                                  )
                                }

                              </div>
                            )
                          }

                          <dl>

                            <div>
                              <dt>
                                {copy.standard}
                              </dt>

                              <dd>
                                {
                                  item.standard_id ||
                                  "—"
                                }

                                {
                                  item.standard_title
                                    ? ` · ${item.standard_title}`
                                    : ""
                                }
                              </dd>
                            </div>

                            <div>
                              <dt>
                                {copy.evidence}
                              </dt>

                              <dd>
                                {
                                  item.evidence ||
                                  "—"
                                }
                              </dd>
                            </div>

                            {
                              item.replacement && (

                                <div>
                                  <dt>
                                    {
                                      copy
                                        .proposedAction
                                    }
                                  </dt>

                                  <dd>
                                    {
                                      item
                                        .replacement
                                    }
                                  </dd>
                                </div>
                              )
                            }

                          </dl>

                        </div>

                      </details>
                    )
                  )
                }

              </div>

            </Disclosure>


            <Disclosure
              title={
                copy.impactTitle
              }
            >

              <div className="sd-impact">

                <ProgressRow
                  label={
                    copy.customerEffort
                  }
                  value={
                    metrics
                      ?.transformation
                      ?.customer_effort_reduction_percent
                  }
                />

                <ProgressRow
                  label={
                    copy.automation
                  }
                  value={
                    metrics
                      ?.transformation
                      ?.automation_rate_percent
                  }
                />

                <ProgressRow
                  label={
                    copy
                      .duplicateElimination
                  }
                  value={
                    metrics
                      ?.transformation
                      ?.duplicate_elimination_percent
                  }
                />

                <ProgressRow
                  label={
                    copy
                      .handoffReduction
                  }
                  value={
                    metrics
                      ?.transformation
                      ?.handoff_reduction_percent
                  }
                />

                <ProgressRow
                  label={
                    copy.waitingReduction
                  }
                  value={
                    metrics
                      ?.transformation
                      ?.waiting_reduction_percent
                  }
                />

                <ProgressRow
                  label={
                    copy.manualReduction
                  }
                  value={
                    metrics
                      ?.reduction
                      ?.manual_actions_percent
                  }
                />

              </div>

            </Disclosure>


            <Disclosure
              title={
                copy.changesTitle
              }
              count={
                copy.items(
                  removedSteps.length +
                  mergedSteps.length +
                  integrations.length
                )
              }
            >

              <div className="sd-change-grid">

                <section>

                  <h4>
                    {copy.removed}
                  </h4>

                  {
                    removedSteps.length > 0
                      ? removedSteps.map(
                        (
                          item,
                          index
                        ) => (

                          <article key={index}>

                            <strong>
                              {item.step}
                            </strong>

                            <p>
                              {item.reason}
                            </p>

                            {
                              item.standard_id && (
                                <small>
                                  {
                                    item
                                      .standard_id
                                  }
                                </small>
                              )
                            }

                          </article>
                        )
                      )
                      : (
                        <p className="sd-empty">
                          {copy.empty}
                        </p>
                      )
                  }

                </section>


                <section>

                  <h4>
                    {copy.merged}
                  </h4>

                  {
                    mergedSteps.length > 0
                      ? mergedSteps.map(
                        (
                          item,
                          index
                        ) => (

                          <article key={index}>

                            <strong>
                              {item.from}
                            </strong>

                            <p>
                              → {item.into}
                            </p>

                            {
                              item.standard_id && (
                                <small>
                                  {
                                    item
                                      .standard_id
                                  }
                                </small>
                              )
                            }

                          </article>
                        )
                      )
                      : (
                        <p className="sd-empty">
                          {copy.empty}
                        </p>
                      )
                  }

                </section>


                <section>

                  <h4>
                    {copy.integrations}
                  </h4>

                  {
                    integrations.length > 0
                      ? integrations.map(
                        (
                          item,
                          index
                        ) => (

                          <article key={index}>

                            <strong>
                              {
                                typeof item ===
                                "string"
                                  ? item
                                  : item
                                    .description
                              }
                            </strong>

                            {
                              typeof item ===
                                "object" &&
                              item.supports
                                ?.length > 0 && (

                                <p>
                                  {
                                    item
                                      .supports
                                      .join(" · ")
                                  }
                                </p>
                              )
                            }

                            {
                              typeof item ===
                                "object" &&
                              item.status && (

                                <small>
                                  {
                                    statusLabel(
                                      item.status
                                    )
                                  }
                                </small>
                              )
                            }

                          </article>
                        )
                      )
                      : (
                        <p className="sd-empty">
                          {copy.empty}
                        </p>
                      )
                  }

                </section>

              </div>

            </Disclosure>


            {
              ownershipTransfers.length > 0 && (

                <Disclosure
                  title={
                    copy.ownershipTitle
                  }
                  count={
                    copy.items(
                      ownershipTransfers
                        .length
                    )
                  }
                >

                  <div className="sd-ownership">

                    {
                      ownershipTransfers.map(
                        (
                          transfer,
                          index
                        ) => (

                          <article
                            key={
                              transfer
                                .source_step_number ||
                              index
                            }
                          >

                            <div>
                              <small>
                                {
                                  copy
                                    .currentStep
                                }
                              </small>

                              <strong>
                                {
                                  transfer
                                    .source_step
                                }
                              </strong>
                            </div>

                            <span>
                              →
                            </span>

                            <div>
                              <small>
                                {
                                  copy
                                    .agentAction
                                }
                              </small>

                              <strong>
                                {
                                  transfer
                                    .assistant_action
                                }
                              </strong>

                              <p>
                                {transfer.how}
                              </p>
                            </div>

                          </article>
                        )
                      )
                    }

                  </div>

                </Disclosure>
              )
            }

          </div>
        )
      }

    </div>
  );
}


export default Dashboard;
