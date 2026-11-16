import { FileDown, FileUp, Plus, Save, Send } from "lucide-react";
import {
  ChangeEvent,
  Fragment,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  ApiError,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPostForm,
  apiPut,
} from "./lib/api";
import {
  compareMoney,
  formatCurrency,
  subtractMoney,
  sumMoney,
} from "./lib/format";
import { annualPlanCategoryLabel } from "./lib/annual-plan-display";
import type {
  AnnualBudgetPlan,
  AnnualBudgetPlanMember,
  FundingAllocation,
  FundingArrangement,
  FundingImportPreview,
  FundingSource,
  ProjectTypeDefinition,
} from "./types";

const currentYear = new Date().getFullYear();
const arrangementBlank = (year: number) => ({
  planning_year: year,
  name: "",
  estimated_amount: "",
  fund_code: "",
  note: "",
});
const sourceBlank = (year: number) => ({
  fund_code: "",
  reference_amount: "",
  valid_from_year: String(year),
  valid_until_year: String(year),
  scope_note: "",
  note: "",
});
const ANNUAL_COLUMN_WIDTHS_KEY = "pmo-annual-budget-table-widths-v1";
const annualColumnDefaults = {
  status: 190,
  project: 270,
  category: 190,
  department: 140,
  stage: 150,
  effectiveBudget: 135,
  plannedAmount: 160,
} as const;
type AnnualColumnKey = keyof typeof annualColumnDefaults;

function readAnnualColumnWidths(): Partial<Record<AnnualColumnKey, number>> {
  try {
    const raw = JSON.parse(localStorage.getItem(ANNUAL_COLUMN_WIDTHS_KEY) || "{}");
    return Object.fromEntries(
      Object.entries(raw && typeof raw === "object" ? raw : {})
        .filter(([key, value]) => key in annualColumnDefaults && typeof value === "number" && Number.isFinite(value) && value >= 96),
    ) as Partial<Record<AnnualColumnKey, number>>;
  } catch {
    return {};
  }
}
type View = "overview" | "stage";
type PendingNavigation =
  { kind: "year"; year: number } | { kind: "view"; view: View; group?: string };

type Props = {
  operator: string;
  projectTypes: ProjectTypeDefinition[];
  onFeedback: (message: string) => void;
  onError: (message: string) => void;
  onChanged: () => Promise<void>;
  onExit: (view: View, group?: string) => void;
  renderStageSlot: (onSelect: (group: string) => void) => ReactNode;
};

function amount(value: string | number | null | undefined) {
  return value == null ? "未记录" : `${formatCurrency(value)} 万`;
}
export default function AnnualBudgetView({
  operator,
  projectTypes,
  onFeedback,
  onError,
  onChanged,
  onExit,
  renderStageSlot,
}: Props) {
  const [year, setYear] = useState(currentYear);
  const [plan, setPlan] = useState<AnnualBudgetPlan | null>(null);
  const [draft, setDraft] = useState<
    Record<
      number,
      { selected: boolean; amount: string; amountIsManual: boolean }
    >
  >({});
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [arrangement, setArrangement] = useState(arrangementBlank(currentYear));
  const [editingArrangementId, setEditingArrangementId] = useState<
    number | null
  >(null);
  const [sources, setSources] = useState<FundingSource[]>([]);
  const [source, setSource] = useState(sourceBlank(currentYear));
  const [fundingOpen, setFundingOpen] = useState(false);
  const [importPreview, setImportPreview] =
    useState<FundingImportPreview | null>(null);
  const [activeSource, setActiveSource] = useState<FundingSource | null>(null);
  const [sourceAllocations, setSourceAllocations] = useState<
    Record<number, string>
  >({});
  const [pendingNavigation, setPendingNavigation] =
    useState<PendingNavigation | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [specialEntries, setSpecialEntries] = useState<
    Record<number, { reason: string; approval_basis: string }>
  >({});
  const [cancelMember, setCancelMember] =
    useState<AnnualBudgetPlanMember | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [columnWidths, setColumnWidths] = useState(readAnnualColumnWidths);

  useEffect(() => {
    localStorage.setItem(ANNUAL_COLUMN_WIDTHS_KEY, JSON.stringify(columnWidths));
  }, [columnWidths]);

  function annualColumnWidth(key: AnnualColumnKey) {
    return columnWidths[key] ?? annualColumnDefaults[key];
  }

  function startColumnResize(key: AnnualColumnKey, event: ReactPointerEvent<HTMLSpanElement>) {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = annualColumnWidth(key);
    const onMove = (moveEvent: PointerEvent) => {
      setColumnWidths((current) => ({
        ...current,
        [key]: Math.max(96, Math.round(startWidth + moveEvent.clientX - startX)),
      }));
    };
    const onStop = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onStop);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onStop, { once: true });
  }

  function annualResizeHandle(key: AnnualColumnKey) {
    return <span className="column-resize-handle" role="separator" aria-label="拖动调整列宽" title="拖动调整列宽" onPointerDown={(event) => startColumnResize(key, event)} />;
  }

  async function load(nextYear = year) {
    setLoading(true);
    try {
      const [nextPlan, nextSources] = await Promise.all([
        apiGet<AnnualBudgetPlan>(`/projects/annual-budget-plans/${nextYear}`),
        apiGet<FundingSource[]>(
          "/funding/sources",
          new URLSearchParams({ year: String(nextYear) }),
        ),
      ]);
      setPlan(nextPlan);
      setSources(nextSources);
      setDraft(
        Object.fromEntries(
          nextPlan.members.map((member) => [
            member.project_id,
            {
              selected: member.selected,
              amount:
                member.planned_new_amount == null
                  ? String(member.default_planned_new_amount)
                  : String(member.planned_new_amount),
              amountIsManual: member.planned_amount_is_manual,
            },
          ]),
        ),
      );
      setArrangement(arrangementBlank(nextYear));
      setDirty(false);
    } catch (error) {
      onError(
        error instanceof ApiError ? error.message : "年度预算安排加载失败",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(year);
  }, [year]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const selectedMembers = useMemo(
    () =>
      (plan?.members ?? []).filter(
        (member) =>
          draft[member.project_id]?.selected ||
          ["carryover", "new_confirmed", "current_year_planned"].includes(member.plan_kind),
      ),
    [plan, draft],
  );
  const countedMembers = useMemo(
    () =>
      selectedMembers.filter(
        (member) => compareMoney(draft[member.project_id]?.amount, "0") > 0,
      ),
    [selectedMembers, draft],
  );
  const plannedTotal = useMemo(
    () =>
      sumMoney(
        selectedMembers.map((member) => draft[member.project_id]?.amount),
      ),
    [selectedMembers, draft],
  );
  const categoryStats = useMemo(
    () =>
      countedMembers.reduce<Record<string, { count: number; amount: string }>>(
        (all, member) => {
          const row = all[member.project_type] ?? { count: 0, amount: "0" };
          row.count += 1;
          row.amount = sumMoney([row.amount, draft[member.project_id]?.amount]);
          all[member.project_type] = row;
          return all;
        },
        {},
      ),
    [countedMembers, draft],
  );
  const draftMembers = useMemo(
    () => selectedMembers.filter((member) => member.member_status === "draft"),
    [selectedMembers],
  );
  const specialMembers = useMemo(
    () => draftMembers.filter((member) => member.next_action === "special"),
    [draftMembers],
  );

  function editMember(
    member: AnnualBudgetPlanMember,
    patch: Partial<{
      selected: boolean;
      amount: string;
      amountIsManual: boolean;
    }>,
  ) {
    if (!member.can_select && patch.selected !== undefined) return;
    setDraft((current) => ({
      ...current,
      [member.project_id]: {
        ...current[member.project_id],
        ...patch,
        amountIsManual:
          patch.amount !== undefined && patch.selected === undefined
            ? true
            : (patch.amountIsManual ??
              current[member.project_id]?.amountIsManual ??
              false),
      },
    }));
    setDirty(true);
  }
  function toggleMember(member: AnnualBudgetPlanMember) {
    if (!member.can_select) return;
    const state = draft[member.project_id];
    editMember(member, {
      selected: !state?.selected,
      amount:
        !state?.selected && !state?.amount
          ? String(member.default_planned_new_amount)
          : (state?.amount ?? ""),
      amountIsManual: state?.amountIsManual ?? false,
    });
  }
  async function savePlan(): Promise<boolean> {
    if (!plan) return false;
    const members = plan.members
      .filter(
        (member) =>
          draft[member.project_id]?.selected ||
          ["carryover", "new_confirmed", "current_year_planned"].includes(member.plan_kind),
      )
      .map((member) => ({
        project_id: member.project_id,
        planned_new_amount: draft[member.project_id]?.amount,
        planned_amount_is_manual: Boolean(
          draft[member.project_id]?.amountIsManual,
        ),
      }));
    if (
      members.some(
        (member) => !/^\d+(?:\.\d+)?$/.test(member.planned_new_amount || ""),
      )
    ) {
      onError("本年新增安排必须为非负十进制数字。");
      return false;
    }
    setSaving(true);
    try {
      const saved = await apiPut<AnnualBudgetPlan>(
        `/projects/annual-budget-plans/${year}`,
        { operator, members },
      );
      setPlan(saved);
      setDirty(false);
      onFeedback("年度计划草案已保存，可继续调整。");
      await onChanged();
      return true;
    } catch (error) {
      onError(
        error instanceof ApiError
          ? error.message
          : "年度计划未保存，已保留当前填写内容。",
      );
      return false;
    } finally {
      setSaving(false);
    }
  }
  function requestNavigation(next: PendingNavigation) {
    if (dirty) setPendingNavigation(next);
    else applyNavigation(next);
  }
  function applyNavigation(next: PendingNavigation) {
    if (next.kind === "year") setYear(next.year);
    else onExit(next.view, next.group);
  }
  async function saveAndLeave() {
    if ((await savePlan()) && pendingNavigation) {
      applyNavigation(pendingNavigation);
      setPendingNavigation(null);
    }
  }
  function discardAndLeave() {
    if (pendingNavigation) applyNavigation(pendingNavigation);
    setPendingNavigation(null);
  }

  async function saveArrangement() {
    if (!arrangement.name.trim() || !arrangement.estimated_amount) {
      onError("请填写资金安排名称和预计总额。");
      return;
    }
    try {
      if (editingArrangementId)
        await apiPatch(`/funding/arrangements/${editingArrangementId}`, {
          ...arrangement,
          operator,
        });
      else await apiPost("/funding/arrangements", { ...arrangement, operator });
      setEditingArrangementId(null);
      setArrangement(arrangementBlank(year));
      await load(year);
      onFeedback("年度资金安排已保存。");
    } catch (error) {
      onError(
        error instanceof ApiError ? error.message : "年度资金安排未保存。",
      );
    }
  }
  async function removeArrangement(item: FundingArrangement) {
    if (!window.confirm(`删除“${item.name}”？`)) return;
    try {
      await apiDelete(`/funding/arrangements/${item.id}`, {
        operator,
        reason: "年度资金安排调整",
      });
      await load(year);
    } catch (error) {
      onError(
        error instanceof ApiError ? error.message : "年度资金安排未删除。",
      );
    }
  }
  async function saveSource() {
    if (!source.fund_code.trim()) {
      onError("请填写资金号。");
      return;
    }
    try {
      await apiPost("/funding/sources", {
        ...source,
        reference_amount:
          source.reference_amount === "" ? null : source.reference_amount,
        valid_from_year: Number(source.valid_from_year),
        valid_until_year: Number(source.valid_until_year),
        operator,
      });
      setSource(sourceBlank(year));
      setSources(
        await apiGet<FundingSource[]>(
          "/funding/sources",
          new URLSearchParams({ year: String(year) }),
        ),
      );
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "正式资金号未保存。");
    }
  }
  async function selectSource(item: FundingSource) {
    setActiveSource(item);
    try {
      const details = await Promise.all(
        selectedMembers.map((member) =>
          apiGet<{ funding_allocations: FundingAllocation[] }>(
            `/projects/${member.project_id}/funding-allocations`,
          ),
        ),
      );
      setSourceAllocations(
        Object.fromEntries(
          selectedMembers.map((member, index) => [
            member.project_id,
            String(
              details[index].funding_allocations.find(
                (allocation) => allocation.funding_source_id === item.id,
              )?.allocated_amount ?? "",
            ),
          ]),
        ),
      );
    } catch (error) {
      onError(
        error instanceof ApiError ? error.message : "无法读取当前资金分配。",
      );
    }
  }
  async function saveSourceAllocations() {
    if (!activeSource) return;
    const allocations = selectedMembers
      .filter((member) => sourceAllocations[member.project_id] !== "")
      .map((member) => ({
        project_id: member.project_id,
        allocated_amount: sourceAllocations[member.project_id],
      }));
    if (
      !allocations.length ||
      allocations.some((item) => !/^\d+(?:\.\d+)?$/.test(item.allocated_amount))
    ) {
      onError("请至少填写一项非负十进制分配金额。");
      return;
    }
    try {
      const result = await apiPost<{
        processed_count: number;
        warnings: string[];
      }>(`/funding/sources/${activeSource.id}/allocations`, {
        operator,
        allocations,
      });
      onFeedback(
        result.warnings.length
          ? `已保存 ${result.processed_count} 项正式资金分配。提醒：${result.warnings.join("；")}`
          : `已保存 ${result.processed_count} 项正式资金分配。`,
      );
      await load(year);
      await onChanged();
    } catch (error) {
      onError(
        error instanceof ApiError ? error.message : "正式资金分配未保存。",
      );
    }
  }
  async function previewImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      setImportPreview(
        await apiPostForm<FundingImportPreview>(
          `/funding/allocations/import/preview?planning_year=${year}`,
          form,
        ),
      );
    } catch (error) {
      onError(
        error instanceof ApiError ? error.message : "正式资金分配预览失败。",
      );
    }
  }
  async function commitImport() {
    if (!importPreview?.records.length) return;
    try {
      const result = await apiPost<{
        success: number;
        failed: number;
        errors: Array<{ message: string }>;
      }>("/funding/allocations/import/commit", {
        records: importPreview.records,
        operator,
        planning_year: year,
        confirm_source_amount_updates: true,
      });
      if (result.failed) {
        onError(result.errors.map((item) => item.message).join("；"));
        return;
      }
      setImportPreview(null);
      await load(year);
      await onChanged();
      onFeedback(`正式资金分配已写入 ${result.success} 条。`);
    } catch (error) {
      onError(
        error instanceof ApiError ? error.message : "正式资金分配未写入。",
      );
    }
  }
  async function confirmPlan() {
    if (!plan?.draft_count) {
      onError("当前没有待确认的新增年度计划项目。");
      return;
    }
    const entries = specialMembers.map((member) => ({
      project_id: member.project_id,
      reason: specialEntries[member.project_id]?.reason?.trim() || "",
      approval_basis:
        specialEntries[member.project_id]?.approval_basis?.trim() || "",
    }));
    if (entries.some((entry) => !entry.reason || !entry.approval_basis)) {
      onError("请逐项填写特批理由和审批依据。");
      return;
    }
    try {
      await apiPost(`/projects/annual-budget-plans/${year}/confirm`, {
        operator,
        special_entries: entries,
      });
      setConfirmOpen(false);
      setSpecialEntries({});
      await load(year);
      await onChanged();
      onFeedback("年度计划已确认；新增项目已正式纳入推进，草案仍可继续调整。");
    } catch (error) {
      onError(
        error instanceof ApiError
          ? error.message
          : "年度计划确认失败；未写入任何正式推进记录。",
      );
    }
  }
  async function cancelConfirmedMember() {
    if (!cancelMember || !cancelReason.trim()) {
      onError("取消推进必须填写原因。");
      return;
    }
    try {
      await apiPost(`/projects/annual-budget-plans/${year}/exception-actions`, {
        action: "cancel",
        project_ids: [cancelMember.project_id],
        operator,
        reason: cancelReason.trim(),
      });
      setCancelMember(null);
      setCancelReason("");
      await load(year);
      await onChanged();
      onFeedback("项目已退回项目库—未实施，并从年度计划中移出。");
    } catch (error) {
      onError(
        error instanceof ApiError
          ? error.message
          : "退回项目库失败，项目保持原状态。",
      );
    }
  }

  const memberGroups = useMemo(() => {
    const members = plan?.members ?? [];
    return [
      [
        "续建项目",
        members.filter((member) => member.plan_kind === "carryover"),
      ],
      [
        "年度计划项目",
        members.filter(
          (member) =>
            member.plan_kind !== "carryover" && member.selected,
        ),
      ],
      [
        "可选项目",
        members.filter((member) => !member.selected),
      ],
    ] as Array<[string, AnnualBudgetPlanMember[]]>;
  }, [plan]);

  return (
    <>
      <section className="main-stage">
        {renderStageSlot((group) =>
          requestNavigation({ kind: "view", view: "overview", group }),
        )}
        <section className="board annual-budget-board">
          <div className="board-heading">
            <div>
              <p className="section-kicker">ANNUAL PLAN</p>
              <h2>年度预算安排</h2>
            </div>
            <label className="field annual-year">
              <span>规划年度</span>
              <select
                className="select"
                value={year}
                onChange={(event) =>
                  requestNavigation({
                    kind: "year",
                    year: Number(event.target.value),
                  })
                }
              >
                {[year - 1, year, year + 1].map((item) => (
                  <option value={item} key={item}>
                    {item} 年
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="table-meta">
            <span>
              保存草案不改变项目推进状态；确认纳入推进才写入正式推进记录。
            </span>
            <div className="table-tools">
              <button
                className="mini-button"
                onClick={() =>
                  requestNavigation({ kind: "view", view: "overview" })
                }
              >
                总览
              </button>
              <button
                className="mini-button"
                onClick={() =>
                  requestNavigation({ kind: "view", view: "stage" })
                }
              >
                阶段跟踪
              </button>
              <button
                className="mini-button active"
                disabled={!dirty || saving}
                onClick={() => void savePlan()}
              >
                <Save size={15} />
                保存年度计划草案
              </button>
              <button
                className="mini-button"
                type="button"
                onClick={() => setColumnWidths({})}
              >
                恢复默认列宽
              </button>
            </div>
          </div>
          <div className="project-table-wrap">
            {loading ? (
              <div className="loading-panel">正在载入年度计划</div>
            ) : (
              <table
                className="project-table annual-budget-table"
                style={{ minWidth: `${Object.values(annualColumnDefaults).reduce((total, _, index) => total + annualColumnWidth(Object.keys(annualColumnDefaults)[index] as AnnualColumnKey), 0)}px` }}
              >
                <colgroup>
                  {(Object.keys(annualColumnDefaults) as AnnualColumnKey[]).map((key) => <col key={key} style={{ width: annualColumnWidth(key) }} />)}
                </colgroup>
                <thead>
                  <tr>
                    <th className="resizable-column">计划状态 / 操作{annualResizeHandle("status")}</th>
                    <th className="resizable-column">项目{annualResizeHandle("project")}</th>
                    <th className="resizable-column">分类 / 采购类型{annualResizeHandle("category")}</th>
                    <th className="resizable-column">学院{annualResizeHandle("department")}</th>
                    <th className="resizable-column">Stage{annualResizeHandle("stage")}</th>
                    <th className="resizable-column">有效预算{annualResizeHandle("effectiveBudget")}</th>
                    <th className="resizable-column">本年新增安排{annualResizeHandle("plannedAmount")}</th>
                  </tr>
                </thead>
                <tbody>
                  {memberGroups.map(([label, members]) =>
                    members.length ? (
                      <Fragment key={label}>
                        <tr className="annual-plan-group">
                          <td colSpan={7}>{label}</td>
                        </tr>
                        {members.map((member) => {
                          const state = draft[member.project_id];
                          const selected = Boolean(state?.selected);
                          const disabledAmount =
                            !selected &&
                            ![
                              "carryover",
                              "new_confirmed",
                              "current_year_planned",
                            ].includes(
                              member.plan_kind,
                            );
                          return (
                            <tr
                              key={member.project_id}
                              className={`${member.can_select ? "annual-plan-row selectable" : "annual-plan-row"} ${selected ? "selected" : ""}`}
                              onClick={(event) => {
                                if (
                                  (event.target as HTMLElement).closest(
                                    "input,button,a,label",
                                  )
                                )
                                  return;
                                toggleMember(member);
                              }}
                            >
                              <td className="annual-plan-status-cell">
                                {member.plan_kind === "carryover" ? (
                                  <span className="plan-tag">续建</span>
                                ) : member.can_cancel ? (
                                  <div className="annual-plan-status">
                                    <span className="plan-tag">{member.plan_status}</span>
                                    <button
                                      type="button"
                                      className="text-button danger"
                                      onClick={() => setCancelMember(member)}
                                    >
                                      退回项目库
                                    </button>
                                  </div>
                                ) : selected ? (
                                  <span className="plan-tag">{member.plan_status}</span>
                                ) : member.can_select ? (
                                  <label className="check-pill">
                                    <input
                                      type="checkbox"
                                      checked={selected}
                                      onChange={() => toggleMember(member)}
                                    />
                                    <span />
                                    纳入计划
                                  </label>
                                ) : (
                                  <span className="plan-tag">{member.plan_status}</span>
                                )}
                              </td>
                              <td>
                                <div className="project-cell">
                                  <strong title={member.name}>
                                    {member.name}
                                  </strong>
                                  <span>{member.project_code}</span>
                                </div>
                              </td>
                              <td>{annualPlanCategoryLabel(member.project_type, member.procurement_nature)}</td>
                              <td>{member.department || "未录入"}</td>
                              <td>{member.stage}</td>
                              <td>{amount(member.effective_budget)}</td>
                              <td>
                                <input
                                  className="input amount-input"
                                  inputMode="decimal"
                                  disabled={disabledAmount}
                                  value={state?.amount ?? ""}
                                  onChange={(event) =>
                                    editMember(member, {
                                      amount: event.target.value,
                                    })
                                  }
                                />
                              </td>
                            </tr>
                          );
                        })}
                      </Fragment>
                    ) : null,
                  )}
                  {!plan?.members.length ? (
                    <tr>
                      <td colSpan={7} className="project-table-empty">
                        当前没有可纳入年度计划的项目
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </section>
      <aside className="control-rail annual-budget-rail">
        <div className="rail-card operation-console">
          <p className="section-kicker">ANNUAL BUDGET</p>
          <h3>{year} 年年度预算安排</h3>
          <div className="annual-summary">
            <strong>当前计划 {countedMembers.length} 个项目</strong>
            <span>本年新增安排 {formatCurrency(plannedTotal)} 万</span>
            <span>年度预计资金 {formatCurrency(plan?.estimated_total)} 万</span>
            <span>
              差额{" "}
              {formatCurrency(
                subtractMoney(plan?.estimated_total, plannedTotal),
              )}{" "}
              万
            </span>
            {plan?.over_expected ||
            compareMoney(plannedTotal, plan?.estimated_total) > 0 ? (
              <small className="notice error">
                本年新增安排已超出预计资金规模，仅作提示。
              </small>
            ) : null}
          </div>
          {["software", "laboratory"].map((code) => (
            <div className="annual-category-stat" key={code}>
              <span>{code === "software" ? "专业教学软件项目" : "实践教学场所项目"}</span>
              <strong>
                {categoryStats[code]?.count ?? 0} 个 ·{" "}
                {formatCurrency(categoryStats[code]?.amount ?? "0")} 万
              </strong>
            </div>
          ))}
          <details className="annual-arrangements">
            <summary>
              年度资金安排 · {plan?.arrangements.length ?? 0} 项 ·{" "}
              {formatCurrency(plan?.estimated_total)} 万
            </summary>
            {plan?.arrangements.map((item) => (
              <article key={item.id}>
                <strong>{item.name}</strong>
                <small>
                  {formatCurrency(item.estimated_amount)} 万{" "}
                  {item.fund_code ? `· ${item.fund_code}` : ""}
                </small>
                <div>
                  <button
                    className="text-button"
                    onClick={() => {
                      setEditingArrangementId(item.id);
                      setArrangement({
                        planning_year: year,
                        name: item.name,
                        estimated_amount: String(item.estimated_amount),
                        fund_code: item.fund_code || "",
                        note: item.note || "",
                      });
                    }}
                  >
                    编辑
                  </button>
                  <button
                    className="text-button danger"
                    onClick={() => void removeArrangement(item)}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
            <input
              className="input"
              value={arrangement.name}
              onChange={(event) =>
                setArrangement({ ...arrangement, name: event.target.value })
              }
              placeholder="资金安排名称"
            />
            <input
              className="input"
              inputMode="decimal"
              value={arrangement.estimated_amount}
              onChange={(event) =>
                setArrangement({
                  ...arrangement,
                  estimated_amount: event.target.value,
                })
              }
              placeholder="预计总额（万元）"
            />
            <input
              className="input"
              value={arrangement.fund_code}
              onChange={(event) =>
                setArrangement({
                  ...arrangement,
                  fund_code: event.target.value,
                })
              }
              placeholder="资金号（可选）"
            />
            <textarea
              className="textarea"
              rows={2}
              value={arrangement.note}
              onChange={(event) =>
                setArrangement({ ...arrangement, note: event.target.value })
              }
              placeholder="说明（可选）"
            />
            <button
              className="mini-button"
              onClick={() => void saveArrangement()}
            >
              {editingArrangementId ? "保存修改" : "新增资金安排"}
            </button>
          </details>
          <small>
            确认将处理 {plan?.draft_count ?? 0}{" "}
            个待确认项目；续建项目不会重复纳入推进。
          </small>
          <button
            className="action-button primary full"
            disabled={!plan?.draft_count}
            onClick={() => setConfirmOpen(true)}
          >
            <Send size={16} />
            确认年度计划
          </button>
          <details className="formal-funding">
            <summary>正式资金分配</summary>
            <a
              className="text-button"
              href={`/api/v1/funding/allocations/import/template?year=${year}`}
            >
              <FileDown size={15} />
              导出当前计划给财务
            </a>
            <label className="file-picker">
              <FileUp size={15} />
              导入财务回填
              <input
                type="file"
                accept=".xlsx,.xls"
                onChange={(event) => void previewImport(event)}
              />
            </label>
            {importPreview ? (
              <div className="operation-preview">
                <strong>
                  有效 {importPreview.valid_rows} 行，异常{" "}
                  {importPreview.invalid_rows} 行
                </strong>
                {importPreview.errors.map((error) => (
                  <small key={`${error.row_number}-${error.code}`}>
                    第 {error.row_number} 行：{error.message}
                  </small>
                ))}
                <button
                  className="mini-button active"
                  disabled={Boolean(importPreview.invalid_rows)}
                  onClick={() => void commitImport()}
                >
                  确认导入
                </button>
              </div>
            ) : null}
            <button
              className="text-button"
              onClick={() => setFundingOpen((open) => !open)}
            >
              {fundingOpen ? "收起资金号维护" : "维护正式资金号"}
            </button>
            {fundingOpen ? (
              <div className="formal-source-form">
                <div className="simple-list">
                  {sources.map((item) => (
                    <article key={item.id}>
                      <button
                        className={`text-button ${activeSource?.id === item.id ? "active" : ""}`}
                        onClick={() => void selectSource(item)}
                      >
                        <strong>{item.fund_code}</strong>
                        <span>
                          {amount(item.reference_amount)} · 已分配{" "}
                          {formatCurrency(item.allocated_total)} 万
                        </span>
                      </button>
                    </article>
                  ))}
                </div>
                <input
                  className="input"
                  value={source.fund_code}
                  onChange={(event) =>
                    setSource({ ...source, fund_code: event.target.value })
                  }
                  placeholder="资金号"
                />
                <input
                  className="input"
                  inputMode="decimal"
                  value={source.reference_amount}
                  onChange={(event) =>
                    setSource({
                      ...source,
                      reference_amount: event.target.value,
                    })
                  }
                  placeholder="参考金额（可选）"
                />
                <button
                  className="mini-button"
                  onClick={() => void saveSource()}
                >
                  <Plus size={15} />
                  新增资金号
                </button>
                {activeSource ? (
                  <section className="source-allocation-editor">
                    <strong>{activeSource.fund_code} 分配到当前年度计划</strong>
                    {selectedMembers.map((member) => (
                      <label key={member.project_id}>
                        <span>{member.name}</span>
                        <input
                          className="input"
                          inputMode="decimal"
                          value={sourceAllocations[member.project_id] ?? ""}
                          onChange={(event) =>
                            setSourceAllocations({
                              ...sourceAllocations,
                              [member.project_id]: event.target.value,
                            })
                          }
                          placeholder="分配金额（万元）"
                        />
                      </label>
                    ))}
                    <button
                      className="mini-button active"
                      onClick={() => void saveSourceAllocations()}
                    >
                      保存项目分配
                    </button>
                  </section>
                ) : null}
              </div>
            ) : null}
          </details>
        </div>
      </aside>
      {pendingNavigation ? (
        <div
          className="plan-leave-dialog"
          role="dialog"
          aria-modal="true"
          aria-label="未保存年度计划"
        >
          <div>
            <h3>年度计划尚未保存</h3>
            <p>可先保存当前草案，或放弃修改后继续切换。</p>
            <div className="dialog-actions">
              <button
                className="mini-button active"
                disabled={saving}
                onClick={() => void saveAndLeave()}
              >
                保存年度计划草案后退出
              </button>
              <button className="mini-button" onClick={discardAndLeave}>
                放弃修改后退出
              </button>
              <button
                className="text-button"
                onClick={() => setPendingNavigation(null)}
              >
                留在年度计划
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {confirmOpen ? (
        <div
          className="plan-leave-dialog"
          role="dialog"
          aria-modal="true"
          aria-label="确认纳入推进"
        >
          <div>
            <h3>确认年度计划</h3>
            <p>
              将正式纳入 {draftMembers.length} 个新增项目；本年新增安排{" "}
              {formatCurrency(plannedTotal)} 万，预计资金差额{" "}
              {formatCurrency(
                subtractMoney(plan?.estimated_total, plannedTotal),
              )}{" "}
              万。
            </p>
            {specialMembers.map((member) => (
              <section className="confirm-special" key={member.project_id}>
                <strong>{member.name} · 特批推进</strong>
                <input
                  className="input"
                  placeholder="特批理由"
                  value={specialEntries[member.project_id]?.reason ?? ""}
                  onChange={(event) =>
                    setSpecialEntries((current) => ({
                      ...current,
                      [member.project_id]: {
                        ...current[member.project_id],
                        reason: event.target.value,
                      },
                    }))
                  }
                />
                <input
                  className="input"
                  placeholder="审批依据"
                  value={
                    specialEntries[member.project_id]?.approval_basis ?? ""
                  }
                  onChange={(event) =>
                    setSpecialEntries((current) => ({
                      ...current,
                      [member.project_id]: {
                        ...current[member.project_id],
                        approval_basis: event.target.value,
                      },
                    }))
                  }
                />
              </section>
            ))}
            <div className="dialog-actions">
              <button
                className="mini-button active"
                onClick={() => void confirmPlan()}
              >
                确认纳入推进
              </button>
              <button
                className="text-button"
                onClick={() => setConfirmOpen(false)}
              >
                返回草案
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {cancelMember ? (
        <div
          className="plan-leave-dialog"
          role="dialog"
          aria-modal="true"
          aria-label="退回项目库"
        >
          <div>
            <h3>退回项目库</h3>
            <p>
              将撤回“{cancelMember.name}”本年度确认的推进，退回项目库—未实施并从年度计划中移出。
            </p>
            <label className="field">
              <span>调整原因</span>
              <textarea
                className="textarea"
                value={cancelReason}
                onChange={(event) => setCancelReason(event.target.value)}
                rows={3}
              />
            </label>
            <div className="dialog-actions">
              <button
                className="mini-button danger"
                onClick={() => void cancelConfirmedMember()}
              >
                确认退回项目库
              </button>
              <button
                className="text-button"
                onClick={() => setCancelMember(null)}
              >
                返回
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
