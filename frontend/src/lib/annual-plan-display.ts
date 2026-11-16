type ProcurementNature = "goods" | "service" | "mixed" | "" | null | undefined;

const procurementNatureLabels: Record<string, string> = {
  goods: "货物",
  service: "服务",
  mixed: "混合",
};

export function annualPlanCategoryLabel(projectType: string, procurementNature: ProcurementNature) {
  if (projectType === "software" || projectType === "teaching_software") {
    return `专业教学软件项目 · ${procurementNatureLabels[procurementNature ?? ""] ?? "未设置"}`;
  }
  if (projectType === "laboratory" || projectType === "practical_teaching_site") {
    return "实践教学场所项目 · 货物";
  }
  return projectType || "未设置分类";
}
