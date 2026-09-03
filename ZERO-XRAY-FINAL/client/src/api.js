import { getToken, clearToken } from "./auth/tokenStore";

const API_URL =
  import.meta.env.VITE_API_URL ||
  "http://localhost:8000";



function readableErrorDetail(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    if (typeof value.message === "string" && value.message.trim()) {
      return value.message;
    }
    try {
      return JSON.stringify(value);
    } catch {
      return "Request could not be completed.";
    }
  }
  return String(value);
}

async function apiRequest(path, options = {}) {
  const token = getToken();

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let message = "";
    // PHASE 7: preserve the backend's stable, machine-readable error
    // code (e.g. SUBSCRIPTION_EXPIRED / TENANT_SUSPENDED) when present,
    // so callers can identify a specific condition without parsing the
    // English message text. Any other error shape is unaffected --
    // `code` is simply empty/undefined for them, exactly as before.
    let code = "";
    try {
      const errorData = await response.json();
      if (errorData.detail && typeof errorData.detail === "object") {
        code = errorData.detail.code || "";
      }
      message = readableErrorDetail(errorData.detail || errorData.error || "");
    } catch {
      // Use the status fallback below.
    }
    if (response.status === 401) {
      // A stale/invalid session token -- clear it so the next call
      // (or a manual re-login) starts clean instead of retrying with
      // the same bad token forever.
      clearToken();
    }
    const requestError = new Error(message || `Request failed (${response.status}).`);
    requestError.status = response.status;
    requestError.code = code;
    throw requestError;
  }

  return await response.json();
}


async function customerRequest(path, options = {}) {
  // Public customer journey traffic deliberately does not use employee
  // Authorization. The server authenticates the customer with an HttpOnly,
  // journey-scoped capability cookie issued when the journey is created.
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let message = "";
    try {
      const errorData = await response.json();
      message = readableErrorDetail(errorData.detail || errorData.error || "");
    } catch {
      // Use the status fallback below.
    }
    throw new Error(message || `Request failed (${response.status}).`);
  }

  return await response.json();
}

export async function analyzeService(service) {
  return apiRequest("/api/analyze", {
    method: "POST",
    body: JSON.stringify(service),
  });
}


export function approveBlueprint(blueprintId) {
  return apiRequest(`/api/blueprints/${blueprintId}/approve`, { method: "POST" });
}


export function publishBlueprint(blueprintId) {
  return apiRequest(`/api/blueprints/${blueprintId}/publish`, { method: "POST" });
}


export function registerSandboxCustomer(customer, authenticated = false) {
  const request = authenticated ? apiRequest : customerRequest;
  return request("/api/sandbox/register", {
    method: "POST",
    body: JSON.stringify(customer),
  });
}


export function createJourney(payload) {
  return customerRequest("/api/journeys", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}


export function editJourneyPlan(journeyId, edit) {
  return customerRequest(`/api/journeys/${journeyId}/edit`, {
    method: "POST",
    body: JSON.stringify(
      typeof edit === "string"
        ? { instruction: edit }
        : edit
    ),
  });
}


export function approveJourneyPlan(journeyId) {
  return customerRequest(`/api/journeys/${journeyId}/approve`, { method: "POST" });
}


export function prepareJourneyPaymentAssessment(journeyId) {
  return customerRequest(`/api/journeys/${journeyId}/payment-assessment`, {
    method: "POST",
  });
}


export function payJourney(journeyId, paymentMethod = "SANDBOX_CARD") {
  return customerRequest(`/api/journeys/${journeyId}/payment`, {
    method: "POST",
    body: JSON.stringify({ payment_method: paymentMethod, approved: true }),
  });
}


export function executeJourney(journeyId) {
  return customerRequest(`/api/journeys/${journeyId}/execute`, { method: "POST" });
}


export function controlJourney(journeyId, action) {
  return customerRequest(`/api/journeys/${journeyId}/${action}`, { method: "POST" });
}


export function getJourneyEventsUrl(journeyId) {
  return `${API_URL}/api/journeys/${journeyId}/events`;
}


// --- Auth / tenant platform -------------------------------------------

export function demoLogin(email, credential) {
  return apiRequest("/api/auth/demo-login", {
    method: "POST",
    body: JSON.stringify({ email, credential }),
  });
}

export function whoami() {
  return apiRequest("/api/me");
}

export function logoutEmployeeSession() {
  // keepalive lets the server-side revocation complete even when the existing
  // Logout UX immediately redirects the browser to /login.
  return apiRequest("/api/auth/logout", { method: "POST", keepalive: true });
}

export function createGovernmentEntity(payload) {
  return apiRequest("/api/platform/entities", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listGovernmentEntities() {
  return apiRequest("/api/platform/entities");
}

export function updateGovernmentEntitySubscription(tenantId, payload) {
  return apiRequest(`/api/platform/entities/${encodeURIComponent(tenantId)}/subscription`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

// --- Published Agents (backend-persisted, replaces localStorage) ------

export function publishAgent(blueprintId, name) {
  return apiRequest("/api/agents/publish", {
    method: "POST",
    body: JSON.stringify({ blueprint_id: blueprintId, name }),
  });
}

export function listAgents() {
  return apiRequest("/api/agents");
}

export async function getPublicService(tenantSlug, agentSlug) {
  // Deliberately NOT routed through apiRequest: this is the
  // anonymous, public customer-facing endpoint (Section 42) -- no
  // Authorization header, no 401-triggered token clearing, and a
  // 404 here just means "service not found", not an auth failure.
  const response = await fetch(
    `${API_URL}/service/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(agentSlug)}`,
    { headers: { Accept: "application/json" } }
  );
  if (!response.ok) {
    return null;
  }
  return await response.json();
}

// --- Services / Analyses / Data Sources / Integrations / Audit --------

export function listServices() {
  return apiRequest("/api/services");
}

export function createService(payload) {
  return apiRequest("/api/services", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getService(serviceId) {
  return apiRequest(`/api/services/${serviceId}`);
}

export function getServiceContext(serviceId) {
  return apiRequest(`/api/services/${serviceId}/context`);
}

export function listServiceAnalyses(serviceId) {
  return apiRequest(`/api/services/${serviceId}/analyses`);
}

export function getAnalysis(analysisId) {
  return apiRequest(`/api/analyses/${analysisId}`);
}

export function getCustomer(customerId) {
  return apiRequest(`/api/customers/${customerId}`);
}

export function getAgent(agentId) {
  return apiRequest(`/api/agents/${agentId}`);
}

export function getPlatformStats() {
  return apiRequest("/api/platform/stats");
}

export function listDataSources() {
  return apiRequest("/api/data-sources");
}

export function createDataSource(payload) {
  return apiRequest("/api/data-sources", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDataSource(id) {
  return apiRequest(`/api/data-sources/${id}`);
}

export function listIntegrations() {
  return apiRequest("/api/integrations");
}

export function getIntegration(id) {
  return apiRequest(`/api/integrations/${id}`);
}

export function createIntegration(payload) {
  return apiRequest("/api/integrations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function importOpenApi(serviceId, payload) {
  return apiRequest(`/api/services/${serviceId}/openapi-import`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function refreshOpenApi(integrationId) {
  return apiRequest(`/api/integrations/${integrationId}/openapi-refresh`, {
    method: "POST",
  });
}

export function listIntegrationOperations(integrationId) {
  return apiRequest(`/api/integrations/${integrationId}/operations`);
}


export function getAuditLog() {
  return apiRequest("/api/audit-log");
}

// --- Entity Admin user management --------------------------------------

export function listTenantUsers() {
  return apiRequest("/api/users");
}

export function createTenantUser(payload) {
  return apiRequest("/api/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUserRole(userId, role) {
  return apiRequest(`/api/users/${userId}/role`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
}

export function setUserStatus(userId, status) {
  return apiRequest(`/api/users/${userId}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

export function listServiceAssignments() {
  return apiRequest("/api/service-assignments");
}

export function assignUserToService(serviceId, userId) {
  return apiRequest(`/api/services/${serviceId}/assignments/${userId}`, { method: "POST" });
}

export function unassignUserFromService(serviceId, userId) {
  return apiRequest(`/api/services/${serviceId}/assignments/${userId}`, { method: "DELETE" });
}


export function getStorageInfo() {
  return apiRequest("/api/system/storage-info");
}

// --- ZERO X-RAY Intelligence: Predict / Simulate / Challenge / Evolve /
// Prevent (Steps 1-5 of the Government Future Engine evolution).
// These call the real, already-tested backend endpoints only -- no
// mock data, no invented fields.

export function predictService(serviceId, lang = "en") {
  return apiRequest(`/api/services/${serviceId}/predict?lang=${encodeURIComponent(lang)}`, { method: "POST" });
}

export function createScenario(serviceId, payload) {
  return apiRequest(`/api/services/${serviceId}/scenarios`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listScenarios(serviceId) {
  return apiRequest(`/api/services/${serviceId}/scenarios`);
}

export function createChallenge(serviceId, payload = {}) {
  return apiRequest(`/api/services/${serviceId}/challenges`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listChallenges(serviceId) {
  return apiRequest(`/api/services/${serviceId}/challenges`);
}

export function createEvolution(serviceId, challengeId, lang = "en") {
  return apiRequest(`/api/services/${serviceId}/evolutions`, {
    method: "POST",
    body: JSON.stringify({ challenge_id: challengeId, lang }),
  });
}

export function listEvolutions(serviceId) {
  return apiRequest(`/api/services/${serviceId}/evolutions`);
}

export function createPrevention(serviceId, evolutionId, lang = "en") {
  return apiRequest(`/api/services/${serviceId}/preventions`, {
    method: "POST",
    body: JSON.stringify({ evolution_id: evolutionId, lang }),
  });
}

export function listPreventions(serviceId) {
  return apiRequest(`/api/services/${serviceId}/preventions`);
}

// --- Monitoring / Alerts (Step 8): on-demand, deterministic re-check
// of stored Prevent triggers against the latest stored Predict/
// Challenge results, and the resulting stored alert records. No
// external notification integration exists -- an alert is only ever
// a stored record.

export function runMonitoringCheck(serviceId, preventionId, lang = "en") {
  return apiRequest(`/api/services/${serviceId}/monitoring-checks`, {
    method: "POST",
    body: JSON.stringify({ prevention_id: preventionId, lang }),
  });
}

export function listAlerts(serviceId) {
  return apiRequest(`/api/services/${serviceId}/alerts`);
}

export function getMonitoringSchedule(serviceId) {
  return apiRequest(`/api/services/${serviceId}/monitoring-schedule`);
}

export function updateMonitoringSchedule(serviceId, enabled, frequency) {
  return apiRequest(`/api/services/${serviceId}/monitoring-schedule`, {
    method: "PUT",
    body: JSON.stringify({ enabled, frequency }),
  });
}
