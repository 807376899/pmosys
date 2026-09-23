from __future__ import annotations

import json
import sqlite3
from datetime import date

from backend.app.db.seeds import seed_statuses, seed_transitions


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


_LEGACY_WORK_ITEM_TEMPLATE_NAMES = (
    "学院流程", "学院内部流程", "PMO 审核", "专家评审", "委员会", "会议", "预算审核", "采购需求",
    "采购申请", "招标", "实施", "验收",
)


def retire_system_presets(conn: sqlite3.Connection) -> None:
    """Remove unreferenced legacy seeds and archive referenced ones."""
    now = "datetime('now','localtime')"
    for name in _LEGACY_WORK_ITEM_TEMPLATE_NAMES:
        row = conn.execute("SELECT id FROM work_item_templates WHERE name=?", (name,)).fetchone()
        if not row:
            continue
        template_id = row["id"]
        referenced = conn.execute(
            "SELECT 1 FROM project_work_items WHERE source_template_id=? LIMIT 1", (template_id,)
        ).fetchone() or conn.execute(
            "SELECT 1 FROM work_package_items WHERE item_json LIKE ? LIMIT 1", (f"%{name}%",)
        ).fetchone()
        if referenced:
            conn.execute(
                f"UPDATE work_item_templates SET is_common=0,stage_view_priority=NULL,archived_at=COALESCE(archived_at,{now}),archived_by='系统迁移',archived_reason='取消系统预置' WHERE id=?",
                (template_id,),
            )
        else:
            conn.execute("DELETE FROM work_item_templates WHERE id=?", (template_id,))

    row = conn.execute("SELECT id FROM external_constraint_templates WHERE name='预算审核'").fetchone()
    if row:
        template_id = row["id"]
        referenced = conn.execute(
            "SELECT 1 FROM project_external_constraints WHERE template_id=? LIMIT 1", (template_id,)
        ).fetchone() or conn.execute(
            "SELECT 1 FROM work_packages WHERE constraints_json LIKE ? LIMIT 1", ("%预算审核%",)
        ).fetchone()
        if referenced:
            conn.execute(
                f"UPDATE external_constraint_templates SET is_common=0,archived_at=COALESCE(archived_at,{now}),archived_by='系统迁移',archived_reason='取消系统预置' WHERE id=?",
                (template_id,),
            )
        else:
            conn.execute("DELETE FROM external_constraint_templates WHERE id=?", (template_id,))

    conn.execute(
        f"UPDATE work_packages SET archived_at=COALESCE(archived_at,{now}),archived_by='系统迁移',archived_reason='取消系统预置' WHERE name='未立项 PMO 工作包'"
    )


def unify_work_item_order(conn: sqlite3.Connection) -> None:
    """Flatten legacy flow groups without discarding the order users already saw."""
    status_rank = {"in_progress": 1, "paused": 2, "not_started": 3}
    priority_rank = {"high": 1, "normal": 2, "low": 3}
    today = date.today().isoformat()
    project_ids = [row["project_id"] for row in conn.execute("SELECT DISTINCT project_id FROM project_work_items").fetchall()]
    for project_id in project_ids:
        items = [dict(row) for row in conn.execute("SELECT * FROM project_work_items WHERE project_id=?", (project_id,)).fetchall()]

        def legacy_order(item: dict) -> tuple:
            if item.get("flow_group") == "main":
                return (0, int(item.get("sequence_rank") or 1000), item["id"])
            planned = item.get("planned_date") or ""
            overdue = bool(planned and planned < today and item.get("status") not in {"completed", "paused", "not_applicable"})
            return (
                1,
                -int(overdue),
                status_rank.get(item.get("status"), 9),
                -int(bool(item.get("track_as_key_node"))),
                planned or "9999-12-31",
                priority_rank.get(item.get("priority"), 2),
                item["id"],
            )

        for index, item in enumerate(sorted(items, key=legacy_order), start=1):
            conn.execute("UPDATE project_work_items SET flow_group='main', sequence_rank=? WHERE id=?", (index * 100, item["id"]))


def unify_work_package_items(conn: sqlite3.Connection) -> None:
    """Keep package order in sort_order; legacy group/rank fields are no longer public."""
    for row in conn.execute("SELECT id,item_json FROM work_package_items").fetchall():
        try:
            item = json.loads(row["item_json"])
        except json.JSONDecodeError:
            continue
        item.pop("flow_group", None)
        item.pop("sequence_rank", None)
        item.pop("priority", None)
        item.pop("execution_mode", None)
        item.pop("completion_effects", None)
        conn.execute("UPDATE work_package_items SET item_json=? WHERE id=?", (json.dumps(item, ensure_ascii=False), row["id"]))


def backfill_latest_activity(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE projects
        SET latest_activity_at=(
            SELECT MAX(activity_at) FROM (
                SELECT MAX(created_at) AS activity_at FROM audit_events
                WHERE project_id=projects.id AND event_type IN (
                    'WORK_ITEM_UPDATED','WORK_ITEM_CANCELLED','WORK_ITEM_SKIPPED','WORK_ITEM_COMPLETED',
                    'WORK_ITEM_COMPLETION_CORRECTED','WORK_ITEM_REOPENED','WORK_ITEM_PROGRESS_RECORDED',
                    'WORK_ITEM_PROGRESS_UPDATED','WORK_ITEM_PROGRESS_DELETED','EXTERNAL_CONSTRAINT_BEGIN',
                    'EXTERNAL_CONSTRAINT_NEEDS_SUPPLEMENT','EXTERNAL_CONSTRAINT_CONCLUDE','EXTERNAL_CONSTRAINT_CLEAR',
                    'EXTERNAL_CONSTRAINT_MARK_NOT_APPLICABLE','EXTERNAL_CONSTRAINT_INVALIDATE',
                    'EXTERNAL_CONSTRAINT_SET_EFFECTIVE_BUDGET_SOURCE','EXTERNAL_CONSTRAINT_PROGRESS_RECORDED',
                    'EXTERNAL_CONSTRAINT_PROGRESS_UPDATED','EXTERNAL_CONSTRAINT_PROGRESS_DELETED'
                )
                UNION ALL
                SELECT MAX(log.created_at) FROM work_item_progress_logs log
                JOIN project_work_items wi ON wi.id=log.project_work_item_id WHERE wi.project_id=projects.id
                UNION ALL
                SELECT MAX(log.updated_at) FROM external_constraint_progress_logs log
                JOIN project_external_constraints ec ON ec.id=log.project_external_constraint_id WHERE ec.project_id=projects.id
            )
        )
        WHERE latest_activity_at IS NULL OR latest_activity_at=''
        """
    )


def init_database(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_work_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'not_started', track_as_key_node INTEGER DEFAULT 0,
            completion_rule_snapshot TEXT DEFAULT '{}', completion_record_json TEXT, created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    for column, definition in [
        ("execution_mode", "TEXT DEFAULT 'tracking'"),
        ("assignee", "TEXT DEFAULT ''"),
        ("planned_date", "TEXT DEFAULT ''"),
        ("priority", "TEXT DEFAULT 'normal'"),
        ("note", "TEXT DEFAULT ''"),
        ("source_template_id", "INTEGER"),
        ("content", "TEXT DEFAULT ''"),
        ("flow_group", "TEXT DEFAULT 'independent'"),
        ("sequence_rank", "INTEGER DEFAULT 1000"),
        ("cancelled_at", "TEXT"),
        ("cancelled_reason", "TEXT DEFAULT ''"),
        ("cancelled_by", "TEXT DEFAULT ''"),
        ("skipped_at", "TEXT"),
        ("skipped_reason", "TEXT DEFAULT ''"),
        ("started_on", "TEXT"),
    ]:
        if not column_exists(conn, "project_work_items", column):
            conn.execute(f"ALTER TABLE project_work_items ADD COLUMN {column} {definition}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_item_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            recommended_stage TEXT DEFAULT '', execution_mode TEXT DEFAULT 'tracking',
            completion_rule_json TEXT DEFAULT '{}', is_common INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    for column, definition in [
        ("default_content", "TEXT DEFAULT ''"),
        ("flow_group", "TEXT DEFAULT 'independent'"),
        ("sequence_rank", "INTEGER DEFAULT 1000"),
        ("stage_view_priority", "INTEGER"),
        ("archived_at", "TEXT"),
        ("archived_by", "TEXT DEFAULT ''"),
        ("archived_reason", "TEXT DEFAULT ''"),
    ]:
        if not column_exists(conn, "work_item_templates", column):
            conn.execute(f"ALTER TABLE work_item_templates ADD COLUMN {column} {definition}")
    conn.execute("UPDATE work_item_templates SET is_common=0, stage_view_priority=NULL WHERE name IN ('学院流程','学院内部流程')")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    unify_work_item_order(conn)
    if not column_exists(conn, "work_packages", "constraints_json"):
        conn.execute("ALTER TABLE work_packages ADD COLUMN constraints_json TEXT DEFAULT '[]'")
    for column, definition in [("archived_at", "TEXT"), ("archived_by", "TEXT DEFAULT ''"), ("archived_reason", "TEXT DEFAULT ''")]:
        if not column_exists(conn, "work_packages", column):
            conn.execute(f"ALTER TABLE work_packages ADD COLUMN {column} {definition}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_package_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, package_id INTEGER NOT NULL REFERENCES work_packages(id) ON DELETE CASCADE,
            item_json TEXT NOT NULL, sort_order INTEGER DEFAULT 0
        )
        """
    )
    unify_work_package_items(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_item_progress_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_work_item_id INTEGER NOT NULL REFERENCES project_work_items(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            operator TEXT NOT NULL,
            is_timeline_highlight INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    for column, definition in [("deleted_at", "TEXT"), ("deleted_by", "TEXT DEFAULT ''"), ("deleted_reason", "TEXT DEFAULT ''")]:
        if not column_exists(conn, "work_item_progress_logs", column):
            conn.execute(f"ALTER TABLE work_item_progress_logs ADD COLUMN {column} {definition}")
    conn.execute("CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, event_type TEXT NOT NULL, operator TEXT NOT NULL, reason TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', created_at TEXT DEFAULT (datetime('now','localtime')))")
    legacy_waiting = conn.execute("SELECT id, project_id FROM project_work_items WHERE status='waiting_external'").fetchall()
    for item in legacy_waiting:
        conn.execute("UPDATE project_work_items SET status='in_progress' WHERE id=?", (item["id"],))
        conn.execute("INSERT INTO audit_events (project_id,event_type,operator,payload_json) VALUES (?,?,?,?)", (item["project_id"], "WORK_ITEM_STATUS_MIGRATED", "系统迁移", json.dumps({"work_item_id": item["id"], "from": "waiting_external", "to": "in_progress"}, ensure_ascii=False)))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_advancement_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        advancement_year INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
        included_at TEXT NOT NULL, included_reason TEXT NOT NULL, included_by TEXT NOT NULL,
        ended_at TEXT, ended_reason TEXT DEFAULT '', ended_by TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS annual_funding_arrangements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        planning_year INTEGER NOT NULL,
        name TEXT NOT NULL,
        estimated_amount REAL NOT NULL,
        fund_code TEXT DEFAULT '',
        note TEXT DEFAULT '',
        created_by TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_by TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS funding_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fund_code TEXT UNIQUE NOT NULL,
        fund_name TEXT DEFAULT '',
        fund_manager TEXT DEFAULT '',
        reference_amount REAL,
        valid_from_year INTEGER NOT NULL,
        valid_until_year INTEGER NOT NULL,
        scope_note TEXT DEFAULT '',
        note TEXT DEFAULT '',
        created_by TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_by TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_funding_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        funding_source_id INTEGER NOT NULL REFERENCES funding_sources(id) ON DELETE RESTRICT,
        allocated_amount REAL NOT NULL,
        allocation_amount_recorded INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_by TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(project_id, funding_source_id)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS funding_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_id INTEGER,
        event_type TEXT NOT NULL,
        operator TEXT NOT NULL,
        reason TEXT DEFAULT '',
        payload_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contracts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        contract_no TEXT UNIQUE,
        supplier TEXT DEFAULT '',
        total_amount REAL,
        signed_on TEXT,
        planned_completion_on TEXT,
        note TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'not_started',
        acceptance_status TEXT NOT NULL DEFAULT 'not_accepted',
        created_by TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_by TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contract_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE RESTRICT,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        linked_by TEXT NOT NULL,
        linked_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(contract_id, project_id)
        )"""
    )
    if not column_exists(conn, "contract_projects", "allocated_amount"):
        conn.execute("ALTER TABLE contract_projects ADD COLUMN allocated_amount REAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contract_progress_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE RESTRICT,
        content TEXT NOT NULL,
        operator TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        updated_by TEXT DEFAULT '',
        deleted_at TEXT,
        deleted_by TEXT DEFAULT '',
        deleted_reason TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contract_acceptance_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE RESTRICT,
        acceptance_status TEXT NOT NULL,
        acceptance_date TEXT NOT NULL,
        result TEXT DEFAULT '',
        note TEXT DEFAULT '',
        operator TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contract_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE RESTRICT,
        event_type TEXT NOT NULL,
        operator TEXT NOT NULL,
        reason TEXT DEFAULT '',
        payload_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contract_projects_project ON contract_projects(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contract_progress_contract ON contract_progress_logs(contract_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contract_acceptance_contract ON contract_acceptance_records(contract_id)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS annual_advancement_drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        advancement_year INTEGER NOT NULL UNIQUE,
        created_by TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS annual_advancement_draft_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draft_id INTEGER NOT NULL REFERENCES annual_advancement_drafts(id) ON DELETE CASCADE,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        member_status TEXT NOT NULL DEFAULT 'draft',
        added_by TEXT NOT NULL,
        added_at TEXT DEFAULT (datetime('now','localtime')),
        confirmed_by TEXT DEFAULT '',
        confirmed_at TEXT,
        removed_by TEXT DEFAULT '',
        removed_at TEXT,
        removal_reason TEXT DEFAULT '',
        planned_new_amount REAL NOT NULL DEFAULT 0,
        planned_amount_is_manual INTEGER NOT NULL DEFAULT 0,
        member_kind TEXT NOT NULL DEFAULT 'new',
        UNIQUE(draft_id, project_id)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS annual_advancement_draft_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draft_id INTEGER NOT NULL REFERENCES annual_advancement_drafts(id) ON DELETE CASCADE,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        event_type TEXT NOT NULL,
        operator TEXT NOT NULL,
        reason TEXT DEFAULT '',
        payload_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    # Governance dictionaries are deliberately separate from the historical
    # project_type field. Categories drive PMO ordering/reporting; types remain
    # project business attributes and import compatibility data.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        is_active INTEGER DEFAULT 1,
        sort_order INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS department_settings (
        department TEXT PRIMARY KEY,
        sort_order INTEGER,
        updated_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_early_preparations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        preparation_year INTEGER NOT NULL, reason TEXT NOT NULL, approval_basis TEXT NOT NULL,
        operator TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            code_prefix TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    if not column_exists(conn, "project_types", "sort_order"):
        conn.execute("ALTER TABLE project_types ADD COLUMN sort_order INTEGER")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            department TEXT,
            sponsor TEXT,
            project_manager TEXT,
            current_status TEXT NOT NULL DEFAULT 'draft',
            category TEXT,
            project_type TEXT,
            budget REAL DEFAULT 0,
            approved_budget REAL DEFAULT NULL,
            contract_amount REAL DEFAULT NULL,
            special_note TEXT DEFAULT '',
            actual_start_date TEXT,
            actual_end_date TEXT,
            procurement_nature TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            status_updated_at TEXT DEFAULT (datetime('now','localtime')),
            latest_activity_at TEXT DEFAULT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            from_status TEXT,
            to_status TEXT NOT NULL,
            action TEXT NOT NULL,
            operator TEXT NOT NULL,
            approver TEXT,
            comment TEXT,
            deliverable TEXT,
            transition_date TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS status_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status_code TEXT UNIQUE NOT NULL,
            status_name TEXT NOT NULL,
            description TEXT,
            entry_condition TEXT,
            exit_condition TEXT,
            responsible_role TEXT,
            key_deliverable TEXT,
            is_terminal INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            color TEXT DEFAULT '#6B7280',
            is_active INTEGER DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transition_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            action_name TEXT NOT NULL,
            requires_approval INTEGER DEFAULT 0,
            approver_role TEXT,
            required_deliverable TEXT,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    ensure_project_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS external_constraint_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            recommended_stage TEXT DEFAULT '',
            is_blocking INTEGER DEFAULT 1,
            outcome_schema_json TEXT DEFAULT '{}',
            project_field_effects_json TEXT DEFAULT '{}',
            is_common INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    for column, definition in [
        ("archived_at", "TEXT"), ("archived_by", "TEXT DEFAULT ''"), ("archived_reason", "TEXT DEFAULT ''"),
        ("scope_kind", "TEXT DEFAULT 'manual'"), ("scope_value", "TEXT DEFAULT ''"),
        ("effective_from", "TEXT DEFAULT ''"), ("effective_until", "TEXT DEFAULT ''"),
        ("applicability_basis", "TEXT DEFAULT ''"),
        ("impact_scope", "TEXT DEFAULT 'none'"), ("impact_note", "TEXT DEFAULT ''"),
    ]:
        if not column_exists(conn, "external_constraint_templates", column):
            conn.execute(f"ALTER TABLE external_constraint_templates ADD COLUMN {column} {definition}")
    conn.execute(
        "UPDATE external_constraint_templates SET scope_kind='all' WHERE scope_kind='manual'"
    )
    # Preserve the meaning of legacy budget-review templates after introducing
    # the explicit impact scope.  New templates no longer read this legacy JSON.
    conn.execute(
        "UPDATE external_constraint_templates SET impact_scope='effective_budget' "
        "WHERE impact_scope='none' AND project_field_effects_json LIKE '%\"effective_budget\"%'"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_external_constraints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            template_id INTEGER REFERENCES external_constraint_templates(id),
            name TEXT NOT NULL,
            template_snapshot_json TEXT DEFAULT '{}',
            is_blocking INTEGER DEFAULT 1,
            primary_work_item_id INTEGER REFERENCES project_work_items(id),
            handling_status TEXT DEFAULT 'not_started',
            handling_started_on TEXT,
            clearance_status TEXT DEFAULT 'unresolved',
            outcome_json TEXT DEFAULT '{}',
            evidence_note TEXT DEFAULT '',
            concluded_at TEXT,
            concluded_by TEXT DEFAULT '',
            invalidated_at TEXT,
            invalidated_by TEXT DEFAULT '',
            invalidated_reason TEXT DEFAULT '',
            is_effective_budget_source INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    if not column_exists(conn, "project_external_constraints", "is_effective_budget_source"):
        conn.execute("ALTER TABLE project_external_constraints ADD COLUMN is_effective_budget_source INTEGER DEFAULT 0")
    for column, definition in [
        ("cleared_at", "TEXT"), ("cleared_by", "TEXT DEFAULT ''"), ("clearance_reason", "TEXT DEFAULT ''"),
        ("handling_started_on", "TEXT"),
        ("impact_scope", "TEXT DEFAULT 'none'"), ("impact_note", "TEXT DEFAULT ''"),
    ]:
        if not column_exists(conn, "project_external_constraints", column):
            conn.execute(f"ALTER TABLE project_external_constraints ADD COLUMN {column} {definition}")
    conn.execute(
        "UPDATE project_external_constraints SET impact_scope='effective_budget' "
        "WHERE impact_scope='none' AND (is_effective_budget_source=1 "
        "OR template_snapshot_json LIKE '%\"effective_budget\"%')"
    )
    # The old intermediate label represented process detail.  Preserve audit
    # history but use the compact Phase 2 handling-state vocabulary at runtime.
    conn.execute("UPDATE project_external_constraints SET handling_status='in_progress' WHERE handling_status='needs_supplement'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS external_constraint_progress_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_external_constraint_id INTEGER NOT NULL REFERENCES project_external_constraints(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            operator TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            updated_by TEXT DEFAULT '',
            deleted_at TEXT,
            deleted_by TEXT DEFAULT '',
            deleted_reason TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS external_constraint_batch_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            operator TEXT NOT NULL,
            reason TEXT DEFAULT '',
            payload_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_item_bulk_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            operator TEXT NOT NULL,
            payload_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_item_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, work_item_name TEXT NOT NULL,
            scheduled_on TEXT DEFAULT '', note TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'not_started',
            created_by TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_by TEXT DEFAULT '', updated_at TEXT DEFAULT (datetime('now','localtime')),
            ended_at TEXT, ended_by TEXT DEFAULT '', voided_at TEXT, voided_by TEXT DEFAULT '', voided_reason TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_item_activity_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id INTEGER NOT NULL REFERENCES work_item_activities(id) ON DELETE CASCADE,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            work_item_id INTEGER NOT NULL REFERENCES project_work_items(id) ON DELETE CASCADE,
            member_status TEXT NOT NULL DEFAULT 'active', outcome_status TEXT NOT NULL DEFAULT 'unrecorded',
            outcome_json TEXT DEFAULT '{}', outcome_recorded_at TEXT, outcome_recorded_by TEXT DEFAULT '',
            follow_up_action TEXT DEFAULT '', follow_up_note TEXT DEFAULT '', processed_at TEXT, processed_by TEXT DEFAULT '',
            added_by TEXT NOT NULL, added_at TEXT DEFAULT (datetime('now','localtime')),
            removed_at TEXT, removed_by TEXT DEFAULT '', removed_reason TEXT DEFAULT '', UNIQUE(activity_id, work_item_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_item_activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id INTEGER NOT NULL REFERENCES work_item_activities(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL, operator TEXT NOT NULL, payload_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_item_activity_progress_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id INTEGER NOT NULL REFERENCES work_item_activities(id) ON DELETE CASCADE,
            content TEXT NOT NULL, operator TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')), updated_by TEXT DEFAULT '',
            deleted_at TEXT, deleted_by TEXT DEFAULT '', deleted_reason TEXT DEFAULT ''
        )
        """
    )
    # Direct migration: legacy Batch records are retained as activities, then
    # the old tables are removed so no compatibility surface remains.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_item_batches'").fetchone():
        conn.execute(
            """INSERT OR IGNORE INTO work_item_activities
               (id,name,work_item_name,scheduled_on,note,status,created_by,created_at,updated_by,updated_at,voided_at,voided_by,voided_reason)
               SELECT b.id,b.name,b.work_item_name,b.scheduled_on,b.note,
                 CASE b.status WHEN 'closed' THEN 'ended' WHEN 'voided' THEN 'voided'
                   WHEN 'open' THEN CASE WHEN EXISTS (SELECT 1 FROM work_item_batch_members m WHERE m.batch_id=b.id AND (m.member_status<>'scheduled' OR COALESCE(m.processed_at,'')<>'')) THEN 'in_progress' ELSE 'not_started' END
                   ELSE 'not_started' END,
                 b.created_by,b.created_at,b.updated_by,b.updated_at,b.voided_at,b.voided_by,b.voided_reason
               FROM work_item_batches b"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO work_item_activity_members
               (id,activity_id,project_id,work_item_id,member_status,outcome_status,outcome_json,outcome_recorded_at,outcome_recorded_by,follow_up_action,follow_up_note,processed_at,processed_by,added_by,added_at,removed_at,removed_by,removed_reason)
               SELECT m.id,m.batch_id,m.project_id,m.work_item_id,
                 CASE WHEN m.member_status='removed' THEN 'removed' WHEN m.member_status='released' THEN 'released' ELSE 'active' END,
                 CASE WHEN m.member_status IN ('completed','external_completed') OR COALESCE(m.completion_record_json,'{}')<>'{}' THEN 'recorded' ELSE 'unrecorded' END,
                 m.completion_record_json,m.processed_at,m.processed_by,m.follow_up_action,m.follow_up_note,m.processed_at,m.processed_by,m.added_by,m.added_at,m.removed_at,m.removed_by,m.removed_reason
               FROM work_item_batch_members m"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO work_item_activity_events (id,activity_id,event_type,operator,payload_json,created_at)
               SELECT id,batch_id,REPLACE(event_type,'BATCH','ACTIVITY'),operator,payload_json,created_at FROM work_item_batch_events"""
        )
        conn.execute("DROP TABLE work_item_batch_events")
        conn.execute("DROP TABLE work_item_batch_members")
        conn.execute("DROP TABLE work_item_batches")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_item_batch_operations'").fetchone() and not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_item_bulk_operations'").fetchone():
        conn.execute("ALTER TABLE work_item_batch_operations RENAME TO work_item_bulk_operations")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_external_constraint_scope_confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            confirmed_at TEXT NOT NULL,
            confirmed_by TEXT NOT NULL,
            note TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_work_item_id INTEGER REFERENCES project_work_items(id),
            title TEXT NOT NULL,
            occurred_on TEXT NOT NULL,
            result TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_by TEXT NOT NULL,
            is_void INTEGER DEFAULT 0,
            voided_at TEXT,
            voided_by TEXT DEFAULT '',
            voided_reason TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute("INSERT OR IGNORE INTO project_types (code, name, code_prefix) VALUES ('software', '专业教学软件项目', 'SW')")
    conn.execute("INSERT OR IGNORE INTO project_types (code, name, code_prefix) VALUES ('laboratory', '实践教学场所项目', 'SY')")
    conn.execute("UPDATE project_types SET sort_order=1 WHERE code='software' AND sort_order IS NULL")
    conn.execute("UPDATE project_types SET sort_order=2 WHERE code='laboratory' AND sort_order IS NULL")
    conn.execute("UPDATE projects SET project_type='software' WHERE project_type='teaching_software'")
    conn.execute("UPDATE projects SET project_type='laboratory' WHERE project_type='practical_teaching_site'")
    retire_system_presets(conn)
    backfill_latest_activity(conn)
    create_indexes(conn)
    seed_statuses(conn)
    seed_transitions(conn)


def ensure_project_schema(conn: sqlite3.Connection) -> None:
    # Precision columns are intentionally additive: legacy REAL values remain
    # untouched and are only used as a read fallback for historical test data.
    for table, columns in {
        "projects": ("budget_decimal", "approved_budget_decimal", "contract_amount_decimal"),
        "annual_funding_arrangements": ("estimated_amount_decimal",),
        "funding_sources": ("reference_amount_decimal",),
        "project_funding_allocations": ("allocated_amount_decimal",),
        "annual_advancement_draft_members": ("planned_new_amount_decimal",),
        "contracts": ("total_amount_decimal",),
        "contract_projects": ("allocated_amount_decimal",),
    }.items():
        for column in columns:
            if not column_exists(conn, table, column):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
    for column, definition in [("fund_name", "TEXT DEFAULT ''"), ("fund_manager", "TEXT DEFAULT ''")]:
        if not column_exists(conn, "funding_sources", column):
            conn.execute(f"ALTER TABLE funding_sources ADD COLUMN {column} {definition}")
    if not column_exists(conn, "project_funding_allocations", "allocation_amount_recorded"):
        conn.execute("ALTER TABLE project_funding_allocations ADD COLUMN allocation_amount_recorded INTEGER NOT NULL DEFAULT 1")
    if not column_exists(conn, "annual_advancement_draft_members", "planned_new_amount"):
        conn.execute("ALTER TABLE annual_advancement_draft_members ADD COLUMN planned_new_amount REAL NOT NULL DEFAULT 0")
    if not column_exists(conn, "annual_advancement_draft_members", "member_kind"):
        conn.execute("ALTER TABLE annual_advancement_draft_members ADD COLUMN member_kind TEXT NOT NULL DEFAULT 'new'")
    if not column_exists(conn, "annual_advancement_draft_members", "planned_amount_is_manual"):
        conn.execute("ALTER TABLE annual_advancement_draft_members ADD COLUMN planned_amount_is_manual INTEGER NOT NULL DEFAULT 0")
    if not column_exists(conn, "projects", "approved_budget"):
        conn.execute("ALTER TABLE projects ADD COLUMN approved_budget REAL DEFAULT NULL")
    if not column_exists(conn, "projects", "special_note"):
        conn.execute("ALTER TABLE projects ADD COLUMN special_note TEXT DEFAULT ''")
    if not column_exists(conn, "projects", "status_updated_at"):
        conn.execute("ALTER TABLE projects ADD COLUMN status_updated_at TEXT DEFAULT ''")
        conn.execute(
            """
            UPDATE projects
            SET status_updated_at = COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''), datetime('now','localtime'))
            WHERE status_updated_at IS NULL OR status_updated_at = ''
            """
        )
    if not column_exists(conn, "projects", "latest_activity_at"):
        conn.execute("ALTER TABLE projects ADD COLUMN latest_activity_at TEXT DEFAULT NULL")
    if not column_exists(conn, "projects", "project_type"):
        conn.execute("ALTER TABLE projects ADD COLUMN project_type TEXT")
    if not column_exists(conn, "projects", "contract_amount"):
        conn.execute("ALTER TABLE projects ADD COLUMN contract_amount REAL DEFAULT NULL")
    for column, definition in [
        ("major", "TEXT DEFAULT ''"),
        ("location", "TEXT DEFAULT ''"),
        ("procurement_nature", "TEXT DEFAULT ''"),
        ("establishment_document_no", "TEXT DEFAULT ''"),
        ("workflow_version_id", "INTEGER DEFAULT 1"),
        ("library_implementation_view", "TEXT DEFAULT 'unimplemented'"),
        ("advancement_year", "INTEGER"),
        ("advancement_date", "TEXT"),
        ("special_advancement_active", "INTEGER DEFAULT 0"),
        ("deleted_at", "TEXT"),
        ("deleted_by", "TEXT DEFAULT ''"),
        ("deleted_reason", "TEXT DEFAULT ''"),
    ]:
        if not column_exists(conn, "projects", column):
            conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {definition}")


def create_indexes(conn: sqlite3.Connection) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(current_status)",
        "CREATE INDEX IF NOT EXISTS idx_projects_department ON projects(department)",
        "CREATE INDEX IF NOT EXISTS idx_projects_manager ON projects(project_manager)",
        "CREATE INDEX IF NOT EXISTS idx_projects_type ON projects(project_type)",
        "CREATE INDEX IF NOT EXISTS idx_projects_status_updated ON projects(status_updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_projects_latest_activity ON projects(latest_activity_at)",
        "CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(category)",
        "CREATE INDEX IF NOT EXISTS idx_history_project ON status_history(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_transition_from ON transition_rules(from_status)",
        "CREATE INDEX IF NOT EXISTS idx_external_constraints_project ON project_external_constraints(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_constraint_progress_constraint ON external_constraint_progress_logs(project_external_constraint_id)",
        "CREATE INDEX IF NOT EXISTS idx_constraint_scope_project ON project_external_constraint_scope_confirmations(project_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_constraint_effective_budget_source ON project_external_constraints(project_id) WHERE is_effective_budget_source=1",
        "CREATE INDEX IF NOT EXISTS idx_funding_arrangements_year ON annual_funding_arrangements(planning_year)",
        "CREATE INDEX IF NOT EXISTS idx_funding_sources_validity ON funding_sources(valid_from_year, valid_until_year)",
        "CREATE INDEX IF NOT EXISTS idx_project_funding_allocations_project ON project_funding_allocations(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_project_funding_allocations_source ON project_funding_allocations(funding_source_id)",
        "CREATE INDEX IF NOT EXISTS idx_advancement_draft_members_draft ON annual_advancement_draft_members(draft_id, member_status)",
        "CREATE INDEX IF NOT EXISTS idx_advancement_draft_events_draft ON annual_advancement_draft_events(draft_id)",
        "CREATE INDEX IF NOT EXISTS idx_work_item_activities_name ON work_item_activities(work_item_name, status, scheduled_on)",
        "CREATE INDEX IF NOT EXISTS idx_work_item_activity_members_activity ON work_item_activity_members(activity_id, member_status)",
        "CREATE INDEX IF NOT EXISTS idx_work_item_activity_members_item ON work_item_activity_members(work_item_id, member_status)",
    ]
    for sql in statements:
        conn.execute(sql)
