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
  budget: number | null;
  approved_budget: number | null;
  contract_amount: number | null;
  special_note: string | null;
  actual_start_date: string | null;
  actual_end_date: string | null;
  created_at: string | null;
  updated_at: string | null;
  status_updated_at: string | null;
  stage?: string | null;
  work_item_summary?: WorkItemSummary[];
  work_item_count?: number;
  work_item_states?: Record<string, string>;
  next_key_node?: WorkItemSummary | null;
  advancement?: { year: number | null; date: string | null; view: string; status?: "active" | "special_active" | "none" } | null;
  external_constraints_cleared?: "true" | "false" | "unknown" | null;
  external_constraint_count?: number;
  external_constraint_open_count?: number;
  effective_budget?: number | null;
  effective_budget_source?: "budget_constraint" | "historical_review" | "initial_budget" | null;
}

export interface ProjectListResponse {
  items: Project[];
  total: number;
  page: number;
  page_size: number;
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
  execution_mode: string;
  assignee: string;
  planned_date: string;
  priority: string;
  note: string;
  completion_rule_snapshot: { effects?: CompletionEffects };
  content: string;
  flow_group: "main" | "independent";
  sequence_rank: number;
  stage_view_priority?: number | null;
  cancelled_at: string | null;
  cancelled_reason: string;
  skipped_at: string | null;
  skipped_reason: string;
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
}

export interface WorkItemTemplate {
  id: number;
  name: string;
  recommended_stage: string;
  execution_mode: string;
  completion_rule_json: string;
  flow_group: "main" | "independent";
  sequence_rank: number;
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
  is_blocking: boolean | number;
  outcome_schema_json: Record<string, unknown>;
  project_field_effects_json: Record<string, unknown>;
  scope_kind?: "all" | "year" | "project_type" | "manual";
  scope_value?: string;
  archived_at?: string | null;
}

export interface ProjectCategory {
  id: number;
  name: string;
  sort_order: number | null;
  is_active: boolean | number;
}

export interface DepartmentSetting {
  department: string;
  sort_order: number | null;
}

export interface ProjectExternalConstraint {
  id: number;
  name: string;
  is_blocking: boolean | number;
  handling_status: string;
  clearance_status: string;
  outcome_json: Record<string, unknown>;
  evidence_note: string;
  concluded_at?: string | null;
}

export interface WorkItemDraft {
  name: string;
  content?: string;
  status?: string;
  execution_mode?: string;
  assignee?: string;
  planned_date?: string;
  priority?: string;
  track_as_key_node?: boolean;
  note?: string;
  completion_effects?: CompletionEffects;
  flow_group?: "main" | "independent";
  sequence_rank?: number;
  insert_after_id?: number | null;
}

export interface WorkItemProgressLog {
  id: number;
  project_work_item_id: number;
  content: string;
  operator: string;
  is_timeline_highlight: number;
  created_at: string;
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
