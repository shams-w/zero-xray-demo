import { useLanguage } from "../i18n/useLanguage";
import { useAuth } from "../auth/AuthContext";

// PHASE 7: shown instead of the normal app when the authenticated
// user's session is still valid but their tenant's workspace access is
// blocked (SUBSCRIPTION_EXPIRED / TENANT_SUSPENDED). Deliberately reuses
// LoginGate's exact card/shell markup and Tailwind classes -- same
// design system, dark/light and RTL/LTR handled the same way -- rather
// than introducing a new visual language.
export default function AccessExpiredGate() {
  const { lang, t } = useLanguage();
  const isAr = lang === "ar";
  const { logout, refresh } = useAuth();
  const copy = t?.accessExpired || {};

  return (
    <div
      dir={isAr ? "rtl" : "ltr"}
      className="min-h-screen bg-[#f7faff] px-6 py-16 text-slate-950 flex items-center justify-center"
    >
      <div className="mx-auto max-w-lg rounded-[30px] border border-blue-100 bg-white p-10 text-center shadow-xl shadow-blue-100/40">
        <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-600 font-black text-white">
          Ø
        </div>
        <h1 className="text-2xl font-black">
          {copy.title}
        </h1>
        <p className="mt-4 text-slate-500">
          {copy.message}
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => refresh()}
            className="inline-block rounded-2xl bg-blue-600 px-6 py-3 font-black text-white transition hover:bg-blue-700"
          >
            {copy.retry}
          </button>
          <button
            type="button"
            onClick={logout}
            className="inline-block rounded-2xl border border-blue-200 px-6 py-3 font-black text-blue-700 transition hover:bg-blue-50"
          >
            {copy.logout}
          </button>
        </div>
      </div>
    </div>
  );
}
