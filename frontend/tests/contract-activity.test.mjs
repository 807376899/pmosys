import assert from "node:assert/strict";
import test from "node:test";

const { buildContractActivity } = await import("../node_modules/.cache/contract-activity-tests/contract-activity.js");

test("contract activity combines progress, acceptance, and payment in newest-first order", () => {
  const activity = buildContractActivity({
    progress_logs: [{ id: 1, content: "供应商确认交付", created_at: "2026-10-02T09:00:00" }],
    acceptance_records: [{ id: 2, acceptance_status: "accepted", acceptance_date: "2026-10-03", result: "通过", note: "" }],
    payment_records: [{ id: 3, amount: "12.5896", paid_on: "2026-10-04", note: "第一笔付款" }],
  });

  assert.deepEqual(activity.map((item) => item.kind), ["payment", "acceptance", "progress"]);
  assert.equal(activity[0].title, "付款 · 12.5896 万");
  assert.equal(activity[1].title, "验收通过 · 通过");
});

test("contract activity keeps records on the same date in a stable type order", () => {
  const activity = buildContractActivity({
    progress_logs: [{ id: 3, content: "补充材料", created_at: "2026-10-03T15:00:00" }],
    acceptance_records: [{ id: 2, acceptance_status: "accepting", acceptance_date: "2026-10-03", result: "", note: "" }],
    payment_records: [{ id: 1, amount: "2", paid_on: "2026-10-03", note: "" }],
  });

  assert.deepEqual(activity.map((item) => item.kind), ["progress", "acceptance", "payment"]);
});
