import { useEffect, useState } from "react";
import { translations } from "./translations";
import { LanguageContext } from "./useLanguage";

const STORAGE_KEY = "zx-language";

function getInitialLang() {

  if (typeof window === "undefined") {
    return "en";
  }

  const saved = window.localStorage.getItem(STORAGE_KEY);

  if (saved === "en" || saved === "ar") {
    return saved;
  }

  return "en";

}

export function LanguageProvider({ children }) {

  const [lang, setLang] = useState(getInitialLang);

  const dir = lang === "ar" ? "rtl" : "ltr";

  useEffect(() => {

    window.localStorage.setItem(STORAGE_KEY, lang);

    document.documentElement.lang = lang;
    document.documentElement.dir = dir;

    document.body.classList.toggle("lang-ar", lang === "ar");
    document.body.classList.toggle("lang-en", lang === "en");

  }, [lang, dir]);

  function toggleLang() {
    setLang((current) => (current === "en" ? "ar" : "en"));
  }

  const value = {
    lang,
    dir,
    setLang,
    toggleLang,
    t: translations[lang],
  };

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );

}
