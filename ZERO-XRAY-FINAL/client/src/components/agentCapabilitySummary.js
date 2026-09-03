// Phase 3 -- safe, defensive extraction of the Build Agent capability
// readiness summary produced by the backend's
// server/core/agent_capability_mapper.py (`agent_capability_map.summary`,
// added in server/main.py's /api/analyze).
//
// Kept in its own plain (non-JSX) module, with no React import, so it can
// be exercised directly with a small Node script (see
// client/src/components/__tests__/agentCapabilitySummary.test.mjs)
// without pulling a new test framework into the project.
//
// Older/legacy analysis results saved before Phase 2 will not have
// `agent_capability_map` at all -- this must never throw for those. It
// returns null so BuildAgentPage.jsx can hide the summary section
// entirely rather than show misleading zeros for a value that was simply
// never computed for that Blueprint.

const REQUIRED_NUMERIC_FIELDS = [
  "used_data_sources",
  "connected_apis",
  "automated_steps",
  "total_steps",
  "customer_steps",
  "manual_steps",
  "integration_required",
];

function toSafeCount(value) {
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

export function deriveCapabilitySummary(result) {
  const summary = result && result.agent_capability_map && result.agent_capability_map.summary;
  if (!summary || typeof summary !== "object") {
    return null;
  }
  const safe = {};
  for (const field of REQUIRED_NUMERIC_FIELDS) {
    safe[field] = toSafeCount(summary[field]);
  }
  return safe;
}
