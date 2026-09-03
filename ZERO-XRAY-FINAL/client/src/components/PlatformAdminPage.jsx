import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { useLanguage } from "../i18n/useLanguage";
import { translateApiError } from "../i18n/apiErrors";
import { useTheme } from "../theme/useTheme";
import { createGovernmentEntity, listGovernmentEntities, getPlatformStats, updateGovernmentEntitySubscription } from "../api";
import LoginGate from "./LoginGate";

const STATUS_COLORS = {
  ACTIVE: "bg-emerald-50 text-emerald-700 border-emerald-200",
  PILOT: "bg-blue-50 text-blue-700 border-blue-200",
  SUSPENDED: "bg-amber-50 text-amber-700 border-amber-200",
  EXPIRED: "bg-red-50 text-red-700 border-red-200",
  ARCHIVED: "bg-slate-100 text-slate-500 border-slate-200",
};

const STATUS_LABELS = {
  en: {
    ACTIVE: "Active",
    PILOT: "Pilot",
    SUSPENDED: "Suspended",
    EXPIRED: "Expired",
    ARCHIVED: "Archived",
  },
  ar: {
    ACTIVE: "نشطة",
    PILOT: "تجريبية",
    SUSPENDED: "موقوفة",
    EXPIRED: "منتهية",
    ARCHIVED: "مؤرشفة",
  },
};

const COPY = {
  en: {
    platformAdministration: "Platform Administration",
    governmentEntities: "Government Entities",
    intro: "Platform administrators manage entity access and subscriptions only. Expiring or suspending an entity blocks its workspace without deleting its data.",
    signOut: "Sign out",
    totalEntities: "Total Entities",
    active: "Active",
    pilot: "Pilot",
    suspended: "Suspended",
    expired: "Expired",
    totalUsers: "Total Users",
    totalServices: "Total Services",
    totalAnalyses: "Total Analyses",
    totalAgents: "Total Agents",
    publishedAgents: "Published Agents",
    addEntity: "+ Add Government Entity",
    addEntityTitle: "Add Government Entity",
    entityName: "Entity name",
    slug: "slug (e.g. emirates-post)",
    adminName: "Entity Admin name",
    adminEmail: "Entity Admin email",
    create: "Create",
    creating: "Creating...",
    cancel: "Cancel",
    plan: "Plan",
    subscriptionEnds: "Subscription ends",
    saveSubscription: "Save subscription",
    activate: "Activate",
    suspend: "Suspend",
    days: "days",
    users: "Users",
    services: "Services",
    agents: "Agents",
    published: "Published",
    loading: "Loading...",
    updateError: "Could not update subscription.",
    createError: "Could not create the entity.",
    loadError: "Could not load entities.",
    adminOnly: "Platform Admin only",
    adminOnlyBody: "This area is only for platform administrators.",
    backToWorkspace: "Back to workspace",
    dark: "Dark",
    light: "Light",
    arabic: "AR",
    english: "EN",
    extendReactivate: "Extend the subscription to reactivate this entity.",
    activateTitle: "Activate this entity.",
  },
  ar: {
    platformAdministration: "إدارة المنصة",
    governmentEntities: "الجهات الحكومية",
    intro: "مدير المنصة يدير وصول الجهات واشتراكاتها فقط. انتهاء الاشتراك أو إيقاف الجهة يمنع الدخول لمساحة العمل دون حذف بياناتها.",
    signOut: "تسجيل الخروج",
    totalEntities: "إجمالي الجهات",
    active: "نشطة",
    pilot: "تجريبية",
    suspended: "موقوفة",
    expired: "منتهية",
    totalUsers: "إجمالي المستخدمين",
    totalServices: "إجمالي الخدمات",
    totalAnalyses: "إجمالي التحليلات",
    totalAgents: "إجمالي الوكلاء",
    publishedAgents: "الوكلاء المنشورون",
    addEntity: "+ إضافة جهة حكومية",
    addEntityTitle: "إضافة جهة حكومية",
    entityName: "اسم الجهة",
    slug: "المعرّف المختصر (مثال: emirates-post)",
    adminName: "اسم مدير الجهة",
    adminEmail: "البريد الإلكتروني لمدير الجهة",
    create: "إنشاء",
    creating: "جارٍ الإنشاء...",
    cancel: "إلغاء",
    plan: "الخطة",
    subscriptionEnds: "نهاية الاشتراك",
    saveSubscription: "حفظ الاشتراك",
    activate: "تفعيل",
    suspend: "إيقاف",
    days: "يوم",
    users: "المستخدمون",
    services: "الخدمات",
    agents: "الوكلاء",
    published: "المنشور",
    loading: "جارٍ التحميل...",
    updateError: "تعذر تحديث الاشتراك.",
    createError: "تعذر إنشاء الجهة.",
    loadError: "تعذر تحميل الجهات.",
    adminOnly: "مدير المنصة فقط",
    adminOnlyBody: "هذه المنطقة مخصصة لمديري المنصة فقط.",
    backToWorkspace: "العودة لمساحة العمل",
    dark: "داكن",
    light: "فاتح",
    arabic: "AR",
    english: "EN",
    extendReactivate: "مدد الاشتراك أولًا لإعادة تفعيل هذه الجهة.",
    activateTitle: "تفعيل هذه الجهة.",
  },
};

function toDateInput(value) {
  return value ? String(value).slice(0, 10) : "";
}

function EntityCard({ entity, onUpdated, lang, isDark }) {
  const text = COPY[lang];
  const status = entity.effective_status || entity.status;
  const badgeClass = STATUS_COLORS[status] || STATUS_COLORS.ARCHIVED;
  const counts = entity.counts || {};
  const [plan, setPlan] = useState(entity.subscription_plan || "PILOT");
  const [endDate, setEndDate] = useState(toDateInput(entity.subscription_end));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPlan(entity.subscription_plan || "PILOT");
    setEndDate(toDateInput(entity.subscription_end));
  }, [entity.subscription_plan, entity.subscription_end]);

  async function updateSubscription(payload) {
    setBusy(true);
    setError("");
    try {
      await updateGovernmentEntitySubscription(entity.id, payload);
      await onUpdated();
    } catch (requestError) {
      setError(translateApiError(requestError.message, lang) || text.updateError);
    } finally {
      setBusy(false);
    }
  }

  async function saveSubscription() {
    await updateSubscription({
      subscription_plan: plan,
      subscription_end: endDate ? `${endDate}T23:59:59+00:00` : "",
    });
  }

  const cardClass = isDark
    ? "border-violet-900/70 bg-[#0d1034] text-slate-100 shadow-violet-950/30"
    : "border-blue-100 bg-white text-slate-950 shadow-blue-100/30";
  const inputClass = isDark
    ? "border-violet-800 bg-[#080b27] text-slate-100"
    : "border-blue-100 bg-white text-slate-700";

  return (
    <div className={`rounded-2xl border p-5 shadow-sm ${cardClass}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-black">{entity.name}</h3>
          <p className={isDark ? "text-xs text-slate-400" : "text-xs text-slate-400"}>/{entity.slug}</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-bold ${badgeClass}`}>
          {STATUS_LABELS[lang][status] || status}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className={`text-xs font-bold ${isDark ? "text-slate-300" : "text-slate-500"}`}>
          {text.plan}
          <select value={plan} onChange={(e) => setPlan(e.target.value)}
            className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm ${inputClass}`}>
            <option value="PILOT">PILOT</option>
            <option value="ENTERPRISE">ENTERPRISE</option>
            <option value="DEDICATED_GOVERNMENT">DEDICATED_GOVERNMENT</option>
          </select>
        </label>
        <label className={`text-xs font-bold ${isDark ? "text-slate-300" : "text-slate-500"}`}>
          {text.subscriptionEnds}
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
            className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm ${inputClass}`} />
        </label>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={saveSubscription}
          className="rounded-lg border border-blue-500/40 px-3 py-2 text-xs font-black text-blue-500 disabled:opacity-50">
          {text.saveSubscription}
        </button>
        <button type="button" disabled={busy || status === "EXPIRED"} onClick={() => updateSubscription({ status: "ACTIVE" })}
          title={status === "EXPIRED" ? text.extendReactivate : text.activateTitle}
          className="rounded-lg border border-emerald-400/60 px-3 py-2 text-xs font-black text-emerald-500 disabled:opacity-50">
          {text.activate}
        </button>
        <button type="button" disabled={busy} onClick={() => updateSubscription({ status: "SUSPENDED" })}
          className="rounded-lg border border-amber-400/60 px-3 py-2 text-xs font-black text-amber-500 disabled:opacity-50">
          {text.suspend}
        </button>
        {[30, 90, 365].map((days) => (
          <button key={days} type="button" disabled={busy}
            onClick={() => updateSubscription({ status: "ACTIVE", extend_days: days })}
            className={`rounded-lg border px-3 py-2 text-xs font-black disabled:opacity-50 ${
              isDark ? "border-violet-800 text-slate-400" : "border-blue-100 text-slate-600"
            }`}>
            +{days} {text.days}
          </button>
        ))}
      </div>
      {error && <p className="mt-2 text-xs font-semibold text-red-500">{error}</p>}

      <div className={`mt-4 grid grid-cols-4 gap-2 border-t pt-3 text-center ${isDark ? "border-violet-900" : "border-blue-50"}`}>
        {[
          ["users", text.users],
          ["services", text.services],
          ["agents", text.agents],
          ["published_agents", text.published],
        ].map(([key, label]) => (
          <div key={key}>
            <div className="text-sm font-black">{counts[key] ?? 0}</div>
            <div className={`text-[10px] font-bold uppercase tracking-wide ${isDark ? "text-slate-400" : "text-slate-400"}`}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddEntityForm({ onCreated, lang, isDark }) {
  const text = COPY[lang];
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    entity_name: "", slug: "", subscription_plan: "PILOT",
    admin_name: "", admin_email: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await createGovernmentEntity(form);
      setForm({ entity_name: "", slug: "", subscription_plan: "PILOT", admin_name: "", admin_email: "" });
      setOpen(false);
      onCreated();
    } catch (requestError) {
      setError(translateApiError(requestError.message, lang) || text.createError);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        type="button"
        className="rounded-2xl bg-blue-600 px-5 py-3 font-black text-white transition hover:bg-blue-700"
      >
        {text.addEntity}
      </button>
    );
  }

  const formClass = isDark
    ? "border-violet-900/70 bg-[#0d1034] text-slate-100"
    : "border-blue-100 bg-white text-slate-950";
  const inputClass = isDark
    ? "border-violet-800 bg-[#080b27] text-slate-100 placeholder:text-slate-500"
    : "border-blue-100 bg-white text-slate-950";

  return (
    <form onSubmit={submit} className={`rounded-2xl border p-6 shadow-sm ${formClass}`}>
      <h3 className="mb-4 font-black">{text.addEntityTitle}</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <input required placeholder={text.entityName} value={form.entity_name}
          onChange={(e) => update("entity_name", e.target.value)}
          className={`rounded-xl border px-4 py-2 text-sm ${inputClass}`} />
        <input required placeholder={text.slug} value={form.slug}
          onChange={(e) => update("slug", e.target.value)}
          className={`rounded-xl border px-4 py-2 text-sm ${inputClass}`} />
        <select value={form.subscription_plan}
          onChange={(e) => update("subscription_plan", e.target.value)}
          className={`rounded-xl border px-4 py-2 text-sm ${inputClass}`}>
          <option value="PILOT">PILOT</option>
          <option value="ENTERPRISE">ENTERPRISE</option>
          <option value="DEDICATED_GOVERNMENT">DEDICATED_GOVERNMENT</option>
        </select>
        <div />
        <input required placeholder={text.adminName} value={form.admin_name}
          onChange={(e) => update("admin_name", e.target.value)}
          className={`rounded-xl border px-4 py-2 text-sm ${inputClass}`} />
        <input required type="email" placeholder={text.adminEmail} value={form.admin_email}
          onChange={(e) => update("admin_email", e.target.value)}
          className={`rounded-xl border px-4 py-2 text-sm ${inputClass}`} />
      </div>
      {error && <p className="mt-3 text-sm font-semibold text-red-500">{error}</p>}
      <div className="mt-4 flex gap-3">
        <button type="submit" disabled={busy}
          className="rounded-xl bg-blue-600 px-5 py-2 font-black text-white disabled:opacity-60">
          {busy ? text.creating : text.create}
        </button>
        <button type="button" onClick={() => setOpen(false)}
          className={`rounded-xl border px-5 py-2 font-bold ${isDark ? "border-violet-800 text-slate-300" : "border-blue-100 text-slate-500"}`}>
          {text.cancel}
        </button>
      </div>
    </form>
  );
}

export default function PlatformAdminPage() {
  const { isAuthenticated, loading: authLoading, role, currentUser, logout } = useAuth();
  const { lang, setLang, dir } = useLanguage();
  const { isDark, toggleTheme } = useTheme();
  const text = COPY[lang];

  const [entities, setEntities] = useState([]);
  const [stats, setStats] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);

  async function reload() {
    setLoading(true);
    try {
      const [entitiesData, statsData] = await Promise.all([
        listGovernmentEntities(),
        getPlatformStats(),
      ]);
      setEntities(entitiesData.entities || []);
      setStats(statsData);
      setLoadError("");
    } catch (requestError) {
      setLoadError(translateApiError(requestError.message, lang) || text.loadError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthenticated && role === "platform_admin") {
      reload();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, role]);

  if (authLoading) return null;
  if (!isAuthenticated) return <LoginGate />;

  if (role !== "platform_admin") {
    return (
      <div className={`min-h-screen px-6 py-16 flex items-center justify-center ${
        isDark ? "bg-[#05071a] text-slate-100" : "bg-[#f7faff] text-slate-950"
      }`}>
        <div className={`max-w-md rounded-[30px] border p-10 text-center shadow-xl ${
          isDark ? "border-violet-900 bg-[#0d1034]" : "border-blue-100 bg-white"
        }`}>
          <h1 className="text-2xl font-black">{text.adminOnly}</h1>
          <p className={`mt-4 ${isDark ? "text-slate-400" : "text-slate-500"}`}>
            {text.adminOnlyBody} ({role || "unknown"})
          </p>
          <a href="/" className="mt-8 inline-block rounded-2xl bg-blue-600 px-6 py-3 font-black text-white">
            {text.backToWorkspace}
          </a>
        </div>
      </div>
    );
  }

  const summaryCards = [
    ["total_entities", text.totalEntities],
    ["ACTIVE", text.active],
    ["PILOT", text.pilot],
    ["SUSPENDED", text.suspended],
    ["EXPIRED", text.expired],
  ];

  const activityCards = [
    ["total_users", text.totalUsers],
    ["total_services", text.totalServices],
    ["total_analyses", text.totalAnalyses],
    ["total_agents", text.totalAgents],
  ];

  return (
    <div
      dir={dir}
      className={`min-h-screen px-6 py-12 transition-colors ${
        isDark ? "bg-[#05071a] text-slate-100" : "bg-[#f7faff] text-slate-950"
      }`}
    >
      <div className="mx-auto max-w-5xl">
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div>
            <span className="text-xs font-bold uppercase tracking-widest text-blue-500">
              {text.platformAdministration}
            </span>
            <h1 className="text-3xl font-black">{text.governmentEntities}</h1>
          </div>

          <div className="flex items-center gap-2">
            <div className={`flex rounded-xl border p-1 ${isDark ? "border-violet-800 bg-[#0d1034]" : "border-blue-100 bg-white"}`}>
              <button
                type="button"
                onClick={() => setLang("ar")}
                className={`rounded-lg px-3 py-2 text-xs font-black transition ${
                  lang === "ar" ? "bg-violet-600 text-white" : isDark ? "text-slate-300" : "text-slate-600"
                }`}
              >
                {text.arabic}
              </button>
              <button
                type="button"
                onClick={() => setLang("en")}
                className={`rounded-lg px-3 py-2 text-xs font-black transition ${
                  lang === "en" ? "bg-violet-600 text-white" : isDark ? "text-slate-300" : "text-slate-600"
                }`}
              >
                {text.english}
              </button>
            </div>

            <button
              type="button"
              onClick={toggleTheme}
              className={`rounded-xl border px-3 py-2 text-sm font-black transition ${
                isDark
                  ? "border-violet-800 bg-[#0d1034] text-slate-100 hover:bg-[#15194a]"
                  : "border-blue-100 bg-white text-slate-700 hover:bg-blue-50"
              }`}
              aria-label={isDark ? text.light : text.dark}
              title={isDark ? text.light : text.dark}
            >
              {isDark ? "☀︎" : "☾"}
            </button>

            <button
              type="button"
              onClick={() => { logout(); window.location.href = "/login"; }}
              className={`rounded-xl border px-4 py-2 text-sm font-black text-red-500 ${
                isDark ? "border-red-900/70 bg-[#0d1034] hover:bg-red-950/30" : "border-red-200 bg-white hover:bg-red-50"
              }`}
            >
              {text.signOut}
            </button>
          </div>
        </div>

        <p className={`mb-6 text-sm ${isDark ? "text-slate-400" : "text-slate-500"}`}>
          {text.intro}
        </p>

        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {summaryCards.map(([key, label]) => (
            <div key={key} className={`rounded-2xl border p-4 text-center shadow-sm ${
              isDark ? "border-violet-900/70 bg-[#0d1034]" : "border-blue-100 bg-white"
            }`}>
              <div className="text-2xl font-black">
                {key === "total_entities" ? (stats?.total_entities ?? 0) : (stats?.by_status?.[key] ?? 0)}
              </div>
              <div className={`text-xs font-bold ${isDark ? "text-slate-400" : "text-slate-400"}`}>{label}</div>
            </div>
          ))}
        </div>

        <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {activityCards.map(([key, label]) => (
            <div key={key} className={`rounded-2xl border p-4 text-center shadow-sm ${
              isDark ? "border-violet-900/70 bg-[#0d1034]" : "border-blue-100 bg-white"
            }`}>
              <div className="text-2xl font-black">{stats?.[key] ?? 0}</div>
              <div className={`text-xs font-bold ${isDark ? "text-slate-400" : "text-slate-400"}`}>{label}</div>
            </div>
          ))}
          <div className={`rounded-2xl border p-4 text-center shadow-sm ${
            isDark ? "border-emerald-900/50 bg-emerald-950/30" : "border-emerald-100 bg-emerald-50"
          }`}>
            <div className="text-2xl font-black text-emerald-500">{stats?.total_published_agents ?? 0}</div>
            <div className="text-xs font-bold text-emerald-500">{text.publishedAgents}</div>
          </div>
        </div>

        <div className="mb-6">
          <AddEntityForm onCreated={reload} lang={lang} isDark={isDark} />
        </div>

        {loadError && <p className="mb-4 text-sm font-semibold text-red-500">{loadError}</p>}
        {loading ? (
          <p className={isDark ? "text-slate-400" : "text-slate-400"}>{text.loading}</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {entities.map((entity) => (
              <EntityCard key={entity.id} entity={entity} onUpdated={reload} lang={lang} isDark={isDark} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
