import { useEffect, useMemo, useState } from "react";

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./lib/api";
import type { Contract, ContractAcceptanceRecord, ContractProgressLog, Project, ProjectListResponse } from "./types";

const today = () => new Date().toISOString().slice(0, 10);
const contractStatus: Record<Contract["status"], string> = { not_started: "未开始", performing: "履约中", completed: "已完成", terminated: "已解除", paused: "暂停" };
const acceptanceStatus: Record<Contract["acceptance_status"], string> = { not_accepted: "未验收", accepting: "验收中", needs_rectification: "待整改", accepted: "验收通过" };

type FormState = { name: string; contract_no: string; supplier: string; total_amount: string; signed_on: string; planned_completion_on: string; note: string; status: Contract["status"]; reason: string };
const emptyForm = (): FormState => ({ name: "", contract_no: "", supplier: "", total_amount: "", signed_on: "", planned_completion_on: "", note: "", status: "not_started", reason: "" });
const toForm = (contract: Contract): FormState => ({ name: contract.name, contract_no: contract.contract_no || "", supplier: contract.supplier, total_amount: contract.total_amount == null ? "" : String(contract.total_amount), signed_on: contract.signed_on || "", planned_completion_on: contract.planned_completion_on || "", note: contract.note, status: contract.status, reason: "" });

export default function ContractPanel({ projectId, contextProject, initialProjectIds = [], initialContractId, operator, onChanged, onClose, allowCreate = true, defaultReadOnly = false }: {
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
  const [mode, setMode] = useState<"list" | "create" | "detail" | "link">(initialContractId ? "detail" : "list");
  const [form, setForm] = useState<FormState>(emptyForm());
  const [selectedProjectIds, setSelectedProjectIds] = useState<number[]>(initialProjectIds);
  const [allocatedAmounts, setAllocatedAmounts] = useState<Record<number, string>>({});
  const [activeProjects, setActiveProjects] = useState<Project[]>([]);
  const [completedProjects, setCompletedProjects] = useState<Project[]>([]);
  const [allContracts, setAllContracts] = useState<Contract[]>([]);
  const [supplierSuggestions, setSupplierSuggestions] = useState<string[]>([]);
  const [progress, setProgress] = useState("");
  const [editingLog, setEditingLog] = useState<ContractProgressLog | null>(null);
  const [logValue, setLogValue] = useState("");
  const [deletingLog, setDeletingLog] = useState<ContractProgressLog | null>(null);
  const [deleteReason, setDeleteReason] = useState("");
  const [acceptance, setAcceptance] = useState<{ status: ContractAcceptanceRecord["acceptance_status"]; date: string; result: string; note: string }>({ status: "accepting", date: today(), result: "", note: "" });
  const [relationReason, setRelationReason] = useState("");
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [editing, setEditing] = useState(!defaultReadOnly);

  const projectIds = useMemo(() => contract?.projects.map((item) => item.id) ?? selectedProjectIds, [contract, selectedProjectIds]);
  useEffect(() => {
    void Promise.all([
      apiGet<ProjectListResponse>("/projects", new URLSearchParams({ group: "pool_active", page_size: "200" })),
      apiGet<ProjectListResponse>("/projects", new URLSearchParams({ group: "completed", page_size: "200" })),
    ]).then(([active, completed]) => { setActiveProjects(active.items); setCompletedProjects(completed.items); }).catch(() => { setActiveProjects([]); setCompletedProjects([]); });
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
      setContract(data); setForm(toForm(data)); setSelectedProjectIds(data.projects.map((item) => item.id)); setAllocatedAmounts(Object.fromEntries(data.projects.map((item) => [item.id, item.allocated_amount == null ? "" : String(item.allocated_amount)]))); setAcceptance({ status: data.acceptance_status === "not_accepted" ? "accepting" : data.acceptance_status, date: data.acceptance_records?.[0]?.acceptance_date || today(), result: data.acceptance_records?.[0]?.result || "", note: data.acceptance_records?.[0]?.note || "" }); setMode("detail"); setEditing(false); setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同加载失败");
    }
  }

  function toggleProject(id: number) {
    setSelectedProjectIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function projectLinks() { return selectedProjectIds.map((id) => ({ project_id: id, allocated_amount: allocatedAmounts[id] === "" || allocatedAmounts[id] == null ? null : Number(allocatedAmounts[id]) })); }

  const linkableProjects = [...activeProjects, ...completedProjects.filter((item) => !activeProjects.some((active) => active.id === item.id))];
  const hasHistoricalSelection = selectedProjectIds.some((id) => !activeProjects.some((item) => item.id === id));
  const isProjectContext = Boolean(projectId);

  async function returnToList() {
    setContract(null); setEditing(false); setMode("list"); setError("");
    if (projectId) await loadProjectContracts(projectId);
  }

  async function refresh(updated: Contract, message: string) {
    setContract(updated); setContracts((current) => current.map((item) => item.id === updated.id ? updated : item)); setForm(toForm(updated)); setSelectedProjectIds(updated.projects.map((item) => item.id)); setAllocatedAmounts(Object.fromEntries(updated.projects.map((item) => [item.id, item.allocated_amount == null ? "" : String(item.allocated_amount)]))); setAcceptance({ status: updated.acceptance_status === "not_accepted" ? "accepting" : updated.acceptance_status, date: updated.acceptance_records?.[0]?.acceptance_date || today(), result: updated.acceptance_records?.[0]?.result || "", note: updated.acceptance_records?.[0]?.note || "" }); setMode(isProjectContext ? "list" : "detail"); setEditing(false);
    await onChanged(updated.projects.map((item) => item.id));
    if (projectId) await loadProjectContracts(projectId);
    setFeedback(message); setError("");
  }

  async function create() {
    try {
      const created = await apiPost<Contract>("/contracts", { ...form, total_amount: form.total_amount || null, project_links: projectLinks(), history_correction: hasHistoricalSelection, completion_acceptance: form.status === "completed" ? { acceptance_status: acceptance.status, acceptance_date: acceptance.date, result: acceptance.result, note: acceptance.note } : undefined, operator });
      await refresh(created, "合同已创建。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同保存失败");
    }
  }

  async function save() {
    if (!contract) return;
    try {
      const updated = await apiPatch<Contract>(`/contracts/${contract.id}`, { ...form, total_amount: form.total_amount || null, completion_acceptance: form.status === "completed" && contract.status !== "completed" ? { acceptance_status: acceptance.status, acceptance_date: acceptance.date, result: acceptance.result, note: acceptance.note } : undefined, operator });
      await refresh(updated, "合同已更新。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同保存失败");
    }
  }

  async function saveProjects() {
    if (!contract) return;
    try {
      const currentIds = contract.projects.map((item) => item.id);
      const historyCorrection = selectedProjectIds.some((id) => !currentIds.includes(id) && !activeProjects.some((item) => item.id === id));
      const updated = await apiPut<Contract>(`/contracts/${contract.id}/projects`, { project_links: projectLinks(), history_correction: historyCorrection, reason: relationReason, operator });
      setRelationReason(""); await refresh(updated, "合同关联项目已更新。");
      if (!currentIds.every((id) => selectedProjectIds.includes(id))) setFeedback("合同关联项目已更新。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "合同关联更新失败");
    }
  }

  async function addProgress() {
    if (!contract || !progress.trim()) return;
    try {
      const log = await apiPost<ContractProgressLog>(`/contracts/${contract.id}/progress-logs`, { content: progress.trim(), operator });
      const updated = { ...contract, latest_progress: log, progress_logs: [...(contract.progress_logs || []), log] };
      setProgress(""); await refresh(updated, "合同进展已记录。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "合同进展保存失败"); }
  }

  async function saveLog() {
    if (!contract || !editingLog || !logValue.trim()) return;
    try {
      const log = await apiPatch<ContractProgressLog>(`/contracts/${contract.id}/progress-logs/${editingLog.id}`, { content: logValue.trim(), operator });
      const logs = (contract.progress_logs || []).map((item) => item.id === log.id ? log : item);
      setEditingLog(null); await refresh({ ...contract, latest_progress: logs.length ? logs[logs.length - 1] : null, progress_logs: logs }, "合同进展已修改。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "合同进展修改失败"); }
  }

  async function removeLog() {
    if (!contract || !deletingLog || !deleteReason.trim()) return;
    try {
      await apiDelete(`/contracts/${contract.id}/progress-logs/${deletingLog.id}`, { reason: deleteReason.trim(), operator });
      const logs = (contract.progress_logs || []).filter((item) => item.id !== deletingLog.id);
      setDeletingLog(null); setDeleteReason(""); await refresh({ ...contract, latest_progress: logs.length ? logs[logs.length - 1] : null, progress_logs: logs }, "合同进展已删除。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "合同进展删除失败"); }
  }

  async function recordAcceptance() {
    if (!contract) return;
    try {
      const record = await apiPost<ContractAcceptanceRecord>(`/contracts/${contract.id}/acceptance-records`, { acceptance_status: acceptance.status, acceptance_date: acceptance.date, result: acceptance.result, note: acceptance.note, operator });
      await refresh(await apiGet<Contract>(`/contracts/${contract.id}`), "验收结果已登记。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "验收登记失败"); }
  }

  async function openExistingContracts() {
    try {
      setAllContracts(await apiGet<Contract[]>("/contracts")); setMode("link");
    } catch (err) { setError(err instanceof ApiError ? err.message : "合同列表加载失败"); }
  }

  async function linkExisting(existing: Contract) {
    if (!projectId) return;
    try {
      const ids = [...new Set([...existing.projects.map((item) => item.id), projectId])];
      const historyCorrection = !activeProjects.some((item) => item.id === projectId);
      const updated = await apiPut<Contract>(`/contracts/${existing.id}/projects`, { project_links: ids.map((id) => ({ project_id: id, allocated_amount: existing.projects.find((item) => item.id === id)?.allocated_amount ?? null })), history_correction: historyCorrection, reason: relationReason, operator });
      setRelationReason(""); await refresh(updated, "已有合同已关联当前项目。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "合同关联失败"); }
  }

  function handleSupplier(value: string) {
    setForm((current) => ({ ...current, supplier: value }));
    void apiGet<string[]>("/contracts/supplier-suggestions", new URLSearchParams({ query: value })).then(setSupplierSuggestions).catch(() => setSupplierSuggestions([]));
  }

  const selectedNames = contract?.projects.map((item) => item.name).join("、") || linkableProjects.filter((item) => selectedProjectIds.includes(item.id)).map((item) => item.name).join("、") || (selectedProjectIds.includes(contextProject?.id ?? -1) ? contextProject?.name : "");
  const linkedProjectRows = contract?.projects ?? [...linkableProjects.filter((item) => selectedProjectIds.includes(item.id)), ...(contextProject && selectedProjectIds.includes(contextProject.id) && !linkableProjects.some((item) => item.id === contextProject.id) ? [contextProject] : [])];
  const historicalCreate = Boolean(hasHistoricalSelection && mode === "create");

  return <section className="contract-panel">
    <div className="panel-heading"><div><h3>{mode === "create" ? historicalCreate ? "补录历史合同" : "添加合同" : mode === "detail" ? "合同办理" : "合同列表"}</h3>{selectedNames ? <small>关联项目：{selectedNames}</small> : null}</div>{onClose ? <button className="mini-button" onClick={onClose}>关闭</button> : null}</div>
    {error ? <div className="notice error">{error}</div> : null}{feedback ? <div className="notice success">{feedback}</div> : null}
    {mode === "list" ? <>
      {contracts.length ? <div className="contract-list">{contracts.map((item) => <button type="button" className="contract-row" key={item.id} onClick={() => void openContract(item.id)}><strong>{item.contract_no} · {item.name}</strong><span>{item.supplier || "未填写供应商"}</span><small>{contractStatus[item.status]} · {item.planned_completion_on ? `计划 ${item.planned_completion_on}` : "未设置计划完成日期"}</small><em>{acceptanceStatus[item.acceptance_status]}{item.latest_progress ? ` · 最近：${item.latest_progress.content}` : ""}</em></button>)}</div> : <div className="empty-state">暂无合同。</div>}
      <div className="work-item-actions">{(allowCreate || defaultReadOnly && projectId) ? <button className="action-button primary" onClick={() => { setForm(emptyForm()); setSelectedProjectIds(projectId ? [projectId] : initialProjectIds); setAllocatedAmounts({}); setRelationReason(""); setMode("create"); setEditing(true); }}>{defaultReadOnly ? "补录历史合同" : "＋ 添加合同"}</button> : null}{projectId ? <button className="mini-button" onClick={() => void openExistingContracts()}>关联已有合同</button> : null}</div>
    </> : null}
    {mode === "link" ? <div className="contract-link-list"><label className="field"><span>补录/纠错原因</span><input className="input" value={relationReason} onChange={(event) => setRelationReason(event.target.value)} placeholder="关联已完成项目时必填" /></label>{allContracts.map((item) => <button type="button" className="contract-row" key={item.id} onClick={() => void linkExisting(item)}><strong>{item.contract_no} · {item.name}</strong><span>{item.supplier || "未填写供应商"}</span></button>)}<button className="mini-button" onClick={() => void returnToList()}>返回合同列表</button></div> : null}
    {mode === "detail" && contract && !editing ? <div className="contract-readonly"><div className="detail-grid"><div className="detail-field"><span>合同编号</span><strong>{contract.contract_no}</strong></div><div className="detail-field"><span>合同状态</span><strong>{contractStatus[contract.status]}</strong></div><div className="detail-field"><span>验收状态</span><strong>{acceptanceStatus[contract.acceptance_status]}</strong></div><div className="detail-field"><span>合同总金额</span><strong>{contract.total_amount == null ? "未记录" : `${contract.total_amount} 万`}</strong></div><div className="detail-field"><span>项目分摊</span><strong>{contract.allocation_complete ? `${contract.allocation_total ?? 0} 万${contract.allocation_difference ? `（差额 ${contract.allocation_difference} 万）` : "（一致）"}` : "待补录"}</strong></div><div className="detail-field"><span>计划完成日期</span><strong>{contract.planned_completion_on || "未设置"}</strong></div></div><p>{contract.note || "未填写说明"}</p><div className="progress-list">{contract.projects.map((item) => <div className="progress-entry" key={item.id}><span>{item.project_code} · {item.name} · 分摊 {item.allocated_amount == null ? "未登记" : `${item.allocated_amount} 万`}</span></div>)}</div><div className="work-item-actions"><button className="mini-button" onClick={() => setEditing(true)}>编辑合同</button><button className="mini-button" onClick={() => void returnToList()}>返回合同列表</button></div></div> : null}
    {mode === "create" || (mode === "detail" && editing) ? <>
      <div className="field-grid"><label className="field"><span>合同编号 *</span><input className="input" value={form.contract_no} onChange={(event) => setForm({ ...form, contract_no: event.target.value })} /></label><label className="field"><span>合同名称 *</span><input className="input" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label></div>
      <div className="field-grid"><label className="field"><span>供应商</span><input className="input" list="contract-suppliers" value={form.supplier} onChange={(event) => handleSupplier(event.target.value)} /></label><datalist id="contract-suppliers">{supplierSuggestions.map((item) => <option key={item} value={item} />)}</datalist><label className="field"><span>合同总金额（万元）</span><input className="input" type="number" min="0" value={form.total_amount} onChange={(event) => setForm({ ...form, total_amount: event.target.value })} /></label></div>
      <div className="field-grid"><label className="field"><span>签订日期</span><input className="input" type="date" value={form.signed_on} onChange={(event) => setForm({ ...form, signed_on: event.target.value })} /></label><label className="field"><span>计划完成日期</span><input className="input" type="date" value={form.planned_completion_on} onChange={(event) => setForm({ ...form, planned_completion_on: event.target.value })} /></label></div>
      <label className="field"><span>当前状态</span><select className="select" value={form.status} onChange={(event) => { const status = event.target.value as Contract["status"]; setForm({ ...form, status }); if (status === "completed" && form.status !== "completed") setAcceptance({ status: "accepted", date: today(), result: "验收通过", note: "" }); }}>{Object.entries(contractStatus).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      {form.status === "terminated" ? <label className="field"><span>解除原因 *</span><input className="input" value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} /></label> : null}
      {historicalCreate ? <label className="field"><span>补录历史合同原因 *</span><input className="input" value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} /></label> : null}
      <label className="field"><span>说明</span><textarea className="textarea" rows={2} value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} /></label>
      <details className="contract-project-picker" open={mode === "create"}><summary>关联项目（{selectedProjectIds.length}）</summary><strong>推进中项目</strong>{activeProjects.map((item) => <label key={item.id} className="check-row"><input type="checkbox" checked={selectedProjectIds.includes(item.id)} onChange={() => toggleProject(item.id)} />{item.project_code} · {item.name}</label>)}<strong>已完成项目（补录/纠错）</strong>{completedProjects.map((item) => <label key={item.id} className="check-row"><input type="checkbox" checked={selectedProjectIds.includes(item.id)} onChange={() => toggleProject(item.id)} />{item.project_code} · {item.name}</label>)}{linkedProjectRows.map((item) => <label className="field" key={`allocation-${item.id}`}><span>{item.project_code} · {item.name} 分摊金额（万元，可选）</span><input className="input" type="number" min="0" value={allocatedAmounts[item.id] ?? ""} onChange={(event) => setAllocatedAmounts((current) => ({ ...current, [item.id]: event.target.value }))} /></label>)}{contract ? <><label className="field"><span>调整关联原因</span><input className="input" value={relationReason} onChange={(event) => setRelationReason(event.target.value)} placeholder="新增已完成项目或移除关联时必填" /></label><button className="mini-button" onClick={() => void saveProjects()}>保存关联项目</button></> : null}</details>
      <div className="work-item-actions"><button className="mini-button" onClick={() => void returnToList()}>返回合同列表</button><button className="action-button primary" onClick={() => void (mode === "create" ? create() : save())}>{mode === "create" ? "保存合同" : "保存合同信息"}</button></div>
      {mode === "detail" && contract ? <div className="contract-follow-up"><h4>合同进展</h4><div className="progress-list">{(contract.progress_logs || []).map((log) => <div key={log.id} className="progress-entry"><span>{log.created_at.slice(0, 10)} · {log.content}</span><button className="text-button" onClick={() => { setEditingLog(log); setLogValue(log.content); }}>编辑</button><button className="text-button danger" onClick={() => { setDeletingLog(log); setDeleteReason(""); }}>删除</button></div>)}</div><textarea className="textarea" rows={2} value={progress} onChange={(event) => setProgress(event.target.value)} placeholder="新增进展" /><button className="mini-button active" onClick={() => void addProgress()}>记录进展</button>
        {editingLog ? <div className="inline-form"><input className="input" value={logValue} onChange={(event) => setLogValue(event.target.value)} /><button className="mini-button" onClick={() => setEditingLog(null)}>取消</button><button className="mini-button active" onClick={() => void saveLog()}>保存修改</button></div> : null}{deletingLog ? <div className="inline-form"><input className="input" value={deleteReason} onChange={(event) => setDeleteReason(event.target.value)} placeholder="删除原因（必填）" /><button className="mini-button" onClick={() => setDeletingLog(null)}>取消</button><button className="mini-button danger" onClick={() => void removeLog()}>确认删除</button></div> : null}
      </div> : null}
      {mode === "detail" && contract && ["performing", "completed"].includes(contract.status) ? <div className="contract-acceptance"><h4>验收记录</h4><small>当前：{acceptanceStatus[contract.acceptance_status]}</small><div className="field-grid"><label className="field"><span>验收状态</span><select className="select" value={acceptance.status} onChange={(event) => setAcceptance({ ...acceptance, status: event.target.value as ContractAcceptanceRecord["acceptance_status"] })}><option value="accepting">验收中</option><option value="needs_rectification">待整改</option><option value="accepted">验收通过</option></select></label><label className="field"><span>验收日期 *</span><input className="input" type="date" value={acceptance.date} onChange={(event) => setAcceptance({ ...acceptance, date: event.target.value })} /></label></div><label className="field"><span>验收结果{acceptance.status === "accepted" ? " *" : ""}</span><input className="input" value={acceptance.result} onChange={(event) => setAcceptance({ ...acceptance, result: event.target.value })} /></label><label className="field"><span>验收说明</span><textarea className="textarea" rows={2} value={acceptance.note} onChange={(event) => setAcceptance({ ...acceptance, note: event.target.value })} /></label><button className="mini-button active" onClick={() => void recordAcceptance()}>登记验收结果</button><div className="progress-list">{(contract.acceptance_records || []).map((item) => <div className="progress-entry" key={item.id}><span>{item.acceptance_date} · {acceptanceStatus[item.acceptance_status]}{item.result ? ` · ${item.result}` : ""}</span></div>)}</div></div> : null}
    </> : null}
  </section>;
}
