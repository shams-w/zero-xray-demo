// Plain module-level token store (no React) so both api.js (a plain
// module, not a component) and AuthContext.jsx can read/write the
// same session token. This stores only the opaque session token --
// never agent/service data -- in localStorage, matching the
// theme/language pattern already used elsewhere in this project.
const STORAGE_KEY = "zx-session-token";

let listeners = [];

export function getToken() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) {
      window.localStorage.setItem(STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Ignore storage failures (private browsing, quota, etc.) --
    // the session simply won't persist across a reload.
  }
  listeners.forEach((listener) => listener(token));
}

export function clearToken() {
  setToken(null);
}

export function onTokenChange(listener) {
  listeners.push(listener);
  return () => {
    listeners = listeners.filter((l) => l !== listener);
  };
}
