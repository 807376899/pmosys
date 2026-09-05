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
  PackagePlus,
  Plus,
  RefreshCcw,
  Send,
} from "lucide-react";
import {
  type CSSProperties,
  type FormEvent,
  type MouseEvent,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPostForm, buildExportUrl } from "./lib/api";
import { formatCurrency, formatDate, formatDateTime, projectTypeLabel, statusLabel } from "./lib/format";
import type {
  BatchExecuteResponse,
  BatchPreviewResponse,
  AuditEvent,
  DashboardGroup,
  DashboardSummary,
  ImportCommitResponse,
  ImportPreviewResponse,
  Project,
  ProjectListResponse,
  StatusHistoryItem,
  WorkItem,
  WorkItemDraft,
  WorkItemProgressLog,
  ManagementTimelineEvent,
  WorkItemTemplate,
  WorkPackage,
  ExternalConstraintTemplate,
  ProjectCategory,
  DepartmentSetting,
  ProjectExternalConstraint,
} from "./types";

const GROUP_ACCENTS: Record<string, string> = {
  pre_establish: "var(--accent-red)",
  pool_pending: "var(--accent-gold)",
  pool_active: "var(--accent-cyan)",
  completed: "var(--accent-green)",
  abandoned: "var(--accent-ink)",
};

const emptyDraft = (): WorkItemDraft => ({
  name: "", content: "", status: "not_started", execution_mode: "tracking", assignee: "", planned_date: "", priority: "normal",
  track_as_key_node: false, note: "", completion_effects: {}, flow_group: "independent", sequence_rank: 1000,
});

const workStatusLabel = (status: string) => ({
  not_started: "未开始", in_progress: "进行中", waiting_external: "等待外部",
  completed: "已完成", paused: "暂停", not_applicable: "不适用",
}[status] ?? status);

function ProgressSummary({ project, onSelect }: { project: Project; onSelect?: (itemId: number) => void }) {
  const items = project.work_item_summary ?? [];
  if (!items.length) return <span className="muted-copy">暂无进行中事项</span>;
  const moreCount = Math.max((project.work_item_count ?? items.length) - items.length, 0);
  return <div className="progress-summary">{items.map((item) => <button type="button" key={item.id} onClick={() => onSelect?.(item.id)}><strong>{item.name}</strong><small>{workStatusLabel(item.status)}</small></button>)}{moreCount ? <em>+{moreCount}</em> : null}</div>;
}

function StageItemCell({ project, column }: { project: Project; column: string }) {
  const aliases: Record<string, string[]> = {
    "学院流程": ["学院流程", "学院内部流程"],
    "专家评审": ["专家评审", "小组评审", "校外专家评审"],
    "委员会": ["委员会", "实验室建设与管理委员会"],
    "会议": ["会议", "校长办公会", "党委会"],
  };
  const status = (aliases[column] ?? [column])
    .map((name) => project.work_item_states?.[name])
    .find(Boolean);
  return status ? <span className="stage-item-cell">{workStatusLabel(status)}</span> : <span className="muted-copy">—</span>;
}

function KeyNode({ project }: { project: Project }) {
  const node = project.next_key_node;
  if (!node) return <span className="muted-copy">未设置</span>;
  return <div className="key-node"><strong>{node.name}</strong><small>{node.planned_date || "未设置日期"} · {workStatusLabel(node.status)}</small></div>;
}

function ExternalCondition({ project }: { project: Project }) {
  const value = project.external_constraints_cleared;
  const label = value === "true" ? "外部条件已具备" : value === "false" ? "外部约束办理中" : "外部范围待确认";
  return <small className={value === "true" ? "external-ready" : "external-pending"}>{label}</small>;
}

type ManagedTemplate = { id: number; name: string; archived_at?: string | null };
function TemplateManager({ items, kind, onArchive, onRefresh, operator, onError }: {
  items: ManagedTemplate[];
  kind: "work-item" | "work-package" | "external-constraint";
  onArchive: (kind: "work-item" | "work-package" | "external-constraint", id: number, name: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  operator: string;
  onError: (message: string) => void;
}) {
  const [showArchived, setShowArchived] = useState(false);
  const [deleting, setDeleting] = useState<ManagedTemplate | null>(null);
  const [editing, setEditing] = useState<ManagedTemplate | null>(null);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const visible = items.filter((item) => showArchived || !item.archived_at);
  const path = (item: ManagedTemplate, action: "restore" | "delete") => kind === "work-package"
    ? `/work-packages/${item.id}${action === "restore" ? "/restore" : ""}`
    : `/${kind}-templates/${item.id}${action === "restore" ? "/restore" : ""}`;
  async function restore(item: ManagedTemplate) {
    try { await apiPost(path(item, "restore"), { operator }); await onRefresh(); }
    catch (err) { onError(err instanceof ApiError ? err.message : "恢复模板失败，列表未变更。"); }
  }
  async function remove() {
    if (!deleting || !reason.trim()) return;
    try { await apiDelete(path(deleting, "delete"), { operator, reason: reason.trim() }); setDeleting(null); setReason(""); await onRefresh(); }
    catch (err) { onError(err instanceof ApiError ? err.message : "模板未删除；如已有引用，请改为归档。"); }
  }
  async function saveName() {
    if (!editing || !name.trim()) return;
    try { await apiPatch(path(editing, "restore").replace("/restore", ""), { operator, name: name.trim() }); setEditing(null); setName(""); await onRefresh(); }
    catch (err) { onError(err instanceof ApiError ? err.message : "模板未更新，页面保持原状。"); }
  }
  return <div className="template-manager" data-interactive>
    <div className="template-manager-heading"><strong>模板治理</strong><button className="text-button" onClick={() => setShowArchived((value) => !value)}>{showArchived ? "仅看启用" : "查看归档"}</button></div>
    {visible.map((item) => <div key={item.id}><span>{item.name}{item.archived_at ? " · 已归档" : ""}</span><aside>{item.archived_at ? <><button className="text-button" onClick={() => void restore(item)}>恢复</button><button className="text-button danger" onClick={() => setDeleting(item)}>永久删除</button></> : <><button className="text-button" onClick={() => { setEditing(item); setName(item.name); }}>编辑</button><button className="text-button" onClick={() => void onArchive(kind, item.id, item.name)}>归档</button></>}</aside></div>)}
    {!visible.length ? <small>当前没有符合条件的模板。</small> : null}
    {deleting ? <section className="template-confirm"><strong>永久删除“{deleting.name}”</strong><p>仅从未被引用的模板可永久删除；已有历史引用将被服务器拒绝。</p><textarea className="textarea" rows={2} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="删除原因（必填）" /><div><button className="mini-button" onClick={() => setDeleting(null)}>取消</button><button className="mini-button danger" disabled={!reason.trim()} onClick={() => void remove()}>确认永久删除</button></div></section> : null}
    {editing ? <section className="template-confirm"><strong>编辑常用模板</strong><input className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="模板名称" /><p>推荐阶段、排序和展示投影沿用原配置；重命名仅影响后续新建，不改写历史实例。</p><div><button className="mini-button" onClick={() => setEditing(null)}>取消</button><button className="mini-button" disabled={!name.trim()} onClick={() => void saveName()}>保存</button></div></section> : null}
  </div>;
}

function DashboardPage() {
  const [groups, setGroups] = useState<DashboardGroup[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [departments, setDepartments] = useState<string[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [activeGroup, setActiveGroup] = useState<string>("pre_establish");
  const [selectedProjectType, setSelectedProjectType] = useState<string>("");
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [selectedDepartment, setSelectedDepartment] = useState<string>("");
  const [selectedExternalConditions, setSelectedExternalConditions] = useState<"" | "ready" | "ongoing">("");
  const [selectedAdvancementStatus, setSelectedAdvancementStatus] = useState<string>("");
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
  const [advancementYear, setAdvancementYear] = useState(String(new Date().getFullYear()));
  const [earlyApprovalBasis, setEarlyApprovalBasis] = useState("");
  const [deliverable, setDeliverable] = useState("");
  const [approvedBudgetEnabled, setApprovedBudgetEnabled] = useState(false);
  const [approvedBudget, setApprovedBudget] = useState("");
  const [forceMode, setForceMode] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportPreviewResponse | null>(null);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [operationMode, setOperationMode] = useState<"advance" | "stage" | "items" | "package" | "constraints" | "config" | "batch">("advance");
  const [railExpanded, setRailExpanded] = useState(false);
  const [quickItem, setQuickItem] = useState<WorkItem | null>(null);
  const [quickProjectId, setQuickProjectId] = useState<number | null>(null);
  const [quickProject, setQuickProject] = useState<Project | null>(null);
  const [quickLogs, setQuickLogs] = useState<WorkItemProgressLog[]>([]);
  const [showAllQuickLogs, setShowAllQuickLogs] = useState(false);
  const [quickProgress, setQuickProgress] = useState("");
  const [quickCompletionResult, setQuickCompletionResult] = useState("");
  const [quickCreateMilestone, setQuickCreateMilestone] = useState(false);
  const [draftItems, setDraftItems] = useState<WorkItemDraft[]>([emptyDraft()]);
  const [saveAsCommon, setSaveAsCommon] = useState(false);
  const [packageName, setPackageName] = useState("");
  const [templates, setTemplates] = useState<WorkItemTemplate[]>([]);
  const [packages, setPackages] = useState<WorkPackage[]>([]);
  const [constraintTemplates, setConstraintTemplates] = useState<ExternalConstraintTemplate[]>([]);
  const [constraintTemplateId, setConstraintTemplateId] = useState<number | null>(null);
  const [constraintName, setConstraintName] = useState("");
  const [constraintBlocking, setConstraintBlocking] = useState(true);
  const [constraintStatus, setConstraintStatus] = useState("not_started");
  const [saveConstraintAsCommon, setSaveConstraintAsCommon] = useState(false);
  const [categories, setCategories] = useState<ProjectCategory[]>([]);
  const [departmentSettings, setDepartmentSettings] = useState<DepartmentSetting[]>([]);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategoryOrder, setNewCategoryOrder] = useState("");
  const [templateManager, setTemplateManager] = useState<"items" | "packages" | "constraints" | null>(null);
  const [selectedPackageId, setSelectedPackageId] = useState<number | null>(null);
  const [templateKeyword, setTemplateKeyword] = useState("");
  const [dialog, setDialog] = useState<null | { kind: "edit-log" | "delete-log" | "archive-template"; title: string; value: string; target?: WorkItemProgressLog; template?: { kind: "work-item" | "work-package" | "external-constraint"; id: number; name: string } }>(null);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [newProject, setNewProject] = useState({ name: "", department: "", project_manager: "", project_type: "teaching_software", budget: "", description: "" });
  const [tableView, setTableView] = useState<"overview" | "stage">("overview");
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const [columnSearch, setColumnSearch] = useState("");
  const [visibleColumnsByStage, setVisibleColumnsByStage] = useState<Record<string, string[]>>(() => {
    try { return JSON.parse(localStorage.getItem("pmo-stage-columns-v2") || "{}") as Record<string, string[]>; } catch { return {}; }
  });

  const exportQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (activeGroup) params.set("group", activeGroup);
    if (selectedProjectType) params.set("project_type", selectedProjectType);
    if (selectedCategory) params.set("category", selectedCategory);
    if (selectedDepartment) params.set("department", selectedDepartment);
    if (selectedExternalConditions) params.set("external_conditions", selectedExternalConditions);
    if (selectedAdvancementStatus) params.set("advancement_status", selectedAdvancementStatus);
    if (selectedImplementationYear) params.set("implementation_year", selectedImplementationYear);
    if (deferredKeyword) params.set("keyword", deferredKeyword);
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    params.set("page", "1");
    params.set("page_size", "50");
    return params;
  }, [
    activeGroup,
    selectedProjectType,
    selectedCategory,
    selectedDepartment,
    selectedExternalConditions,
    selectedAdvancementStatus,
    selectedImplementationYear,
    sortBy,
    sortDir,
    deferredKeyword,
  ]);

  async function loadDashboard() {
    setLoading(true);
    setError("");
    try {
      const [groupData, summaryData, departmentData, projectData, templateData, packageData, constraintTemplateData, categoryData, departmentSettingData] = await Promise.all([
        apiGet<DashboardGroup[]>("/dashboard/groups"),
        apiGet<DashboardSummary>("/dashboard/summary"),
        apiGet<string[]>("/meta/departments"),
        apiGet<ProjectListResponse>("/projects", exportQuery),
        apiGet<WorkItemTemplate[]>("/work-item-templates?include_archived=true"),
        apiGet<WorkPackage[]>("/work-packages?include_archived=true"),
        apiGet<ExternalConstraintTemplate[]>("/external-constraint-templates?include_archived=true"),
        apiGet<ProjectCategory[]>("/meta/project-categories"),
        apiGet<DepartmentSetting[]>("/meta/department-settings"),
      ]);
      setGroups(groupData);
      setSummary(summaryData);
      setDepartments(departmentData);
      setProjects(projectData.items);
      setTotal(projectData.total);
      setTemplates(templateData);
      setPackages(packageData);
      setConstraintTemplates(constraintTemplateData);
      setCategories(categoryData);
      setDepartmentSettings(departmentSettingData);
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
  }, [activeGroup, selectedProjectType, selectedCategory, selectedDepartment, selectedExternalConditions, selectedAdvancementStatus, selectedImplementationYear, sortBy, sortDir, deferredKeyword]);

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
  const showImplementationFilter = activeGroup === "completed";

  useEffect(() => {
    if (!showImplementationFilter && selectedImplementationYear) {
      setSelectedImplementationYear("");
    }
  }, [showImplementationFilter, selectedImplementationYear]);

  useEffect(() => {
    if (activeGroup !== "pre_establish" && selectedAdvancementStatus) setSelectedAdvancementStatus("");
  }, [activeGroup, selectedAdvancementStatus]);

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

  function handleProjectRowClick(event: MouseEvent<HTMLTableRowElement>, projectId: number) {
    const target = event.target as HTMLElement;
    if (target.closest("button,a,input,select,textarea,[role=button],[data-interactive]")) return;
    toggleSelection(projectId);
  }

  function toggleAllVisible() {
    if (selectedProjects.length === projects.length && projects.length > 0) {
      setSelectedIds([]);
      return;
    }
    setSelectedIds(projects.map((project) => project.id));
  }

  const activeTemplates = useMemo(() => templates.filter((item) => !item.archived_at), [templates]);
  const activePackages = useMemo(() => packages.filter((item) => !item.archived_at), [packages]);
  const activeConstraintTemplates = useMemo(() => constraintTemplates.filter((item) => !item.archived_at), [constraintTemplates]);

  const recommendedColumns = useMemo(
    () => activeTemplates
      .filter((item) => item.recommended_stage === (groups.find((group) => group.key === activeGroup)?.label ?? "") && item.stage_view_priority != null)
      .sort((left, right) => (left.stage_view_priority ?? 999) - (right.stage_view_priority ?? 999))
      .map((item) => item.name)
      .slice(0, 7),
    [activeGroup, groups, activeTemplates],
  );
  const stageColumns = visibleColumnsByStage[activeGroup] ?? recommendedColumns;
  const currentProjectColumns = useMemo(
    () => [...new Set(projects.flatMap((project) => Object.keys(project.work_item_states ?? {})))].sort((left, right) => left.localeCompare(right, "zh-CN")),
    [projects],
  );
  const searchedColumns = useMemo(() => {
    const keyword = columnSearch.trim();
    if (!keyword) return [];
    return [...new Set([...currentProjectColumns, ...activeTemplates.map((item) => item.name)])]
      .filter((name) => name.includes(keyword))
      .filter((name) => !stageColumns.includes(name))
      .slice(0, 8);
  }, [columnSearch, currentProjectColumns, stageColumns, activeTemplates]);

  function saveStageColumns(columns: string[]) {
    setVisibleColumnsByStage((current) => {
      const result = { ...current, [activeGroup]: columns };
      localStorage.setItem("pmo-stage-columns-v2", JSON.stringify(result));
      return result;
    });
  }

  function addStageColumn(column: string) {
    if (!stageColumns.includes(column)) saveStageColumns([...stageColumns, column]);
  }

  function removeStageColumn(column: string) {
    saveStageColumns(stageColumns.filter((item) => item !== column));
  }

  function resetStageColumns() {
    setVisibleColumnsByStage((current) => {
      const { [activeGroup]: _discarded, ...remaining } = current;
      localStorage.setItem("pmo-stage-columns-v2", JSON.stringify(remaining));
      return remaining;
    });
  }

  function closeRail() {
    setRailExpanded(false);
    setQuickItem(null);
    setQuickProjectId(null);
    setQuickProject(null);
  }

  useEffect(() => {
    if (!railExpanded) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRail();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [railExpanded]);

  function updateDraft(index: number, patch: Partial<WorkItemDraft>) {
    setDraftItems((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  }

  function addTemplateToDraft(template: WorkItemTemplate) {
    setDraftItems((items) => [...items, { ...emptyDraft(), name: template.name, execution_mode: template.execution_mode, flow_group: template.flow_group, sequence_rank: template.sequence_rank }]);
  }

  async function openQuickItem(projectId: number, itemId: number) {
    const [items, project, logs] = await Promise.all([
      apiGet<WorkItem[]>("/projects/" + projectId + "/work-items"),
      apiGet<Project>("/projects/" + projectId),
      apiGet<WorkItemProgressLog[]>("/projects/" + projectId + "/work-items/" + itemId + "/progress-logs"),
    ]);
    const item = items.find((entry) => entry.id === itemId) ?? null;
    setQuickItem(item); setQuickProjectId(projectId); setQuickProject(project); setQuickLogs(logs); setShowAllQuickLogs(false); setQuickCompletionResult(""); setQuickCreateMilestone(Boolean(item?.completion_rule_snapshot?.effects?.create_milestone)); setRailExpanded(true);
  }

  async function refreshProjectRow(projectId: number) {
    const project = await apiGet<Project>("/projects/" + projectId);
    setProjects((current) => current.map((entry) => entry.id === projectId ? { ...entry, ...project } : entry));
    setQuickProject(project);
  }

  async function saveQuickItem() {
    if (!quickItem || !quickProjectId) return;
    try {
      const updated = await apiPatch<WorkItem>("/projects/" + quickProjectId + "/work-items/" + quickItem.id, { ...quickItem, operator });
      setQuickItem(updated);
      await refreshProjectRow(quickProjectId);
      setFeedback("事项变更已保存。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项未保存，页面保持原状。"); }
  }

  async function addQuickProgress() {
    if (!quickItem || !quickProjectId || !quickProgress.trim()) return;
    try {
      const log = await apiPost<WorkItemProgressLog>("/projects/" + quickProjectId + "/work-items/" + quickItem.id + "/progress-logs", { operator, content: quickProgress.trim() });
      setQuickLogs((current) => [log, ...current]); setQuickProgress(""); await refreshProjectRow(quickProjectId);
    } catch (err) { setError(err instanceof ApiError ? err.message : "进展未记录，页面保持原状。"); }
  }

  async function editQuickProgress(log: WorkItemProgressLog) {
    setDialog({ kind: "edit-log", title: "修改进展记录", value: log.content, target: log });
  }

  async function deleteQuickProgress(log: WorkItemProgressLog) {
    setDialog({ kind: "delete-log", title: "删除进展记录", value: "", target: log });
  }

  async function submitDialog() {
    if (!dialog) return;
    try {
      if (dialog.kind === "edit-log" && quickItem && quickProjectId && dialog.target && dialog.value.trim()) {
        const updated = await apiPatch<WorkItemProgressLog>(`/projects/${quickProjectId}/work-items/${quickItem.id}/progress-logs/${dialog.target.id}`, { operator, content: dialog.value.trim(), is_timeline_highlight: dialog.target.is_timeline_highlight });
        setQuickLogs((logs) => logs.map((entry) => entry.id === updated.id ? updated : entry));
      } else if (dialog.kind === "delete-log" && quickItem && quickProjectId && dialog.target && dialog.value.trim()) {
        await apiDelete<{ success: boolean }>(`/projects/${quickProjectId}/work-items/${quickItem.id}/progress-logs/${dialog.target.id}`, { operator, reason: dialog.value.trim() });
        setQuickLogs((logs) => logs.filter((entry) => entry.id !== dialog.target!.id));
      } else if (dialog.kind === "archive-template" && dialog.template && dialog.value.trim()) {
        const path = dialog.template.kind === "work-package" ? `/work-packages/${dialog.template.id}/archive` : `/${dialog.template.kind}-templates/${dialog.template.id}/archive`;
        await apiPost(path, { operator, reason: dialog.value.trim() });
        setFeedback(`已归档“${dialog.template.name}”。`);
        await loadDashboard();
      }
      setDialog(null);
    } catch (err) { setError(err instanceof ApiError ? err.message : "操作未成功，界面未变更。"); }
  }

  async function quickComplete() {
    if (!quickItem || !quickProjectId) return;
    const effects = quickItem.completion_rule_snapshot?.effects;
    try {
      const requiredMilestone = Boolean(effects?.create_milestone && effects?.milestone_name);
      const updated = await apiPost<WorkItem>("/projects/" + quickProjectId + "/work-items/" + quickItem.id + "/complete", {
        operator, result: quickCompletionResult.trim() || "已完成", create_milestone: requiredMilestone || quickCreateMilestone, milestone_name: effects?.milestone_name || quickItem.name,
      });
      setQuickItem(updated); await refreshProjectRow(quickProjectId); setFeedback("事项已完成并写入项目历史。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项未完成，页面保持原状。"); }
  }

  async function submitBatchItems() {
    if (!selectedIds.length || draftItems.some((item) => !item.name.trim())) { setError("请选择项目并填写每个事项名称。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ created_count: number }>("/projects/batch-work-items", {
        project_ids: selectedIds, operator, items: draftItems,
        save_as_common: saveAsCommon,
        save_as_package_name: packageName.trim() || null,
      });
      setFeedback(`已向 ${selectedIds.length} 个项目下发 ${result.created_count} 条事项。`);
      setDraftItems([emptyDraft()]); setSaveAsCommon(false); setPackageName("");
      await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项下发失败"); }
    finally { setExecuting(false); }
  }

  async function submitBatchConstraints() {
    if (!selectedIds.length) { setError("请先选择项目。"); return; }
    const template = constraintTemplates.find((item) => item.id === constraintTemplateId);
    const name = constraintName.trim() || template?.name || "";
    if (!name) { setError("请选择常用外部约束或填写约束名称。"); return; }
    setExecuting(true); setError("");
    try {
      await apiPost("/projects/batch-external-constraints", {
        project_ids: selectedIds,
        operator,
        constraints: [{ template_id: constraintTemplateId, name, is_blocking: constraintBlocking, handling_status: constraintStatus }],
        save_as_common: saveConstraintAsCommon,
      });
      setFeedback(`已向 ${selectedIds.length} 个项目建立外部约束${saveConstraintAsCommon ? "，并已保存为常用约束。" : "。"}`);
      setConstraintTemplateId(null); setConstraintName(""); setSaveConstraintAsCommon(false);
      await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "建立外部约束失败"); }
    finally { setExecuting(false); }
  }

  async function archiveTemplate(kind: "work-item" | "work-package" | "external-constraint", id: number, name: string) {
    setDialog({ kind: "archive-template", title: `归档“${name}”`, value: "", template: { kind, id, name } });
  }

  async function addProjectCategory() {
    if (!newCategoryName.trim()) { setError("请填写项目类别名称。"); return; }
    try {
      await apiPost("/meta/project-categories", { name: newCategoryName.trim(), sort_order: newCategoryOrder ? Number(newCategoryOrder) : null, operator });
      setNewCategoryName(""); setNewCategoryOrder(""); await loadDashboard(); setFeedback("已新增项目类别。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "新增项目类别失败"); }
  }

  async function saveDepartmentOrder(department: string, order: string) {
    try {
      await apiPatch(`/meta/departments/${encodeURIComponent(department)}/order`, { sort_order: Number(order), operator });
      await loadDashboard(); setFeedback(`已更新“${department}”的部门排序。`);
    } catch (err) { setError(err instanceof ApiError ? err.message : "部门排序保存失败"); }
  }

  async function saveProjectCategory(category: ProjectCategory, updates: Partial<ProjectCategory>) {
    try {
      await apiPatch(`/meta/project-categories/${category.id}`, { ...updates, operator });
      await loadDashboard(); setFeedback(`已更新项目类别“${category.name}”。`);
    } catch (err) { setError(err instanceof ApiError ? err.message : "项目类别未更新，页面保持原状。"); }
  }

  async function submitAdvancement() {
    if (!selectedIds.length || !comment.trim()) { setError("纳入推进需要选择项目并填写理由。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ success: number }>("/projects/batch-include-in-advancement", {
        project_ids: selectedIds, operator, reason: comment, advancement_year: Number(advancementYear),
      });
      setFeedback(`已将 ${result.success} 个项目纳入年度推进。`); setComment(""); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "纳入推进失败"); }
    finally { setExecuting(false); }
  }

  async function submitDeferAdvancement() {
    if (!selectedIds.length || !comment.trim()) { setError("暂缓推进需要选择项目并填写原因。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ success: number }>("/projects/batch-defer-advancement", { project_ids: selectedIds, operator, reason: comment });
      setFeedback(`已暂缓 ${result.success} 个项目的本年度推进。`); setComment(""); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "暂缓推进失败"); }
    finally { setExecuting(false); }
  }

  async function submitEarlyPreparation() {
    if (!selectedIds.length || !comment.trim() || !earlyApprovalBasis.trim()) { setError("提前推进准备需要填写理由和审批依据。"); return; }
    setExecuting(true); setError("");
    try {
      await Promise.all(selectedIds.map((id) => apiPost(`/projects/${id}/special-include-in-advancement`, { operator, reason: comment, approval_basis: earlyApprovalBasis, advancement_year: Number(advancementYear) })));
      setFeedback(`已特批纳入 ${selectedIds.length} 个未立项项目的前期推进管理。`); setComment(""); setEarlyApprovalBasis(""); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "特批纳入推进失败"); }
    finally { setExecuting(false); }
  }

  async function submitPackage() {
    if (!selectedIds.length || !selectedPackageId) { setError("请选择项目和工作包。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ created_count: number }>("/projects/apply-work-package", { project_ids: selectedIds, package_id: selectedPackageId, operator });
      setFeedback(`已从工作包下发 ${result.created_count} 条事项。`); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "工作包下发失败"); }
    finally { setExecuting(false); }
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

  async function createManualProject() {
    if (!newProject.name.trim()) { setError("请填写项目名称。"); return; }
    try {
      const created = await apiPost<Project>("/projects", {
        name: newProject.name.trim(), department: newProject.department.trim(), project_manager: newProject.project_manager.trim(),
        project_type: newProject.project_type, budget: Number(newProject.budget || 0), description: newProject.description.trim(), operator,
      });
      setNewProjectOpen(false);
      setNewProject({ name: "", department: "", project_manager: "", project_type: "teaching_software", budget: "", description: "" });
      setFeedback(`已新增项目“${created.name}”（${created.project_code}）。`);
      await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "新增项目失败，列表未变更。"); }
  }

  return (
    <div className="shell">
      <div className="backdrop-grid" />
      <header className="hero">
        <div className="hero-copy">
          <p className="eyebrow">PMO WORKSPACE</p>
          <h1>PMO 项目管理工作台</h1>
          <div className="hero-actions">
            <button className="action-button primary" onClick={() => setNewProjectOpen(true)}>
              <Plus size={16} />新增项目
            </button>
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
        <div className="hero-metrics">
          <div className="hero-stats">
            <article className="hero-stat"><span>项目库总量</span><strong>{summary?.project_library_count ?? "—"}</strong></article>
            <article className="hero-stat"><span>项目库总预算</span><strong>{formatCurrency(summary?.project_library_total_effective_budget)} 万</strong></article>
            <article className="hero-stat"><span>外部条件已具备</span><strong>{summary?.external_conditions_ready_count ?? "—"}</strong></article>
            <article className="hero-stat"><span>外部条件已具备预算</span><strong>{formatCurrency(summary?.external_conditions_ready_effective_budget)} 万</strong></article>
          </div>
          <button type="button" className={`external-ongoing-summary ${selectedExternalConditions === "ongoing" ? "active" : ""}`} onClick={() => setSelectedExternalConditions((value) => value === "ongoing" ? "" : "ongoing")}>
            外部约束办理中：{summary?.external_conditions_ongoing_count ?? 0} 个项目 · 涉及预算 {formatCurrency(summary?.external_conditions_ongoing_effective_budget)} 万
          </button>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}
      {feedback ? <div className="notice success">{feedback}</div> : null}

      <main className="workspace">
        <section className="main-stage">
          <section className="group-band">
            {groups.map((group) => (
              <button
                key={group.key}
                className={`group-card ${activeGroup === group.key ? "active" : ""}`}
                style={{ "--group-accent": GROUP_ACCENTS[group.key] } as CSSProperties}
                onClick={() => setActiveGroup(group.key)}
              >
                <div className="group-main">
                  <p>{group.label}</p>
                  <strong>{group.count}</strong>
                </div>
                <div className="group-budget">
                  <span>预算 {formatCurrency(group.total_budget)} 万</span>
                  {group.key !== "pre_establish" && group.key !== "completed" ? (
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
                <select className="select" value={selectedCategory} onChange={(event) => setSelectedCategory(event.target.value)}>
                  <option value="">全部类别</option>
                  {categories.filter((item) => item.is_active).map((category) => <option key={category.id} value={category.name}>{category.name}</option>)}
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
                {activeGroup === "pre_establish" ? <select className="select" value={selectedAdvancementStatus} onChange={(event) => setSelectedAdvancementStatus(event.target.value)}><option value="">全部推进状态</option><option value="special_active">特批推进中</option></select> : null}
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
              <div className="table-tools">
                <button className={`mini-button ${tableView === "overview" ? "active" : ""}`} onClick={() => { setTableView("overview"); setColumnPickerOpen(false); }}>总览</button>
                <button className={`mini-button ${tableView === "stage" ? "active" : ""}`} onClick={() => setTableView("stage")}>阶段跟踪</button>
                {tableView === "stage" ? <div className="column-picker"><button type="button" className="mini-button" aria-expanded={columnPickerOpen} onClick={() => setColumnPickerOpen((open) => !open)}>显示列</button>{columnPickerOpen ? <div className="column-picker-menu" role="dialog" aria-label="配置阶段跟踪显示列">
                  <div className="column-picker-heading"><strong>显示列</strong><button type="button" className="text-button" onClick={() => setColumnPickerOpen(false)}>关闭</button></div>
                  <p>只影响当前工作台视图，不会创建事项。</p>
                  <section><span>已显示</span><div className="column-chip-list">{stageColumns.map((column) => <button type="button" key={column} onClick={() => removeStageColumn(column)}>{column} <b>×</b></button>)}{!stageColumns.length ? <small>暂无显示列</small> : null}</div></section>
                  <section><span>推荐列</span><div className="column-action-list">{recommendedColumns.filter((column) => !stageColumns.includes(column)).map((column) => <button type="button" key={column} onClick={() => addStageColumn(column)}>＋ {column}</button>)}{!recommendedColumns.filter((column) => !stageColumns.includes(column)).length ? <small>已全部加入</small> : null}</div></section>
                  <section><span>当前结果中存在</span><div className="column-action-list">{currentProjectColumns.filter((column) => !stageColumns.includes(column) && !recommendedColumns.includes(column)).slice(0, 8).map((column) => <button type="button" key={column} onClick={() => addStageColumn(column)}>＋ {column}</button>)}{!currentProjectColumns.filter((column) => !stageColumns.includes(column) && !recommendedColumns.includes(column)).length ? <small>暂无额外事项</small> : null}</div></section>
                  <label className="column-search"><span>搜索其他常用事项</span><input className="input" value={columnSearch} onChange={(event) => setColumnSearch(event.target.value)} placeholder="输入事项名称" /></label>
                  {columnSearch.trim() ? <div className="column-action-list search-results">{searchedColumns.map((column) => <button type="button" key={column} onClick={() => addStageColumn(column)}>＋ {column}</button>)}{!searchedColumns.length ? <small>未找到可添加的事项</small> : null}</div> : null}
                  <button type="button" className="text-button column-reset" onClick={resetStageColumns}>恢复默认推荐列</button>
                </div> : null}</div> : null}
                <button className="mini-button" onClick={toggleAllVisible}>
                  {selectedProjects.length === projects.length && projects.length ? "取消全选" : "全选当前结果"}
                </button>
              </div>
            </div>

            <div className="project-table-wrap">
              {loading ? (
                <div className="loading-panel">
                  <LoaderCircle className="spin" size={22} />
                  正在载入工作台
                </div>
              ) : (
                <table className={`project-table ${tableView === "stage" ? "stage-tracking-table" : ""}`}>
                  <thead>
                    <tr>
                      <th>选中</th>
                      <th>项目</th>
                      <th>Stage</th>
                      {tableView === "overview" ? <th>当前进展</th> : stageColumns.map((column) => <th key={column}>{column}</th>)}
                      <th>
                        <button className="sort-button" onClick={() => toggleSort("department")}>
                          部门 / 负责人 {sortLabel("department")}
                        </button>
                      </th>
                      <th>预算</th>
                      <th>下一关键节点</th>
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
                        <tr key={project.id} className={selected ? "selected" : ""} onClick={(event) => handleProjectRowClick(event, project.id)}>
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
                          <td>
                            <div className="stage-cell"><strong>{project.stage || "未归属"}</strong>{project.advancement?.status === "special_active" ? <small className="special-advancement">特批推进中</small> : null}</div>
                          </td>
                          {tableView === "overview" ? <td><ProgressSummary project={project} onSelect={(itemId) => void openQuickItem(project.id, itemId)} /></td> : stageColumns.map((column) => <td key={column}><StageItemCell project={project} column={column} /></td>)}
                          <td>
                            <div className="stacked">
                              <span>{project.department || "未录入部门"}</span>
                              <small>{project.project_manager || "未录入负责人"}</small>
                            </div>
                          </td>
                          <td>
                            <div className="stacked">
                              <span>有效 {formatCurrency(project.effective_budget ?? project.budget)} 万</span>
                              <small>初始 {formatCurrency(project.budget)} 万</small>
                              <ExternalCondition project={project} />
                            </div>
                          </td>
                          <td><KeyNode project={project} /></td>
                          <td className="updated-date">{formatDate(project.status_updated_at)}</td>
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
          {railExpanded ? <button type="button" className="rail-scrim" aria-label="收起操作台" onClick={closeRail} /> : null}
          <div className={`rail-card operation-console ${railExpanded ? "is-expanded" : ""}`}>
            <button className="rail-toggle" type="button" onClick={() => railExpanded ? closeRail() : setRailExpanded(true)} aria-label={railExpanded ? "收起操作台" : "展开批量操作"}>{railExpanded ? "×" : "☰"}</button>
            <p className="section-kicker">PMO ACTIONS</p>
            <h3>{quickItem ? "快速办理" : "批量操作"}</h3>
            {!quickItem ? <div className="selection-summary">
              <span>当前勾选</span>
              <strong>{selectedIds.length}</strong>
            </div> : null}
            {!quickItem ? <div className="operation-tabs">
              {([ ["advance", "纳入推进"], ["stage", "调整 Stage"], ["items", "添加事项"], ["package", "应用工作包"], ["constraints", "外部约束"], ["config", "基础配置"], ["batch", "加入批次"] ] as const).map(([mode, label]) => <button key={mode} disabled={mode === "batch"} className={operationMode === mode ? "active" : ""} onClick={() => { setOperationMode(mode); setRailExpanded(true); }}>{label}{mode === "batch" ? " · 后续" : ""}</button>)}
            </div> : null}
            <div className="operation-body">
              {quickItem ? <section className="quick-panel">
                <div className="quick-context"><span>当前项目</span><strong>{quickProject?.name || "项目"}</strong><small>{quickProject?.project_code}</small><div><b>{quickItem.name}</b><em>{workStatusLabel(quickItem.status)}</em></div></div>
                <div className="quick-panel-heading"><span>最近进展</span><button className="text-button" onClick={() => { setQuickItem(null); setQuickProjectId(null); setQuickProject(null); }}>返回批量操作</button></div>
                <div className="quick-log-list">{(showAllQuickLogs ? quickLogs : quickLogs.slice(0, 3)).map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDate(log.created_at)} · {log.operator}</small><div className="log-actions"><button className="text-button" onClick={() => void editQuickProgress(log)}>编辑</button><button className="text-button" onClick={() => void deleteQuickProgress(log)}>删除</button></div></article>)}</div>
                {!quickLogs.length ? <p className="muted-copy">暂无进展记录</p> : null}
                {quickLogs.length > 3 ? <button className="text-button" onClick={() => setShowAllQuickLogs((value) => !value)}>{showAllQuickLogs ? "收起进展记录" : "查看全部进展记录"}</button> : null}
                <textarea className="textarea" rows={3} value={quickProgress} onChange={(event) => setQuickProgress(event.target.value)} placeholder="今天有什么变化？" />
                <div className="quick-fields"><select className="select" value={quickItem.status} onChange={(event) => setQuickItem((item) => item ? { ...item, status: event.target.value } : item)}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option><option value="paused">暂停</option><option value="not_applicable">不适用</option></select><input className="input" type="date" value={quickItem.planned_date} onChange={(event) => setQuickItem((item) => item ? { ...item, planned_date: event.target.value } : item)} /></div>
                <label className="toggle"><input type="checkbox" checked={Boolean(quickItem.track_as_key_node)} onChange={(event) => setQuickItem((item) => item ? { ...item, track_as_key_node: event.target.checked } : item)} /><span>☆ 重点关注</span></label>
                <details className="draft-settings"><summary>完成时补充信息</summary><div className="details-body"><textarea className="textarea" rows={2} value={quickCompletionResult} onChange={(event) => setQuickCompletionResult(event.target.value)} placeholder="完成结果、日期或说明（可选）" /><label className="toggle"><input type="checkbox" checked={quickCreateMilestone} disabled={Boolean(quickItem.completion_rule_snapshot?.effects?.create_milestone && quickItem.completion_rule_snapshot?.effects?.milestone_name)} onChange={(event) => setQuickCreateMilestone(event.target.checked)} /><span>同时记录为项目里程碑</span></label></div></details>
                <div className="quick-actions"><button className="mini-button" onClick={() => void addQuickProgress()}>＋记录进展</button><button className="mini-button" onClick={() => void saveQuickItem()}>保存变更</button><button className="mini-button active" onClick={() => void quickComplete()}>完成事项</button></div>
              </section> : <>{operationMode === "advance" ? <>
                <p className="operation-lead">{activeGroup === "pool_active" ? "将结束当前年度推进周期，项目回到项目库—未实施。" : activeGroup === "pre_establish" ? "特批推进仅用于未立项项目的前期管理；项目仍留在未立项 Stage。" : "将把已勾选项目纳入年度推进管理，不受单个事项状态影响。"}</p>
                <label className="field"><span>操作人</span><input className="input" value={operator} onChange={(event) => setOperator(event.target.value)} /></label>
                {activeGroup !== "pool_active" ? <label className="field"><span>推进年度</span><input className="input" type="number" value={advancementYear} onChange={(event) => setAdvancementYear(event.target.value)} /></label> : null}
                <label className="field"><span>{activeGroup === "pool_active" ? "暂缓原因" : activeGroup === "pre_establish" ? "特批原因" : "纳入理由"}</span><textarea className="textarea" value={comment} onChange={(event) => setComment(event.target.value)} rows={4} /></label>
                {activeGroup === "pool_active" ? <button className="action-button primary full" disabled={!selectedIds.length || !comment || executing} onClick={() => void submitDeferAdvancement()}><CheckCircle2 size={16} />确认暂缓推进</button> : activeGroup === "pre_establish" ? <><label className="field"><span>审批人或审批依据</span><input className="input" value={earlyApprovalBasis} onChange={(event) => setEarlyApprovalBasis(event.target.value)} placeholder="必填：审批人或审批依据" /></label><button className="action-button primary full" disabled={!selectedIds.length || !comment || !earlyApprovalBasis || executing} onClick={() => void submitEarlyPreparation()}><CheckCircle2 size={16} />确认特批纳入推进</button></> : <button className="action-button primary full" disabled={!selectedIds.length || !comment || executing} onClick={() => void submitAdvancement()}><CheckCircle2 size={16} />确认纳入推进</button>}
              </> : null}
              {operationMode === "items" ? <>
                <p className="operation-lead">将向 <strong>{selectedIds.length}</strong> 个项目添加事项</p>
                <div className="common-item-picker">
                  <div className="mini-section-heading"><strong>常用事项</strong><button className="text-button" onClick={() => setTemplateManager(templateManager === "items" ? null : "items")}>管理</button></div>
                  <input className="input" value={templateKeyword} onChange={(event) => setTemplateKeyword(event.target.value)} placeholder="搜索常用事项……" />
                  <div className="template-chip-list">{activeTemplates.filter((item) => item.name.includes(templateKeyword.trim())).map((item) => <button key={item.id} onClick={() => addTemplateToDraft(item)}>{item.name}</button>)}{!activeTemplates.length ? <span>暂无常用事项，可将本次事项保存后复用。</span> : null}</div>
                  {templateManager === "items" ? <TemplateManager items={templates} kind="work-item" onArchive={archiveTemplate} onRefresh={loadDashboard} operator={operator} onError={setError} /> : null}
                </div>
                {draftItems.map((item, index) => <div className="draft-item" key={index}>
                  <div className="draft-item-title"><strong>{index + 1}. 新建跟踪事项</strong>{draftItems.length > 1 ? <button className="text-button" onClick={() => setDraftItems((items) => items.filter((_, itemIndex) => itemIndex !== index))}>移除</button> : null}</div>
                  <input className="input" value={item.name} onChange={(event) => updateDraft(index, { name: event.target.value })} placeholder="事项名称*，例如：等学院补交采购需求书" />
                  <textarea className="textarea" rows={3} value={item.content} onChange={(event) => updateDraft(index, { content: event.target.value })} placeholder="事项内容 / 当前需要做什么" />
                  <select className="select" value={item.status} onChange={(event) => updateDraft(index, { status: event.target.value })}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option></select>
                  <details className="draft-settings"><summary>更多管理信息</summary><div className="details-body"><div className="field-grid"><input className="input" value={item.assignee} onChange={(event) => updateDraft(index, { assignee: event.target.value })} placeholder="负责人" /><input className="input" type="date" value={item.planned_date} onChange={(event) => updateDraft(index, { planned_date: event.target.value })} /></div><div className="field-grid"><select className="select" value={item.priority} onChange={(event) => updateDraft(index, { priority: event.target.value })}><option value="high">高优先级</option><option value="normal">普通</option><option value="low">低优先级</option></select><select className="select" value={item.execution_mode} onChange={(event) => updateDraft(index, { execution_mode: event.target.value })}><option value="tracking">仅跟踪</option><option value="internal">系统内</option><option value="external">系统外</option></select></div><div className="field-grid"><select className="select" value={item.flow_group} onChange={(event) => updateDraft(index, { flow_group: event.target.value as "main" | "independent" })}><option value="independent">独立跟踪事项</option><option value="main">主流程事项</option></select>{item.flow_group === "main" ? <input className="input" type="number" value={item.sequence_rank || ""} onChange={(event) => updateDraft(index, { sequence_rank: Number(event.target.value) || 1000 })} placeholder="流程排序，例如 400" /> : <span />}</div><textarea className="textarea" rows={2} value={item.note} onChange={(event) => updateDraft(index, { note: event.target.value })} placeholder="附加备注" /></div></details>
                  <details className="draft-settings"><summary>完成设置</summary><div className="details-body"><label className="toggle"><input type="checkbox" checked={Boolean(item.completion_effects?.create_milestone)} onChange={(event) => updateDraft(index, { completion_effects: { ...item.completion_effects, create_milestone: event.target.checked } })} /><span>完成后记入项目里程碑</span></label>{item.completion_effects?.create_milestone ? <input className="input" value={item.completion_effects?.milestone_name || ""} onChange={(event) => updateDraft(index, { completion_effects: { ...item.completion_effects, milestone_name: event.target.value } })} placeholder="里程碑名称" /> : null}<label className="toggle"><input type="checkbox" checked={Boolean(item.completion_effects?.require_result)} onChange={(event) => updateDraft(index, { completion_effects: { ...item.completion_effects, require_result: event.target.checked } })} /><span>完成时需要填写结果</span></label>{item.completion_effects?.require_result ? <select className="select" value={item.completion_effects?.result_type || "free_text"} onChange={(event) => updateDraft(index, { completion_effects: { ...item.completion_effects, result_type: event.target.value as "free_text" | "pass_fail" | "custom" } })}><option value="free_text">自由填写</option><option value="pass_fail">通过 / 不通过</option><option value="custom">自定义选项</option></select> : null}</div></details>
                </div>)}
                <button className="mini-button full" onClick={() => setDraftItems((items) => [...items, emptyDraft()])}><Plus size={15} />再添加一项</button>
                <label className="toggle"><input type="checkbox" checked={saveAsCommon} onChange={(event) => setSaveAsCommon(event.target.checked)} /><span>保存单项为常用事项</span></label>
                <input className="input" value={packageName} onChange={(event) => setPackageName(event.target.value)} placeholder="工作包名称（填写即保存本次事项组合）" />
                <button className="action-button primary full" disabled={!selectedIds.length || executing} onClick={() => void submitBatchItems()}><PackagePlus size={16} />确认添加事项</button>
              </> : null}
              {operationMode === "package" ? <>
                <p className="operation-lead">从已沉淀的工作包向 <strong>{selectedIds.length}</strong> 个项目下发事项。</p>
                <button className="text-button" onClick={() => setTemplateManager(templateManager === "packages" ? null : "packages")}>管理工作包</button>
                {templateManager === "packages" ? <TemplateManager items={packages} kind="work-package" onArchive={archiveTemplate} onRefresh={loadDashboard} operator={operator} onError={setError} /> : null}
                <select className="select" value={selectedPackageId ?? ""} onChange={(event) => setSelectedPackageId(Number(event.target.value) || null)}><option value="">选择工作包</option>{activePackages.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.items.length} 项</option>)}</select>
                {selectedPackageId ? <div className="package-preview">{activePackages.find((item) => item.id === selectedPackageId)?.items.map((item) => <span key={item.name}>{item.name}</span>)}{activePackages.find((item) => item.id === selectedPackageId)?.constraints?.length ? <div className="constraint-package-preview"><strong>将建立的外部约束</strong>{activePackages.find((item) => item.id === selectedPackageId)?.constraints?.map((item, index) => <span key={item.template_id ?? index}>{item.name || "外部约束模板"}</span>)}</div> : null}</div> : null}
                <button className="action-button primary full" disabled={!selectedIds.length || !selectedPackageId || executing} onClick={() => void submitPackage()}><PackagePlus size={16} />应用工作包</button>
              </> : null}
              {operationMode === "constraints" ? <>
                <p className="operation-lead">向已勾选项目建立外部治理条件；它不会改变项目 Stage 或事项状态。</p>
                <button className="text-button" onClick={() => setTemplateManager(templateManager === "constraints" ? null : "constraints")}>管理常用外部约束</button>
                {templateManager === "constraints" ? <TemplateManager items={constraintTemplates} kind="external-constraint" onArchive={archiveTemplate} onRefresh={loadDashboard} operator={operator} onError={setError} /> : null}
                <label className="field"><span>操作人</span><input className="input" value={operator} onChange={(event) => setOperator(event.target.value)} /></label>
                <label className="field"><span>常用外部约束</span><select className="select" value={constraintTemplateId ?? ""} onChange={(event) => { const next = Number(event.target.value) || null; setConstraintTemplateId(next); const template = activeConstraintTemplates.find((item) => item.id === next); if (template) { setConstraintName(template.name); setConstraintBlocking(Boolean(template.is_blocking)); } }}><option value="">选择常用约束（可选）</option>{activeConstraintTemplates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                <label className="field"><span>约束名称</span><input className="input" value={constraintName} onChange={(event) => setConstraintName(event.target.value)} placeholder="例如：上级预算核定" /></label>
                <label className="toggle"><input type="checkbox" checked={constraintBlocking} onChange={(event) => setConstraintBlocking(event.target.checked)} /><span>当前阻断后续推进</span></label>
                <label className="field"><span>初始办理状态</span><select className="select" value={constraintStatus} onChange={(event) => setConstraintStatus(event.target.value)}><option value="not_started">未开始</option><option value="in_progress">办理中</option><option value="needs_supplement">需补充材料</option></select></label>
                <label className="toggle"><input type="checkbox" checked={saveConstraintAsCommon} onChange={(event) => setSaveConstraintAsCommon(event.target.checked)} /><span>保存为常用外部约束</span></label>
                <button className="action-button primary full" disabled={!selectedIds.length || executing} onClick={() => void submitBatchConstraints()}>确认添加外部约束</button>
              </> : null}
              {operationMode === "stage" ? <>
                <label className="field"><span>操作人</span><input className="input" value={operator} onChange={(event) => setOperator(event.target.value)} /></label>
                <label className="toggle"><input type="checkbox" checked={forceMode} onChange={(event) => setForceMode(event.target.checked)} /><span>启用 PMO 特批强制变更</span></label>
                <label className="field"><span>目标 Stage（特批）</span><select className="select" value={selectedTarget} onChange={(event) => setSelectedTarget(event.target.value)}><option value="">选择固定 Stage</option><option value="draft">未立项</option><option value="established">项目库—未实施</option><option value="closed">已完成</option><option value="terminated">已废弃</option></select></label>
                <label className="field"><span>审批人</span><input className="input" value={approver} onChange={(event) => setApprover(event.target.value)} /></label>
                <label className="field"><span>变更理由</span><textarea className="textarea" value={comment} onChange={(event) => setComment(event.target.value)} rows={3} /></label>
                <button className="action-button primary full" disabled={!selectedIds.length || !selectedTarget || !comment || executing} onClick={() => void executeBatch()}><CheckCircle2 size={16} />确认调整 Stage</button>
                <div className="operation-preview">{preview ? <><strong>预检结果：{preview.requested_target?.status_name ?? "未命中共同状态"}</strong><span>{preview.requires_approval ? "需要审批" : "可直接推进"}</span>{preview.conflicts.length ? <div className="conflict-list">{preview.conflicts.map((conflict) => <div key={`${conflict.project_id}-${conflict.code}`} className="conflict-item"><AlertTriangle size={15} /><span>{conflict.message}</span></div>)}</div> : <span>本次勾选没有发现预检冲突。</span>}</> : <span>选择目标 Stage 后显示预检结果。</span>}</div>
              </> : null}
              {operationMode === "config" ? <section className="config-panel"><p className="operation-lead">基础字典用于 PMO 排序和筛选；项目类别不等同于项目业务类型。</p><label className="field"><span>新增项目类别</span><input className="input" value={newCategoryName} onChange={(event) => setNewCategoryName(event.target.value)} placeholder="例如：实验室建设项目" /></label><label className="field"><span>类别排序（小的在前）</span><input className="input" type="number" value={newCategoryOrder} onChange={(event) => setNewCategoryOrder(event.target.value)} /></label><button className="mini-button" onClick={() => void addProjectCategory()}>新增类别</button><div className="template-manager">{categories.map((category) => <div key={category.id}><span>{category.name}</span><input className="input compact-input" type="number" defaultValue={category.sort_order ?? ""} placeholder="排序" onBlur={(event) => { if (event.target.value) void saveProjectCategory(category, { sort_order: Number(event.target.value) }); }} /><button className="text-button" onClick={() => void saveProjectCategory(category, { is_active: !category.is_active })}>{category.is_active ? "停用" : "恢复"}</button></div>) || <span>暂无类别</span>}</div><p className="mini-section-heading"><strong>部门排序</strong></p><div className="template-manager">{departments.map((department) => { const configured = departmentSettings.find((item) => item.department === department); return <div key={department}><span>{department}</span><input className="input compact-input" type="number" defaultValue={configured?.sort_order ?? ""} placeholder="排序" onBlur={(event) => { if (event.target.value) void saveDepartmentOrder(department, event.target.value); }} /></div>; })}</div></section> : null}
              {operationMode === "batch" ? <div className="empty-state"><Layers3 size={18} />批次登记将在 Phase 2 开放。</div> : null}</>}
            </div>
          </div>

        </aside>
      </main>
      {dialog ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => setDialog(null)}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label={dialog.title} onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">PMO ACTION</p><h3>{dialog.title}</h3>
          <p className="muted-copy">{dialog.kind === "delete-log" ? "请填写删除原因。记录会从日常界面隐藏，但审计仍会完整保留。" : dialog.kind === "archive-template" ? "归档后不会影响已下发事项和历史记录。" : "更新后将立即回显到当前事项。"}</p>
          <textarea className="textarea" rows={3} autoFocus value={dialog.value} placeholder={dialog.kind === "delete-log" || dialog.kind === "archive-template" ? "请填写原因（必填）" : "进展内容"} onChange={(event) => setDialog({ ...dialog, value: event.target.value })} />
          <div className="dialog-actions"><button className="mini-button" onClick={() => setDialog(null)}>取消</button><button className="action-button primary" disabled={!dialog.value.trim()} onClick={() => void submitDialog()}>确认</button></div>
        </section>
      </div> : null}
      {newProjectOpen ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => setNewProjectOpen(false)}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label="新增项目" onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">PMO ACTION</p><h3>新增项目</h3>
          <input className="input" autoFocus value={newProject.name} onChange={(event) => setNewProject({ ...newProject, name: event.target.value })} placeholder="项目名称（必填）" />
          <div className="field-grid"><input className="input" value={newProject.department} onChange={(event) => setNewProject({ ...newProject, department: event.target.value })} placeholder="部门/学院" /><input className="input" value={newProject.project_manager} onChange={(event) => setNewProject({ ...newProject, project_manager: event.target.value })} placeholder="负责人" /></div>
          <div className="field-grid"><select className="select" value={newProject.project_type} onChange={(event) => setNewProject({ ...newProject, project_type: event.target.value })}><option value="teaching_software">专业教学软件项目</option><option value="practical_teaching_site">实践教学场所项目</option></select><input className="input" type="number" value={newProject.budget} onChange={(event) => setNewProject({ ...newProject, budget: event.target.value })} placeholder="初始预算（万元）" /></div>
          <textarea className="textarea" rows={2} value={newProject.description} onChange={(event) => setNewProject({ ...newProject, description: event.target.value })} placeholder="项目说明（可选）" />
          <div className="dialog-actions"><button className="mini-button" onClick={() => setNewProjectOpen(false)}>取消</button><button className="action-button primary" disabled={!newProject.name.trim()} onClick={() => void createManualProject()}>确认新增</button></div>
        </section>
      </div> : null}
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
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [managementTimeline, setManagementTimeline] = useState<ManagementTimelineEvent[]>([]);
  const [workItems, setWorkItems] = useState<WorkItem[]>([]);
  const [templates, setTemplates] = useState<WorkItemTemplate[]>([]);
  const [externalConstraints, setExternalConstraints] = useState<ProjectExternalConstraint[]>([]);
  const [constraintTemplates, setConstraintTemplates] = useState<ExternalConstraintTemplate[]>([]);
  const [addingConstraint, setAddingConstraint] = useState(false);
  const [newConstraintTemplateId, setNewConstraintTemplateId] = useState<number | null>(null);
  const [newConstraintName, setNewConstraintName] = useState("");
  const [newConstraintBlocking, setNewConstraintBlocking] = useState(true);
  const [concludingConstraintId, setConcludingConstraintId] = useState<number | null>(null);
  const [conclusionBudget, setConclusionBudget] = useState("");
  const [conclusionNote, setConclusionNote] = useState("");
  const [conclusionCleared, setConclusionCleared] = useState(true);
  const [invalidatingConstraintId, setInvalidatingConstraintId] = useState<number | null>(null);
  const [invalidationReason, setInvalidationReason] = useState("");
  const [editingProject, setEditingProject] = useState(false);
  const [projectReason, setProjectReason] = useState("");
  const [deleteProjectOpen, setDeleteProjectOpen] = useState(false);
  const [deleteProjectReason, setDeleteProjectReason] = useState("");
  const [addingItem, setAddingItem] = useState(false);
  const [newDraft, setNewDraft] = useState<WorkItemDraft>(emptyDraft());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [completionId, setCompletionId] = useState<number | null>(null);
  const [completionMilestone, setCompletionMilestone] = useState(false);
  const [completionMilestoneName, setCompletionMilestoneName] = useState("");
  const [reopenId, setReopenId] = useState<number | null>(null);
  const [reopenReason, setReopenReason] = useState("");
  const [progressLogs, setProgressLogs] = useState<Record<number, WorkItemProgressLog[]>>({});
  const [expandedProgressItem, setExpandedProgressItem] = useState<number | null>(null);
  const [progressDraft, setProgressDraft] = useState("");
  const [highlightProgress, setHighlightProgress] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    void Promise.all([
      apiGet<Project>(`/projects/${projectId}`),
      apiGet<StatusHistoryItem[]>(`/projects/${projectId}/history`),
      apiGet<WorkItem[]>(`/projects/${projectId}/work-items`),
      apiGet<WorkItemTemplate[]>("/work-item-templates"),
      apiGet<AuditEvent[]>(`/projects/${projectId}/audit-events`),
      apiGet<ManagementTimelineEvent[]>(`/projects/${projectId}/management-timeline`),
      apiGet<ProjectExternalConstraint[]>(`/projects/${projectId}/external-constraints`),
      apiGet<ExternalConstraintTemplate[]>("/external-constraint-templates"),
    ])
      .then(([projectData, historyData, workItemData, templateData, auditData, timelineData, constraintData, constraintTemplateData]) => {
        setProject(projectData);
        setHistory(historyData);
        setWorkItems(workItemData);
        setTemplates(templateData);
        setAuditEvents(auditData);
        setManagementTimeline(timelineData);
        setExternalConstraints(constraintData);
        setConstraintTemplates(constraintTemplateData);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "项目详情加载失败");
      })
      .finally(() => setLoading(false));
  }, [projectId]);

  async function refreshTimeline() {
    if (!projectId) return;
    const [auditData, timelineData] = await Promise.all([
      apiGet<AuditEvent[]>(`/projects/${projectId}/audit-events`),
      apiGet<ManagementTimelineEvent[]>(`/projects/${projectId}/management-timeline`),
    ]);
    setAuditEvents(auditData);
    setManagementTimeline(timelineData);
  }

  async function addWorkItem() {
    if (!projectId || !newDraft.name.trim()) return;
    const created = await apiPost<WorkItem>(`/projects/${projectId}/work-items`, { ...newDraft, name: newDraft.name.trim(), operator: "PMO办公室" });
    setWorkItems((items) => [created, ...items]);
    setNewDraft(emptyDraft()); setAddingItem(false);
    await refreshTimeline();
  }

  async function completeWorkItem(item: WorkItem) {
    if (!projectId) return;
    const updated = await apiPost<WorkItem>(`/projects/${projectId}/work-items/${item.id}/complete`, { operator: "PMO办公室", result: "已完成", create_milestone: completionMilestone, milestone_name: completionMilestoneName || item.name });
    setWorkItems((items) => items.map((current) => current.id === updated.id ? updated : current));
    setCompletionId(null); setCompletionMilestone(false); setCompletionMilestoneName("");
    await refreshTimeline();
  }

  async function updateWorkItem(item: WorkItem) {
    if (!projectId) return;
  const updated = await apiPatch<WorkItem>(`/projects/${projectId}/work-items/${item.id}`, { operator: "PMO办公室", status: item.status === "not_started" ? "in_progress" : item.status, assignee: item.assignee, planned_date: item.planned_date, priority: item.priority, note: item.note, content: item.content, track_as_key_node: Boolean(item.track_as_key_node) });
    setWorkItems((items) => items.map((current) => current.id === updated.id ? updated : current)); setEditingId(null);
    await refreshTimeline();
  }

  async function reopenWorkItem(item: WorkItem) {
    if (!projectId || !reopenReason.trim()) return;
    const updated = await apiPost<WorkItem>(`/projects/${projectId}/work-items/${item.id}/reopen`, { operator: "PMO办公室", reason: reopenReason });
    setWorkItems((items) => items.map((current) => current.id === updated.id ? updated : current)); setReopenId(null); setReopenReason("");
    await refreshTimeline();
  }

  async function toggleProgressLogs(itemId: number) {
    if (!projectId) return;
    if (expandedProgressItem === itemId) { setExpandedProgressItem(null); return; }
    if (!progressLogs[itemId]) {
      const logs = await apiGet<WorkItemProgressLog[]>(`/projects/${projectId}/work-items/${itemId}/progress-logs`);
      setProgressLogs((current) => ({ ...current, [itemId]: logs }));
    }
    setExpandedProgressItem(itemId);
  }

  async function addProgressLog(itemId: number) {
    if (!projectId || !progressDraft.trim()) return;
    const log = await apiPost<WorkItemProgressLog>(`/projects/${projectId}/work-items/${itemId}/progress-logs`, {
      content: progressDraft.trim(), operator: "PMO办公室", is_timeline_highlight: highlightProgress,
    });
    setProgressLogs((current) => ({ ...current, [itemId]: [log, ...(current[itemId] ?? [])] }));
    setProgressDraft(""); setHighlightProgress(false);
    await refreshTimeline();
  }

  async function addExternalConstraint() {
    if (!projectId || !newConstraintName.trim()) return;
    try {
      const created = await apiPost<ProjectExternalConstraint>(`/projects/${projectId}/external-constraints`, { template_id: newConstraintTemplateId, name: newConstraintName.trim(), is_blocking: newConstraintBlocking, operator: "PMO办公室" });
      setExternalConstraints((items) => [created, ...items]); setNewConstraintName(""); setNewConstraintTemplateId(null); setAddingConstraint(false);
      const current = await apiGet<Project>(`/projects/${projectId}`); setProject(current); await refreshTimeline();
    } catch (err) { setError(err instanceof ApiError ? err.message : "外部约束未建立，页面保持原状。"); }
  }

  async function confirmConstraintScope() {
    if (!projectId) return;
    try {
      await apiPost(`/projects/${projectId}/confirm-external-constraint-scope`, { operator: "PMO办公室", note: "PMO 已确认当前适用外部约束范围" });
      const current = await apiGet<Project>(`/projects/${projectId}`); setProject(current); await refreshTimeline();
    } catch (err) { setError(err instanceof ApiError ? err.message : "适用范围未确认，页面保持原状。"); }
  }

  async function actOnConstraint(constraint: ProjectExternalConstraint, action: string) {
    if (!projectId) return;
    const payload: Record<string, unknown> = { operator: "PMO办公室", action };
    if (action === "conclude") {
      payload.cleared = conclusionCleared;
      payload.outcome = conclusionBudget.trim() ? { approved_budget: Number(conclusionBudget) } : {};
      payload.evidence_note = conclusionNote;
    }
    if (action === "invalidate") payload.reason = invalidationReason;
    try {
      const updated = await apiPost<ProjectExternalConstraint>(`/projects/${projectId}/external-constraints/${constraint.id}/actions`, payload);
      setExternalConstraints((items) => items.map((item) => item.id === updated.id ? updated : item));
      if (action === "conclude") { setConcludingConstraintId(null); setConclusionBudget(""); setConclusionNote(""); setConclusionCleared(true); }
      if (action === "invalidate") { setInvalidatingConstraintId(null); setInvalidationReason(""); }
      const current = await apiGet<Project>(`/projects/${projectId}`); setProject(current); await refreshTimeline();
    } catch (err) { setError(err instanceof ApiError ? err.message : "约束办理未成功，页面保持原状。"); }
  }

  async function saveProjectEdits() {
    if (!projectId || !project || !projectReason.trim()) return;
    const updated = await apiPatch<Project>(`/projects/${projectId}`, { name: project.name, department: project.department, major: project.major, project_manager: project.project_manager, location: project.location, category: project.category, project_type: project.project_type, description: project.description, budget: project.budget, operator: "PMO办公室", reason: projectReason });
    setProject(updated); setProjectReason(""); setEditingProject(false); await refreshTimeline();
  }

  async function removeProject() {
    if (!projectId || !project || !deleteProjectReason.trim()) return;
    try {
      await apiDelete(`/projects/${projectId}`, { operator: "PMO办公室", reason: deleteProjectReason.trim() });
      navigate("/");
    } catch (err) { setError(err instanceof ApiError ? err.message : "项目未移除，页面保持原状。"); }
  }

  const detailKeyNode = useMemo(() => workItems
    .filter((item) => item.track_as_key_node && !["completed", "paused", "not_applicable"].includes(item.status))
    .sort((left, right) => (left.planned_date || "9999-12-31").localeCompare(right.planned_date || "9999-12-31"))[0], [workItems]);

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
            {project ? <span className="status-chip">{project.stage || "未归属"}</span> : null}
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
              <div className="section-title"><div><p className="section-kicker">PROGRESS</p><h2>当前进展</h2>{detailKeyNode ? <p className="next-node-inline"><strong>下一关键节点</strong>　{detailKeyNode.name} · {detailKeyNode.planned_date || "未设置日期"} · {workStatusLabel(detailKeyNode.status)}</p> : <p className="next-node-inline"><strong>下一关键节点</strong>　未设置</p>}</div><button className="mini-button" onClick={() => setAddingItem((current) => !current)}><Plus size={15} />添加事项</button></div>
              {addingItem ? <div className="detail-add-item">
                <select className="select" value="" onChange={(event) => { const template = templates.find((item) => item.id === Number(event.target.value)); if (template) setNewDraft((current) => ({ ...current, name: template.name, execution_mode: template.execution_mode })); }}><option value="">从常用事项选择（或直接自定义）</option>{templates.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>
                <input className="input" value={newDraft.name} onChange={(event) => setNewDraft((current) => ({ ...current, name: event.target.value }))} placeholder="事项名称*，例如：等学院补交采购需求书" />
                <textarea className="textarea" rows={3} value={newDraft.content} onChange={(event) => setNewDraft((current) => ({ ...current, content: event.target.value }))} placeholder="事项内容 / 当前需要做什么" />
                <select className="select" value={newDraft.status} onChange={(event) => setNewDraft((current) => ({ ...current, status: event.target.value }))}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option></select>
                <details className="draft-settings"><summary>更多管理信息</summary><div className="details-body"><div className="field-grid"><input className="input" value={newDraft.assignee} onChange={(event) => setNewDraft((current) => ({ ...current, assignee: event.target.value }))} placeholder="负责人" /><input className="input" type="date" value={newDraft.planned_date} onChange={(event) => setNewDraft((current) => ({ ...current, planned_date: event.target.value }))} /></div><div className="field-grid"><select className="select" value={newDraft.priority} onChange={(event) => setNewDraft((current) => ({ ...current, priority: event.target.value }))}><option value="high">高优先级</option><option value="normal">普通</option><option value="low">低优先级</option></select><select className="select" value={newDraft.execution_mode} onChange={(event) => setNewDraft((current) => ({ ...current, execution_mode: event.target.value }))}><option value="tracking">仅跟踪</option><option value="internal">系统内</option><option value="external">系统外</option></select></div><textarea className="textarea" rows={2} value={newDraft.note} onChange={(event) => setNewDraft((current) => ({ ...current, note: event.target.value }))} placeholder="附加备注" /></div></details>
                <button className="action-button primary" onClick={() => void addWorkItem()}>确认添加临时事项</button>
              </div> : null}
              <div className="work-item-list">
                {workItems.length ? workItems.map((item) => (
                  <div className={`work-item-row work-${item.status}`} key={item.id}>
                    <div className="work-item-copy"><strong>{item.name}</strong><span className={`work-status work-${item.status}`}>{workStatusLabel(item.status)}</span><small>负责人：{item.assignee || "未指定"}　计划：{item.planned_date || "未设置"}</small>{item.content ? <p>{item.content}</p> : null}{item.note ? <small>{item.note}</small> : null}{item.track_as_key_node ? <em>☆ 重点关注</em> : null}</div>
                    {editingId === item.id ? <div className="work-item-edit"><select className="select" value={item.status} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, status: event.target.value } : current))}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option><option value="paused">暂停</option><option value="not_applicable">不适用</option></select><input className="input" value={item.assignee} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, assignee: event.target.value } : current))} placeholder="负责人" /><input className="input" type="date" value={item.planned_date} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, planned_date: event.target.value } : current))} /><textarea className="textarea" rows={2} value={item.content} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, content: event.target.value } : current))} placeholder="事项内容" /><label className="toggle"><input type="checkbox" checked={Boolean(item.track_as_key_node)} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, track_as_key_node: event.target.checked } : current))} /><span>☆ 重点关注</span></label><button className="mini-button" onClick={() => void updateWorkItem(item)}>保存</button></div> : <div className="work-item-actions">{item.status !== "completed" ? <><button className="mini-button" onClick={() => setEditingId(item.id)}>更新</button><button className="mini-button" onClick={() => { setCompletionId(item.id); setCompletionMilestone(Boolean(item.completion_rule_snapshot.effects?.create_milestone)); setCompletionMilestoneName(item.completion_rule_snapshot.effects?.milestone_name || item.name); }}>完成</button></> : <button className="mini-button" onClick={() => setReopenId(item.id)}>重开</button>}<button className="mini-button" onClick={() => void toggleProgressLogs(item.id)}>进展 {expandedProgressItem === item.id ? "收起" : "记录"}</button></div>}
                    {completionId === item.id ? <div className="reopen-row"><label className="toggle"><input type="checkbox" checked={completionMilestone} onChange={(event) => setCompletionMilestone(event.target.checked)} /><span>同时记录为项目里程碑</span></label>{completionMilestone ? <input className="input" value={completionMilestoneName} onChange={(event) => setCompletionMilestoneName(event.target.value)} placeholder="里程碑名称" /> : null}<button className="mini-button" onClick={() => void completeWorkItem(item)}>确认完成</button></div> : null}
                    {reopenId === item.id ? <div className="reopen-row"><input className="input" value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} placeholder="重开原因" /><button className="mini-button" onClick={() => void reopenWorkItem(item)}>确认重开</button></div> : null}
                    {expandedProgressItem === item.id ? <div className="progress-log-panel"><div className="progress-log-compose"><textarea className="textarea" rows={2} value={progressDraft} onChange={(event) => setProgressDraft(event.target.value)} placeholder="今天有什么变化？" /><label className="toggle"><input type="checkbox" checked={highlightProgress} onChange={(event) => setHighlightProgress(event.target.checked)} /><span>同步到项目时间线</span></label><button className="mini-button" onClick={() => void addProgressLog(item.id)}>记录进展</button></div>{(progressLogs[item.id] ?? []).length ? <div className="progress-log-list">{progressLogs[item.id].map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDateTime(log.created_at)} · {log.operator}{log.is_timeline_highlight ? " · 已同步时间线" : ""}</small></article>)}</div> : <p className="muted-copy">尚未记录过程进展。</p>}</div> : null}
                  </div>
                )) : <div className="empty-state">暂无跟踪事项。先添加一个当前正在推进的工作。</div>}
              </div>
            </section>

            <section className="detail-section">
              <div className="section-title"><div><p className="section-kicker">EXTERNAL CONDITIONS</p><h2>外部约束</h2><p className="muted-copy">外部约束只描述外部治理条件，不改变项目 Stage 或当前事项。</p></div><div className="work-item-actions"><button className="mini-button" onClick={() => void confirmConstraintScope()}>确认适用范围</button><button className="mini-button" onClick={() => setAddingConstraint((value) => !value)}><Plus size={15} />添加外部约束</button></div></div>
              {addingConstraint ? <div className="detail-add-item"><select className="select" value={newConstraintTemplateId ?? ""} onChange={(event) => { const id = Number(event.target.value) || null; setNewConstraintTemplateId(id); const template = constraintTemplates.find((item) => item.id === id); if (template) { setNewConstraintName(template.name); setNewConstraintBlocking(Boolean(template.is_blocking)); } }}><option value="">从常用约束选择（或直接新建）</option>{constraintTemplates.filter((item) => !item.archived_at).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input className="input" value={newConstraintName} onChange={(event) => setNewConstraintName(event.target.value)} placeholder="外部约束名称，例如：上级预算核定" /><label className="toggle"><input type="checkbox" checked={newConstraintBlocking} onChange={(event) => setNewConstraintBlocking(event.target.checked)} /><span>当前阻断后续推进</span></label><button className="action-button primary" onClick={() => void addExternalConstraint()}>确认添加外部约束</button></div> : null}
              <div className="constraint-list">{externalConstraints.length ? externalConstraints.map((constraint) => <article key={constraint.id} className="constraint-card"><div><strong>{constraint.name}</strong><small>{constraint.is_blocking ? "阻断性条件" : "非阻断性条件"} · {constraint.handling_status === "concluded" ? "已形成结论" : constraint.handling_status === "in_progress" ? "办理中" : constraint.handling_status === "needs_supplement" ? "需补充" : constraint.handling_status === "not_applicable" ? "不适用" : "未开始"}</small></div><div className="work-item-actions"><button className="mini-button" onClick={() => void actOnConstraint(constraint, "begin")}>开始办理</button><button className="mini-button" onClick={() => void actOnConstraint(constraint, "needs_supplement")}>需补充</button><button className="mini-button active" onClick={() => setConcludingConstraintId(constraint.id)}>登记结论</button><button className="mini-button" onClick={() => void actOnConstraint(constraint, "mark_not_applicable")}>不适用</button><button className="mini-button" onClick={() => setInvalidatingConstraintId(constraint.id)}>结论失效</button></div>{concludingConstraintId === constraint.id ? <div className="constraint-conclusion"><strong>登记当前有效结论</strong><input className="input" type="number" value={conclusionBudget} onChange={(event) => setConclusionBudget(event.target.value)} placeholder="核定预算（可选，万元）" /><textarea className="textarea" rows={2} value={conclusionNote} onChange={(event) => setConclusionNote(event.target.value)} placeholder="结论说明或依据" /><label className="toggle"><input type="checkbox" checked={conclusionCleared} onChange={(event) => setConclusionCleared(event.target.checked)} /><span>该结论已解除当前阻断</span></label><div className="work-item-actions"><button className="mini-button" onClick={() => setConcludingConstraintId(null)}>取消</button><button className="mini-button active" onClick={() => void actOnConstraint(constraint, "conclude")}>保存结论</button></div></div> : null}{invalidatingConstraintId === constraint.id ? <div className="constraint-conclusion"><strong>使已有结论失效</strong><textarea className="textarea" rows={2} value={invalidationReason} onChange={(event) => setInvalidationReason(event.target.value)} placeholder="失效原因（必填）" /><div className="work-item-actions"><button className="mini-button" onClick={() => setInvalidatingConstraintId(null)}>取消</button><button className="mini-button danger" disabled={!invalidationReason.trim()} onClick={() => void actOnConstraint(constraint, "invalidate")}>确认失效</button></div></div> : null}</article>) : <div className="empty-state">尚无外部约束。无阻断性约束的项目默认计为外部条件已具备。</div>}</div>
            </section>

            <section className="detail-section">
              <div className="section-title">
                <div><p className="section-kicker">BASIC</p><h2>基本信息</h2></div>
                <div className="work-item-actions"><button className="mini-button" onClick={() => setEditingProject((value) => !value)}>编辑基本信息</button><button className="mini-button danger" onClick={() => setDeleteProjectOpen(true)}>移除项目</button></div>
              </div>
              {editingProject ? <div className="detail-add-item"><input className="input" value={project.name} onChange={(event) => setProject({ ...project, name: event.target.value })} placeholder="项目名称" /><div className="field-grid"><input className="input" value={project.department ?? ""} onChange={(event) => setProject({ ...project, department: event.target.value })} placeholder="部门/学院" /><input className="input" value={project.major ?? ""} onChange={(event) => setProject({ ...project, major: event.target.value })} placeholder="所属专业" /></div><div className="field-grid"><input className="input" value={project.project_manager ?? ""} onChange={(event) => setProject({ ...project, project_manager: event.target.value })} placeholder="项目负责人" /><input className="input" value={project.location ?? ""} onChange={(event) => setProject({ ...project, location: event.target.value })} placeholder="地点" /></div><div className="field-grid"><label className="field"><span>项目类别（PMO 管理分类）</span><input className="input" value={project.category ?? ""} onChange={(event) => setProject({ ...project, category: event.target.value })} placeholder="例如：实验室建设项目" /></label><label className="field"><span>项目类型（业务属性）</span><input className="input" value={project.project_type ?? ""} onChange={(event) => setProject({ ...project, project_type: event.target.value })} placeholder="项目类型" /></label></div><label className="field"><span>初始预算（仅导入/录入纠错）</span><input className="input" type="number" value={project.budget ?? 0} onChange={(event) => setProject({ ...project, budget: Number(event.target.value) })} /></label><textarea className="textarea" rows={2} value={project.description ?? ""} onChange={(event) => setProject({ ...project, description: event.target.value })} placeholder="项目说明" /><textarea className="textarea" rows={2} value={projectReason} onChange={(event) => setProjectReason(event.target.value)} placeholder="修改理由（必填）" /><button className="action-button primary" disabled={!projectReason.trim()} onClick={() => void saveProjectEdits()}>保存并写入审计</button></div> : null}
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
                <p className="section-kicker">TIMELINE</p>
                <h2>项目时间线</h2>
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
              {managementTimeline.length ? <div className="audit-timeline">{managementTimeline.map((event) => <article key={event.id}><strong>{event.summary}</strong><span>{formatDateTime(event.created_at)} · {event.operator}</span></article>)}</div> : null}
              <details className="full-audit-log"><summary>查看完整操作记录</summary><div className="audit-timeline">{auditEvents.map((event) => <article key={event.id}><strong>{event.event_type}</strong><span>{formatDateTime(event.created_at)} · {event.operator}{event.reason ? ` · ${event.reason}` : ""}</span></article>)}</div></details>
            </section>
          </section>

          <aside className="detail-side">
            <article className="hero-stat">
              <span>初始预算</span>
              <strong>{formatCurrency(project.budget)} 万</strong>
            </article>
            <article className="hero-stat">
              <span>当前有效预算</span>
              <strong>{formatCurrency(project.effective_budget ?? project.budget)} 万</strong>
              <small>{project.effective_budget_source === "budget_constraint" ? "来源：预算核定结果" : project.effective_budget_source === "historical_review" ? "来源：历史审核预算" : "来源：初始预算"}</small>
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
      {deleteProjectOpen && project ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => setDeleteProjectOpen(false)}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label="移除项目" onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">PMO ACTION</p><h3>移除“{project.name}”</h3>
          <p className="muted-copy">项目将从日常列表隐藏，历史和审计记录会保留。</p>
          <textarea className="textarea" rows={3} autoFocus value={deleteProjectReason} onChange={(event) => setDeleteProjectReason(event.target.value)} placeholder="移除原因（必填）" />
          <div className="dialog-actions"><button className="mini-button" onClick={() => setDeleteProjectOpen(false)}>取消</button><button className="action-button primary danger-action" disabled={!deleteProjectReason.trim()} onClick={() => void removeProject()}>确认移除</button></div>
        </section>
      </div> : null}
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
