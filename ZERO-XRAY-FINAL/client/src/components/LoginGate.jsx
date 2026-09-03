import { useLanguage } from "../i18n/useLanguage";

export default function LoginGate() {
  const { lang } = useLanguage();
  const isAr = lang === "ar";

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
          {isAr ? "تسجيل الدخول مطلوب" : "Sign in required"}
        </h1>
        <p className="mt-4 text-slate-500">
          {isAr
            ? "منصة ZERO X-RAY الآن متعددة الجهات الحكومية. سجّل الدخول بحساب جهتك للمتابعة."
            : "ZERO X-RAY is now a multi-tenant government platform. Sign in with your entity's account to continue."}
        </p>
        <a
          href="/login"
          className="mt-8 inline-block rounded-2xl bg-blue-600 px-6 py-3 font-black text-white transition hover:bg-blue-700"
        >
          {isAr ? "الذهاب لتسجيل الدخول" : "Go to sign in"}
        </a>
      </div>
    </div>
  );
}
