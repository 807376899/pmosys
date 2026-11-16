import assert from "node:assert/strict";
import test from "node:test";

const { annualPlanCategoryLabel } = await import("../.annual-plan-test-dist/annual-plan-display.js");

test("annual plan shows software procurement nature", () => {
  assert.equal(annualPlanCategoryLabel("software", "goods"), "专业教学软件项目 · 货物");
  assert.equal(annualPlanCategoryLabel("teaching_software", "service"), "专业教学软件项目 · 服务");
});

test("annual plan treats practical teaching sites as goods", () => {
  assert.equal(annualPlanCategoryLabel("laboratory", ""), "实践教学场所项目 · 货物");
});
