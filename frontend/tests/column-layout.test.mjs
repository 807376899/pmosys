import assert from "node:assert/strict";
import test from "node:test";

const { applySharedOrder, insertStageGroup, replaceVisibleOrder } = await import("../.column-layout-test-dist/column-layout.js");

test("shared base order is applied without changing a view's visibility", () => {
  const order = applySharedOrder(["stage", "department", "budget", "contract"], ["budget", "contract"]);
  assert.deepEqual(order, ["budget", "contract"]);
});

test("stage group stays after its anchor while its internal columns remain separate", () => {
  const layout = insertStageGroup(["stage", "department", "contract", "budget"], "contract");
  assert.deepEqual(layout, ["stage", "department", "contract", "stage_group", "budget"]);
});

test("reordering visible stage columns keeps hidden shared columns in place", () => {
  const order = replaceVisibleOrder(
    ["stage", "document", "department", "budget", "contract", "latest_activity"],
    ["stage", "department", "budget", "contract"],
    ["stage", "contract", "department", "budget"],
  );
  assert.deepEqual(order, ["stage", "document", "contract", "department", "budget", "latest_activity"]);
});
