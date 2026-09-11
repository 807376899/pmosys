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
  useRef,
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
  ProjectTypeDefinition,
  DepartmentSetting,
  ProjectExternalConstraint,
  ExternalConstraintProgressLog,
  ExternalConstraintState,
  StageColumn,
  Milestone,
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
const today = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

const workStatusLabel = (status: string) => ({
  not_started: "未开始", in_progress: "进行中", waiting_external: "等待外部",
  completed: "已完成", paused: "暂停", not_applicable: "不适用",
}[status] ?? status);

const procurementNatureLabel = (value?: string | null) => ({ goods: "货物", service: "服务", mixed: "混合" } as Record<string, string>)[value || ""] ?? "未设置";

const sortProjectWorkItems = (items: WorkItem[]) => [...items].sort((left, right) => {
  if (left.flow_group !== right.flow_group) return left.flow_group === "main" ? -1 : 1;
  if (left.flow_group === "main") return left.sequence_rank - right.sequence_rank || left.id - right.id;
  const inactive = (item: WorkItem) => item.status === "completed" || item.status === "not_applicable" || Boolean(item.cancelled_at);
  const priority = { high: 0, normal: 1, low: 2 } as Record<string, number>;
  return Number(inactive(left)) - Number(inactive(right))
    || Number(Boolean(right.track_as_key_node)) - Number(Boolean(left.track_as_key_node))
    || (left.planned_date || "9999-12-31").localeCompare(right.planned_date || "9999-12-31")
    || (priority[left.priority] ?? 1) - (priority[right.priority] ?? 1)
    || left.id - right.id;
});

const constraintStatusLabel = (status: string) => ({ not_started: "未开始", in_progress: "办理中", concluded: "已形成结论", invalidated: "结论失效" } as Record<string, string>)[status] ?? status;
const clearanceLabel = (status: string) => ({ unresolved: "待解除", cleared: "已解除", not_applicable: "不适用" } as Record<string, string>)[status] ?? status;

function constraintMatchesColumn(constraint: ExternalConstraintState, key: string) {
  if (key.startsWith("manual:")) {
    const [, name, outcomeKind] = key.split(":");
    return constraint.template_id == null && constraint.name === decodeURIComponent(name) && (constraint.outcome_kind || "custom") === outcomeKind;
  }
  return constraint.id === Number(key) || constraint.template_id === Number(key) || constraint.name === key;
}

type ColumnBatchTarget = {
  kind: "work_item" | "external_constraint";
  key: string;
  label: string;
  instances: Record<number, number>;
  templateId?: number;
  outcomeKind?: string;
};

function ProgressSituation({ project, onSelect, onConstraintSelect }: { project: Project; onSelect?: (itemId: number) => void; onConstraintSelect?: () => void }) {
  const node = project.next_key_node;
  const focus = project.progress_focus_item;
  const shownActive = [node, focus].filter((item, index, all) => item && all.findIndex((entry) => entry?.id === item.id) === index).length;
  const moreCount = Math.max((project.active_work_item_count ?? 0) - shownActive, 0);
  const ready = project.external_constraints_cleared === "true";
  const summary = ready ? "外部条件已具备" : `外部条件待处理 · ${project.external_constraint_open_count ?? 0} 项`;
  if (!node && !focus && ready) return <div className="progress-summary progress-situation"><button type="button" onClick={onConstraintSelect}><strong>{summary}</strong></button><span className="muted-copy">暂无待推进事项</span></div>;
  return <div className="progress-summary progress-situation">
    <button type="button" className={ready ? "external-ready" : "external-pending"} onClick={onConstraintSelect}><strong>{summary}</strong></button>
    {node ? <button type="button" onClick={() => onSelect?.(node.id)}><strong>{node.name}</strong><small>{workStatusLabel(node.status)}{node.planned_date ? ` · ${node.planned_date}` : ""}</small></button> : null}
    {focus ? <button type="button" onClick={() => onSelect?.(focus.id)}><strong>{focus.name}</strong><small>{workStatusLabel(focus.status)}</small></button> : null}
    {moreCount ? <em>+{moreCount}</em> : null}
  </div>;
}

function StageItemCell({ project, column, onWorkItemSelect, onConstraintSelect, highlighted }: { project: Project; column: StageColumn; onWorkItemSelect?: (id: number) => void; onConstraintSelect?: (id: number) => void; highlighted?: boolean }) {
  const aliases: Record<string, string[]> = {
    "学院流程": ["学院流程", "学院内部流程"],
    "专家评审": ["专家评审", "小组评审", "校外专家评审"],
    "委员会": ["委员会", "实验室建设与管理委员会"],
    "会议": ["会议", "校长办公会", "党委会"],
  };
  if (column.kind === "external_constraint") {
    const constraint = project.external_constraint_states?.find((item) => constraintMatchesColumn(item, column.key));
    return constraint ? <button type="button" className={`stage-constraint-cell${highlighted ? " column-batch-highlight" : ""}`} onClick={() => onConstraintSelect?.(constraint.id)}><small>约束</small><strong>{constraintStatusLabel(constraint.handling_status)}</strong><span>{clearanceLabel(constraint.clearance_status)}</span>{constraint.latest_progress_summary ? <em title={constraint.latest_progress_summary}>{constraint.latest_progress_summary}</em> : null}</button> : <span className="muted-copy">—</span>;
  }
  const item = project.work_item_column_states?.find((candidate) => (aliases[column.key] ?? [column.key]).includes(candidate.name));
  return item ? <button type="button" className={`stage-item-cell${highlighted ? " column-batch-highlight" : ""}`} onClick={() => onWorkItemSelect?.(item.id)}>{workStatusLabel(item.status)}</button> : <span className="muted-copy">—</span>;
}

function constraintSummary(constraint: ProjectExternalConstraint) {
  const outcome = constraint.outcome_json || {};
  if (typeof outcome.approved_budget === "number") return `核定 ${formatCurrency(outcome.approved_budget)} 万`;
  return typeof outcome.result === "string" && outcome.result ? outcome.result : "暂无结论";
}

type ManagedTemplate = { id: number; name: string; archived_at?: string | null; default_content?: string; recommended_stage?: string; stage_view_priority?: number | null; flow_group?: "main" | "independent"; execution_mode?: string; is_blocking?: boolean | number; outcome_schema_json?: { kind?: string }; scope_kind?: string; scope_value?: string; effective_from?: string; effective_until?: string; applicability_basis?: string };
function TemplateManager({ items, kind, onArchive, onRefresh, operator, onError, projectTypes = [] }: {
  items: ManagedTemplate[];
  kind: "work-item" | "work-package" | "external-constraint";
  onArchive: (kind: "work-item" | "work-package" | "external-constraint", id: number, name: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  operator: string;
  onError: (message: string) => void;
  projectTypes?: ProjectTypeDefinition[];
}) {
  const [showArchived, setShowArchived] = useState(false);
  const [deleting, setDeleting] = useState<ManagedTemplate | null>(null);
  const [editing, setEditing] = useState<ManagedTemplate | null>(null);
  const [name, setName] = useState("");
  const [defaultContent, setDefaultContent] = useState("");
  const [recommendedStage, setRecommendedStage] = useState("");
  const [stageViewPriority, setStageViewPriority] = useState("");
  const [reason, setReason] = useState("");
  const [blocking, setBlocking] = useState(true);
  const [outcomeKind, setOutcomeKind] = useState("custom");
  const [scopeKind, setScopeKind] = useState("manual");
  const [scopeValue, setScopeValue] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveUntil, setEffectiveUntil] = useState("");
  const [applicabilityBasis, setApplicabilityBasis] = useState("");
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
    try { await apiPatch(path(editing, "restore").replace("/restore", ""), { operator, name: name.trim(), ...(kind === "work-item" ? { default_content: defaultContent, recommended_stage: recommendedStage, stage_view_priority: stageViewPriority ? Number(stageViewPriority) : null } : {}), ...(kind === "external-constraint" ? { is_blocking: blocking, outcome_schema_json: { kind: outcomeKind }, scope_kind: scopeKind, scope_value: scopeKind === "project_type" ? scopeValue : "", effective_from: effectiveFrom, effective_until: effectiveUntil, applicability_basis: applicabilityBasis } : {}) }); setEditing(null); setName(""); await onRefresh(); }
    catch (err) { onError(err instanceof ApiError ? err.message : "模板未更新，页面保持原状。"); }
  }
  return <div className="template-manager" data-interactive>
    <div className="template-manager-heading"><strong>模板治理</strong><button className="text-button" onClick={() => setShowArchived((value) => !value)}>{showArchived ? "仅看启用" : "查看归档"}</button></div>
    {visible.map((item) => <div key={item.id}><span>{item.name}{item.archived_at ? " · 已归档" : ""}</span><aside>{item.archived_at ? <><button className="text-button" onClick={() => void restore(item)}>恢复</button><button className="text-button danger" onClick={() => setDeleting(item)}>永久删除</button></> : <><button className="text-button" onClick={() => { setEditing(item); setName(item.name); setDefaultContent(item.default_content || ""); setRecommendedStage(item.recommended_stage || ""); setStageViewPriority(item.stage_view_priority ? String(item.stage_view_priority) : ""); setBlocking(Boolean(item.is_blocking)); setOutcomeKind(item.outcome_schema_json?.kind || "custom"); setScopeKind(item.scope_kind || "manual"); setScopeValue(item.scope_value || ""); setEffectiveFrom(item.effective_from || ""); setEffectiveUntil(item.effective_until || ""); setApplicabilityBasis(item.applicability_basis || ""); }}>编辑</button><button className="text-button" onClick={() => void onArchive(kind, item.id, item.name)}>归档</button></>}</aside></div>)}
    {!visible.length ? <small>当前没有符合条件的模板。</small> : null}
    {deleting ? <section className="template-confirm"><strong>永久删除“{deleting.name}”</strong><p>仅从未被引用的模板可永久删除；已有历史引用将被服务器拒绝。</p><textarea className="textarea" rows={2} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="删除原因（必填）" /><div><button className="mini-button" onClick={() => setDeleting(null)}>取消</button><button className="mini-button danger" disabled={!reason.trim()} onClick={() => void remove()}>确认永久删除</button></div></section> : null}
    {editing ? <section className="template-confirm"><strong>编辑常用模板</strong><input className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="模板名称" />{kind === "work-item" ? <><textarea className="textarea" rows={2} value={defaultContent} onChange={(event) => setDefaultContent(event.target.value)} placeholder="默认事项内容" /><div className="field-grid"><select className="select" value={recommendedStage} onChange={(event) => setRecommendedStage(event.target.value)}><option value="">不推荐特定 Stage</option><option value="未立项">未立项</option><option value="项目库—未实施">项目库—未实施</option><option value="项目库—推进中">项目库—推进中</option></select><input className="input" type="number" value={stageViewPriority} onChange={(event) => setStageViewPriority(event.target.value)} placeholder="阶段跟踪排序（留空不推荐）" /></div></> : null}{kind === "external-constraint" ? <><label className="toggle"><input type="checkbox" checked={blocking} onChange={(event) => setBlocking(event.target.checked)} /><span>默认阻断后续推进</span></label><div className="field-grid"><select className="select" value={outcomeKind} onChange={(event) => setOutcomeKind(event.target.value)}><option value="budget_determination">预算核定</option><option value="eligibility">准入判断</option><option value="filing">备案</option><option value="custom">自定义结果</option></select><select className="select" value={scopeKind} onChange={(event) => setScopeKind(event.target.value)}><option value="manual">手工/批量指定</option><option value="all">全部项目</option><option value="project_type">指定项目分类</option></select></div>{scopeKind === "project_type" ? <select className="select" value={scopeValue} onChange={(event) => setScopeValue(event.target.value)}><option value="">选择项目分类</option>{projectTypes.filter((item) => item.is_active).map((item) => <option value={item.code} key={item.id}>{item.name}</option>)}</select> : null}<div className="field-grid"><input className="input" type="date" value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} /><input className="input" type="date" value={effectiveUntil} onChange={(event) => setEffectiveUntil(event.target.value)} /></div><input className="input" value={applicabilityBasis} onChange={(event) => setApplicabilityBasis(event.target.value)} placeholder="适用判断基准说明（仅供 PMO 手工判断）" /></> : null}<p>修改只影响后续新建或下发；项目中的既有事项保持自身快照。</p><div><button className="mini-button" onClick={() => setEditing(null)}>取消</button><button className="mini-button" disabled={!name.trim() || (kind === "external-constraint" && scopeKind === "project_type" && !scopeValue)} onClick={() => void saveName()}>保存</button></div></section> : null}
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
  const [selectedDepartment, setSelectedDepartment] = useState<string>("");
  const [selectedExternalConditions, setSelectedExternalConditions] = useState<"" | "ready" | "ongoing">("");
  const [showRemoved, setShowRemoved] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<Project | null>(null);
  const [restoreReason, setRestoreReason] = useState("");
  const [selectedImplementationYear, setSelectedImplementationYear] = useState<string>("");
  const [sortBy, setSortBy] = useState<string>("status_updated_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [keyword, setKeyword] = useState("");
  const deferredKeyword = useDeferredValue(keyword);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedProjectSnapshots, setSelectedProjectSnapshots] = useState<Record<number, Project>>({});
  const [selectedListOpen, setSelectedListOpen] = useState(false);
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
  const [quickConstraint, setQuickConstraint] = useState<ProjectExternalConstraint | null>(null);
  const [quickConstraintList, setQuickConstraintList] = useState<ProjectExternalConstraint[] | null>(null);
  const [quickConstraintFromList, setQuickConstraintFromList] = useState(false);
  const [quickConstraintHasBatchContext, setQuickConstraintHasBatchContext] = useState(false);
  const [quickProjectId, setQuickProjectId] = useState<number | null>(null);
  const [quickProject, setQuickProject] = useState<Project | null>(null);
  const [quickLogs, setQuickLogs] = useState<WorkItemProgressLog[]>([]);
  const [quickConstraintLogs, setQuickConstraintLogs] = useState<ExternalConstraintProgressLog[]>([]);
  const [quickConstraintAction, setQuickConstraintAction] = useState<"clear" | "conclude" | "mark_not_applicable" | "invalidate" | null>(null);
  const [quickConstraintActionText, setQuickConstraintActionText] = useState("");
  const [showAllQuickLogs, setShowAllQuickLogs] = useState(false);
  const [quickProgress, setQuickProgress] = useState("");
  const [quickCompletionResult, setQuickCompletionResult] = useState("");
  const [quickCreateMilestone, setQuickCreateMilestone] = useState(false);
  const [quickCompleting, setQuickCompleting] = useState(false);
  const [quickCompletionDate, setQuickCompletionDate] = useState(today());
  const [quickCompletionNote, setQuickCompletionNote] = useState("");
  const [quickMilestoneName, setQuickMilestoneName] = useState("");
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
  const [batchConstraintAction, setBatchConstraintAction] = useState<"begin" | "progress" | "clear" | "conclude" | "mark_not_applicable" | "invalidate">("begin");
  const [batchConstraintReason, setBatchConstraintReason] = useState("");
  const [batchConstraintPreview, setBatchConstraintPreview] = useState<{ eligible: Array<{ project_id: number; project_code: string; name: string; outcome_kind?: string }>; ineligible: Array<{ project_id: number; name?: string; message: string }> } | null>(null);
  const [batchBudgetOutcomes, setBatchBudgetOutcomes] = useState<Record<number, { approved_budget: string; concluded_on: string; note: string; cleared: boolean; set_effective_budget_source: boolean }>>({});
  const [projectTypes, setProjectTypes] = useState<ProjectTypeDefinition[]>([]);
  const [departmentSettings, setDepartmentSettings] = useState<DepartmentSetting[]>([]);
  const [newClassificationName, setNewClassificationName] = useState("");
  const [newClassificationPrefix, setNewClassificationPrefix] = useState("");
  const [newClassificationOrder, setNewClassificationOrder] = useState("");
  const [templateManager, setTemplateManager] = useState<"items" | "packages" | "constraints" | null>(null);
  const [selectedPackageId, setSelectedPackageId] = useState<number | null>(null);
  const [editingPackage, setEditingPackage] = useState(false);
  const [packageEditName, setPackageEditName] = useState("");
  const [packageEditItems, setPackageEditItems] = useState<WorkItemDraft[]>([]);
  const [draggedPackageItem, setDraggedPackageItem] = useState<number | null>(null);
  const [templateKeyword, setTemplateKeyword] = useState("");
  const [dialog, setDialog] = useState<null | { kind: "edit-log" | "delete-log" | "archive-template"; title: string; value: string; target?: WorkItemProgressLog | ExternalConstraintProgressLog; template?: { kind: "work-item" | "work-package" | "external-constraint"; id: number; name: string } }>(null);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [newProject, setNewProject] = useState({ name: "", department: "", project_manager: "", project_type: "", procurement_nature: "", location: "", budget: "", description: "" });
  const [tableView, setTableView] = useState<"overview" | "stage">("overview");
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const [columnSearch, setColumnSearch] = useState("");
  const [columnBatchTarget, setColumnBatchTarget] = useState<ColumnBatchTarget | null>(null);
  const [columnWorkItemAction, setColumnWorkItemAction] = useState<"progress" | "update" | "complete">("progress");
  const [columnBatchValue, setColumnBatchValue] = useState({ progress_content: "", status: "", planned_date: "", track_as_key_node: "", completed_on: today(), result: "", note: "", create_milestone: false, milestone_name: "" });
  const [columnBatchOverrides, setColumnBatchOverrides] = useState<Record<number, Partial<typeof columnBatchValue>>>({});
  const [columnBatchPreview, setColumnBatchPreview] = useState<{ eligible: Array<{ project_id: number; project_code: string; name: string; work_item_id?: number; constraint_id?: number; outcome_kind?: string }>; ineligible: Array<{ project_id: number; name?: string; message: string }> } | null>(null);
  const [visibleColumnsByStage, setVisibleColumnsByStage] = useState<Record<string, StageColumn[]>>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem("pmo-stage-columns-v2") || "{}") as Record<string, Array<StageColumn | string>>;
      return Object.fromEntries(Object.entries(raw).map(([stage, columns]) => [stage, columns.map((column) => typeof column === "string" ? { kind: "work_item", key: column, label: column } : column)]));
    } catch { return {}; }
  });

  const exportQuery = useMemo(() => {
    const params = new URLSearchParams();
    if (activeGroup && !showRemoved) params.set("group", activeGroup);
    if (showRemoved) params.set("include_deleted", "true");
    if (selectedProjectType) params.set("project_type", selectedProjectType);
    if (selectedDepartment) params.set("department", selectedDepartment);
    if (selectedExternalConditions) params.set("external_conditions", selectedExternalConditions);
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
    selectedDepartment,
    selectedExternalConditions,
    selectedImplementationYear,
    sortBy,
    sortDir,
    deferredKeyword,
    showRemoved,
  ]);

  async function loadDashboard() {
    setLoading(true);
    setError("");
    try {
      const [groupData, summaryData, departmentData, projectData, templateData, packageData, constraintTemplateData, projectTypeData, departmentSettingData] = await Promise.all([
        apiGet<DashboardGroup[]>("/dashboard/groups"),
        apiGet<DashboardSummary>("/dashboard/summary"),
        apiGet<string[]>("/meta/departments"),
        apiGet<ProjectListResponse>("/projects", exportQuery),
        apiGet<WorkItemTemplate[]>("/work-item-templates?include_archived=true"),
        apiGet<WorkPackage[]>("/work-packages?include_archived=true"),
        apiGet<ExternalConstraintTemplate[]>("/external-constraint-templates?include_archived=true"),
        apiGet<ProjectTypeDefinition[]>("/project-types?include_inactive=true"),
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
      setProjectTypes(projectTypeData);
      const activeTypes = projectTypeData.filter((item) => item.is_active);
      setNewProject((current) => current.project_type || !activeTypes.length ? current : { ...current, project_type: activeTypes[0].code });
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
  }, [activeGroup, selectedProjectType, selectedDepartment, selectedExternalConditions, selectedImplementationYear, sortBy, sortDir, deferredKeyword]);

  const selectedProjects = useMemo(
    () => selectedIds.map((id) => selectedProjectSnapshots[id]).filter((project): project is Project => Boolean(project)),
    [selectedIds, selectedProjectSnapshots],
  );
  const selectedEffectiveBudget = useMemo(
    () => selectedProjects.reduce((totalBudget, project) => totalBudget + (project.effective_budget ?? project.budget ?? 0), 0),
    [selectedProjects],
  );

  useEffect(() => {
    setSelectedProjectSnapshots((current) => {
      const next: Record<number, Project> = {};
      for (const id of selectedIds) {
        const snapshot = projects.find((project) => project.id === id) ?? current[id];
        if (snapshot) next[id] = snapshot;
      }
      return next;
    });
  }, [projects, selectedIds]);

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

  function toggleSelection(project: Project) {
    if (columnBatchTarget && !columnBatchTarget.instances[project.id]) return;
    setSelectedIds((current) => current.includes(project.id) ? current.filter((id) => id !== project.id) : [...current, project.id]);
    setSelectedProjectSnapshots((current) => {
      if (current[project.id]) {
        const { [project.id]: _removed, ...remaining } = current;
        return remaining;
      }
      return { ...current, [project.id]: project };
    });
  }

  function handleProjectRowClick(event: MouseEvent<HTMLTableRowElement>, project: Project) {
    const target = event.target as HTMLElement;
    if (target.closest("button,a,input,select,textarea,[role=button],[data-interactive]")) return;
    toggleSelection(project);
  }

  function toggleAllVisible() {
    const selectableProjects = columnBatchTarget ? projects.filter((project) => Boolean(columnBatchTarget.instances[project.id])) : projects;
    const visibleIds = new Set(selectableProjects.map((project) => project.id));
    if (selectableProjects.length > 0 && selectableProjects.every((project) => selectedIds.includes(project.id))) {
      setSelectedIds((current) => current.filter((id) => !visibleIds.has(id)));
      setSelectedProjectSnapshots((current) => Object.fromEntries(Object.entries(current).filter(([id]) => !visibleIds.has(Number(id)))));
      return;
    }
    setSelectedIds((current) => [...new Set([...current, ...selectableProjects.map((project) => project.id)])]);
    setSelectedProjectSnapshots((current) => ({ ...current, ...Object.fromEntries(selectableProjects.map((project) => [project.id, project])) }));
  }

  const activeTemplates = useMemo(() => templates.filter((item) => !item.archived_at), [templates]);
  const activePackages = useMemo(() => packages.filter((item) => !item.archived_at), [packages]);
  const selectedPackage = useMemo(
    () => activePackages.find((item) => item.id === selectedPackageId) ?? null,
    [activePackages, selectedPackageId],
  );
  const activeConstraintTemplates = useMemo(() => constraintTemplates.filter((item) => !item.archived_at), [constraintTemplates]);
  const selectedConstraintTemplate = useMemo(() => activeConstraintTemplates.find((item) => item.id === constraintTemplateId) ?? null, [activeConstraintTemplates, constraintTemplateId]);
  const isBatchBudgetDetermination = batchConstraintAction === "conclude" && selectedConstraintTemplate?.outcome_schema_json?.kind === "budget_determination";

  const recommendedColumns = useMemo<StageColumn[]>(
    () => [...activeTemplates
      .filter((item) => item.recommended_stage === (groups.find((group) => group.key === activeGroup)?.label ?? "") && item.stage_view_priority != null)
      .sort((left, right) => (left.stage_view_priority ?? 999) - (right.stage_view_priority ?? 999))
      .map((item) => ({ kind: "work_item" as const, key: item.name, label: item.name }))
      .slice(0, 7), ...activeConstraintTemplates
      .filter((item) => item.recommended_stage === (groups.find((group) => group.key === activeGroup)?.label ?? ""))
      .map((item) => ({ kind: "external_constraint" as const, key: String(item.id), label: item.name }))],
    [activeGroup, groups, activeTemplates, activeConstraintTemplates],
  );
  const stageColumns = visibleColumnsByStage[activeGroup] ?? recommendedColumns;

  function columnTargetFor(column: StageColumn): ColumnBatchTarget | null {
    const instances: Record<number, number> = {};
    let templateId: number | undefined;
    let outcomeKind: string | undefined;
    for (const project of projects) {
      if (column.kind === "work_item") {
        const aliases: Record<string, string[]> = { "学院流程": ["学院流程", "学院内部流程"], "专家评审": ["专家评审", "小组评审", "校外专家评审"], "委员会": ["委员会", "实验室建设与管理委员会"], "会议": ["会议", "校长办公会", "党委会"] };
        const item = (project.work_item_column_states ?? []).find((candidate) => (aliases[column.key] ?? [column.key]).includes(candidate.name) && candidate.actionable);
        if (item) instances[project.id] = item.id;
      } else {
        const constraint = (project.external_constraint_states ?? []).find((candidate) => constraintMatchesColumn(candidate, column.key)
          && candidate.clearance_status !== "not_applicable" && candidate.handling_status !== "invalidated");
        if (constraint) {
          instances[project.id] = constraint.id;
          templateId ??= constraint.template_id ?? undefined;
          outcomeKind ??= constraint.outcome_kind;
        }
      }
    }
    return Object.keys(instances).length ? { kind: column.kind, key: column.key, label: column.label, instances, templateId, outcomeKind } : null;
  }

  function clearColumnBatchTarget() {
    if (!columnBatchTarget) return;
    setColumnBatchTarget(null);
    setColumnBatchPreview(null);
    setSelectedIds([]);
    setSelectedProjectSnapshots({});
  }

  function selectColumnBatch(column: StageColumn) {
    const target = columnTargetFor(column);
    if (columnBatchTarget?.kind === column.kind && columnBatchTarget.key === column.key) {
      clearColumnBatchTarget();
      return;
    }
    if (!target) { setFeedback("该列当前没有可批量办理的实例。"); return; }
    const targetProjects = projects.filter((project) => Boolean(target.instances[project.id]));
    setColumnBatchTarget(target);
    setSelectedIds(targetProjects.map((project) => project.id));
    setSelectedProjectSnapshots(Object.fromEntries(targetProjects.map((project) => [project.id, project])));
    setColumnBatchPreview(null);
    setRailExpanded(true);
  }
  const currentProjectColumns = useMemo<StageColumn[]>(
    () => [...new Set(projects.flatMap((project) => Object.keys(project.work_item_states ?? {})))].sort((left, right) => left.localeCompare(right, "zh-CN")).map((name) => ({ kind: "work_item" as const, key: name, label: name })),
    [projects],
  );
  const currentConstraintColumns = useMemo<StageColumn[]>(() => {
    const cells = projects.flatMap((project) => project.external_constraint_states ?? []);
    return [...new Map(cells.map((item) => {
      const key = item.template_id != null ? String(item.template_id) : `manual:${encodeURIComponent(item.name)}:${item.outcome_kind || "custom"}`;
      return [key, { kind: "external_constraint" as const, key, label: item.name }];
    })).values()];
  }, [projects]);
  const searchedColumns = useMemo<StageColumn[]>(() => {
    const keyword = columnSearch.trim();
    if (!keyword) return [];
    const items = [...currentProjectColumns, ...currentConstraintColumns, ...activeTemplates.map((item) => ({ kind: "work_item" as const, key: item.name, label: item.name })), ...activeConstraintTemplates.map((item) => ({ kind: "external_constraint" as const, key: String(item.id), label: item.name }))];
    return [...new Map(items.map((item) => [`${item.kind}:${item.key}`, item])).values()]
      .filter((item) => item.label.includes(keyword))
      .filter((item) => !stageColumns.some((column) => column.kind === item.kind && column.key === item.key))
      .slice(0, 8);
  }, [columnSearch, currentProjectColumns, currentConstraintColumns, stageColumns, activeTemplates, activeConstraintTemplates]);

  function saveStageColumns(columns: StageColumn[]) {
    setVisibleColumnsByStage((current) => {
      const result = { ...current, [activeGroup]: columns };
      localStorage.setItem("pmo-stage-columns-v2", JSON.stringify(result));
      return result;
    });
  }

  function addStageColumn(column: StageColumn) {
    if (!stageColumns.some((item) => item.kind === column.kind && item.key === column.key)) saveStageColumns([...stageColumns, column]);
  }

  function removeStageColumn(column: StageColumn) {
    saveStageColumns(stageColumns.filter((item) => item.kind !== column.kind || item.key !== column.key));
  }

  function resetStageColumns() {
    setVisibleColumnsByStage((current) => {
      const { [activeGroup]: _discarded, ...remaining } = current;
      localStorage.setItem("pmo-stage-columns-v2", JSON.stringify(remaining));
      return remaining;
    });
  }

  function closeRail() {
    if (columnBatchTarget) clearColumnBatchTarget();
    setRailExpanded(false);
    setQuickItem(null);
    setQuickConstraint(null);
    setQuickConstraintList(null);
    setQuickConstraintFromList(false);
    setQuickConstraintHasBatchContext(false);
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
    setDraftItems((items) => [...items, { ...emptyDraft(), name: template.name, content: template.default_content || "", execution_mode: template.execution_mode, flow_group: template.flow_group, sequence_rank: template.sequence_rank }]);
  }

  async function openQuickItem(projectId: number, itemId: number) {
    const [items, project, logs] = await Promise.all([
      apiGet<WorkItem[]>("/projects/" + projectId + "/work-items"),
      apiGet<Project>("/projects/" + projectId),
      apiGet<WorkItemProgressLog[]>("/projects/" + projectId + "/work-items/" + itemId + "/progress-logs"),
    ]);
    const item = items.find((entry) => entry.id === itemId) ?? null;
    setQuickConstraint(null); setQuickConstraintList(null); setQuickItem(item); setQuickProjectId(projectId); setQuickProject(project); setQuickLogs(logs); setShowAllQuickLogs(false); setQuickCompletionResult(""); setQuickCreateMilestone(Boolean(item?.completion_rule_snapshot?.effects?.create_milestone)); setRailExpanded(true);
  }

  async function openQuickConstraintList(projectId: number) {
    try {
      const [project, constraints] = await Promise.all([apiGet<Project>(`/projects/${projectId}`), apiGet<ProjectExternalConstraint[]>(`/projects/${projectId}/external-constraints`)]);
      setQuickItem(null); setQuickConstraint(null); setQuickConstraintList(constraints); setQuickConstraintFromList(false); setQuickConstraintHasBatchContext(Boolean(selectedIds.length || columnBatchTarget)); setQuickProjectId(projectId); setQuickProject(project); setRailExpanded(true);
    } catch (err) { setError(err instanceof ApiError ? err.message : "无法载入外部约束。"); }
  }

  async function openQuickConstraint(projectId: number, constraintId: number, fromList = false) {
    try {
      const [project, constraints, logs] = await Promise.all([apiGet<Project>(`/projects/${projectId}`), apiGet<ProjectExternalConstraint[]>(`/projects/${projectId}/external-constraints`), apiGet<ExternalConstraintProgressLog[]>(`/projects/${projectId}/external-constraints/${constraintId}/progress-logs`)]);
      setQuickItem(null); setQuickConstraintList(null); setQuickConstraintFromList(fromList); setQuickConstraintHasBatchContext(Boolean(selectedIds.length || columnBatchTarget)); setQuickConstraint(constraints.find((item) => item.id === constraintId) ?? null); setQuickProjectId(projectId); setQuickProject(project); setQuickConstraintLogs(logs); setQuickProgress(""); setShowAllQuickLogs(false); setQuickConstraintAction(null); setQuickConstraintActionText(""); setRailExpanded(true);
    } catch (err) { setError(err instanceof ApiError ? err.message : "无法载入外部约束。"); }
  }

  async function submitQuickConstraintAction(action: string, extra: Record<string, unknown> = {}) {
    if (!quickConstraint || !quickProjectId) return;
    try {
      const updated = await apiPost<ProjectExternalConstraint>(`/projects/${quickProjectId}/external-constraints/${quickConstraint.id}/actions`, { action, operator, ...extra });
      setQuickConstraint(updated); await refreshProjectRow(quickProjectId); await loadDashboard(); setFeedback("外部约束已更新。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "外部约束未更新，页面保持原状。"); }
  }

  async function addQuickConstraintProgress() {
    if (!quickConstraint || !quickProjectId || !quickProgress.trim()) return;
    try {
      const log = await apiPost<ExternalConstraintProgressLog>(`/projects/${quickProjectId}/external-constraints/${quickConstraint.id}/progress-logs`, { operator, content: quickProgress.trim() });
      setQuickConstraintLogs((current) => [log, ...current]); setQuickProgress(""); await refreshProjectRow(quickProjectId); setFeedback("外部约束进展已记录。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "进展未记录，页面保持原状。"); }
  }

  async function refreshProjectRow(projectId: number) {
    const project = await apiGet<Project>("/projects/" + projectId);
    setProjects((current) => current.map((entry) => entry.id === projectId ? { ...entry, ...project } : entry));
    setSelectedProjectSnapshots((current) => current[projectId] ? { ...current, [projectId]: project } : current);
    setQuickProject(project);
  }

  async function restoreProject() {
    if (!restoreTarget || !restoreReason.trim()) return;
    try {
      const restored = await apiPost<Project>(`/projects/${restoreTarget.id}/restore`, { operator, reason: restoreReason.trim() });
      setProjects((current) => current.filter((project) => project.id !== restored.id));
      setTotal((current) => Math.max(0, current - 1));
      setFeedback(`已恢复“${restored.name}”。`); setRestoreTarget(null); setRestoreReason("");
    } catch (err) { setError(err instanceof ApiError ? err.message : "项目未恢复，页面保持原状。"); }
  }

  async function saveQuickItem() {
    if (!quickItem || !quickProjectId) return;
    try {
      const result = await apiPost<{ work_item: WorkItem; progress_log: WorkItemProgressLog | null }>("/projects/" + quickProjectId + "/work-items/" + quickItem.id + "/quick-update", {
        operator, status: quickItem.status, planned_date: quickItem.planned_date, track_as_key_node: Boolean(quickItem.track_as_key_node), progress_content: quickProgress.trim(),
      });
      setQuickItem(result.work_item);
      if (result.progress_log) setQuickLogs((current) => [result.progress_log!, ...current]);
      setQuickProgress("");
      await refreshProjectRow(quickProjectId);
      setFeedback("本次办理已保存。");
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

  function editQuickConstraintProgress(log: ExternalConstraintProgressLog) { setDialog({ kind: "edit-log", title: "修改外部约束进展", value: log.content, target: log }); }
  function deleteQuickConstraintProgress(log: ExternalConstraintProgressLog) { setDialog({ kind: "delete-log", title: "删除外部约束进展", value: "", target: log }); }

  async function submitDialog() {
    if (!dialog) return;
    try {
      if (dialog.kind === "edit-log" && quickItem && quickProjectId && dialog.target && dialog.value.trim()) {
        const updated = await apiPatch<WorkItemProgressLog>(`/projects/${quickProjectId}/work-items/${quickItem.id}/progress-logs/${dialog.target.id}`, { operator, content: dialog.value.trim(), is_timeline_highlight: (dialog.target as WorkItemProgressLog).is_timeline_highlight });
        setQuickLogs((logs) => logs.map((entry) => entry.id === updated.id ? updated : entry));
      } else if (dialog.kind === "delete-log" && quickItem && quickProjectId && dialog.target && dialog.value.trim()) {
        await apiDelete<{ success: boolean }>(`/projects/${quickProjectId}/work-items/${quickItem.id}/progress-logs/${dialog.target.id}`, { operator, reason: dialog.value.trim() });
        setQuickLogs((logs) => logs.filter((entry) => entry.id !== dialog.target!.id));
      } else if (dialog.kind === "edit-log" && quickConstraint && quickProjectId && dialog.target && dialog.value.trim()) {
        const updated = await apiPatch<ExternalConstraintProgressLog>(`/projects/${quickProjectId}/external-constraints/${quickConstraint.id}/progress-logs/${dialog.target.id}`, { operator, content: dialog.value.trim() });
        setQuickConstraintLogs((logs) => logs.map((entry) => entry.id === updated.id ? updated : entry));
      } else if (dialog.kind === "delete-log" && quickConstraint && quickProjectId && dialog.target && dialog.value.trim()) {
        await apiDelete<{ success: boolean }>(`/projects/${quickProjectId}/external-constraints/${quickConstraint.id}/progress-logs/${dialog.target.id}`, { operator, reason: dialog.value.trim() });
        setQuickConstraintLogs((logs) => logs.filter((entry) => entry.id !== dialog.target!.id));
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
        operator, result: quickCompletionResult.trim() || "已完成", completed_on: quickCompletionDate, note: quickCompletionNote.trim(), create_milestone: requiredMilestone || quickCreateMilestone, milestone_name: effects?.milestone_name || quickMilestoneName || quickItem.name,
      });
      setQuickItem(updated); setQuickCompleting(false); await refreshProjectRow(quickProjectId); setFeedback("事项已完成并写入项目历史。");
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

  async function addProjectClassification() {
    if (!newClassificationName.trim() || !newClassificationPrefix.trim()) { setError("请填写分类名称和编号前缀。"); return; }
    try {
      await apiPost("/project-types", { name: newClassificationName.trim(), code_prefix: newClassificationPrefix.trim(), sort_order: newClassificationOrder ? Number(newClassificationOrder) : null, operator });
      setNewClassificationName(""); setNewClassificationPrefix(""); setNewClassificationOrder(""); await loadDashboard(); setFeedback("已新增项目分类。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "新增项目分类失败"); }
  }

  async function saveDepartmentOrder(department: string, order: string) {
    try {
      await apiPatch(`/meta/departments/${encodeURIComponent(department)}/order`, { sort_order: Number(order), operator });
      await loadDashboard(); setFeedback(`已更新“${department}”的部门排序。`);
    } catch (err) { setError(err instanceof ApiError ? err.message : "部门排序保存失败"); }
  }

  async function saveProjectClassification(item: ProjectTypeDefinition, updates: Partial<ProjectTypeDefinition>) {
    try {
      await apiPatch(`/project-types/${item.id}`, { ...updates, operator });
      await loadDashboard(); setFeedback(`已更新项目分类“${item.name}”。`);
    } catch (err) { setError(err instanceof ApiError ? err.message : "项目分类未更新，页面保持原状。"); }
  }

  async function submitAdvancement() {
    if (!selectedIds.length || !comment.trim()) { setError("纳入推进需要选择项目并填写理由。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ success: number }>("/projects/batch-include-in-advancement", {
        project_ids: selectedIds, operator, reason: comment, advancement_year: Number(advancementYear),
      });
      await refreshSelectedProjects(); setFeedback(`已将 ${result.success} 个项目纳入年度推进。当前视图保持不变，可切换查看推进中项目。`); setComment("");
    } catch (err) { setError(err instanceof ApiError ? err.message : "纳入推进失败"); }
    finally { setExecuting(false); }
  }

  async function submitDeferAdvancement() {
    if (!selectedIds.length || !comment.trim()) { setError("暂缓推进需要选择项目并填写原因。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ success: number }>("/projects/batch-defer-advancement", { project_ids: selectedIds, operator, reason: comment });
      await refreshSelectedProjects(); setFeedback(`已暂缓 ${result.success} 个项目的本年度推进。当前视图保持不变，可切换查看未实施项目。`); setComment("");
    } catch (err) { setError(err instanceof ApiError ? err.message : "暂缓推进失败"); }
    finally { setExecuting(false); }
  }

  async function submitEarlyPreparation() {
    if (!selectedIds.length || !comment.trim() || !earlyApprovalBasis.trim()) { setError("提前推进准备需要填写理由和审批依据。"); return; }
    setExecuting(true); setError("");
    try {
      await Promise.all(selectedIds.map((id) => apiPost(`/projects/${id}/special-include-in-advancement`, { operator, reason: comment, approval_basis: earlyApprovalBasis, advancement_year: Number(advancementYear) })));
      await refreshSelectedProjects(); setFeedback(`已特批纳入 ${selectedIds.length} 个未立项项目的前期推进管理。当前视图保持不变。`); setComment(""); setEarlyApprovalBasis("");
    } catch (err) { setError(err instanceof ApiError ? err.message : "特批纳入推进失败"); }
    finally { setExecuting(false); }
  }

  async function refreshSelectedProjects(projectIds = selectedIds) {
    const refreshed = await Promise.all(projectIds.map((id) => apiGet<Project>(`/projects/${id}`)));
    setProjects((current) => current.map((project) => refreshed.find((item) => item.id === project.id) ?? project));
    const [nextGroups, nextSummary] = await Promise.all([apiGet<DashboardGroup[]>("/dashboard/groups"), apiGet<DashboardSummary>("/dashboard/summary")]);
    setGroups(nextGroups); setSummary(nextSummary);
  }

  const advancementAction = !selectedProjects.length ? "none"
    : selectedProjects.every((project) => ["active", "special_active"].includes(project.advancement?.status || "none")) ? "defer"
      : selectedProjects.every((project) => project.stage === "项目库—未实施" && project.advancement?.status === "none") ? "include"
        : selectedProjects.every((project) => project.stage === "未立项" && project.advancement?.status === "none") ? "special"
          : "invalid";

  async function submitPackage() {
    if (!selectedIds.length || !selectedPackageId) { setError("请选择项目和工作包。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ created_count: number }>("/projects/apply-work-package", { project_ids: selectedIds, package_id: selectedPackageId, operator });
      setFeedback(`已从工作包下发 ${result.created_count} 条事项。`); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "工作包下发失败"); }
    finally { setExecuting(false); }
  }

  async function previewBatchConstraintAction() {
    if (!selectedIds.length || !constraintTemplateId) { setError("请选择项目和同一外部约束模板。 "); return; }
    try {
      const preview = await apiPost<typeof batchConstraintPreview>("/projects/batch-external-constraint-actions/preflight", { project_ids: selectedIds, template_id: constraintTemplateId, action: batchConstraintAction, operator });
      setBatchConstraintPreview(preview);
      if (preview && isBatchBudgetDetermination) {
        setBatchBudgetOutcomes(Object.fromEntries((preview?.eligible ?? []).map((item) => [item.project_id, { approved_budget: "", concluded_on: today(), note: "", cleared: true, set_effective_budget_source: true }])));
      }
    } catch (err) { setError(err instanceof ApiError ? err.message : "批量预检失败。"); }
  }

  async function submitBatchConstraintAction() {
    if (!selectedIds.length || (!constraintTemplateId && !columnBatchTarget)) return;
    const activePreview = columnBatchTarget?.kind === "external_constraint" ? columnBatchPreview : batchConstraintPreview;
    const budgetDetermination = isBatchBudgetDetermination || (columnBatchTarget?.kind === "external_constraint" && columnBatchTarget.outcomeKind === "budget_determination");
    if (["clear", "mark_not_applicable", "invalidate"].includes(batchConstraintAction) && !batchConstraintReason.trim()) { setError("请填写原因或说明。"); return; }
    if (["progress", "conclude"].includes(batchConstraintAction) && !budgetDetermination && !batchConstraintReason.trim()) { setError(batchConstraintAction === "progress" ? "请填写共同进展。" : "请填写共同结论。"); return; }
    if (budgetDetermination && activePreview?.eligible.some((item) => !batchBudgetOutcomes[item.project_id]?.approved_budget.trim())) { setError("请逐个填写每个项目的核定预算。"); return; }
    try {
      await apiPost("/projects/batch-external-constraint-actions", { project_ids: selectedIds, targets: columnBatchTarget?.kind === "external_constraint" ? columnTargetsPayload() : undefined, template_id: constraintTemplateId ?? undefined, name: columnBatchTarget && !columnBatchTarget.templateId ? columnBatchTarget.label : undefined, outcome_kind: columnBatchTarget?.outcomeKind, action: batchConstraintAction, operator, reason: batchConstraintReason.trim(), content: batchConstraintAction === "progress" ? batchConstraintReason.trim() : undefined, outcome: batchConstraintAction === "conclude" && !budgetDetermination ? { result: batchConstraintReason.trim() } : undefined, concluded_on: batchConstraintAction === "conclude" && !budgetDetermination ? today() : undefined, project_outcomes: budgetDetermination ? activePreview?.eligible.map((item) => {
        const value = batchBudgetOutcomes[item.project_id];
        return { project_id: item.project_id, outcome: { approved_budget: Number(value.approved_budget), note: value.note }, concluded_on: value.concluded_on || today(), cleared: value.cleared, set_effective_budget_source: value.set_effective_budget_source };
      }) : undefined });
      setBatchConstraintPreview(null); setBatchConstraintReason(""); setBatchBudgetOutcomes({}); await refreshSelectedProjects(); setFeedback("批量外部约束办理已完成，并已写入逐项目审计。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "批量办理未执行，项目保持原状。"); }
  }

  function columnTargetsPayload() {
    return selectedIds.map((projectId) => ({ project_id: projectId, [columnBatchTarget?.kind === "work_item" ? "work_item_id" : "constraint_id"]: columnBatchTarget?.instances[projectId] })).filter((item) => Object.values(item).every(Boolean));
  }

  function columnWorkItemDefaults() {
    return columnWorkItemAction === "progress" ? { progress_content: columnBatchValue.progress_content }
      : columnWorkItemAction === "update" ? {
        status: columnBatchValue.status || undefined,
        planned_date: columnBatchValue.planned_date || undefined,
        ...(columnBatchValue.track_as_key_node === "" ? {} : { track_as_key_node: columnBatchValue.track_as_key_node === "true" }),
      }
        : { completed_on: columnBatchValue.completed_on || today(), result: columnBatchValue.result, note: columnBatchValue.note, create_milestone: columnBatchValue.create_milestone, milestone_name: columnBatchValue.milestone_name };
  }

  async function previewColumnBatch() {
    if (!columnBatchTarget || !selectedIds.length) { setError("请先从阶段跟踪选择可办理列。 "); return; }
    const path = columnBatchTarget.kind === "work_item" ? "/projects/batch-work-item-actions/preflight" : "/projects/batch-external-constraint-actions/preflight";
    const action = columnBatchTarget.kind === "work_item" ? columnWorkItemAction : batchConstraintAction;
    try {
      const defaults = columnBatchTarget.kind === "work_item" ? columnWorkItemDefaults() : undefined;
      const payload = { project_ids: selectedIds, targets: columnTargetsPayload(), action, operator, defaults, overrides: columnBatchTarget.kind === "work_item" ? columnBatchOverrides : undefined, template_id: columnBatchTarget.templateId, name: columnBatchTarget.templateId ? undefined : columnBatchTarget.label, outcome_kind: columnBatchTarget.outcomeKind };
      const preview = await apiPost<typeof columnBatchPreview>(path, payload);
      setColumnBatchPreview(preview);
      if (columnBatchTarget.kind === "external_constraint" && columnBatchTarget.outcomeKind === "budget_determination") {
        setBatchBudgetOutcomes(Object.fromEntries((preview?.eligible ?? []).map((item) => [item.project_id, { approved_budget: "", concluded_on: today(), note: "", cleared: true, set_effective_budget_source: true }])));
      }
    } catch (err) { setError(err instanceof ApiError ? err.message : "批量预检失败。"); }
  }

  async function executeColumnWorkItemBatch() {
    if (!columnBatchTarget || columnBatchTarget.kind !== "work_item" || !columnBatchPreview || columnBatchPreview.ineligible.length) return;
    const defaults = columnWorkItemDefaults();
    if (columnWorkItemAction === "progress" && !columnBatchValue.progress_content.trim()) { setError("请填写共同进展。 "); return; }
    if (columnWorkItemAction === "update" && !columnBatchValue.status && !columnBatchValue.planned_date && columnBatchValue.track_as_key_node === "") { setError("请至少填写一项要更新的事项设置。 "); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ processed_targets: Array<{ project_id: number }> }>("/projects/batch-work-item-actions", { project_ids: selectedIds, targets: columnTargetsPayload(), action: columnWorkItemAction, operator, defaults, overrides: columnBatchOverrides });
      await refreshSelectedProjects(result.processed_targets.map((target) => target.project_id)); setColumnBatchPreview(null); setFeedback("批量事项办理已完成，并已写入批量与逐项目审计。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "批量事项办理失败，项目保持原状。"); }
    finally { setExecuting(false); }
  }

  function startEditingPackage() {
    if (!selectedPackage) return;
    setPackageEditName(selectedPackage.name);
    setPackageEditItems(selectedPackage.items.map((item) => ({ ...item })));
    setEditingPackage(true);
  }

  async function savePackageEdits() {
    if (!selectedPackage || !packageEditName.trim() || packageEditItems.some((item) => !item.name.trim())) return;
    try {
      await apiPatch(`/work-packages/${selectedPackage.id}`, { operator, name: packageEditName.trim(), items: packageEditItems });
      setEditingPackage(false);
      await loadDashboard();
      setFeedback(`已更新工作包“${packageEditName.trim()}”；已下发到项目的事项不受影响。`);
    } catch (err) { setError(err instanceof ApiError ? err.message : "工作包未更新，既有项目事项保持不变。"); }
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
        project_type: newProject.project_type, procurement_nature: newProject.procurement_nature, location: newProject.location.trim(), budget: Number(newProject.budget || 0), description: newProject.description.trim(), operator,
      });
      setNewProjectOpen(false);
      setNewProject({ name: "", department: "", project_manager: "", project_type: projectTypes.find((item) => item.is_active)?.code || "", procurement_nature: "", location: "", budget: "", description: "" });
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
            外部条件待处理：{summary?.external_conditions_ongoing_count ?? 0} 个项目 · 涉及预算 {formatCurrency(summary?.external_conditions_ongoing_effective_budget)} 万
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
                  {group.key === "pool_active" ? <small className="group-note">含特批未立项项目</small> : null}
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
                  <option value="">全部项目分类</option>
                  {projectTypes.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.code}>{item.name}</option>)}
                </select>
                <select className="select" value={showRemoved ? "removed" : "active"} onChange={(event) => { setShowRemoved(event.target.value === "removed"); setSelectedIds([]); }}>
                  <option value="active">日常项目</option><option value="removed">已移除项目</option>
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
              <div className="table-tools">
                <button className={`mini-button ${tableView === "overview" ? "active" : ""}`} onClick={() => { clearColumnBatchTarget(); setTableView("overview"); setColumnPickerOpen(false); }}>总览</button>
                <button className={`mini-button ${tableView === "stage" ? "active" : ""}`} onClick={() => setTableView("stage")}>阶段跟踪</button>
                {tableView === "stage" ? <div className="column-picker"><button type="button" className="mini-button" aria-expanded={columnPickerOpen} onClick={() => setColumnPickerOpen((open) => !open)}>显示列</button>{columnPickerOpen ? <div className="column-picker-menu" role="dialog" aria-label="配置阶段跟踪显示列">
                  <div className="column-picker-heading"><strong>显示列</strong><button type="button" className="text-button" onClick={() => setColumnPickerOpen(false)}>关闭</button></div>
                  <p>只影响当前工作台视图，不会创建事项。</p>
                  <section><span>已显示（拖动调整顺序）</span><div className="column-chip-list">{stageColumns.map((column, index) => <button type="button" draggable key={`${column.kind}:${column.key}`} onDragStart={(event) => event.dataTransfer.setData("text/plain", String(index))} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const from = Number(event.dataTransfer.getData("text/plain")); if (Number.isInteger(from) && from !== index) { const next = [...stageColumns]; const [moved] = next.splice(from, 1); next.splice(index, 0, moved); saveStageColumns(next); } }} onClick={() => removeStageColumn(column)}><span className="drag-handle">⋮⋮</span>{column.kind === "external_constraint" ? "约束 · " : "事项 · "}{column.label} <b>×</b></button>)}{!stageColumns.length ? <small>暂无显示列</small> : null}</div></section>
                  <section><span>推荐列</span><div className="column-action-list">{recommendedColumns.filter((column) => !stageColumns.some((item) => item.kind === column.kind && item.key === column.key)).map((column) => <button type="button" key={`${column.kind}:${column.key}`} onClick={() => addStageColumn(column)}>＋ {column.kind === "external_constraint" ? "约束 · " : ""}{column.label}</button>)}{!recommendedColumns.filter((column) => !stageColumns.some((item) => item.kind === column.kind && item.key === column.key)).length ? <small>已全部加入</small> : null}</div></section>
                <section><span>当前结果中存在</span><div className="column-action-list">{[...currentConstraintColumns, ...currentProjectColumns].filter((column) => !stageColumns.some((item) => item.kind === column.kind && item.key === column.key) && !recommendedColumns.some((item) => item.kind === column.kind && item.key === column.key)).slice(0, 8).map((column) => <button type="button" key={`${column.kind}:${column.key}`} onClick={() => addStageColumn(column)}>＋ {column.kind === "external_constraint" ? "约束 · " : ""}{column.label}</button>)}</div></section>
                  <label className="column-search"><span>搜索其他常用事项</span><input className="input" value={columnSearch} onChange={(event) => setColumnSearch(event.target.value)} placeholder="输入事项名称" /></label>
                  {columnSearch.trim() ? <div className="column-action-list search-results">{searchedColumns.map((column) => <button type="button" key={`${column.kind}:${column.key}`} onClick={() => addStageColumn(column)}>＋ {column.kind === "external_constraint" ? "约束 · " : ""}{column.label}</button>)}{!searchedColumns.length ? <small>未找到可添加的事项或约束</small> : null}</div> : null}
                  <button type="button" className="text-button column-reset" onClick={resetStageColumns}>恢复默认推荐列</button>
                </div> : null}</div> : null}
                <button className="mini-button" onClick={toggleAllVisible}>
                  {projects.length && projects.every((project) => selectedIds.includes(project.id)) ? "取消全选" : "全选当前结果"}
                </button>
                <button className="mini-button active" onClick={() => setNewProjectOpen(true)}><Plus size={15} />新增项目</button>
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
                      {tableView === "overview" ? <th>推进情况</th> : stageColumns.map((column) => {
                        const active = columnBatchTarget?.kind === column.kind && columnBatchTarget.key === column.key;
                        const available = Boolean(columnTargetFor(column));
                        return <th key={`${column.kind}:${column.key}`} className={active ? "column-batch-header" : ""}><span>{column.kind === "external_constraint" ? "约束 · " : "事项 · "}{column.label}</span><button type="button" className="column-select-button" disabled={!available} aria-label={`选择“${column.label}”列进行批量办理`} aria-pressed={active} onClick={() => selectColumnBatch(column)}><b aria-hidden="true">{active ? "✓" : "◎"}</b></button></th>;
                      })}
                      <th>
                        <button className="sort-button" onClick={() => toggleSort("department")}>
                          部门 / 负责人 {sortLabel("department")}
                        </button>
                      </th>
                      <th>预算</th>
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
                        <tr key={project.id} className={selected && !columnBatchTarget ? "selected" : ""} onClick={(event) => handleProjectRowClick(event, project)}>
                          <td>
                            <label className="check-pill">
                              <input
                                type="checkbox"
                                checked={selected}
                                disabled={Boolean(columnBatchTarget && !columnBatchTarget.instances[project.id])}
                                onChange={() => toggleSelection(project)}
                              />
                              <span />
                            </label>
                          </td>
                          <td>
                            <div className="project-cell">
                              {showRemoved ? <strong title={project.name}>{project.name}</strong> : <Link className="project-link" title={project.name} to={`/projects/${project.id}`}>{project.name}</Link>}
                              <span>{project.project_code}</span>
                              <small>{project.project_summary_display || "未分类"}</small>
                              {showRemoved ? <button className="text-button" onClick={() => setRestoreTarget(project)}>恢复项目</button> : null}
                            </div>
                          </td>
                          <td>
                            <div className="stage-cell"><strong>{project.stage || "未归属"}</strong>{project.advancement?.status === "special_active" ? <small className="special-advancement">特批推进中</small> : null}</div>
                          </td>
                          {tableView === "overview" ? <td><ProgressSituation project={project} onSelect={(itemId) => void openQuickItem(project.id, itemId)} onConstraintSelect={() => void openQuickConstraintList(project.id)} /></td> : stageColumns.map((column) => {
                            const columnSelected = Boolean(selected && columnBatchTarget?.kind === column.kind && columnBatchTarget.key === column.key && columnBatchTarget.instances[project.id]);
                            return <td key={`${column.kind}:${column.key}`} className={columnSelected ? "column-batch-cell" : ""}><StageItemCell project={project} column={column} highlighted={columnSelected} onWorkItemSelect={(itemId) => void openQuickItem(project.id, itemId)} onConstraintSelect={(constraintId) => void openQuickConstraint(project.id, constraintId)} /></td>;
                          })}
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
                              <small>{project.effective_budget_source === "budget_constraint" ? "来源：预算核定" : project.effective_budget_source === "historical_review" ? "来源：历史审核" : "来源：初始预算"}</small>
                            </div>
                          </td>
                          <td className="updated-date">{formatDate(project.status_updated_at)}</td>
                        </tr>
                      );
                    })}
                    {!projects.length ? <tr><td className="project-table-empty" colSpan={tableView === "overview" ? 7 : stageColumns.length + 6}>当前条件下暂无项目</td></tr> : null}
                  </tbody>
                </table>
              )}
            </div>
          </section>

        </section>

        <aside className="control-rail">
          {railExpanded ? <button type="button" className="rail-scrim" aria-label="收起操作台" onClick={closeRail} /> : null}
          <div className={`rail-card operation-console ${railExpanded ? "is-expanded" : ""}`}>
            <button className="rail-toggle" type="button" onClick={() => railExpanded ? closeRail() : setRailExpanded(true)} aria-label={railExpanded ? "收起操作台" : "展开批量操作"}>{railExpanded ? "×" : "☰"}</button>
            <p className="section-kicker">PMO ACTIONS</p>
            <h3>{quickItem || quickConstraint || quickConstraintList ? "快速办理" : columnBatchTarget ? "阶段跟踪批量办理" : "批量操作"}</h3>
            {!quickItem && !quickConstraint && !quickConstraintList ? <div className="selection-summary">
              <span>当前已选</span>
              <strong>{selectedIds.length}</strong>
              <small>有效预算合计 {formatCurrency(selectedEffectiveBudget)} 万</small>
              <button type="button" className="text-button" disabled={!selectedIds.length} onClick={() => setSelectedListOpen((open) => !open)}>{selectedListOpen ? "收起已选项目" : "查看已选项目"}</button>
              {selectedListOpen ? <div className="selected-project-list">
                {selectedProjects.map((project) => <article key={project.id}><div><strong>{project.name}</strong><small>{project.project_code} · 有效 {formatCurrency(project.effective_budget ?? project.budget)} 万</small></div><button type="button" className="text-button" onClick={() => toggleSelection(project)}>取消选中</button></article>)}
              </div> : null}
            </div> : null}
            {!quickItem && !quickConstraint && !quickConstraintList && !columnBatchTarget ? <div className="operation-tabs">
              {([ ["advance", "推进管理"], ["stage", "调整 Stage"], ["items", "添加事项"], ["package", "应用工作包"], ["constraints", "外部约束"], ["config", "基础配置"], ["batch", "加入批次"] ] as const).map(([mode, label]) => <button key={mode} disabled={mode === "batch"} className={operationMode === mode ? "active" : ""} onClick={() => { setOperationMode(mode); setRailExpanded(true); }}>{label}{mode === "batch" ? " · 后续" : ""}</button>)}
            </div> : null}
            <div className="operation-body">
              {columnBatchTarget ? <section className="column-batch-panel">
                <div className="quick-panel-heading"><strong>阶段跟踪批量办理</strong><button type="button" className="text-button" onClick={clearColumnBatchTarget}>取消列选择</button></div>
                <p className="operation-lead">{columnBatchTarget.kind === "work_item" ? "事项" : "约束"} · <strong>{columnBatchTarget.label}</strong>，已选 {selectedIds.length} 个实际存在的实例。</p>
                <label className="field"><span>操作人</span><input className="input" value={operator} onChange={(event) => setOperator(event.target.value)} /></label>
                {columnBatchTarget.kind === "work_item" ? <>
                  <label className="field"><span>办理动作</span><select className="select" value={columnWorkItemAction} onChange={(event) => { setColumnWorkItemAction(event.target.value as typeof columnWorkItemAction); setColumnBatchPreview(null); }}><option value="progress">添加共同进展</option><option value="update">修改事项设置</option><option value="complete">完成事项</option></select></label>
                  {columnWorkItemAction === "progress" ? <label className="field"><span>共同进展</span><textarea className="textarea" rows={3} value={columnBatchValue.progress_content} onChange={(event) => setColumnBatchValue((current) => ({ ...current, progress_content: event.target.value }))} /></label> : null}
                  {columnWorkItemAction === "update" ? <div className="field-grid"><label className="field"><span>当前状态</span><select className="select" value={columnBatchValue.status} onChange={(event) => setColumnBatchValue((current) => ({ ...current, status: event.target.value }))}><option value="">不修改</option><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option><option value="paused">暂停</option></select></label><label className="field"><span>计划日期</span><input className="input" type="date" value={columnBatchValue.planned_date} onChange={(event) => setColumnBatchValue((current) => ({ ...current, planned_date: event.target.value }))} /></label><label className="field"><span>总览重点关注</span><select className="select" value={columnBatchValue.track_as_key_node} onChange={(event) => setColumnBatchValue((current) => ({ ...current, track_as_key_node: event.target.value }))}><option value="">不修改</option><option value="true">设为重点关注</option><option value="false">取消重点关注</option></select></label></div> : null}
                  {columnWorkItemAction === "complete" ? <div className="field-grid"><label className="field"><span>完成日期</span><input className="input" type="date" value={columnBatchValue.completed_on} onChange={(event) => setColumnBatchValue((current) => ({ ...current, completed_on: event.target.value }))} /></label><label className="field"><span>完成结果</span><input className="input" value={columnBatchValue.result} onChange={(event) => setColumnBatchValue((current) => ({ ...current, result: event.target.value }))} /></label><label className="field"><span>完成说明</span><input className="input" value={columnBatchValue.note} onChange={(event) => setColumnBatchValue((current) => ({ ...current, note: event.target.value }))} /></label><label className="toggle"><input type="checkbox" checked={columnBatchValue.create_milestone} onChange={(event) => setColumnBatchValue((current) => ({ ...current, create_milestone: event.target.checked }))} /><span>记入里程碑</span></label>{columnBatchValue.create_milestone ? <label className="field"><span>里程碑名称</span><input className="input" value={columnBatchValue.milestone_name} onChange={(event) => setColumnBatchValue((current) => ({ ...current, milestone_name: event.target.value }))} /></label> : null}</div> : null}
                </> : <>
                  <label className="field"><span>办理动作</span><select className="select" value={batchConstraintAction} onChange={(event) => { setBatchConstraintAction(event.target.value as typeof batchConstraintAction); setColumnBatchPreview(null); }}><option value="begin">开始办理</option><option value="progress">记录共同进展</option><option value="conclude">登记共同结论</option><option value="clear">解除约束</option><option value="mark_not_applicable">标记不适用</option><option value="invalidate">使结论失效</option></select></label>
                  {batchConstraintAction !== "begin" ? <label className="field"><span>{batchConstraintAction === "progress" ? "共同进展" : batchConstraintAction === "conclude" ? "共同结论" : "原因或说明"}</span><textarea className="textarea" rows={2} value={batchConstraintReason} onChange={(event) => setBatchConstraintReason(event.target.value)} /></label> : null}
                </>}
                <button className="mini-button" disabled={!selectedIds.length} onClick={() => void previewColumnBatch()}>预检批量办理</button>
                {columnBatchPreview ? <div className="operation-preview"><strong>可办理 {columnBatchPreview.eligible.length} 个</strong>{columnBatchPreview.ineligible.length ? <small>不可办理：{columnBatchPreview.ineligible.map((item) => item.name || item.project_id).join("、")}</small> : <small>全部项目符合条件</small>}{columnBatchTarget.kind === "work_item" ? <details className="batch-overrides"><summary>项目级覆盖（可选）</summary>{columnBatchPreview.eligible.map((item) => { const value = columnBatchOverrides[item.project_id] ?? {}; const update = (patch: Partial<typeof columnBatchValue>) => setColumnBatchOverrides((current) => ({ ...current, [item.project_id]: { ...value, ...patch } })); return <fieldset key={item.project_id}><legend>{item.name} · {item.project_code}</legend>{columnWorkItemAction === "progress" ? <label className="field"><span>项目进展</span><input className="input" value={value.progress_content ?? ""} placeholder="留空使用共同进展" onChange={(event) => update({ progress_content: event.target.value })} /></label> : null}{columnWorkItemAction === "update" ? <div className="field-grid"><label className="field"><span>状态</span><select className="select" value={value.status ?? ""} onChange={(event) => update({ status: event.target.value })}><option value="">使用公共值</option><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option><option value="paused">暂停</option></select></label><label className="field"><span>计划日期</span><input className="input" type="date" value={value.planned_date ?? ""} onChange={(event) => update({ planned_date: event.target.value })} /></label></div> : null}{columnWorkItemAction === "complete" ? <div className="field-grid"><label className="field"><span>完成日期</span><input className="input" type="date" value={value.completed_on ?? ""} onChange={(event) => update({ completed_on: event.target.value })} /></label><label className="field"><span>完成结果</span><input className="input" value={value.result ?? ""} onChange={(event) => update({ result: event.target.value })} /></label><label className="field"><span>完成说明</span><input className="input" value={value.note ?? ""} onChange={(event) => update({ note: event.target.value })} /></label></div> : null}</fieldset>; })}</details> : null}{columnBatchTarget.kind === "external_constraint" && columnBatchTarget.outcomeKind === "budget_determination" && batchConstraintAction === "conclude" ? <div className="batch-budget-outcomes">{columnBatchPreview.eligible.map((item) => { const value = batchBudgetOutcomes[item.project_id] ?? { approved_budget: "", concluded_on: today(), note: "", cleared: true, set_effective_budget_source: true }; const update = (patch: Partial<typeof value>) => setBatchBudgetOutcomes((current) => ({ ...current, [item.project_id]: { ...value, ...patch } })); return <fieldset key={item.project_id}><legend>{item.name} · {item.project_code}</legend><label className="field"><span>核定预算（万元）</span><input className="input" type="number" min="0" value={value.approved_budget} onChange={(event) => update({ approved_budget: event.target.value })} /></label><label className="field"><span>结论日期</span><input className="input" type="date" value={value.concluded_on} onChange={(event) => update({ concluded_on: event.target.value })} /></label><label className="field"><span>说明</span><input className="input" value={value.note} onChange={(event) => update({ note: event.target.value })} /></label><label className="toggle"><input type="checkbox" checked={value.cleared} onChange={(event) => update({ cleared: event.target.checked })} /><span>解除阻断</span></label><label className="toggle"><input type="checkbox" checked={value.set_effective_budget_source} onChange={(event) => update({ set_effective_budget_source: event.target.checked })} /><span>设为当前有效预算</span></label></fieldset>; })}</div> : null}{columnBatchTarget.kind === "work_item" ? <button className="action-button primary full" disabled={Boolean(columnBatchPreview.ineligible.length) || executing} onClick={() => void executeColumnWorkItemBatch()}>确认批量办理</button> : <button className="action-button primary full" disabled={Boolean(columnBatchPreview.ineligible.length) || executing} onClick={() => void submitBatchConstraintAction()}>确认批量办理</button>}</div> : null}
              </section> : quickItem ? <section className="quick-panel">
                <button type="button" className="quick-return" onClick={() => { setQuickItem(null); setQuickProjectId(null); setQuickProject(null); }}>← 返回批量操作</button>
                <div className="quick-context"><span>当前项目</span><strong>{quickProject?.name || "项目"}</strong><small>{quickProject?.project_code}</small><div><b>{quickItem.name}</b><em>{workStatusLabel(quickItem.status)}</em></div></div>
                <section className="quick-group"><div className="quick-panel-heading"><strong>本次进展</strong><span>记录这次发生了什么</span></div>
                  <div className="quick-log-list">{(showAllQuickLogs ? quickLogs : quickLogs.slice(0, 3)).map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDate(log.created_at)} · {log.operator}</small><div className="log-actions"><button className="text-button" onClick={() => void editQuickProgress(log)}>编辑</button><button className="text-button" onClick={() => void deleteQuickProgress(log)}>删除</button></div></article>)}</div>
                  {!quickLogs.length ? <p className="muted-copy">暂无进展记录</p> : null}
                  {quickLogs.length > 3 ? <button className="text-button" onClick={() => setShowAllQuickLogs((value) => !value)}>{showAllQuickLogs ? "收起进展记录" : "查看全部进展记录"}</button> : null}
                  <textarea className="textarea" rows={3} value={quickProgress} onChange={(event) => setQuickProgress(event.target.value)} placeholder="今天有什么变化？" />
                  <button className="mini-button" onClick={() => void addQuickProgress()}>仅记录进展</button>
                </section>
                <section className="quick-group"><div className="quick-panel-heading"><strong>事项设置</strong><span>修改这个事项的当前状态和计划</span></div>
                  <div className="quick-fields"><label className="field"><span>当前状态</span><select className="select" value={quickItem.status} onChange={(event) => setQuickItem((item) => item ? { ...item, status: event.target.value } : item)}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option><option value="paused">暂停</option><option value="not_applicable">不适用</option></select></label><label className="field"><span>计划日期</span><input className="input" type="date" value={quickItem.planned_date} onChange={(event) => setQuickItem((item) => item ? { ...item, planned_date: event.target.value } : item)} /></label></div>
                  <label className="toggle"><input type="checkbox" checked={Boolean(quickItem.track_as_key_node)} onChange={(event) => setQuickItem((item) => item ? { ...item, track_as_key_node: event.target.checked } : item)} /><span>☆ 重点关注</span></label>
                </section>
                {quickCompleting ? <section className="quick-complete-form">
                  <div className="quick-complete-heading"><strong>完成事项</strong><small>记录完成事实；里程碑为可选治理结果。</small></div>
                  <div className="quick-complete-info">
                    <label className="field"><span>完成结果</span><input className="input" value={quickCompletionResult} onChange={(event) => setQuickCompletionResult(event.target.value)} placeholder="可选" /></label>
                    <label className="field"><span>完成日期</span><input className="input" type="date" value={quickCompletionDate} onChange={(event) => setQuickCompletionDate(event.target.value)} /></label>
                    <label className="field quick-complete-note"><span>完成说明</span><textarea className="textarea" rows={2} value={quickCompletionNote} onChange={(event) => setQuickCompletionNote(event.target.value)} placeholder="可选" /></label>
                  </div>
                  <div className="quick-milestone-group">
                    <label className="toggle"><input type="checkbox" checked={quickCreateMilestone} disabled={Boolean(quickItem.completion_rule_snapshot?.effects?.create_milestone && quickItem.completion_rule_snapshot?.effects?.milestone_name)} onChange={(event) => setQuickCreateMilestone(event.target.checked)} /><span>记入里程碑</span></label>
                    {quickCreateMilestone ? <label className="field"><span>里程碑名称</span><input className="input" value={quickMilestoneName} onChange={(event) => setQuickMilestoneName(event.target.value)} /></label> : <span className="milestone-name-placeholder" aria-hidden="true" />}
                  </div>
                  <div className="quick-complete-actions"><button className="mini-button" onClick={() => setQuickCompleting(false)}>取消</button><button className="mini-button active" onClick={() => void quickComplete()}>确认完成</button></div>
                </section> : null}
                <div className="quick-actions"><button className="mini-button" onClick={() => void saveQuickItem()}>保存本次办理</button>{!quickCompleting ? <button className="mini-button active" onClick={() => { setQuickCompleting(true); setQuickCompletionDate(today()); setQuickMilestoneName(quickItem.completion_rule_snapshot?.effects?.milestone_name || quickItem.name); setQuickCreateMilestone(Boolean(quickItem.completion_rule_snapshot?.effects?.create_milestone)); }}>完成事项</button> : null}</div>
              </section> : quickConstraint ? <section className="quick-panel constraint-quick-panel">
                {quickConstraintHasBatchContext ? <button type="button" className="quick-return" onClick={() => { setQuickConstraint(null); setQuickConstraintFromList(false); }}>← 返回批量操作</button> : <button type="button" className="quick-return" onClick={closeRail}>关闭办理</button>}
                {quickConstraintFromList ? <button type="button" className="text-button" onClick={() => { setQuickConstraint(null); void openQuickConstraintList(quickProjectId!); }}>返回约束列表</button> : null}
                <div className="quick-context"><span>当前项目</span><strong>{quickProject?.name || "项目"}</strong><small>{quickProject?.project_code}</small><div><b>{quickConstraint.name}</b><em>{constraintStatusLabel(quickConstraint.handling_status)} · {clearanceLabel(quickConstraint.clearance_status)}</em></div></div>
                <section className="quick-group"><div className="quick-panel-heading"><strong>办理进展</strong><span>记录外部单位或审批程序的最新变化</span></div>
                  <div className="quick-log-list">{(showAllQuickLogs ? quickConstraintLogs : quickConstraintLogs.slice(0, 3)).map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDate(log.created_at)} · {log.operator}</small><div className="log-actions"><button className="text-button" onClick={() => editQuickConstraintProgress(log)}>编辑</button><button className="text-button" onClick={() => deleteQuickConstraintProgress(log)}>删除</button></div></article>)}</div>
                  {!quickConstraintLogs.length ? <p className="muted-copy">暂无进展记录</p> : null}
                  {quickConstraintLogs.length > 3 ? <button className="text-button" onClick={() => setShowAllQuickLogs((value) => !value)}>{showAllQuickLogs ? "收起进展记录" : "查看全部进展记录"}</button> : null}
                  <textarea className="textarea" rows={3} value={quickProgress} onChange={(event) => setQuickProgress(event.target.value)} placeholder="记录本次外部办理进展" />
                  <button className="mini-button" onClick={() => void addQuickConstraintProgress()}>记录进展</button>
                </section>
                <section className="quick-group"><div className="quick-panel-heading"><strong>约束办理</strong><span>约束不会改变项目 Stage 或事项状态</span></div>
                  <div className="work-item-actions"><button className="mini-button" onClick={() => void submitQuickConstraintAction("begin")}>开始办理</button><button className="mini-button" onClick={() => { setQuickConstraintAction("clear"); setQuickConstraintActionText(""); }}>解除约束</button><button className="mini-button active" onClick={() => { setQuickConstraintAction("conclude"); setQuickConstraintActionText(""); }}>登记结论</button></div>
                  <details><summary>更多操作</summary><div className="work-item-actions"><button className="mini-button" onClick={() => { setQuickConstraintAction("mark_not_applicable"); setQuickConstraintActionText(""); }}>标记不适用</button><button className="mini-button danger" onClick={() => { setQuickConstraintAction("invalidate"); setQuickConstraintActionText(""); }}>结论失效</button></div></details>
                  {quickConstraintAction ? <div className="constraint-conclusion"><strong>{quickConstraintAction === "conclude" ? "登记结论" : quickConstraintAction === "clear" ? "解除约束" : quickConstraintAction === "invalidate" ? "使结论失效" : "标记不适用"}</strong><textarea className="textarea" rows={2} value={quickConstraintActionText} onChange={(event) => setQuickConstraintActionText(event.target.value)} placeholder={quickConstraintAction === "conclude" ? "结论内容" : "原因或说明（必填）"} /><div className="work-item-actions"><button className="mini-button" onClick={() => setQuickConstraintAction(null)}>取消</button><button className="mini-button active" disabled={!quickConstraintActionText.trim()} onClick={() => { const action = quickConstraintAction; setQuickConstraintAction(null); void submitQuickConstraintAction(action, action === "conclude" ? { outcome: { result: quickConstraintActionText.trim() }, concluded_on: today(), cleared: false } : { reason: quickConstraintActionText.trim() }); }}>确认</button></div></div> : null}
                </section>
              </section> : quickConstraintList ? <section className="quick-panel constraint-quick-panel"><button type="button" className="quick-return" onClick={() => { setQuickConstraintList(null); }}>← 返回批量操作</button><div className="quick-context"><span>当前项目</span><strong>{quickProject?.name || "项目"}</strong><small>{quickProject?.project_code}</small></div><section className="quick-group"><div className="quick-panel-heading"><strong>外部约束</strong><span>{quickConstraintList.length} 项</span></div>{quickConstraintList.length ? <div className="constraint-list">{quickConstraintList.map((constraint) => <button key={constraint.id} type="button" className="constraint-quick-entry" onClick={() => void openQuickConstraint(quickProjectId!, constraint.id, true)}><strong>{constraint.name}</strong><small>{constraintStatusLabel(constraint.handling_status)} · {clearanceLabel(constraint.clearance_status)}</small><em>{constraint.latest_progress_summary || "暂无进展"}</em></button>)}</div> : <p className="muted-copy">当前无外部约束。</p>}</section></section> : <>{operationMode === "advance" ? <>
                <p className="operation-lead">根据当前勾选项目显示可执行的推进治理动作；切换筛选不会关闭操作台。</p>
                <label className="field"><span>操作人</span><input className="input" value={operator} onChange={(event) => setOperator(event.target.value)} /></label>
                {(advancementAction === "include" || advancementAction === "special") ? <label className="field"><span>推进年度</span><input className="input" type="number" value={advancementYear} onChange={(event) => setAdvancementYear(event.target.value)} /></label> : null}
                <label className="field"><span>{advancementAction === "defer" ? "暂缓原因" : advancementAction === "special" ? "特批原因" : "纳入理由"}</span><textarea className="textarea" value={comment} onChange={(event) => setComment(event.target.value)} rows={4} /></label>
                {advancementAction === "defer" ? <button className="action-button primary full" disabled={!comment || executing} onClick={() => void submitDeferAdvancement()}><CheckCircle2 size={16} />确认暂缓推进</button> : advancementAction === "special" ? <><label className="field"><span>审批人或审批依据</span><input className="input" value={earlyApprovalBasis} onChange={(event) => setEarlyApprovalBasis(event.target.value)} placeholder="必填：审批人或审批依据" /></label><button className="action-button primary full" disabled={!comment || !earlyApprovalBasis || executing} onClick={() => void submitEarlyPreparation()}><CheckCircle2 size={16} />确认特批纳入推进</button></> : advancementAction === "include" ? <button className="action-button primary full" disabled={!comment || executing} onClick={() => void submitAdvancement()}><CheckCircle2 size={16} />确认纳入推进</button> : <p className="notice error">{advancementAction === "none" ? "请先勾选项目。" : "所选项目的 Stage 不一致或不符合推进动作，请分别处理。"}</p>}
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
                  <details className="draft-settings"><summary>办理安排</summary><div className="details-body"><div className="field-grid"><input className="input" value={item.assignee} onChange={(event) => updateDraft(index, { assignee: event.target.value })} placeholder="负责人" /><input className="input" type="date" value={item.planned_date} onChange={(event) => updateDraft(index, { planned_date: event.target.value })} /></div><div className="field-grid"><label className="field"><span>关注程度（仅影响独立事项的显示先后）</span><select className="select" value={item.priority} onChange={(event) => updateDraft(index, { priority: event.target.value })}><option value="high">高</option><option value="normal">普通</option><option value="low">低</option></select></label><label className="field"><span>办理位置</span><select className="select" value={item.flow_group} onChange={(event) => updateDraft(index, { flow_group: event.target.value as "main" | "independent", sequence_rank: undefined })}><option value="independent">独立跟踪（不占主流程）</option><option value="main">主流程末尾</option></select></label></div><p className="muted-copy">办理方式默认“仅跟踪”；需要标记系统内或系统外时再在项目详情调整。</p><textarea className="textarea" rows={2} value={item.note} onChange={(event) => updateDraft(index, { note: event.target.value })} placeholder="附加备注" /></div></details>
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
                <select className="select" value={selectedPackageId ?? ""} onChange={(event) => { setSelectedPackageId(Number(event.target.value) || null); setEditingPackage(false); }}><option value="">选择工作包</option>{activePackages.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.items.length} 项</option>)}</select>
                {selectedPackage ? <>{editingPackage ? <div className="detail-add-item"><input className="input" value={packageEditName} onChange={(event) => setPackageEditName(event.target.value)} placeholder="工作包名称" /><p className="muted-copy">拖动左侧把手调整后续下发顺序；已下发项目不会被改写。</p>{packageEditItems.map((item, index) => <div className="field-grid sortable-item" draggable key={`${item.name}-${index}`} onDragStart={() => setDraggedPackageItem(index)} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (draggedPackageItem === null || draggedPackageItem === index) return; setPackageEditItems((items) => { const next = [...items]; const [moved] = next.splice(draggedPackageItem, 1); next.splice(index, 0, moved); return next; }); setDraggedPackageItem(null); }}><span className="drag-handle" aria-label="拖动排序">⋮⋮</span><input className="input" value={item.name} onChange={(event) => setPackageEditItems((items) => items.map((current, itemIndex) => itemIndex === index ? { ...current, name: event.target.value } : current))} placeholder="事项名称" /><button className="text-button danger" onClick={() => setPackageEditItems((items) => items.filter((_, itemIndex) => itemIndex !== index))}>移除</button></div>)}<button className="mini-button" onClick={() => setPackageEditItems((items) => [...items, { ...emptyDraft(), flow_group: "main" }])}>＋添加临时事项</button><div className="work-item-actions"><button className="mini-button" onClick={() => setEditingPackage(false)}>取消</button><button className="mini-button active" disabled={!packageEditName.trim() || !packageEditItems.length} onClick={() => void savePackageEdits()}>保存工作包</button></div></div> : <div className="package-preview">{selectedPackage.items.map((item, index) => <span key={`${item.name}-${index}`}>{item.name}</span>)}{selectedPackage.constraints?.length ? <div className="constraint-package-preview"><strong>将建立的外部约束</strong>{selectedPackage.constraints.map((item, index) => <span key={item.template_id ?? index}>{item.name || "外部约束模板"}</span>)}</div> : null}<button className="text-button" onClick={startEditingPackage}>编辑组成与顺序</button></div>}</> : null}
                <button className="action-button primary full" disabled={!selectedIds.length || !selectedPackageId || executing} onClick={() => void submitPackage()}><PackagePlus size={16} />应用工作包</button>
              </> : null}
              {operationMode === "constraints" ? <>
                <p className="operation-lead">向已勾选项目建立外部治理条件；它不会改变项目 Stage 或事项状态。</p>
                <button className="text-button" onClick={() => setTemplateManager(templateManager === "constraints" ? null : "constraints")}>管理常用外部约束</button>
                {templateManager === "constraints" ? <TemplateManager items={constraintTemplates} kind="external-constraint" onArchive={archiveTemplate} onRefresh={loadDashboard} operator={operator} onError={setError} projectTypes={projectTypes} /> : null}
                <label className="field"><span>操作人</span><input className="input" value={operator} onChange={(event) => setOperator(event.target.value)} /></label>
                <label className="field"><span>常用外部约束</span><select className="select" value={constraintTemplateId ?? ""} onChange={(event) => { const next = Number(event.target.value) || null; setConstraintTemplateId(next); const template = activeConstraintTemplates.find((item) => item.id === next); if (template) { setConstraintName(template.name); setConstraintBlocking(Boolean(template.is_blocking)); } }}><option value="">选择常用约束（可选）</option>{activeConstraintTemplates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                <label className="field"><span>约束名称</span><input className="input" value={constraintName} onChange={(event) => setConstraintName(event.target.value)} placeholder="例如：上级预算核定" /></label>
                <label className="toggle"><input type="checkbox" checked={constraintBlocking} onChange={(event) => setConstraintBlocking(event.target.checked)} /><span>当前阻断后续推进</span></label>
                <label className="field"><span>初始办理状态</span><select className="select" value={constraintStatus} onChange={(event) => setConstraintStatus(event.target.value)}><option value="not_started">未开始</option><option value="in_progress">办理中</option></select></label>
                <label className="toggle"><input type="checkbox" checked={saveConstraintAsCommon} onChange={(event) => setSaveConstraintAsCommon(event.target.checked)} /><span>保存为常用外部约束</span></label>
                <button className="action-button primary full" disabled={!selectedIds.length || executing} onClick={() => void submitBatchConstraints()}>确认添加外部约束</button>
                <hr />
                <p className="mini-section-heading"><strong>批量办理已有约束</strong></p>
                <p className="muted-copy">仅对每个项目均存在同一模板约束的项目执行；先预检，存在不合格项目时不会部分提交。</p>
                <label className="field"><span>办理动作</span><select className="select" value={batchConstraintAction} onChange={(event) => { setBatchConstraintAction(event.target.value as typeof batchConstraintAction); setBatchConstraintPreview(null); }}><option value="begin">开始办理</option><option value="progress">记录共同进展</option><option value="conclude">登记共同结论</option><option value="clear">解除约束</option><option value="mark_not_applicable">标记不适用</option></select></label>
                {batchConstraintAction !== "begin" && !isBatchBudgetDetermination ? <label className="field"><span>{batchConstraintAction === "progress" ? "共同进展" : batchConstraintAction === "conclude" ? "共同结论" : "原因或说明"}</span><textarea className="textarea" rows={2} value={batchConstraintReason} onChange={(event) => setBatchConstraintReason(event.target.value)} /></label> : null}
                <button className="mini-button" disabled={!selectedIds.length || !constraintTemplateId} onClick={() => void previewBatchConstraintAction()}>预检批量办理</button>
                {batchConstraintPreview ? <div className="operation-preview"><strong>可办理 {batchConstraintPreview.eligible.length} 个</strong>{batchConstraintPreview.ineligible.length ? <small>不可办理 {batchConstraintPreview.ineligible.length} 个：{batchConstraintPreview.ineligible.map((item) => item.name || item.project_id).join("、")}</small> : <small>全部项目符合条件</small>}{isBatchBudgetDetermination ? <div className="batch-budget-outcomes">{batchConstraintPreview.eligible.map((item) => { const value = batchBudgetOutcomes[item.project_id] ?? { approved_budget: "", concluded_on: today(), note: "", cleared: true, set_effective_budget_source: true }; const update = (patch: Partial<typeof value>) => setBatchBudgetOutcomes((current) => ({ ...current, [item.project_id]: { ...value, ...patch } })); return <fieldset key={item.project_id}><legend>{item.name} · {item.project_code}</legend><label className="field"><span>核定预算（万元）</span><input className="input" type="number" min="0" value={value.approved_budget} onChange={(event) => update({ approved_budget: event.target.value })} /></label><label className="field"><span>结论日期</span><input className="input" type="date" value={value.concluded_on} onChange={(event) => update({ concluded_on: event.target.value })} /></label><label className="field"><span>说明（可选）</span><input className="input" value={value.note} onChange={(event) => update({ note: event.target.value })} /></label><label className="toggle"><input type="checkbox" checked={value.cleared} onChange={(event) => update({ cleared: event.target.checked })} /><span>解除阻断</span></label><label className="toggle"><input type="checkbox" checked={value.set_effective_budget_source} onChange={(event) => update({ set_effective_budget_source: event.target.checked })} /><span>设为当前有效预算</span></label></fieldset>; })}</div> : null}<button className="action-button primary full" disabled={Boolean(batchConstraintPreview.ineligible.length)} onClick={() => void submitBatchConstraintAction()}>确认批量办理</button></div> : null}
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
              {operationMode === "config" ? <section className="config-panel"><p className="operation-lead">项目分类是唯一的 PMO 分类字段；系统自动维护内部标识，PMO 只需填写显示名称和编号前缀。</p><div className="field-grid"><input className="input" value={newClassificationName} onChange={(event) => setNewClassificationName(event.target.value)} placeholder="新增项目分类" /><input className="input" value={newClassificationPrefix} onChange={(event) => setNewClassificationPrefix(event.target.value)} placeholder="编号前缀，例如 EQ" /><input className="input" type="number" value={newClassificationOrder} onChange={(event) => setNewClassificationOrder(event.target.value)} placeholder="排序（小的在前）" /></div><button className="mini-button" onClick={() => void addProjectClassification()}>新增项目分类</button><div className="template-manager">{projectTypes.map((item) => <div key={item.id}><span>{item.name} · {item.code_prefix}</span><input className="input compact-input" type="number" defaultValue={item.sort_order ?? ""} placeholder="排序" onBlur={(event) => { if (event.target.value) void saveProjectClassification(item, { sort_order: Number(event.target.value) }); }} /><button className="text-button" onClick={() => void saveProjectClassification(item, { is_active: !item.is_active })}>{item.is_active ? "停用" : "恢复"}</button></div>) || <span>暂无项目分类</span>}</div><p className="mini-section-heading"><strong>部门排序</strong></p><div className="template-manager">{departments.map((department) => { const configured = departmentSettings.find((item) => item.department === department); return <div key={department}><span>{department}</span><input className="input compact-input" type="number" defaultValue={configured?.sort_order ?? ""} placeholder="排序" onBlur={(event) => { if (event.target.value) void saveDepartmentOrder(department, event.target.value); }} /></div>; })}</div></section> : null}
              {operationMode === "batch" ? <div className="empty-state"><Layers3 size={18} />批次登记将在 Phase 2 开放。</div> : null}</>}
            </div>
          </div>

        </aside>

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
              <article className="preview-card"><strong>{importPreview.valid_rows}</strong><span>可导入行</span></article>
              <article className="preview-card"><strong>{importPreview.invalid_rows}</strong><span>异常行</span></article>
              <article className="preview-card"><strong>{importPreview.total_rows}</strong><span>总行数</span></article>
              <button className="action-button ghost compact" onClick={() => void commitImport()}><Send size={16} />确认写入</button>
            </div>
          ) : null}
          {importPreview?.errors?.length ? (
            <div className="error-list">
              {importPreview.errors.map((item) => <div key={`${item.row_number}-${item.code}`} className="error-item"><AlertTriangle size={16} />第 {item.row_number} 行：{item.message}</div>)}
            </div>
          ) : null}
        </section>
      </main>
      {dialog ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => setDialog(null)}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label={dialog.title} onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">PMO ACTION</p><h3>{dialog.title}</h3>
          <p className="muted-copy">{dialog.kind === "delete-log" ? "请填写删除原因。记录会从日常界面隐藏，但审计仍会完整保留。" : dialog.kind === "archive-template" ? "归档后不会影响已下发事项和历史记录。" : "更新后将立即回显到当前事项。"}</p>
          <textarea className="textarea" rows={3} autoFocus value={dialog.value} placeholder={dialog.kind === "delete-log" || dialog.kind === "archive-template" ? "请填写原因（必填）" : "进展内容"} onChange={(event) => setDialog({ ...dialog, value: event.target.value })} />
          <div className="dialog-actions"><button className="mini-button" onClick={() => setDialog(null)}>取消</button><button className="action-button primary" disabled={!dialog.value.trim()} onClick={() => void submitDialog()}>确认</button></div>
        </section>
      </div> : null}
      {restoreTarget ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => setRestoreTarget(null)}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label="恢复项目" onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">PMO ACTION</p><h3>恢复“{restoreTarget.name}”</h3>
          <p className="muted-copy">项目将回到日常列表；原移除记录和审计会继续保留。</p>
          <textarea className="textarea" rows={3} autoFocus value={restoreReason} onChange={(event) => setRestoreReason(event.target.value)} placeholder="恢复原因（必填）" />
          <div className="dialog-actions"><button className="mini-button" onClick={() => setRestoreTarget(null)}>取消</button><button className="action-button primary" disabled={!restoreReason.trim()} onClick={() => void restoreProject()}>确认恢复</button></div>
        </section>
      </div> : null}
      {newProjectOpen ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => setNewProjectOpen(false)}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label="新增项目" onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">PMO ACTION</p><h3>新增项目</h3>
          <input className="input" autoFocus value={newProject.name} onChange={(event) => setNewProject({ ...newProject, name: event.target.value })} placeholder="项目名称（必填）" />
          <div className="field-grid"><input className="input" value={newProject.department} onChange={(event) => setNewProject({ ...newProject, department: event.target.value })} placeholder="部门/学院" /><input className="input" value={newProject.project_manager} onChange={(event) => setNewProject({ ...newProject, project_manager: event.target.value })} placeholder="负责人" /></div>
          <div className="field-grid"><select className="select" value={newProject.project_type} onChange={(event) => setNewProject({ ...newProject, project_type: event.target.value, procurement_nature: "", location: "" })}><option value="">选择项目分类</option>{projectTypes.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.code}>{item.name}</option>)}</select><input className="input" type="number" value={newProject.budget} onChange={(event) => setNewProject({ ...newProject, budget: event.target.value })} placeholder="初始预算（万元）" /></div>
          {newProject.project_type === "software" ? <label className="field"><span>采购属性</span><select className="select" value={newProject.procurement_nature} onChange={(event) => setNewProject({ ...newProject, procurement_nature: event.target.value })}><option value="">未设置</option><option value="goods">货物</option><option value="service">服务</option><option value="mixed">混合</option></select></label> : null}
          {newProject.project_type === "laboratory" ? <input className="input" value={newProject.location} onChange={(event) => setNewProject({ ...newProject, location: event.target.value })} placeholder="地点（可选）" /> : null}
          <textarea className="textarea" rows={2} value={newProject.description} onChange={(event) => setNewProject({ ...newProject, description: event.target.value })} placeholder="项目说明（可选）" />
          <div className="dialog-actions"><button className="mini-button" onClick={() => setNewProjectOpen(false)}>取消</button><button className="action-button primary" disabled={!newProject.name.trim() || !newProject.project_type} onClick={() => void createManualProject()}>确认新增</button></div>
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
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [workItems, setWorkItems] = useState<WorkItem[]>([]);
  const [templates, setTemplates] = useState<WorkItemTemplate[]>([]);
  const [projectTypes, setProjectTypes] = useState<ProjectTypeDefinition[]>([]);
  const [externalConstraints, setExternalConstraints] = useState<ProjectExternalConstraint[]>([]);
  const [constraintTemplates, setConstraintTemplates] = useState<ExternalConstraintTemplate[]>([]);
  const [addingConstraint, setAddingConstraint] = useState(false);
  const [newConstraintTemplateId, setNewConstraintTemplateId] = useState<number | null>(null);
  const [newConstraintName, setNewConstraintName] = useState("");
  const [newConstraintBlocking, setNewConstraintBlocking] = useState(true);
  const [concludingConstraintId, setConcludingConstraintId] = useState<number | null>(null);
  const [conclusionBudget, setConclusionBudget] = useState("");
  const [conclusionKind, setConclusionKind] = useState("custom");
  const [conclusionResult, setConclusionResult] = useState("");
  const [conclusionReference, setConclusionReference] = useState("");
  const [conclusionNote, setConclusionNote] = useState("");
  const [conclusionDate, setConclusionDate] = useState(today());
  const [conclusionCleared, setConclusionCleared] = useState(true);
  const [invalidatingConstraintId, setInvalidatingConstraintId] = useState<number | null>(null);
  const [invalidationReason, setInvalidationReason] = useState("");
  const [constraintAction, setConstraintAction] = useState<null | { id: number; action: "clear" | "mark_not_applicable" | "set_effective_budget_source" }>(null);
  const [constraintActionReason, setConstraintActionReason] = useState("");
  const [editingProject, setEditingProject] = useState(false);
  const [projectReason, setProjectReason] = useState("");
  const [projectEditErrors, setProjectEditErrors] = useState<{ name?: string; reason?: string }>({});
  const projectNameRef = useRef<HTMLInputElement>(null);
  const projectReasonRef = useRef<HTMLTextAreaElement>(null);
  const [deleteProjectOpen, setDeleteProjectOpen] = useState(false);
  const [deleteProjectReason, setDeleteProjectReason] = useState("");
  const [addingItem, setAddingItem] = useState(false);
  const [newDraft, setNewDraft] = useState<WorkItemDraft>(emptyDraft());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [completionId, setCompletionId] = useState<number | null>(null);
  const [completionMilestone, setCompletionMilestone] = useState(false);
  const [completionMilestoneName, setCompletionMilestoneName] = useState("");
  const [completionResult, setCompletionResult] = useState("");
  const [completionDate, setCompletionDate] = useState("");
  const [completionNote, setCompletionNote] = useState("");
  const [draggedWorkItemId, setDraggedWorkItemId] = useState<number | null>(null);
  const [reopenId, setReopenId] = useState<number | null>(null);
  const [reopenReason, setReopenReason] = useState("");
  const [itemAction, setItemAction] = useState<{ item: WorkItem; action: "cancel" | "skip" } | null>(null);
  const [itemActionReason, setItemActionReason] = useState("");
  const [progressLogs, setProgressLogs] = useState<Record<number, WorkItemProgressLog[]>>({});
  const [expandedProgressItem, setExpandedProgressItem] = useState<number | null>(null);
  const [progressDraft, setProgressDraft] = useState("");
  const [highlightProgress, setHighlightProgress] = useState(false);
  const [editingProgressLog, setEditingProgressLog] = useState<WorkItemProgressLog | null>(null);
  const [deletingProgressLog, setDeletingProgressLog] = useState<WorkItemProgressLog | null>(null);
  const [progressDialogValue, setProgressDialogValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    void Promise.all([
      apiGet<Project>(`/projects/${projectId}`),
      apiGet<StatusHistoryItem[]>(`/projects/${projectId}/history`),
      apiGet<WorkItem[]>(`/projects/${projectId}/work-items`),
      apiGet<WorkItemTemplate[]>("/work-item-templates"),
      apiGet<ProjectTypeDefinition[]>("/project-types"),
      apiGet<Milestone[]>(`/projects/${projectId}/milestones`),
      apiGet<AuditEvent[]>(`/projects/${projectId}/audit-events`),
      apiGet<ManagementTimelineEvent[]>(`/projects/${projectId}/management-timeline`),
      apiGet<ProjectExternalConstraint[]>(`/projects/${projectId}/external-constraints`),
      apiGet<ExternalConstraintTemplate[]>("/external-constraint-templates"),
    ])
      .then(([projectData, historyData, workItemData, templateData, projectTypeData, milestoneData, auditData, timelineData, constraintData, constraintTemplateData]) => {
        setProject(projectData);
        setHistory(historyData);
        setWorkItems(workItemData);
        setTemplates(templateData);
        setProjectTypes(projectTypeData);
        setMilestones(milestoneData);
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

  async function refreshDetailProjection() {
    if (!projectId) return;
    const [projectData, workItemData, milestoneData, auditData, timelineData, constraintData] = await Promise.all([
      apiGet<Project>(`/projects/${projectId}`),
      apiGet<WorkItem[]>(`/projects/${projectId}/work-items`),
      apiGet<Milestone[]>(`/projects/${projectId}/milestones`),
      apiGet<AuditEvent[]>(`/projects/${projectId}/audit-events`),
      apiGet<ManagementTimelineEvent[]>(`/projects/${projectId}/management-timeline`),
      apiGet<ProjectExternalConstraint[]>(`/projects/${projectId}/external-constraints`),
    ]);
    setProject(projectData);
    setWorkItems(workItemData);
    setMilestones(milestoneData);
    setAuditEvents(auditData);
    setManagementTimeline(timelineData);
    setExternalConstraints(constraintData);
  }

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
    setWorkItems((items) => sortProjectWorkItems([...items, created]));
    setNewDraft(emptyDraft()); setAddingItem(false);
    await refreshTimeline();
  }

  async function completeWorkItem(item: WorkItem) {
    if (!projectId) return;
    await apiPost<WorkItem>(`/projects/${projectId}/work-items/${item.id}/complete`, { operator: "PMO办公室", result: completionResult.trim() || "已完成", completed_on: completionDate || null, note: completionNote.trim() || null, create_milestone: completionMilestone, milestone_name: completionMilestoneName || item.name });
    setCompletionId(null); setCompletionMilestone(false); setCompletionMilestoneName(""); setCompletionResult(""); setCompletionDate(""); setCompletionNote("");
    await refreshDetailProjection();
  }

  async function reorderMainWorkItems(targetId: number) {
    if (!projectId || !draggedWorkItemId || draggedWorkItemId === targetId) return;
    const main = orderedWorkItems.filter((item) => item.flow_group === "main");
    const from = main.findIndex((item) => item.id === draggedWorkItemId);
    const to = main.findIndex((item) => item.id === targetId);
    if (from < 0 || to < 0) return;
    const reordered = [...main];
    const [moved] = reordered.splice(from, 1);
    reordered.splice(to, 0, moved);
    try {
      const updated = await apiPost<WorkItem[]>(`/projects/${projectId}/work-items/reorder`, { operator: "PMO办公室", work_item_ids: reordered.map((item) => item.id) });
      setWorkItems(updated); await refreshTimeline();
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项顺序未保存，页面保持原状。"); }
    finally { setDraggedWorkItemId(null); }
  }

  async function updateWorkItem(item: WorkItem) {
    if (!projectId) return;
  const updated = await apiPatch<WorkItem>(`/projects/${projectId}/work-items/${item.id}`, { operator: "PMO办公室", status: item.status === "not_started" ? "in_progress" : item.status, assignee: item.assignee, planned_date: item.planned_date, priority: item.priority, note: item.note, content: item.content, track_as_key_node: Boolean(item.track_as_key_node) });
    setWorkItems((items) => items.map((current) => current.id === updated.id ? updated : current)); setEditingId(null);
    await refreshTimeline();
  }

  async function reopenWorkItem(item: WorkItem) {
    if (!projectId || !reopenReason.trim()) return;
    await apiPost<WorkItem>(`/projects/${projectId}/work-items/${item.id}/reopen`, { operator: "PMO办公室", reason: reopenReason });
    setReopenId(null); setReopenReason("");
    await refreshDetailProjection();
  }

  async function submitItemAction() {
    if (!projectId || !itemAction || !itemActionReason.trim()) return;
    try {
      const updated = await apiPost<WorkItem>(`/projects/${projectId}/work-items/${itemAction.item.id}/${itemAction.action}`, { operator: "PMO办公室", reason: itemActionReason.trim() });
      setWorkItems((items) => items.map((current) => current.id === updated.id ? updated : current));
      setItemAction(null); setItemActionReason("");
      await refreshTimeline();
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项操作未成功，页面保持原状。"); }
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

  async function saveDetailProgress() {
    if (!projectId || !editingProgressLog || !progressDialogValue.trim()) return;
    const updated = await apiPatch<WorkItemProgressLog>(`/projects/${projectId}/work-items/${editingProgressLog.project_work_item_id}/progress-logs/${editingProgressLog.id}`, { operator: "PMO办公室", content: progressDialogValue.trim(), is_timeline_highlight: editingProgressLog.is_timeline_highlight });
    setProgressLogs((logs) => ({ ...logs, [updated.project_work_item_id]: (logs[updated.project_work_item_id] ?? []).map((entry) => entry.id === updated.id ? updated : entry) }));
    setEditingProgressLog(null); setProgressDialogValue(""); await refreshTimeline();
  }

  async function deleteDetailProgress() {
    if (!projectId || !deletingProgressLog || !progressDialogValue.trim()) return;
    await apiDelete(`/projects/${projectId}/work-items/${deletingProgressLog.project_work_item_id}/progress-logs/${deletingProgressLog.id}`, { operator: "PMO办公室", reason: progressDialogValue.trim() });
    setProgressLogs((logs) => ({ ...logs, [deletingProgressLog.project_work_item_id]: (logs[deletingProgressLog.project_work_item_id] ?? []).filter((entry) => entry.id !== deletingProgressLog.id) }));
    setDeletingProgressLog(null); setProgressDialogValue(""); await refreshTimeline();
  }

  async function addExternalConstraint() {
    if (!projectId || !newConstraintName.trim()) return;
    try {
      await apiPost<ProjectExternalConstraint>(`/projects/${projectId}/external-constraints`, { template_id: newConstraintTemplateId, name: newConstraintName.trim(), is_blocking: newConstraintBlocking, operator: "PMO办公室" });
      setNewConstraintName(""); setNewConstraintTemplateId(null); setAddingConstraint(false);
      await refreshDetailProjection();
    } catch (err) { setError(err instanceof ApiError ? err.message : "外部约束未建立，页面保持原状。"); }
  }

  async function confirmConstraintScope() {
    if (!projectId) return;
    try {
      await apiPost(`/projects/${projectId}/confirm-external-constraint-scope`, { operator: "PMO办公室", note: "PMO 已确认当前适用外部约束范围" });
      await refreshDetailProjection();
    } catch (err) { setError(err instanceof ApiError ? err.message : "适用范围未确认，页面保持原状。"); }
  }

  async function actOnConstraint(constraint: ProjectExternalConstraint, action: string) {
    if (!projectId) return;
    const payload: Record<string, unknown> = { operator: "PMO办公室", action };
    if (action === "conclude") {
      payload.cleared = conclusionCleared;
      payload.outcome = {
        kind: conclusionKind,
        ...(conclusionBudget.trim() ? { approved_budget: Number(conclusionBudget) } : {}),
        ...(conclusionResult.trim() ? { result: conclusionResult.trim() } : {}),
        ...(conclusionReference.trim() ? { reference: conclusionReference.trim() } : {}),
      };
      payload.evidence_note = conclusionNote;
      payload.concluded_on = conclusionDate;
      payload.set_effective_budget_source = conclusionKind === "budget_determination" && conclusionCleared && Boolean(conclusionBudget.trim());
    }
    if (action === "invalidate") payload.reason = invalidationReason;
    if (action === "clear" || action === "mark_not_applicable" || action === "set_effective_budget_source") payload.reason = constraintActionReason;
    try {
      await apiPost<ProjectExternalConstraint>(`/projects/${projectId}/external-constraints/${constraint.id}/actions`, payload);
      if (action === "conclude") { setConcludingConstraintId(null); setConclusionBudget(""); setConclusionResult(""); setConclusionReference(""); setConclusionNote(""); setConclusionDate(today()); setConclusionCleared(true); }
      if (action === "invalidate") { setInvalidatingConstraintId(null); setInvalidationReason(""); }
      if (action === "clear" || action === "mark_not_applicable" || action === "set_effective_budget_source") { setConstraintAction(null); setConstraintActionReason(""); }
      await refreshDetailProjection();
    } catch (err) { setError(err instanceof ApiError ? err.message : "约束办理未成功，页面保持原状。"); }
  }

  async function saveProjectEdits() {
    if (!projectId || !project) return;
    const errors = {
      ...(project.name.trim() ? {} : { name: "请填写项目名称" }),
      ...(projectReason.trim() ? {} : { reason: "请填写修改理由" }),
    };
    if (Object.keys(errors).length) {
      setProjectEditErrors(errors);
      requestAnimationFrame(() => (errors.name ? projectNameRef.current : projectReasonRef.current)?.focus());
      return;
    }
    setProjectEditErrors({});
    setError("");
    try {
      await apiPatch<Project>(`/projects/${projectId}`, { name: project.name, department: project.department, major: project.major, project_manager: project.project_manager, location: project.location, procurement_nature: project.procurement_nature, project_type: project.project_type, description: project.description, budget: project.budget, operator: "PMO办公室", reason: projectReason });
      await refreshDetailProjection();
      setProjectReason(""); setProjectEditErrors({}); setEditingProject(false);
      setFeedback("项目基本信息已保存并写入审计。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "项目基本信息未保存，页面保留当前填写内容。");
    }
  }

  async function removeProject() {
    if (!projectId || !project || !deleteProjectReason.trim()) return;
    try {
      await apiDelete(`/projects/${projectId}`, { operator: "PMO办公室", reason: deleteProjectReason.trim() });
      navigate("/");
    } catch (err) { setError(err instanceof ApiError ? err.message : "项目未移除，页面保持原状。"); }
  }

  const detailKeyNode = project?.next_key_node;
  const detailProjectTypeLabel = (code: Project["project_type"]) => projectTypes.find((item) => item.code === code)?.name || projectTypeLabel(code);
  const orderedWorkItems = useMemo(() => sortProjectWorkItems(workItems), [workItems]);

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
            <span>{detailProjectTypeLabel(project?.project_type ?? null)}</span>
          </div>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}
      {feedback ? <div className="notice success">{feedback}</div> : null}

      {loading ? (
        <div className="detail-loading">
          <LoaderCircle className="spin" size={22} />
          正在载入项目详情
        </div>
      ) : project ? (
        <main className="detail-layout">
          <section className="detail-main">
            <section className="detail-section detail-current-work">
              <div className="section-title"><div><p className="section-kicker">CURRENT WORK</p><h2>当前办理</h2>{detailKeyNode ? <p className="next-node-inline"><strong>下一关键节点</strong>　{detailKeyNode.name} · {detailKeyNode.planned_date || "未设置日期"} · {workStatusLabel(detailKeyNode.status)}</p> : <p className="next-node-inline"><strong>下一关键节点</strong>　未设置</p>}</div><button className="mini-button" onClick={() => setAddingItem((current) => !current)}><Plus size={15} />添加事项</button></div>
              {addingItem ? <div className="detail-add-item">
                <select className="select" value="" onChange={(event) => { const template = templates.find((item) => item.id === Number(event.target.value)); if (template) setNewDraft((current) => ({ ...current, name: template.name, content: template.default_content || "", execution_mode: template.execution_mode, flow_group: template.flow_group, sequence_rank: template.sequence_rank })); }}><option value="">从常用事项选择（或直接自定义）</option>{templates.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>
                <input className="input" value={newDraft.name} onChange={(event) => setNewDraft((current) => ({ ...current, name: event.target.value }))} placeholder="事项名称*，例如：等学院补交采购需求书" />
                <textarea className="textarea" rows={3} value={newDraft.content} onChange={(event) => setNewDraft((current) => ({ ...current, content: event.target.value }))} placeholder="事项内容 / 当前需要做什么" />
                <select className="select" value={newDraft.status} onChange={(event) => setNewDraft((current) => ({ ...current, status: event.target.value }))}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option></select>
                <details className="draft-settings"><summary>更多管理信息</summary><div className="details-body"><div className="field-grid"><input className="input" value={newDraft.assignee} onChange={(event) => setNewDraft((current) => ({ ...current, assignee: event.target.value }))} placeholder="负责人" /><input className="input" type="date" value={newDraft.planned_date} onChange={(event) => setNewDraft((current) => ({ ...current, planned_date: event.target.value }))} /></div><div className="field-grid"><select className="select" value={newDraft.priority} onChange={(event) => setNewDraft((current) => ({ ...current, priority: event.target.value }))}><option value="high">高优先级</option><option value="normal">普通</option><option value="low">低优先级</option></select><select className="select" value={newDraft.execution_mode} onChange={(event) => setNewDraft((current) => ({ ...current, execution_mode: event.target.value }))}><option value="tracking">仅跟踪</option><option value="internal">系统内</option><option value="external">系统外</option></select></div><label className="field"><span>事项位置</span><select className="select" value={newDraft.flow_group === "main" ? String(newDraft.insert_after_id ?? "start") : "independent"} onChange={(event) => { const value = event.target.value; setNewDraft((current) => value === "independent" ? { ...current, flow_group: "independent", insert_after_id: null } : { ...current, flow_group: "main", insert_after_id: value === "start" ? null : Number(value), sequence_rank: undefined }); }}><option value="independent">独立跟踪事项</option><option value="start">主流程开始处</option>{orderedWorkItems.filter((item) => item.flow_group === "main").map((item) => <option key={item.id} value={item.id}>插入“{item.name}”之后</option>)}</select></label><textarea className="textarea" rows={2} value={newDraft.note} onChange={(event) => setNewDraft((current) => ({ ...current, note: event.target.value }))} placeholder="附加备注" /></div></details>
                <button className="action-button primary" onClick={() => void addWorkItem()}>确认添加临时事项</button>
              </div> : null}
              <div className="work-item-list">
                {orderedWorkItems.length ? orderedWorkItems.map((item) => (
                  <div className={`work-item-row work-${item.status}`} key={item.id} draggable={item.flow_group === "main"} onDragStart={() => item.flow_group === "main" && setDraggedWorkItemId(item.id)} onDragOver={(event) => item.flow_group === "main" && event.preventDefault()} onDrop={() => void reorderMainWorkItems(item.id)}>
                    <div className="work-item-copy"><strong>{item.flow_group === "main" ? <span className="drag-handle" title="拖动调整主流程顺序">⋮⋮</span> : null}{item.name}</strong><span className={`work-status work-${item.status}`}>{workStatusLabel(item.status)}</span><small>负责人：{item.assignee || "未指定"}　计划：{item.planned_date || "未设置"}</small>{item.content ? <p>{item.content}</p> : null}{item.note ? <small>{item.note}</small> : null}{item.track_as_key_node ? <em>☆ 重点关注</em> : null}</div>
                    {editingId === item.id ? <div className="work-item-edit"><select className="select" value={item.status} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, status: event.target.value } : current))}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="waiting_external">等待外部</option><option value="paused">暂停</option><option value="not_applicable">不适用</option></select><input className="input" value={item.assignee} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, assignee: event.target.value } : current))} placeholder="负责人" /><input className="input" type="date" value={item.planned_date} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, planned_date: event.target.value } : current))} /><textarea className="textarea" rows={2} value={item.content} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, content: event.target.value } : current))} placeholder="事项内容" /><label className="toggle"><input type="checkbox" checked={Boolean(item.track_as_key_node)} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, track_as_key_node: event.target.checked } : current))} /><span>☆ 重点关注</span></label><button className="mini-button" onClick={() => void updateWorkItem(item)}>保存</button></div> : <div className="work-item-actions">{item.status !== "completed" && !item.cancelled_at ? <><button className="mini-button" onClick={() => setEditingId(item.id)}>更新</button><button className="mini-button" onClick={() => { setCompletionId(item.id); setCompletionMilestone(Boolean(item.completion_rule_snapshot.effects?.create_milestone)); setCompletionMilestoneName(item.completion_rule_snapshot.effects?.milestone_name || item.name); setCompletionDate(today()); setCompletionResult(""); setCompletionNote(""); }}>完成</button><button className="mini-button danger" onClick={() => { setItemAction({ item, action: "cancel" }); setItemActionReason(""); }}>取消事项</button>{item.flow_group === "main" && !item.skipped_at ? <button className="mini-button" onClick={() => { setItemAction({ item, action: "skip" }); setItemActionReason(""); }}>跳过节点</button> : null}</> : item.status === "completed" ? <button className="mini-button" onClick={() => setReopenId(item.id)}>重开</button> : <span className="muted-copy">已取消</span>}<button className="mini-button" onClick={() => void toggleProgressLogs(item.id)}>进展 {expandedProgressItem === item.id ? "收起" : "记录"}</button></div>}
                    {completionId === item.id ? <div className="reopen-row"><input className="input" value={completionResult} onChange={(event) => setCompletionResult(event.target.value)} placeholder="完成结果（可选）" /><input className="input" type="date" value={completionDate} onChange={(event) => setCompletionDate(event.target.value)} /><textarea className="textarea" rows={2} value={completionNote} onChange={(event) => setCompletionNote(event.target.value)} placeholder="完成说明（可选）" /><label className="toggle"><input type="checkbox" checked={completionMilestone} disabled={Boolean(item.completion_rule_snapshot.effects?.create_milestone && item.completion_rule_snapshot.effects?.milestone_name)} onChange={(event) => setCompletionMilestone(event.target.checked)} /><span>同时记录为项目里程碑</span></label>{completionMilestone ? <input className="input" value={completionMilestoneName} onChange={(event) => setCompletionMilestoneName(event.target.value)} placeholder="里程碑名称" /> : null}<button className="mini-button" onClick={() => void completeWorkItem(item)}>确认完成</button></div> : null}
                    {reopenId === item.id ? <div className="reopen-row"><input className="input" value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} placeholder="重开原因" /><button className="mini-button" onClick={() => void reopenWorkItem(item)}>确认重开</button></div> : null}
                    {expandedProgressItem === item.id ? <div className="progress-log-panel"><div className="progress-log-compose"><textarea className="textarea" rows={2} value={progressDraft} onChange={(event) => setProgressDraft(event.target.value)} placeholder="今天有什么变化？" /><label className="toggle"><input type="checkbox" checked={highlightProgress} onChange={(event) => setHighlightProgress(event.target.checked)} /><span>同步到项目时间线</span></label><button className="mini-button" onClick={() => void addProgressLog(item.id)}>记录进展</button></div>{(progressLogs[item.id] ?? []).length ? <div className="progress-log-list">{progressLogs[item.id].map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDateTime(log.created_at)} · {log.operator}{log.is_timeline_highlight ? " · 已同步时间线" : ""}</small><div className="log-actions"><button className="text-button" onClick={() => { setEditingProgressLog(log); setProgressDialogValue(log.content); }}>编辑</button><button className="text-button" onClick={() => { setDeletingProgressLog(log); setProgressDialogValue(""); }}>删除</button></div></article>)}</div> : <p className="muted-copy">尚未记录过程进展。</p>}</div> : null}
                  </div>
                )) : <div className="empty-state">暂无跟踪事项。先添加一个当前正在推进的工作。</div>}
              </div>
            </section>

            <section className="detail-section detail-governance governance-milestones">
              <div className="section-title"><div><p className="section-kicker">KEY GOVERNANCE</p><h2>里程碑</h2></div></div>
              {milestones.filter((milestone) => !milestone.is_void).length ? <div className="timeline-list">{milestones.filter((milestone) => !milestone.is_void).map((milestone) => <article key={milestone.id}><strong>{milestone.title}</strong><small>{formatDate(milestone.occurred_on)}{milestone.result ? ` · ${milestone.result}` : ""}</small>{milestone.note ? <p>{milestone.note}</p> : null}</article>)}</div> : <p className="muted-copy">尚未形成项目里程碑。</p>}
            </section>

            <section className="detail-section detail-governance governance-constraints">
              <div className="section-title"><div><p className="section-kicker">EXTERNAL CONDITIONS</p><h2>外部约束 <small>({externalConstraints.length} 项)</small></h2><p className="muted-copy">外部约束只描述外部治理条件，不改变项目 Stage 或当前事项。</p></div><div className="work-item-actions"><button className="mini-button" onClick={() => void confirmConstraintScope()}>确认适用范围</button><button className="mini-button" onClick={() => setAddingConstraint((value) => !value)}><Plus size={15} />添加外部约束</button></div></div>
              {addingConstraint ? <div className="detail-add-item"><select className="select" value={newConstraintTemplateId ?? ""} onChange={(event) => { const id = Number(event.target.value) || null; setNewConstraintTemplateId(id); const template = constraintTemplates.find((item) => item.id === id); if (template) { setNewConstraintName(template.name); setNewConstraintBlocking(Boolean(template.is_blocking)); } }}><option value="">从常用约束选择（或直接新建）</option>{constraintTemplates.filter((item) => !item.archived_at).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input className="input" value={newConstraintName} onChange={(event) => setNewConstraintName(event.target.value)} placeholder="外部约束名称，例如：上级预算核定" /><label className="toggle"><input type="checkbox" checked={newConstraintBlocking} onChange={(event) => setNewConstraintBlocking(event.target.checked)} /><span>当前阻断后续推进</span></label><button className="action-button primary" onClick={() => void addExternalConstraint()}>确认添加外部约束</button></div> : null}
              <div className="constraint-list">{externalConstraints.length ? externalConstraints.map((constraint) => <article key={constraint.id} className="constraint-card"><div><strong>{constraint.name}</strong><small>{constraint.is_blocking ? "阻断性条件" : "非阻断性条件"} · {constraintStatusLabel(constraint.handling_status)} · {clearanceLabel(constraint.clearance_status)}</small>{constraint.handling_status === "concluded" ? <small>{constraintSummary(constraint)}{constraint.is_effective_budget_source ? " · 当前有效预算来源" : ""}</small> : null}{constraint.latest_progress_summary ? <small>最近进展：{constraint.latest_progress_summary}</small> : null}</div><div className="work-item-actions"><button className="mini-button" onClick={() => void actOnConstraint(constraint, "begin")}>开始办理</button><button className="mini-button" onClick={() => { setConstraintAction({ id: constraint.id, action: "clear" }); setConstraintActionReason(""); }}>解除约束</button><button className="mini-button active" onClick={() => { setConcludingConstraintId(constraint.id); setConclusionKind(constraint.template_snapshot_json?.outcome_schema_json?.kind || "custom"); setConclusionDate(today()); }}>登记结论</button><details><summary>更多</summary><button className="text-button" onClick={() => { setConstraintAction({ id: constraint.id, action: "mark_not_applicable" }); setConstraintActionReason(""); }}>标记不适用</button><button className="text-button danger" onClick={() => setInvalidatingConstraintId(constraint.id)}>结论失效</button></details>{constraint.handling_status === "concluded" && constraint.clearance_status === "cleared" && typeof constraint.outcome_json.approved_budget === "number" && !constraint.is_effective_budget_source ? <button className="mini-button" onClick={() => { setConstraintAction({ id: constraint.id, action: "set_effective_budget_source" }); setConstraintActionReason(""); }}>设为当前预算</button> : null}</div>{constraintAction?.id === constraint.id ? <div className="constraint-conclusion"><strong>{constraintAction.action === "clear" ? "解除约束" : constraintAction.action === "mark_not_applicable" ? "标记不适用" : "设为当前有效预算"}</strong><textarea className="textarea" rows={2} value={constraintActionReason} onChange={(event) => setConstraintActionReason(event.target.value)} placeholder="原因或说明（必填）" /><div className="work-item-actions"><button className="mini-button" onClick={() => setConstraintAction(null)}>取消</button><button className="mini-button active" disabled={!constraintActionReason.trim()} onClick={() => void actOnConstraint(constraint, constraintAction.action)}>确认</button></div></div> : null}{concludingConstraintId === constraint.id ? <div className="constraint-conclusion"><strong>登记当前有效结论</strong><select className="select" value={conclusionKind} onChange={(event) => setConclusionKind(event.target.value)}><option value="budget_determination">预算核定</option><option value="eligibility">准入判断</option><option value="filing">备案</option><option value="custom">自定义结果</option></select><input className="input" type="date" value={conclusionDate} onChange={(event) => setConclusionDate(event.target.value)} />{conclusionKind === "budget_determination" ? <input className="input" type="number" value={conclusionBudget} onChange={(event) => setConclusionBudget(event.target.value)} placeholder="核定预算（万元）" /> : null}<input className="input" value={conclusionResult} onChange={(event) => setConclusionResult(event.target.value)} placeholder={conclusionKind === "filing" ? "备案编号或结果" : "结论结果（可选）"} /><input className="input" value={conclusionReference} onChange={(event) => setConclusionReference(event.target.value)} placeholder="依据编号（可选）" /><textarea className="textarea" rows={2} value={conclusionNote} onChange={(event) => setConclusionNote(event.target.value)} placeholder="结论说明" /><label className="toggle"><input type="checkbox" checked={conclusionCleared} onChange={(event) => setConclusionCleared(event.target.checked)} /><span>该结论已解除当前阻断</span></label><div className="work-item-actions"><button className="mini-button" onClick={() => setConcludingConstraintId(null)}>取消</button><button className="mini-button active" onClick={() => void actOnConstraint(constraint, "conclude")}>保存结论</button></div></div> : null}{invalidatingConstraintId === constraint.id ? <div className="constraint-conclusion"><strong>使已有结论失效</strong><textarea className="textarea" rows={2} value={invalidationReason} onChange={(event) => setInvalidationReason(event.target.value)} placeholder="失效原因（必填）" /><div className="work-item-actions"><button className="mini-button" onClick={() => setInvalidatingConstraintId(null)}>取消</button><button className="mini-button danger" disabled={!invalidationReason.trim()} onClick={() => void actOnConstraint(constraint, "invalidate")}>确认失效</button></div></div> : null}</article>) : <div className="empty-state">尚无外部约束。无阻断性约束的项目默认计为外部条件已具备。</div>}</div>
            </section>

            <section className="detail-section detail-overview">
              <div className="section-title">
                <div><p className="section-kicker">PROJECT OVERVIEW</p><h2>项目概况</h2></div>
                <div className="work-item-actions"><button className="mini-button" onClick={() => { setEditingProject((value) => !value); setProjectEditErrors({}); setError(""); }}>编辑基本信息</button><button className="mini-button danger" onClick={() => setDeleteProjectOpen(true)}>移除项目</button></div>
              </div>
              {editingProject ? <div className="detail-add-item project-edit-form">
                <label className="field"><span>项目名称 <b aria-hidden="true">*</b></span><input ref={projectNameRef} className={`input ${projectEditErrors.name ? "input-error" : ""}`} value={project.name} onChange={(event) => { setProject({ ...project, name: event.target.value }); setProjectEditErrors((errors) => ({ ...errors, name: undefined })); }} aria-invalid={Boolean(projectEditErrors.name)} aria-describedby={projectEditErrors.name ? "project-name-error" : undefined} /></label>
                {projectEditErrors.name ? <small id="project-name-error" className="field-error">{projectEditErrors.name}</small> : null}
                <div className="field-grid"><input className="input" value={project.department ?? ""} onChange={(event) => setProject({ ...project, department: event.target.value })} placeholder="部门/学院" /><input className="input" value={project.major ?? ""} onChange={(event) => setProject({ ...project, major: event.target.value })} placeholder="所属专业" /></div><div className="field-grid"><input className="input" value={project.project_manager ?? ""} onChange={(event) => setProject({ ...project, project_manager: event.target.value })} placeholder="项目负责人" />{project.project_type === "laboratory" ? <input className="input" value={project.location ?? ""} onChange={(event) => setProject({ ...project, location: event.target.value })} placeholder="地点" /> : null}</div><label className="field"><span>项目分类</span><select className="select" value={project.project_type ?? ""} onChange={(event) => setProject({ ...project, project_type: event.target.value, procurement_nature: "", location: event.target.value === "laboratory" ? project.location : "" })}>{projectTypes.some((item) => item.code === project.project_type) ? null : <option value={project.project_type ?? ""}>{detailProjectTypeLabel(project.project_type)}</option>}{projectTypes.map((item) => <option key={item.id} value={item.code}>{item.name}</option>)}</select></label>{project.project_type === "software" ? <label className="field"><span>采购属性</span><select className="select" value={project.procurement_nature ?? ""} onChange={(event) => setProject({ ...project, procurement_nature: event.target.value as Project["procurement_nature"] })}><option value="">未设置</option><option value="goods">货物</option><option value="service">服务</option><option value="mixed">混合</option></select></label> : null}<label className="field"><span>初始预算（仅导入/录入纠错）</span><input className="input" type="number" value={project.budget ?? 0} onChange={(event) => setProject({ ...project, budget: Number(event.target.value) })} /></label><textarea className="textarea" rows={2} value={project.description ?? ""} onChange={(event) => setProject({ ...project, description: event.target.value })} placeholder="项目说明" />
                <label className="field"><span>修改理由 <b aria-hidden="true">*</b></span><textarea ref={projectReasonRef} className={`textarea ${projectEditErrors.reason ? "input-error" : ""}`} rows={2} value={projectReason} onChange={(event) => { setProjectReason(event.target.value); setProjectEditErrors((errors) => ({ ...errors, reason: undefined })); }} aria-invalid={Boolean(projectEditErrors.reason)} aria-describedby={projectEditErrors.reason ? "project-reason-error" : undefined} /></label>
                {projectEditErrors.reason ? <small id="project-reason-error" className="field-error">{projectEditErrors.reason}</small> : null}
                <button className="action-button primary" onClick={() => void saveProjectEdits()}>保存</button>
              </div> : null}
              <div className="detail-grid">
                <DetailField label="项目名称" value={project.name} />
                <DetailField label="项目编号" value={project.project_code} />
                <DetailField label="Stage" value={project.stage} />
                <DetailField label="申报部门" value={project.department} />
                <DetailField label="项目负责人" value={project.project_manager} />
                <DetailField label="项目分类摘要" value={project.project_summary_display} />
                <DetailField label="初始预算" value={`${formatCurrency(project.budget)} 万`} />
                <DetailField label="当前有效预算" value={`${formatCurrency(project.effective_budget ?? project.budget)} 万`} />
                <DetailField label="预算来源" value={project.effective_budget_source === "budget_constraint" ? "预算核定结果" : project.effective_budget_source === "historical_review" ? "历史审核预算" : "初始预算"} />
                <DetailField label="推进状态" value={project.advancement?.status === "special_active" ? "特批推进中" : project.advancement?.status === "active" ? "推进中" : "未纳入推进"} />
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

            <section className="detail-section detail-history">
              <div className="section-title">
                <p className="section-kicker">TIMELINE</p>
                <h2>历史记录</h2>
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
      {editingProgressLog || deletingProgressLog ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => { setEditingProgressLog(null); setDeletingProgressLog(null); }}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label={editingProgressLog ? "编辑进展" : "删除进展"} onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">WORK ITEM</p><h3>{editingProgressLog ? "编辑进展记录" : "删除进展记录"}</h3>
          <textarea className="textarea" rows={3} autoFocus value={progressDialogValue} onChange={(event) => setProgressDialogValue(event.target.value)} placeholder={editingProgressLog ? "进展内容" : "删除原因（必填）"} />
          <div className="dialog-actions"><button className="mini-button" onClick={() => { setEditingProgressLog(null); setDeletingProgressLog(null); }}>取消</button><button className={`action-button primary ${deletingProgressLog ? "danger-action" : ""}`} disabled={!progressDialogValue.trim()} onClick={() => void (editingProgressLog ? saveDetailProgress() : deleteDetailProgress())}>{editingProgressLog ? "保存修改" : "确认删除"}</button></div>
        </section>
      </div> : null}
      {itemAction ? <div className="system-dialog-backdrop" role="presentation" onMouseDown={() => setItemAction(null)}>
        <section className="system-dialog" role="dialog" aria-modal="true" aria-label={itemAction.action === "cancel" ? "取消事项" : "跳过主流程节点"} onMouseDown={(event) => event.stopPropagation()}>
          <p className="section-kicker">WORK ITEM</p><h3>{itemAction.action === "cancel" ? `取消“${itemAction.item.name}”` : `跳过“${itemAction.item.name}”`}</h3>
          <p className="muted-copy">{itemAction.action === "cancel" ? "事项将退出当前工作与下一关键节点计算，历史和审计会保留。" : "该主流程节点不再阻塞下一关键节点，历史和审计会保留。"}</p>
          <textarea className="textarea" rows={3} autoFocus value={itemActionReason} onChange={(event) => setItemActionReason(event.target.value)} placeholder="操作原因（必填）" />
          <div className="dialog-actions"><button className="mini-button" onClick={() => setItemAction(null)}>取消</button><button className={`action-button primary ${itemAction.action === "cancel" ? "danger-action" : ""}`} disabled={!itemActionReason.trim()} onClick={() => void submitItemAction()}>确认{itemAction.action === "cancel" ? "取消" : "跳过"}</button></div>
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
