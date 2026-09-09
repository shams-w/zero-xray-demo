import { useMemo, useState, useEffect, useRef } from "react";
import LiveAgentPage from "./LiveAgentPage";
import { useLanguage } from "../i18n/useLanguage";
import { getPublicService } from "../api";



const DEMO_IDENTITY_PROFILES = [
  { name: "Ahmed Al Mansoori", emirates_id: "784-1995-1234567-1", email: "ahmed.almansoori@demo.ae", phone: "+971 50 123 4567", address: "Dubai, United Arab Emirates" },
  { name: "Fatima Al Nuaimi", emirates_id: "784-1998-7654321-2", email: "fatima.alnuaimi@demo.ae", phone: "+971 55 987 6543", address: "Abu Dhabi, United Arab Emirates" },
  { name: "Omar Al Suwaidi", emirates_id: "784-1992-4567890-3", email: "omar.alsuwaidi@demo.ae", phone: "+971 52 555 7812", address: "Sharjah, United Arab Emirates" },
  { name: "Mariam Al Mazrouei", emirates_id: "784-2000-3141592-4", email: "mariam.almazrouei@demo.ae", phone: "+971 54 321 9087", address: "Ajman, United Arab Emirates" },
  { name: "Saeed Al Ketbi", emirates_id: "784-1990-2718281-5", email: "saeed.alketbi@demo.ae", phone: "+971 56 246 8135", address: "Al Ain, United Arab Emirates" },
];

const SERVICE_NAME_PAIRS = [
  {
    ar: "خدمة إرسال شحنة دولية",
    en: "International Shipment Service",
    keys: ["خدمة إرسال شحنة دولية", "إرسال شحنة دولية", "international shipment", "international shipping"],
  },
  {
    ar: "استئجار صندوق بريد للأفراد",
    en: "Rent Individual P.O. Box",
    keys: ["استئجار صندوق بريد للأفراد", "صندوقي", "rent individual p.o. box", "individual po box"],
  },
  {
    ar: "تجديد صندوق بريد للأفراد",
    en: "Renew Individual P.O. Box",
    keys: ["تجديد صندوق بريد للأفراد", "renew individual p.o. box"],
  },
  {
    ar: "استئجار صندوق بريد للشركات",
    en: "Rent Corporate P.O. Box",
    keys: ["استئجار صندوق بريد للشركات", "rent corporate p.o. box", "corporate po box rent"],
  },
  {
    ar: "تجديد صندوق بريد للشركات",
    en: "Renew Corporate P.O. Box",
    keys: ["تجديد صندوق بريد للشركات", "renew corporate p.o. box", "corporate po box renewal"],
  },
  {
    ar: "إصدار ترخيص نشاط بريدي",
    en: "Postal Activity License Issuance",
    keys: ["إصدار ترخيص نشاط بريدي", "postal activity license issuance", "issue postal activity license"],
  },
  {
    ar: "تجديد ترخيص نشاط بريدي",
    en: "Postal Activity License Renewal",
    keys: ["تجديد ترخيص نشاط بريدي", "postal activity license renewal", "renew postal activity license"],
  },
  {
    ar: "خدمة الشكاوى",
    en: "Complaints Service",
    keys: ["خدمة الشكاوى", "شكوى", "شكاوى", "complaint", "complaints service"],
  },
  {
    ar: "خدمة الاستفسارات",
    en: "Inquiry Service",
    keys: ["خدمة الاستفسارات", "استفسار", "استفسارات", "inquiry", "information service"],
  },
];

function localizedServiceName(result, lang) {
  const explicitAr =
    result?.service_name_ar ||
    result?.service?.name_ar ||
    result?.service?.service_name_ar ||
    result?.redesign?.service_name_ar ||
    result?.redesign?.customer_plan?.service_name_ar;

  const explicitEn =
    result?.service_name_en ||
    result?.service?.name_en ||
    result?.service?.service_name_en ||
    result?.redesign?.service_name_en ||
    result?.redesign?.customer_plan?.service_name_en;

  if (lang === "ar" && explicitAr) return explicitAr;
  if (lang === "en" && explicitEn) return explicitEn;

  const original = String(result?.service_name || "").trim();
  const normalized = original.toLowerCase();

  const matched = SERVICE_NAME_PAIRS.find((item) =>
    item.keys.some((key) => normalized.includes(String(key).toLowerCase()))
  );

  if (matched) return lang === "ar" ? matched.ar : matched.en;

  // If the backend already supplied the correct language, keep it.
  return original || (lang === "ar" ? "الخدمة الرقمية" : "Digital Service");
}

function withLocalizedServiceName(result, lang) {
  if (!result) return result;

  const serviceName = localizedServiceName(result, lang);

  return {
    ...result,
    service_name: serviceName,
    service: result.service
      ? {
          ...result.service,
          name: serviceName,
          service_name: serviceName,
        }
      : result.service,
    redesign: result.redesign
      ? {
          ...result.redesign,
          customer_plan: result.redesign.customer_plan
            ? {
                ...result.redesign.customer_plan,
                service_name: serviceName,
              }
            : result.redesign.customer_plan,
        }
      : result.redesign,
  };
}

/*
  Small stylized "digital identity" fingerprint glyph used across the
  UAE PASS simulation screens below. This is a generic, abstract mark
  drawn from scratch for this sandbox demo, inspired only by the
  general concept of a fingerprint-based digital identity icon — it
  does not trace or reproduce any official logo artwork file.
*/
function IdentityFingerprintMark({ size = 40 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <path d="M18.5 24a5.5 5.5 0 0 1 11 0" stroke="#232a3d" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M14.5 24a9.5 9.5 0 0 1 19 0" stroke="#2b3348" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M10.5 24a13.5 13.5 0 0 1 27 0" stroke="#333c55" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M7 24a17 17 0 0 1 34 0" stroke="#3a4463" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M7.6 26.4a17 17 0 0 1 -1.1 -4.9" stroke="#16a394" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M40.4 26.4a17 17 0 0 0 1.1 -4.9" stroke="#e2574c" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="24" cy="24" r="2.8" fill="#232a3d" />
    </svg>
  );
}

export default function PublishedAgentPage({ tenantSlug, agentSlug }) {
  const { lang, toggleLang } = useLanguage();
  const isAr = lang === "ar";

  // Backend-persisted lookup (GET /service/{tenantSlug}/{agentSlug}),
  // NOT localStorage: this is what makes the published URL survive a
  // refresh and work from another browser/device. The endpoint
  // returns only the sanitized public subset of the analysis (see
  // core/agent_store.py:sanitize_for_public on the backend).
  const [storedAgent, setStoredAgent] = useState(undefined); // undefined = loading, null = not found
  useEffect(() => {
    let cancelled = false;
    setStoredAgent(undefined);
    getPublicService(tenantSlug, agentSlug)
      .then((data) => {
        if (cancelled) return;
        setStoredAgent(data);
      })
      .catch(() => {
        if (!cancelled) setStoredAgent(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, agentSlug]);

  const localizedResult = useMemo(
    () => withLocalizedServiceName(storedAgent?.result, lang),
    [storedAgent, lang]
  );

  function goHome() {
    window.location.href = "/";
  }

  /*
    UAE PASS presentation overlay.
    ---------------------------------------------------------------
    This is a purely visual, front-of-flow simulation that lives
    entirely inside PublishedAgentPage.jsx. It does not read from or
    write to any state inside LiveAgentPage.jsx, and it does not call
    any API. Once the simulated 2-step UAE PASS screens finish, it
    performs a single synthetic click on the REAL, unmodified
    "Sign in with UAE PASS" button that LiveAgentPage already renders
    (identified only by its existing className), which is exactly
    what happens when a person clicks it themselves. All actual
    authentication/journey logic stays inside LiveAgentPage.jsx,
    untouched.
  */
  const [identityStep, setIdentityStep] = useState("button");
  const [identityInput, setIdentityInput] = useState("");
  const [rememberIdentity, setRememberIdentity] = useState(true);
  const [confirmationCode, setConfirmationCode] = useState("49");
  const [demoIdentity, setDemoIdentity] = useState(null);
  const publishedRootRef = useRef(null);

  useEffect(() => {
    if (identityStep !== "confirm") return undefined;

    const timer = setTimeout(() => {
      const realButton = publishedRootRef.current?.querySelector(
        ".uae-pass-button"
      );
      realButton?.click();
      setIdentityStep(null);
    }, 5000);

    return () => clearTimeout(timer);
  }, [identityStep]);

  if (storedAgent === undefined) {
    return (
      <div
        dir={isAr ? "rtl" : "ltr"}
        className="min-h-screen bg-[#f7faff] px-6 py-16 text-slate-950 flex items-center justify-center"
      >
        <p className="text-slate-400">{isAr ? "جارٍ التحميل..." : "Loading..."}</p>
      </div>
    );
  }

  if (!storedAgent) {
    return (
      <div
        dir={isAr ? "rtl" : "ltr"}
        className="min-h-screen bg-[#f7faff] px-6 py-16 text-slate-950"
      >
        <div className="mx-auto max-w-2xl rounded-[30px] border border-blue-100 bg-white p-10 text-center shadow-xl shadow-blue-100/40">
          <h1 className="text-3xl font-black">
            {isAr ? "الخدمة غير متاحة" : "Service unavailable"}
          </h1>
          <p className="mt-4 text-slate-500">
            {isAr
              ? "لم يتم العثور على هذه الخدمة المنشورة."
              : "This published service could not be found."}
          </p>
          <button
            className="mt-8 rounded-2xl bg-blue-600 px-6 py-3 font-black text-white"
            onClick={goHome}
            type="button"
          >
            {isAr ? "العودة للرئيسية" : "Back to home"}
          </button>
        </div>
      </div>
    );
  }


  return (
    <div
      className="published-agent-theme"
      dir={isAr ? "rtl" : "ltr"}
      ref={publishedRootRef}
    >
      <div className="published-government-title">
        <h1>
          {isAr
            ? "منظومة ذكية لتنفيذ الخدمات الحكومية"
            : "Intelligent Government Service Delivery"}
        </h1>
      </div>
      <div className="published-language-bar">
        <button
          type="button"
          onClick={toggleLang}
          className="published-language-button"
          aria-label={isAr ? "Switch to English" : "التبديل إلى العربية"}
        >
          {isAr ? "EN" : "AR"}
        </button>
      </div>

      {identityStep && (
        <div className="uae-pass-overlay" role="dialog" aria-modal="true">
          {identityStep === "button" && (
            <div className="uae-pass-overlay-card uae-pass-overlay-entry">
              <span className="uae-pass-overlay-fingerprint">
                <IdentityFingerprintMark size={46} />
              </span>

              <p className="uae-pass-overlay-entry-caption">
                {isAr
                  ? "هوية رقمية موحدة ومعتمدة لجميع المواطنين والمقيمين والزوار"
                  : "A unified, certified digital identity for citizens, residents and visitors"}
              </p>

              <button
                type="button"
                className="uae-pass-overlay-entry-button"
                onClick={() => setIdentityStep("form")}
              >
                <span className="uae-pass-overlay-entry-button-icon" aria-hidden="true">
                  <IdentityFingerprintMark size={18} />
                </span>
                {isAr
                  ? "تسجيل الدخول بالهوية الرقمية"
                  : "Login with Digital Identity"}
              </button>
            </div>
          )}

          {identityStep === "form" && (
            <div className="uae-pass-overlay-card">
              <span className="uae-pass-overlay-fingerprint">
                <IdentityFingerprintMark size={40} />
              </span>

              <h2 className="uae-pass-overlay-title">
                {isAr ? "تسجيل الدخول إلى UAE PASS" : "Login to UAE PASS"}
              </h2>

              <form
                className="uae-pass-overlay-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  setConfirmationCode(
                    String(Math.floor(Math.random() * 90) + 10)
                  );
                  setDemoIdentity(
                    DEMO_IDENTITY_PROFILES[
                      Math.floor(Math.random() * DEMO_IDENTITY_PROFILES.length)
                    ]
                  );
                  setIdentityStep("confirm");
                }}
              >
                <input
                  id="uae-pass-overlay-id"
                  className="uae-pass-overlay-input"
                  type="text"
                  inputMode="numeric"
                  autoComplete="off"
                  aria-label={
                    isAr
                      ? "رقم الهاتف أو رقم الهوية"
                      : "Mobile number or Emirates ID"
                  }
                  value={identityInput}
                  onChange={(event) => setIdentityInput(event.target.value)}
                  placeholder={
                    isAr ? "أدخل أي رقم للتجربة" : "Enter any number to try"
                  }
                />

                <label className="uae-pass-overlay-remember">
                  <input
                    type="checkbox"
                    checked={rememberIdentity}
                    onChange={(event) =>
                      setRememberIdentity(event.target.checked)
                    }
                  />
                  <span>{isAr ? "تذكرني" : "Remember me"}</span>
                </label>

                <button type="submit" className="uae-pass-overlay-button">
                  {isAr ? "تسجيل الدخول" : "Login"}
                </button>

                <div className="uae-pass-overlay-form-footer">
                  <span>
                    {isAr
                      ? "ليس لديك حساب UAE PASS؟"
                      : "Don't have UAEPASS account?"}{" "}
                    <span className="uae-pass-overlay-link">
                      {isAr ? "إنشاء حساب جديد" : "Create new account"}
                    </span>
                  </span>
                  <span className="uae-pass-overlay-link">
                    {isAr ? "استرجاع حسابك" : "Recover your account"}
                  </span>
                </div>
              </form>
            </div>
          )}

          {identityStep === "confirm" && (
            <div className="uae-pass-overlay-card uae-pass-overlay-confirm">
              <div className="uae-pass-overlay-confirm-header">
                <span className="uae-pass-overlay-wordmark">
                  <IdentityFingerprintMark size={22} />
                  {isAr ? "الهوية الرقمية · UAE PASS" : "UAE PASS"}
                </span>

                <button
                  type="button"
                  className="uae-pass-overlay-cancel"
                  onClick={() => setIdentityStep("button")}
                >
                  {isAr ? "إلغاء الطلب ×" : "Cancel Request ×"}
                </button>
              </div>

              <p className="uae-pass-overlay-request-label">
                {isAr ? "طلب تسجيل دخول من" : "Login request from"}
              </p>

              <strong className="uae-pass-overlay-request-name">
                {isAr
                  ? "منظومة ذكية لتنفيذ الخدمات الحكومية"
                  : "Intelligent Government Service Delivery"}
              </strong>

              <p className="uae-pass-overlay-instruction">
                {isAr
                  ? "افتح تطبيق UAE PASS، اختر الرقم الظاهر أدناه، ثم أكّد لتسجيل الدخول"
                  : "Open your UAE PASS app, select the number shown and confirm to login"}
              </p>

              <div className="uae-pass-overlay-code">{confirmationCode}</div>

              <p className="uae-pass-overlay-waiting">
                ⏳ {isAr ? "بانتظار تأكيدك" : "Waiting for your confirmation"}
              </p>
            </div>
          )}
        </div>
      )}

      {/*
        IMPORTANT:
        The published Agent uses the SAME LiveAgentPage as Customer Journey.
        Only the visual theme below is different.
        Therefore service understanding, plans, pricing, choices, UAE PASS,
        complaints/inquiries, payment and execution stay identical.
        While the overlay above is active, the real LiveAgentPage stays
        mounted (so its unmodified UAE PASS button can be triggered
        programmatically) but is visually hidden.
      */}
      <div
        className={
          identityStep
            ? "published-live-wrap is-hidden-behind-overlay"
            : "published-live-wrap"
        }
      >
        <LiveAgentPage
          result={localizedResult}
          onBack={goHome}
          customerOnly
          demoIdentity={demoIdentity}
        />
      </div>

      <style>{`
        /* =========================================================
           Published Agent Page — Government Portal Theme (v2)
           Visual layer ONLY. No logic, no markup outside this file
           was touched. Everything below is scoped under
           .published-agent-theme so LiveAgentPage's own styling
           never leaks outside the published view.
        ========================================================= */

        .published-agent-theme {
          --gp-ink: #10182b;
          --gp-muted: #667085;
          --gp-line: #e3e7ee;
          --gp-line-soft: #edf0f5;
          --gp-primary: #1f4fd8;
          --gp-primary-ink: #ffffff;
          --gp-success: #0f8a5f;
          --gp-danger: #be123c;
          --gp-radius-pill: 999px;
          --gp-radius-btn: 14px;
          --gp-content-w: 720px;

          min-height: 100vh;
          background: #ffffff;
          color: var(--gp-ink);
        }

        /* The real LiveAgentPage stays mounted at all times so its
           unmodified UAE PASS button remains clickable programmatically;
           it is only visually hidden while the overlay above plays. */
        .published-agent-theme .published-live-wrap {
          display: contents;
        }

        .published-agent-theme .published-live-wrap.is-hidden-behind-overlay {
          display: none;
        }

        /* ---------- UAE PASS overlay (button + login + confirmation) ----
           Three simulated screens matching the real UAE PASS reference
           flow visually. No authentication happens here — the final
           step auto-advances after 5s by clicking the real, unmodified
           "Sign in with UAE PASS" button underneath. */
        .published-agent-theme .uae-pass-overlay {
          position: fixed;
          inset: 0;
          z-index: 60;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
          background: #ffffff;
        }

        .published-agent-theme .uae-pass-overlay-card {
          width: 100%;
          max-width: 360px;
          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;
        }

        .published-agent-theme .uae-pass-overlay-fingerprint {
          display: grid;
          place-items: center;
          margin-bottom: 20px;
          color: var(--gp-ink);
        }

        /* ---- Step 1: entry button ---- */
        .published-agent-theme .uae-pass-overlay-entry-caption {
          max-width: 300px;
          margin: 0 0 26px;
          font-size: 13px;
          line-height: 1.7;
          color: var(--gp-muted);
        }

        .published-agent-theme .uae-pass-overlay-entry-button {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          height: 50px;
          padding: 0 22px;
          border: 0;
          border-radius: var(--gp-radius-pill);
          background: var(--gp-ink) !important;
          color: #ffffff !important;
          font-size: 14px;
          font-weight: 700;
        }

        .published-agent-theme .uae-pass-overlay-entry-button-icon {
          display: grid;
          place-items: center;
          width: 24px;
          height: 24px;
          border-radius: 7px;
          background: #ffffff !important;
        }

        /* ---- Step 2: login form ---- */
        .published-agent-theme .uae-pass-overlay-title {
          margin: 0 0 24px;
          font-size: 19px;
          font-weight: 750;
          color: var(--gp-ink);
        }

        .published-agent-theme .uae-pass-overlay-form {
          width: 100%;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .published-agent-theme .uae-pass-overlay-input {
          width: 100%;
          height: 46px;
          padding: 0 14px;
          border: 1px solid var(--gp-line);
          border-radius: 10px;
          font-size: 14px;
          color: var(--gp-ink);
          background: #ffffff;
        }

        .published-agent-theme .uae-pass-overlay-input:focus {
          outline: none;
          border-color: var(--gp-primary);
          box-shadow: 0 0 0 3px rgba(31,79,216,.10);
        }

        .published-agent-theme .uae-pass-overlay-remember {
          display: flex;
          align-items: center;
          gap: 8px;
          justify-content: flex-start;
          font-size: 12.5px;
          color: var(--gp-muted);
        }

        .published-agent-theme .uae-pass-overlay-remember input {
          width: 15px;
          height: 15px;
          accent-color: var(--gp-primary);
        }

        .published-agent-theme .uae-pass-overlay-button {
          margin-top: 6px;
          height: 46px;
          border: 1px solid var(--gp-primary);
          border-radius: var(--gp-radius-pill);
          background: var(--gp-primary) !important;
          color: var(--gp-primary-ink) !important;
          font-size: 14px;
          font-weight: 700;
        }

        .published-agent-theme .uae-pass-overlay-form-footer {
          margin-top: 14px;
          padding-top: 14px;
          border-top: 1px solid var(--gp-line-soft);
          display: flex;
          flex-direction: column;
          gap: 8px;
          font-size: 12px;
          color: var(--gp-muted);
        }

        .published-agent-theme .uae-pass-overlay-link {
          color: var(--gp-success);
          font-weight: 700;
        }

        /* ---- Step 3: confirmation ---- */
        .published-agent-theme .uae-pass-overlay-confirm {
          max-width: 420px;
        }

        .published-agent-theme .uae-pass-overlay-confirm-header {
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          margin-bottom: 26px;
        }

        .published-agent-theme .uae-pass-overlay-wordmark {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          font-weight: 750;
          color: var(--gp-ink);
        }

        .published-agent-theme .uae-pass-overlay-cancel {
          border: 0;
          background: transparent;
          padding: 0;
          font-size: 12px;
          font-weight: 700;
          color: var(--gp-danger);
        }

        .published-agent-theme .uae-pass-overlay-request-label {
          margin: 0;
          font-size: 13px;
          color: var(--gp-muted);
        }

        .published-agent-theme .uae-pass-overlay-request-name {
          display: block;
          max-width: 320px;
          margin: 6px 0 18px;
          font-size: 15px;
          font-weight: 750;
          color: var(--gp-ink);
        }

        .published-agent-theme .uae-pass-overlay-instruction {
          max-width: 320px;
          margin: 0 0 22px;
          font-size: 13.5px;
          line-height: 1.7;
          color: var(--gp-muted);
        }

        .published-agent-theme .uae-pass-overlay-code {
          min-width: 96px;
          padding: 10px 20px;
          margin-bottom: 20px;
          border: 1px solid var(--gp-line);
          border-radius: 16px;
          font-size: 34px;
          font-weight: 800;
          letter-spacing: .1em;
          color: var(--gp-primary);
        }

        .published-agent-theme .uae-pass-overlay-waiting {
          margin: 0;
          font-size: 13px;
          color: #b45309;
        }

        .published-agent-theme * {
          text-shadow: none !important;
        }

        /* Safety net: force every element inside the published theme
           to a white background, so nothing from the original
           purple/dark theme (gradients, tinted panels, badges, etc.)
           can leak through — regardless of which class it uses. */
        .published-agent-theme div,
        .published-agent-theme section,
        .published-agent-theme article,
        .published-agent-theme header,
        .published-agent-theme main,
        .published-agent-theme aside,
        .published-agent-theme form,
        .published-agent-theme fieldset,
        .published-agent-theme label,
        .published-agent-theme ul,
        .published-agent-theme li,
        .published-agent-theme button,
        .published-agent-theme span,
        .published-agent-theme small,
        .published-agent-theme p,
        .published-agent-theme a {
          background-color: #ffffff !important;
          background-image: none !important;
        }

        /* ---------- Top identity strip ---------- */
        .published-government-title {
          max-width: var(--gp-content-w);
          margin: 0 auto;
          padding: 30px 60px 14px;
          text-align: center;
          background: #ffffff !important;
        }

        .published-government-title h1 {
          display: block;
          margin: 0;
          font-size: clamp(19px, 2.4vw, 24px);
          line-height: 1.4;
          font-weight: 800;
          color: var(--gp-ink) !important;
        }

        .published-language-bar {
          position: absolute;
          top: 22px;
          right: 28px;
          left: auto;
          width: auto;
          max-width: none;
          margin: 0;
          padding: 0;
          z-index: 20;
          background: transparent !important;
        }

        [dir="rtl"] .published-language-bar {
          right: auto;
          left: 28px;
        }

        .published-language-button {
          min-width: 44px;
          height: 34px;
          padding: 0 13px;
          border: 1px solid var(--gp-ink) !important;
          border-radius: var(--gp-radius-pill);
          background: #ffffff !important;
          color: var(--gp-ink) !important;
          font-size: 12.5px;
          font-weight: 700;
          box-shadow: none !important;
        }

        .published-language-button:hover {
          background: #ffffff !important;
          transform: none !important;
        }

        /* ---------- Overall page frame ---------- */
        .published-agent-theme {
          position: relative;
        }

        .published-agent-theme .live-agent-page {
          min-height: 100vh !important;
          max-width: var(--gp-content-w) !important;
          margin: 0 auto !important;
          padding: 8px 16px 56px !important;
          background: #ffffff !important;
          color: var(--gp-ink) !important;
        }

        /* Hide the original decorated hero completely — the small
           government title strip above already carries that role. */
        .published-agent-theme .live-agent-header {
          display: none !important;
        }

        /* ---------- Stepper ---------- */
        .published-agent-theme .live-stage-rail {
          margin: 4px 0 26px !important;
          padding: 0 0 16px !important;
          border: 0 !important;
          border-bottom: 1px solid var(--gp-line) !important;
          border-radius: 0 !important;
          background: #ffffff !important;
          box-shadow: none !important;
        }

        .published-agent-theme .live-stage {
          background: transparent !important;
        }

        .published-agent-theme .live-stage > span {
          width: 20px !important;
          height: 20px !important;
          min-width: 20px !important;
          font-size: 11px !important;
          border-width: 1px !important;
          box-shadow: none !important;
        }

        .published-agent-theme .live-stage small {
          font-size: 10.5px !important;
          font-weight: 600 !important;
        }

        .published-agent-theme .live-stage:not(:last-child)::after {
          height: 1px !important;
          box-shadow: none !important;
        }

        /* ---------- Cards: strip the "boxed" look entirely ----------
           Only buttons / inputs / badges / selected-options keep a
           border, per spec. Section wrappers become plain, borderless,
           shadow-free blocks sitting directly on the white page. */
        .published-agent-theme .live-focus-card,
        .published-agent-theme .live-plan-layout > *,
        .published-agent-theme .execution-live-layout > *,
        .published-agent-theme .customer-review-card,
        .published-agent-theme .customer-payment-card,
        .published-agent-theme .customer-processing-card,
        .published-agent-theme .customer-success-card,
        .published-agent-theme .payment-live-card,
        .published-agent-theme .service-checkpoint-card,
        .published-agent-theme .quote-ready-card,
        .published-agent-theme .plan-main-card,
        .published-agent-theme .execution-main-card,
        .published-agent-theme .uae-pass-card,
        .published-agent-theme .document-loading-card,
        .published-agent-theme .live-side-card {
          max-width: var(--gp-content-w) !important;
          margin-left: auto !important;
          margin-right: auto !important;
          border: 0 !important;
          border-radius: 0 !important;
          background: #ffffff !important;
          background-image: none !important;
          box-shadow: none !important;
          color: var(--gp-ink) !important;
          padding-left: 0 !important;
          padding-right: 0 !important;
        }

        .published-agent-theme .live-plan-layout,
        .published-agent-theme .execution-live-layout {
          display: flex !important;
          flex-direction: column !important;
          gap: 22px !important;
        }

        .published-agent-theme .plan-side-stack {
          display: flex !important;
          flex-direction: column !important;
          gap: 10px !important;
        }

        .published-agent-theme .live-side-card {
          padding: 10px 0 !important;
          border: 0 !important;
        }

        /* Headings / text — smaller, calmer, government-portal scale */
        .published-agent-theme h1,
        .published-agent-theme h2,
        .published-agent-theme h3,
        .published-agent-theme h4 {
          color: var(--gp-ink) !important;
          font-weight: 750 !important;
        }

        .published-agent-theme h3 {
          font-size: 18px !important;
          margin: 4px 0 8px !important;
        }

        .published-agent-theme h4 {
          font-size: 14px !important;
        }

        .published-agent-theme p,
        .published-agent-theme span,
        .published-agent-theme small,
        .published-agent-theme li,
        .published-agent-theme label {
          color: var(--gp-muted) !important;
        }

        .published-agent-theme p {
          font-size: 13.5px !important;
          line-height: 1.6 !important;
        }

        .published-agent-theme strong,
        .published-agent-theme b {
          color: var(--gp-ink) !important;
          font-weight: 700 !important;
        }

        .published-agent-theme .live-card-kicker {
          color: var(--gp-primary) !important;
          font-size: 11px !important;
          font-weight: 700 !important;
          letter-spacing: .02em !important;
        }

        /* ---------- Inputs ---------- */
        .published-agent-theme input,
        .published-agent-theme textarea,
        .published-agent-theme select {
          border: 1px solid var(--gp-line) !important;
          border-radius: 10px !important;
          background: #ffffff !important;
          color: var(--gp-ink) !important;
          box-shadow: none !important;
        }

        .published-agent-theme input:focus,
        .published-agent-theme textarea:focus,
        .published-agent-theme select:focus {
          border-color: var(--gp-primary) !important;
          outline: 3px solid rgba(31,79,216,.10) !important;
          box-shadow: none !important;
        }

        /* ---------- Buttons: small, rounded / pill ---------- */
        .published-agent-theme button {
          border-radius: var(--gp-radius-btn) !important;
          box-shadow: none !important;
          font-weight: 700 !important;
          font-size: 13px !important;
          transition: transform .15s ease, background .15s ease, border-color .15s ease;
        }

        .published-agent-theme button:not([disabled]):hover {
          transform: translateY(-1px);
        }

        .published-agent-theme button[class*="primary"],
        .published-agent-theme button[class*="confirm"],
        .published-agent-theme button[class*="continue"],
        .published-agent-theme .payment-submit,
        .published-agent-theme .uae-pass-button,
        .published-agent-theme .plan-approval-actions > button:last-child,
        .published-agent-theme .customer-success-card > button {
          border: 1px solid var(--gp-primary) !important;
          background: var(--gp-primary) !important;
          color: var(--gp-primary-ink) !important;
          border-radius: var(--gp-radius-pill) !important;
          padding: 10px 22px !important;
        }

        .published-agent-theme button.secondary,
        .published-agent-theme .plan-approval-actions > button:first-child {
          border: 1px solid var(--gp-line) !important;
          background: #ffffff !important;
          color: var(--gp-ink) !important;
          border-radius: var(--gp-radius-pill) !important;
          padding: 10px 22px !important;
        }

        .published-agent-theme .plan-approval-actions,
        .published-agent-theme .customer-plan-actions {
          display: flex !important;
          gap: 12px !important;
          margin-top: 18px !important;
        }

        .published-agent-theme button:disabled {
          opacity: .5 !important;
        }

        /* Clear spacing between the text above and the action buttons
           that follow it, everywhere in the flow. */
        .published-agent-theme .live-focus-card > button,
        .published-agent-theme .plan-approval-actions,
        .published-agent-theme .customer-plan-actions,
        .published-agent-theme .payment-submit,
        .published-agent-theme .uae-pass-button {
          margin-top: 20px !important;
        }

        /* ---------- Selectable option cards (Standard/Express/Premium
           style plans, duration choices) — white, small, radio-style.
           Only the selected option gets a border/tint. ---------- */
        .published-agent-theme .package-option,
        .published-agent-theme .duration-option {
          border: 1px solid var(--gp-line) !important;
          border-radius: 12px !important;
          background: #ffffff !important;
          box-shadow: none !important;
          padding: 10px 12px !important;
        }

        .published-agent-theme .package-option.selected,
        .published-agent-theme .duration-option.selected {
          border: 1.5px solid var(--gp-primary) !important;
          background: #ffffff !important;
          color: var(--gp-primary) !important;
          box-shadow: none !important;
        }

        .published-agent-theme .package-option input[type="radio"] {
          accent-color: var(--gp-primary) !important;
        }

        /* ---------- UAE PASS screen: white, minimal, centered ---------- */
        .published-agent-theme .uae-pass-card {
          max-width: 420px !important;
          text-align: center !important;
          padding: 48px 8px 8px !important;
        }

        .published-agent-theme .uae-pass-mark {
          margin: 0 auto 18px !important;
          background: #ffffff !important;
          border: 0 !important;
        }

        .published-agent-theme .uae-pass-note {
          display: block !important;
          margin-top: 14px !important;
          font-size: 11px !important;
        }

        /* Loading screen: small, intact spinner + text, all centered
           in the middle of the screen with clean, consistent spacing. */
        .published-agent-theme .document-loading-card {
          max-width: 420px !important;
          width: 100% !important;
          min-height: min(60vh, 420px) !important;
          margin: 0 auto !important;
          padding: 24px 8px !important;
          display: flex !important;
          flex-direction: column !important;
          align-items: center !important;
          justify-content: center !important;
          text-align: center !important;
        }

        .published-agent-theme .document-loader {
          width: 56px !important;
          height: 56px !important;
          margin: 0 auto 18px !important;
          position: relative !important;
          display: grid !important;
          place-items: center !important;
        }

        .published-agent-theme .document-loader-ring {
          position: absolute !important;
          inset: 0 !important;
          border-width: 2px !important;
          border-color: var(--gp-line) !important;
          border-top-color: var(--gp-primary) !important;
        }

        .published-agent-theme .document-loader span {
          width: 32px !important;
          height: 32px !important;
          font-size: 14px !important;
          border-color: var(--gp-line) !important;
          color: var(--gp-primary) !important;
        }

        .published-agent-theme .document-loading-card h3 {
          margin-top: 4px !important;
          font-size: 16px !important;
        }

        .published-agent-theme .document-loading-card p {
          max-width: 380px !important;
          margin: 6px auto 0 !important;
        }

        .published-agent-theme .document-loading-progress {
          max-width: 220px !important;
          margin: 16px auto 0 !important;
          height: 3px !important;
          background: var(--gp-line-soft) !important;
        }

        .published-agent-theme .document-loading-progress span {
          background: var(--gp-primary) !important;
        }

        /* The "processing" screen at the very end of the customer
           journey — everything centered horizontally in the middle
           of the page: loader, badge, title, description. */
        .published-agent-theme .customer-processing-card {
          display: flex !important;
          flex-direction: column !important;
          align-items: center !important;
          justify-content: center !important;
          min-height: min(60vh, 420px) !important;
          text-align: center !important;
        }

        .published-agent-theme .customer-processing-orb {
          margin: 0 auto 18px !important;
        }

        .published-agent-theme .customer-processing-card .live-card-kicker {
          display: block !important;
        }

        /* ---------- Service review — compact stacked rows ---------- */
        .published-agent-theme .plan-service-summary {
          display: flex !important;
          flex-direction: column !important;
          gap: 4px !important;
          padding: 14px 0 !important;
          border: 0 !important;
          background: #ffffff !important;
        }

        .published-agent-theme .plan-service-summary small {
          font-size: 11px !important;
          text-transform: uppercase !important;
          letter-spacing: .04em !important;
        }

        .published-agent-theme .plan-service-summary strong {
          font-size: 16px !important;
        }

        .published-agent-theme .plan-heading-row {
          display: flex !important;
          flex-wrap: wrap !important;
          gap: 8px !important;
          align-items: flex-start !important;
        }

        .published-agent-theme .plan-ready-badge {
          border: 1px solid var(--gp-line) !important;
          border-radius: var(--gp-radius-pill) !important;
          background: #ffffff !important;
          color: var(--gp-muted) !important;
          font-size: 10.5px !important;
          padding: 4px 10px !important;
        }

        /* fee / SLA / integrations side items rendered as compact
           label-over-value rows, matching the "الخدمة / السعر" style */
        .published-agent-theme .live-side-card > span {
          font-size: 11px !important;
          text-transform: uppercase !important;
          letter-spacing: .04em !important;
          color: var(--gp-muted) !important;
        }

        .published-agent-theme .live-side-card > strong {
          display: block !important;
          margin-top: 4px !important;
          font-size: 15px !important;
        }

        /* ---------- Price / receipt panels — plain white rows ---------- */
        .published-agent-theme .payment-amount-panel,
        .published-agent-theme .customer-service-receipt {
          display: flex !important;
          flex-direction: column !important;
          gap: 4px !important;
          padding: 14px 0 !important;
          border: 0 !important;
          background: #ffffff !important;
        }

        .published-agent-theme .customer-service-receipt > div {
          display: flex !important;
          justify-content: space-between !important;
          gap: 12px !important;
          padding: 4px 0 !important;
        }

        .published-agent-theme .payment-amount-panel span,
        .published-agent-theme .customer-service-receipt span {
          font-size: 11px !important;
          text-transform: uppercase !important;
          letter-spacing: .04em !important;
          color: var(--gp-muted) !important;
        }

        .published-agent-theme .payment-amount-panel strong,
        .published-agent-theme .customer-service-receipt strong {
          font-size: 17px !important;
          color: var(--gp-ink) !important;
        }

        .published-agent-theme .payment-amount-panel small {
          font-size: 11.5px !important;
          color: var(--gp-muted) !important;
        }

        /* ---------- Payment step ---------- */
        .published-agent-theme .payment-consent {
          display: flex !important;
          align-items: center !important;
          gap: 8px !important;
          margin-top: 14px !important;
        }

        .published-agent-theme .payment-consent input {
          width: 16px !important;
          height: 16px !important;
          accent-color: var(--gp-primary) !important;
        }

        .published-agent-theme .payment-consent span {
          font-size: 12.5px !important;
        }

        .published-agent-theme .sandbox-card-visual {
          max-width: 340px !important;
          margin: 14px auto !important;
          border: 1px solid var(--gp-line) !important;
          border-radius: 12px !important;
          background: #ffffff !important;
          box-shadow: none !important;
        }

        /* ---------- Success check + completion ---------- */
        .published-agent-theme .success-check {
          border: 1px solid #b9e6cf !important;
          background: #ffffff !important;
          color: var(--gp-success) !important;
          box-shadow: none !important;
        }

        .published-agent-theme .success-live-card,
        .published-agent-theme .customer-success-card {
          text-align: center !important;
          padding: 40px 8px !important;
        }

        .published-agent-theme .completion-receipt {
          margin: 18px auto !important;
        }

        /* ---------- Errors ---------- */
        .published-agent-theme .live-agent-error {
          border: 1px solid #fecaca !important;
          border-radius: 12px !important;
          background: #ffffff !important;
          color: var(--gp-danger) !important;
          box-shadow: none !important;
        }

        /* ---------- Mobile ---------- */
        @media (max-width: 720px) {
          .published-government-title {
            padding: 68px 18px 12px;
          }

          .published-language-bar,
          [dir="rtl"] .published-language-bar {
            top: 18px;
            right: 18px;
            left: auto;
          }

          .published-agent-theme .live-agent-page {
            padding: 6px 14px 42px !important;
          }

          .published-agent-theme .customer-service-receipt > div,
          .published-agent-theme .plan-heading-row {
            flex-direction: column !important;
          }
        }
          /* Remove ALL borders around service / amount summary */
.published-agent-theme .plan-service-summary,
.published-agent-theme .plan-service-summary *,
.published-agent-theme .payment-amount-panel,
.published-agent-theme .payment-amount-panel *,
.published-agent-theme .customer-service-receipt,
.published-agent-theme .customer-service-receipt *,
.published-agent-theme .live-side-card,
.published-agent-theme .live-side-card * {
  border: 0 !important;
  outline: 0 !important;
  box-shadow: none !important;
}

.published-agent-theme .plan-service-summary::before,
.published-agent-theme .plan-service-summary::after,
.published-agent-theme .payment-amount-panel::before,
.published-agent-theme .payment-amount-panel::after,
.published-agent-theme .customer-service-receipt::before,
.published-agent-theme .customer-service-receipt::after,
.published-agent-theme .live-side-card::before,
.published-agent-theme .live-side-card::after {
  border: 0 !important;
  box-shadow: none !important;
  background: transparent !important;
}
  /* Review action buttons */
.published-agent-theme .plan-approval-actions > button,
.published-agent-theme .customer-plan-actions > button {
  background: var(--gp-primary) !important;
  color: #ffffff !important;
  border: 1px solid var(--gp-primary) !important;
  border-radius: 999px !important;
  padding: 10px 22px !important;
}

/* Keep Edit options as secondary */
.published-agent-theme .plan-approval-actions > button:first-child,
.published-agent-theme .customer-plan-actions > button:first-child {
  background: #ffffff !important;
  color: var(--gp-ink) !important;
  border: 1px solid var(--gp-line) !important;
}

      `}</style>
    </div>
  );
}