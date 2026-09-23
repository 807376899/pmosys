export type GroupKey =
  | "pre_establish"
  | "pool_pending"
  | "pool_active"
  | "completed"
  | "abandoned";

export interface DashboardGroup {
  key: GroupKey;
  label: string;
  statuses: string[];
  count: number;
  total_budget: number;
  total_approved_budget: number;
  total_contract_amount: number;
}

export interface StatusStat {
  status_code: string;
  status_name: string;
  color: string;
  is_terminal: number;
  project_count: number;
}

export interface DashboardSummary {
  total_projects: number;
  total_budget: number;
  total_approved_budget: number;
  total_contract_amount: number;
  project_library_count: number;
  project_library_total_budget: number;
  project_library_total_effective_budget: number;
  review_in_progress_count: number;
  reviewed_count: number;
  reviewed_total_approved_budget: number;
  external_conditions_ready_count: number;
  external_conditions_ready_effective_budget: number;
  external_conditions_ongoing_count: number;
  external_conditions_ongoing_effective_budget: number;
  status_stats: StatusStat[];
}

export interface Project {
  id: number;
  project_code: string;
  name: string;
  description: string | null;
  department: string | null;
  sponsor: string | null;
  project_manager: string | null;
  current_status?: string | null;
  category: string | null;
  project_type: string | null;
  major?: string | null;
  location?: string | null;
  procurement_nature?: "goods" | "service" | "mixed" | "" | null;
  project_summary_display?: string | null;
  establishment_document_no?: string | null;
  budget: number | null;
  approved_budget: number | null;
  contract_amount: number | null;
  special_note: string | null;
  actual_start_date: string | null;
  actual_end_date: string | null;
  created_at: string | null;
  updated_at: string | null;
  status_updated_at: string | null;
  latest_activity_at?: string | null;
  deleted_at?: string | null;
  deleted_reason?: string | null;
  stage?: string | null;
  work_item_summary?: WorkItemSummary[];
  work_item_count?: number;
  active_work_item_count?: number;
  work_item_states?: Record<string, string>;
  work_item_column_states?: WorkItemColumnState[];
  advancement?: { year: number | null; date: string | null; view: string; status?: "active" | "special_active" | "completed" | "none" } | null;
  implementation_year?: number | null;
  planned_advancement_year?: number | null;
  planned_advancement_status?: "draft" | "confirmed" | null;
  has_completed_advancement_cycle?: boolean;
  external_constraints_cleared?: "true" | "false" | "unknown" | null;
  external_constraint_count?: number;
  external_constraint_open_count?: number;
  external_constraint_states?: ExternalConstraintState[];
  effective_budget?: number | null;
  effective_budget_source?: "budget_constraint" | "historical_review" | "initial_budget" | "unrecorded" | null;
  formal_allocation_total?: number | null;
  funding_allocations?: FundingAllocation[];
  contract_summary?: ContractSummary;
  contracts?: Contract[];
  stage_events?: StageTrackingEvent[];
}

export interface ContractProjectRef {
  id: number;
  project_code: string;
  name: string;
  department?: string;
  allocated_amount?: number | null;
}

export interface ContractProgressLog {
  id: number;
  contract_id: number;
  content: string;
  operator: string;
  created_at: string;
  updated_at: string;
}

export interface ContractAcceptanceRecord {
  id: number;
  contract_id: number;
  acceptance_status: "accepting" | "needs_rectification" | "accepted";
  acceptance_date: string;
  result: string;
  note: string;
  operator: string;
  created_at: string;
}

export interface ContractSummary {
  count: number;
  label: string;
  performing_count: number;
  pending_acceptance_count: number;
  contracts: Array<Pick<Contract, "id" | "contract_no" | "name" | "status">>;
}

export interface Contract {
  id: number;
  name: string;
  contract_no: string | null;
  supplier: string;
  total_amount: number | null;
  signed_on: string | null;
  planned_completion_on: string | null;
  note: string;
  status: "not_started" | "performing" | "completed" | "terminated" | "paused";
  acceptance_status: "not_accepted" | "accepting" | "needs_rectification" | "accepted";
  allocation_complete?: boolean;
  allocation_total?: number;
  allocation_difference?: number | null;
  projects: ContractProjectRef[];
  latest_progress?: ContractProgressLog | null;
  progress_logs?: ContractProgressLog[];
  acceptance_records?: ContractAcceptanceRecord[];
}

export interface FundingArrangement {
  id: number;
  planning_year: number;
  name: string;
  estimated_amount: number;
  fund_code: string;
  note: string;
}

export interface FundingSource {
  id: number;
  fund_code: string;
  fund_name?: string;
  fund_manager?: string;
  reference_amount: number | null;
  valid_from_year: number;
  valid_until_year: number;
  scope_note: string;
  note: string;
  allocated_total: number;
  project_count: number;
}

export interface FundingAllocation {
  id: number;
  project_id: number;
  funding_source_id: number;
  allocated_amount: number | null;
  allocation_amount_recorded?: boolean;
  fund_code: string;
  reference_amount?: number | null;
  valid_from_year?: number;
  valid_until_year?: number;
}

export interface FundingOverview {
  year: number;
  arrangements: FundingArrangement[];
  estimated_total: number;
  advancing_effective_budget_total: number;
  difference: number;
  over_expected: boolean;
  advancing_project_count: number;
  advancing_projects: Project[];
  sources: FundingSource[];
}

export interface AdvancementDraftMember {
  id: number;
  project_id: number;
  project_code: string;
  name: string;
  stage: string;
  advancement: Project["advancement"];
  effective_budget: number | null;
  member_status: "draft" | "confirmed";
  next_action: "include" | "special" | "already_active" | "already_special" | "terminal";
  added_at: string;
  confirmed_at: string | null;
}

export interface AdvancementDraft {
  id?: number;
  year: number;
  members: AdvancementDraftMember[];
  member_count: number;
  draft_count: number;
  confirmed_count: number;
  effective_budget_total: number;
  estimated_total: number;
  difference: number;
  over_expected: boolean;
  arrangements: FundingArrangement[];
}

export interface AnnualBudgetPlanMember {
  id?: number | null;
  project_id: number;
  project_code: string;
  name: string;
  department: string;
  project_type: string;
  stage: string;
  effective_budget: number | null;
  plan_kind: "carryover" | "new_confirmed" | "candidate" | "untracked_current_year";
  selected: boolean;
  member_status?: "draft" | "confirmed" | "removed" | null;
  planned_new_amount: number | null;
  default_planned_new_amount: number;
  next_action: string;
  confirmed_at?: string | null;
  can_select: boolean;
  can_cancel: boolean;
  counts_toward_stats: boolean;
  planned_amount_is_manual: boolean;
}

export interface AnnualBudgetPlan {
  id?: number | null;
  year: number;
  members: AnnualBudgetPlanMember[];
  planned_project_count: number;
  carryover_count: number;
  draft_count: number;
  confirmed_count: number;
  planned_new_amount_total: number;
  estimated_total: number;
  difference: number;
  over_expected: boolean;
  category_stats: Record<string, { count: number; planned_new_amount: number }>;
  arrangements: FundingArrangement[];
}

export interface FundingImportPreview {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  records: Array<Record<string, unknown>>;
  errors: Array<{ row_number: number; code: string; message: string; name?: string }>;
}

export interface ProjectListResponse {
  items: Project[];
  total: number;
  page: number;
  page_size: number;
  filter_options?: {
    departments?: string[];
    project_types?: string[];
    implementation_years?: string[];
  };
}

export interface WorkflowStatus {
  id: number;
  status_code: string;
  status_name: string;
  color: string;
}

export interface StatusHistoryItem {
  id: number;
  project_id: number;
  from_status: string | null;
  to_status: string;
  action: string;
  operator: string;
  approver: string | null;
  comment: string | null;
  deliverable: string | null;
  transition_date: string;
  from_status_name: string | null;
  to_status_name: string | null;
}

export interface WorkItem {
  id: number;
  project_id: number;
  name: string;
  status: string;
  track_as_key_node: boolean | number;
  completion_record_json: Record<string, unknown> | null;
  assignee: string;
  planned_date: string;
  note: string;
  completion_rule_snapshot: { effects?: CompletionEffects };
  content: string;
  stage_view_priority?: number | null;
  cancelled_at: string | null;
  cancelled_reason: string;
  skipped_at: string | null;
  skipped_reason: string;
  started_on?: string | null;
  last_progress_at?: string | null;
  latest_progress_summary?: string | null;
  first_activity_at?: string | null;
}

export interface StageTrackingEvent {
  id: number;
  kind: "established" | "completed" | "abandoned";
  label: string;
  occurred_at: string;
  operator: string;
  comment: string;
}

export interface CompletionEffects {
  create_milestone?: boolean;
  require_result?: boolean;
  result_type?: "free_text" | "pass_fail" | "custom";
  result_options?: string[];
  milestone_name?: string;
  require_business_record?: boolean;
}

export interface WorkItemSummary {
  id: number;
  name: string;
  status: string;
  planned_date: string;
  track_as_key_node: boolean;
  last_progress_at?: string | null;
  last_activity_at?: string | null;
  batch_summaries?: WorkItemBatchSummary[];
}

export interface WorkItemBatchSummary {
  id: number;
  name: string;
  scheduled_on?: string;
}

export interface WorkItemBatchMember {
  id: number;
  project_id: number;
  work_item_id: number;
  project_name: string;
  project_code: string;
  member_status: string;
  work_item_status: string;
  completion_record?: { result?: string; completed_on?: string; note?: string };
  follow_up_action?: string;
}

export interface WorkItemBatch {
  id: number;
  name: string;
  work_item_name: string;
  scheduled_on?: string;
  note?: string;
  status: "open" | "closed" | "voided";
  members: WorkItemBatchMember[];
  member_count: number;
  open_member_count: number;
}

export interface WorkItemColumnState {
  id: number;
  source_template_id?: number | null;
  name: string;
  status: string;
  planned_date?: string;
  cancelled_at?: string | null;
  skipped_at?: string | null;
  actionable: boolean;
  started_on?: string | null;
  completed_on?: string | null;
  completion_result?: string;
    completion_note?: string;
    track_as_key_node?: boolean;
    batch_summaries?: WorkItemBatchSummary[];
}

export interface WorkItemTemplate {
  id: number;
  name: string;
  default_content?: string;
  recommended_stage: string;
  stage_view_priority?: number | null;
  archived_at?: string | null;
  archived_by?: string;
  archived_reason?: string;
}

export interface WorkPackage {
  id: number;
  name: string;
  items: WorkItemDraft[];
  constraints?: Array<{ template_id?: number; name?: string }>;
  archived_at?: string | null;
}

export interface ExternalConstraintTemplate {
  id: number;
  name: string;
  recommended_stage: string;
  impact_scope?: "none" | "effective_budget" | "other";
  impact_note?: string;
  scope_kind?: "all" | "project_type";
  scope_value?: string;
  effective_from?: string;
  effective_until?: string;
  applicability_basis?: string;
  archived_at?: string | null;
}

export interface ProjectCategory {
  id: number;
  name: string;
  sort_order: number | null;
  is_active: boolean | number;
}

export interface ProjectTypeDefinition {
  id: number;
  code: string;
  name: string;
  code_prefix: string;
  is_active: boolean | number;
  sort_order: number | null;
}

export interface DepartmentSetting {
  department: string;
  sort_order: number | null;
}

export interface ProjectExternalConstraint {
  id: number;
  name: string;
  impact_scope?: "none" | "effective_budget" | "other";
  impact_note?: string;
  handling_status: string;
  clearance_status: string;
  outcome_json: Record<string, unknown>;
  template_snapshot_json?: { impact_scope?: "none" | "effective_budget" | "other"; impact_note?: string; outcome_schema_json?: { kind?: string } };
  evidence_note: string;
  concluded_at?: string | null;
  handling_started_on?: string | null;
  cleared_at?: string | null;
  invalidated_at?: string | null;
  is_effective_budget_source?: boolean | number;
  recent_progress_logs?: ExternalConstraintProgressLog[];
  latest_progress_summary?: string;
}

export interface ExternalConstraintState {
  id: number;
  template_id?: number | null;
  name: string;
  outcome_kind?: string;
  impact_scope?: "none" | "effective_budget" | "other";
  impact_note?: string;
  handling_status: string;
  clearance_status: string;
  latest_progress_summary?: string;
  latest_progress_at?: string | null;
  handling_started_on?: string | null;
  concluded_at?: string | null;
  cleared_at?: string | null;
  invalidated_at?: string | null;
  outcome_summary?: string;
}

export interface ExternalConstraintProgressLog {
  id: number;
  project_external_constraint_id: number;
  content: string;
  operator: string;
  created_at: string;
  updated_at?: string;
  updated_by?: string;
}

export interface StageColumn {
  kind: "work_item" | "external_constraint";
  key: string;
  label: string;
}

export interface WorkItemDraft {
  name: string;
  content?: string;
  status?: string;
  assignee?: string;
  planned_date?: string;
  track_as_key_node?: boolean;
  note?: string;
  completion_effects?: CompletionEffects;
  insert_after_id?: number | null;
  insert_mode?: "after_current" | "last";
  save_as_common?: boolean;
}

export interface WorkItemProgressLog {
  id: number;
  project_work_item_id: number;
  content: string;
  operator: string;
  is_timeline_highlight: number;
  created_at: string;
}

export interface Milestone {
  id: number;
  title: string;
  occurred_on: string;
  result: string;
  note: string;
  is_void: boolean | number;
}

export interface ManagementTimelineEvent {
  id: string;
  summary: string;
  created_at: string;
  operator: string;
  kind: string;
}

export interface AuditEvent {
  id: number;
  project_id: number;
  event_type: string;
  operator: string;
  reason: string;
  payload_json: string;
  created_at: string;
}

export interface BatchTarget {
  to_status: string;
  status_name: string;
  requires_approval: boolean;
  approver_roles: string[];
  action_names: string[];
}

export interface BatchConflict {
  project_id: number;
  project_code: string;
  name: string;
  code: string;
  message: string;
}

export interface BatchPreviewResponse {
  total: number;
  project_ids: number[];
  available_targets: BatchTarget[];
  requested_target: BatchTarget | null;
  requires_approval: boolean;
  approved_budget_allowed: boolean;
  conflicts: BatchConflict[];
}

export interface BatchExecuteResponse {
  total: number;
  success: number;
  failed: number;
  errors: Array<BatchConflict>;
}

export interface ImportPreviewRecord {
  row_number: number;
  project_code: string;
  name: string;
  description: string;
  department: string;
  sponsor: string;
  project_manager: string;
  current_status: string;
  category: string;
  project_type: "teaching_software" | "practical_teaching_site";
  budget: number;
  approved_budget: number | null;
  contract_amount: number | null;
  special_note: string;
  actual_start_date: string;
  actual_end_date: string;
}

export interface ImportPreviewError {
  row_number: number;
  code: string;
  message: string;
  name?: string | null;
}

export interface ImportPreviewResponse {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  records: ImportPreviewRecord[];
  errors: ImportPreviewError[];
}

export interface ImportCommitResponse {
  total: number;
  success: number;
  failed: number;
  errors: Array<{
    row_number: number;
    name: string;
    code: string;
    message: string;
  }>;
}
