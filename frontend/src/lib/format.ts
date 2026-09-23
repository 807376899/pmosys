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
  teaching_software: "专业教学软件项目",
  software: "专业教学软件项目",
  practical_teaching_site: "实践教学场所项目",
  laboratory: "实践教学场所项目",
};

/**
 * Money is intentionally formatted as decimal text rather than through
 * `Intl.NumberFormat`: the latter rounds when a maximum fraction precision is
 * supplied, and converting a saved decimal through a JavaScript number can
 * lose the user's original precision.  The API may still return legacy
 * numeric values, hence the small union here.
 */
export function formatCurrency(value: string | number | null | undefined) {
  if (value == null || value === "") return "0";
  const raw = String(value).trim();
  if (!/^-?\d+(?:\.\d+)?$/.test(raw)) return raw;
  const negative = raw.startsWith("-");
  const [integerPart, fractionPart] = (negative ? raw.slice(1) : raw).split(".");
  const normalizedInteger = (integerPart.replace(/^0+(?=\d)/, "") || "0")
    .replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const normalizedFraction = fractionPart?.replace(/0+$/, "");
  return `${negative ? "-" : ""}${normalizedInteger}${normalizedFraction ? `.${normalizedFraction}` : ""}`;
}

function moneyParts(value: string | number | null | undefined) {
  const raw = String(value ?? "0").trim();
  if (!/^\d+(?:\.\d+)?$/.test(raw)) return { digits: 0n, scale: 0 };
  const [whole, fraction = ""] = raw.split(".");
  return { digits: BigInt(`${whole}${fraction}`), scale: fraction.length };
}

export function compareMoney(left: string | number | null | undefined, right: string | number | null | undefined) {
  const a = moneyParts(left), b = moneyParts(right), scale = Math.max(a.scale, b.scale);
  const av = a.digits * 10n ** BigInt(scale - a.scale), bv = b.digits * 10n ** BigInt(scale - b.scale);
  return av === bv ? 0 : av > bv ? 1 : -1;
}

export function sumMoney(values: Array<string | number | null | undefined>) {
  const parts = values.map(moneyParts), scale = Math.max(0, ...parts.map((item) => item.scale));
  const result = parts.reduce((current, item) => current + item.digits * 10n ** BigInt(scale - item.scale), 0n).toString().padStart(scale + 1, "0");
  const whole = scale ? result.slice(0, -scale) : result;
  const fraction = scale ? result.slice(-scale).replace(/0+$/, "") : "";
  return fraction ? `${whole}.${fraction}` : whole;
}

export function subtractMoney(left: string | number | null | undefined, right: string | number | null | undefined) {
  const a = moneyParts(left), b = moneyParts(right), scale = Math.max(a.scale, b.scale);
  const result = a.digits * 10n ** BigInt(scale - a.scale) - b.digits * 10n ** BigInt(scale - b.scale);
  const negative = result < 0n, raw = (negative ? -result : result).toString().padStart(scale + 1, "0");
  const whole = scale ? raw.slice(0, -scale) : raw;
  const fraction = scale ? raw.slice(-scale).replace(/0+$/, "") : "";
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "未记录";
  return value.replace("T", " ").slice(0, 16);
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "未记录";
  return value.replace("T", " ").slice(0, 10);
}

export function statusLabel(code: string) {
  return statusLabelMap[code] ?? code;
}

export function projectTypeLabel(value: Project["project_type"]) {
  if (!value) return "待补录";
  return projectTypeLabelMap[value] ?? value;
}
