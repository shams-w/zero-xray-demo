import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { demoLogin, logoutEmployeeSession, whoami } from "../api";
import { clearToken, getToken, onTokenChange, setToken } from "./tokenStore";

const AuthContext = createContext(null);

// Coarse, UI-facing mirror of the backend's tenants/models.py
// ROLE_PERMISSIONS. Backend authorization is authoritative (Section
// 32) -- this is for rendering only (hiding a button a user can't
// use), never a security boundary by itself.
const ROLE_PERMISSIONS = {
  platform_admin: ["platform:manage_tenants", "platform:view_metadata"],
  entity_admin: [
    "tenant:manage_users", "tenant:manage_services", "tenant:manage_agents",
    "tenant:manage_data_sources", "tenant:manage_integrations",
    "tenant:manage_settings", "tenant:analyze", "tenant:publish", "tenant:write", "tenant:read",
    "future:predict", "future:simulate", "future:challenge", "future:evolve", "future:prevent", "future:monitor",
  ],
  service_owner: [
    "tenant:manage_services", "tenant:manage_agents", "tenant:analyze", "tenant:publish", "tenant:write", "tenant:read",
    "future:predict", "future:simulate", "future:challenge", "future:evolve", "future:prevent", "future:monitor",
  ],
  analyst: ["tenant:analyze", "tenant:read", "future:predict", "future:simulate", "future:challenge"],
  viewer: ["tenant:read"],
};

export function AuthProvider({ children }) {
  const [token, setTokenState] = useState(getToken);
  const [currentUser, setCurrentUser] = useState(null);
  const [currentTenant, setCurrentTenant] = useState(null);
  const [role, setRole] = useState(null);
  const [loading, setLoading] = useState(Boolean(getToken()));
  const [error, setError] = useState("");
  // PHASE 7: set to the backend's stable code (SUBSCRIPTION_EXPIRED /
  // TENANT_SUSPENDED) when whoami() fails specifically because the
  // tenant's workspace access is blocked -- distinct from "not logged
  // in". The session token is deliberately NOT cleared for this case
  // (see refresh() below); only an actual 401 clears it, in api.js.
  const [subscriptionBlocked, setSubscriptionBlocked] = useState(null);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setCurrentUser(null);
      setCurrentTenant(null);
      setRole(null);
      setSubscriptionBlocked(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const me = await whoami();
      setCurrentUser({ id: me.user_id });
      setCurrentTenant({ id: me.tenant_id, name: me.tenant_name, status: me.tenant_status });
      setRole(me.role);
      setSubscriptionBlocked(null);
    } catch (err) {
      // whoami() failing with an actual invalid/expired session already
      // clears the token inside apiRequest -- just reflect that here.
      // A SUBSCRIPTION_EXPIRED/TENANT_SUSPENDED error is different: the
      // session itself is still valid, only the tenant's workspace
      // access is blocked, so the token is preserved and the UI shows a
      // dedicated access-expired state instead of the login screen.
      setCurrentUser(null);
      setCurrentTenant(null);
      setRole(null);
      setSubscriptionBlocked(
        err && (err.code === "SUBSCRIPTION_EXPIRED" || err.code === "TENANT_SUSPENDED")
          ? err.code
          : null
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Keep the React auth state in sync when api.js clears an expired
  // token after a 401 response. This makes LoginGate appear immediately.
  useEffect(() => onTokenChange((nextToken) => {
    setTokenState(nextToken);
    if (!nextToken) {
      setCurrentUser(null);
      setCurrentTenant(null);
      setRole(null);
      setLoading(false);
    }
  }), []);

  async function login(email, credential) {
    setError("");
    setLoading(true);
    try {
      const session = await demoLogin(email, credential);
      setToken(session.token);
      setTokenState(session.token);
      await refresh();
      return true;
    } catch (loginError) {
      setError(loginError.message || "Login failed.");
      setLoading(false);
      return false;
    }
  }

  function logout() {
    if (getToken()) {
      // Fire the server-side invalidation first; keepalive in api.js preserves
      // the current immediate redirect/logout experience.
      void logoutEmployeeSession().catch(() => {});
    }
    clearToken();
    setTokenState(null);
    setCurrentUser(null);
    setCurrentTenant(null);
    setRole(null);
  }

  const permissions = role ? (ROLE_PERMISSIONS[role] || []) : [];

  const value = {
    token,
    currentUser,
    currentTenant,
    role,
    permissions,
    hasPermission: (permission) => permissions.includes(permission),
    isAuthenticated: Boolean(token && currentUser),
    loading,
    error,
    subscriptionBlocked,
    login,
    logout,
    refresh,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
