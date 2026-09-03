import { useEffect, useState } from "react";
import { ThemeContext } from "./useTheme";

const STORAGE_KEY = "zr-theme";

function getInitialTheme() {

  if (typeof window === "undefined") {
    return "dark";
  }

  const saved = window.localStorage.getItem(STORAGE_KEY);

  if (saved === "dark" || saved === "light") {
    return saved;
  }

  const prefersLight =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: light)").matches;

  return prefersLight ? "light" : "dark";

}

export function ThemeProvider({ children }) {

  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {

    window.localStorage.setItem(STORAGE_KEY, theme);

    document.documentElement.setAttribute("data-theme", theme);

    document.body.classList.toggle("theme-dark", theme === "dark");
    document.body.classList.toggle("theme-light", theme === "light");

  }, [theme]);

  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }

  const value = {
    theme,
    setTheme,
    toggleTheme,
    isDark: theme === "dark",
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );

}
