import assert from "node:assert/strict";
import test from "node:test";

const { applySharedOrder, clampColumnWidth, insertStageGroup, replaceVisibleOrder, resetViewColumnWidths, setViewColumnWidth, stageLayoutForVisibleColumns } = await import("../.column-layout-test-dist/column-layout.js");

test("shared base order is applied without changing a view's visibility", () => {
  const order = applySharedOrder(["stage", "department", "budget", "contract"], ["budget", "contract"]);
  assert.deepEqual(order, ["budget", "contract"]);
});

test("stage group stays after its anchor while its internal columns remain separate", () => {
  const layout = insertStageGroup(["stage", "department", "contract", "budget"], "contract");
  assert.deepEqual(layout, ["stage", "department", "contract", "stage_group", "budget"]);
});

test("hidden stage base columns leave the group at its configured position", () => {
  const layout = stageLayoutForVisibleColumns(
    ["stage", "department", "contract", "budget"],
    ["stage", "contract", "budget"],
    "department",
  );
  assert.deepEqual(layout, ["stage", "stage_group", "contract", "budget"]);
});

test("reordering visible stage columns keeps hidden shared columns in place", () => {
  const order = replaceVisibleOrder(
    ["stage", "document", "department", "budget", "contract", "latest_activity"],
    ["stage", "department", "budget", "contract"],
    ["stage", "contract", "department", "budget"],
  );
  assert.deepEqual(order, ["stage", "document", "contract", "department", "budget", "latest_activity"]);
});

test("column widths are isolated by view and persist by stable column key", () => {
  const initial = { overview: {}, stage: {} };
  const overview = setViewColumnWidth(initial, "overview", "base:budget", 236, 112);
  const stage = setViewColumnWidth(overview, "stage", "work_item:review", 208, 148);
  assert.deepEqual(stage, { overview: { "base:budget": 236 }, stage: { "work_item:review": 208 } });
  assert.deepEqual(resetViewColumnWidths(stage, "overview"), { overview: {}, stage: { "work_item:review": 208 } });
});

test("column widths never shrink below their readable minimum", () => {
  assert.equal(clampColumnWidth(76, 112), 112);
  assert.equal(clampColumnWidth(236, 112), 236);
});
