import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
} from "./lib/api";
import type {
  Contract,
  ContractAcceptanceRecord,
  ContractPaymentRecord,
  ContractProgressLog,
  Project,
  ProjectListResponse,
} from "./types";
import { buildContractActivity } from "./lib/contract-activity";
import { formatCurrency } from "./lib/format";

const today = () => new Date().toISOString().slice(0, 10);
const contractStatus: Record<Contract["status"], string> = {
  active: "正常",
  terminated: "已解除",
  paused: "暂停",
};
const acceptanceStatus: Record<Contract["acceptance_status"], string> = {
  not_accepted: "未验收",
  accepting: "验收中",
  needs_rectification: "待整改",
  accepted: "验收通过",
};
const paymentStatus: Record<Contract["payment_status"], string> = {
  unpaid: "未支付",
  partial: "部分支付",
  paid: "已全部支付",
};
const deliveryLabel = (contract: Contract) => {
  const schedule = contract.delivery_schedule;
  if (schedule.kind === "delivered") return `已交付 · ${schedule.date}`;
  if (schedule.kind === "upcoming") return `距计划交付 ${schedule.days} 天`;
  if (schedule.kind === "due_today") return "计划今日交付";
  if (schedule.kind === "overdue") return `逾期 ${schedule.days} 天`;
  return "待补充签订日期与交付周期";
};
const deliveryCalendarLabel = (contract: Contract) => ({
  holiday_calendar: "法定节假日日历",
  weekday_fallback: "工作日仅排除周末",
  calendar_days: "自然日",
  calendar_weeks: "自然周",
  calendar_months: "日历月",
  calendar_years: "日历年",
}[contract.delivery_schedule.calendar_source] || "系统日历");

type FormState = {
  name: string;
  contract_no: string;
  supplier: string;
  total_amount: string;
  signed_on: string;
  planned_completion_on: string;
  delivery_period_value: string;
  delivery_period_unit: Exclude<Contract["delivery_period_unit"], null> | "";
  actual_delivered_on: string;
  note: string;
};
const emptyForm = (): FormState => ({
  name: "",
  contract_no: "",
  supplier: "",
  total_amount: "",
  signed_on: "",
  planned_completion_on: "",
  delivery_period_value: "",
  delivery_period_unit: "",
  actual_delivered_on: "",
  note: "",
});
const toForm = (contract: Contract): FormState => ({
  name: contract.name,
  contract_no: contract.contract_no || "",
  supplier: contract.supplier,
  total_amount:
    contract.total_amount == null ? "" : String(contract.total_amount),
  signed_on: contract.signed_on || "",
  planned_completion_on: contract.planned_completion_on || "",
  delivery_period_value: contract.delivery_period_value == null ? "" : String(contract.delivery_period_value),
  delivery_period_unit: contract.delivery_period_unit || "",
  actual_delivered_on: contract.actual_delivered_on || "",
  note: contract.note,
});

export default function ContractPanel({
  projectId,
  contextProject,
  initialProjectIds = [],
  initialContractId,
  operator,
  onChanged,
  onClose,
  allowCreate = true,
  defaultReadOnly = false,
}: {
  projectId?: number;
  contextProject?: Pick<Project, "id" | "name" | "project_code">;
  initialProjectIds?: number[];
  initialContractId?: number | null;
  operator: string;
  onChanged: (projectIds: number[]) => Promise<void> | void;
  onClose?: () => void;
  allowCreate?: boolean;
  defaultReadOnly?: boolean;
}) {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [contract, setContract] = useState<Contract | null>(null);
  const [mode, setMode] = useState<"list" | "create" | "detail" | "link" | "relations">(
    initialContractId ? "detail" : "list",
  );
  const [form, setForm] = useState<FormState>(emptyForm());
  const [selectedProjectIds, setSelectedProjectIds] =
    useState<number[]>(initialProjectIds);
  const [allocatedAmounts, setAllocatedAmounts] = useState<
    Record<number, string>
  >({});
  const [activeProjects, setActiveProjects] = useState<Project[]>([]);
  const [completedProjects, setCompletedProjects] = useState<Project[]>([]);
  const [allContracts, setAllContracts] = useState<Contract[]>([]);
  const [supplierSuggestions, setSupplierSuggestions] = useState<string[]>([]);
  const [progress, setProgress] = useState("");
  const [editingLog, setEditingLog] = useState<ContractProgressLog | null>(
    null,
  );
  const [logValue, setLogValue] = useState("");
  const [deletingLog, setDeletingLog] = useState<ContractProgressLog | null>(
    null,
  );
  const [deleteReason, setDeleteReason] = useState("");
  const [acceptance, setAcceptance] = useState<{
    status: ContractAcceptanceRecord["acceptance_status"];
    date: string;
    result: string;
    note: string;
  }>({ status: "accepting", date: today(), result: "", note: "" });
  const [relationReason, setRelationReason] = useState("");
  const [payment, setPayment] = useState({ amount: "", paid_on: today(), note: "" });
  const [editingPayment, setEditingPayment] = useState<ContractPaymentRecord | null>(null);
  const [activeAction, setActiveAction] = useState<"progress" | "acceptance" | "payment" | null>(null);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [editing, setEditing] = useState(!defaultReadOnly);

  const projectIds = useMemo(
    () => contract?.projects.map((item) => item.id) ?? selectedProjectIds,
    [contract, selectedProjectIds],
  );
  useEffect(() => {
    void Promise.all([
      apiGet<ProjectListResponse>(
        "/projects",
        new URLSearchParams({ group: "pool_active", page_size: "200" }),
      ),
      apiGet<ProjectListResponse>(
        "/projects",
        new URLSearchParams({ group: "completed", page_size: "200" }),
      ),
    ])
      .then(([active, completed]) => {
        setActiveProjects(active.items);
        setCompletedProjects(completed.items);
      })
      .catch(() => {
        setActiveProjects([]);
        setCompletedProjects([]);
      });
  }, []);

  useEffect(() => {
    if (initialContractId) {
      void openContract(initialContractId);
    } else if (projectId) {
      void loadProjectContracts(projectId);
    }
  }, [initialContractId, projectId]);

  async function loadProjectContracts(id: number) {
    try {
      const data = await apiGet<Contract[]>(`/projects/${id}/contracts`);
      setContracts(data);
      if (!data.length && !initialProjectIds.length) setMode("list");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同加载失败");
    }
  }

  async function openContract(id: number) {
    try {
      const data = await apiGet<Contract>(`/contracts/${id}`);
      setContract(data);
      setForm(toForm(data));
      setSelectedProjectIds(data.projects.map((item) => item.id));
      setAllocatedAmounts(
        Object.fromEntries(
          data.projects.map((item) => [
            item.id,
            item.allocated_amount == null ? "" : String(item.allocated_amount),
          ]),
        ),
      );
      setAcceptance({
        status:
          data.acceptance_status === "not_accepted"
            ? "accepting"
            : data.acceptance_status,
        date: data.acceptance_records?.[0]?.acceptance_date || today(),
        result: data.acceptance_records?.[0]?.result || "",
        note: data.acceptance_records?.[0]?.note || "",
      });
      setMode("detail");
      setEditing(false);
      setActiveAction(null);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同加载失败");
    }
  }

  function toggleProject(id: number) {
    setSelectedProjectIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  }

  function projectLinks() {
    return selectedProjectIds.map((id) => ({
      project_id: id,
      allocated_amount:
        allocatedAmounts[id] === "" || allocatedAmounts[id] == null
          ? null
          : allocatedAmounts[id],
    }));
  }

  const linkableProjects = [
    ...activeProjects,
    ...completedProjects.filter(
      (item) => !activeProjects.some((active) => active.id === item.id),
    ),
  ];
  const hasHistoricalSelection = selectedProjectIds.some(
    (id) => !activeProjects.some((item) => item.id === id),
  );
  const isProjectContext = Boolean(projectId);

  async function returnToList() {
    setContract(null);
    setEditing(false);
    setActiveAction(null);
    setMode("list");
    setError("");
    if (projectId) await loadProjectContracts(projectId);
  }

  async function refresh(updated: Contract, message: string, destination: "list" | "detail" = isProjectContext ? "list" : "detail") {
    setContract(updated);
    setContracts((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
    setForm(toForm(updated));
    setSelectedProjectIds(updated.projects.map((item) => item.id));
    setAllocatedAmounts(
      Object.fromEntries(
        updated.projects.map((item) => [
          item.id,
          item.allocated_amount == null ? "" : String(item.allocated_amount),
        ]),
      ),
    );
    setAcceptance({
      status:
        updated.acceptance_status === "not_accepted"
          ? "accepting"
          : updated.acceptance_status,
      date: updated.acceptance_records?.[0]?.acceptance_date || today(),
      result: updated.acceptance_records?.[0]?.result || "",
      note: updated.acceptance_records?.[0]?.note || "",
    });
    setMode(destination);
    setEditing(false);
    setActiveAction(null);
    await onChanged(updated.projects.map((item) => item.id));
    if (projectId) await loadProjectContracts(projectId);
    setFeedback(message);
    setError("");
  }

  async function create() {
    try {
      const created = await apiPost<Contract>("/contracts", {
        ...form,
        total_amount: form.total_amount || null,
        project_links: projectLinks(),
        history_correction: hasHistoricalSelection,
        reason: historicalCreate ? relationReason : undefined,
        operator,
      });
      await refresh(created, "合同已创建。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同保存失败");
    }
  }

  async function save() {
    if (!contract) return;
    try {
      const updated = await apiPatch<Contract>(`/contracts/${contract.id}`, {
        ...form,
        total_amount: form.total_amount || null,
        operator,
      });
      await refresh(updated, "合同已更新。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同保存失败");
    }
  }

  async function applyException(action: "pause" | "resume" | "terminate") {
    if (!contract) return;
    const reason = window.prompt(action === "pause" ? "暂停原因" : action === "terminate" ? "解除原因" : "") || "";
    if (action !== "resume" && !reason.trim()) return;
    try {
      const updated = await apiPost<Contract>(`/contracts/${contract.id}/${action}`, { reason: reason.trim(), operator });
      await refresh(updated, action === "pause" ? "合同已暂停。" : action === "resume" ? "合同已恢复。" : "合同已解除。", "detail");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同例外操作失败");
    }
  }

  async function saveProjects() {
    if (!contract) return;
    try {
      const currentIds = contract.projects.map((item) => item.id);
      const historyCorrection = selectedProjectIds.some(
        (id) =>
          !currentIds.includes(id) &&
          !activeProjects.some((item) => item.id === id),
      );
      const updated = await apiPut<Contract>(
        `/contracts/${contract.id}/projects`,
        {
          project_links: projectLinks(),
          history_correction: historyCorrection,
          reason: relationReason,
          operator,
        },
      );
      setRelationReason("");
      await refresh(updated, "合同关联项目已更新。", "detail");
      if (!currentIds.every((id) => selectedProjectIds.includes(id)))
        setFeedback("合同关联项目已更新。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同关联更新失败");
    }
  }

  async function addProgress() {
    if (!contract || !progress.trim()) return;
    try {
      const log = await apiPost<ContractProgressLog>(
        `/contracts/${contract.id}/progress-logs`,
        { content: progress.trim(), operator },
      );
      const updated = {
        ...contract,
        latest_progress: log,
        progress_logs: [...(contract.progress_logs || []), log],
      };
      setProgress("");
      await refresh(updated, "合同进展已记录。", "detail");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同进展保存失败");
    }
  }

  async function saveLog() {
    if (!contract || !editingLog || !logValue.trim()) return;
    try {
      const log = await apiPatch<ContractProgressLog>(
        `/contracts/${contract.id}/progress-logs/${editingLog.id}`,
        { content: logValue.trim(), operator },
      );
      const logs = (contract.progress_logs || []).map((item) =>
        item.id === log.id ? log : item,
      );
      setEditingLog(null);
      await refresh(
        {
          ...contract,
          latest_progress: logs.length ? logs[logs.length - 1] : null,
          progress_logs: logs,
        },
        "合同进展已修改。",
        "detail",
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同进展修改失败");
    }
  }

  async function removeLog() {
    if (!contract || !deletingLog || !deleteReason.trim()) return;
    try {
      await apiDelete(
        `/contracts/${contract.id}/progress-logs/${deletingLog.id}`,
        { reason: deleteReason.trim(), operator },
      );
      const logs = (contract.progress_logs || []).filter(
        (item) => item.id !== deletingLog.id,
      );
      setDeletingLog(null);
      setDeleteReason("");
      await refresh(
        {
          ...contract,
          latest_progress: logs.length ? logs[logs.length - 1] : null,
          progress_logs: logs,
        },
        "合同进展已删除。",
        "detail",
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同进展删除失败");
    }
  }

  async function recordAcceptance() {
    if (!contract) return;
    try {
      const record = await apiPost<ContractAcceptanceRecord>(
        `/contracts/${contract.id}/acceptance-records`,
        {
          acceptance_status: acceptance.status,
          acceptance_date: acceptance.date,
          result: acceptance.result,
          note: acceptance.note,
          operator,
        },
      );
      await refresh(
        await apiGet<Contract>(`/contracts/${contract.id}`),
        "验收结果已登记。",
        "detail",
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "验收登记失败");
    }
  }

  async function savePayment() {
    if (!contract) return;
    try {
      const payload = { amount: payment.amount, paid_on: payment.paid_on, note: payment.note };
      const updated = editingPayment
        ? await apiPatch<Contract>(`/contracts/${contract.id}/payment-records/${editingPayment.id}`, payload)
        : await apiPost<Contract>(`/contracts/${contract.id}/payment-records`, payload);
      setPayment({ amount: "", paid_on: today(), note: "" });
      setEditingPayment(null);
      await refresh(updated, editingPayment ? "付款记录已更正。" : "付款记录已登记。", "detail");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "付款记录保存失败");
    }
  }

  async function removePayment(paymentId: number) {
    if (!contract) return;
    try {
      const updated = await apiDelete<Contract>(`/contracts/${contract.id}/payment-records/${paymentId}`);
      await refresh(updated, "付款记录已删除。", "detail");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "付款记录删除失败");
    }
  }

  async function openExistingContracts() {
    try {
      setAllContracts(await apiGet<Contract[]>("/contracts"));
      setMode("link");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同列表加载失败");
    }
  }

  async function linkExisting(existing: Contract) {
    if (!projectId) return;
    try {
      const ids = [
        ...new Set([...existing.projects.map((item) => item.id), projectId]),
      ];
      const historyCorrection = !activeProjects.some(
        (item) => item.id === projectId,
      );
      const updated = await apiPut<Contract>(
        `/contracts/${existing.id}/projects`,
        {
          project_links: ids.map((id) => ({
            project_id: id,
            allocated_amount:
              existing.projects.find((item) => item.id === id)
                ?.allocated_amount ?? null,
          })),
          history_correction: historyCorrection,
          reason: relationReason,
          operator,
        },
      );
      setRelationReason("");
      await refresh(updated, "已有合同已关联当前项目。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同关联失败");
    }
  }

  function handleSupplier(value: string) {
    setForm((current) => ({ ...current, supplier: value }));
    void apiGet<string[]>(
      "/contracts/supplier-suggestions",
      new URLSearchParams({ query: value }),
    )
      .then(setSupplierSuggestions)
      .catch(() => setSupplierSuggestions([]));
  }

  const selectedNames =
    contract?.projects.map((item) => item.name).join("、") ||
    linkableProjects
      .filter((item) => selectedProjectIds.includes(item.id))
      .map((item) => item.name)
      .join("、") ||
    (selectedProjectIds.includes(contextProject?.id ?? -1)
      ? contextProject?.name
      : "");
  const linkedProjectRows = contract?.projects ?? [
    ...linkableProjects.filter((item) => selectedProjectIds.includes(item.id)),
    ...(contextProject &&
    selectedProjectIds.includes(contextProject.id) &&
    !linkableProjects.some((item) => item.id === contextProject.id)
      ? [contextProject]
      : []),
  ];
  const historicalCreate = Boolean(hasHistoricalSelection && mode === "create");
  const recentActivity = contract ? buildContractActivity(contract) : [];

  function activateAction(action: "progress" | "acceptance" | "payment") {
    setActiveAction((current) => current === action ? null : action);
    setEditingLog(null);
    setDeletingLog(null);
    setEditingPayment(null);
  }

  return (
    <section className="contract-panel">
      <div className="panel-heading">
        <div>
          <h3>
            {mode === "create"
              ? historicalCreate
                ? "补录历史合同"
                : "添加合同"
              : mode === "detail"
                ? editing
                  ? "编辑合同"
                  : "合同办理"
                : mode === "relations"
                  ? "管理关联项目"
                  : "合同列表"}
          </h3>
          {selectedNames ? <small>关联项目：{selectedNames}</small> : null}
        </div>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
      {feedback ? <div className="notice success">{feedback}</div> : null}
      {mode === "detail" && contract && !editing ? (
        <div className="contract-context-actions">
          <button className="mini-button" onClick={() => void returnToList()}>
            返回合同列表
          </button>
        </div>
      ) : null}
      {mode === "list" ? (
        <>
          {contracts.length ? (
            <div className="contract-list">
              {contracts.map((item) => (
                <button
                  type="button"
                  className="contract-row"
                  key={item.id}
                  onClick={() => void openContract(item.id)}
                >
                  <strong>
                    {item.contract_no} · {item.name}
                  </strong>
                  <span>{item.supplier || "未填写供应商"}</span>
                  <small>{item.status === "terminated" ? "已解除" : item.status === "paused" ? `已暂停 · ${deliveryLabel(item)}` : deliveryLabel(item)}</small>
                  <em>
                    {acceptanceStatus[item.acceptance_status]}
                    {item.latest_progress
                      ? ` · 最近：${item.latest_progress.content}`
                      : ""}
                  </em>
                </button>
              ))}
            </div>
          ) : (
            <div className="empty-state">暂无合同。</div>
          )}
          <div className="work-item-actions">
            {allowCreate || (defaultReadOnly && projectId) ? (
              <button
                className="action-button primary"
                onClick={() => {
                  setForm(emptyForm());
                  setSelectedProjectIds(
                    projectId ? [projectId] : initialProjectIds,
                  );
                  setAllocatedAmounts({});
                  setRelationReason("");
                  setMode("create");
                  setEditing(true);
                }}
              >
                {defaultReadOnly ? "补录历史合同" : "＋ 添加合同"}
              </button>
            ) : null}
            {projectId ? (
              <button
                className="mini-button"
                onClick={() => void openExistingContracts()}
              >
                关联已有合同
              </button>
            ) : null}
          </div>
        </>
      ) : null}
      {mode === "link" ? (
        <div className="contract-link-list">
          <label className="field">
            <span>补录/纠错原因</span>
            <input
              className="input"
              value={relationReason}
              onChange={(event) => setRelationReason(event.target.value)}
              placeholder="关联已完成项目时必填"
            />
          </label>
          {allContracts.map((item) => (
            <button
              type="button"
              className="contract-row"
              key={item.id}
              onClick={() => void linkExisting(item)}
            >
              <strong>
                {item.contract_no} · {item.name}
              </strong>
              <span>{item.supplier || "未填写供应商"}</span>
            </button>
          ))}
          <button className="mini-button" onClick={() => void returnToList()}>
            返回合同列表
          </button>
        </div>
      ) : null}
      {mode === "relations" && contract ? (
        <section className="contract-relation-editor">
          <p className="muted-copy">管理关联项目及各项目涉及金额；合同基础信息和办理记录不会在此修改。</p>
          <details className="contract-project-picker" open>
            <summary>关联项目（{selectedProjectIds.length}）</summary>
            <strong>推进中项目</strong>
            {activeProjects.map((item) => (
              <label key={item.id} className="check-row">
                <input type="checkbox" checked={selectedProjectIds.includes(item.id)} onChange={() => toggleProject(item.id)} />
                {item.project_code} · {item.name}
              </label>
            ))}
            <strong>已完成项目（补录/纠错）</strong>
            {completedProjects.map((item) => (
              <label key={item.id} className="check-row">
                <input type="checkbox" checked={selectedProjectIds.includes(item.id)} onChange={() => toggleProject(item.id)} />
                {item.project_code} · {item.name}
              </label>
            ))}
            {linkedProjectRows.map((item) => (
              <label className="field" key={`relation-allocation-${item.id}`}>
                <span>{item.project_code} · {item.name} 分摊金额（万元，可选）</span>
                <input className="input" inputMode="decimal" value={allocatedAmounts[item.id] ?? ""} onChange={(event) => setAllocatedAmounts((current) => ({ ...current, [item.id]: event.target.value }))} />
              </label>
            ))}
            <label className="field">
              <span>调整关联原因</span>
              <input className="input" value={relationReason} onChange={(event) => setRelationReason(event.target.value)} placeholder="新增已完成项目或移除关联时必填" />
            </label>
          </details>
          <div className="work-item-actions">
            <button className="mini-button" onClick={() => setMode("detail")}>返回合同</button>
            <button className="action-button primary" onClick={() => void saveProjects()}>保存关联项目</button>
          </div>
        </section>
      ) : null}
      {mode === "detail" && contract && !editing ? (
        <div className="contract-readonly contract-overview">
          <div className="contract-fact-list">
            <div className="contract-fact"><span>合同名称</span><strong>{contract.name}</strong></div>
            <div className="contract-fact"><span>合同编号</span><strong>{contract.contract_no}</strong></div>
            <div className="contract-fact"><span>供应商</span><strong>{contract.supplier || "未填写"}</strong></div>
            <div className="contract-fact contract-amount"><span>合同总金额</span><strong>{contract.total_amount == null ? "未记录" : `${formatCurrency(contract.total_amount)} 万`}</strong></div>
            <div className="contract-fact"><span>计划交付日期</span><strong>{contract.planned_delivery_on || "未设置"}</strong></div>
            <div className="contract-fact"><span>验收状态</span><strong>{acceptanceStatus[contract.acceptance_status]}</strong></div>
            <div className="contract-fact"><span>交付提示</span><strong>{deliveryLabel(contract)}</strong></div>
            {contract.status !== "active" ? <div className="contract-fact contract-exception"><span>合同例外</span><strong>{contractStatus[contract.status]}</strong></div> : null}
          </div>
          {contract.note ? <p className="contract-note">{contract.note}</p> : null}

          <section className="contract-linked-projects">
            <div className="section-heading"><h4>关联项目</h4><span><small>共 {contract.projects.length} 项</small><button type="button" className="text-button" onClick={() => setMode("relations")}>管理</button></span></div>
            <div className="progress-list">
              {contract.projects.map((item) => <div className="progress-entry" key={item.id}><span>{item.project_code} · {item.name}</span><small>分摊 {item.allocated_amount == null ? "未登记" : `${formatCurrency(item.allocated_amount)} 万`}</small></div>)}
            </div>
            <p className="contract-allocation-summary">项目分摊：{contract.allocation_complete ? `${formatCurrency(contract.allocation_total ?? 0)} 万${contract.allocation_difference ? `（差额 ${formatCurrency(contract.allocation_difference)} 万）` : "（一致）"}` : "待补录"}</p>
          </section>

          <section className="contract-handling">
            <div className="section-heading"><h4>办理记录</h4><small>选择一项操作，填写区域才会展开</small></div>
            <div className="contract-action-tabs">
              <button type="button" aria-label="新增合同进展" className={`mini-button ${activeAction === "progress" ? "active" : ""}`} disabled={contract.status !== "active"} onClick={() => activateAction("progress")}>＋ 进展</button>
              <button type="button" aria-label="登记合同验收" className={`mini-button ${activeAction === "acceptance" ? "active" : ""}`} disabled={contract.status !== "active"} onClick={() => activateAction("acceptance")}>＋ 验收</button>
              <button type="button" aria-label="登记合同付款" className={`mini-button ${activeAction === "payment" ? "active" : ""}`} disabled={contract.status !== "active"} onClick={() => activateAction("payment")}>＋ 付款</button>
            </div>
            {contract.status !== "active" ? <p className="muted-copy">暂停或已解除合同不可新增办理记录。</p> : null}
            {activeAction === "progress" ? <div className="contract-action-form">
              <div className="progress-list">{(contract.progress_logs || []).map((log) => <div key={log.id} className="progress-entry"><span>{log.created_at.slice(0, 10)} · {log.content}</span><button className="text-button" onClick={() => { setEditingLog(log); setLogValue(log.content); }}>编辑</button><button className="text-button danger" onClick={() => { setDeletingLog(log); setDeleteReason(""); }}>删除</button></div>)}</div>
              <textarea className="textarea" rows={2} value={progress} onChange={(event) => setProgress(event.target.value)} placeholder="新增进展" />
              <button className="mini-button active" onClick={() => void addProgress()}>记录进展</button>
              {editingLog ? <div className="inline-form"><input className="input" value={logValue} onChange={(event) => setLogValue(event.target.value)} /><button className="mini-button" onClick={() => setEditingLog(null)}>取消</button><button className="mini-button active" onClick={() => void saveLog()}>保存修改</button></div> : null}
              {deletingLog ? <div className="inline-form"><input className="input" value={deleteReason} onChange={(event) => setDeleteReason(event.target.value)} placeholder="删除原因（必填）" /><button className="mini-button" onClick={() => setDeletingLog(null)}>取消</button><button className="mini-button danger" onClick={() => void removeLog()}>确认删除</button></div> : null}
            </div> : null}
            {activeAction === "acceptance" ? <div className="contract-action-form">
              <div className="field-grid"><label className="field"><span>验收状态</span><select className="select" value={acceptance.status} onChange={(event) => setAcceptance({ ...acceptance, status: event.target.value as ContractAcceptanceRecord["acceptance_status"] })}><option value="accepting">验收中</option><option value="needs_rectification">待整改</option><option value="accepted">验收通过</option></select></label><label className="field"><span>验收日期 *</span><input className="input" type="date" value={acceptance.date} onChange={(event) => setAcceptance({ ...acceptance, date: event.target.value })} /></label></div>
              <label className="field"><span>验收结果{acceptance.status === "accepted" ? " *" : ""}</span><input className="input" value={acceptance.result} onChange={(event) => setAcceptance({ ...acceptance, result: event.target.value })} /></label>
              <label className="field"><span>验收说明</span><textarea className="textarea" rows={2} value={acceptance.note} onChange={(event) => setAcceptance({ ...acceptance, note: event.target.value })} /></label>
              <button className="mini-button active" onClick={() => void recordAcceptance()}>登记验收结果</button>
              <div className="progress-list">{(contract.acceptance_records || []).map((item) => <div className="progress-entry" key={item.id}><span>{item.acceptance_date} · {acceptanceStatus[item.acceptance_status]}{item.result ? ` · ${item.result}` : ""}</span></div>)}</div>
            </div> : null}
            {activeAction === "payment" ? <div className="contract-action-form">
              <div className="progress-list">{(contract.payment_records || []).map((item) => <div className="progress-entry" key={item.id}><span>{item.paid_on} · {formatCurrency(item.amount)} 万{item.note ? ` · ${item.note}` : ""}</span><button type="button" className="text-button" onClick={() => { setEditingPayment(item); setPayment({ amount: item.amount, paid_on: item.paid_on, note: item.note }); }}>更正</button><button type="button" className="text-button danger" onClick={() => void removePayment(item.id)}>删除</button></div>)}</div>
              {!contract.payment_records?.length ? <span className="muted-copy">尚未登记付款。</span> : null}
              <div className="inline-form contract-payment-form"><input className="input" inputMode="decimal" value={payment.amount} onChange={(event) => setPayment({ ...payment, amount: event.target.value })} placeholder="付款金额（万元）" /><input className="input" type="date" value={payment.paid_on} onChange={(event) => setPayment({ ...payment, paid_on: event.target.value })} /><input className="input" value={payment.note} onChange={(event) => setPayment({ ...payment, note: event.target.value })} placeholder="说明（可选）" />{editingPayment ? <button type="button" className="mini-button" onClick={() => { setEditingPayment(null); setPayment({ amount: "", paid_on: today(), note: "" }); }}>取消</button> : null}<button type="button" className="mini-button active" onClick={() => void savePayment()}>{editingPayment ? "保存更正" : "登记付款"}</button></div>
            </div> : null}
          </section>

          <section className="contract-business-summary"><div className="section-heading"><h4>业务概况</h4><small>截至当前</small></div><div className="contract-fact"><span>验收</span><strong>{acceptanceStatus[contract.acceptance_status]}{contract.acceptance_records?.length ? " · 已有记录" : " · 暂无记录"}</strong></div><div className="contract-fact"><span>付款</span><strong>已付 {formatCurrency(contract.paid_total)} 万 / {contract.total_amount == null ? "未记录" : `${formatCurrency(contract.total_amount)} 万`}</strong></div></section>
          <section className="contract-recent-activity"><div className="section-heading"><h4>最近动态</h4><small>共 {recentActivity.length} 条</small></div>{recentActivity.length ? <div className="progress-list">{recentActivity.map((item) => <div className="progress-entry" key={item.id}><span>{item.occurredAt.slice(0, 10)} · {item.title}{item.note ? ` · ${item.note}` : ""}</span></div>)}</div> : <p className="muted-copy">暂无办理记录。</p>}</section>
          <section className="contract-management"><div className="section-heading"><h4>合同管理</h4>{contract.status !== "active" ? <small>{contractStatus[contract.status]}</small> : null}</div><div className="contract-management-actions"><button className="mini-button" onClick={() => setEditing(true)}>编辑合同</button>{contract.status === "active" ? <button className="mini-button" onClick={() => void applyException("pause")}>暂停合同</button> : null}{contract.status === "paused" ? <button className="mini-button" onClick={() => void applyException("resume")}>恢复合同</button> : null}{contract.status !== "terminated" ? <button className="mini-button danger" onClick={() => void applyException("terminate")}>解除合同</button> : null}</div></section>
        </div>
      ) : null}
      {mode === "create" || (mode === "detail" && editing) ? (
        <section className="contract-edit-form">
          <div className="field-grid">
            <label className="field">
              <span>合同编号 *</span>
              <input
                className="input"
                value={form.contract_no}
                onChange={(event) =>
                  setForm({ ...form, contract_no: event.target.value })
                }
              />
            </label>
            <label className="field">
              <span>合同名称 *</span>
              <input
                className="input"
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
              />
            </label>
          </div>
          <div className="field-grid">
            <label className="field">
              <span>供应商</span>
              <input
                className="input"
                list="contract-suppliers"
                value={form.supplier}
                onChange={(event) => handleSupplier(event.target.value)}
              />
            </label>
            <datalist id="contract-suppliers">
              {supplierSuggestions.map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
            <label className="field">
              <span>合同总金额（万元）</span>
              <input
                className="input"
                inputMode="decimal"
                value={form.total_amount}
                onChange={(event) =>
                  setForm({ ...form, total_amount: event.target.value })
                }
              />
            </label>
          </div>
          <div className="field-grid">
            <label className="field">
              <span>签订日期</span>
              <input
                className="input"
                type="date"
                value={form.signed_on}
                onChange={(event) =>
                  setForm({ ...form, signed_on: event.target.value })
                }
              />
            </label>
            <label className="field">
              <span>实际交付日期</span>
              <input
                className="input"
                type="date"
                value={form.actual_delivered_on}
                onChange={(event) =>
                  setForm({
                    ...form,
                    actual_delivered_on: event.target.value,
                  })
                }
              />
            </label>
          </div>
          <div className="field-grid">
            <label className="field">
              <span>约定交付周期</span>
              <input
                className="input"
                inputMode="numeric"
                value={form.delivery_period_value}
                onChange={(event) =>
                  setForm({ ...form, delivery_period_value: event.target.value })
                }
              />
            </label>
            <label className="field">
              <span>交付周期单位</span>
              <select className="select" value={form.delivery_period_unit} onChange={(event) => setForm({ ...form, delivery_period_unit: event.target.value as FormState["delivery_period_unit"] })}>
                <option value="">未设置</option>
                <option value="calendar_days">自然日</option>
                <option value="working_days">工作日</option>
                <option value="weeks">周</option>
                <option value="months">月</option>
                <option value="years">年</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>人工计划交付日期（可选）</span>
            <input className="input" type="date" value={form.planned_completion_on} onChange={(event) => setForm({ ...form, planned_completion_on: event.target.value })} />
          </label>
          {contract?.calculated_delivery_on ? <p className={contract.delivery_plan_conflict ? "notice error" : "muted-copy"}>
            系统计算计划交付日期：{contract.calculated_delivery_on}（{deliveryCalendarLabel(contract)}）{contract.delivery_plan_conflict ? `；当前人工日期 ${contract.planned_completion_on} 优先` : ""}
          </p> : null}
          {historicalCreate ? (
            <label className="field">
              <span>补录历史合同原因 *</span>
              <input
                className="input"
                value={relationReason}
                onChange={(event) =>
                  setRelationReason(event.target.value)
                }
              />
            </label>
          ) : null}
          <label className="field">
            <span>说明</span>
            <textarea
              className="textarea"
              rows={2}
              value={form.note}
              onChange={(event) =>
                setForm({ ...form, note: event.target.value })
              }
            />
          </label>
          {mode === "create" ? <details className="contract-project-picker" open>
            <summary>关联项目（{selectedProjectIds.length}）</summary>
            <strong>推进中项目</strong>
            {activeProjects.map((item) => (
              <label key={item.id} className="check-row">
                <input
                  type="checkbox"
                  checked={selectedProjectIds.includes(item.id)}
                  onChange={() => toggleProject(item.id)}
                />
                {item.project_code} · {item.name}
              </label>
            ))}
            <strong>已完成项目（补录/纠错）</strong>
            {completedProjects.map((item) => (
              <label key={item.id} className="check-row">
                <input
                  type="checkbox"
                  checked={selectedProjectIds.includes(item.id)}
                  onChange={() => toggleProject(item.id)}
                />
                {item.project_code} · {item.name}
              </label>
            ))}
            {linkedProjectRows.map((item) => (
              <label className="field" key={`allocation-${item.id}`}>
                <span>
                  {item.project_code} · {item.name} 分摊金额（万元，可选）
                </span>
                <input
                  className="input"
                  inputMode="decimal"
                  value={allocatedAmounts[item.id] ?? ""}
                  onChange={(event) =>
                    setAllocatedAmounts((current) => ({
                      ...current,
                      [item.id]: event.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </details> : null}
          <div className="work-item-actions">
            <button className="mini-button" onClick={() => void returnToList()}>
              返回合同列表
            </button>
            <button
              className="action-button primary"
              onClick={() => void (mode === "create" ? create() : save())}
            >
              {mode === "create" ? "保存合同" : "保存合同信息"}
            </button>
          </div>
        </section>
      ) : null}
    </section>
  );
}
