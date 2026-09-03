// Phase 3 -- minimal, framework-free regression test for
// client/src/components/agentCapabilitySummary.js.
//
// The project has no frontend test framework installed (see
// client/package.json -- no jest/vitest/testing-library). Per the Phase 3
// scope ("do NOT introduce a large new testing framework solely for this
// phase"), this uses only Node's built-in `assert` and ES module import,
// exercising the pure (non-JSX, no React import) derivation function
// directly.
//
// Run with:  node client/src/components/__tests__/agentCapabilitySummary.test.mjs

import assert from "node:assert/strict";
import { deriveCapabilitySummary } from "../agentCapabilitySummary.js";

function test(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

test("returns null when agent_capability_map is entirely absent (legacy Blueprint)", () => {
  assert.equal(deriveCapabilitySummary({}), null);
  assert.equal(deriveCapabilitySummary(null), null);
  assert.equal(deriveCapabilitySummary(undefined), null);
});

test("returns null when agent_capability_map exists but summary is missing", () => {
  assert.equal(deriveCapabilitySummary({ agent_capability_map: {} }), null);
});

test("extracts every required field when summary is present", () => {
  const result = {
    agent_capability_map: {
      summary: {
        used_data_sources: 4,
        connected_apis: 7,
        sandbox_apis: 1,
        automated_steps: 8,
        total_steps: 10,
        customer_steps: 2,
        manual_steps: 0,
        integration_required: 2,
      },
    },
  };
  const summary = deriveCapabilitySummary(result);
  assert.deepEqual(summary, {
    used_data_sources: 4,
    connected_apis: 7,
    automated_steps: 8,
    total_steps: 10,
    customer_steps: 2,
    manual_steps: 0,
    integration_required: 2,
  });
});

test("all-empty backend summary safely produces all zeros", () => {
  const result = {
    agent_capability_map: {
      summary: {
        used_data_sources: 0,
        connected_apis: 0,
        sandbox_apis: 0,
        automated_steps: 0,
        total_steps: 0,
        customer_steps: 0,
        manual_steps: 0,
        integration_required: 0,
      },
    },
  };
  const summary = deriveCapabilitySummary(result);
  assert.equal(summary.used_data_sources, 0);
  assert.equal(summary.total_steps, 0);
});

test("malformed/negative/non-numeric fields never crash and clamp to 0", () => {
  const result = {
    agent_capability_map: {
      summary: {
        used_data_sources: "not-a-number",
        connected_apis: -3,
        automated_steps: null,
        total_steps: undefined,
        customer_steps: NaN,
        manual_steps: {},
        integration_required: [],
      },
    },
  };
  const summary = deriveCapabilitySummary(result);
  for (const value of Object.values(summary)) {
    assert.equal(typeof value, "number");
    assert.ok(value >= 0);
  }
});

test("never leaks unexpected/secret-shaped keys from the raw summary object", () => {
  const result = {
    agent_capability_map: {
      summary: {
        used_data_sources: 1,
        connected_apis: 1,
        automated_steps: 1,
        total_steps: 1,
        customer_steps: 0,
        manual_steps: 0,
        integration_required: 0,
        secret_reference: "vault://should-not-appear",
        config: { api_key: "should-not-appear" },
      },
    },
  };
  const summary = deriveCapabilitySummary(result);
  assert.equal("secret_reference" in summary, false);
  assert.equal("config" in summary, false);
});

if (process.exitCode) {
  console.error("\nOne or more agentCapabilitySummary tests FAILED.");
} else {
  console.log("\nAll agentCapabilitySummary tests passed.");
}
