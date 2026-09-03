import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { useLanguage } from "../i18n/useLanguage";

export default function LoginPage() {
  const { lang } = useLanguage();
  const isAr = lang === "ar";
  const { login, loading, error } = useAuth();
  const [email, setEmail] = useState("");
  const [credential, setCredential] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    const ok = await login(email.trim(), credential);
    if (ok) {
      window.location.href = "/";
    }
  }

  return (
    <div
      dir={isAr ? "rtl" : "ltr"}
      className="min-h-screen bg-[#f7faff] px-6 py-16 text-slate-950 flex items-center justify-center"
    >
      <div className="w-full max-w-md rounded-[30px] border border-blue-100 bg-white p-10 shadow-xl shadow-blue-100/40">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 font-black text-white">
            Ø
          </div>
          <div>
            <strong className="block text-lg font-black">ZERO X-RAY</strong>
            <span className="text-xs text-slate-500">
              {isAr ? "بيئة تجريبية / تطوير" : "Demo / Development"}
            </span>
          </div>
        </div>

        <h1 className="text-2xl font-black">
          {isAr ? "تسجيل الدخول" : "Sign in"}
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          {isAr
            ? "استخدم بريد المستخدم التجريبي الخاص بجهتك الحكومية."
            : "Use your government entity's demo user email."}
        </p>

        <form onSubmit={handleSubmit} className="mt-8 space-y-4">
          <div>
            <label className="mb-1 block text-xs font-bold text-slate-600">
              {isAr ? "البريد الإلكتروني" : "Email"}
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl border border-blue-100 px-4 py-3 text-sm outline-none focus:border-blue-400"
              placeholder="fatima@emirates-post.test"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-bold text-slate-600">
              {isAr ? "كلمة المرور التجريبية" : "Demo passphrase"}
            </label>
            <input
              type="password"
              required
              value={credential}
              onChange={(e) => setCredential(e.target.value)}
              className="w-full rounded-xl border border-blue-100 px-4 py-3 text-sm outline-none focus:border-blue-400"
              placeholder={isAr ? "أدخل كلمة المرور التجريبية" : "Enter demo passphrase"}
            />
          </div>

          {error && (
            <p className="rounded-xl bg-red-50 px-4 py-3 text-sm font-semibold text-red-600">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-2xl bg-blue-600 px-6 py-3 font-black text-white transition hover:bg-blue-700 disabled:opacity-60"
          >
            {loading
              ? isAr ? "جارٍ الدخول..." : "Signing in..."
              : isAr ? "دخول" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-slate-400">
          {isAr
            ? "*** هذا تسجيل دخول تجريبي فقط، وليس UAE PASS الحقيقي ***"
            : "*** Demo login only -- not real UAE PASS ***"}
        </p>
      </div>
    </div>
  );
}
