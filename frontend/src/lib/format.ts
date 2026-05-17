import type { Project } from "../types";

export const statusLabelMap: Record<string, string> = {
  draft: "草稿",
  under_review: "评审中",
  established: "已立项",
  submission_review: "送审中",
  procuring: "采购中",
  implementing: "实施中",
  trial: "试用中",
  accepting: "验收中",
  closed: "已关闭",
  suspended: "已暂停",
  terminated: "已终止",
};

export const projectTypeLabelMap: Record<string, string> = {
  teaching_software: "教学软件",
  practical_teaching_site: "实践教学场所",
};

export function formatCurrency(value: number | null | undefined) {
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  }).format(value ?? 0);
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "未记录";
  return value.replace("T", " ").slice(0, 16);
}

export function statusLabel(code: string) {
  return statusLabelMap[code] ?? code;
}

export function projectTypeLabel(value: Project["project_type"]) {
  if (!value) return "待补录";
  return projectTypeLabelMap[value] ?? value;
}
