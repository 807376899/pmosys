import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Database,
  FileDown,
  FileUp,
  Layers3,
  LoaderCircle,
  RefreshCcw,
  Send,
  Sparkles,
} from "lucide-react";
import {
  type CSSProperties,
  type FormEvent,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ApiError, apiGet, apiPost, apiPostForm, buildExportUrl } from "./lib/api";
import { formatCurrency, formatDateTime, projectTypeLabel, statusLabel } from "./lib/format";
import type {
  BatchExecuteResponse,
  BatchPreviewResponse,
  DashboardGroup,
  DashboardSummary,
  ImportCommitResponse,
  ImportPreviewResponse,
  Project,
  ProjectListResponse,
  WorkflowStatus,
} from "./types";

const GROUP_ACCENTS: Record<string, string> = {
  pre_establish: "var(--accent-red)",
  pool_pending: "var(--accent-gold)",
  pool_active: "var(--accent-cyan)",
  completed: "var(--accent-green)",
  abandoned: "var(--accent-ink)",
};

function App() {
  const [groups, setGroups] = useState<DashboardGroup[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [statuses, setStatuses] = useState<WorkflowStatus[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [activeGroup, setActiveGroup] = useState<string>("pre_establish");
  const [selectedStatus, setSelectedStatus] = useState<string>("");
  const [keyword, setKeyword] = useState("");
  const deferredKeyword = useDeferredValue(keyword);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [preview, setPreview] = useState<BatchPreviewResponse | null>(null);
  const [selectedTarget, setSelectedTarget] = useState<string>("");
  const [operator, setOperator] = useState("PMO办公室");
  const [operatorRole, setOperatorRole] = useState("PMO");
  const [approver, setApprover] = useState("");
  const [comment, setComment] = useState("");
  const [deliverable, setDeliverable] = useState("");
  const [approvedBudgetEnabled, setApprovedBudgetEnabled] = useState(false);
  const [approvedBudget, setApprovedBudget] = useState("");
  const [forceMode, setForceMode] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportPreviewResponse | null>(null);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);

  const exportQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (activeGroup) params.set("group", activeGroup);
    if (selectedStatus) params.set("status", selectedStatus);
    if (deferredKeyword) params.set("keyword", deferredKeyword);
    params.set("page", "1");
    params.set("page_size", "50");
    return params;
  }, [activeGroup, selectedStatus, deferredKeyword]);

  async function loadDashboard() {
    setLoading(true);
    setError("");
    try {
      const [groupData, summaryData, statusData, projectData] = await Promise.all([
        apiGet<DashboardGroup[]>("/dashboard/groups"),
        apiGet<DashboardSummary>("/dashboard/summary"),
        apiGet<WorkflowStatus[]>("/workflow/statuses"),
        apiGet<ProjectListResponse>("/projects", exportQuery),
      ]);
      setGroups(groupData);
      setSummary(summaryData);
      setStatuses(statusData);
      setProjects(projectData.items);
      setTotal(projectData.total);
      setSelectedIds((current) => current.filter((id) => projectData.items.some((item) => item.id === id)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "工作台加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, [exportQuery]);

  useEffect(() => {
    if (!selectedIds.length || !selectedTarget) {
      setPreview(null);
      return;
    }

    const payload = {
      project_ids: selectedIds,
      to_status: selectedTarget,
      operator_role: operatorRole,
      force: forceMode,
    };

    void apiPost<BatchPreviewResponse>("/projects/batch-transition/preview", payload)
      .then((data) => {
        setPreview(data);
        setApprovedBudgetEnabled(data.approved_budget_allowed);
      })
      .catch((err) => {
        setPreview(null);
        setApprovedBudgetEnabled(false);
        setError(err instanceof ApiError ? err.message : "批量预检失败");
      });
  }, [selectedIds, selectedTarget, operatorRole, forceMode]);

  useEffect(() => {
    startTransition(() => {
      setSelectedTarget("");
      setPreview(null);
      setApprovedBudgetEnabled(false);
    });
  }, [activeGroup, selectedStatus, deferredKeyword]);

  const selectedProjects = useMemo(
    () => projects.filter((project) => selectedIds.includes(project.id)),
    [projects, selectedIds],
  );

  const availableTargets = useMemo(() => preview?.available_targets ?? [], [preview]);

  function toggleSelection(projectId: number) {
    setSelectedIds((current) =>
      current.includes(projectId)
        ? current.filter((id) => id !== projectId)
        : [...current, projectId],
    );
  }

  function toggleAllVisible() {
    if (selectedProjects.length === projects.length && projects.length > 0) {
      setSelectedIds([]);
      return;
    }
    setSelectedIds(projects.map((project) => project.id));
  }

  async function executeBatch() {
    setExecuting(true);
    setFeedback("");
    setError("");
    try {
      const result = await apiPost<BatchExecuteResponse>("/projects/batch-transition", {
        project_ids: selectedIds,
        to_status: selectedTarget,
        operator,
        operator_role: operatorRole,
        approver: approver || null,
        comment,
        deliverable,
        force: forceMode,
        approved_budget: approvedBudgetEnabled && approvedBudget ? Number(approvedBudget) : null,
      });
      setFeedback(
        result.failed
          ? `本次处理 ${result.total} 个项目，成功 ${result.success} 个，失败 ${result.failed} 个。`
          : `本次处理 ${result.total} 个项目，全部成功。`,
      );
      setSelectedIds([]);
      setComment("");
      setDeliverable("");
      setApprover("");
      setApprovedBudget("");
      await loadDashboard();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "批量执行失败");
    } finally {
      setExecuting(false);
    }
  }

  async function handleImportSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fileInput = form.elements.namedItem("import-file") as HTMLInputElement | null;
    const file = fileInput?.files?.[0];
    if (!file) {
      setError("请先选择导入文件。");
      return;
    }
    setError("");
    setFeedback("");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await apiPostForm<ImportPreviewResponse>("/imports/projects/preview", formData);
      setImportPreview(response);
      setFeedback(`导入预览完成：有效 ${response.valid_rows} 行，异常 ${response.invalid_rows} 行。`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "导入预览失败");
    }
  }

  async function commitImport() {
    if (!importPreview?.records.length) return;
    try {
      const response = await apiPost<ImportCommitResponse>("/imports/projects/commit", {
        records: importPreview.records,
        operator,
      });
      setFeedback(`导入完成：成功 ${response.success} 行，失败 ${response.failed} 行。`);
      setImportPreview(null);
      await loadDashboard();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "导入提交失败");
    }
  }

  return (
    <div className="shell">
      <div className="backdrop-grid" />
      <header className="hero">
        <div className="hero-copy">
          <p className="eyebrow">
            <Sparkles size={16} />
            PMO Mission Control
          </p>
          <h1>把批量流转放到舞台中央，而不是藏在表格刷新里。</h1>
          <p className="hero-text">
            这是一个为 PMO、项目负责人和领导共同使用而设计的编辑部式工作台。
            左边看局势，右边推流程，中间永远只保留当前最重要的批量决策。
          </p>
          <div className="hero-actions">
            <a className="action-button primary" href={buildExportUrl(exportQuery)} target="_blank" rel="noreferrer">
              <FileDown size={16} />
              导出当前视图
            </a>
            <button className="action-button ghost" onClick={() => void loadDashboard()}>
              <RefreshCcw size={16} />
              刷新数据
            </button>
          </div>
        </div>
        <div className="hero-stats">
          <article className="hero-stat">
            <span>项目总量</span>
            <strong>{summary?.total_projects ?? "—"}</strong>
          </article>
          <article className="hero-stat">
            <span>初始预算</span>
            <strong>{formatCurrency(summary?.total_budget)} 万</strong>
          </article>
          <article className="hero-stat">
            <span>审核预算</span>
            <strong>{formatCurrency(summary?.total_approved_budget)} 万</strong>
          </article>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}
      {feedback ? <div className="notice success">{feedback}</div> : null}

      <main className="workspace">
        <section className="main-stage">
          <section className="group-band">
            {groups.map((group, index) => (
              <button
                key={group.key}
                className={`group-card ${activeGroup === group.key ? "active" : ""}`}
                style={{ "--group-accent": GROUP_ACCENTS[group.key] } as CSSProperties}
                onClick={() => setActiveGroup(group.key)}
              >
                <span className="group-index">0{index + 1}</span>
                <div>
                  <p>{group.label}</p>
                  <strong>{group.count}</strong>
                </div>
                <ArrowUpRight size={18} />
              </button>
            ))}
          </section>

          <section className="board">
            <div className="board-heading">
              <div>
                <p className="section-kicker">项目矩阵</p>
                <h2>让统筹视角、检索和批量勾选在同一块画布里协同。</h2>
              </div>
              <div className="filter-row">
                <input
                  className="input"
                  placeholder="搜索项目名称 / 编号 / 发起人"
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                />
                <select
                  className="select"
                  value={selectedStatus}
                  onChange={(event) => setSelectedStatus(event.target.value)}
                >
                  <option value="">全部状态</option>
                  {statuses.map((status) => (
                    <option key={status.status_code} value={status.status_code}>
                      {status.status_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="table-meta">
              <span>当前共 {total} 条，视图内 {projects.length} 条</span>
              <button className="mini-button" onClick={toggleAllVisible}>
                {selectedProjects.length === projects.length && projects.length ? "取消全选" : "全选当前结果"}
              </button>
            </div>

            <div className="project-table-wrap">
              {loading ? (
                <div className="loading-panel">
                  <LoaderCircle className="spin" size={22} />
                  正在载入工作台
                </div>
              ) : (
                <table className="project-table">
                  <thead>
                    <tr>
                      <th>选中</th>
                      <th>项目</th>
                      <th>类型</th>
                      <th>状态</th>
                      <th>部门 / 负责人</th>
                      <th>预算</th>
                      <th>状态更新时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {projects.map((project) => {
                      const selected = selectedIds.includes(project.id);
                      return (
                        <tr key={project.id} className={selected ? "selected" : ""}>
                          <td>
                            <label className="check-pill">
                              <input
                                type="checkbox"
                                checked={selected}
                                onChange={() => toggleSelection(project.id)}
                              />
                              <span />
                            </label>
                          </td>
                          <td>
                            <div className="project-cell">
                              <strong>{project.name}</strong>
                              <span>{project.project_code}</span>
                              <small>{project.category || "未分类"}</small>
                            </div>
                          </td>
                          <td>{projectTypeLabel(project.project_type)}</td>
                          <td>
                            <span className={`status-chip status-${project.current_status}`}>
                              {statusLabel(project.current_status)}
                            </span>
                          </td>
                          <td>
                            <div className="stacked">
                              <span>{project.department || "未录入部门"}</span>
                              <small>{project.project_manager || "未录入负责人"}</small>
                            </div>
                          </td>
                          <td>
                            <div className="stacked">
                              <span>{formatCurrency(project.budget)} 万</span>
                              <small>审后 {formatCurrency(project.approved_budget)} 万</small>
                            </div>
                          </td>
                          <td>{formatDateTime(project.status_updated_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="import-lab">
            <div className="import-heading">
              <div>
                <p className="section-kicker">导入试验台</p>
                <h3>先看预览，再写入数据库。</h3>
              </div>
              <a className="mini-link" href="/api/v1/imports/projects/template" target="_blank" rel="noreferrer">
                下载模板
              </a>
            </div>
            <form className="import-form" onSubmit={handleImportSubmit}>
              <label className="upload-box">
                <FileUp size={20} />
                <span>上传 CSV / XLSX 做导入预览</span>
                <input id="import-file" name="import-file" type="file" accept=".csv,.xlsx,.xls" />
              </label>
              <button className="action-button primary compact" type="submit">
                <Database size={16} />
                生成导入预览
              </button>
            </form>
            {importPreview ? (
              <div className="preview-grid">
                <article className="preview-card">
                  <strong>{importPreview.valid_rows}</strong>
                  <span>可导入行</span>
                </article>
                <article className="preview-card">
                  <strong>{importPreview.invalid_rows}</strong>
                  <span>异常行</span>
                </article>
                <article className="preview-card">
                  <strong>{importPreview.total_rows}</strong>
                  <span>总行数</span>
                </article>
                <button className="action-button ghost compact" onClick={() => void commitImport()}>
                  <Send size={16} />
                  确认写入
                </button>
              </div>
            ) : null}
            {importPreview?.errors?.length ? (
              <div className="error-list">
                {importPreview.errors.map((item) => (
                  <div key={`${item.row_number}-${item.code}`} className="error-item">
                    <AlertTriangle size={16} />
                    第 {item.row_number} 行：{item.message}
                  </div>
                ))}
              </div>
            ) : null}
          </section>
        </section>

        <aside className="control-rail">
          <div className="rail-card">
            <p className="section-kicker">批量流转</p>
            <h3>让选中、预检、审批和执行始终在同一条轨道上完成。</h3>
            <div className="selection-summary">
              <span>当前勾选</span>
              <strong>{selectedIds.length}</strong>
            </div>

            <label className="field">
              <span>操作人</span>
              <input className="input" value={operator} onChange={(event) => setOperator(event.target.value)} />
            </label>
            <label className="field">
              <span>操作角色</span>
              <select className="select" value={operatorRole} onChange={(event) => setOperatorRole(event.target.value)}>
                <option value="PMO">PMO</option>
                <option value="USER">普通用户</option>
              </select>
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={forceMode}
                onChange={(event) => setForceMode(event.target.checked)}
              />
              <span>启用 PMO 特批强制变更</span>
            </label>

            <label className="field">
              <span>目标状态</span>
              <select
                className="select"
                value={selectedTarget}
                onChange={(event) => setSelectedTarget(event.target.value)}
              >
                <option value="">先选择目标状态</option>
                {statuses.map((status) => (
                  <option key={status.status_code} value={status.status_code}>
                    {status.status_name}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>审批人</span>
              <input className="input" value={approver} onChange={(event) => setApprover(event.target.value)} />
            </label>
            <label className="field">
              <span>交付物</span>
              <input className="input" value={deliverable} onChange={(event) => setDeliverable(event.target.value)} />
            </label>
            <label className="field">
              <span>变更理由</span>
              <textarea
                className="textarea"
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                rows={4}
              />
            </label>
            <label className={`field ${approvedBudgetEnabled ? "" : "disabled"}`}>
              <span>审核后预算</span>
              <input
                className="input"
                type="number"
                disabled={!approvedBudgetEnabled}
                placeholder={approvedBudgetEnabled ? "仅送审相关流转可填写" : "当前目标状态不可填"}
                value={approvedBudget}
                onChange={(event) => setApprovedBudget(event.target.value)}
              />
            </label>

            <button
              className="action-button primary full"
              disabled={!selectedIds.length || !selectedTarget || !comment || executing}
              onClick={() => void executeBatch()}
            >
              {executing ? <LoaderCircle className="spin" size={16} /> : <CheckCircle2 size={16} />}
              执行批量流转
            </button>
          </div>

          <div className="rail-card preview-card-large">
            <p className="section-kicker">预检结果</p>
            {preview ? (
              <>
                <div className="preview-summary">
                  <div>
                    <span>目标状态</span>
                    <strong>{preview.requested_target?.status_name ?? "未命中共同状态"}</strong>
                  </div>
                  <div>
                    <span>审批要求</span>
                    <strong>{preview.requires_approval ? "需要审批" : "可直接推进"}</strong>
                  </div>
                  <div>
                    <span>预算逻辑</span>
                    <strong>{preview.approved_budget_allowed ? "允许改审后预算" : "本次不可改预算"}</strong>
                  </div>
                </div>

                {availableTargets.length ? (
                  <div className="target-cloud">
                    {availableTargets.map((target) => (
                      <span
                        key={target.to_status}
                        className={`target-pill ${selectedTarget === target.to_status ? "active" : ""}`}
                      >
                        {target.status_name}
                      </span>
                    ))}
                  </div>
                ) : null}

                {preview.conflicts.length ? (
                  <div className="conflict-list">
                    {preview.conflicts.map((conflict) => (
                      <div key={`${conflict.project_id}-${conflict.code}`} className="conflict-item">
                        <AlertTriangle size={16} />
                        <div>
                          <strong>{conflict.project_code}</strong>
                          <span>{conflict.message}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <CheckCircle2 size={18} />
                    本次勾选没有发现预检冲突。
                  </div>
                )}
              </>
            ) : (
              <div className="empty-state">
                <Layers3 size={18} />
                勾选项目并选择目标状态后，这里会显示共同合法流转、审批要求和冲突项。
              </div>
            )}
          </div>
        </aside>
      </main>
    </div>
  );
}

export default App;
