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
  Fragment,
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
import AnnualBudgetView from "./AnnualBudgetView";
import ContractPanel from "./ContractPanel";
import ProjectFundingPanel from "./ProjectFundingPanel";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPostForm, buildExportUrl } from "./lib/api";
import { formatCurrency, formatDate, formatDateTime, projectTypeLabel, statusLabel, sumMoney } from "./lib/format";
import type {
  BatchExecuteResponse,
  AuditEvent,
  DashboardGroup,
  DashboardSummary,
  ImportCommitResponse,
  ImportPreviewResponse,
  Project,
  ProjectListResponse,
  WorkItem,
  WorkItemDraft,
  WorkItemProgressLog,
  WorkItemTemplate,
  WorkPackage,
  ExternalConstraintTemplate,
  ProjectTypeDefinition,
  DepartmentSetting,
  ProjectExternalConstraint,
  ExternalConstraintProgressLog,
  ExternalConstraintState,
  StageColumn,
  WorkItemActivity,
} from "./types";

const GROUP_ACCENTS: Record<string, string> = {
  pre_establish: "var(--accent-red)",
  pool_pending: "var(--accent-gold)",
  pool_active: "var(--accent-cyan)",
  completed: "var(--accent-green)",
  abandoned: "var(--accent-ink)",
};

const emptyDraft = (): WorkItemDraft => ({
  name: "", content: "", status: "not_started", planned_date: "",
  track_as_key_node: false, note: "", completion_effects: {}, insert_after_id: null,
  insert_mode: "after_current", save_as_common: false,
});
const today = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

const workStatusLabel = (status: string) => ({
  not_started: "待办理", in_progress: "进行中",
  completed: "已完成", paused: "暂停", not_applicable: "不适用",
}[status] ?? status);

const procurementNatureLabel = (value?: string | null) => ({ goods: "货物", service: "服务", mixed: "混合" } as Record<string, string>)[value || ""] ?? "未设置";

const sortProjectWorkItems = (items: WorkItem[]) => [...items];

const constraintStatusLabel = (status: string) => ({ not_started: "待办理", in_progress: "办理中", concluded: "已形成结论", invalidated: "结论失效" } as Record<string, string>)[status] ?? status;
const clearanceLabel = (status: string) => ({ unresolved: "待解除", cleared: "已解除", not_applicable: "不适用" } as Record<string, string>)[status] ?? status;
const constraintImpactLabel = (scope?: string) => ({ effective_budget: "影响有效预算", other: "其他影响", none: "不影响项目字段" } as Record<string, string>)[scope || "none"];
const parseEffectiveBudget = (value: string) => {
  const normalized = value.trim();
  return /^\d+(?:\.\d+)?$/.test(normalized) ? normalized : null;
};
const stageTone = (status: string, clearance?: string) => {
  if (status === "completed" || clearance === "cleared") return "complete";
  if (status === "in_progress" || status === "concluded") return "active";
  return "neutral";
};

function ContractCell({ project, onOpen }: { project: Project; onOpen: () => void }) {
  const supported = project.stage === "项目库—推进中" || project.stage === "已完成";
  if (!supported) return <span className="muted-copy">—</span>;
  const summary = project.contract_summary;
  if (!summary?.count) {
    return <button type="button" className="text-button contract-summary-link" onClick={(event) => { event.stopPropagation(); onOpen(); }}>暂无合同</button>;
  }
  return <button type="button" className="text-button contract-summary-link" onClick={(event) => { event.stopPropagation(); onOpen(); }}>{summary.contracts?.length ? summary.contracts.map((contract) => <span key={contract.id}>{contract.contract_no} · {contract.name} · {({ not_started: "未开始", performing: "履约中", completed: "已完成", terminated: "已解除", paused: "暂停" }[contract.status])}</span>) : summary.label}</button>;
}

const workItemStageFacts = (item: NonNullable<Project["work_item_column_states"]>[number]) => {
  if (item.status === "completed") return [workStatusLabel(item.status), item.completed_on ? `完成：${item.completed_on}` : "未记录完成日期", item.completion_result || item.completion_note || ""];
  if (["in_progress", "paused"].includes(item.status)) return [workStatusLabel(item.status), item.started_on ? `开始：${item.started_on}` : "未记录开始日期", ""];
  return [workStatusLabel(item.status), item.planned_date ? `计划：${item.planned_date}` : "未设置计划完成日期", ""];
};

const constraintStageFacts = (item: ExternalConstraintState) => {
  if (item.clearance_status === "cleared") return ["已解除", item.cleared_at ? `办结：${item.cleared_at.slice(0, 10)}` : "未记录解除日期", item.outcome_summary || ""];
  if (item.clearance_status === "not_applicable") return ["不适用", "已标记不适用", ""];
  if (item.handling_status === "concluded") return ["已形成结论", item.concluded_at ? `结论：${item.concluded_at}` : "未记录结论日期", item.outcome_summary || "待解除"];
  if (item.handling_status === "in_progress") return ["办理中", item.handling_started_on ? `开始：${item.handling_started_on}` : "未记录开始日期", item.latest_progress_summary || ""];
  if (item.handling_status === "invalidated") return ["结论失效", item.invalidated_at ? `失效：${item.invalidated_at.slice(0, 10)}` : "未记录失效日期", ""];
  return ["未开始", "未设置办理时间", ""];
};

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
  impactScope?: "none" | "effective_budget" | "other";
};

type OverviewColumn = "stage" | "document" | "implementation_year" | "completion_year" | "department" | "budget" | "summary" | "allocation" | "contract" | "progress" | "latest_activity";

const OVERVIEW_COLUMN_LABELS: Record<OverviewColumn, string> = {
  stage: "Stage", document: "立项文件", implementation_year: "实施年份", completion_year: "完成年份",
  department: "部门 / 负责人", budget: "预算", summary: "项目概括", allocation: "正式分配",
  contract: "合同", progress: "推进情况", latest_activity: "最新动态",
};

const DEFAULT_OVERVIEW_COLUMNS: OverviewColumn[] = [
  "stage", "document", "implementation_year", "department", "budget", "summary", "allocation", "contract", "progress", "latest_activity", "completion_year",
];

const overviewColumnsForStage = (stage: string): OverviewColumn[] => {
  if (stage === "pre_establish") return ["stage", "department", "budget", "summary", "progress", "latest_activity"];
  if (stage === "pool_pending") return ["stage", "document", "department", "budget", "progress", "latest_activity"];
  if (stage === "pool_active") return ["stage", "document", "implementation_year", "department", "budget", "allocation", "contract", "progress", "latest_activity"];
  if (stage === "completed") return ["stage", "document", "department", "budget", "allocation", "contract", "implementation_year", "completion_year"];
  return ["stage", "document", "department", "budget", "latest_activity"];
};

function ProgressSituation({ project, onSelect, onConstraintSelect }: { project: Project; onSelect?: (itemId: number) => void; onConstraintSelect?: () => void }) {
  const items = project.work_item_summary ?? [];
  const moreCount = Math.max((project.active_work_item_count ?? 0) - items.length, 0);
  const constraintCount = project.external_constraint_count ?? 0;
  const ready = project.external_constraints_cleared === "true";
  const summary = ready ? `外部约束 · ${constraintCount} 项` : `外部约束待处理 · ${project.external_constraint_open_count ?? 0}/${constraintCount} 项`;
  const externalConditionClass = ready ? "external-ready" : "external-pending";
  if (!items.length && !constraintCount) return <div className="progress-summary progress-situation"><span className="muted-copy">暂无待推进事项</span></div>;
  return <div className="progress-summary progress-situation">
    {constraintCount ? <button type="button" className={externalConditionClass} onClick={onConstraintSelect}><strong>{summary}</strong></button> : null}
    {items.map((item) => <button type="button" key={item.id} onClick={() => onSelect?.(item.id)}><strong>{item.track_as_key_node ? "☆ " : ""}{item.name}</strong><small>{workStatusLabel(item.status)}{item.planned_date ? ` · ${item.planned_date}` : ""}</small></button>)}
    {moreCount ? <em>+{moreCount}</em> : null}
  </div>;
}

function StageItemCell({ project, column, onWorkItemSelect, onConstraintSelect, onActivitySelect, highlighted }: { project: Project; column: StageColumn; onWorkItemSelect?: (id: number) => void; onConstraintSelect?: (id: number) => void; onActivitySelect?: (id: number) => void; highlighted?: boolean }) {
  if (column.kind === "external_constraint") {
    const constraint = project.external_constraint_states?.find((item) => constraintMatchesColumn(item, column.key));
    if (!constraint) return <span className="muted-copy">—</span>;
    const [status, fact, detail] = constraintStageFacts(constraint);
    return <button type="button" aria-label={`办理外部约束 ${constraint.name}：${status}`} className={`stage-business-cell stage-constraint-cell tone-${stageTone(constraint.handling_status, constraint.clearance_status)}${highlighted ? " column-batch-highlight" : ""}`} onClick={() => onConstraintSelect?.(constraint.id)}><strong>{status}</strong><span>{fact}</span>{detail ? <em title={detail}>{detail}</em> : null}</button>;
  }
  const item = project.work_item_column_states?.find((candidate) => candidate.name === column.key);
  if (!item) return <span className="muted-copy">—</span>;
  const [status, fact, detail] = workItemStageFacts(item);
  const activities = item.activity_summaries || [];
  return <div className={`stage-business-cell stage-item-cell tone-${stageTone(item.status)}${highlighted ? " column-batch-highlight" : ""}`}><button type="button" aria-label={`办理事项 ${item.name}：${status}`} onClick={() => onWorkItemSelect?.(item.id)}><strong>{item.track_as_key_node ? "☆ " : ""}{status}</strong><span>{fact}</span>{detail ? <em title={detail}>{detail}</em> : null}</button>{activities.slice(0, 2).map((activity) => <button type="button" key={activity.id} className="activity-chip" onClick={() => onActivitySelect?.(activity.id)}>{activity.scheduled_on ? `${activity.scheduled_on} · ` : ""}{activity.name}</button>)}{activities.length > 2 ? <button type="button" className="activity-chip" onClick={() => onActivitySelect?.(activities[0].id)}>+{activities.length - 2} 个活动</button> : null}</div>;
}

function constraintSummary(constraint: ProjectExternalConstraint) {
  const outcome = constraint.outcome_json || {};
  if (typeof outcome.approved_budget === "number") return `核定 ${formatCurrency(outcome.approved_budget)} 万`;
  return typeof outcome.result === "string" && outcome.result ? outcome.result : "暂无结论";
}

type ManagedTemplate = { id: number; name: string; archived_at?: string | null; default_content?: string; recommended_stage?: string; stage_view_priority?: number | null; flow_group?: "main" | "independent"; execution_mode?: string; impact_scope?: "none" | "effective_budget" | "other"; impact_note?: string; scope_kind?: string; scope_value?: string };
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
  const [impactScope, setImpactScope] = useState<"none" | "effective_budget" | "other">("none");
  const [impactNote, setImpactNote] = useState("");
  const [scopeKind, setScopeKind] = useState("all");
  const [scopeValue, setScopeValue] = useState("");
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
    try { await apiPatch(path(editing, "restore").replace("/restore", ""), { operator, name: name.trim(), ...(kind === "work-item" ? { default_content: defaultContent, recommended_stage: recommendedStage, stage_view_priority: stageViewPriority ? Number(stageViewPriority) : null } : {}), ...(kind === "external-constraint" ? { scope_kind: scopeKind, scope_value: scopeKind === "project_type" ? scopeValue : "", impact_scope: impactScope, impact_note: impactNote } : {}) }); setEditing(null); setName(""); await onRefresh(); }
    catch (err) { onError(err instanceof ApiError ? err.message : "模板未更新，页面保持原状。"); }
  }
  return <div className="template-manager" data-interactive>
    <div className="template-manager-heading"><strong>模板治理</strong><button className="text-button" onClick={() => setShowArchived((value) => !value)}>{showArchived ? "仅看启用" : "查看归档"}</button></div>
    {visible.map((item) => <div key={item.id}><span>{item.name}{item.archived_at ? " · 已归档" : ""}</span><aside>{item.archived_at ? <><button className="text-button" onClick={() => void restore(item)}>恢复</button><button className="text-button danger" onClick={() => setDeleting(item)}>永久删除</button></> : <><button className="text-button" onClick={() => { setEditing(item); setName(item.name); setDefaultContent(item.default_content || ""); setRecommendedStage(item.recommended_stage || ""); setStageViewPriority(item.stage_view_priority ? String(item.stage_view_priority) : ""); setImpactScope(item.impact_scope || "none"); setImpactNote(item.impact_note || ""); setScopeKind(item.scope_kind || "all"); setScopeValue(item.scope_value || ""); }}>编辑</button><button className="text-button" onClick={() => void onArchive(kind, item.id, item.name)}>归档</button></>}</aside></div>)}
    {!visible.length ? <small>当前没有符合条件的模板。</small> : null}
    {deleting ? <section className="template-confirm"><strong>永久删除“{deleting.name}”</strong><p>仅从未被引用的模板可永久删除；已有历史引用将被服务器拒绝。</p><textarea className="textarea" rows={2} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="删除原因（必填）" /><div><button className="mini-button" onClick={() => setDeleting(null)}>取消</button><button className="mini-button danger" disabled={!reason.trim()} onClick={() => void remove()}>确认永久删除</button></div></section> : null}
    {editing ? <section className="template-confirm"><strong>编辑常用模板</strong><input className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="模板名称" />{kind === "work-item" ? <><textarea className="textarea" rows={2} value={defaultContent} onChange={(event) => setDefaultContent(event.target.value)} placeholder="默认事项内容" /><div className="field-grid"><select className="select" value={recommendedStage} onChange={(event) => setRecommendedStage(event.target.value)}><option value="">不推荐特定 Stage</option><option value="未立项">未立项</option><option value="项目库—未实施">项目库—未实施</option><option value="项目库—推进中">项目库—推进中</option></select><input className="input" type="number" value={stageViewPriority} onChange={(event) => setStageViewPriority(event.target.value)} placeholder="阶段跟踪排序（留空不推荐）" /></div></> : null}{kind === "external-constraint" ? <><label className="field"><span>适用范围</span><select className="select" value={scopeKind} onChange={(event) => setScopeKind(event.target.value)}><option value="all">全部项目</option><option value="project_type">指定项目分类</option></select></label>{scopeKind === "project_type" ? <select className="select" value={scopeValue} onChange={(event) => setScopeValue(event.target.value)}><option value="">选择项目分类</option>{projectTypes.filter((item) => item.is_active).map((item) => <option value={item.code} key={item.id}>{item.name}</option>)}</select> : null}<label className="field"><span>影响范围</span><select className="select" value={impactScope} onChange={(event) => setImpactScope(event.target.value as typeof impactScope)}><option value="none">不影响项目字段</option><option value="effective_budget">影响有效预算</option><option value="other">其他影响</option></select></label>{impactScope === "other" ? <input className="input" value={impactNote} onChange={(event) => setImpactNote(event.target.value)} placeholder="影响说明（必填）" /> : null}</> : null}<p>修改只影响后续新建或下发；项目中的既有事项保持自身快照。</p><div><button className="mini-button" onClick={() => setEditing(null)}>取消</button><button className="mini-button" disabled={!name.trim() || (kind === "external-constraint" && (scopeKind === "project_type" && !scopeValue || impactScope === "other" && !impactNote.trim()))} onClick={() => void saveName()}>保存</button></div></section> : null}
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
  const [sortBy, setSortBy] = useState<string>("department");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filterOptions, setFilterOptions] = useState<ProjectListResponse["filter_options"]>({});
  const [keyword, setKeyword] = useState("");
  const deferredKeyword = useDeferredValue(keyword);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedProjectSnapshots, setSelectedProjectSnapshots] = useState<Record<number, Project>>({});
  const [selectedListOpen, setSelectedListOpen] = useState(false);
  const [selectedTarget, setSelectedTarget] = useState<string>("");
  // These remain internal audit values.  PMO's project contact is represented
  // by project_manager; workflow role fields are deliberately not a daily UI
  // input.
  const operator = "PMO办公室";
  const approver = "PMO办公室";
  const [comment, setComment] = useState("");
  const [advancementYear, setAdvancementYear] = useState(String(new Date().getFullYear()));
  const [backfillClearZeroBudget, setBackfillClearZeroBudget] = useState(false);
  const earlyApprovalBasis = "PMO办公室（前端隐藏审批依据）";
  const [annualExceptionAction, setAnnualExceptionAction] = useState<"supplement" | "cancel" | "defer" | "resume" | "special">("supplement");
  const [establishmentDocumentNo, setEstablishmentDocumentNo] = useState("");
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
  const [quickConstraintAction, setQuickConstraintAction] = useState<"clear" | "mark_not_applicable" | "invalidate" | null>(null);
  const [quickConstraintActionText, setQuickConstraintActionText] = useState("");
  const [quickConstraintBudget, setQuickConstraintBudget] = useState("");
  const [quickConstraintBudgetError, setQuickConstraintBudgetError] = useState("");
  const quickConstraintBudgetRef = useRef<HTMLInputElement>(null);
  const [showAllQuickLogs, setShowAllQuickLogs] = useState(false);
  const [quickProgress, setQuickProgress] = useState("");
  const [quickCompletionResult, setQuickCompletionResult] = useState("");
  const [quickCompleting, setQuickCompleting] = useState(false);
  const [quickCorrectingCompletion, setQuickCorrectingCompletion] = useState(false);
  const [quickSupplementingNote, setQuickSupplementingNote] = useState(false);
  const [quickCompletionDate, setQuickCompletionDate] = useState(today());
  const [quickCompletionNote, setQuickCompletionNote] = useState("");
  const [contractPanel, setContractPanel] = useState<null | { projectId?: number; projectIds: number[]; contractId?: number; contextProject?: Project }>(null);
  const [draftItems, setDraftItems] = useState<WorkItemDraft[]>([emptyDraft()]);
  const [packageName, setPackageName] = useState("");
  const [templates, setTemplates] = useState<WorkItemTemplate[]>([]);
  const [packages, setPackages] = useState<WorkPackage[]>([]);
  const [constraintTemplates, setConstraintTemplates] = useState<ExternalConstraintTemplate[]>([]);
  const [constraintTemplateId, setConstraintTemplateId] = useState<number | null>(null);
  const [constraintName, setConstraintName] = useState("");
  const [constraintImpactScope, setConstraintImpactScope] = useState<"none" | "effective_budget" | "other">("none");
  const [constraintImpactNote, setConstraintImpactNote] = useState("");
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
  const [draggedProjectTypeId, setDraggedProjectTypeId] = useState<number | null>(null);
  const [draggedDepartment, setDraggedDepartment] = useState<string | null>(null);
  const [templateManager, setTemplateManager] = useState<"items" | "packages" | "constraints" | null>(null);
  const [selectedPackageId, setSelectedPackageId] = useState<number | null>(null);
  const [editingPackage, setEditingPackage] = useState(false);
  const [packageEditName, setPackageEditName] = useState("");
  const [packageEditItems, setPackageEditItems] = useState<WorkItemDraft[]>([]);
  const [draggedPackageItem, setDraggedPackageItem] = useState<number | null>(null);
  const [templateKeyword, setTemplateKeyword] = useState("");
  const [dialog, setDialog] = useState<null | { kind: "edit-log" | "delete-log" | "archive-template" | "reopen"; title: string; value: string; target?: WorkItemProgressLog | ExternalConstraintProgressLog | WorkItem; template?: { kind: "work-item" | "work-package" | "external-constraint"; id: number; name: string } }>(null);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [newProject, setNewProject] = useState({ name: "", department: "", project_manager: "", project_type: "", procurement_nature: "", location: "", budget: "", description: "" });
  const [tableView, setTableView] = useState<"overview" | "stage" | "annual">("overview");
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const [overviewColumnPickerOpen, setOverviewColumnPickerOpen] = useState(false);
  const [columnSearch, setColumnSearch] = useState("");
  const [columnBatchTarget, setColumnBatchTarget] = useState<ColumnBatchTarget | null>(null);
  const [workItemActivity, setWorkItemActivity] = useState<WorkItemActivity | null>(null);
  const [batchArrangeOpen, setBatchArrangeOpen] = useState(false);
  const [batchDraft, setBatchDraft] = useState({ name: "", scheduled_on: "", note: "" });
  const [activityJoinChoices, setActivityJoinChoices] = useState<WorkItemActivity[]>([]);
  const [activityResult, setActivityResult] = useState({ result_on: today(), result: "", note: "" });
  const [activityProgress, setActivityProgress] = useState("");
  const [activityEditingProgressId, setActivityEditingProgressId] = useState<number | null>(null);
  const [activityMemberManaging, setActivityMemberManaging] = useState(false);
  const [activityMembersOnly, setActivityMembersOnly] = useState(true);
  const [activityMemberReason, setActivityMemberReason] = useState("");
  const [activityEditOpen, setActivityEditOpen] = useState(false);
  const [activityEditDraft, setActivityEditDraft] = useState({ name: "", scheduled_on: "", note: "" });
  const [activityNextGroups, setActivityNextGroups] = useState<Array<{ name: string; count: number; project_ids: number[] }>>([]);
  const [activityVoidOpen, setActivityVoidOpen] = useState(false);
  const [batchHistoryOpen, setBatchHistoryOpen] = useState(false);
  const [batchHistory, setBatchHistory] = useState<WorkItemActivity[]>([]);
  const [batchHistoryFilters, setBatchHistoryFilters] = useState({ year: "", keyword: "", status: "" });
  const [batchReturnMode, setBatchReturnMode] = useState<"batch" | "stage">("batch");
  const [columnWorkItemAction, setColumnWorkItemAction] = useState<"progress" | "update" | "complete">("progress");
  const [columnBatchValue, setColumnBatchValue] = useState({ progress_content: "", status: "", planned_date: "", track_as_key_node: "", completed_on: today(), result: "", note: "" });
  const [columnBatchPreview, setColumnBatchPreview] = useState<{ eligible: Array<{ project_id: number; project_code: string; name: string; work_item_id?: number; constraint_id?: number; outcome_kind?: string }>; ineligible: Array<{ project_id: number; name?: string; message: string }> } | null>(null);
  const [visibleColumnsByStage, setVisibleColumnsByStage] = useState<Record<string, StageColumn[]>>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem("pmo-stage-columns-v2") || "{}") as Record<string, Array<StageColumn | string>>;
      return Object.fromEntries(Object.entries(raw).map(([stage, columns]) => [stage, columns.map((column) => typeof column === "string" ? { kind: "work_item", key: column, label: column } : column)]));
    } catch { return {}; }
  });
  const [overviewColumnsByStage, setOverviewColumnsByStage] = useState<Record<string, OverviewColumn[]>>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem("pmo-overview-columns-v3") || "{}");
      if (raw && typeof raw === "object" && !Array.isArray(raw)) {
        return Object.fromEntries(Object.entries(raw as Record<string, unknown>).flatMap(([stage, columns]) =>
          Array.isArray(columns) && columns.every((column) => typeof column === "string" && column in OVERVIEW_COLUMN_LABELS)
            ? [[stage, columns as OverviewColumn[]]] : [],
        ));
      }
      const legacy = JSON.parse(localStorage.getItem("pmo-overview-columns-v2") || "[]");
      return Array.isArray(legacy) && legacy.every((column) => typeof column === "string" && column in OVERVIEW_COLUMN_LABELS)
        ? { legacy: legacy as OverviewColumn[] } : {};
    } catch { return {}; }
  });
  const columnHeaderClickTimer = useRef<number | null>(null);

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
      setFilterOptions(projectData.filter_options ?? {});
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
    startTransition(() => {
      setSelectedTarget("");
    });
  }, [activeGroup, selectedProjectType, selectedDepartment, selectedExternalConditions, selectedImplementationYear, sortBy, sortDir, deferredKeyword]);

  const selectedProjects = useMemo(
    () => selectedIds.map((id) => selectedProjectSnapshots[id]).filter((project): project is Project => Boolean(project)),
    [selectedIds, selectedProjectSnapshots],
  );
  const selectedEffectiveBudget = useMemo(
    () => sumMoney(selectedProjects.map((project) => project.effective_budget ?? project.budget)),
    [selectedProjects],
  );
  const directStageAction = useMemo<"establish" | "complete" | null>(() => {
    if (!selectedProjects.length) return null;
    if (selectedProjects.every((project) => project.stage === "未立项")) return "establish";
    if (selectedProjects.every((project) => project.stage === "项目库—推进中")) return "complete";
    return null;
  }, [selectedProjects]);

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

  const implementationYearOptions = useMemo(() => Array.from(new Set([...(filterOptions?.implementation_years ?? []), selectedImplementationYear].filter(Boolean))).sort((a, b) => Number(b) - Number(a)), [filterOptions, selectedImplementationYear]);
  const filterDepartments = useMemo(() => Array.from(new Set([...(filterOptions?.departments ?? []), selectedDepartment].filter(Boolean))), [filterOptions, selectedDepartment]);
  const filterProjectTypes = useMemo(() => new Set([...(filterOptions?.project_types ?? []), selectedProjectType].filter(Boolean)), [filterOptions, selectedProjectType]);
  const showImplementationFilter = activeGroup === "completed";
  const showImplementationYearColumn = !showRemoved && (activeGroup === "pool_active" || activeGroup === "completed");
  const showCompletionYearColumn = !showRemoved && activeGroup === "completed";
  const showProgressColumn = tableView === "overview" && !showCompletionYearColumn;
  const overviewPreferenceStage = showRemoved ? "removed" : activeGroup;
  const overviewAllowedColumns = useMemo<OverviewColumn[]>(() => {
    const allowed = new Set<OverviewColumn>(["stage", "department", "budget", "latest_activity"]);
    if (!showRemoved && activeGroup !== "pre_establish") allowed.add("document");
    if (!showRemoved && activeGroup === "pre_establish") allowed.add("summary");
    if (showImplementationYearColumn) allowed.add("implementation_year");
    if (showCompletionYearColumn) allowed.add("completion_year");
    if (!showRemoved && activeGroup !== "pre_establish" && activeGroup !== "pool_pending") allowed.add("allocation");
    if (!showRemoved && (activeGroup === "pool_active" || activeGroup === "completed")) allowed.add("contract");
    if (showProgressColumn) allowed.add("progress");
    if (showCompletionYearColumn) allowed.delete("latest_activity");
    return DEFAULT_OVERVIEW_COLUMNS.filter((column) => allowed.has(column));
  }, [activeGroup, showCompletionYearColumn, showImplementationYearColumn, showProgressColumn, showRemoved]);
  const overviewColumns = useMemo<OverviewColumn[]>(() => {
    const saved = overviewColumnsByStage[overviewPreferenceStage] ?? overviewColumnsByStage.legacy ?? overviewColumnsForStage(overviewPreferenceStage);
    return saved.filter((column) => overviewAllowedColumns.includes(column));
  }, [overviewAllowedColumns, overviewColumnsByStage, overviewPreferenceStage]);
  const overviewContextColumns = useMemo<OverviewColumn[]>(() => {
    const ordered = overviewColumns;
    if (showCompletionYearColumn) {
      return [...ordered.filter((column) => column !== "implementation_year" && column !== "completion_year"), "implementation_year", "completion_year"];
    }
    if (showProgressColumn) {
      return [...ordered.filter((column) => column !== "progress" && column !== "latest_activity"), "progress", "latest_activity"];
    }
    return ordered;
  }, [overviewColumns, showCompletionYearColumn, showProgressColumn]);

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
    setSortDir(nextSortBy === "implementation_year" || nextSortBy === "completion_year" ? "desc" : "asc");
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
  const isBatchBudgetDetermination = batchConstraintAction === "clear" && selectedConstraintTemplate?.impact_scope === "effective_budget";

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
  const stageStaticColumnCount = 1
    + (activeGroup !== "pre_establish" && !showRemoved ? 1 : 0)
    + (showImplementationYearColumn ? 1 : 0)
    + (showCompletionYearColumn ? 1 : 0)
    + 1 // department
    + 1 // budget
    + (activeGroup !== "pre_establish" && activeGroup !== "pool_pending" && !showRemoved ? 1 : 0)
    + (activeGroup !== "completed" ? 1 : 0); // latest activity
  const tableColumnCount = 2 + (tableView === "overview" ? overviewContextColumns.length : stageStaticColumnCount + stageColumns.length);

  function columnTargetFor(column: StageColumn): ColumnBatchTarget | null {
    const instances: Record<number, number> = {};
    let templateId: number | undefined;
    let outcomeKind: string | undefined;
    let impactScope: ColumnBatchTarget["impactScope"];
    for (const project of projects) {
      if (column.kind === "work_item") {
        const item = (project.work_item_column_states ?? []).find((candidate) => candidate.name === column.key && candidate.actionable);
        if (item) instances[project.id] = item.id;
      } else {
        const constraint = (project.external_constraint_states ?? []).find((candidate) => constraintMatchesColumn(candidate, column.key)
          && candidate.clearance_status !== "not_applicable" && candidate.handling_status !== "invalidated");
        if (constraint) {
          instances[project.id] = constraint.id;
          templateId ??= constraint.template_id ?? undefined;
          outcomeKind ??= constraint.outcome_kind;
          impactScope ??= constraint.impact_scope;
        }
      }
    }
    return Object.keys(instances).length ? { kind: column.kind, key: column.key, label: column.label, instances, templateId, outcomeKind, impactScope } : null;
  }

  function clearColumnBatchTarget() {
    if (!columnBatchTarget) return;
    setColumnBatchTarget(null);
    setColumnBatchPreview(null);
    setSelectedIds([]);
    setSelectedProjectSnapshots({});
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

  function saveOverviewColumns(columns: OverviewColumn[]) {
    const unique = [...new Set(columns)].filter((column) => overviewAllowedColumns.includes(column));
    setOverviewColumnsByStage((current) => {
      const result = { ...current, [overviewPreferenceStage]: unique };
      localStorage.setItem("pmo-overview-columns-v3", JSON.stringify(result));
      return result;
    });
  }

  function resetOverviewColumns() {
    saveOverviewColumns(overviewColumnsForStage(overviewPreferenceStage));
  }

  function moveOverviewColumn(from: number, to: number) {
    if (from === to) return;
    const next = [...overviewColumns];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    saveOverviewColumns(next);
  }

  function selectColumnBatch(column: StageColumn, mode: "manual" | "all") {
    const target = columnTargetFor(column);
    if (columnBatchTarget?.kind === column.kind && columnBatchTarget.key === column.key) {
      if (mode === "manual") clearColumnBatchTarget();
      else {
        const targetProjects = projects.filter((project) => Boolean(columnBatchTarget.instances[project.id]));
        setSelectedIds(targetProjects.map((project) => project.id));
        setSelectedProjectSnapshots(Object.fromEntries(targetProjects.map((project) => [project.id, project])));
      }
      return;
    }
    if (!target) { setFeedback("该列当前没有可批量办理的实例。"); return; }
    const targetProjects = mode === "all" ? projects.filter((project) => Boolean(target.instances[project.id])) : [];
    setColumnBatchTarget(target);
    setSelectedIds(targetProjects.map((project) => project.id));
    setSelectedProjectSnapshots(Object.fromEntries(targetProjects.map((project) => [project.id, project])));
    setColumnBatchPreview(null);
    setRailExpanded(true);
  }

  async function openWorkItemActivity(activityId: number, returnMode: "batch" | "stage" = "batch") {
    try {
      const activity = await apiGet<WorkItemActivity>(`/work-item-activities/${activityId}`);
      setBatchReturnMode(returnMode);
      setWorkItemActivity(activity);
      setActivityMembersOnly(true); setActivityMemberManaging(false); setActivityMemberReason(""); setActivityProgress(""); setActivityEditingProgressId(null); setActivityEditOpen(false); setActivityNextGroups([]); setActivityVoidOpen(false);
      setTableView("stage");
      setSelectedIds(activity.members.filter((member) => member.member_status === "active" && ["not_started", "in_progress"].includes(member.work_item_status)).map((member) => member.project_id));
      setRailExpanded(true);
    } catch (err) { setError(err instanceof ApiError ? err.message : "无法打开办理活动。"); }
  }

  async function createWorkItemActivity() {
    if (!columnBatchTarget || columnBatchTarget.kind !== "work_item") return;
    try {
      const activity = await apiPost<WorkItemActivity>("/work-item-activities", { ...batchDraft, work_item_name: columnBatchTarget.label, operator, targets: columnTargetsPayload() });
      setBatchArrangeOpen(false); setBatchDraft({ name: "", scheduled_on: "", note: "" }); setFeedback("办理活动已安排；事项状态未改变。");
      await openWorkItemActivity(activity.id); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "办理活动未创建，请检查所选事项。"); }
  }

  async function loadActivityJoinChoices() {
    if (!columnBatchTarget || columnBatchTarget.kind !== "work_item") return;
    try {
      const query = `work_item_name=${encodeURIComponent(columnBatchTarget.label)}`;
      const [pending, active] = await Promise.all([
        apiGet<{ items: WorkItemActivity[] }>(`/work-item-activities?status=not_started&${query}`),
        apiGet<{ items: WorkItemActivity[] }>(`/work-item-activities?status=in_progress&${query}`),
      ]);
      setActivityJoinChoices([...pending.items, ...active.items]);
    } catch (err) { setError(err instanceof ApiError ? err.message : "可加入的办理活动加载失败。"); }
  }

  async function joinWorkItemActivity(activity: WorkItemActivity) {
    if (!columnBatchTarget || columnBatchTarget.kind !== "work_item") return;
    try {
      const updated = await apiPost<WorkItemActivity>(`/work-item-activities/${activity.id}/members`, { operator, targets: columnTargetsPayload() });
      setBatchArrangeOpen(false); setFeedback("已将所选事项加入办理活动；事项状态未改变。");
      setWorkItemActivity(updated); await openWorkItemActivity(updated.id); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "所选事项未加入办理活动。请检查是否已加入、已完成或不可办理。"); }
  }

  function activityMemberTargets() {
    if (!workItemActivity) return [];
    return selectedIds.map((projectId) => {
      const item = projects.find((project) => project.id === projectId)?.work_item_column_states?.find((candidate) => candidate.name === workItemActivity.work_item_name && candidate.actionable);
      return item ? { project_id: projectId, work_item_id: item.id } : null;
    }).filter((target): target is { project_id: number; work_item_id: number } => Boolean(target));
  }

  async function saveActivityProgress() {
    if (!workItemActivity || !activityProgress.trim()) { setError("请填写活动进展。"); return; }
    try {
      const path = activityEditingProgressId == null
        ? `/work-item-activities/${workItemActivity.id}/progress-logs`
        : `/work-item-activities/${workItemActivity.id}/progress-logs/${activityEditingProgressId}`;
      const activity = activityEditingProgressId == null
        ? await apiPost<WorkItemActivity>(path, { operator, content: activityProgress.trim() })
        : await apiPatch<WorkItemActivity>(path, { operator, content: activityProgress.trim() });
      setWorkItemActivity(activity); setActivityProgress(""); setActivityEditingProgressId(null); setFeedback("活动进展已保存。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "活动进展未保存。"); }
  }

  async function deleteActivityProgress(logId: number) {
    if (!workItemActivity || !activityMemberReason.trim()) { setError("删除活动进展必须填写原因。"); return; }
    try {
      const activity = await apiDelete<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/progress-logs/${logId}`, { operator, reason: activityMemberReason.trim() });
      setWorkItemActivity(activity); setActivityMemberReason(""); setFeedback("活动进展已删除，原记录仍保留在审计中。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "活动进展未删除。"); }
  }

  async function saveActivityEdit() {
    if (!workItemActivity || !activityEditDraft.name.trim()) { setError("请填写活动名称。"); return; }
    try {
      const activity = await apiPatch<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}`, { operator, ...activityEditDraft, name: activityEditDraft.name.trim() });
      setWorkItemActivity(activity); setActivityEditOpen(false); setFeedback("活动信息已更新。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "活动信息未更新。"); }
  }

  async function updateActivityMembers(action: "add" | "remove") {
    if (!workItemActivity) return;
    const memberIds = workItemActivity.members.filter((member) => selectedIds.includes(member.project_id) && member.member_status === "active").map((member) => member.id);
    const targets = activityMemberTargets();
    if (action === "add" && !targets.length) { setError("所选项目没有可加入的同名待办理事项。"); return; }
    if (action === "remove" && (!memberIds.length || !activityMemberReason.trim())) { setError("请选择活动成员并填写移出原因。"); return; }
    try {
      const activity = action === "add"
        ? await apiPost<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/members`, { operator, targets })
        : await apiPost<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/members/remove`, { operator, member_ids: memberIds, reason: activityMemberReason.trim() });
      setWorkItemActivity(activity); setActivityMemberReason(""); setSelectedIds(activity.members.filter((member) => member.member_status === "active").map((member) => member.project_id)); setFeedback(action === "add" ? "已加入活动成员。" : "已移出活动成员，原因已记录。"); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "成员管理未保存，活动保持原状。"); }
  }

  async function executeActivityWorkItemAction() {
    if (!workItemActivity) return;
    const selectedMembers = workItemActivity.members.filter((member) => selectedIds.includes(member.project_id) && member.member_status === "active" && ["not_started", "in_progress"].includes(member.work_item_status));
    const targets = selectedMembers.map((member) => ({ project_id: member.project_id, work_item_id: member.work_item_id }));
    if (!targets.length) { setError("请选择活动中可办理的项目。"); return; }
    if (columnWorkItemAction === "progress" && !columnBatchValue.progress_content.trim()) { setError("请填写共同进展。"); return; }
    if (columnWorkItemAction === "update" && !columnBatchValue.status && !columnBatchValue.planned_date && columnBatchValue.track_as_key_node === "") { setError("请至少填写一项要更新的事项设置。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ processed_targets: Array<{ project_id: number }> }>("/projects/batch-work-item-actions", { project_ids: targets.map((target) => target.project_id), targets, action: columnWorkItemAction, operator, defaults: columnWorkItemDefaults() });
      await refreshSelectedProjects(result.processed_targets.map((target) => target.project_id));
      const activity = await apiGet<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}`);
      setWorkItemActivity(activity); setFeedback(columnWorkItemAction === "complete" ? "所选事项已完成；当前活动与项目选择保留，可继续安排后续事项。" : "已完成所选活动成员的事项办理。");
      if (columnWorkItemAction === "complete") {
        const next = await apiPost<{ groups: Array<{ name: string; count: number; project_ids: number[] }> }>(`/work-item-activities/${workItemActivity.id}/next-groups`, { operator, member_ids: selectedMembers.map((member) => member.id) });
        setActivityNextGroups(next.groups);
      }
    } catch (err) { setError(err instanceof ApiError ? err.message : "活动内事项办理失败，所有项目保持原状。"); }
    finally { setExecuting(false); }
  }

  async function recordActivityFollowUp(action: "next" | "rehandle" | "hold", projectIds = selectedIds) {
    if (!workItemActivity) return;
    const memberIds = workItemActivity.members.filter((member) => projectIds.includes(member.project_id) && member.member_status === "active").map((member) => member.id);
    if (!memberIds.length) { setError("请选择活动成员。"); return; }
    try {
      const activity = await apiPost<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/follow-up`, { operator, member_ids: memberIds, action });
      setWorkItemActivity(activity);
      if (action === "next") { setSelectedIds(projectIds); setWorkItemActivity(null); setTableView("stage"); setFeedback("已保留项目选择，请在阶段跟踪选择下一事项列后安排办理活动。"); }
      else setFeedback(action === "rehandle" ? "已记录重新办理当前事项；事项状态未改变。" : "已记录暂不安排；事项状态未改变。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "后续处理未保存。"); }
  }

  async function voidCurrentActivity() {
    if (!workItemActivity || !activityMemberReason.trim()) { setError("作废办理活动必须填写原因。"); return; }
    try {
      const activity = await apiPost<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/void`, { operator, reason: activityMemberReason.trim() });
      setWorkItemActivity(activity); setActivityVoidOpen(false); setActivityMemberReason(""); setFeedback("办理活动已作废；成员和已登记结果已保留历史。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "办理活动未作废。"); }
  }

  async function recordCurrentActivityResults() {
    if (!workItemActivity) return;
    const memberIds = workItemActivity.members.filter((member) => selectedIds.includes(member.project_id) && member.member_status === "active").map((member) => member.id);
    try {
      const activity = await apiPost<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/results`, { operator, member_ids: memberIds, ...activityResult });
      setWorkItemActivity(activity); setFeedback("已记录所选项目本次办理结果；事项状态未改变。"); await loadDashboard();
    } catch (err) { setError(err instanceof ApiError ? err.message : "活动结果登记失败，未写入任何事项。"); }
  }

  async function loadBatchHistory() {
    const params = new URLSearchParams();
    if (batchHistoryFilters.year) params.set("year", batchHistoryFilters.year);
    if (batchHistoryFilters.keyword) params.set("keyword", batchHistoryFilters.keyword);
    if (batchHistoryFilters.status) params.set("status", batchHistoryFilters.status);
    try { const result = await apiGet<{ items: WorkItemActivity[] }>(`/work-item-activities?${params}`); setBatchHistory(result.items); setBatchHistoryOpen(true); }
    catch (err) { setError(err instanceof ApiError ? err.message : "办理活动记录加载失败。"); }
  }

  function queueColumnBatchSelection(column: StageColumn) {
    if (columnHeaderClickTimer.current != null) window.clearTimeout(columnHeaderClickTimer.current);
    columnHeaderClickTimer.current = window.setTimeout(() => {
      selectColumnBatch(column, "manual");
      columnHeaderClickTimer.current = null;
    }, 220);
  }

  function selectAllColumnBatch(column: StageColumn) {
    if (columnHeaderClickTimer.current != null) window.clearTimeout(columnHeaderClickTimer.current);
    columnHeaderClickTimer.current = null;
    selectColumnBatch(column, "all");
  }

  function overviewTableHeader(column: OverviewColumn) {
    if (column === "implementation_year" || column === "completion_year" || column === "department" || column === "latest_activity") {
      const sortField = column === "department" ? "department" : column === "latest_activity" ? "latest_activity_at" : column;
      return <th key={column} className={column === "department" ? "department-column" : column === "latest_activity" ? "updated-date" : "year-column"}><button className="sort-button" onClick={() => toggleSort(sortField)}>{OVERVIEW_COLUMN_LABELS[column]} {sortLabel(sortField)}</button></th>;
    }
    return <th key={column} className={column === "progress" ? "progress-column" : column === "contract" ? "contract-column" : column === "budget" || column === "allocation" ? "budget-column" : column === "summary" ? "summary-column" : column === "document" ? "document-column" : undefined}>{OVERVIEW_COLUMN_LABELS[column]}</th>;
  }

  function overviewTableCell(project: Project, column: OverviewColumn) {
    if (column === "stage") return <td key={column}><div className="stage-cell"><strong>{project.stage || "未归属"}</strong>{project.advancement?.status === "special_active" ? <small className="special-advancement">特批推进中</small> : null}</div></td>;
    if (column === "document") return <td key={column} className="document-column">{project.establishment_document_no || "—"}</td>;
    if (column === "implementation_year") return <td key={column} className="year-column">{project.implementation_year ?? "未记录"}</td>;
    if (column === "completion_year") return <td key={column} className="year-column">{project.actual_end_date?.slice(0, 4) || "未记录"}</td>;
    if (column === "department") return <td key={column} className="department-column"><div className="stacked"><span>{project.department || "未录入部门"}</span><small>{project.project_manager || "未录入负责人"}</small></div></td>;
    if (column === "budget") return <td key={column} className="budget-column"><div className="stacked"><span>有效 {project.effective_budget == null ? "未记录" : `${formatCurrency(project.effective_budget)} 万`}</span><small>初始 {project.budget == null ? "未记录" : `${formatCurrency(project.budget)} 万`}</small><small>{project.effective_budget_source === "budget_constraint" ? "来源：预算核定" : project.effective_budget_source === "historical_review" ? "来源：历史审核" : project.effective_budget_source === "initial_budget" ? "来源：初始预算" : "来源：未记录"}</small></div></td>;
    if (column === "summary") return <td key={column} className="summary-column">{activeGroup === "pre_establish" ? project.description || "未填写项目描述" : project.project_summary_display || "未分类"}</td>;
    if (column === "allocation") return <td key={column} className="budget-column">{project.formal_allocation_total == null ? "暂未确定" : `${formatCurrency(project.formal_allocation_total)} 万`}</td>;
    if (column === "contract") return <td key={column} className="contract-column"><ContractCell project={project} onOpen={() => openContractPanel(project)} /></td>;
    if (column === "progress") return <td key={column} className="progress-column"><ProgressSituation project={project} onSelect={(itemId) => void openQuickItem(project.id, itemId)} onConstraintSelect={() => void openQuickConstraintList(project.id)} /></td>;
    return <td key={column} className="updated-date">{formatDate(project.latest_activity_at)}</td>;
  }

  function closeRail() {
    if (columnBatchTarget) clearColumnBatchTarget();
    setWorkItemActivity(null);
    setRailExpanded(false);
    setQuickItem(null);
    setQuickConstraint(null);
    setQuickConstraintList(null);
    setQuickConstraintFromList(false);
    setQuickConstraintHasBatchContext(false);
    setQuickProjectId(null);
    setQuickProject(null);
    setContractPanel(null);
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
    setDraftItems((items) => [...items, { ...emptyDraft(), name: template.name, content: template.default_content || "" }]);
  }

  async function openQuickItem(projectId: number, itemId: number) {
    const [items, project, logs] = await Promise.all([
      apiGet<WorkItem[]>("/projects/" + projectId + "/work-items"),
      apiGet<Project>("/projects/" + projectId),
      apiGet<WorkItemProgressLog[]>("/projects/" + projectId + "/work-items/" + itemId + "/progress-logs"),
    ]);
    const item = items.find((entry) => entry.id === itemId) ?? null;
    setQuickConstraint(null); setQuickConstraintList(null); setQuickItem(item); setQuickProjectId(projectId); setQuickProject(project); setQuickLogs(logs); setShowAllQuickLogs(false); setQuickCompletionResult(""); setRailExpanded(true);
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
      setQuickItem(null); setQuickConstraintList(null); setQuickConstraintFromList(fromList); setQuickConstraintHasBatchContext(Boolean(selectedIds.length || columnBatchTarget)); setQuickConstraint(constraints.find((item) => item.id === constraintId) ?? null); setQuickProjectId(projectId); setQuickProject(project); setQuickConstraintLogs(logs); setQuickProgress(""); setShowAllQuickLogs(false); setQuickConstraintAction(null); setQuickConstraintActionText(""); setQuickConstraintBudget(""); setQuickConstraintBudgetError(""); setRailExpanded(true);
    } catch (err) { setError(err instanceof ApiError ? err.message : "无法载入外部约束。"); }
  }

  async function submitQuickConstraintAction(action: string, extra: Record<string, unknown> = {}) {
    if (!quickConstraint || !quickProjectId) return;
    try {
      const updated = await apiPost<ProjectExternalConstraint>(`/projects/${quickProjectId}/external-constraints/${quickConstraint.id}/actions`, { action, operator, ...extra });
      setQuickConstraint(updated);
      if (action === "clear") { setQuickConstraintAction(null); setQuickConstraintActionText(""); setQuickConstraintBudget(""); setQuickConstraintBudgetError(""); }
      await refreshProjectRow(quickProjectId); await loadDashboard(); setFeedback("外部约束已更新。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "外部约束未更新，页面保持原状。"); }
  }

  function submitQuickConstraintClear() {
    if (!quickConstraint) return;
    const effectiveBudget = parseEffectiveBudget(quickConstraintBudget);
    if (quickConstraint.impact_scope === "effective_budget" && effectiveBudget === null) {
      setQuickConstraintBudgetError("请填写解除后的有效预算（万元）。");
      requestAnimationFrame(() => quickConstraintBudgetRef.current?.focus());
      return;
    }
    void submitQuickConstraintAction("clear", {
      result: quickConstraintActionText.trim(),
      note: quickConstraintActionText.trim(),
      ...(quickConstraint.impact_scope === "effective_budget" ? { effective_budget: effectiveBudget } : {}),
    });
  }

  async function addQuickConstraintProgress() {
    if (!quickConstraint || !quickProjectId || !quickProgress.trim()) return;
    try {
      const log = await apiPost<ExternalConstraintProgressLog>(`/projects/${quickProjectId}/external-constraints/${quickConstraint.id}/progress-logs`, { operator, content: quickProgress.trim() });
      setQuickConstraintLogs((current) => [...current, log]); setQuickProgress(""); await refreshProjectRow(quickProjectId); setFeedback("外部约束进展已记录。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "进展未记录，页面保持原状。"); }
  }

  async function refreshProjectRow(projectId: number) {
    const project = await apiGet<Project>("/projects/" + projectId);
    setProjects((current) => current.map((entry) => entry.id === projectId ? { ...entry, ...project } : entry));
    setSelectedProjectSnapshots((current) => current[projectId] ? { ...current, [projectId]: project } : current);
    setQuickProject(project);
  }

  async function refreshContractProjects(projectIds: number[]) {
    await Promise.all(projectIds.map((projectId) => refreshProjectRow(projectId)));
    await loadDashboard();
  }

  function openContractPanel(project: Project) {
    const eligibleSelected = selectedProjects.filter((entry) => entry.stage === "项目库—推进中").map((entry) => entry.id);
    const projectIds = eligibleSelected.length ? eligibleSelected : project.stage === "项目库—推进中" ? [project.id] : [];
    setQuickItem(null); setQuickConstraint(null); setQuickConstraintList(null);
    setContractPanel({ projectId: project.id, projectIds, contextProject: project }); setRailExpanded(true);
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
        operator, status: quickItem.status, planned_date: quickItem.planned_date, track_as_key_node: Boolean(quickItem.track_as_key_node),
      });
      setQuickItem(result.work_item);
      await refreshProjectRow(quickProjectId);
      setFeedback("事项设置已保存。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项未保存，页面保持原状。"); }
  }

  async function startQuickItem() {
    if (!quickItem || !quickProjectId) return;
    try {
      const result = await apiPost<{ work_item: WorkItem }>(`/projects/${quickProjectId}/work-items/${quickItem.id}/quick-update`, {
        operator, status: "in_progress", planned_date: quickItem.planned_date, track_as_key_node: Boolean(quickItem.track_as_key_node),
      });
      setQuickItem(result.work_item); await refreshProjectRow(quickProjectId); setFeedback("事项已开始办理。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项未开始办理，页面保持原状。"); }
  }

  async function addQuickProgress() {
    if (!quickItem || !quickProjectId || !quickProgress.trim()) return;
    try {
      const log = await apiPost<WorkItemProgressLog>("/projects/" + quickProjectId + "/work-items/" + quickItem.id + "/progress-logs", { operator, content: quickProgress.trim() });
      setQuickLogs((current) => [...current, log]); setQuickProgress(""); await refreshProjectRow(quickProjectId);
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
        const updated = await apiPatch<WorkItemProgressLog>(`/projects/${quickProjectId}/work-items/${quickItem.id}/progress-logs/${dialog.target.id}`, { operator, content: dialog.value.trim() });
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
      } else if (dialog.kind === "reopen" && quickItem && quickProjectId && dialog.value.trim()) {
        const updated = await apiPost<WorkItem>(`/projects/${quickProjectId}/work-items/${quickItem.id}/reopen`, { operator, reason: dialog.value.trim() });
        setQuickItem(updated); await refreshProjectRow(quickProjectId); setFeedback("事项已重开。");
      }
      setDialog(null);
    } catch (err) { setError(err instanceof ApiError ? err.message : "操作未成功，界面未变更。"); }
  }

  async function quickComplete() {
    if (!quickItem || !quickProjectId) return;
    try {
      const updated = await apiPost<WorkItem>("/projects/" + quickProjectId + "/work-items/" + quickItem.id + "/complete", {
        operator, result: quickCompletionResult.trim() || "已完成", completed_on: quickCompletionDate, note: quickCompletionNote.trim(),
      });
      setQuickItem(updated); setQuickCompleting(false); await refreshProjectRow(quickProjectId); setFeedback("事项已完成。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项未完成，页面保持原状。"); }
  }

  async function correctQuickCompletion() {
    if (!quickItem || !quickProjectId) return;
    try {
      const updated = await apiPatch<WorkItem>(`/projects/${quickProjectId}/work-items/${quickItem.id}/completion-record`, {
        operator, result: quickCompletionResult.trim(), completed_on: quickCompletionDate,
        note: quickCompletionNote.trim(),
      });
      setQuickItem(updated); setQuickCorrectingCompletion(false); await refreshProjectRow(quickProjectId); setFeedback("已更正完成信息。");
    } catch (err) { setError(err instanceof ApiError ? err.message : "完成信息未更正，页面保持原状。"); }
  }

  async function submitBatchItems() {
    if (!selectedIds.length || draftItems.some((item) => !item.name.trim())) { setError("请选择项目并填写每个事项名称。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ created_count: number }>("/projects/batch-work-items", {
        project_ids: selectedIds, operator, items: draftItems,
        save_as_package_name: packageName.trim() || null,
      });
      setFeedback(`已向 ${selectedIds.length} 个项目下发 ${result.created_count} 条事项。`);
      setDraftItems([emptyDraft()]); setPackageName("");
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
        constraints: [{ template_id: constraintTemplateId, name, impact_scope: constraintImpactScope, impact_note: constraintImpactNote, handling_status: constraintStatus }],
        save_as_common: saveConstraintAsCommon,
      });
      setFeedback(`已向 ${selectedIds.length} 个项目建立外部约束${saveConstraintAsCommon ? "，并已保存为常用约束。" : "。"}`);
      setConstraintTemplateId(null); setConstraintName(""); setConstraintImpactScope("none"); setConstraintImpactNote(""); setSaveConstraintAsCommon(false);
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
      await apiPost("/project-types", { name: newClassificationName.trim(), code_prefix: newClassificationPrefix.trim(), sort_order: projectTypes.length + 1, operator });
      setNewClassificationName(""); setNewClassificationPrefix(""); await loadDashboard(); setFeedback("已新增项目分类。");
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

  async function reorderProjectClassifications(fromId: number, toId: number) {
    const next = [...projectTypes];
    const from = next.findIndex((item) => item.id === fromId);
    const to = next.findIndex((item) => item.id === toId);
    if (from < 0 || to < 0 || from === to) return;
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setProjectTypes(next.map((item, index) => ({ ...item, sort_order: index + 1 })));
    try {
      await Promise.all(next.map((item, index) => apiPatch(`/project-types/${item.id}`, { sort_order: index + 1, operator })));
      setFeedback("项目分类顺序已保存。");
    } catch (err) { await loadDashboard(); setError(err instanceof ApiError ? err.message : "项目分类顺序未保存，已恢复当前数据。"); }
  }

  async function reorderDepartments(fromDepartment: string, toDepartment: string) {
    const next = [...departments];
    const from = next.indexOf(fromDepartment);
    const to = next.indexOf(toDepartment);
    if (from < 0 || to < 0 || from === to) return;
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setDepartments(next);
    try {
      await Promise.all(next.map((department, index) => apiPatch(`/meta/departments/${encodeURIComponent(department)}/order`, { sort_order: index + 1, operator })));
      setFeedback("部门顺序已保存。");
    } catch (err) { await loadDashboard(); setError(err instanceof ApiError ? err.message : "部门顺序未保存，已恢复当前数据。"); }
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

  async function submitAnnualSupplement() {
    if (!selectedIds.length || !comment.trim()) { setError("补充纳入需要选择项目并填写理由。"); return; }
    setExecuting(true); setError("");
    try {
      await apiPost(`/projects/annual-budget-plans/${Number(advancementYear)}/supplement`, { project_ids: selectedIds, operator, reason: comment });
      await refreshSelectedProjects(); setFeedback("已补充纳入本年度计划并正式推进；当前视图保持不变。"); setComment("");
    } catch (err) { setError(err instanceof ApiError ? err.message : "补充纳入失败"); }
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

  async function submitCompletedAdvancementBackfill() {
    if (!selectedIds.length || !comment.trim()) { setError("补录历史实施需要选择项目并填写理由。"); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ success: number }>("/projects/batch-backfill-completed-advancement", {
        project_ids: selectedIds, operator, reason: comment, advancement_year: Number(advancementYear), clear_zero_budget: backfillClearZeroBudget,
      });
      await refreshSelectedProjects();
      setFeedback(`已补录 ${result.success} 个已完成项目的历史实施记录。`);
      setComment(""); setBackfillClearZeroBudget(false);
    } catch (err) { setError(err instanceof ApiError ? err.message : "历史实施补录失败"); }
    finally { setExecuting(false); }
  }

  async function submitEarlyPreparation() {
    if (!selectedIds.length || !comment.trim() || !earlyApprovalBasis.trim()) { setError("提前推进准备需要填写理由和审批依据。"); return; }
    setExecuting(true); setError("");
    try {
      await Promise.all(selectedIds.map((id) => apiPost(`/projects/${id}/special-include-in-advancement`, { operator, reason: comment, approval_basis: earlyApprovalBasis, advancement_year: Number(advancementYear) })));
      await refreshSelectedProjects(); setFeedback(`已特批纳入 ${selectedIds.length} 个未立项项目的前期推进管理。当前视图保持不变。`); setComment("");
    } catch (err) { setError(err instanceof ApiError ? err.message : "特批纳入推进失败"); }
    finally { setExecuting(false); }
  }

  async function submitAnnualException() {
    if (!selectedIds.length || !comment.trim()) { setError("请选择项目并填写原因。"); return; }
    if (annualExceptionAction === "special" && !earlyApprovalBasis.trim()) { setError("特批推进必须填写审批依据。"); return; }
    setExecuting(true); setError("");
    try {
      await apiPost(`/projects/annual-budget-plans/${Number(advancementYear)}/exception-actions`, {
        action: annualExceptionAction,
        project_ids: selectedIds,
        operator,
        reason: comment.trim(),
        special_entries: annualExceptionAction === "special" ? selectedIds.map((project_id) => ({ project_id, reason: comment.trim(), approval_basis: earlyApprovalBasis.trim() })) : undefined,
      });
      await refreshSelectedProjects();
      setFeedback({ supplement: "已补充纳入本年度。", cancel: "已取消本次推进。", defer: "已暂缓推进。", resume: "已恢复推进。", special: "已特批推进。" }[annualExceptionAction]);
      setComment("");
    } catch (err) { setError(err instanceof ApiError ? err.message : "推进例外操作失败，项目保持原状态。"); }
    finally { setExecuting(false); }
  }

  async function refreshSelectedProjects(projectIds = selectedIds) {
    const refreshed = await Promise.all(projectIds.map((id) => apiGet<Project>(`/projects/${id}`)));
    setProjects((current) => current.map((project) => refreshed.find((item) => item.id === project.id) ?? project));
    setSelectedProjectSnapshots((current) => ({ ...current, ...Object.fromEntries(refreshed.map((project) => [project.id, project])) }));
    const [nextGroups, nextSummary] = await Promise.all([apiGet<DashboardGroup[]>("/dashboard/groups"), apiGet<DashboardSummary>("/dashboard/summary")]);
    setGroups(nextGroups); setSummary(nextSummary);
  }

  const advancementAction = !selectedProjects.length ? "none"
    : selectedProjects.every((project) => ["active", "special_active"].includes(project.advancement?.status || "none")) ? "defer"
      : selectedProjects.every((project) => project.stage === "项目库—未实施" && project.advancement?.status === "none") ? "include"
        : selectedProjects.every((project) => project.stage === "未立项" && project.advancement?.status === "none") ? "special"
          : selectedProjects.every((project) => project.stage === "已完成" && (!project.implementation_year || !project.has_completed_advancement_cycle)) ? "backfill"
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
    const budgetDetermination = isBatchBudgetDetermination || (columnBatchTarget?.kind === "external_constraint" && columnBatchTarget.impactScope === "effective_budget");
    if (["mark_not_applicable", "invalidate"].includes(batchConstraintAction) && !batchConstraintReason.trim()) { setError("请填写原因。 "); return; }
    if (batchConstraintAction === "progress" && !batchConstraintReason.trim()) { setError("请填写共同进展。 "); return; }
    if (budgetDetermination && activePreview?.eligible.some((item) => !batchBudgetOutcomes[item.project_id]?.approved_budget.trim())) { setError("请逐个填写每个项目的有效预算。 "); return; }
    try {
      await apiPost("/projects/batch-external-constraint-actions", { project_ids: selectedIds, targets: columnBatchTarget?.kind === "external_constraint" ? columnTargetsPayload() : undefined, template_id: constraintTemplateId ?? undefined, name: columnBatchTarget && !columnBatchTarget.templateId ? columnBatchTarget.label : undefined, outcome_kind: columnBatchTarget?.outcomeKind, action: batchConstraintAction, operator, reason: batchConstraintReason.trim(), content: batchConstraintAction === "progress" ? batchConstraintReason.trim() : undefined, result: batchConstraintAction === "clear" ? batchConstraintReason.trim() : undefined, note: batchConstraintAction === "clear" ? batchConstraintReason.trim() : undefined, project_outcomes: budgetDetermination ? activePreview?.eligible.map((item) => {
        const value = batchBudgetOutcomes[item.project_id];
        return { project_id: item.project_id, effective_budget: Number(value.approved_budget), result: value.note };
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
        : { completed_on: columnBatchValue.completed_on || today(), result: columnBatchValue.result, note: columnBatchValue.note };
  }

  async function previewColumnBatch() {
    if (!columnBatchTarget || !selectedIds.length) { setError("请先从阶段跟踪选择可办理列。 "); return; }
    if (columnBatchTarget.kind === "work_item") {
      await executeColumnWorkItemBatch();
      return;
    }
    const path = "/projects/batch-external-constraint-actions/preflight";
    const action = batchConstraintAction;
    try {
      const defaults = undefined;
      const payload = { project_ids: selectedIds, targets: columnTargetsPayload(), action, operator, defaults, template_id: columnBatchTarget.templateId, name: columnBatchTarget.templateId ? undefined : columnBatchTarget.label, outcome_kind: columnBatchTarget.outcomeKind };
      const preview = await apiPost<typeof columnBatchPreview>(path, payload);
      setColumnBatchPreview(preview);
      if (columnBatchTarget.kind === "external_constraint" && columnBatchTarget.impactScope === "effective_budget" && action === "clear") {
        setBatchBudgetOutcomes(Object.fromEntries((preview?.eligible ?? []).map((item) => [item.project_id, { approved_budget: "", concluded_on: today(), note: "", cleared: true, set_effective_budget_source: true }])));
      }
    } catch (err) { setError(err instanceof ApiError ? err.message : "批量预检失败。"); }
  }

  async function executeColumnWorkItemBatch() {
    if (!columnBatchTarget || columnBatchTarget.kind !== "work_item") return;
    const defaults = columnWorkItemDefaults();
    if (columnWorkItemAction === "progress" && !columnBatchValue.progress_content.trim()) { setError("请填写共同进展。 "); return; }
    if (columnWorkItemAction === "update" && !columnBatchValue.status && !columnBatchValue.planned_date && columnBatchValue.track_as_key_node === "") { setError("请至少填写一项要更新的事项设置。 "); return; }
    setExecuting(true); setError("");
    try {
      const result = await apiPost<{ processed_targets: Array<{ project_id: number }> }>("/projects/batch-work-item-actions", { project_ids: selectedIds, targets: columnTargetsPayload(), action: columnWorkItemAction, operator, defaults });
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

  async function executeDirectStage(action: "establish" | "complete") {
    setExecuting(true);
    setFeedback("");
    setError("");
    try {
      const result = await apiPost<{ projects: Project[]; success: number }>("/projects/batch-stage-advance", {
        project_ids: selectedIds,
        action,
        operator,
        establishment_document_no: action === "establish" ? establishmentDocumentNo.trim() : "",
      });
      await refreshSelectedProjects(result.projects.map((project) => project.id));
      setFeedback(action === "establish" ? `已登记 ${result.success} 个项目的立项文件并进入项目库。` : `已完成 ${result.success} 个项目。`);
      if (action === "establish") setEstablishmentDocumentNo("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Stage 推进失败，项目保持原状。");
    } finally {
      setExecuting(false);
    }
  }

  async function executeForceBatch() {
    setExecuting(true);
    setFeedback("");
    setError("");
    try {
      const result = await apiPost<BatchExecuteResponse>("/projects/batch-transition", {
        project_ids: selectedIds,
        to_status: selectedTarget,
        operator,
        operator_role: "PMO",
        approver: approver || null,
        comment,
        deliverable: "",
        force: true,
        approved_budget: null,
      });
      setFeedback(
        result.failed
          ? `本次处理 ${result.total} 个项目，成功 ${result.success} 个，失败 ${result.failed} 个。`
          : `本次处理 ${result.total} 个项目，全部成功。`,
      );
      setSelectedIds([]);
      setComment("");
      await loadDashboard();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "批量执行失败");
    } finally {
      setExecuting(false);
    }
  }

  async function previewImportFile(file: File) {
    setError("");
    setFeedback(`正在校验“${file.name}”…`);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await apiPostForm<ImportPreviewResponse>("/imports/projects/preview", formData);
      setImportPreview(response);
      setFeedback(`已生成预览：有效 ${response.valid_rows} 行，异常 ${response.invalid_rows} 行。确认写入前不会修改数据。`);
    } catch (err) {
      setImportPreview(null);
      setError(err instanceof ApiError ? err.message : "导入预览失败");
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
    await previewImportFile(file);
  }

  async function commitImport() {
    if (!importPreview?.records.length) return;
    setError("");
    try {
      const response = await apiPost<ImportCommitResponse>("/imports/projects/commit", {
        records: importPreview.records,
        operator,
      });
      if (response.failed) {
        setImportPreview((current) => current ? { ...current, invalid_rows: response.failed, errors: response.errors } : current);
        setFeedback("");
        setError(`确认写入前校验失败：${response.errors.map((item) => `第 ${item.row_number} 行：${item.message}`).join("；")}。未写入任何项目。`);
        return;
      }
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
        project_type: newProject.project_type, procurement_nature: newProject.procurement_nature, location: newProject.location.trim(), budget: newProject.budget.trim() || null, description: newProject.description.trim(), operator,
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
          <button type="button" className={`external-ongoing-summary ${selectedExternalConditions === "ongoing" ? "active" : ""}`} onClick={() => { const next = selectedExternalConditions === "ongoing" ? "" : "ongoing"; setSelectedExternalConditions(next); if (next) setActiveGroup("project_library"); }}>
            外部条件待处理：{summary?.external_conditions_ongoing_count ?? 0} 个项目 · 涉及预算 {formatCurrency(summary?.external_conditions_ongoing_effective_budget)} 万
          </button>
        </div>
      </header>

      {error || feedback ? <div className="dashboard-notices">{error ? <div className="notice error">{error}</div> : null}{feedback ? <div className="notice success">{feedback}</div> : null}</div> : null}

      <main className="workspace">
        {tableView === "annual" ? <AnnualBudgetView operator={operator} projectTypes={projectTypes} onFeedback={setFeedback} onError={setError} onChanged={loadDashboard} onExit={(view, group) => { if (group) setActiveGroup(group); setTableView(view); }} renderStageSlot={(onSelect) => <section className="group-band">{groups.map((group) => <button key={group.key} className={`group-card ${activeGroup === group.key ? "active" : ""}`} style={{ "--group-accent": GROUP_ACCENTS[group.key] } as CSSProperties} onClick={() => onSelect(group.key)}><div className="group-main"><p>{group.label}</p><strong>{group.count}</strong></div><div className="group-budget"><span>预算 {formatCurrency(group.total_budget)} 万</span></div><ArrowUpRight size={18} /></button>)}</section>} /> : <>
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
                  placeholder="搜索项目名称 / 编号 / 项目描述"
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                />
                <select
                  className="select"
                  value={selectedProjectType}
                  onChange={(event) => setSelectedProjectType(event.target.value)}
                >
                  <option value="">全部项目分类</option>
                  {projectTypes.filter((item) => item.is_active && filterProjectTypes.has(item.code)).map((item) => <option key={item.id} value={item.code}>{item.name}</option>)}
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
                  {filterDepartments.map((department) => (
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
                <button className="mini-button" onClick={() => { clearColumnBatchTarget(); setTableView("annual"); setColumnPickerOpen(false); }}>年度预算安排</button>
                {tableView === "overview" ? <div className="column-picker"><button type="button" className="mini-button" aria-expanded={overviewColumnPickerOpen} onClick={() => setOverviewColumnPickerOpen((open) => !open)}>显示列</button>{overviewColumnPickerOpen ? <div className="column-picker-menu" role="dialog" aria-label="配置总览显示列">
                  <div className="column-picker-heading"><strong>显示列</strong><button type="button" className="text-button" onClick={() => setOverviewColumnPickerOpen(false)}>关闭</button></div>
                  <p>“选中”和“项目”固定；这里只显示当前 Stage 可用的列。</p>
                  <section><span>已显示（拖动调整顺序）</span><div className="column-chip-list">{overviewColumns.map((column, index) => <button type="button" draggable key={column} onDragStart={(event) => event.dataTransfer.setData("text/plain", String(index))} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const from = Number(event.dataTransfer.getData("text/plain")); if (Number.isInteger(from)) moveOverviewColumn(from, index); }} onClick={() => saveOverviewColumns(overviewColumns.filter((item) => item !== column))}><span className="drag-handle">⋮⋮</span>{OVERVIEW_COLUMN_LABELS[column]} <b>×</b></button>)}</div></section>
                  <section><span>可添加</span><div className="column-action-list">{overviewAllowedColumns.filter((column) => !overviewColumns.includes(column)).map((column) => <button type="button" key={column} onClick={() => saveOverviewColumns([...overviewColumns, column])}>＋ {OVERVIEW_COLUMN_LABELS[column]}</button>)}{!overviewAllowedColumns.filter((column) => !overviewColumns.includes(column)).length ? <small>当前 Stage 的可用列已全部显示</small> : null}</div></section>
                  <button type="button" className="text-button column-reset" onClick={resetOverviewColumns}>恢复默认显示列</button>
                </div> : null}</div> : null}
                {tableView === "stage" ? <div className="column-picker"><button type="button" className="mini-button" aria-expanded={columnPickerOpen} onClick={() => setColumnPickerOpen((open) => !open)}>显示列</button>{columnPickerOpen ? <div className="column-picker-menu" role="dialog" aria-label="配置阶段跟踪显示列">
                  <div className="column-picker-heading"><strong>显示列</strong><button type="button" className="text-button" onClick={() => setColumnPickerOpen(false)}>关闭</button></div>
                  <p>只影响当前工作台视图，不会创建事项。</p>
                  <section><span>已显示（拖动调整顺序）</span><div className="column-chip-list">{stageColumns.map((column, index) => <button type="button" draggable key={`${column.kind}:${column.key}`} aria-label={`${column.kind === "external_constraint" ? "外部约束" : "事项"}列 ${column.label}`} onDragStart={(event) => event.dataTransfer.setData("text/plain", String(index))} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const from = Number(event.dataTransfer.getData("text/plain")); if (Number.isInteger(from) && from !== index) { const next = [...stageColumns]; const [moved] = next.splice(from, 1); next.splice(index, 0, moved); saveStageColumns(next); } }} onClick={() => removeStageColumn(column)}><span className="drag-handle">⋮⋮</span>{column.label} <b>×</b></button>)}{!stageColumns.length ? <small>暂无显示列</small> : null}</div></section>
                  <section><span>推荐列</span><div className="column-action-list">{recommendedColumns.filter((column) => !stageColumns.some((item) => item.kind === column.kind && item.key === column.key)).map((column) => <button type="button" key={`${column.kind}:${column.key}`} aria-label={`添加${column.kind === "external_constraint" ? "外部约束" : "事项"}列 ${column.label}`} onClick={() => addStageColumn(column)}>＋ {column.label}</button>)}{!recommendedColumns.filter((column) => !stageColumns.some((item) => item.kind === column.kind && item.key === column.key)).length ? <small>已全部加入</small> : null}</div></section>
                <section><span>当前结果中存在</span><div className="column-action-list">{[...currentConstraintColumns, ...currentProjectColumns].filter((column) => !stageColumns.some((item) => item.kind === column.kind && item.key === column.key) && !recommendedColumns.some((item) => item.kind === column.kind && item.key === column.key)).slice(0, 8).map((column) => <button type="button" key={`${column.kind}:${column.key}`} aria-label={`添加${column.kind === "external_constraint" ? "外部约束" : "事项"}列 ${column.label}`} onClick={() => addStageColumn(column)}>＋ {column.label}</button>)}</div></section>
                  <label className="column-search"><span>搜索其他常用事项</span><input className="input" value={columnSearch} onChange={(event) => setColumnSearch(event.target.value)} placeholder="输入事项名称" /></label>
                  {columnSearch.trim() ? <div className="column-action-list search-results">{searchedColumns.map((column) => <button type="button" key={`${column.kind}:${column.key}`} aria-label={`添加${column.kind === "external_constraint" ? "外部约束" : "事项"}列 ${column.label}`} onClick={() => addStageColumn(column)}>＋ {column.label}</button>)}{!searchedColumns.length ? <small>未找到可添加的事项或约束</small> : null}</div> : null}
                  <button type="button" className="text-button column-reset" onClick={resetStageColumns}>恢复默认推荐列</button>
                </div> : null}</div> : null}
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
                      <th className="selection-column"><button type="button" className="table-select-all" onClick={toggleAllVisible} aria-label={projects.length && projects.every((project) => selectedIds.includes(project.id)) ? "取消全选当前结果" : "全选当前结果"}>选中</button></th>
                      <th>项目</th>
                      {tableView === "overview" ? overviewContextColumns.map(overviewTableHeader) : <>
                      <th>Stage</th>
                      {activeGroup !== "pre_establish" && !showRemoved ? <th className="document-column">立项文件</th> : null}
                      {showImplementationYearColumn ? <th className="year-column"><button className="sort-button" onClick={() => toggleSort("implementation_year")}>实施年份 {sortLabel("implementation_year")}</button></th> : null}
                      {showCompletionYearColumn ? <th className="year-column"><button className="sort-button" onClick={() => toggleSort("completion_year")}>完成年份 {sortLabel("completion_year")}</button></th> : null}
                      {stageColumns.map((column) => {
                        const active = columnBatchTarget?.kind === column.kind && columnBatchTarget.key === column.key;
                        const available = Boolean(columnTargetFor(column));
                        return <th key={`${column.kind}:${column.key}`} className={`${active ? "column-batch-header" : ""} ${column.kind === "external_constraint" ? "stage-constraint-header" : "stage-item-header"}`}><button type="button" className="stage-column-heading" disabled={!available} aria-label={`单击手动选择“${column.label}”列，双击全选实例`} onClick={() => queueColumnBatchSelection(column)} onDoubleClick={() => selectAllColumnBatch(column)} onKeyDown={(event) => { if ((event.key === "Enter" || event.key === " ") && event.shiftKey) { event.preventDefault(); selectAllColumnBatch(column); } }}>{column.label}</button></th>;
                      })}
                      <th className="department-column">
                        <button className="sort-button" onClick={() => toggleSort("department")}>
                          部门 / 负责人 {sortLabel("department")}
                        </button>
                      </th>
                      <th className="budget-column">预算</th>
                      {activeGroup !== "pre_establish" && activeGroup !== "pool_pending" && !showRemoved ? <th className="budget-column">正式分配</th> : null}
                      {!showCompletionYearColumn ? <th className="updated-date">
                        <button className="sort-button" onClick={() => toggleSort("latest_activity_at")}>
                          最新动态 {sortLabel("latest_activity_at")}
                        </button>
                      </th> : null}
                      </>}
                    </tr>
                  </thead>
                  <tbody>
                    {(workItemActivity && activityMembersOnly ? projects.filter((project) => workItemActivity.members.some((member) => member.project_id === project.id)) : projects).map((project) => {
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
                              {activeGroup !== "pre_establish" ? <small>{project.project_summary_display || "未分类"}</small> : null}
                              {showRemoved ? <button className="text-button" onClick={() => setRestoreTarget(project)}>恢复项目</button> : null}
                            </div>
                          </td>
                          {tableView === "overview" ? overviewContextColumns.map((column) => overviewTableCell(project, column)) : <>
                          <td><div className="stage-cell"><strong>{project.stage || "未归属"}</strong>{project.advancement?.status === "special_active" ? <small className="special-advancement">特批推进中</small> : null}</div></td>
                          {activeGroup !== "pre_establish" && !showRemoved ? <td className="document-column">{project.establishment_document_no || "—"}</td> : null}
                          {showImplementationYearColumn ? <td className="year-column">{project.implementation_year ?? "未记录"}</td> : null}
                          {showCompletionYearColumn ? <td className="year-column">{project.actual_end_date?.slice(0, 4) || "未记录"}</td> : null}
                          {stageColumns.map((column) => {
                            const columnSelected = Boolean(selected && columnBatchTarget?.kind === column.kind && columnBatchTarget.key === column.key && columnBatchTarget.instances[project.id]);
                            return <td key={`${column.kind}:${column.key}`} className={columnSelected ? "column-batch-cell" : ""}><StageItemCell project={project} column={column} highlighted={columnSelected} onWorkItemSelect={(itemId) => void openQuickItem(project.id, itemId)} onConstraintSelect={(constraintId) => void openQuickConstraint(project.id, constraintId)} onActivitySelect={(activityId) => void openWorkItemActivity(activityId, "stage")} /></td>;
                          })}
                          <td className="department-column">
                            <div className="stacked">
                              <span>{project.department || "未录入部门"}</span>
                              <small>{project.project_manager || "未录入负责人"}</small>
                            </div>
                          </td>
                          <td className="budget-column">
                            <div className="stacked">
                              <span>有效 {project.effective_budget == null ? "未记录" : `${formatCurrency(project.effective_budget)} 万`}</span>
                              <small>初始 {project.budget == null ? "未记录" : `${formatCurrency(project.budget)} 万`}</small>
                              <small>{project.effective_budget_source === "budget_constraint" ? "来源：预算核定" : project.effective_budget_source === "historical_review" ? "来源：历史审核" : project.effective_budget_source === "initial_budget" ? "来源：初始预算" : "来源：未记录"}</small>
                            </div>
                          </td>
                          {activeGroup !== "pre_establish" && activeGroup !== "pool_pending" && !showRemoved ? <td className="budget-column">{project.formal_allocation_total == null ? "暂未确定" : `${formatCurrency(project.formal_allocation_total)} 万`}</td> : null}
                          {!showCompletionYearColumn ? <td className="updated-date">{formatDate(project.latest_activity_at)}</td> : null}
                          </>}
                        </tr>
                      );
                    })}
                    {!projects.length ? <tr><td className="project-table-empty" colSpan={tableColumnCount}>当前条件下暂无项目</td></tr> : null}
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
            <h3>{contractPanel || quickItem || quickConstraint || quickConstraintList ? "快速办理" : workItemActivity ? "办理活动" : columnBatchTarget ? "阶段跟踪批量办理" : "批量操作"}</h3>
            {!contractPanel && !quickItem && !quickConstraint && !quickConstraintList ? <div className="selection-summary">
              <span>当前已选</span>
              <strong>{selectedIds.length}</strong>
              <small>有效预算合计 {formatCurrency(selectedEffectiveBudget)} 万</small>
              <button type="button" className="text-button" disabled={!selectedIds.length} onClick={() => setSelectedListOpen((open) => !open)}>{selectedListOpen ? "收起已选项目" : "查看已选项目"}</button>
              {selectedListOpen ? <div className="selected-project-list">
                {selectedProjects.map((project) => <article key={project.id}><div><strong>{project.name}</strong><small>{project.project_code} · 有效 {formatCurrency(project.effective_budget ?? project.budget)} 万</small></div><button type="button" className="text-button" onClick={() => toggleSelection(project)}>取消选中</button></article>)}
              </div> : null}
            </div> : null}
            {!contractPanel && !quickItem && !quickConstraint && !quickConstraintList && !columnBatchTarget ? <div className="operation-tabs">
              {([ ["advance", "推进管理"], ["batch", "办理活动"], ["stage", "Stage 推进"], ["items", "添加事项"], ["package", "应用工作包"], ["constraints", "外部约束"], ["config", "基础配置"] ] as const).map(([mode, label]) => <button key={mode} className={operationMode === mode ? "active" : ""} onClick={() => { setOperationMode(mode); setRailExpanded(true); if (mode === "batch") void loadBatchHistory(); }}>{label}</button>)}
            </div> : null}
            <div className="operation-body">
              {contractPanel ? <ContractPanel projectId={contractPanel.projectId} contextProject={contractPanel.contextProject} initialProjectIds={contractPanel.projectIds} initialContractId={contractPanel.contractId} operator={operator} allowCreate={contractPanel.projectIds.length > 0} defaultReadOnly={contractPanel.contextProject?.stage === "已完成"} onClose={closeRail} onChanged={refreshContractProjects} /> : workItemActivity ? <section className="column-batch-panel activity-panel">
                <div className="quick-panel-heading"><strong>{workItemActivity.name}</strong><button type="button" className="text-button" onClick={() => { setWorkItemActivity(null); setOperationMode(batchReturnMode === "batch" ? "batch" : "advance"); if (batchReturnMode === "stage") setTableView("stage"); }}>返回{batchReturnMode === "batch" ? "办理活动" : "阶段跟踪"}</button></div>
                <p className="operation-lead">事项 · <strong>{workItemActivity.work_item_name}</strong>{workItemActivity.scheduled_on ? ` · ${workItemActivity.scheduled_on}` : ""}</p>
                <p className="muted-copy">活动成员 {workItemActivity.member_count} 个，已登记结果 {workItemActivity.recorded_outcome_count} 个；当前选择只决定本次办理，不会移出活动。</p>
                <div className="quick-actions">
                  <button className="mini-button" onClick={() => { setActivityMembersOnly((value) => !value); setActivityMemberManaging(false); }}>{activityMembersOnly ? "查看全部项目" : "仅看本活动项目"}</button>
                  {workItemActivity.status === "not_started" ? <button className="mini-button" onClick={() => void apiPost<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/start`, { operator }).then(setWorkItemActivity)}>开始活动</button> : null}
                  {["not_started", "in_progress"].includes(workItemActivity.status) ? <button className="mini-button" onClick={() => void apiPost<WorkItemActivity>(`/work-item-activities/${workItemActivity.id}/end`, { operator }).then((activity) => { setWorkItemActivity(activity); setFeedback("办理活动已结束；未登记成员结果已保留。"); })}>结束活动</button> : null}
                  <button className="mini-button" onClick={() => { setActivityEditDraft({ name: workItemActivity.name, scheduled_on: workItemActivity.scheduled_on || "", note: workItemActivity.note || "" }); setActivityEditOpen((value) => !value); }}>编辑活动</button>
                  {["not_started", "in_progress"].includes(workItemActivity.status) ? <button className="mini-button" onClick={() => { setActivityMemberManaging((value) => !value); setActivityMembersOnly(false); setSelectedIds([]); }}>管理成员</button> : null}
                  {["not_started", "in_progress"].includes(workItemActivity.status) ? <button className="mini-button danger" onClick={() => setActivityVoidOpen((value) => !value)}>作废活动</button> : null}
                </div>
                {activityVoidOpen ? <section className="quick-group"><strong>作废办理活动</strong><label className="field"><span>作废原因</span><textarea className="textarea" rows={2} value={activityMemberReason} onChange={(event) => setActivityMemberReason(event.target.value)} /></label><div className="quick-actions"><button className="mini-button" onClick={() => setActivityVoidOpen(false)}>取消</button><button className="mini-button danger" onClick={() => void voidCurrentActivity()}>确认作废</button></div></section> : null}
                {activityEditOpen ? <section className="quick-group"><strong>编辑活动</strong><label className="field"><span>活动名称</span><input className="input" value={activityEditDraft.name} onChange={(event) => setActivityEditDraft((current) => ({ ...current, name: event.target.value }))} /></label><label className="field"><span>日期（可选）</span><input className="input" type="date" value={activityEditDraft.scheduled_on} onChange={(event) => setActivityEditDraft((current) => ({ ...current, scheduled_on: event.target.value }))} /></label><label className="field"><span>说明（可选）</span><textarea className="textarea" rows={2} value={activityEditDraft.note} onChange={(event) => setActivityEditDraft((current) => ({ ...current, note: event.target.value }))} /></label><div className="quick-actions"><button className="mini-button" onClick={() => setActivityEditOpen(false)}>取消</button><button className="mini-button active" onClick={() => void saveActivityEdit()}>保存活动</button></div></section> : null}
                <section className="quick-group"><strong>活动进展</strong>{workItemActivity.progress_logs.map((log) => <article key={log.id} className="batch-member-row"><span>{formatDate(log.created_at)} · {log.content}</span><aside><button className="text-button" onClick={() => { setActivityEditingProgressId(log.id); setActivityProgress(log.content); }}>编辑</button><button className="text-button danger" onClick={() => setActivityEditingProgressId(log.id)}>删除</button></aside></article>)}{activityEditingProgressId != null && workItemActivity.progress_logs.some((log) => log.id === activityEditingProgressId) ? <label className="field"><span>删除原因</span><input className="input" value={activityMemberReason} onChange={(event) => setActivityMemberReason(event.target.value)} placeholder="删除时必填" /></label> : null}<textarea className="textarea" rows={2} value={activityProgress} onChange={(event) => setActivityProgress(event.target.value)} placeholder={activityEditingProgressId == null ? "记录本次活动进展" : "修改活动进展"} /><div className="quick-actions"><button className="mini-button" onClick={() => { setActivityEditingProgressId(null); setActivityProgress(""); }}>取消</button><button className="mini-button" onClick={() => void saveActivityProgress()}>{activityEditingProgressId == null ? "记录进展" : "保存修改"}</button>{activityEditingProgressId != null ? <button className="mini-button danger" onClick={() => void deleteActivityProgress(activityEditingProgressId)}>确认删除</button> : null}</div></section>
                {activityMemberManaging ? <section className="quick-group"><strong>管理办理活动成员</strong><p className="muted-copy">左侧已切换为全部项目：有同名待办理事项的项目可加入；当前成员可移出。</p><label className="field"><span>移出原因</span><input className="input" value={activityMemberReason} onChange={(event) => setActivityMemberReason(event.target.value)} placeholder="移出成员时必填" /></label><div className="quick-actions"><button className="mini-button" onClick={() => void updateActivityMembers("add")}>将已选项目加入</button><button className="mini-button danger" onClick={() => void updateActivityMembers("remove")}>移出已选成员</button><button className="mini-button" onClick={() => { setActivityMemberManaging(false); setActivityMembersOnly(true); setSelectedIds(workItemActivity.members.filter((member) => member.member_status === "active").map((member) => member.project_id)); }}>完成成员管理</button></div></section> : null}
                {workItemActivity.status === "not_started" || workItemActivity.status === "in_progress" ? <><section className="quick-group"><label className="field"><span>当前选中项目办理</span><select className="select" value={columnWorkItemAction} onChange={(event) => setColumnWorkItemAction(event.target.value as typeof columnWorkItemAction)}><option value="progress">添加事项进展</option><option value="update">修改事项状态或计划完成日期</option><option value="complete">完成事项</option></select></label>{columnWorkItemAction === "progress" ? <textarea className="textarea" rows={2} value={columnBatchValue.progress_content} onChange={(event) => setColumnBatchValue((current) => ({ ...current, progress_content: event.target.value }))} placeholder="共同事项进展" /> : null}{columnWorkItemAction === "update" ? <div className="field-grid"><select className="select" value={columnBatchValue.status} onChange={(event) => setColumnBatchValue((current) => ({ ...current, status: event.target.value }))}><option value="">不修改状态</option><option value="not_started">待办理</option><option value="in_progress">进行中</option><option value="paused">暂停</option></select><input className="input" type="date" value={columnBatchValue.planned_date} onChange={(event) => setColumnBatchValue((current) => ({ ...current, planned_date: event.target.value }))} /></div> : null}{columnWorkItemAction === "complete" ? <div className="field-grid"><input className="input" type="date" value={columnBatchValue.completed_on} onChange={(event) => setColumnBatchValue((current) => ({ ...current, completed_on: event.target.value }))} /><input className="input" value={columnBatchValue.result} onChange={(event) => setColumnBatchValue((current) => ({ ...current, result: event.target.value }))} placeholder="完成结果（可选）" /><input className="input" value={columnBatchValue.note} onChange={(event) => setColumnBatchValue((current) => ({ ...current, note: event.target.value }))} placeholder="完成说明（可选）" /></div> : null}<button className="action-button primary full" disabled={!selectedIds.length || executing} onClick={() => void executeActivityWorkItemAction()}>{columnWorkItemAction === "complete" ? "完成事项" : "保存事项办理"}</button></section><section className="quick-group"><strong>记录本次办理结果</strong><div className="field-grid"><label className="field"><span>结果日期</span><input className="input" type="date" value={activityResult.result_on} onChange={(event) => setActivityResult((current) => ({ ...current, result_on: event.target.value }))} /></label><label className="field"><span>本次结果（可选）</span><input className="input" value={activityResult.result} onChange={(event) => setActivityResult((current) => ({ ...current, result: event.target.value }))} /></label></div><label className="field"><span>说明（可选）</span><textarea className="textarea" rows={2} value={activityResult.note} onChange={(event) => setActivityResult((current) => ({ ...current, note: event.target.value }))} /></label><button className="action-button primary full" disabled={!selectedIds.length || executing} onClick={() => void recordCurrentActivityResults()}>记录本次办理结果</button></section>{activityNextGroups.length ? <section className="quick-group"><strong>当前处理项目下一步</strong>{activityNextGroups.map((group) => <div key={group.name} className="batch-member-row"><span>{group.name} · {group.count} 个项目</span><button className="text-button" onClick={() => void recordActivityFollowUp("next", group.project_ids)}>安排下一办理活动</button></div>)}</section> : <section className="quick-group"><strong>后续处理</strong><div className="quick-actions"><button className="mini-button" onClick={() => void recordActivityFollowUp("rehandle")}>重新办理当前事项</button><button className="mini-button" onClick={() => void recordActivityFollowUp("hold")}>暂不安排</button></div></section>}</> : <p className="success-copy">该办理活动已{workItemActivity.status === "voided" ? "作废" : "结束"}，可查看保留的成员与结果。</p>}
              </section> : columnBatchTarget ? <section className="column-batch-panel">
                <div className="quick-panel-heading"><strong>阶段跟踪批量办理</strong><button type="button" className="text-button" onClick={clearColumnBatchTarget}>取消列选择</button></div>
                <p className="operation-lead">{columnBatchTarget.kind === "work_item" ? "事项" : "约束"} · <strong>{columnBatchTarget.label}</strong>，已选 {selectedIds.length} 个实际存在的实例。</p>
                {columnBatchTarget.kind === "work_item" ? <>
                  <button type="button" className="mini-button" disabled={!selectedIds.length} onClick={() => { setBatchArrangeOpen((value) => !value); void loadActivityJoinChoices(); }}>安排办理活动</button>
                  {batchArrangeOpen ? <section className="batch-arrange-form"><strong>新建活动</strong><label className="field"><span>活动名称</span><input className="input" value={batchDraft.name} onChange={(event) => setBatchDraft((current) => ({ ...current, name: event.target.value }))} /></label><label className="field"><span>日期（可选）</span><input className="input" type="date" value={batchDraft.scheduled_on} onChange={(event) => setBatchDraft((current) => ({ ...current, scheduled_on: event.target.value }))} /></label><label className="field"><span>说明（可选）</span><textarea className="textarea" rows={2} value={batchDraft.note} onChange={(event) => setBatchDraft((current) => ({ ...current, note: event.target.value }))} /></label><button className="action-button primary full" disabled={!batchDraft.name.trim() || executing} onClick={() => void createWorkItemActivity()}>保存办理活动</button>{activityJoinChoices.length ? <section className="quick-group"><strong>加入已有活动</strong>{activityJoinChoices.map((activity) => <button type="button" key={activity.id} className="batch-member-row" disabled={executing} onClick={() => void joinWorkItemActivity(activity)}><span>{activity.name}{activity.scheduled_on ? ` · ${activity.scheduled_on}` : ""}</span><small>{activity.status === "in_progress" ? "进行中" : "待办理"} · {activity.member_count} 个项目</small></button>)}</section> : <small className="muted-copy">当前没有同事项、未结束的可加入活动。</small>}</section> : null}
                  <label className="field"><span>办理动作</span><select className="select" value={columnWorkItemAction} onChange={(event) => { setColumnWorkItemAction(event.target.value as typeof columnWorkItemAction); setColumnBatchPreview(null); }}><option value="progress">添加共同进展</option><option value="update">修改事项设置</option><option value="complete">完成事项</option></select></label>
                  {columnWorkItemAction === "progress" ? <label className="field"><span>共同进展</span><textarea className="textarea" rows={3} value={columnBatchValue.progress_content} onChange={(event) => setColumnBatchValue((current) => ({ ...current, progress_content: event.target.value }))} /></label> : null}
                {columnWorkItemAction === "update" ? <div className="field-grid"><label className="field"><span>当前状态</span><select className="select" value={columnBatchValue.status} onChange={(event) => setColumnBatchValue((current) => ({ ...current, status: event.target.value }))}><option value="">不修改</option><option value="not_started">待办理</option><option value="in_progress">进行中</option><option value="paused">暂停</option></select></label><label className="field"><span>计划完成日期</span><input className="input" type="date" value={columnBatchValue.planned_date} onChange={(event) => setColumnBatchValue((current) => ({ ...current, planned_date: event.target.value }))} /></label><label className="field"><span>总览重点关注</span><select className="select" value={columnBatchValue.track_as_key_node} onChange={(event) => setColumnBatchValue((current) => ({ ...current, track_as_key_node: event.target.value }))}><option value="">不修改</option><option value="true">设为重点关注</option><option value="false">取消重点关注</option></select></label></div> : null}
                  {columnWorkItemAction === "complete" ? <div className="field-grid"><label className="field"><span>完成日期</span><input className="input" type="date" value={columnBatchValue.completed_on} onChange={(event) => setColumnBatchValue((current) => ({ ...current, completed_on: event.target.value }))} /></label><label className="field"><span>完成结果</span><input className="input" value={columnBatchValue.result} onChange={(event) => setColumnBatchValue((current) => ({ ...current, result: event.target.value }))} /></label><label className="field"><span>完成说明</span><input className="input" value={columnBatchValue.note} onChange={(event) => setColumnBatchValue((current) => ({ ...current, note: event.target.value }))} /></label></div> : null}
                </> : <>
                  <label className="field"><span>办理动作</span><select className="select" value={batchConstraintAction} onChange={(event) => { setBatchConstraintAction(event.target.value as typeof batchConstraintAction); setColumnBatchPreview(null); }}><option value="begin">开始办理</option><option value="progress">记录共同进展</option><option value="clear">解除约束</option><option value="mark_not_applicable">标记不适用</option><option value="invalidate">使结论失效</option></select></label>
                  {batchConstraintAction !== "begin" ? <label className="field"><span>{batchConstraintAction === "progress" ? "共同进展" : batchConstraintAction === "clear" ? "共同结论或说明（可选）" : "原因（必填）"}</span><textarea className="textarea" rows={2} value={batchConstraintReason} onChange={(event) => setBatchConstraintReason(event.target.value)} /></label> : null}
                </>}
                <button className="mini-button" disabled={!selectedIds.length || executing} onClick={() => void previewColumnBatch()}>{columnBatchTarget.kind === "work_item" ? "保存批量办理" : "预检批量办理"}</button>
                {columnBatchPreview ? <div className="operation-preview"><strong>可办理 {columnBatchPreview.eligible.length} 个</strong>{columnBatchPreview.ineligible.length ? <small>不可办理：{columnBatchPreview.ineligible.map((item) => item.name || item.project_id).join("、")}</small> : <small>全部项目符合条件</small>}{columnBatchTarget.kind === "external_constraint" && columnBatchTarget.impactScope === "effective_budget" && batchConstraintAction === "clear" ? <div className="batch-budget-outcomes">{columnBatchPreview.eligible.map((item) => { const value = batchBudgetOutcomes[item.project_id] ?? { approved_budget: "", concluded_on: today(), note: "", cleared: true, set_effective_budget_source: true }; const update = (patch: Partial<typeof value>) => setBatchBudgetOutcomes((current) => ({ ...current, [item.project_id]: { ...value, ...patch } })); return <fieldset key={item.project_id}><legend>{item.name} · {item.project_code}</legend><label className="field"><span>有效预算（万元）</span><input className="input" type="number" min="0" value={value.approved_budget} onChange={(event) => update({ approved_budget: event.target.value })} /></label></fieldset>; })}</div> : null}{columnBatchTarget.kind === "work_item" ? <button className="action-button primary full" disabled={Boolean(columnBatchPreview.ineligible.length) || executing} onClick={() => void executeColumnWorkItemBatch()}>确认批量办理</button> : <button className="action-button primary full" disabled={Boolean(columnBatchPreview.ineligible.length) || executing} onClick={() => void submitBatchConstraintAction()}>确认批量办理</button>}</div> : null}
              </section> : quickItem ? <section className="quick-panel">
                <button type="button" className="quick-return" onClick={() => { setQuickItem(null); setQuickProjectId(null); setQuickProject(null); }}>← 返回批量操作</button>
                <div className="quick-context"><span>当前项目</span><strong>{quickProject?.name || "项目"}</strong><small>{quickProject?.project_code}</small><div><b>{quickItem.name}</b><em>{workStatusLabel(quickItem.status)}</em></div></div>
                {quickItem.status === "completed" ? <>
                  <section className="quick-group quick-completed-summary"><strong>已完成</strong><dl><div><dt>完成日期</dt><dd>{String(quickItem.completion_record_json?.completed_on || quickItem.completion_record_json?.completed_at || "未记录").slice(0, 10)}</dd></div><div><dt>完成结果</dt><dd>{String(quickItem.completion_record_json?.result || "未记录")}</dd></div><div><dt>完成说明</dt><dd>{String(quickItem.completion_record_json?.note || "—")}</dd></div></dl></section>
                  {quickCorrectingCompletion ? <section className="quick-complete-form"><div className="quick-complete-heading"><strong>修改完成事项</strong></div><div className="quick-complete-info"><label className="field"><span>完成结果</span><input className="input" value={quickCompletionResult} onChange={(event) => setQuickCompletionResult(event.target.value)} /></label><label className="field"><span>完成日期</span><input className="input" type="date" value={quickCompletionDate} onChange={(event) => setQuickCompletionDate(event.target.value)} /></label><label className="field quick-complete-note"><span>完成说明</span><textarea className="textarea" rows={2} value={quickCompletionNote} onChange={(event) => setQuickCompletionNote(event.target.value)} /></label></div><div className="quick-complete-actions"><button className="mini-button" onClick={() => setQuickCorrectingCompletion(false)}>取消</button><button className="mini-button active" onClick={() => void correctQuickCompletion()}>保存更正</button></div></section> : null}
                  {quickSupplementingNote ? <section className="quick-group"><strong>补充备注</strong><textarea className="textarea" rows={3} value={quickProgress} onChange={(event) => setQuickProgress(event.target.value)} /><button className="mini-button" onClick={() => void addQuickProgress()}>记录备注</button></section> : null}
                  <div className="quick-actions"><button className="mini-button" onClick={() => { const record = quickItem.completion_record_json || {}; setQuickCompletionResult(String(record.result || "")); setQuickCompletionNote(String(record.note || "")); setQuickCompletionDate(String(record.completed_on || record.completed_at || today()).slice(0, 10)); setQuickCorrectingCompletion(true); }}>修改事项</button><button className="mini-button" onClick={() => setDialog({ kind: "reopen", title: "重开事项", value: "", target: quickItem })}>重开事项</button><button className="mini-button" onClick={() => setQuickSupplementingNote((value) => !value)}>补充备注</button></div>
                </> : <>
                  <section className="quick-group"><strong>进展</strong><div className="quick-log-list">{(showAllQuickLogs ? quickLogs : quickLogs.slice(0, 3)).map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDate(log.created_at)} · {log.operator}</small><div className="log-actions"><button className="text-button" onClick={() => void editQuickProgress(log)}>编辑</button><button className="text-button" onClick={() => void deleteQuickProgress(log)}>删除</button></div></article>)}</div>{quickLogs.length > 3 ? <button className="text-button" onClick={() => setShowAllQuickLogs((value) => !value)}>{showAllQuickLogs ? "收起记录" : "查看全部"}</button> : null}<textarea className="textarea" rows={3} value={quickProgress} onChange={(event) => setQuickProgress(event.target.value)} placeholder="补充备注或进展" /><button className="mini-button" onClick={() => void addQuickProgress()}>记录进展</button></section>
                  <section className="quick-group"><div className="quick-fields"><label className="field"><span>当前状态</span><select className="select" value={quickItem.status} onChange={(event) => setQuickItem((item) => item ? { ...item, status: event.target.value } : item)}><option value="not_started">待办理</option><option value="in_progress">进行中</option><option value="paused">暂停</option><option value="not_applicable">不适用</option></select></label>{quickItem.status === "in_progress" ? <label className="field"><span>开始日期</span><input className="input" value={quickItem.started_on || "未记录"} readOnly /></label> : null}<label className="field"><span>计划完成日期</span><input className="input" type="date" value={quickItem.planned_date} onChange={(event) => setQuickItem((item) => item ? { ...item, planned_date: event.target.value } : item)} /></label></div><label className="toggle"><input type="checkbox" checked={Boolean(quickItem.track_as_key_node)} onChange={(event) => setQuickItem((item) => item ? { ...item, track_as_key_node: event.target.checked } : item)} /><span>☆ 重点关注</span></label></section>
                  {quickCompleting ? <section className="quick-complete-form"><div className="quick-complete-heading"><strong>完成事项</strong></div><div className="quick-complete-info"><label className="field"><span>完成结果</span><input className="input" value={quickCompletionResult} onChange={(event) => setQuickCompletionResult(event.target.value)} placeholder="可选" /></label><label className="field"><span>完成日期</span><input className="input" type="date" value={quickCompletionDate} onChange={(event) => setQuickCompletionDate(event.target.value)} /></label><label className="field quick-complete-note"><span>完成说明</span><textarea className="textarea" rows={2} value={quickCompletionNote} onChange={(event) => setQuickCompletionNote(event.target.value)} placeholder="可选" /></label></div><div className="quick-complete-actions"><button className="mini-button" onClick={() => setQuickCompleting(false)}>取消</button><button className="mini-button active" onClick={() => void quickComplete()}>确认完成</button></div></section> : null}
                  <div className="quick-actions"><button className="mini-button" onClick={() => void saveQuickItem()}>保存</button>{quickItem.status === "not_started" ? <button className="mini-button" onClick={() => void startQuickItem()}>开始办理</button> : null}{!quickCompleting ? <button className="mini-button active" onClick={() => { setQuickCompleting(true); setQuickCompletionDate(today()); }}>完成事项</button> : null}</div>
                </>}
              </section> : quickConstraint ? <section className="quick-panel constraint-quick-panel">
                {quickConstraintHasBatchContext ? <button type="button" className="quick-return" onClick={() => { setQuickConstraint(null); setQuickConstraintFromList(false); }}>← 返回批量操作</button> : <button type="button" className="quick-return" onClick={closeRail}>关闭办理</button>}
                {quickConstraintFromList ? <button type="button" className="text-button" onClick={() => { setQuickConstraint(null); void openQuickConstraintList(quickProjectId!); }}>返回约束列表</button> : null}
                <div className="quick-context"><span>当前项目</span><strong>{quickProject?.name || "项目"}</strong><small>{quickProject?.project_code}</small><div><b>{quickConstraint.name}</b><em>{constraintStatusLabel(quickConstraint.handling_status)} · {clearanceLabel(quickConstraint.clearance_status)}</em><small>影响范围：{constraintImpactLabel(quickConstraint.impact_scope)}</small></div></div>
                <section className="quick-group"><strong>进展</strong>
                  <div className="quick-log-list">{(showAllQuickLogs ? quickConstraintLogs : quickConstraintLogs.slice(0, 3)).map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDate(log.created_at)} · {log.operator}</small><div className="log-actions"><button className="text-button" onClick={() => editQuickConstraintProgress(log)}>编辑</button><button className="text-button" onClick={() => deleteQuickConstraintProgress(log)}>删除</button></div></article>)}</div>
                  {!quickConstraintLogs.length ? <p className="muted-copy">暂无进展记录</p> : null}
                  {quickConstraintLogs.length > 3 ? <button className="text-button" onClick={() => setShowAllQuickLogs((value) => !value)}>{showAllQuickLogs ? "收起进展记录" : "查看全部进展记录"}</button> : null}
                  <textarea className="textarea" rows={3} value={quickProgress} onChange={(event) => setQuickProgress(event.target.value)} placeholder="记录本次外部办理进展" />
                  <button className="mini-button" onClick={() => void addQuickConstraintProgress()}>记录进展</button>
                </section>
                <section className="quick-group"><strong>{quickConstraint.handling_status === "not_started" ? "办理" : quickConstraint.clearance_status === "unresolved" ? "当前办理" : "结论"}</strong>
                  {quickConstraint.clearance_status === "unresolved" ? <div className="work-item-actions">{quickConstraint.handling_status === "not_started" ? <button className="mini-button" onClick={() => void submitQuickConstraintAction("begin")}>开始办理</button> : null}<button className="mini-button active" onClick={() => { setQuickConstraintAction("clear"); setQuickConstraintActionText(""); setQuickConstraintBudget(""); setQuickConstraintBudgetError(""); }}>解除约束</button></div> : <p className="muted-copy">{constraintSummary(quickConstraint)} · {clearanceLabel(quickConstraint.clearance_status)}</p>}
                  <details><summary>更多操作</summary><div className="work-item-actions"><button className="mini-button" onClick={() => { setQuickConstraintAction("mark_not_applicable"); setQuickConstraintActionText(""); }}>标记不适用</button><button className="mini-button danger" onClick={() => { setQuickConstraintAction("invalidate"); setQuickConstraintActionText(""); }}>结论失效</button></div></details>
                  {quickConstraintAction ? <div className="constraint-conclusion"><strong>{quickConstraintAction === "clear" ? "解除约束" : quickConstraintAction === "invalidate" ? "使结论失效" : "标记不适用"}</strong>{quickConstraintAction === "clear" ? <><textarea className="textarea" rows={2} value={quickConstraintActionText} onChange={(event) => setQuickConstraintActionText(event.target.value)} placeholder="结论或说明（可选）" />{quickConstraint.impact_scope === "effective_budget" ? <label className="field"><span>解除后的有效预算（万元）<b aria-hidden="true">*</b></span><input ref={quickConstraintBudgetRef} className={`input ${quickConstraintBudgetError ? "input-error" : ""}`} type="number" min="0" value={quickConstraintBudget} onChange={(event) => { setQuickConstraintBudget(event.target.value); setQuickConstraintBudgetError(""); }} aria-invalid={Boolean(quickConstraintBudgetError)} aria-describedby={quickConstraintBudgetError ? "quick-constraint-budget-error" : undefined} />{quickConstraintBudgetError ? <small id="quick-constraint-budget-error" className="field-error">{quickConstraintBudgetError}</small> : null}</label> : null}</> : <textarea className="textarea" rows={2} value={quickConstraintActionText} onChange={(event) => setQuickConstraintActionText(event.target.value)} placeholder="原因（必填）" />}<div className="work-item-actions"><button className="mini-button" onClick={() => { setQuickConstraintAction(null); setQuickConstraintBudgetError(""); }}>取消</button><button className="mini-button active" disabled={quickConstraintAction !== "clear" && !quickConstraintActionText.trim()} onClick={() => quickConstraintAction === "clear" ? submitQuickConstraintClear() : void submitQuickConstraintAction(quickConstraintAction, { reason: quickConstraintActionText.trim() })}>确认</button></div></div> : null}
                </section>
              </section> : quickConstraintList ? <section className="quick-panel constraint-quick-panel"><button type="button" className="quick-return" onClick={() => { setQuickConstraintList(null); }}>← 返回批量操作</button><div className="quick-context"><span>当前项目</span><strong>{quickProject?.name || "项目"}</strong><small>{quickProject?.project_code}</small></div><section className="quick-group"><div className="quick-panel-heading"><strong>外部约束</strong><span>{quickConstraintList.length} 项</span></div>{quickConstraintList.length ? <div className="constraint-list">{quickConstraintList.map((constraint) => <button key={constraint.id} type="button" className="constraint-quick-entry" onClick={() => void openQuickConstraint(quickProjectId!, constraint.id, true)}><strong>{constraint.name}</strong><small>{constraintStatusLabel(constraint.handling_status)} · {clearanceLabel(constraint.clearance_status)}</small><em>{constraint.latest_progress_summary || "暂无进展"}</em></button>)}</div> : <p className="muted-copy">当前无外部约束。</p>}</section></section> : <>{operationMode === "advance" ? <>
                <section className="operation-preview"><strong>常规年度项目请在“年度预算安排”中统一选择、保存并确认。</strong><button className="mini-button" onClick={() => setTableView("annual")}>进入年度预算安排</button></section>
                <details className="direct-advancement">
                <summary>推进例外操作</summary>
                <p className="operation-lead">常规年度项目请通过年度计划确认。此处只处理已确认方案后的例外。</p>
                <label className="field"><span>操作</span><select className="select" value={annualExceptionAction} onChange={(event) => setAnnualExceptionAction(event.target.value as typeof annualExceptionAction)}><option value="supplement">补充纳入本年度</option><option value="cancel">取消推进</option><option value="defer">暂缓推进</option><option value="resume">恢复推进</option><option value="special">特批推进</option></select></label>
                <label className="field"><span>实施年份</span><input className="input" type="number" value={advancementYear} onChange={(event) => setAdvancementYear(event.target.value)} /></label>
                <label className="field"><span>{annualExceptionAction === "special" ? "特批理由" : annualExceptionAction === "cancel" ? "取消原因" : annualExceptionAction === "defer" ? "暂缓原因" : annualExceptionAction === "resume" ? "恢复原因" : "补充纳入理由"}</span><textarea className="textarea" value={comment} onChange={(event) => setComment(event.target.value)} rows={3} /></label>
                <button className="action-button primary full" disabled={!selectedIds.length || !comment.trim() || executing} onClick={() => void submitAnnualException()}><CheckCircle2 size={16} />确认{({ supplement: "补充纳入", cancel: "取消推进", defer: "暂缓推进", resume: "恢复推进", special: "特批推进" }[annualExceptionAction])}</button>
                {!selectedIds.length ? <p className="notice error">请先勾选项目；混入不符合本操作的项目时，系统会整批拒绝并说明原因。</p> : null}
                {advancementAction === "backfill" ? <details><summary>历史实施补录</summary><label className="toggle"><input type="checkbox" checked={backfillClearZeroBudget} onChange={(event) => setBackfillClearZeroBudget(event.target.checked)} /><span>将当前 0 预算标为未记录</span></label><button className="mini-button" disabled={!comment || executing} onClick={() => void submitCompletedAdvancementBackfill()}>确认补录历史实施</button></details> : null}
                </details>
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
                  <select className="select" value={item.status} onChange={(event) => updateDraft(index, { status: event.target.value })}><option value="not_started">待办理</option><option value="in_progress">进行中</option></select>
                  <label className="toggle"><input type="checkbox" checked={Boolean(item.track_as_key_node)} onChange={(event) => updateDraft(index, { track_as_key_node: event.target.checked })} /><span>☆ 重点关注</span></label>
                  <textarea className="textarea" rows={2} value={item.note || ""} onChange={(event) => updateDraft(index, { note: event.target.value })} placeholder="附加备注" />
                  <label className="field"><span>添加位置</span><select className="select" value={item.insert_mode || "after_current"} onChange={(event) => updateDraft(index, { insert_mode: event.target.value as "after_current" | "last" })}><option value="after_current">添加到当前事项后</option><option value="last">添加到最后</option></select></label>
                  <label className="toggle"><input type="checkbox" checked={Boolean(item.save_as_common)} onChange={(event) => updateDraft(index, { save_as_common: event.target.checked })} /><span>保存为常用事项</span></label>
                </div>)}
                <button className="mini-button full" onClick={() => setDraftItems((items) => [...items, emptyDraft()])}><Plus size={15} />再添加一项</button>
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
                <label className="field"><span>常用外部约束</span><select className="select" value={constraintTemplateId ?? ""} onChange={(event) => { const next = Number(event.target.value) || null; setConstraintTemplateId(next); const template = activeConstraintTemplates.find((item) => item.id === next); if (template) { setConstraintName(template.name); setConstraintImpactScope(template.impact_scope || "none"); setConstraintImpactNote(template.impact_note || ""); } }}><option value="">选择常用约束（可选）</option>{activeConstraintTemplates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                <label className="field"><span>约束名称</span><input className="input" value={constraintName} onChange={(event) => setConstraintName(event.target.value)} placeholder="例如：上级预算核定" /></label>
                {!constraintTemplateId ? <><label className="field"><span>影响范围</span><select className="select" value={constraintImpactScope} onChange={(event) => setConstraintImpactScope(event.target.value as typeof constraintImpactScope)}><option value="none">不影响项目字段</option><option value="effective_budget">影响有效预算</option><option value="other">其他影响</option></select></label>{constraintImpactScope === "other" ? <label className="field"><span>影响说明</span><input className="input" value={constraintImpactNote} onChange={(event) => setConstraintImpactNote(event.target.value)} /></label> : null}</> : null}
                <label className="field"><span>初始办理状态</span><select className="select" value={constraintStatus} onChange={(event) => setConstraintStatus(event.target.value)}><option value="not_started">待办理</option><option value="in_progress">办理中</option></select></label>
                <label className="toggle"><input type="checkbox" checked={saveConstraintAsCommon} onChange={(event) => setSaveConstraintAsCommon(event.target.checked)} /><span>保存为常用外部约束</span></label>
                <button className="action-button primary full" disabled={!selectedIds.length || executing} onClick={() => void submitBatchConstraints()}>确认添加外部约束</button>
                <hr />
                <p className="mini-section-heading"><strong>批量办理已有约束</strong></p>
                <p className="muted-copy">仅对每个项目均存在同一模板约束的项目执行；先预检，存在不合格项目时不会部分提交。</p>
                <label className="field"><span>办理动作</span><select className="select" value={batchConstraintAction} onChange={(event) => { setBatchConstraintAction(event.target.value as typeof batchConstraintAction); setBatchConstraintPreview(null); }}><option value="begin">开始办理</option><option value="progress">记录共同进展</option><option value="clear">解除约束</option><option value="mark_not_applicable">标记不适用</option></select></label>
                {batchConstraintAction !== "begin" && !isBatchBudgetDetermination ? <label className="field"><span>{batchConstraintAction === "progress" ? "共同进展" : batchConstraintAction === "clear" ? "结论或说明（可选）" : "原因"}</span><textarea className="textarea" rows={2} value={batchConstraintReason} onChange={(event) => setBatchConstraintReason(event.target.value)} /></label> : null}
                <button className="mini-button" disabled={!selectedIds.length || !constraintTemplateId} onClick={() => void previewBatchConstraintAction()}>预检批量办理</button>
                {batchConstraintPreview ? <div className="operation-preview"><strong>可办理 {batchConstraintPreview.eligible.length} 个</strong>{batchConstraintPreview.ineligible.length ? <small>不可办理 {batchConstraintPreview.ineligible.length} 个：{batchConstraintPreview.ineligible.map((item) => item.name || item.project_id).join("、")}</small> : <small>全部项目符合条件</small>}{isBatchBudgetDetermination ? <div className="batch-budget-outcomes">{batchConstraintPreview.eligible.map((item) => { const value = batchBudgetOutcomes[item.project_id] ?? { approved_budget: "", concluded_on: today(), note: "", cleared: true, set_effective_budget_source: true }; const update = (patch: Partial<typeof value>) => setBatchBudgetOutcomes((current) => ({ ...current, [item.project_id]: { ...value, ...patch } })); return <fieldset key={item.project_id}><legend>{item.name} · {item.project_code}</legend><label className="field"><span>有效预算（万元）</span><input className="input" type="number" min="0" value={value.approved_budget} onChange={(event) => update({ approved_budget: event.target.value })} /></label><label className="field"><span>结论或说明（可选）</span><input className="input" value={value.note} onChange={(event) => update({ note: event.target.value })} /></label></fieldset>; })}</div> : null}<button className="action-button primary full" disabled={Boolean(batchConstraintPreview.ineligible.length)} onClick={() => void submitBatchConstraintAction()}>确认批量办理</button></div> : null}
              </> : null}
              {operationMode === "stage" ? <>
                {directStageAction === "establish" ? <><label className="field"><span>立项文件号</span><input className="input" value={establishmentDocumentNo} onChange={(event) => setEstablishmentDocumentNo(event.target.value)} placeholder="例如：杭校立〔2026〕12号" /></label><button className="action-button primary full" disabled={!establishmentDocumentNo.trim() || executing} onClick={() => void executeDirectStage("establish")}><CheckCircle2 size={16} />登记立项并进入项目库</button></> : null}
                {directStageAction === "complete" ? <button className="action-button primary full" disabled={executing} onClick={() => void executeDirectStage("complete")}><CheckCircle2 size={16} />完成项目</button> : null}
                {!directStageAction ? <p className="muted-copy">当前选择不能执行普通 Stage 推进；请按同一 Stage 分别选择，或使用特批处理例外。</p> : null}
                <details className="force-stage-action"><summary>PMO 特批强制变更（例外）</summary><label className="field"><span>目标 Stage</span><select className="select" value={selectedTarget} onChange={(event) => setSelectedTarget(event.target.value)}><option value="">选择固定 Stage</option><option value="draft">未立项</option><option value="established">项目库—未实施</option><option value="closed">已完成</option><option value="terminated">已废弃</option></select></label><label className="field"><span>变更理由</span><textarea className="textarea" value={comment} onChange={(event) => setComment(event.target.value)} rows={3} /></label><button className="action-button primary full" disabled={!selectedIds.length || !selectedTarget || !comment || executing} onClick={() => void executeForceBatch()}><CheckCircle2 size={16} />确认特批变更</button></details>
              </> : null}
              {operationMode === "config" ? <section className="config-panel"><p className="operation-lead">项目分类是唯一的 PMO 分类字段；拖动条目调整显示与默认排序顺序。</p><div className="field-grid"><input className="input" value={newClassificationName} onChange={(event) => setNewClassificationName(event.target.value)} placeholder="新增项目分类" /><input className="input" value={newClassificationPrefix} onChange={(event) => setNewClassificationPrefix(event.target.value)} placeholder="编号前缀，例如 EQ" /></div><button className="mini-button" onClick={() => void addProjectClassification()}>新增项目分类</button><div className="template-manager config-sort-list">{projectTypes.map((item) => <div key={item.id} draggable onDragStart={() => setDraggedProjectTypeId(item.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (draggedProjectTypeId != null) void reorderProjectClassifications(draggedProjectTypeId, item.id); setDraggedProjectTypeId(null); }}><span className="drag-handle" aria-label="拖动调整项目分类顺序">⋮⋮</span><span>{item.name} · {item.code_prefix}</span><button className="text-button" onClick={() => void saveProjectClassification(item, { is_active: !item.is_active })}>{item.is_active ? "停用" : "恢复"}</button></div>) || <span>暂无项目分类</span>}</div><p className="mini-section-heading"><strong>部门排序</strong></p><div className="template-manager config-sort-list">{departments.map((department) => <div key={department} draggable onDragStart={() => setDraggedDepartment(department)} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (draggedDepartment) void reorderDepartments(draggedDepartment, department); setDraggedDepartment(null); }}><span className="drag-handle" aria-label="拖动调整部门顺序">⋮⋮</span><span>{department}</span></div>)}</div></section> : null}
              {operationMode === "batch" ? <section className="batch-history-panel"><div className="quick-panel-heading"><strong>办理活动</strong><button type="button" className="text-button" onClick={() => void loadBatchHistory()}>刷新</button></div><div className="field-grid"><label className="field"><span>年度</span><input className="input" inputMode="numeric" value={batchHistoryFilters.year} onChange={(event) => setBatchHistoryFilters((value) => ({ ...value, year: event.target.value }))} placeholder="例如 2026" /></label><label className="field"><span>状态</span><select className="select" value={batchHistoryFilters.status} onChange={(event) => setBatchHistoryFilters((value) => ({ ...value, status: event.target.value }))}><option value="">全部</option><option value="not_started">待办理</option><option value="in_progress">进行中</option><option value="ended">已结束</option><option value="voided">已作废</option></select></label></div><label className="field"><span>事项、项目或活动名称</span><input className="input" value={batchHistoryFilters.keyword} onChange={(event) => setBatchHistoryFilters((value) => ({ ...value, keyword: event.target.value }))} /></label><button className="mini-button" onClick={() => void loadBatchHistory()}>查询办理活动</button><div className="batch-history">{batchHistory.map((activity) => <button type="button" key={activity.id} className="batch-history-row" onClick={() => void openWorkItemActivity(activity.id, "batch")}><strong>{activity.name}</strong><small>{activity.work_item_name} · {activity.scheduled_on || "未设日期"} · {activity.member_count} 项 · {activity.status === "not_started" ? "待办理" : activity.status === "in_progress" ? "进行中" : activity.status === "ended" ? "已结束" : "已作废"}</small></button>)}{batchHistoryOpen && !batchHistory.length ? <small>暂无符合条件的办理活动。</small> : null}</div></section> : null}</>}
            </div>
          </div>

        </aside>
        </>}

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
              <span>选择 CSV / XLSX / XLS 后自动生成预览</span>
              <input id="import-file" name="import-file" type="file" accept=".csv,.xlsx,.xls" onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) void previewImportFile(file); }} />
            </label>
            <button className="action-button primary compact" type="submit">
              <Database size={16} />
              重新生成预览
            </button>
          </form>
          {importPreview ? (
            <div className="preview-grid">
              <article className="preview-card"><strong>{importPreview.valid_rows}</strong><span>可导入行</span></article>
              <article className="preview-card"><strong>{importPreview.invalid_rows}</strong><span>异常行</span></article>
              <article className="preview-card"><strong>{importPreview.total_rows}</strong><span>总行数</span></article>
              <button className="action-button ghost compact" disabled={importPreview.invalid_rows > 0} onClick={() => void commitImport()}><Send size={16} />确认写入</button>
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
          <p className="muted-copy">{dialog.kind === "delete-log" ? "请填写删除原因。记录会从日常界面隐藏，但审计仍会完整保留。" : dialog.kind === "archive-template" ? "归档后不会影响已下发事项和历史记录。" : dialog.kind === "reopen" ? "请填写重开原因。" : "更新后将立即回显到当前事项。"}</p>
          <textarea className="textarea" rows={3} autoFocus value={dialog.value} placeholder={dialog.kind === "delete-log" || dialog.kind === "archive-template" || dialog.kind === "reopen" ? "请填写原因（必填）" : "进展内容"} onChange={(event) => setDialog({ ...dialog, value: event.target.value })} />
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
          <div className="field-grid"><label className="field"><span>学院</span><input className="input" list="department-suggestions" value={newProject.department} onChange={(event) => setNewProject({ ...newProject, department: event.target.value })} placeholder="选择或填写学院" /><datalist id="department-suggestions">{departments.map((department) => <option key={department} value={department} />)}</datalist></label><input className="input" value={newProject.project_manager} onChange={(event) => setNewProject({ ...newProject, project_manager: event.target.value })} placeholder="负责人" /></div>
          <div className="field-grid"><select className="select" value={newProject.project_type} onChange={(event) => setNewProject({ ...newProject, project_type: event.target.value, procurement_nature: "", location: "" })}><option value="">选择项目分类</option>{projectTypes.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.code}>{item.name}</option>)}</select><input className="input" inputMode="decimal" value={newProject.budget} onChange={(event) => setNewProject({ ...newProject, budget: event.target.value })} placeholder="初始预算（万元）" /></div>
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
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [workItems, setWorkItems] = useState<WorkItem[]>([]);
  const [templates, setTemplates] = useState<WorkItemTemplate[]>([]);
  const [projectTypes, setProjectTypes] = useState<ProjectTypeDefinition[]>([]);
  const [externalConstraints, setExternalConstraints] = useState<ProjectExternalConstraint[]>([]);
  const [constraintTemplates, setConstraintTemplates] = useState<ExternalConstraintTemplate[]>([]);
  const [addingConstraint, setAddingConstraint] = useState(false);
  const [newConstraintTemplateId, setNewConstraintTemplateId] = useState<number | null>(null);
  const [newConstraintName, setNewConstraintName] = useState("");
  const [newConstraintImpactScope, setNewConstraintImpactScope] = useState<"none" | "effective_budget" | "other">("none");
  const [newConstraintImpactNote, setNewConstraintImpactNote] = useState("");
  const [conclusionBudget, setConclusionBudget] = useState("");
  const [conclusionBudgetError, setConclusionBudgetError] = useState("");
  const conclusionBudgetRef = useRef<HTMLInputElement>(null);
  const [conclusionResult, setConclusionResult] = useState("");
  const [conclusionNote, setConclusionNote] = useState("");
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
  const [isReordering, setIsReordering] = useState(false);
  const [newDraft, setNewDraft] = useState<WorkItemDraft>(emptyDraft());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [completionId, setCompletionId] = useState<number | null>(null);
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
      apiGet<WorkItem[]>(`/projects/${projectId}/work-items`),
      apiGet<WorkItemTemplate[]>("/work-item-templates"),
      apiGet<ProjectTypeDefinition[]>("/project-types"),
      apiGet<AuditEvent[]>(`/projects/${projectId}/audit-events`),
      apiGet<ProjectExternalConstraint[]>(`/projects/${projectId}/external-constraints`),
      apiGet<ExternalConstraintTemplate[]>("/external-constraint-templates"),
    ])
      .then(([projectData, workItemData, templateData, projectTypeData, auditData, constraintData, constraintTemplateData]) => {
        setProject(projectData);
        setWorkItems(workItemData);
        setTemplates(templateData);
        setProjectTypes(projectTypeData);
        setAuditEvents(auditData);
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
    const [projectData, workItemData, auditData, constraintData] = await Promise.all([
      apiGet<Project>(`/projects/${projectId}`),
      apiGet<WorkItem[]>(`/projects/${projectId}/work-items`),
      apiGet<AuditEvent[]>(`/projects/${projectId}/audit-events`),
      apiGet<ProjectExternalConstraint[]>(`/projects/${projectId}/external-constraints`),
    ]);
    setProject(projectData);
    setWorkItems(workItemData);
    setAuditEvents(auditData);
    setExternalConstraints(constraintData);
  }

  async function addWorkItem() {
    if (!projectId || !newDraft.name.trim()) return;
    await apiPost<WorkItem>(`/projects/${projectId}/work-items`, { ...newDraft, name: newDraft.name.trim(), operator: "PMO办公室" });
    setNewDraft(emptyDraft()); setAddingItem(false);
    await refreshDetailProjection();
  }

  async function completeWorkItem(item: WorkItem) {
    if (!projectId) return;
    await apiPost<WorkItem>(`/projects/${projectId}/work-items/${item.id}/complete`, { operator: "PMO办公室", result: completionResult.trim() || "已完成", completed_on: completionDate || null, note: completionNote.trim() || null });
    setCompletionId(null); setCompletionResult(""); setCompletionDate(""); setCompletionNote("");
    await refreshDetailProjection();
  }

  async function reorderWorkItems(targetId: number) {
    if (!projectId || !draggedWorkItemId || draggedWorkItemId === targetId) return;
    const from = orderedWorkItems.findIndex((item) => item.id === draggedWorkItemId);
    const to = orderedWorkItems.findIndex((item) => item.id === targetId);
    if (from < 0 || to < 0) return;
    const reordered = [...orderedWorkItems];
    const [moved] = reordered.splice(from, 1);
    reordered.splice(to, 0, moved);
    try {
      const updated = await apiPost<WorkItem[]>(`/projects/${projectId}/work-items/reorder`, { operator: "PMO办公室", item_ids: reordered.map((item) => item.id) });
      setWorkItems(updated); await refreshDetailProjection();
    } catch (err) { setError(err instanceof ApiError ? err.message : "事项顺序未保存，页面保持原状。"); }
    finally { setDraggedWorkItemId(null); }
  }

  async function updateWorkItem(item: WorkItem) {
    if (!projectId) return;
  const updated = await apiPatch<WorkItem>(`/projects/${projectId}/work-items/${item.id}`, { operator: "PMO办公室", status: item.status === "not_started" ? "in_progress" : item.status, planned_date: item.planned_date, note: item.note, content: item.content, track_as_key_node: Boolean(item.track_as_key_node) });
    setWorkItems((items) => items.map((current) => current.id === updated.id ? updated : current)); setEditingId(null);
    await refreshDetailProjection();
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
      await refreshDetailProjection();
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
      content: progressDraft.trim(), operator: "PMO办公室",
    });
    setProgressLogs((current) => ({ ...current, [itemId]: [...(current[itemId] ?? []), log] }));
    setProgressDraft("");
    await refreshDetailProjection();
  }

  async function saveDetailProgress() {
    if (!projectId || !editingProgressLog || !progressDialogValue.trim()) return;
    const updated = await apiPatch<WorkItemProgressLog>(`/projects/${projectId}/work-items/${editingProgressLog.project_work_item_id}/progress-logs/${editingProgressLog.id}`, { operator: "PMO办公室", content: progressDialogValue.trim(), is_timeline_highlight: editingProgressLog.is_timeline_highlight });
    setProgressLogs((logs) => ({ ...logs, [updated.project_work_item_id]: (logs[updated.project_work_item_id] ?? []).map((entry) => entry.id === updated.id ? updated : entry) }));
    setEditingProgressLog(null); setProgressDialogValue(""); await refreshDetailProjection();
  }

  async function deleteDetailProgress() {
    if (!projectId || !deletingProgressLog || !progressDialogValue.trim()) return;
    await apiDelete(`/projects/${projectId}/work-items/${deletingProgressLog.project_work_item_id}/progress-logs/${deletingProgressLog.id}`, { operator: "PMO办公室", reason: progressDialogValue.trim() });
    setProgressLogs((logs) => ({ ...logs, [deletingProgressLog.project_work_item_id]: (logs[deletingProgressLog.project_work_item_id] ?? []).filter((entry) => entry.id !== deletingProgressLog.id) }));
    setDeletingProgressLog(null); setProgressDialogValue(""); await refreshDetailProjection();
  }

  async function addExternalConstraint() {
    if (!projectId || !newConstraintName.trim()) return;
    try {
      await apiPost<ProjectExternalConstraint>(`/projects/${projectId}/external-constraints`, { template_id: newConstraintTemplateId, name: newConstraintName.trim(), impact_scope: newConstraintImpactScope, impact_note: newConstraintImpactNote, operator: "PMO办公室" });
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
    if (action === "clear") {
      const effectiveBudget = parseEffectiveBudget(conclusionBudget);
      if (constraint.impact_scope === "effective_budget" && effectiveBudget === null) {
        setConclusionBudgetError("请填写解除后的有效预算（万元）。");
        requestAnimationFrame(() => conclusionBudgetRef.current?.focus());
        return;
      }
      payload.result = conclusionResult.trim();
      payload.note = conclusionNote.trim();
      if (constraint.impact_scope === "effective_budget") payload.effective_budget = effectiveBudget;
    }
    if (action === "invalidate") payload.reason = invalidationReason;
    if (action === "mark_not_applicable" || action === "set_effective_budget_source") payload.reason = constraintActionReason;
    try {
      await apiPost<ProjectExternalConstraint>(`/projects/${projectId}/external-constraints/${constraint.id}/actions`, payload);
      if (action === "clear") { setConclusionBudget(""); setConclusionBudgetError(""); setConclusionResult(""); setConclusionNote(""); }
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
      await apiPatch<Project>(`/projects/${projectId}`, { name: project.name, department: project.department, major: project.major, project_manager: project.project_manager, location: project.location, procurement_nature: project.procurement_nature, project_type: project.project_type, description: project.description, budget: project.budget, actual_end_date: project.actual_end_date, operator: "PMO办公室", reason: projectReason });
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

  const detailProjectTypeLabel = (code: Project["project_type"]) => projectTypes.find((item) => item.code === code)?.name || projectTypeLabel(code);
  const orderedWorkItems = useMemo(() => sortProjectWorkItems(workItems), [workItems]);
  const stageEventsByAnchor = useMemo(() => {
    const entries = new Map<number | null, NonNullable<Project["stage_events"]>>();
    for (const event of project?.stage_events ?? []) {
      const anchor = orderedWorkItems.find((item) => item.first_activity_at && item.first_activity_at > event.occurred_at)?.id ?? null;
      entries.set(anchor, [...(entries.get(anchor) ?? []), event]);
    }
    return entries;
  }, [project?.stage_events, orderedWorkItems]);

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

      {error || feedback ? <div className="dashboard-notices">{error ? <div className="notice error">{error}</div> : null}{feedback ? <div className="notice success">{feedback}</div> : null}</div> : null}

      {loading ? (
        <div className="detail-loading">
          <LoaderCircle className="spin" size={22} />
          正在载入项目详情
        </div>
      ) : project ? (
        <main className="detail-layout">
          <section className="detail-main">
            <section className="detail-section detail-current-work">
              <div className="section-title"><div><p className="section-kicker">PROGRESS TRACKING</p><h2>进度跟踪</h2></div><div className="work-item-actions"><button className={`mini-button ${isReordering ? "active" : ""}`} onClick={() => setIsReordering((current) => !current)}>排列</button><button className="mini-button" onClick={() => setAddingItem((current) => !current)}><Plus size={15} />添加事项</button></div></div>
              {addingItem ? <div className="detail-add-item">
                <select className="select" value="" onChange={(event) => { const template = templates.find((item) => item.id === Number(event.target.value)); if (template) setNewDraft((current) => ({ ...current, name: template.name, content: template.default_content || "" })); }}><option value="">从常用事项选择（或直接自定义）</option>{templates.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>
                <input className="input" value={newDraft.name} onChange={(event) => setNewDraft((current) => ({ ...current, name: event.target.value }))} placeholder="事项名称*，例如：等学院补交采购需求书" />
                <textarea className="textarea" rows={3} value={newDraft.content} onChange={(event) => setNewDraft((current) => ({ ...current, content: event.target.value }))} placeholder="事项内容 / 当前需要做什么" />
                  <select className="select" value={newDraft.status} onChange={(event) => setNewDraft((current) => ({ ...current, status: event.target.value }))}><option value="not_started">待办理</option><option value="in_progress">进行中</option></select>
                <label className="field"><span>计划完成日期</span><input className="input" type="date" value={newDraft.planned_date || ""} onChange={(event) => setNewDraft((current) => ({ ...current, planned_date: event.target.value }))} /></label>
                <label className="toggle"><input type="checkbox" checked={Boolean(newDraft.track_as_key_node)} onChange={(event) => setNewDraft((current) => ({ ...current, track_as_key_node: event.target.checked }))} /><span>☆ 重点关注</span></label>
                <label className="field"><span>添加位置</span><select className="select" value={newDraft.insert_after_id ? String(newDraft.insert_after_id) : "last"} onChange={(event) => setNewDraft((current) => ({ ...current, insert_after_id: event.target.value === "last" ? null : Number(event.target.value) }))}><option value="last">添加到最后</option>{orderedWorkItems.map((item) => <option key={item.id} value={item.id}>添加到“{item.name}”之后</option>)}</select></label>
                <textarea className="textarea" rows={2} value={newDraft.note || ""} onChange={(event) => setNewDraft((current) => ({ ...current, note: event.target.value }))} placeholder="附加备注" />
                <div className="work-item-actions"><button className="mini-button" onClick={() => { setAddingItem(false); setNewDraft(emptyDraft()); }}>取消</button><button className="action-button primary" onClick={() => void addWorkItem()}>确认添加事项</button></div>
              </div> : null}
              <div className="work-item-list">
                {orderedWorkItems.length ? <>{orderedWorkItems.map((item) => (<Fragment key={item.id}>
                  {(stageEventsByAnchor.get(item.id) ?? []).map((event) => <div className={`stage-tracking-event stage-${event.kind}`} key={`stage-${event.id}`}><strong>{event.label}</strong><span>{formatDateTime(event.occurred_at)} · {event.operator}{event.comment ? ` · ${event.comment}` : ""}</span></div>)}
                  <div className={`work-item-row work-${item.status}`} key={item.id} draggable={isReordering} onDragStart={() => isReordering && setDraggedWorkItemId(item.id)} onDragOver={(event) => isReordering && event.preventDefault()} onDrop={() => void reorderWorkItems(item.id)}>
                    <div className="work-item-copy"><strong>{isReordering ? <span className="drag-handle" title="拖动调整事项顺序">⋮⋮</span> : null}{item.name}</strong><span className={`work-status work-${item.status}`}>{workStatusLabel(item.status)}</span>{item.status === "completed" ? <small>完成：{String(item.completion_record_json?.completed_on || item.completion_record_json?.completed_at || "未记录").slice(0, 10)}{item.completion_record_json?.result ? ` · ${String(item.completion_record_json.result)}` : ""}{item.completion_record_json?.note ? ` · ${String(item.completion_record_json.note)}` : ""}</small> : <small>计划完成：{item.planned_date || "未设置"}</small>}{item.latest_progress_summary ? <small>最近进展：{item.last_progress_at ? `${formatDateTime(item.last_progress_at)} · ` : ""}{item.latest_progress_summary}</small> : null}{item.content ? <p>{item.content}</p> : null}{item.note ? <small>{item.note}</small> : null}{item.track_as_key_node ? <em>☆ 重点关注</em> : null}</div>
                    {editingId === item.id ? <div className="work-item-edit"><select className="select" value={item.status} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, status: event.target.value } : current))}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="paused">暂停</option><option value="not_applicable">不适用</option></select><label className="field"><span>计划完成日期</span><input className="input" type="date" value={item.planned_date || ""} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, planned_date: event.target.value } : current))} /></label><textarea className="textarea" rows={2} value={item.content} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, content: event.target.value } : current))} placeholder="事项内容" /><label className="toggle"><input type="checkbox" checked={Boolean(item.track_as_key_node)} onChange={(event) => setWorkItems((items) => items.map((current) => current.id === item.id ? { ...current, track_as_key_node: event.target.checked } : current))} /><span>☆ 重点关注</span></label><button className="mini-button" onClick={() => void updateWorkItem(item)}>保存</button></div> : <div className="work-item-actions">{item.status !== "completed" && !item.cancelled_at ? <><button className="mini-button" onClick={() => setEditingId(item.id)}>更新</button><button className="mini-button" onClick={() => { setCompletionId(item.id); setCompletionDate(today()); setCompletionResult(""); setCompletionNote(""); }}>完成</button><button className="mini-button danger" onClick={() => { setItemAction({ item, action: "cancel" }); setItemActionReason(""); }}>取消事项</button>{!item.skipped_at ? <button className="mini-button" onClick={() => { setItemAction({ item, action: "skip" }); setItemActionReason(""); }}>跳过节点</button> : null}</> : item.status === "completed" ? <button className="mini-button" onClick={() => setReopenId(item.id)}>重开</button> : <span className="muted-copy">已取消</span>}<button className="mini-button" onClick={() => void toggleProgressLogs(item.id)}>进展 {expandedProgressItem === item.id ? "收起" : "记录"}</button></div>}
                    {completionId === item.id ? <div className="reopen-row"><input className="input" value={completionResult} onChange={(event) => setCompletionResult(event.target.value)} placeholder="完成结果（可选）" /><input className="input" type="date" value={completionDate} onChange={(event) => setCompletionDate(event.target.value)} /><textarea className="textarea" rows={2} value={completionNote} onChange={(event) => setCompletionNote(event.target.value)} placeholder="完成说明（可选）" /><button className="mini-button" onClick={() => void completeWorkItem(item)}>确认完成</button></div> : null}
                    {reopenId === item.id ? <div className="reopen-row"><input className="input" value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} placeholder="重开原因" /><button className="mini-button" onClick={() => void reopenWorkItem(item)}>确认重开</button></div> : null}
                    {expandedProgressItem === item.id ? <div className="progress-log-panel"><div className="progress-log-compose"><textarea className="textarea" rows={2} value={progressDraft} onChange={(event) => setProgressDraft(event.target.value)} placeholder="今天有什么变化？" /><button className="mini-button" onClick={() => void addProgressLog(item.id)}>记录进展</button></div>{(progressLogs[item.id] ?? []).length ? <div className="progress-log-list">{progressLogs[item.id].map((log) => <article key={log.id}><p>{log.content}</p><small>{formatDateTime(log.created_at)} · {log.operator}</small><div className="log-actions"><button className="text-button" onClick={() => { setEditingProgressLog(log); setProgressDialogValue(log.content); }}>编辑</button><button className="text-button" onClick={() => { setDeletingProgressLog(log); setProgressDialogValue(""); }}>删除</button></div></article>)}</div> : <p className="muted-copy">尚未记录过程进展。</p>}</div> : null}
                  </div>
                </Fragment>))}{(stageEventsByAnchor.get(null) ?? []).map((event) => <div className={`stage-tracking-event stage-${event.kind}`} key={`stage-${event.id}`}><strong>{event.label}</strong><span>{formatDateTime(event.occurred_at)} · {event.operator}{event.comment ? ` · ${event.comment}` : ""}</span></div>)}</> : <>{(stageEventsByAnchor.get(null) ?? []).map((event) => <div className={`stage-tracking-event stage-${event.kind}`} key={`stage-${event.id}`}><strong>{event.label}</strong><span>{formatDateTime(event.occurred_at)} · {event.operator}{event.comment ? ` · ${event.comment}` : ""}</span></div>)}<div className="empty-state">暂无跟踪事项。先添加一个当前正在推进的工作。</div></>}
              </div>
            </section>

            <section className="detail-section detail-governance governance-constraints">
              <div className="section-title"><div><p className="section-kicker">EXTERNAL CONDITIONS</p><h2>外部约束 <small>({externalConstraints.length} 项)</small></h2><p className="muted-copy">外部约束独立记录外部办理，不改变项目 Stage 或事项。</p></div><div className="work-item-actions"><button className="mini-button" onClick={() => setAddingConstraint((value) => !value)}><Plus size={15} />添加外部约束</button></div></div>
              {addingConstraint ? <div className="detail-add-item"><select className="select" value={newConstraintTemplateId ?? ""} onChange={(event) => { const id = Number(event.target.value) || null; setNewConstraintTemplateId(id); const template = constraintTemplates.find((item) => item.id === id); if (template) { setNewConstraintName(template.name); setNewConstraintImpactScope(template.impact_scope || "none"); setNewConstraintImpactNote(template.impact_note || ""); } }}><option value="">从常用约束选择（或直接新建）</option>{constraintTemplates.filter((item) => !item.archived_at).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input className="input" value={newConstraintName} onChange={(event) => setNewConstraintName(event.target.value)} placeholder="外部约束名称，例如：上级预算核定" />{!newConstraintTemplateId ? <><label className="field"><span>影响范围</span><select className="select" value={newConstraintImpactScope} onChange={(event) => setNewConstraintImpactScope(event.target.value as typeof newConstraintImpactScope)}><option value="none">不影响项目字段</option><option value="effective_budget">影响有效预算</option><option value="other">其他影响</option></select></label>{newConstraintImpactScope === "other" ? <input className="input" value={newConstraintImpactNote} onChange={(event) => setNewConstraintImpactNote(event.target.value)} placeholder="影响说明（必填）" /> : null}</> : null}<button className="action-button primary" onClick={() => void addExternalConstraint()}>确认添加外部约束</button></div> : null}
              <div className="constraint-list">{externalConstraints.length ? externalConstraints.map((constraint) => <article key={constraint.id} className="constraint-card"><div><strong>{constraint.name}</strong><small>{constraintStatusLabel(constraint.handling_status)} · {clearanceLabel(constraint.clearance_status)}</small>{constraint.impact_scope === "effective_budget" ? <small>影响范围：影响有效预算{constraint.is_effective_budget_source ? " · 当前有效预算来源" : ""}</small> : constraint.impact_scope === "other" ? <small>影响范围：其他影响 · {constraint.impact_note}</small> : null}{constraint.handling_status === "concluded" ? <small>{constraintSummary(constraint)}</small> : null}{constraint.latest_progress_summary ? <small>最近进展：{constraint.latest_progress_summary}</small> : null}</div><div className="work-item-actions">{constraint.clearance_status === "unresolved" ? <><button className="mini-button" onClick={() => void actOnConstraint(constraint, "begin")}>开始办理</button><button className="mini-button active" onClick={() => { setConstraintAction({ id: constraint.id, action: "clear" }); setConclusionResult(""); setConclusionNote(""); setConclusionBudget(""); setConclusionBudgetError(""); }}>解除约束</button></> : null}<details><summary>更多</summary><button className="text-button" onClick={() => { setConstraintAction({ id: constraint.id, action: "mark_not_applicable" }); setConstraintActionReason(""); }}>标记不适用</button><button className="text-button danger" onClick={() => setInvalidatingConstraintId(constraint.id)}>结论失效</button></details></div>{constraintAction?.id === constraint.id ? <div className="constraint-conclusion"><strong>{constraintAction.action === "clear" ? "解除约束" : "标记不适用"}</strong>{constraintAction.action === "clear" ? <><textarea className="textarea" rows={2} value={conclusionResult} onChange={(event) => setConclusionResult(event.target.value)} placeholder="结论（可选）" /><textarea className="textarea" rows={2} value={conclusionNote} onChange={(event) => setConclusionNote(event.target.value)} placeholder="说明（可选）" />{constraint.impact_scope === "effective_budget" ? <label className="field"><span>解除后的有效预算（万元）<b aria-hidden="true">*</b></span><input ref={conclusionBudgetRef} className={`input ${conclusionBudgetError ? "input-error" : ""}`} type="number" min="0" value={conclusionBudget} onChange={(event) => { setConclusionBudget(event.target.value); setConclusionBudgetError(""); }} aria-invalid={Boolean(conclusionBudgetError)} aria-describedby={conclusionBudgetError ? `constraint-budget-error-${constraint.id}` : undefined} />{conclusionBudgetError ? <small id={`constraint-budget-error-${constraint.id}`} className="field-error">{conclusionBudgetError}</small> : null}</label> : null}</> : <textarea className="textarea" rows={2} value={constraintActionReason} onChange={(event) => setConstraintActionReason(event.target.value)} placeholder="原因（必填）" />}<div className="work-item-actions"><button className="mini-button" onClick={() => { setConstraintAction(null); setConclusionBudgetError(""); }}>取消</button><button className="mini-button active" disabled={constraintAction.action === "mark_not_applicable" && !constraintActionReason.trim()} onClick={() => void actOnConstraint(constraint, constraintAction.action)}>确认</button></div></div> : null}{invalidatingConstraintId === constraint.id ? <div className="constraint-conclusion"><strong>使已有结论失效</strong><textarea className="textarea" rows={2} value={invalidationReason} onChange={(event) => setInvalidationReason(event.target.value)} placeholder="失效原因（必填）" /><div className="work-item-actions"><button className="mini-button" onClick={() => setInvalidatingConstraintId(null)}>取消</button><button className="mini-button danger" disabled={!invalidationReason.trim()} onClick={() => void actOnConstraint(constraint, "invalidate")}>确认失效</button></div></div> : null}</article>) : <div className="empty-state">尚无外部约束。</div>}</div>
            </section>

            <section className="detail-section detail-contracts">
              <div className="section-title"><div><p className="section-kicker">CONTRACTS</p><h2>合同 <small>({project.contract_summary?.count ?? 0} 份)</small></h2></div></div>
              <ContractPanel projectId={project.id} contextProject={project} operator="PMO办公室" allowCreate={project.stage === "项目库—推进中"} defaultReadOnly={project.stage === "已完成"} onChanged={async () => { await refreshDetailProjection(); }} />
            </section>

            <section className="detail-section detail-overview">
              <div className="section-title">
                <div><p className="section-kicker">PROJECT OVERVIEW</p><h2>项目概况</h2></div>
                <div className="work-item-actions"><button className="mini-button" onClick={() => { setEditingProject((value) => !value); setProjectEditErrors({}); setError(""); }}>编辑基本信息</button><button className="mini-button danger" onClick={() => setDeleteProjectOpen(true)}>移除项目</button></div>
              </div>
              {editingProject ? <div className="detail-add-item project-edit-form">
                <label className="field"><span>项目名称 <b aria-hidden="true">*</b></span><input ref={projectNameRef} className={`input ${projectEditErrors.name ? "input-error" : ""}`} value={project.name} onChange={(event) => { setProject({ ...project, name: event.target.value }); setProjectEditErrors((errors) => ({ ...errors, name: undefined })); }} aria-invalid={Boolean(projectEditErrors.name)} aria-describedby={projectEditErrors.name ? "project-name-error" : undefined} /></label>
                {projectEditErrors.name ? <small id="project-name-error" className="field-error">{projectEditErrors.name}</small> : null}
                <div className="field-grid"><input className="input" value={project.department ?? ""} onChange={(event) => setProject({ ...project, department: event.target.value })} placeholder="部门/学院" /><input className="input" value={project.major ?? ""} onChange={(event) => setProject({ ...project, major: event.target.value })} placeholder="所属专业" /></div><div className="field-grid"><input className="input" value={project.project_manager ?? ""} onChange={(event) => setProject({ ...project, project_manager: event.target.value })} placeholder="项目负责人" />{project.project_type === "laboratory" ? <input className="input" value={project.location ?? ""} onChange={(event) => setProject({ ...project, location: event.target.value })} placeholder="地点" /> : null}</div><label className="field"><span>项目分类</span><select className="select" value={project.project_type ?? ""} onChange={(event) => setProject({ ...project, project_type: event.target.value, procurement_nature: "", location: event.target.value === "laboratory" ? project.location : "" })}>{projectTypes.some((item) => item.code === project.project_type) ? null : <option value={project.project_type ?? ""}>{detailProjectTypeLabel(project.project_type)}</option>}{projectTypes.map((item) => <option key={item.id} value={item.code}>{item.name}</option>)}</select></label>{project.project_type === "software" ? <label className="field"><span>采购属性</span><select className="select" value={project.procurement_nature ?? ""} onChange={(event) => setProject({ ...project, procurement_nature: event.target.value as Project["procurement_nature"] })}><option value="">未设置</option><option value="goods">货物</option><option value="service">服务</option><option value="mixed">混合</option></select></label> : null}<label className="field"><span>初始预算（仅导入/录入纠错）</span><input className="input" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={project.budget ?? ""} onChange={(event) => setProject({ ...project, budget: event.target.value === "" ? null : event.target.value })} /></label>{project.stage === "已完成" ? <label className="field"><span>项目完成时间</span><input className="input" value={project.actual_end_date ?? ""} onChange={(event) => setProject({ ...project, actual_end_date: event.target.value })} placeholder="YYYY、YYYY-MM 或 YYYY-MM-DD" /></label> : null}<textarea className="textarea" rows={2} value={project.description ?? ""} onChange={(event) => setProject({ ...project, description: event.target.value })} placeholder="项目说明" />
                <label className="field"><span>修改理由 <b aria-hidden="true">*</b></span><textarea ref={projectReasonRef} className={`textarea ${projectEditErrors.reason ? "input-error" : ""}`} rows={2} value={projectReason} onChange={(event) => { setProjectReason(event.target.value); setProjectEditErrors((errors) => ({ ...errors, reason: undefined })); }} aria-invalid={Boolean(projectEditErrors.reason)} aria-describedby={projectEditErrors.reason ? "project-reason-error" : undefined} /></label>
                {projectEditErrors.reason ? <small id="project-reason-error" className="field-error">{projectEditErrors.reason}</small> : null}
                <button className="action-button primary" onClick={() => void saveProjectEdits()}>保存</button>
              </div> : null}
              <div className="detail-grid">
                <DetailField label="项目名称" value={project.name} />
                <DetailField label="项目编号" value={project.project_code} />
                <DetailField label="Stage" value={project.stage} />
                <DetailField label="立项文件号" value={project.establishment_document_no || "—"} />
                <DetailField label="申报部门" value={project.department} />
                <DetailField label="项目负责人" value={project.project_manager} />
                <DetailField label="项目分类" value={detailProjectTypeLabel(project.project_type)} />
                <DetailField label="地点" value={project.location || "未设置"} />
                <DetailField label="采购属性" value={procurementNatureLabel(project.procurement_nature)} />
                <DetailField label="初始预算" value={project.budget == null ? "未记录" : `${formatCurrency(project.budget)} 万`} />
                <DetailField label="当前有效预算" value={project.effective_budget == null ? "未记录" : `${formatCurrency(project.effective_budget)} 万`} />
                <DetailField label="预算来源" value={project.effective_budget_source === "budget_constraint" ? "预算核定结果" : project.effective_budget_source === "historical_review" ? "历史审核预算" : project.effective_budget_source === "initial_budget" ? "初始预算" : "未记录"} />
                <DetailField label="推进状态" value={project.advancement?.status === "special_active" ? "特批推进中" : project.advancement?.status === "active" ? "推进中" : project.advancement?.status === "completed" ? "已完成" : "未纳入推进"} />
                <DetailField label="计划推进年份" value={project.planned_advancement_year ? `${project.planned_advancement_year} 年${project.planned_advancement_status === "draft" ? " · 草案中" : ""}` : "未纳入年度计划"} />
                {project.stage === "已完成" ? <><DetailField label="实施年份" value={project.implementation_year?.toString() || "待补录"} /><DetailField label="项目完成时间" value={project.actual_end_date || "未记录"} /></> : null}
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

            <ProjectFundingPanel project={project} onChanged={refreshDetailProjection} />

            <details className="full-audit-log detail-audit-log"><summary>查看完整操作记录</summary><div className="audit-timeline">{auditEvents.map((event) => <article key={event.id}><strong>{event.event_type}</strong><span>{formatDateTime(event.created_at)} · {event.operator}{event.reason ? ` · ${event.reason}` : ""}</span></article>)}</div></details>
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
              <span>最新动态</span>
              <strong>{formatDateTime(project.latest_activity_at)}</strong>
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
