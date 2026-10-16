import assert from "node:assert/strict";
import test from "node:test";

const { resolveProjectRailState, resolveWorkbenchRailVisibility } = await import("../node_modules/.cache/rail-state-tests/rail-state.js");

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
