export type ContractActivityKind = "progress" | "acceptance" | "payment";

export type ContractActivity = {
  id: string;
  kind: ContractActivityKind;
  occurredAt: string;
  title: string;
  note: string;
};

type ActivitySource = {
  progress_logs?: Array<{ id: number; content: string; created_at: string }>;
  acceptance_records?: Array<{ id: number; acceptance_status: "accepting" | "needs_rectification" | "accepted"; acceptance_date: string; result: string; note: string; created_at?: string }>;
  payment_records?: Array<{ id: number; amount: string; paid_on: string; note: string; created_at?: string }>;
};

const acceptanceLabel = {
  accepting: "验收中",
  needs_rectification: "待整改",
  accepted: "验收通过",
};
const sameMomentOrder: Record<ContractActivityKind, number> = { progress: 0, acceptance: 1, payment: 2 };

export function buildContractActivity(source: ActivitySource): ContractActivity[] {
  const activity: ContractActivity[] = [
    ...(source.progress_logs ?? []).map((item) => ({ id: `progress:${item.id}`, kind: "progress" as const, occurredAt: item.created_at, title: "合同进展", note: item.content })),
    ...(source.acceptance_records ?? []).map((item) => ({ id: `acceptance:${item.id}`, kind: "acceptance" as const, occurredAt: item.created_at || item.acceptance_date, title: item.result ? `${acceptanceLabel[item.acceptance_status]} · ${item.result}` : acceptanceLabel[item.acceptance_status], note: item.note })),
    ...(source.payment_records ?? []).map((item) => ({ id: `payment:${item.id}`, kind: "payment" as const, occurredAt: item.created_at || item.paid_on, title: `付款 · ${item.amount} 万`, note: item.note })),
  ];
  return activity.sort((left, right) => right.occurredAt.localeCompare(left.occurredAt) || sameMomentOrder[left.kind] - sameMomentOrder[right.kind] || right.id.localeCompare(left.id));
}
