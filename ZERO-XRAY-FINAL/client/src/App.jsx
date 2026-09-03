import {
  useCallback,
  useEffect,
  useRef,
  useState
} from "react";
import SpaceIntro
from "./components/SpaceIntro";
import MethodSelect
from "./components/MethodSelect";
import ServiceForm
from "./components/ServiceForm";
import AgentProgress
from "./components/AgentProgress";
import Dashboard
from "./components/Dashboard";
import LiveAgentPage
from "./components/LiveAgentPage";
import BuildAgentPage
from "./components/BuildAgentPage";
import StandardsPage
from "./components/StandardsPage";
import PublishedAgentPage from "./components/PublishedAgentPage";
import LoginPage from "./components/LoginPage";
import LoginGate from "./components/LoginGate";
import AccessExpiredGate from "./components/AccessExpiredGate";
import PlatformAdminPage from "./components/PlatformAdminPage";
import {
  AgentsPanel,
  AnalysesPanel,
  AuditLogPanel,
  DataSourcesPanel,
  IntegrationsPanel,
  OverviewPanel,
  ServicesPanel,
  SettingsPanel,
  UsersPanel,
} from "./components/WorkspacePanels";

import {
  analyzeService,
  approveBlueprint,
  publishBlueprint,
  listServices,
  listServiceAnalyses
} from "./api";


import { useLanguage } from "./i18n/useLanguage";
import { translateApiError } from "./i18n/apiErrors";
import { useTheme } from "./theme/useTheme";
import { useAuth } from "./auth/AuthContext";


// Minimum time (ms) the AgentProgress animation stays on screen,
// so the loading moment always feels intentional even on a fast reply.
const MIN_LOADING_MS = 2600;


function wait(ms) {

  return new Promise(
    (resolve) => setTimeout(
      resolve,
      ms
    )
  );

}


function LanguageSwitch() {

  const { lang, toggleLang, t } = useLanguage();
  return (

    <button
      className="lang-switch"
      onClick={toggleLang}
      type="button"
      aria-label={t.header.switchLanguage}
    >

      <span className={lang === "en" ? "lang-switch-option active" : "lang-switch-option"}>
        EN
      </span>

      <span className={lang === "ar" ? "lang-switch-option active" : "lang-switch-option"}>
        AR
      </span>

    </button>

  );

}


function ThemeSwitch() {

  const { theme, toggleTheme } = useTheme();
  const { t } = useLanguage();

  const isDark = theme === "dark";

  return (

    <button
      className="theme-switch"
      onClick={toggleTheme}
      type="button"
      aria-label={t.header?.switchTheme || "Toggle theme"}
      title={t.header?.switchTheme || "Toggle theme"}
    >

      <span className={isDark ? "theme-switch-option active" : "theme-switch-option"}>
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <path
            fill="currentColor"
            d="M12 3a9 9 0 1 0 9 9c0-.35-.02-.7-.05-1.04A7 7 0 0 1 12 3Z"
          />
        </svg>
      </span>

      <span className={!isDark ? "theme-switch-option active" : "theme-switch-option"}>
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <path
            fill="currentColor"
            d="M12 5a1 1 0 0 1-1-1V2a1 1 0 1 1 2 0v2a1 1 0 0 1-1 1Zm0 17a1 1 0 0 1-1-1v-2a1 1 0 1 1 2 0v2a1 1 0 0 1-1 1ZM3 13H2a1 1 0 1 1 0-2h1a1 1 0 1 1 0 2Zm19 0h-1a1 1 0 1 1 0-2h1a1 1 0 1 1 0 2ZM5.64 6.35a1 1 0 0 1-.71-.29L4.22 5.35a1 1 0 1 1 1.41-1.41l.71.7a1 1 0 0 1-.7 1.71Zm12.72 12.72a1 1 0 0 1-.7-.3l-.71-.7a1 1 0 0 1 1.41-1.41l.71.7a1 1 0 0 1-.71 1.71ZM5.64 19.07a1 1 0 0 1-.7-1.71l.7-.7a1 1 0 1 1 1.41 1.4l-.7.71a1 1 0 0 1-.71.3ZM18.36 6.35a1 1 0 0 1-.71-1.71l.71-.7a1 1 0 1 1 1.41 1.41l-.71.7a1 1 0 0 1-.7.3ZM12 17a5 5 0 1 1 5-5 5 5 0 0 1-5 5Z"
          />
        </svg>
      </span>

    </button>

  );

}


function App() {

  const { t, lang } = useLanguage();
  const { isAuthenticated, loading: authLoading, currentTenant, role, hasPermission, logout, subscriptionBlocked } = useAuth();

  // view: "app" | "standards" — top-level section, independent of
  // the analysis phase below.
  const [
    view,
    setView
  ] = useState(
    "app"
  );


  // phase: "intro" | "method" | "form" | "loading" | "dashboard" | "build" | "live"
  const [
    phase,
    setPhase
  ] = useState(
    "intro"
  );


  const [
    method,
    setMethod
  ] = useState(
    null
  );


  const [
    result,
    setResult
  ] = useState(
    null
  );


  const [
    totalSteps,
    setTotalSteps
  ] = useState(
    8
  );


  const [
    error,
    setError
  ] = useState(
    ""
  );


  // Retranslating an already-shown result when the language switch is
  // pressed on the dashboard (as opposed to the initial submit) is a
  // background action — the previous result stays on screen while it
  // runs, so we track it separately from the main "loading" phase.
  const [
    retranslating,
    setRetranslating
  ] = useState(
    false
  );


  const [
    blueprintActionBusy,
    setBlueprintActionBusy
  ] = useState(false);


  const [
    blueprintActionError,
    setBlueprintActionError
  ] = useState("");

  // The exact payload last sent to /api/analyze, so a language switch
  // can re-request the same service with only "lang" changed.
  const lastServiceRef = useRef(null);

  // Cache of already-fetched results keyed by language, so toggling
  // back and forth between EN/AR doesn't re-hit the backend every time.
  const resultCacheRef = useRef({});
  // Tracks whether the customer has actually registered/started a
  // real, backend-persisted session (customer, journey, payment) on
  // the current Live Agent visit. Gates whether a language switch may
  // safely re-analyze there too (see the effect below) -- before
  // registration there is nothing to break; after it, re-analyzing
  // would return a NEW blueprint_id and silently orphan the
  // already-registered customer/journey tied to the old one.
  const [liveSessionStarted, setLiveSessionStarted] = useState(false);

  // ROOT-CAUSE FIX: guards against a duplicate /api/analyze call
  // firing while one is already in flight. The `loading` prop passed
  // to ServiceForm below already disables its submit button once
  // phase flips to "loading", but that flip only happens on the
  // NEXT render -- a very fast double-click (or an Enter-key repeat)
  // in the same synchronous event-handling window can still queue a
  // second onAnalyze() call before React re-renders with the button
  // disabled. The backend now also rejects an overlapping analysis
  // with a clear 409 (see server/main.py), but guarding here means
  // the user never even sees that error: a duplicate call in this
  // window is simply ignored instead of starting a second network
  // request that would only get rejected anyway.
  const analyzeInFlightRef = useRef(false);

  // ROOT-CAUSE FIX (duplicate /api/analyze -> 409): analyzeInFlightRef
  // only ever guarded handleAnalyze(). Two OTHER call sites call
  // analyzeService() directly and bypassed it entirely:
  //
  //   * the post-login restore effect, which re-analyzes a restored
  //     workspace whose persisted language differs from the UI language;
  //   * the language-switch effect, which re-analyzes on every `lang`
  //     change while a result is on screen.
  //
  // Those two can fire while a first analysis is still running (switching
  // language during a long analysis, or a restore landing on top of one),
  // so a second overlapping POST /api/analyze was sent and the backend's
  // single-flight lock correctly rejected it with 409 -- which the
  // callers then logged as a failure. The backend guard is intentionally
  // left exactly as it is; this makes the frontend stop generating the
  // duplicate in the first place, so the 409 is never provoked.
  //
  // Every analyze request in this component now goes through this one
  // helper, which owns the ref. It returns null when a request is already
  // in flight; callers treat that as "nothing to apply" and keep their
  // current state.
  const runAnalyze = useCallback(async (payload) => {
    if (analyzeInFlightRef.current) {
      return null;
    }
    analyzeInFlightRef.current = true;
    try {
      return await analyzeService(payload);
    } finally {
      analyzeInFlightRef.current = false;
    }
  }, []);

  // Restore the most recent persisted analysis after login.  The backend
  // already stores Services + Analysis.result_json in SQLite; older builds
  // simply reset React state to the intro screen on every reload/login.
  // This ref prevents a normal rerender from repeatedly replacing whatever
  // the user is currently doing with the stored analysis.
  const restoredTenantRef = useRef(null);

  useEffect(() => {
    if (!isAuthenticated || !currentTenant?.id || role === "platform_admin") {
      if (!isAuthenticated) restoredTenantRef.current = null;
      return;
    }
    if (restoredTenantRef.current === currentTenant.id) return;
    restoredTenantRef.current = currentTenant.id;

    let cancelled = false;
    async function restoreLatestWorkspace() {
      try {
        const serviceResponse = await listServices();
        const services = serviceResponse?.services || [];
        if (!services.length || cancelled) return;

        const histories = await Promise.all(
          services.map(async (service) => {
            try {
              const response = await listServiceAnalyses(service.id);
              return (response?.analyses || []).map((analysis) => ({ analysis, service }));
            } catch {
              return [];
            }
          })
        );
        if (cancelled) return;

        const latest = histories
          .flat()
          .filter((item) => item.analysis?.result && Object.keys(item.analysis.result).length)
          .sort((a, b) => String(b.analysis.created_at || "").localeCompare(String(a.analysis.created_at || "")))[0];

        if (!latest) return;
        const restoredResult = {
          ...latest.analysis.result,
          service_id: latest.service.id,
          analysis_id: latest.analysis.id,
          blueprint_id: latest.analysis.blueprint_id || latest.analysis.result?.blueprint_id,
        };

        // ROOT-CAUSE FIX: this used to display+cache whatever the most
        // recently PERSISTED analysis was, unconditionally -- even if
        // it was originally generated in a DIFFERENT language than the
        // Application Language currently active (e.g. an old English
        // analysis silently redisplayed on a fresh login with Arabic
        // selected). Worse, caching it under resultCacheRef.current[lang]
        // "poisoned" the cache so the language-switch re-analyze effect
        // above never got a chance to run for that language -- it saw
        // a cache hit and reused the stale, wrong-language content.
        // Application Language is the single source of truth for ALL
        // AI-generated content, including restored history, so a
        // mismatch here is treated exactly like a language switch: the
        // SAME service is re-submitted with the CURRENT lang instead of
        // trusting the persisted language.
        const restoredLang = restoredResult.service?.lang;
        console.log(
          "[LANG DEBUG] restore: persisted analysis lang=",
          restoredLang,
          "current UI lang=",
          lang
        );

        if (restoredResult.service) {
          lastServiceRef.current = {
            ...restoredResult.service,
            service_id: latest.service.id,
          };
        }

        if (restoredLang && restoredLang !== lang) {
          console.log(
            "[LANG DEBUG] restore: language mismatch detected -- "
            + "re-analyzing in the current UI language instead of "
            + "displaying the stale, wrong-language persisted result."
          );
          setError("");
          setMethod(null);
          setView("app");
          setPhase("dashboard");
          setRetranslating(true);
          try {
            const fresh = await runAnalyze({
              ...restoredResult.service,
              lang,
            });
            if (cancelled) return;
            if (!fresh) {
              // Another analysis is already running; keep the persisted
              // result rather than firing a duplicate request that the
              // backend would reject.
              setResult(restoredResult);
              resultCacheRef.current = { [restoredLang]: restoredResult };
              return;
            }
            resultCacheRef.current = { [lang]: fresh };
            setResult(fresh);
            console.log(
              "[LANG DEBUG] restore: re-analysis complete, first_step=",
              fresh?.redesign?.future_steps?.[0]?.name
            );
          } catch (reanalyzeError) {
            console.warn(
              "Could not re-analyze restored workspace in the current language",
              reanalyzeError
            );
            // Fall back to the persisted result rather than showing
            // nothing -- still better than a blank dashboard, and the
            // language-switch effect below will retry on the next
            // actual language toggle.
            setResult(restoredResult);
            resultCacheRef.current = { [restoredLang]: restoredResult };
          } finally {
            if (!cancelled) setRetranslating(false);
          }
          return;
        }

        console.log(
          "[LANG DEBUG] restore: language matches, using persisted result as-is, first_step=",
          restoredResult?.redesign?.future_steps?.[0]?.name
        );
        setResult(restoredResult);
        setError("");
        setMethod(null);
        setView("app");
        setPhase("dashboard");
        resultCacheRef.current = { [lang]: restoredResult };
      } catch (restoreError) {
        // Persistence restore should never block login.  Services/Analyses
        // pages remain available even if this convenience restore fails.
        console.warn("Could not restore latest ZERO X-RAY workspace", restoreError);
      }
    }
    restoreLatestWorkspace();
    return () => { cancelled = true; };
  }, [isAuthenticated, currentTenant?.id, role, lang]);


  // Legacy `?demoAgent=` query param support has been removed along
  // with the localStorage-backed Agent lookup it depended on. The
  // persistent public URL is now /service/{tenantSlug}/{agentSlug}
  // (see the route match below), which is backend-resolved and
  // works after a refresh or from another browser/device.


  useEffect(() => {

    // Covers "dashboard", "build", AND "live" (only while no real
    // session has started there yet -- liveSessionStarted): all three
    // render the SAME `result` (Dashboard/BuildAgentPage/LiveAgentPage),
    // so a stale-language Future Journey would otherwise persist after
    // switching language on any of them. Once a customer has actually
    // registered on Live Agent (liveSessionStarted=true), re-analyzing
    // is deliberately skipped there: it would return a NEW blueprint_id
    // and silently orphan the already-registered customer/journey/
    // payment tied to the old one -- a real backend-persisted session,
    // not just a read-only view like the other two pages.
    const eligiblePhase =
      phase === "dashboard" ||
      phase === "build" ||
      (phase === "live" && !liveSessionStarted);

    if (
      !eligiblePhase ||
      !lastServiceRef.current
    ) {
      return;
    }

    if (
      resultCacheRef.current[lang]
    ) {

      setResult(
        resultCacheRef.current[lang]
      );

      return;

    }

    let cancelled = false;

    setRetranslating(
      true
    );

    runAnalyze({
      ...lastServiceRef.current,
      lang,
    })
      .then((response) => {

        if (cancelled) {
          return;
        }

        if (!response) {
          // An analysis is already in flight (e.g. the language was
          // switched while the first one was still running). Leave the
          // current result on screen instead of sending a duplicate
          // request; this effect runs again on the next language change.
          return;
        }

        resultCacheRef.current[lang] =
          response;

        setResult(
          response
        );

      })
      .catch((requestError) => {

        console.error(
          requestError
        );

      })
      .finally(() => {

        if (!cancelled) {

          setRetranslating(
            false
          );

        }

      });

    return () => {
      cancelled = true;
    };

    // Only re-run when the language actually changes while a result
    // is already on screen — not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);


  function handleZero() {

    setPhase(
      "method"
    );

  }


  function handleMethodPick(
    pickedMethod
  ) {

    setMethod(
      pickedMethod
    );

    setError(
      ""
    );

    setPhase(
      "form"
    );

  }


  async function handleAnalyze(
    service
  ) {

    // ROOT-CAUSE FIX: analyzeInFlightRef (declared above) was created to
    // guard exactly this path but was never actually checked/set here,
    // so it did nothing. `loading`/`phase` only flips to "loading" on the
    // NEXT render, so a fast double-click or an Enter-key repeat on the
    // form could still call handleAnalyze() a second time in the same
    // synchronous window and fire a second, overlapping POST /api/analyze
    // -- which the backend's single-flight lock then rejected with 409
    // (see server/main.py), while this function's own catch handler
    // silently logged it and reset the form, making the failed duplicate
    // look like the pipeline had just "continued" past an error. This
    // ref now actually gates re-entry: a call that arrives while one is
    // already in flight is ignored instead of starting a second request.
    if (analyzeInFlightRef.current) {
      return;
    }
    analyzeInFlightRef.current = true;

    setTotalSteps(
      service?.steps?.length || 8
    );

    setError(
      ""
    );

    setPhase(
      "loading"
    );


    try {

      const [response] =
        await Promise.all([
          analyzeService(
            // ROOT CAUSE FIX: `service` (built by ServiceForm.jsx) never
            // included "lang" -- and server/models/schemas.py's
            // ServiceInput.lang defaults to "en" when omitted, which
            // permanently overrides agents/journey_builder_agent.py's own
            // auto-detect-from-source-text fallback (the request always
            // arrives with an explicit "en", never a missing value, once
            // Pydantic applies its default). The result: every first-time
            // analysis was generated in English regardless of the current
            // UI language or the language the customer actually typed the
            // service in. The current UI `lang` always overrides here
            // (spread last), matching the same, already-correct pattern
            // used below when re-analyzing on a language switch.
            { ...service, lang }
          ),
          wait(
            MIN_LOADING_MS
          )
        ]);


      // Remember exactly what was submitted (and reset the language
      // cache) so a later language-switch on the dashboard can
      // re-request the same service with only "lang" changed.
      lastServiceRef.current = {
        ...service,
        blueprint_id: response.blueprint_id,
      };
      resultCacheRef.current = {
        [service.lang || lang]: response,
      };

      setResult(
        response
      );

      setPhase(
        "dashboard"
      );

    } catch (
      requestError
    ) {

      console.error(
        requestError
      );

      // ROOT-CAUSE FIX: this displayed the raw backend error verbatim,
      // untranslated. Most cases now go through translateApiError
      // (the same shared, centrally-maintained map used across the
      // rest of the app). AI_ENGINE_UNAVAILABLE is handled separately
      // because it carries a raw, dynamic Python exception string
      // (the actual HTTPConnectionPool/connection-refused detail) --
      // never appropriate to show a user regardless of language --
      // so it's replaced with a clean, professional, language-aware
      // message instead of translating the raw text.
      const rawMessage = requestError.message || "";
      const isAiUnavailable = /^AI_ENGINE_UNAVAILABLE/.test(rawMessage);

      setError(
        isAiUnavailable
          ? (lang === "ar"
              ? "محرك الذكاء الاصطناعي غير متاح حالياً. تحقق من تشغيل Ollama وحاول مرة أخرى."
              : "The AI engine is currently unavailable. Check that Ollama is running and try again.")
          : translateApiError(rawMessage, lang) || t.form.genericError
      );

      setPhase(
        "form"
      );

    } finally {

      analyzeInFlightRef.current = false;

    }

  }


  function handleNewAnalysis() {

    lastServiceRef.current = null;
    resultCacheRef.current = {};

    setResult(
      null
    );

    setError(
      ""
    );

    setMethod(
      null
    );

    setPhase(
      "method"
    );

  }


  async function handleApprovePublish() {

    if (!result?.blueprint_id) {
      return;
    }

    setBlueprintActionBusy(true);
    setBlueprintActionError("");

    try {

      await approveBlueprint(result.blueprint_id);
      const published = await publishBlueprint(result.blueprint_id);
      const updated = {
        ...result,
        blueprint_status: published.status,
      };

      setResult(updated);
      resultCacheRef.current[lang] = updated;

    } catch (requestError) {

      setBlueprintActionError(
        translateApiError(requestError.message, lang) ||
        (lang === "ar" ? "تعذّر اعتماد مخطط الخدمة." : "Blueprint approval failed.")
      );

    } finally {

      setBlueprintActionBusy(false);

    }

  }


  function handleLaunchAgent() {
    setBlueprintActionError("");
    // Reset per language-switch guard below: a fresh visit to Live
    // Agent has no registered customer/journey yet, so a language
    // switch here is still safe to re-analyze (see the effect above).
    setLiveSessionStarted(false);
    setPhase("live");
  }

  function handleBuildAgent() {
    setBlueprintActionError("");
    setPhase("build");
  }


  // Published customer experience:
  // /service/{tenantSlug}/{agentSlug} renders as a completely
  // standalone, anonymous page (backend-resolved -- see
  // GET /service/{tenantSlug}/{agentSlug} in server/main.py), outside
  // the ZERO X-RAY builder/sidebar layout. Replaces the old
  // /agent/{agentId} route that read from localStorage.
  const serviceMatch = window.location.pathname.match(
    /^\/service\/([^/]+)\/([^/]+)\/?$/
  );

  if (serviceMatch) {
    const tenantSlug = decodeURIComponent(serviceMatch[1]);
    const agentSlug = decodeURIComponent(serviceMatch[2]);

    return (
      <PublishedAgentPage
        tenantSlug={tenantSlug}
        agentSlug={agentSlug}
      />
    );
  }

  if (window.location.pathname === "/login") {
    return <LoginPage />;
  }

  if (window.location.pathname.startsWith("/platform")) {
    return <PlatformAdminPage />;
  }

  if (!isAuthenticated && !authLoading && subscriptionBlocked) {
    // PHASE 7: the session token is still valid (see AuthContext.jsx's
    // refresh()) -- only the tenant's workspace access is blocked. Show
    // a dedicated access-expired state instead of the sign-in screen,
    // which would incorrectly suggest the user needs to log in again.
    return <AccessExpiredGate />;
  }

  if (!isAuthenticated && !authLoading) {
    return <LoginGate />;
  }

  if (authLoading) {
    return null;
  }

  // Platform administrators manage the platform only. They never render
  // tenant workspace screens or tenant service/analysis tools.
  if (role === "platform_admin") {
    return <PlatformAdminPage />;
  }


  if (
    view === "app" &&
    phase === "intro"
  ) {

    return (

      <>

        <div className="top-switches">
          <LanguageSwitch />
          <ThemeSwitch />
        </div>

        <SpaceIntro
          onZero={handleZero}
        />

      </>

    );

  }


  return (

    <div className="app-layout">


      <aside className="app-sidebar">


        <div className="sidebar-brand">

          <div className="sidebar-logo" aria-hidden="true">
            Ø
          </div>


          <div>

            <strong>
              {t.brand.name}
            </strong>

            <span>
              {t.brand.tagline}
            </span>

          </div>

        </div>



        <nav className="sidebar-navigation">


          {role !== "viewer" && (
            <>
              {(role === "entity_admin" || role === "service_owner" || role === "analyst") && (
                <button
                  className={view === "app" ? "sidebar-link active" : "sidebar-link"}
                  onClick={() => setView("app")}
                >
                  {t.nav.analysis}
                </button>
              )}
              {(role === "entity_admin" || role === "service_owner" || role === "analyst") && (
                <button
                  className={view === "standards" ? "sidebar-link active" : "sidebar-link"}
                  onClick={() => setView("standards")}
                >
                  {t.nav.standards}
                </button>
              )}
            </>
          )}

          <div className="sidebar-navigation-divider" style={{ height: "1px", background: "rgba(255,255,255,0.08)", margin: "10px 0" }} />

          {role !== "platform_admin" && (
            <>
              <div style={{ margin: "12px 12px 6px", fontSize: "11px", fontWeight: 800, opacity: 0.55 }}>
                {lang === "ar" ? "مساحة العمل" : "WORKSPACE"}
              </div>

              {[
                ["overview", lang === "ar" ? "نظرة عامة" : "Overview", true],
                ["services", lang === "ar" ? (role === "service_owner" ? "خدماتي" : "الخدمات") : (role === "service_owner" ? "My Services" : "Services"), true],
                ["agents", lang === "ar" ? "الخدمات المنشورة" : "Published Services", role !== "analyst"],
              ].filter(([, , visible]) => visible).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={view === key ? "sidebar-link active" : "sidebar-link"}
                  onClick={() => setView(key)}
                >
                  {label}
                </button>
              ))}
            </>
          )}

          {role === "entity_admin" && (
            <>
              <div style={{ margin: "16px 12px 6px", fontSize: "11px", fontWeight: 800, opacity: 0.55 }}>
                {lang === "ar" ? "إدارة الجهة" : "ENTITY MANAGEMENT"}
              </div>
              {[
                ["datasources", lang === "ar" ? "مصادر البيانات" : "Data Sources"],
                ["integrations", lang === "ar" ? "الأنظمة والتكاملات" : "Systems & Integrations"],
                ["users", lang === "ar" ? "المستخدمون والصلاحيات" : "Users & Roles"],
                ["audit", lang === "ar" ? "سجل التدقيق" : "Audit Logs"],
                ["settings", lang === "ar" ? "الإعدادات" : "Settings"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={view === key ? "sidebar-link active" : "sidebar-link"}
                  onClick={() => setView(key)}
                >
                  {label}
                </button>
              ))}
            </>
          )}



        </nav>



        {role === "platform_admin" && (
          <a
            href="/platform"
            className="sidebar-link"
            style={{ display: "block", textAlign: "left" }}
          >
            {lang === "ar" ? "إدارة المنصة" : "Platform Admin"}
          </a>
        )}


        <div className="sidebar-footer">
          {isAuthenticated && (
            <button
              type="button"
              onClick={() => { logout(); window.location.replace("/login"); }}
              className="sidebar-logout-button"
            >
              <span aria-hidden="true">↪</span>
              <span>{lang === "ar" ? "تسجيل الخروج" : "Logout"}</span>
            </button>
          )}

          <div className="sidebar-status">
            <span className="sidebar-status-dot" />

            <div>
              <strong>
                {currentTenant?.name || t.nav.statusTitle}
              </strong>

              <small>
                {currentTenant
                  ? (lang === "ar" ? "متصل" : "Connected")
                  : t.nav.statusSubtitle}
              </small>
            </div>
          </div>
        </div>


      </aside>



      <main className="app-main">


        <header className="app-header">


          <div>

            <span className="app-header-kicker">

              {["datasources", "integrations", "users", "audit", "settings", "agents"].includes(view)
                ? (currentTenant?.name || t.header.kicker)
                : t.header.kicker}

            </span>


            <h1>

              {
                ({
                  datasources: lang === "ar" ? "مصادر البيانات" : "Data Sources",
                  integrations: lang === "ar" ? "الأنظمة والتكاملات" : "Systems & Integrations",
                  users: lang === "ar" ? "المستخدمون والصلاحيات" : "Users & Roles",
                  audit: lang === "ar" ? "سجل التدقيق" : "Audit Logs",
                  settings: lang === "ar" ? "الإعدادات" : "Settings",
                  agents: lang === "ar" ? "الخدمات المنشورة" : "Published Services",
                })[view] || (
                  view === "standards"
                    ? t.header.titleStandards
                    : (phase === "dashboard" || phase === "live") && result
                      ? result.service_name
                      : t.header.titleDefault
                )
              }

            </h1>

          </div>


          <div className="app-header-actions">

            {
              view === "app" &&
              (phase === "dashboard" || phase === "build") &&
              retranslating && (

                <span className="lang-retranslating-badge">

                  {t.header.retranslating}

                </span>

              )
            }

            {
              view === "app" &&
              phase === "dashboard" && (

                <button
                  className="new-analysis-button"
                  onClick={
                    handleNewAnalysis
                  }
                >

                  {t.header.analyzeAnother}

                </button>

              )
            }

            <LanguageSwitch />
            <ThemeSwitch />

          </div>


        </header>



        {
          view === "standards" && (

            <StandardsPage />

          )
        }


        {view === "overview" && (
          <OverviewPanel onStartAnalysis={() => setView("app")} />
        )}
        {view === "services" && <ServicesPanel onAnalyzeService={(service) => { setView("app"); handleAnalyze(service); }} />}
        {view === "analyses" && <AnalysesPanel />}
        {view === "agents" && <AgentsPanel />}
        {view === "datasources" && <DataSourcesPanel />}
        {view === "integrations" && <IntegrationsPanel onBuildAgent={(service) => { setView("app"); handleAnalyze(service); }} />}
        {view === "users" && <UsersPanel />}
        {view === "audit" && <AuditLogPanel />}
        {view === "settings" && <SettingsPanel />}


        {
          view === "app" &&
          phase === "method" && (

            <MethodSelect
              onPick={handleMethodPick}
              onBack={
                () => setPhase("intro")
              }
            />

          )
        }


        {
          view === "app" &&
          phase === "form" && (

            <ServiceForm
              method={method}
              onBack={() => setPhase("method")}
              onAnalyze={handleAnalyze}
              loading={phase === "loading"}
              error={error}
            />

          )
        }


        {
          view === "app" &&
          phase === "loading" && (

            <AgentProgress
              totalSteps={totalSteps}
            />

          )
        }


        {
          view === "app" &&
          phase === "dashboard" && result && (

            <Dashboard
              result={result}
              onApprovePublish={handleApprovePublish}
              onLaunchAgent={handleLaunchAgent}
              onBuildAgent={handleBuildAgent}
              actionBusy={blueprintActionBusy}
              actionError={blueprintActionError}
            />

          )
        }


        {
          view === "app" &&
          phase === "build" && result && (

            <BuildAgentPage
              result={result}
              onBack={() => setPhase("dashboard")}
              onTestAgent={handleLaunchAgent}
            />

          )
        }


        {
          view === "app" &&
          phase === "live" && result && (

            <LiveAgentPage
              result={result}
              onBack={() => setPhase("dashboard")}
              onSessionStart={() => setLiveSessionStarted(true)}
            />

          )
        }


      </main>


    </div>

  );

}


export default App;