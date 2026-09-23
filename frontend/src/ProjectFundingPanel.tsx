import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost } from "./lib/api";
import { formatCurrency } from "./lib/format";
import type { FundingSource, Project } from "./types";

export default function ProjectFundingPanel({ project, onChanged }: { project: Project; onChanged: () => Promise<void> }) {
  const [sources, setSources] = useState<FundingSource[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { void apiGet<FundingSource[]>("/funding/sources").then(setSources).catch(() => setSources([])); }, []);
  async function save() {
    if (!sourceId || amount === "") { setError("请选择资金号并填写分配金额"); return; }
    try { await apiPost(`/projects/${project.id}/funding-allocations`, { funding_source_id: Number(sourceId), allocated_amount: amount, operator: "PMO办公室" }); setSourceId(""); setAmount(""); setError(""); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "资金分配未保存"); }
  }
  async function remove(id: number) {
    const reason = window.prompt("请填写移除原因"); if (!reason?.trim()) return;
    try { await apiDelete(`/projects/${project.id}/funding-allocations/${id}`, { operator: "PMO办公室", reason }); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "资金分配未移除"); }
  }
  return <section className="detail-section project-funding-panel">
    <div className="section-title"><div><p className="section-kicker">FORMAL FUNDING</p><h2>正式项目分配</h2></div><strong>{project.formal_allocation_total == null ? "暂未确定" : `${formatCurrency(project.formal_allocation_total)} 万`}</strong></div>
    {project.funding_allocations?.length ? <div className="simple-list">{project.funding_allocations.map((item) => <article key={item.id}><strong>{item.fund_code}</strong><span>{item.allocated_amount == null ? "已关联，分配金额待补录" : `${formatCurrency(item.allocated_amount)} 万`} · 有效期 {item.valid_from_year}–{item.valid_until_year}</span><button className="text-button danger" onClick={() => void remove(item.id)}>移除</button></article>)}</div> : <p className="muted-copy">暂未记录正式资金分配。</p>}
    <div className="funding-project-add"><select className="select" value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">选择资金号</option>{sources.map((source) => <option value={source.id} key={source.id}>{source.fund_code} · {source.reference_amount == null ? "金额未记录" : `${formatCurrency(source.reference_amount)} 万`}</option>)}</select><input className="input" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="分配金额（万元）" /><button className="mini-button active" onClick={() => void save()}>保存分配</button></div>
    {error ? <small className="field-error">{error}</small> : null}
  </section>;
}
