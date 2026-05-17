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
  current_status: string;
  category: string | null;
  project_type: "teaching_software" | "practical_teaching_site" | null;
  budget: number | null;
  approved_budget: number | null;
  special_note: string | null;
  actual_start_date: string | null;
  actual_end_date: string | null;
  created_at: string | null;
  updated_at: string | null;
  status_updated_at: string | null;
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
