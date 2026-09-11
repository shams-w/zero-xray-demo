import { useEffect, useMemo, useState } from "react";
import { useLanguage } from "../i18n/useLanguage";
import { translateApiError } from "../i18n/apiErrors";
import {
  approveBlueprint,
  getServiceContext,
  publishAgent,
  publishBlueprint,
} from "../api";
import { deriveCapabilitySummary } from "./agentCapabilitySummary";

const COPY = {
  en: {
    back: "Back to Blueprint",
    badge: "AGENT BUILDER · SANDBOX",
    title: "Build this service Agent",
    subtitle:
      "ZERO X-RAY turns the redesigned service into a reusable Agent configuration and sandbox runtime.",
    build: "BUILD THIS AGENT",
    building: "Building Agent...",
    created: "AGENT CREATED ✓",
    test: "TEST AGENT",
    publish: "PUBLISH SERVICE",
    published: "SERVICE PUBLISHED ✓",
    copy: "COPY SERVICE LINK",
    copied: "LINK COPIED ✓",
    open: "OPEN SERVICE",
    config: "VIEW CONFIGURATION",
    hideConfig: "HIDE CONFIGURATION",
    readiness: "Agent Readiness",
    decisions: "Customer Decisions",
    documents: "Required Documents",
    actions: "Agent Actions",
    tools: "Required Tools",
    consent: "Consent Points",
    integrations: "Integration status",
    unknown: "Unknown requirements",
    sandbox: "Sandbox",
    required: "Integration Required",
    environment: "Environment",
    agentId: "Agent ID",
    service: "Service",
    noItems: "UNKNOWN",
    note:
      "Demo only. No external government system or payment gateway is executed.",
    steps: [
      "Creating Service Schema",
      "Mapping Customer Decisions",
      "Building Document Schema",
      "Mapping Agent Actions",
      "Selecting Required Tools",
      "Creating Consent Rules",
      "Building Exception Handling",
      "Creating Agent Configuration",
      "Running Validation",
    ],
  },

  ar: {
    back: "العودة إلى مخطط الخدمة",
    badge: "منشئ الوكيل · بيئة تجريبية",
    title: "إنشاء وكيل لهذه الخدمة",
    subtitle:
      "يحوّل ZERO X-RAY الخدمة بعد تصفيرها إلى تعريف وكيل قابل لإعادة الاستخدام والتجربة داخل البيئة التجريبية.",
    build: "إنشاء وكيل لهذه الخدمة",
    building: "جارٍ إنشاء الوكيل...",
    created: "تم إنشاء الوكيل ✓",
    test: "اختبار الوكيل",
    publish: "نشر الخدمة",
    published: "تم نشر الخدمة بنجاح ✓",
    copy: "نسخ رابط الخدمة",
    copied: "تم نسخ الرابط ✓",
    open: "فتح الخدمة",
    config: "عرض إعدادات الوكيل",
    hideConfig: "إخفاء إعدادات الوكيل",
    readiness: "جاهزية الوكيل",
    decisions: "قرارات المتعامل",
    documents: "المستندات المطلوبة",
    actions: "إجراءات الوكيل",
    tools: "الأدوات المطلوبة",
    consent: "نقاط الموافقة",
    integrations: "حالة التكامل",
    unknown: "المتطلبات غير المعروفة",
    sandbox: "بيئة تجريبية",
    required: "يتطلب تكاملًا",
    environment: "البيئة",
    agentId: "معرّف الوكيل",
    service: "الخدمة",
    noItems: "غير معروف",
    note:
      "للعرض التجريبي فقط. لا يتم تنفيذ أي نظام حكومي خارجي أو بوابة دفع حقيقية.",
    steps: [
      "إنشاء مخطط الخدمة",
      "تحديد قرارات المتعامل",
      "بناء مخطط المستندات",
      "تحديد إجراءات الوكيل",
      "اختيار الأدوات المطلوبة",
      "إنشاء قواعد الموافقة",
      "بناء معالجة الاستثناءات",
      "إنشاء إعدادات الوكيل",
      "تشغيل التحقق النهائي",
    ],
  },
};

function textOf(v) {
  if (typeof v === "string") return v;
  if (!v) return "";

  return (
    v.title ||
    v.label ||
    v.name ||
    v.description ||
    v.action ||
    v.step ||
    v.customer_action ||
    v.assistant_action ||
    ""
  );
}

function uniq(items) {
  return [
    ...new Set(
      items
        .map(textOf)
        .map((v) => String(v || "").trim())
        .filter(Boolean)
    ),
  ];
}

function deriveConfig(result) {
  const exp = result?.redesign?.agent_execution_explanation || {};
  const future = result?.redesign?.future_steps || [];
  const execution = exp?.execution_plan || [];
  const integrations = result?.redesign?.required_integrations || [];
  const decisions = uniq(exp?.customer_only_actions || []);
  const actions = uniq(execution.length ? execution : future);
  const source = JSON.stringify(result || {}).toLowerCase();

  const documents = [];

  const knownDocs = [
    ["emirates id", "Emirates ID"],
    ["trade licence", "Trade Licence"],
    ["trade license", "Trade Licence"],
    ["invoice", "Invoice"],
    ["receipt", "Receipt"],
    ["passport", "Passport"],
    ["photo", "Personal Photo"],
    ["tracking", "Tracking Number"],
  ];

  knownDocs.forEach(([needle, label]) => {
    if (source.includes(needle)) {
      documents.push(label);
    }
  });

  const tools = uniq(integrations);

  if (source.includes("payment") || source.includes("fee")) {
    tools.push("Payment");
  }

  if (source.includes("identity") || source.includes("uae pass")) {
    tools.push("Identity Verification");
  }

  if (source.includes("complaint") || source.includes("case")) {
    tools.push("Case Management");
  }

  if (source.includes("notification") || source.includes("notify")) {
    tools.push("Notification");
  }

  const consent = decisions.filter((x) =>
    /approv|consent|pay|confirm|موافق|دفع|تأكيد/i.test(x)
  );

  if (!consent.length && decisions.length) {
    consent.push(decisions[decisions.length - 1]);
  }

  const id = `AGT-DEMO-${String(
    Math.abs(hashCode(result?.service_name || "service")) % 1000
  ).padStart(3, "0")}`;

  const unknowns = (result?.validation?.issues || []).length;

  const base =
    90 -
    Math.min(unknowns * 6, 30) -
    Math.min(tools.length * 2, 12);

  return {
    agent_id: id,
    agent_name: `${result?.service_name || "Generated Service"} Agent`,
    service_name: result?.service_name || "UNKNOWN",
    goal:
      exp?.summary ||
      result?.service?.description ||
      "UNKNOWN",
    environment: "SANDBOX",
    customer_decisions: decisions,
    required_documents: uniq(documents),
    agent_actions: actions,
    consent_points: uniq(consent),
    required_tools: uniq(tools),
    exceptions: uniq(
      (result?.redesign?.review_steps || []).map(textOf)
    ),
    payment: {
      required: /payment|fee|aed|دفع|رسوم/i.test(source),
    },
    readiness: Math.max(58, Math.min(94, base)),
    unknown_requirements: unknowns,
  };
}

function hashCode(str) {
  let h = 0;

  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h) + str.charCodeAt(i) | 0;
  }

  return h;
}

export default function BuildAgentPage({
  result,
  onBack,
  onTestAgent,
}) {
  const { lang, t } = useLanguage();

  const copy = COPY[lang] || COPY.en;

  const config = useMemo(
    () => deriveConfig(result),
    [result]
  );

  const capabilitySummary = useMemo(
    () => deriveCapabilitySummary(result),
    [result]
  );

  const [built, setBuilt] = useState(false);
  const [building, setBuilding] = useState(false);
  const [doneCount, setDoneCount] = useState(0);

  const [published, setPublished] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState("");
  const [publishedAgent, setPublishedAgent] = useState(null);

  const [copied, setCopied] = useState(false);
  const [showConfig, setShowConfig] = useState(false);

  const [serviceContext, setServiceContext] = useState(null);

  useEffect(() => {
    if (!result?.service_id) return;

    getServiceContext(result.service_id)
      .then(setServiceContext)
      .catch(() => setServiceContext(null));
  }, [result?.service_id]);

  async function build() {
    setBuilding(true);
    setDoneCount(0);

    for (let i = 0; i < copy.steps.length; i++) {
      await new Promise((r) => setTimeout(r, 260));
      setDoneCount(i + 1);
    }

    setBuilding(false);
    setBuilt(true);
  }

  async function publish() {
    if (!result?.blueprint_id || publishing) return;

    const hasConnectedApi =
      serviceContext?.integrations?.some(
        (integration) =>
          String(integration?.status || "").toUpperCase() === "CONNECTED"
      ) ||
      Number(capabilitySummary?.connected_apis || 0) > 0;

    if (!hasConnectedApi) {
      setPublishError(
        lang === "ar"
          ? "يجب ربط API بحالة CONNECTED قبل نشر الخدمة."
          : "A CONNECTED API is required before publishing the service."
      );

      return;
    }

    setPublishing(true);
    setPublishError("");

    try {
      let agent;

      if (result.blueprint_status !== "PUBLISHED") {
        try {
          await approveBlueprint(result.blueprint_id);
        } catch (approveError) {
          if (
            !/approved|published|transition/i.test(
              approveError?.message || ""
            )
          ) {
            throw approveError;
          }
        }

        try {
          await publishBlueprint(result.blueprint_id);
        } catch (publishBlueprintError) {
          if (
            !/published|transition/i.test(
              publishBlueprintError?.message || ""
            )
          ) {
            throw publishBlueprintError;
          }
        }
      }

      agent = await publishAgent(
        result.blueprint_id,
        config.agent_name
      );

      setPublishedAgent(agent);
      setPublished(true);
    } catch (requestError) {
      setPublishError(
        translateApiError(requestError.message, lang) ||
          (lang === "ar"
            ? "تعذر نشر الخدمة. تحقق من صلاحية الجلسة ثم حاول مرة أخرى."
            : "Could not publish the service. Check your session and try again.")
      );
    } finally {
      setPublishing(false);
    }
  }

  const demoUrl = publishedAgent
    ? `${window.location.origin}/service/${publishedAgent.published_slug}`
    : "";

  async function copyLink() {
    if (!demoUrl) return;

    try {
      await navigator.clipboard.writeText(demoUrl);
    } catch {}

    setCopied(true);

    setTimeout(() => {
      setCopied(false);
    }, 1800);
  }

  function openPublished() {
    if (demoUrl) {
      window.open(
        demoUrl,
        "_blank",
        "noopener,noreferrer"
      );
    }
  }

  function testAgent() {
    if (onTestAgent) {
      onTestAgent();
    }
  }

  const buildButtonStyle = {
    border: "0",
    borderRadius: "18px",
    padding: "16px 30px",
    minWidth: "240px",
    background:
      "linear-gradient(135deg, #7048ff 0%, #4f46ff 55%, #3c2ed0 100%)",
    color: "#fff",
    fontSize: "18px",
    fontWeight: 800,
    letterSpacing: lang === "ar" ? "0" : ".02em",
    cursor: building ? "wait" : "pointer",
    boxShadow:
      "0 14px 34px rgba(91, 70, 255, .28), inset 0 1px 0 rgba(255,255,255,.22)",
    transition:
      "transform .2s ease, box-shadow .2s ease, filter .2s ease",
  };

  const testButtonStyle = {
    border: "1px solid rgba(104,71,255,.22)",
    borderRadius: "16px",
    padding: "14px 24px",
    background:
      "linear-gradient(135deg, #6b49ff 0%, #4f46ff 100%)",
    color: "#fff",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow:
      "0 10px 28px rgba(91,70,255,.20)",
  };

  const publishButtonStyle = {
    border: "1px solid #bcefdc",
    borderRadius: "16px",
    padding: "14px 24px",
    background:
      published
        ? "#e9fff6"
        : "#f3fff9",
    color: "#15966c",
    fontWeight: 800,
    cursor: "pointer",
  };

  return (
    <div className="ab-page">
      <button
        className="ab-back"
        onClick={onBack}
        type="button"
      >
        ← {copy.back}
      </button>

      <section className="ab-hero">
        <span className="ab-badge">
          {copy.badge}
        </span>

        <h2>{copy.title}</h2>

        <p>{copy.subtitle}</p>

        {!built && (
          <button
            className="ab-build-button"
            onClick={build}
            disabled={building}
            type="button"
            style={buildButtonStyle}
            onMouseEnter={(e) => {
              if (!building) {
                e.currentTarget.style.transform =
                  "translateY(-2px) scale(1.01)";

                e.currentTarget.style.boxShadow =
                  "0 18px 40px rgba(91, 70, 255, .34)";
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform =
                "translateY(0) scale(1)";

              e.currentTarget.style.boxShadow =
                "0 14px 34px rgba(91, 70, 255, .28), inset 0 1px 0 rgba(255,255,255,.22)";
            }}
          >
            {building
              ? copy.building
              : copy.build}
          </button>
        )}
      </section>

      {(building || built) && (
        <section className="ab-builder-card">
          <div className="ab-builder-head">
            <strong>
              {building
                ? copy.building
                : copy.created}
            </strong>

            <span>
              {doneCount}/{copy.steps.length}
            </span>
          </div>

          <div className="ab-steps">
            {copy.steps.map((step, i) => (
              <div
                className={`ab-step ${
                  i < doneCount
                    ? "done"
                    : i === doneCount && building
                    ? "active"
                    : ""
                }`}
                key={step}
              >
                <span>
                  {i < doneCount
                    ? "✓"
                    : String(i + 1).padStart(2, "0")}
                </span>

                <strong>
                  {step}
                </strong>

                <em>
                  {i < doneCount
                    ? "Complete"
                    : i === doneCount && building
                    ? "Processing..."
                    : "Queued"}
                </em>
              </div>
            ))}
          </div>
        </section>
      )}

      {built && (
        <>
          <section className="ab-blueprint">
            <div className="ab-blueprint-top">
              <div>
                <span>
                  {copy.service}
                </span>

                <h3>
                  {config.service_name}
                </h3>
              </div>

              <div className="ab-id">
                <span>
                  {copy.agentId}
                </span>

                <strong>
                  {config.agent_id}
                </strong>

                <small>
                  {copy.environment}:{" "}
                  {config.environment}
                </small>
              </div>
            </div>

            <div className="ab-readiness">
              <div>
                <span>
                  {copy.readiness}
                </span>

                <strong>
                  {serviceContext
                    ? serviceContext.agent_readiness
                    : config.readiness}
                  %
                </strong>
              </div>

              <div className="ab-progress">
                <i
                  style={{
                    width: `${
                      serviceContext
                        ? serviceContext.agent_readiness
                        : config.readiness
                    }%`,
                  }}
                />
              </div>
            </div>

            <div className="ab-grid">
              <Info
                title={copy.decisions}
                items={config.customer_decisions}
                empty={copy.noItems}
              />

              <Info
                title={copy.documents}
                items={config.required_documents}
                empty={copy.noItems}
              />

              <Info
                title={copy.actions}
                items={config.agent_actions}
                empty={copy.noItems}
              />

              <Info
                title={copy.consent}
                items={config.consent_points}
                empty={copy.noItems}
              />
            </div>

            <div className="ab-tools">
              <h4>
                {copy.integrations}
              </h4>

              {serviceContext?.integrations?.length ? (
                serviceContext.integrations.map((tool) => (
                  <div key={tool.id}>
                    <strong>
                      {tool.name}
                    </strong>

                    <span
                      className={
                        tool.status === "CONNECTED"
                          ? "connected"
                          : tool.status === "SANDBOX"
                          ? "sandbox"
                          : "required"
                      }
                    >
                      {tool.status === "CONNECTED"
                        ? lang === "ar"
                          ? "متصل"
                          : "Connected"
                        : tool.status === "SANDBOX"
                        ? copy.sandbox
                        : lang === "ar"
                        ? "تكامل مطلوب"
                        : "Integration Required"}
                    </span>
                  </div>
                ))
              ) : config.required_tools.length ? (
                config.required_tools.map((tool, i) => (
                  <div key={`${tool}-${i}`}>
                    <strong>
                      {tool}
                    </strong>

                    <span className="required">
                      {copy.required}
                    </span>
                  </div>
                ))
              ) : (
                <p>
                  {copy.noItems}
                </p>
              )}
            </div>

            <div className="ab-stats">
              <span>
                {copy.decisions}
                <b>
                  {config.customer_decisions.length}
                </b>
              </span>

              <span>
                {copy.actions}
                <b>
                  {config.agent_actions.length}
                </b>
              </span>

              <span>
                {copy.documents}
                <b>
                  {config.required_documents.length}
                </b>
              </span>

              <span>
                {copy.unknown}
                <b>
                  {config.unknown_requirements}
                </b>
              </span>
            </div>

            {capabilitySummary &&
              t?.buildAgentCapabilitySummary && (
                <div className="ab-capability-summary">
                  <h4>
                    {
                      t.buildAgentCapabilitySummary
                        .title
                    }
                  </h4>

                  <div className="ab-stats">
                    <span>
                      {
                        t.buildAgentCapabilitySummary
                          .usedDataSources
                      }
                      <b>
                        {
                          capabilitySummary.used_data_sources
                        }
                      </b>
                    </span>

                    <span>
                      {
                        t.buildAgentCapabilitySummary
                          .connectedApis
                      }
                      <b>
                        {
                          capabilitySummary.connected_apis
                        }
                      </b>
                    </span>

                    <span>
                      {
                        t.buildAgentCapabilitySummary
                          .automatedSteps
                      }
                      <b>
                        {
                          capabilitySummary.automated_steps
                        }
                        /
                        {
                          capabilitySummary.total_steps
                        }
                      </b>
                    </span>

                    <span>
                      {
                        t.buildAgentCapabilitySummary
                          .customerSteps
                      }
                      <b>
                        {
                          capabilitySummary.customer_steps
                        }
                      </b>
                    </span>

                    <span>
                      {
                        t.buildAgentCapabilitySummary
                          .manualSteps
                      }
                      <b>
                        {
                          capabilitySummary.manual_steps
                        }
                      </b>
                    </span>

                    <span>
                      {
                        t.buildAgentCapabilitySummary
                          .integrationRequired
                      }
                      <b>
                        {
                          capabilitySummary.integration_required
                        }
                      </b>
                    </span>
                  </div>
                </div>
              )}

            <p className="ab-note">
              {copy.note}
            </p>

            <div className="ab-actions">
              <button
                className="ab-secondary"
                onClick={() =>
                  setShowConfig((v) => !v)
                }
                type="button"
              >
                {showConfig
                  ? copy.hideConfig
                  : copy.config}
              </button>

              <button
                className="ab-primary"
                onClick={testAgent}
                type="button"
                style={testButtonStyle}
              >
                {copy.test}
              </button>

              <button
                className="ab-secondary"
                onClick={publish}
                type="button"
                style={publishButtonStyle}
                disabled={publishing}
              >
                {publishing
                  ? copy.building
                  : published
                  ? copy.published
                  : copy.publish}
              </button>
            </div>

            {publishError && (
              <p
                className="ab-note"
                style={{
                  color: "#c0392b",
                }}
              >
                {publishError}
              </p>
            )}

            {showConfig && (
              <pre className="ab-config">
                {JSON.stringify(
                  config,
                  null,
                  2
                )}
              </pre>
            )}
          </section>

          {published && (
            <section className="ab-publish-card">
              <span className="ab-published">
                {copy.published}
              </span>

              <code>
                {demoUrl}
              </code>

              <div>
                <button
                  onClick={copyLink}
                  type="button"
                >
                  {copied
                    ? copy.copied
                    : copy.copy}
                </button>

                <button
                  onClick={openPublished}
                  type="button"
                >
                  {copy.open}
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Info({
  title,
  items,
  empty,
}) {
  return (
    <article className="ab-info">
      <div>
        <h4>
          {title}
        </h4>

        <b>
          {items.length}
        </b>
      </div>

      {items.length ? (
        <ul>
          {items
            .slice(0, 8)
            .map((x, i) => (
              <li key={`${x}-${i}`}>
                {x}
              </li>
            ))}
        </ul>
      ) : (
        <p>
          {empty}
        </p>
      )}
    </article>
  );
}
