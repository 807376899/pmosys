import assert from "node:assert/strict";
import test from "node:test";

const { resolveProjectRailState, resolveWorkbenchRailVisibility, shouldApplyDashboardLoad, shouldClearProjectSelection } = await import("../node_modules/.cache/rail-state-tests/rail-state.js");

test("selection opens project operations unless the user dismissed it", () => {
  assert.equal(resolveProjectRailState({ selectedCount: 2, dismissed: false, explicitContext: false }), "project_operations");
  assert.equal(resolveProjectRailState({ selectedCount: 2, dismissed: true, explicitContext: false }), "closed");
});

test("clearing selection closes only the automatic project operation panel", () => {
  assert.equal(resolveProjectRailState({ selectedCount: 0, dismissed: false, explicitContext: false }), "closed");
  assert.equal(resolveProjectRailState({ selectedCount: 0, dismissed: false, explicitContext: true }), "explicit");
});

test("annual budget planning always reserves the common workbench rail", () => {
  assert.equal(resolveWorkbenchRailVisibility("annual", "closed"), true);
  assert.equal(resolveWorkbenchRailVisibility("overview", "closed"), false);
  assert.equal(resolveWorkbenchRailVisibility("stage", "project_operations"), true);
});

test("only the latest dashboard response may replace the current result set", () => {
  assert.equal(shouldApplyDashboardLoad(3, 3), true);
  assert.equal(shouldApplyDashboardLoad(2, 3), false);
});

test("a Stage or filter result-set change clears ordinary project selection", () => {
  assert.equal(shouldClearProjectSelection("pool_active|engineering", "completed|engineering"), true);
  assert.equal(shouldClearProjectSelection("pool_active|engineering", "pool_active|engineering"), false);
});
