import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  Database,
  FileDown,
  FileUp,
  Layers3,
  LoaderCircle,
  RefreshCcw,
  Send,
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
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
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
  StatusHistoryItem,
  WorkflowStatus,
} from "./types";

const GROUP_ACCENTS: Record<string, string> = {
  pre_establish: "var(--accent-red)",
  pool_pending: "var(--accent-gold)",
  pool_active: "var(--accent-cyan)",
  completed: "var(--accent-green)",
  abandoned: "var(--accent-ink)",
};

function DashboardPage() {
  const [groups, setGroups] = useState<DashboardGroup[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [statuses, setStatuses] = useState<WorkflowStatus[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [activeGroup, setActiveGroup] = useState<string>("pre_establish");
  const [selectedStatus, setSelectedStatus] = useState<string>("");
  const [selectedProjectType, setSelectedProjectType] = useState<string>("");
  const [selectedDepartment, setSelectedDepartment] = useState<string>("");
  const [selectedImplementationYear, setSelectedImplementationYear] = useState<string>("");
  const [sortBy, setSortBy] = useState<string>("status_updated_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
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
    if (selectedProjectType) params.set("project_type", selectedProjectType);
    if (selectedDepartment) params.set("department", selectedDepartment);
    if (selectedImplementationYear) params.set("implementation_year", selectedImplementationYear);
    if (deferredKeyword) params.set("keyword", deferredKeyword);
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    params.set("page", "1");
    params.set("page_size", "50");
    return params;
  }, [
    activeGroup,
    selectedStatus,
    selectedProjectType,
    selectedDepartment,
    selectedImplementationYear,
    sortBy,
    sortDir,
    deferredKeyword,
  ]);

  async function loadDashboard() {
    setLoading(true);
    setError("");
    try {
      const [groupData, summaryData, statusData, departmentData, projectData] = await Promise.all([
        apiGet<DashboardGroup[]>("/dashboard/groups"),
        apiGet<DashboardSummary>("/dashboard/summary"),
        apiGet<WorkflowStatus[]>("/workflow/statuses"),
        apiGet<string[]>("/meta/departments"),
        apiGet<ProjectListResponse>("/projects", exportQuery),
      ]);
      setGroups(groupData);
      setSummary(summaryData);
      setStatuses(statusData);
      setDepartments(departmentData);
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
  }, [activeGroup, selectedStatus, selectedProjectType, selectedDepartment, selectedImplementationYear, sortBy, sortDir, deferredKeyword]);

  const selectedProjects = useMemo(
    () => projects.filter((project) => selectedIds.includes(project.id)),
    [projects, selectedIds],
  );

  const availableTargets = useMemo(() => preview?.available_targets ?? [], [preview]);
  const implementationYearOptions = useMemo(() => {
    const years = new Set<string>();
    for (const project of projects) {
      const year = project.actual_start_date?.slice(0, 4);
      if (year) years.add(year);
    }
    return Array.from(years).sort((a, b) => Number(b) - Number(a));
  }, [projects]);
  const showImplementationFilter = activeGroup === "completed" || selectedStatus === "closed";

  useEffect(() => {
    if (!showImplementationFilter && selectedImplementationYear) {
      setSelectedImplementationYear("");
    }
  }, [showImplementationFilter, selectedImplementationYear]);

  function toggleSort(nextSortBy: string) {
    if (sortBy === nextSortBy) {
      setSortDir((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortBy(nextSortBy);
    setSortDir(nextSortBy === "implementation_year" ? "desc" : "asc");
  }

  function sortLabel(field: string) {
    if (sortBy !== field) return "↕";
    return sortDir === "asc" ? "↑" : "↓";
  }

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
          <p className="eyebrow">PMO WORKSPACE</p>
          <h1>PMO 项目管理工作台</h1>
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
          <article className="hero-stat hero-stat-single">
            <span>项目库总量</span>
            <strong>{summary?.project_library_count ?? "—"}</strong>
          </article>
          <article className="hero-stat hero-stat-pair">
            <div>
              <span>项目库预算</span>
              <strong>{formatCurrency(summary?.project_library_total_budget)} 万</strong>
            </div>
            <div>
              <span>审核预算总计</span>
              <strong>{formatCurrency(summary?.reviewed_total_approved_budget)} 万</strong>
            </div>
          </article>
          <article className="hero-stat hero-stat-pair">
            <div>
              <span>审核中项目</span>
              <strong>{summary?.review_in_progress_count ?? "—"}</strong>
            </div>
            <div>
              <span>已审核项目</span>
              <strong>{summary?.reviewed_count ?? "—"}</strong>
            </div>
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
                <div className="group-main">
                  <p>{group.label}</p>
                  <strong>{group.count}</strong>
                </div>
                <div className="group-budget">
                  <span>预算 {formatCurrency(group.total_budget)} 万</span>
                  {group.key !== "pre_establish" ? (
                    <span>审核 {formatCurrency(group.total_approved_budget)} 万</span>
                  ) : null}
                  {group.key === "completed" ? (
                    <span>合同 {formatCurrency(group.total_contract_amount)} 万</span>
                  ) : null}
                </div>
                <ArrowUpRight size={18} />
              </button>
            ))}
          </section>

          <section className="board">
            <div className="board-heading">
              <div>
                <p className="section-kicker">PROJECTS</p>
                <h2>项目列表</h2>
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
                  value={selectedProjectType}
                  onChange={(event) => setSelectedProjectType(event.target.value)}
                >
                  <option value="">全部类型</option>
                  <option value="teaching_software">教学软件</option>
                  <option value="practical_teaching_site">实践教学场所</option>
                </select>
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
                <select
                  className="select"
                  value={selectedDepartment}
                  onChange={(event) => setSelectedDepartment(event.target.value)}
                >
                  <option value="">全部部门</option>
                  {departments.map((department) => (
                    <option key={department} value={department}>
                      {department}
                    </option>
                  ))}
                </select>
                {showImplementationFilter ? (
                  <select
                    className="select"
                    value={selectedImplementationYear}
                    onChange={(event) => setSelectedImplementationYear(event.target.value)}
                  >
                    <option value="">全部实施年份</option>
                    {implementationYearOptions.map((year) => (
                      <option key={year} value={year}>
                        {year}
                      </option>
                    ))}
                  </select>
                ) : null}
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
                      <th>
                        <button className="sort-button" onClick={() => toggleSort("project_type")}>
                          类型 {sortLabel("project_type")}
                        </button>
                      </th>
                      <th>
                        <button className="sort-button" onClick={() => toggleSort("current_status")}>
                          状态 {sortLabel("current_status")}
                        </button>
                      </th>
                      <th>
                        <button className="sort-button" onClick={() => toggleSort("department")}>
                          部门 / 负责人 {sortLabel("department")}
                        </button>
                      </th>
                      <th>预算</th>
                      <th>
                        <button className="sort-button" onClick={() => toggleSort("implementation_year")}>
                          实施年份 {sortLabel("implementation_year")}
                        </button>
                      </th>
                      <th>
                        <button className="sort-button" onClick={() => toggleSort("status_updated_at")}>
                          状态更新时间 {sortLabel("status_updated_at")}
                        </button>
                      </th>
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
                              <Link className="project-link" to={`/projects/${project.id}`}>
                                {project.name}
                              </Link>
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
                              <small>合同 {formatCurrency(project.contract_amount)} 万</small>
                            </div>
                          </td>
                          <td>{project.actual_start_date?.slice(0, 4) || "未记录"}</td>
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
                <p className="section-kicker">IMPORT</p>
                <h3>导入预览</h3>
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
            <p className="section-kicker">BATCH</p>
            <h3>批量流转</h3>
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
            <p className="section-kicker">PREVIEW</p>
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

function DetailField({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="detail-field">
      <span>{label}</span>
      <strong>{value || "未记录"}</strong>
    </div>
  );
}

function ProjectDetailPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [history, setHistory] = useState<StatusHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    void Promise.all([
      apiGet<Project>(`/projects/${projectId}`),
      apiGet<StatusHistoryItem[]>(`/projects/${projectId}/history`),
    ])
      .then(([projectData, historyData]) => {
        setProject(projectData);
        setHistory(historyData);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "项目详情加载失败");
      })
      .finally(() => setLoading(false));
  }, [projectId]);

  return (
    <div className="shell">
      <div className="backdrop-grid" />
      <header className="detail-hero">
        <button className="mini-button" onClick={() => navigate(-1)}>
          <ArrowLeft size={16} />
          返回
        </button>
        <div>
          <p className="eyebrow">PROJECT DETAIL</p>
          <h1>{project?.name ?? "项目详情"}</h1>
          <div className="detail-tags">
            <span>{project?.project_code ?? "加载中"}</span>
            {project ? <span className={`status-chip status-${project.current_status}`}>{statusLabel(project.current_status)}</span> : null}
            <span>{projectTypeLabel(project?.project_type ?? null)}</span>
          </div>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}

      {loading ? (
        <div className="detail-loading">
          <LoaderCircle className="spin" size={22} />
          正在载入项目详情
        </div>
      ) : project ? (
        <main className="detail-layout">
          <section className="detail-main">
            <section className="detail-section">
              <div className="section-title">
                <p className="section-kicker">BASIC</p>
                <h2>基本信息</h2>
              </div>
              <div className="detail-grid">
                <DetailField label="申报部门" value={project.department} />
                <DetailField label="项目负责人" value={project.project_manager} />
                <DetailField label="发起人" value={project.sponsor} />
                <DetailField label="项目分类" value={project.category} />
                <DetailField label="实际开始日期" value={project.actual_start_date} />
                <DetailField label="实际结束日期" value={project.actual_end_date} />
              </div>
              <div className="detail-note">
                <span>项目描述</span>
                <p>{project.description || "未记录"}</p>
              </div>
              <div className="detail-note">
                <span>特殊说明</span>
                <p>{project.special_note || "未记录"}</p>
              </div>
            </section>

            <section className="detail-section">
              <div className="section-title">
                <p className="section-kicker">HISTORY</p>
                <h2>状态历史</h2>
              </div>
              {history.length ? (
                <div className="history-list">
                  {history.map((item) => (
                    <article className="history-item" key={item.id}>
                      <div className="history-date">{formatDateTime(item.transition_date)}</div>
                      <div>
                        <strong>
                          {item.from_status_name || "初始"} → {item.to_status_name || statusLabel(item.to_status)}
                        </strong>
                        <p>{item.action}</p>
                        <div className="history-meta">
                          <span>操作人：{item.operator}</span>
                          <span>审批人：{item.approver || "无"}</span>
                          <span>交付物：{item.deliverable || "未记录"}</span>
                        </div>
                        {item.comment ? <p className="history-comment">{item.comment}</p> : null}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty-state">暂无状态历史。</div>
              )}
            </section>
          </section>

          <aside className="detail-side">
            <article className="hero-stat">
              <span>初始预算</span>
              <strong>{formatCurrency(project.budget)} 万</strong>
            </article>
            <article className="hero-stat">
              <span>审核后预算</span>
              <strong>{formatCurrency(project.approved_budget)} 万</strong>
            </article>
            <article className="hero-stat">
              <span>合同金额</span>
              <strong>{formatCurrency(project.contract_amount)} 万</strong>
            </article>
            <article className="hero-stat">
              <span>创建时间</span>
              <strong>{formatDateTime(project.created_at)}</strong>
            </article>
            <article className="hero-stat">
              <span>状态更新时间</span>
              <strong>{formatDateTime(project.status_updated_at)}</strong>
            </article>
          </aside>
        </main>
      ) : null}
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
    </Routes>
  );
}

export default App;
