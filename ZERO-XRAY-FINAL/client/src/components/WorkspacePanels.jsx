import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { useLanguage } from "../i18n/useLanguage";
import { translateApiError } from "../i18n/apiErrors";
import {
  createDataSource,
  createService,
  createIntegration,
  importOpenApi,
  refreshOpenApi,
  listIntegrationOperations,
  createTenantUser,
  assignUserToService,
  unassignUserFromService,
  getAuditLog,
  listAgents,
  listDataSources,
  listIntegrations,
  listServiceAnalyses,
  listServices,
  listServiceAssignments,
  listTenantUsers,
  getServiceContext,
  setUserStatus,
  updateUserRole,
  getStorageInfo
} from "../api";
import { extractFromExcel, extractFromPdf, extractFromWord, extractFromImage } from "../lib/fileExtract";
import { deriveJourneyFromText } from "../lib/serviceText";

function Card({ children }) {
  return (
    <div className="workspace-surface rounded-2xl border border-blue-100 bg-white p-5 shadow-sm shadow-blue-100/30">
      {children}
    </div>
  );
}

function ErrorBanner({ message, lang }) {
  if (!message) return null;
  // Translated HERE, at render time, not where the error is caught: every
  // caller above stores the RAW backend message, and this is the single
  // place `lang` is guaranteed fresh from the current render (a value read
  // inside a useEffect closure with an empty dependency array would still
  // be whatever `lang` was when the effect first ran, not the language the
  // user has actually switched to since -- see the language-switch
  // scenario this shared component avoids).
  return <p className="mb-4 text-sm font-semibold text-red-600">{translateApiError(message, lang)}</p>;
}

function EmptyState({ label }) {
  return <p className="text-sm text-slate-400">{label}</p>;
}

// --- Overview -----------------------------------------------------------

export function OverviewPanel({ onStartAnalysis }) {
  const { currentTenant, role } = useAuth();
  const { lang } = useLanguage();
  const [counts, setCounts] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([listServices(), listAgents()])
      .then(([services, agents]) => {
        if (cancelled) return;
        setCounts({
          services: services.services.length,
          agents: agents.agents.length,
          published: agents.agents.filter((a) => a.status === "PUBLISHED").length,
        });
      })
      .catch((e) => !cancelled && setError(e.message || "Could not load overview."));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h2 className="mb-1 text-2xl font-black">{currentTenant?.name} {lang === "ar" ? "— مساحة العمل" : "Workspace"}</h2>
      <p className="mb-6 text-sm text-slate-400">
        {lang === "ar" ? `الصلاحية: ${{entity_admin:"مدير الجهة",service_owner:"مسؤول الخدمة",analyst:"محلل",viewer:"مشاهدة فقط"}[role] || role}` : `Signed in as ${role}`}
      </p>
      <ErrorBanner message={error} lang={lang} />
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {["services", "agents", "published"].map((key) => (
          <Card key={key}>
            <div className="text-2xl font-black">{counts ? counts[key] : "…"}</div>
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">
              {lang === "ar"
                ? ({ services: "الخدمات", agents: "الوكلاء", published: "الخدمات المنشورة" }[key])
                : (key === "published" ? "Published Services" : key)}
            </div>
          </Card>
        ))}
      </div>
      <button
        type="button"
        onClick={onStartAnalysis}
        className="rounded-2xl bg-blue-600 px-6 py-3 font-black text-white transition hover:bg-blue-700"
      >
        {lang === "ar" ? "+ تحليل خدمة جديدة" : "+ New ZERO X-RAY Analysis"}
      </button>
    </div>
  );
}

// --- Services / Analyses --------------------------------------------------

export function ServicesPanel({ onAnalyzeService }) {
  const { lang } = useLanguage();
  const { hasPermission } = useAuth();
  const [services, setServices] = useState(null);
  const [selected, setSelected] = useState(null);
  const [analyses, setAnalyses] = useState(null);
  const [context, setContext] = useState(null);
  const [error, setError] = useState("");
  const [showWizard, setShowWizard] = useState(false);
  const [step, setStep] = useState(1);
  const [sources, setSources] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [form, setForm] = useState({
    service_name: "", description: "", language: lang,
    data_source_ids: [], integration_ids: [],
  });

  const ar = lang === "ar";
  function reload() {
    listServices().then((d) => setServices(d.services)).catch((e) => setError(e.message || "Could not load services."));
  }
  useEffect(reload, []);
  useEffect(() => { setForm((f) => ({ ...f, language: lang })); }, [lang]);

  function startWizard() {
    setError(""); setStep(1); setShowWizard(true);
    Promise.all([listDataSources(), listIntegrations()])
      .then(([d, i]) => { setSources(d.data_sources || []); setIntegrations(i.integrations || []); })
      .catch((e) => setError(e.message));
  }

  function toggle(field, id) {
    setForm((f) => ({ ...f, [field]: f[field].includes(id) ? f[field].filter((x) => x !== id) : [...f[field], id] }));
  }

  async function createAndAnalyze() {
    setError("");
    try {
      const service = await createService(form);
      setShowWizard(false);
      reload();
      if (onAnalyzeService) {
        onAnalyzeService({
          service_id: service.id,
          service_name: form.service_name,
          description: form.description,
          steps: [], documents: [], actors: [], approvals: [], waiting_times: [],
          manual_actions: [], digital_actions: [], dependencies: [], branch_visits: 0,
          protected_steps: [], lang: form.language,
          data_source_ids: form.data_source_ids,
          integration_ids: form.integration_ids,
        });
      }
    } catch (e) { setError(e.message || "Could not create service."); }
  }

  function openService(service) {
    setSelected(service); setAnalyses(null); setContext(null);
    Promise.all([listServiceAnalyses(service.id), getServiceContext(service.id)])
      .then(([a, c]) => { setAnalyses(a.analyses); setContext(c); })
      .catch((e) => setError(e.message || "Could not load service."));
  }

  return (
    <div dir={ar ? "rtl" : "ltr"}>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-black">{ar ? "الخدمات" : "Services"}</h2>
          <p className="mt-1 text-sm text-slate-400">{ar ? "كل خدمة تربط بمصادر المعرفة والأنظمة التي يحتاجها الوكيل." : "Each service is linked to the knowledge and systems its Agent may use."}</p>
        </div>
        {hasPermission("tenant:analyze") && <button type="button" onClick={startWizard} className="rounded-2xl bg-blue-600 px-5 py-3 font-black text-white">{ar ? "+ إضافة خدمة" : "+ Add Service"}</button>}
      </div>
      <ErrorBanner message={error} lang={lang} />

      {showWizard && <div className="mb-7 rounded-3xl border border-blue-100 bg-white p-6 shadow-sm">
        <div className="mb-5 flex gap-2 text-xs font-bold text-slate-400">
          {[1,2,3,4].map((n) => <span key={n} className={`rounded-full px-3 py-1 ${step===n ? "bg-blue-600 text-white" : "bg-slate-100"}`}>{n}</span>)}
        </div>
        {step === 1 && <div className="space-y-4">
          <h3 className="text-lg font-black">{ar ? "1. معلومات الخدمة" : "1. Service Information"}</h3>
          <input className="w-full rounded-xl border border-blue-100 px-4 py-3" placeholder={ar ? "اسم الخدمة" : "Service name"} value={form.service_name} onChange={(e)=>setForm(f=>({...f,service_name:e.target.value}))}/>
          <textarea className="min-h-32 w-full rounded-xl border border-blue-100 px-4 py-3" placeholder={ar ? "وصف الخدمة، الهدف، الرسوم، القواعد أو الخطوات الحالية" : "Description, outcome, fees, rules or current steps"} value={form.description} onChange={(e)=>setForm(f=>({...f,description:e.target.value}))}/>
        </div>}
        {step === 2 && <div>
          <h3 className="mb-1 text-lg font-black">{ar ? "2. اختر مصادر البيانات" : "2. Select Data Sources"}</h3>
          <p className="mb-4 text-sm text-slate-400">{ar ? "هذه المصادر تساعد ZERO X-RAY على فهم قواعد الخدمة ورسومها ومستنداتها." : "These sources teach ZERO X-RAY the service rules, fees and documents."}</p>
          {sources.length===0 ? <EmptyState label={ar ? "لا توجد مصادر بعد. أضفها من مصادر البيانات أولاً." : "No sources yet. Add them from Data Sources first."}/> : <div className="grid gap-3 sm:grid-cols-2">{sources.map((x)=><label key={x.id} className="flex cursor-pointer items-center gap-3 rounded-xl border border-blue-100 p-3"><input type="checkbox" checked={form.data_source_ids.includes(x.id)} onChange={()=>toggle("data_source_ids",x.id)}/><span><b>{x.name}</b><small className="block text-slate-400">{x.type}</small></span></label>)}</div>}
        </div>}
        {step === 3 && <div>
          <h3 className="mb-1 text-lg font-black">{ar ? "3. اختر الأنظمة وواجهات API" : "3. Select Systems & APIs"}</h3>
          <p className="mb-4 text-sm text-slate-400">{ar ? "CONNECTED يمكن للوكيل تنفيذه، SANDBOX للتجربة فقط، NOT CONNECTED سيظهر كتكامل مطلوب." : "CONNECTED can execute, SANDBOX is demo-only, NOT CONNECTED becomes Integration Required."}</p>
          {integrations.length===0 ? <EmptyState label={ar ? "لا توجد تكاملات بعد. أضفها من التكاملات أولاً." : "No integrations yet. Add them from Integrations first."}/> : <div className="grid gap-3 sm:grid-cols-2">{integrations.map((x)=><label key={x.id} className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-blue-100 p-3"><span className="flex gap-3"><input type="checkbox" checked={form.integration_ids.includes(x.id)} onChange={()=>toggle("integration_ids",x.id)}/><span><b>{x.name}</b><small className="block text-slate-400">{x.type}</small></span></span><StatusPill status={x.status}/></label>)}</div>}
        </div>}
        {step === 4 && <div>
          <h3 className="mb-4 text-lg font-black">{ar ? "4. مراجعة ثم تحليل" : "4. Review & Analyze"}</h3>
          <div className="grid gap-3 sm:grid-cols-3"><Card><b>{form.service_name || "—"}</b><small className="block text-slate-400">{ar ? "الخدمة" : "Service"}</small></Card><Card><b>{form.data_source_ids.length}</b><small className="block text-slate-400">{ar ? "مصادر بيانات" : "Data sources"}</small></Card><Card><b>{form.integration_ids.length}</b><small className="block text-slate-400">{ar ? "تكاملات" : "Integrations"}</small></Card></div>
          <p className="mt-4 text-sm text-slate-500">{ar ? "ZERO X-RAY سيستخدم فقط العناصر التي اخترتها لهذه الخدمة، ولن يفترض وجود أي نظام غير مربوط." : "ZERO X-RAY will use only the items selected for this service and will not invent unavailable systems."}</p>
        </div>}
        <div className="mt-6 flex justify-between gap-3">
          <button type="button" onClick={()=> step===1 ? setShowWizard(false) : setStep(step-1)} className="rounded-xl border border-slate-200 px-5 py-2 font-bold">{ar ? "رجوع" : "Back"}</button>
          {step<4 ? <button type="button" disabled={step===1 && !form.service_name.trim()} onClick={()=>setStep(step+1)} className="rounded-xl bg-blue-600 px-5 py-2 font-bold text-white disabled:opacity-40">{ar ? "التالي" : "Next"}</button> : <button type="button" onClick={createAndAnalyze} className="rounded-xl bg-blue-600 px-5 py-2 font-black text-white">{ar ? "تشغيل ZERO X-RAY" : "Run ZERO X-RAY"}</button>}
        </div>
      </div>}

      {services === null ? <EmptyState label={ar ? "جارٍ التحميل..." : "Loading..."}/> : services.length===0 ? <EmptyState label={ar ? "لا توجد خدمات بعد." : "No services yet."}/> : <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{services.map((s)=><button key={s.id} type="button" onClick={()=>openService(s)} className={`rounded-2xl border p-4 text-start shadow-sm ${selected?.id===s.id?"border-blue-400 bg-blue-50":"border-blue-100 bg-white"}`}><div className="font-black">{s.service_name}</div><div className="text-xs text-slate-400">{s.language||"en"} · {s.created_at?.slice(0,10)}</div></button>)}</div>}

      {selected && <div className="mt-6 rounded-3xl border border-blue-100 bg-white p-5">
        <h3 className="text-xl font-black">{selected.service_name}</h3>
        {context && <><div className="mt-4 grid gap-3 sm:grid-cols-4"><Card><b>{context.data_sources.length}</b><small className="block text-slate-400">{ar?"مصادر المعرفة":"Knowledge"}</small></Card><Card><b>{context.connected_count}</b><small className="block text-slate-400">CONNECTED</small></Card><Card><b>{context.sandbox_count}</b><small className="block text-slate-400">SANDBOX</small></Card><Card><b>{context.integration_required_count}</b><small className="block text-slate-400">INTEGRATION REQUIRED</small></Card></div><div className="mt-4 grid gap-3 sm:grid-cols-2"><Card><b>{ar?"مصادر المعرفة":"Knowledge Sources"}</b><div className="mt-2 text-sm text-slate-400">{context.data_sources?.length ? context.data_sources.map((x)=>x.name).join(" · ") : (ar?"لا توجد مصادر مرتبطة":"No linked sources")}</div></Card><Card><b>{ar?"الأنظمة المسموح بها":"Allowed Systems"}</b><div className="mt-2 text-sm text-slate-400">{context.integrations?.length ? context.integrations.map((x)=>`${x.name} (${x.status})`).join(" · ") : (ar?"لا توجد أنظمة مرتبطة":"No linked systems")}</div></Card></div><div className="mt-4"><b>{ar?"جاهزية أدوات الوكيل":"Agent tool readiness"}: {context.agent_readiness}%</b><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-blue-600" style={{width:`${context.agent_readiness}%`}}/></div></div></>}
        <h4 className="mb-2 mt-5 font-black">{ar?"سجل التحليلات":"Analysis history"}</h4>
        {analyses===null ? <EmptyState label="Loading..."/> : analyses.length===0 ? <EmptyState label={ar?"لا توجد تحليلات":"No analyses"}/> : <ul className="space-y-2">{analyses.map((a)=><li key={a.id} className="rounded-xl border border-blue-100 p-3 text-sm"><b>{a.status}</b><span className="ms-2 text-slate-400">{a.created_at?.slice(0,19).replace("T"," ")}</span></li>)}</ul>}
      </div>}
    </div>
  );
}


// --- Analyses (all analyses across every service, flattened) -----------

export function AnalysesPanel() {
  const { lang } = useLanguage();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    listServices()
      .then(async (d) => {
        const services = d.services;
        const perService = await Promise.all(
          services.map((s) =>
            listServiceAnalyses(s.id)
              .then((a) => a.analyses.map((an) => ({ ...an, service_name: s.service_name })))
              .catch(() => [])
          )
        );
        if (cancelled) return;
        const flattened = perService.flat().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
        setRows(flattened);
      })
      .catch((e) => !cancelled && setError(e.message || "Could not load analyses."));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h2 className="mb-4 text-2xl font-black">Analyses</h2>
      <ErrorBanner message={error} lang={lang} />
      {rows === null ? (
        <EmptyState label="Loading..." />
      ) : rows.length === 0 ? (
        <EmptyState label="No analyses yet -- run a ZERO X-RAY analysis to create one." />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-blue-100 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-400">
              <tr>
                <th className="px-4 py-2">Service</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className="border-t border-blue-50">
                  <td className="px-4 py-2 font-bold">{a.service_name}</td>
                  <td className="px-4 py-2 text-slate-500">{a.status}</td>
                  <td className="px-4 py-2 text-slate-400">{a.created_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- Agents ------------------------------------------------------------

export function AgentsPanel() {
  const { lang } = useLanguage();
  const [agents, setAgents] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listAgents()
      .then((d) => setAgents(d.agents))
      .catch((e) => setError(e.message || "Could not load agents."));
  }, []);

  return (
    <div>
      <h2 className="mb-4 text-2xl font-black">Agents</h2>
      <ErrorBanner message={error} lang={lang} />
      {agents === null ? (
        <EmptyState label="Loading..." />
      ) : agents.length === 0 ? (
        <EmptyState label="No agents published yet." />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {agents.map((a) => (
            <Card key={a.id}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-black">{a.name}</div>
                  <div className="text-xs text-slate-400">/{a.published_slug}</div>
                </div>
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">
                  {a.status}
                </span>
              </div>
              <a
                href={`/service/${a.published_slug}`}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-block text-xs font-bold text-blue-600"
              >
                Open public URL →
              </a>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Data Sources --------------------------------------------------------

const DATA_SOURCE_TYPES = ["PDF", "EXCEL", "TEXT", "SERVICE_CATALOGUE", "POLICIES", "INTERNAL_KNOWLEDGE_BASE"];
const INTEGRATION_TYPES = ["IDENTITY_PROVIDER", "UAE_PASS", "GOVERNMENT_API", "INTERNAL_API", "PAYMENT_GATEWAY", "CRM", "DOCUMENT_MANAGEMENT", "NOTIFICATIONS"];

function StatusPill({ status }) {
  const colors = {
    CONNECTED: "bg-emerald-50 text-emerald-700 border-emerald-200",
    SANDBOX: "bg-blue-50 text-blue-700 border-blue-200",
    NOT_CONNECTED: "bg-slate-100 text-slate-500 border-slate-200",
    READY: "bg-emerald-50 text-emerald-700 border-emerald-200",
    PROCESSING: "bg-amber-50 text-amber-700 border-amber-200",
    FAILED: "bg-red-50 text-red-700 border-red-200",
  };
  return <span className={`rounded-full border px-3 py-1 text-xs font-bold ${colors[status] || colors.NOT_CONNECTED}`}>{status}</span>;
}

export function DataSourcesPanel() {
  const { hasPermission } = useAuth();
  const { lang } = useLanguage();
  const ar = lang === "ar";
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "", type: "PDF", content: "", original_filename: "",
    mime_type: "", file_content_base64: "",
  });

  function reload(){ listDataSources().then(d=>setItems(d.data_sources)).catch(e=>setError(e.message)); }
  useEffect(reload,[]);

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const value = String(reader.result || "");
        resolve(value.includes(",") ? value.split(",", 2)[1] : value);
      };
      reader.onerror = () => reject(reader.error || new Error("Could not read file."));
      reader.readAsDataURL(file);
    });
  }

  async function readFile(file){
    if(!file) return;
    setBusy(true); setError("");
    try{
      const n=file.name.toLowerCase(); let text="";
      if(n.endsWith(".pdf")) text=await extractFromPdf(file);
      else if(n.endsWith(".xlsx")||n.endsWith(".xls")||n.endsWith(".csv")) text=await extractFromExcel(file);
      else if(n.endsWith(".docx")) text=await extractFromWord(file);
      else if(file.type.startsWith("image/")) text=await extractFromImage(file);
      else text=await file.text();
      const encoded = await fileToBase64(file);
      setForm(f=>({
        ...f,
        name:f.name||file.name,
        content:text,
        original_filename:file.name,
        mime_type:file.type || "application/octet-stream",
        file_content_base64:encoded,
      }));
    }catch(e){ setError(e.message||"Could not read file."); }
    finally{ setBusy(false); }
  }

  async function submit(e){
    e.preventDefault(); setError("");
    try{
      await createDataSource({
        name:form.name,
        type:form.type,
        status:"READY",
        classification:"TENANT_PRIVATE_SOURCE",
        configuration:{content:form.content},
        original_filename:form.original_filename || null,
        mime_type:form.mime_type || null,
        file_content_base64:form.file_content_base64 || null,
      });
      setForm({name:"",type:"PDF",content:"",original_filename:"",mime_type:"",file_content_base64:""});
      reload();
    }catch(err){ setError(err.message || "Could not create data source."); }
  }

  return <div dir={ar?"rtl":"ltr"}>
    <h2 className="mb-1 text-2xl font-black">{ar?"مصادر بيانات الجهة":"Organization Data Sources"}</h2>
    <p className="mb-5 text-sm text-slate-400">{ar?"ارفع الملفات التي تشرح قواعد الخدمة ورسومها ومستنداتها. يتم حفظ الملف داخل مساحة جهتك، ويظهر READY بعد الحفظ.":"Upload files that explain service rules, fees and documents. The file is stored inside your tenant workspace and becomes READY when saved."}</p>
    <ErrorBanner message={error} lang={lang} />
    {hasPermission("tenant:manage_data_sources")&&<form onSubmit={submit} className="mb-6 space-y-4 rounded-2xl border border-blue-100 bg-white p-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <input required placeholder={ar?"اسم المصدر، مثال: رسوم صندوق البريد":"Source name, e.g. PO Box Fees"} value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} className="rounded-xl border border-blue-100 px-3 py-2"/>
        <select value={form.type} onChange={e=>setForm(f=>({...f,type:e.target.value}))} className="rounded-xl border border-blue-100 px-3 py-2">{DATA_SOURCE_TYPES.map(t=><option key={t}>{t}</option>)}</select>
      </div>
      <div className="rounded-xl border border-dashed border-blue-200 bg-blue-50/30 p-4">
        <div className="mb-2 font-bold">{ar?"ارفع ملف الجهة":"Upload organization file"}</div>
        <input type="file" onChange={e=>readFile(e.target.files?.[0])} className="block w-full text-sm"/>
        {form.original_filename&&<small className="mt-2 block text-emerald-700">✓ {form.original_filename}</small>}
      </div>
      <textarea value={form.content} onChange={e=>setForm(f=>({...f,content:e.target.value}))} placeholder={ar?"أو الصق سياسة/رسوم/متطلبات الخدمة هنا. النص المستخرج من الملف سيظهر هنا للمراجعة.":"Or paste policy/fees/requirements here. Extracted text from the uploaded file appears here for review."} className="min-h-32 w-full rounded-xl border border-blue-100 p-3"/>
      <button disabled={busy} className="rounded-xl bg-blue-600 px-4 py-2 font-bold text-white">{busy?(ar?"جارٍ قراءة الملف...":"Reading file..."):(ar?"حفظ مصدر البيانات":"Save data source")}</button>
    </form>}
    {items===null?<EmptyState label="Loading..."/>:items.length===0?<EmptyState label={ar?"لا توجد مصادر بعد. ارفع أول ملف خاص بالجهة.":"No data sources yet. Upload the organization's first file."}/>:<div className="grid gap-3 sm:grid-cols-2">{items.map(d=><Card key={d.id}><div className="flex items-start justify-between gap-3"><div><b>{d.name}</b><small className="block text-slate-400">{d.type}{d.original_filename?` · ${d.original_filename}`:""}</small>{d.created_at&&<small className="mt-1 block text-slate-400">{ar?"تاريخ الرفع":"Uploaded"}: {d.created_at.slice(0,10)}</small>}<small className="mt-2 block text-slate-500">{(d.configuration?.content||"").slice(0,140)}{(d.configuration?.content||"").length>140?"…":""}</small>{d.storage_path&&<small className="mt-2 block text-emerald-700">{ar?"محفوظ داخل مساحة الجهة":"Stored in tenant workspace"}</small>}</div><StatusPill status={d.status}/></div></Card>)}</div>}
  </div>;
}


export function IntegrationsPanel({ onBuildAgent }) {
  const { hasPermission, role } = useAuth();
  const { lang } = useLanguage();
  const ar = lang === "ar";
  const canImportOpenApi = hasPermission("tenant:manage_integrations") || role === "service_owner";
  const [items, setItems] = useState(null);
  const [services, setServices] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [operations, setOperations] = useState({});
  const [form, setForm] = useState({name:"",type:"CRM",status:"NOT_CONNECTED",endpoint:""});
  const [openapi, setOpenapi] = useState({url:"",service_id:"",environment:"SANDBOX",name:""});

  function reload(){
    Promise.all([listIntegrations(), listServices()])
      .then(([integrationsData, servicesData]) => {
        setItems(integrationsData.integrations || []);
        setServices(servicesData.services || []);
        setOpenapi((f) => ({...f, service_id: f.service_id || servicesData.services?.[0]?.id || ""}));
      })
      .catch(e=>setError(e.message));
  }
  useEffect(reload,[]);

  async function submit(e){
    e.preventDefault();setError("");setMessage("");
    try{
      await createIntegration({name:form.name,type:form.type,status:form.status,config:{endpoint:form.endpoint||null}});
      setForm({name:"",type:"CRM",status:"NOT_CONNECTED",endpoint:""});reload();
    }catch(err){setError(err.message || "Could not create integration.");}
  }

  async function importSpec(e){
    e.preventDefault(); setError(""); setMessage(""); setBusy(true);
    try {
      const result = await importOpenApi(openapi.service_id, {
        url: openapi.url,
        environment: openapi.environment,
        name: openapi.name || null,
        integration_type: "GOVERNMENT_API",
      });
      setMessage(ar
        ? `تم استيراد ${result.operations_discovered} عملية API من ${result.title || "OpenAPI"}.`
        : `Imported ${result.operations_discovered} API operations from ${result.title || "OpenAPI"}.`);
      const selectedService = services.find((service) => service.id === openapi.service_id);
      setOpenapi((f)=>({...f,url:"",name:""}));
      reload();
      if (selectedService && onBuildAgent && hasPermission("tenant:analyze")) {
        const history = await listServiceAnalyses(selectedService.id);
        const previousService = (history.analyses || []).find((analysis) => analysis?.result?.service)?.result?.service;
        if (previousService) {
          const sourceText = selectedService.description || previousService.description || "";
          const reconstructed = deriveJourneyFromText(
            sourceText,
            selectedService.service_name || previousService.service_name || ""
          );
          onBuildAgent({
            ...previousService,
            service_id: selectedService.id,
            service_name: selectedService.service_name || previousService.service_name,
            description: sourceText,
            // Do not reuse a stale AI-derived Current Journey. Rebuild only
            // the evidence-backed current steps from the original service text.
            steps: reconstructed.steps,
            lang: selectedService.language || previousService.lang || lang,
          });
        }
      }
    } catch (err) {
      setError(err.message || (ar ? "تعذر استيراد Swagger/OpenAPI." : "Could not import Swagger/OpenAPI."));
    } finally { setBusy(false); }
  }

  async function toggleOperations(integrationId) {
    if (expanded[integrationId]) {
      setExpanded((x)=>({...x,[integrationId]:false}));
      return;
    }
    try {
      if (!operations[integrationId]) {
        const data = await listIntegrationOperations(integrationId);
        setOperations((x)=>({...x,[integrationId]:data.operations || []}));
      }
      setExpanded((x)=>({...x,[integrationId]:true}));
    } catch (err) { setError(err.message || "Could not load API operations."); }
  }

  async function refreshSpec(integrationId) {
    setError(""); setMessage(""); setBusy(true);
    try {
      const result = await refreshOpenApi(integrationId);
      const data = await listIntegrationOperations(integrationId);
      setOperations((x)=>({...x,[integrationId]:data.operations || []}));
      setExpanded((x)=>({...x,[integrationId]:true}));
      setMessage(ar ? `تم تحديث ${result.operations_discovered} عملية API.` : `Refreshed ${result.operations_discovered} API operations.`);
    } catch (err) { setError(err.message || "Could not refresh OpenAPI."); }
    finally { setBusy(false); }
  }

  return <div dir={ar?"rtl":"ltr"}>
    <h2 className="mb-1 text-2xl font-black">{ar?"التكاملات والأنظمة":"Systems & Integrations"}</h2>
    <p className="mb-5 text-sm text-slate-400">{ar?"سجّل الأنظمة يدويًا أو الصق رابط Swagger/OpenAPI ليكتشف ZERO X-RAY عمليات الـAPI تلقائيًا ويربطها بالخدمة.":"Register systems manually or paste a Swagger/OpenAPI link so ZERO X-RAY can discover API operations automatically and link them to a Service."}</p>
    <ErrorBanner message={error} lang={lang} />
    {message&&<p className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">{message}</p>}

    {canImportOpenApi&&<>
      <form onSubmit={importSpec} className="mb-6 rounded-2xl border border-violet-200 bg-violet-50/30 p-5">
        <div className="mb-3 flex items-center justify-between gap-3"><div><div className="font-black">{ar?"استيراد Swagger / OpenAPI":"Import Swagger / OpenAPI"}</div><small className="text-slate-500">{ar?"الصق رابط Swagger UI أو رابط swagger.json/openapi.json مباشرة.":"Paste a Swagger UI URL or a direct swagger.json/openapi.json URL."}</small></div><span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-bold text-violet-700">AUTO DISCOVERY</span></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <input required type="url" placeholder={ar?"رابط Swagger / OpenAPI":"Swagger / OpenAPI URL"} value={openapi.url} onChange={e=>setOpenapi(f=>({...f,url:e.target.value}))} className="rounded-xl border border-violet-200 bg-white px-3 py-2 sm:col-span-2"/>
          <select required value={openapi.service_id} onChange={e=>setOpenapi(f=>({...f,service_id:e.target.value}))} className="rounded-xl border border-violet-200 bg-white px-3 py-2"><option value="">{ar?"اختر الخدمة":"Select Service"}</option>{services.map(service=><option key={service.id} value={service.id}>{service.service_name}</option>)}</select>
          <select value={openapi.environment} onChange={e=>setOpenapi(f=>({...f,environment:e.target.value}))} className="rounded-xl border border-violet-200 bg-white px-3 py-2"><option>SANDBOX</option><option>CONNECTED</option><option>NOT_CONNECTED</option></select>
          <input placeholder={ar?"اسم اختياري (يُقرأ تلقائيًا من Swagger)":"Optional name (auto-read from Swagger)"} value={openapi.name} onChange={e=>setOpenapi(f=>({...f,name:e.target.value}))} className="rounded-xl border border-violet-200 bg-white px-3 py-2 sm:col-span-2"/>
        </div>
        <button disabled={busy||!openapi.service_id} className="mt-3 w-full rounded-xl bg-violet-600 px-4 py-2 font-bold text-white disabled:opacity-50">{busy?(ar?"جارٍ الاستيراد...":"Importing..."):(hasPermission("tenant:analyze")?(ar?"استيراد API وبناء الوكيل":"Import API & Build Agent"):(ar?"استيراد عمليات API":"Import API operations"))}</button>
      </form>

      {hasPermission("tenant:manage_integrations")&&<details className="mb-6 rounded-2xl border border-blue-100 bg-white p-5"><summary className="cursor-pointer font-black">{ar?"إضافة تكامل يدوي":"Add integration manually"}</summary>
        <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-2"><input required placeholder={ar?"اسم النظام / API":"System / API name"} value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} className="rounded-xl border border-blue-100 px-3 py-2"/><select value={form.type} onChange={e=>setForm(f=>({...f,type:e.target.value}))} className="rounded-xl border border-blue-100 px-3 py-2">{INTEGRATION_TYPES.map(t=><option key={t}>{t}</option>)}</select><input placeholder={ar?"Endpoint اختياري للديمو":"Optional endpoint for demo"} value={form.endpoint} onChange={e=>setForm(f=>({...f,endpoint:e.target.value}))} className="rounded-xl border border-blue-100 px-3 py-2"/><select value={form.status} onChange={e=>setForm(f=>({...f,status:e.target.value}))} className="rounded-xl border border-blue-100 px-3 py-2"><option>NOT_CONNECTED</option><option>SANDBOX</option><option>CONNECTED</option></select><button className="rounded-xl bg-blue-600 px-4 py-2 font-bold text-white sm:col-span-2">{ar?"إضافة التكامل":"Add integration"}</button></form>
      </details>}
    </>}

    {items===null?<EmptyState label="Loading..."/>:items.length===0?<EmptyState label={ar?"لا توجد تكاملات بعد.":"No integrations yet."}/>:<div className="grid gap-3 sm:grid-cols-2">{items.map(i=><Card key={i.id}><div className="flex items-start justify-between gap-3"><div className="min-w-0"><b>{i.name}</b><small className="block text-slate-400">{i.type}</small>{i.config?.endpoint&&<small className="mt-1 block break-all text-slate-500">{i.config.endpoint}</small>}<small className="mt-2 block text-slate-400">{{CONNECTED:ar?"نظام متصل.":"Connected system.",SANDBOX:ar?"بيئة تجريبية/محاكاة.":"Demo/simulation environment.",NOT_CONNECTED:ar?"يتطلب تكاملًا.":"Integration required."}[i.status]}</small></div><StatusPill status={i.status}/></div>
      <div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={()=>toggleOperations(i.id)} className="rounded-lg border border-blue-200 px-3 py-1.5 text-xs font-bold text-blue-700">{expanded[i.id]?(ar?"إخفاء العمليات":"Hide operations"):(ar?"عرض عمليات API":"View API operations")}</button>{operations[i.id]?.length>0&&canImportOpenApi&&<button disabled={busy} type="button" onClick={()=>refreshSpec(i.id)} className="rounded-lg border border-violet-200 px-3 py-1.5 text-xs font-bold text-violet-700">{ar?"تحديث OpenAPI":"Refresh OpenAPI"}</button>}</div>
      {expanded[i.id]&&<div className="mt-3 max-h-72 space-y-2 overflow-auto rounded-xl bg-slate-50 p-3">{(operations[i.id]||[]).length===0?<small className="text-slate-400">{ar?"لا توجد عمليات OpenAPI مسجلة لهذا التكامل.":"No imported OpenAPI operations for this integration."}</small>:(operations[i.id]||[]).map(op=><div key={op.id||`${op.method}-${op.path}`} className="rounded-lg border border-slate-200 bg-white p-2"><div className="flex items-center gap-2"><span className="rounded bg-slate-900 px-2 py-0.5 text-[10px] font-black text-white">{op.method}</span><code className="break-all text-xs">{op.path}</code></div>{op.operation_id&&<small className="mt-1 block font-semibold text-slate-600">{op.operation_id}</small>}{op.summary&&<small className="block text-slate-400">{op.summary}</small>}{op.tags?.length>0&&<small className="block text-slate-400">{op.tags.join(" · ")}</small>}</div>)}</div>}
    </Card>)}</div>}
  </div>;
}


// --- Users -----------------------------------------------------------

const ROLES = ["entity_admin", "service_owner", "analyst", "viewer"];

export function UsersPanel() {
  const { currentUser } = useAuth();
  const { lang } = useLanguage();
  const ar = lang === "ar";
  const [users, setUsers] = useState(null);
  const [services, setServices] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", email: "", role: "viewer" });

  function reload() {
    Promise.all([listTenantUsers(), listServices(), listServiceAssignments()])
      .then(([userData, serviceData, assignmentData]) => {
        setUsers(userData.users);
        setServices(serviceData.services || []);
        setAssignments(assignmentData.assignments || []);
      })
      .catch((e) => setError(e.message));
  }
  useEffect(reload, []);

  async function submit(e) {
    e.preventDefault();
    setError("");
    try {
      await createTenantUser(form);
      setForm({ name: "", email: "", role: "viewer" });
      reload();
    } catch (err) {
      setError(err.message || "Could not add user.");
    }
  }

  async function changeRole(userId, role) {
    try {
      await updateUserRole(userId, role);
      reload();
    } catch (err) {
      setError(err.message || "Could not change role.");
    }
  }

  async function toggleStatus(user) {
    try {
      await setUserStatus(user.id, user.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE");
      reload();
    } catch (err) {
      setError(err.message || "Could not update status.");
    }
  }

  function isAssigned(userId, serviceId) {
    return assignments.some((a) => a.user_id === userId && a.service_id === serviceId);
  }

  async function toggleAssignment(userId, serviceId) {
    setError("");
    try {
      if (isAssigned(userId, serviceId)) await unassignUserFromService(serviceId, userId);
      else await assignUserToService(serviceId, userId);
      reload();
    } catch (err) {
      setError(err.message || "Could not update service assignment.");
    }
  }

  return (
    <div dir={ar ? "rtl" : "ltr"}>
      <h2 className="mb-1 text-2xl font-black">{ar ? "المستخدمون والصلاحيات" : "Users & Roles"}</h2><p className="mb-4 text-sm text-slate-400">{ar ? "يتم حفظ المستخدمين في قاعدة بيانات الجهة وتظل حساباتهم متاحة بعد إعادة تشغيل الخادم." : "Users are saved in the tenant database and remain available after backend restarts. Demo users sign in with the configured demo credential."}</p>
      <ErrorBanner message={error} lang={lang} />
      <form onSubmit={submit} className="mb-6 flex flex-wrap gap-3 rounded-2xl border border-blue-100 bg-white p-4">
        <input required placeholder={ar ? "الاسم" : "Name"} value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          className="rounded-xl border border-blue-100 px-3 py-2 text-sm" />
        <input required type="email" placeholder={ar ? "البريد الإلكتروني" : "Email"} value={form.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          className="rounded-xl border border-blue-100 px-3 py-2 text-sm" />
        <select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
          className="rounded-xl border border-blue-100 px-3 py-2 text-sm">
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button type="submit" className="rounded-xl bg-blue-600 px-4 py-2 font-bold text-white">{ar ? "إضافة مستخدم تجريبي" : "Add demo user"}</button>
      </form>
      {users === null ? <EmptyState label="Loading..." /> : (
        <div className="space-y-2">
          {users.map((u) => (
            <div key={u.id} className="rounded-xl border border-blue-100 bg-white p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-bold">{u.name}</div>
                  <div className="text-xs text-slate-400">{u.email}</div>
                </div>
                <select value={u.role} onChange={(e) => changeRole(u.id, e.target.value)}
                  disabled={u.id === currentUser?.id}
                  title={u.id === currentUser?.id ? "You cannot change your own active role." : ""}
                  className="rounded-lg border border-blue-100 px-2 py-1 text-xs disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400">
                  {["entity_admin", ...ROLES.filter((r) => r !== "entity_admin")].map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <button type="button" onClick={() => toggleStatus(u)}
                  disabled={u.id === currentUser?.id}
                  title={u.id === currentUser?.id ? "Your own account must remain active while you are signed in." : ""}
                  className={`rounded-full border px-3 py-1 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-60 ${u.status === "ACTIVE" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                  {u.status}
                </button>
              </div>
              {u.role === "service_owner" && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-blue-50 pt-3">
                  {services.length === 0 ? <span className="text-xs text-slate-400">No services available.</span> : services.map((service) => (
                    <label key={service.id} className="flex items-center gap-2 rounded-lg border border-blue-100 px-2 py-1 text-xs">
                      <input type="checkbox" checked={isAssigned(u.id, service.id)} onChange={() => toggleAssignment(u.id, service.id)} />
                      <span>{service.service_name}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Audit Logs --------------------------------------------------------

export function AuditLogPanel() {
  const { lang } = useLanguage();
  const ar = lang === "ar";
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getAuditLog().then((d) => setEntries(d.entries)).catch((e) => setError(e.message));
  }, []);

  return (
    <div dir={ar ? "rtl" : "ltr"}>
      <h2 className="mb-4 text-2xl font-black">{ar ? "سجل التدقيق" : "Audit Logs"}</h2>
      <ErrorBanner message={error} lang={lang} />
      {entries === null ? <EmptyState label="Loading..." /> : entries.length === 0 ? (
        <EmptyState label={ar ? "لا يوجد نشاط مسجل حتى الآن." : "No activity recorded yet."} />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-blue-100 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-400">
              <tr>
                <th className="px-4 py-2">{ar ? "الإجراء" : "Action"}</th>
                <th className="px-4 py-2">{ar ? "الكيان" : "Entity"}</th>
                <th className="px-4 py-2">{ar ? "الوقت" : "When"}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-t border-blue-50">
                  <td className="px-4 py-2 font-bold">{e.action}</td>
                  <td className="px-4 py-2 text-slate-500">{e.entity_type}</td>
                  <td className="px-4 py-2 text-slate-400">{e.created_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- Settings (read-only summary) --------------------------------------

export function SettingsPanel() {
  const { currentTenant, role } = useAuth();
  const { lang } = useLanguage();
  const ar = lang === "ar";
  const [storage, setStorage] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getStorageInfo()
      .then((value) => !cancelled && setStorage(value))
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return (
    <div dir={ar ? "rtl" : "ltr"}>
      <h2 className="mb-4 text-2xl font-black">{ar ? "الإعدادات" : "Settings"}</h2>
      <Card>
        <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs font-bold uppercase text-slate-400">{ar ? "الجهة" : "Entity"}</dt>
            <dd className="font-black">{currentTenant?.name}</dd>
          </div>
          <div>
            <dt className="text-xs font-bold uppercase text-slate-400">{ar ? "الحالة" : "Status"}</dt>
            <dd className="font-black">{currentTenant?.status}</dd>
          </div>
          <div>
            <dt className="text-xs font-bold uppercase text-slate-400">{ar ? "صلاحيتك" : "Your role"}</dt>
            <dd className="font-black">{role}</dd>
          </div>
        </dl>
      </Card>
      {storage && (
        <div className="mt-4 rounded-2xl border border-blue-100 bg-white p-5 text-sm">
          <h3 className="font-black">{ar ? "مكان حفظ البيانات الدائم" : "Persistent data location"}</h3>
          <p className="mt-2 text-slate-500">{ar ? "قاعدة البيانات والملفات هنا لا تعتمد على مجلد ملف ZIP، لذلك تظل موجودة عند تشغيل نسخة جديدة." : "The database and uploaded files live outside the ZIP folder, so they survive new project copies."}</p>
          <code className="mt-3 block break-all rounded-xl bg-slate-50 p-3 text-xs">{storage.database_path}</code>
        </div>
      )}
    </div>
  );
}
