from __future__ import annotations

import sqlite3

from backend.app.db.seeds import seed_statuses, seed_transitions


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


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
    ]:
        if not column_exists(conn, "project_work_items", column):
            conn.execute(f"ALTER TABLE project_work_items ADD COLUMN {column} {definition}")
    for name, rank in {
        "学院流程": 100, "学院内部流程": 100, "PMO 审核": 200,
        "小组评审": 300, "校外专家评审": 300, "实验室建设与管理委员会": 400,
        "校长办公会": 500, "党委会": 600, "立项发文": 700,
    }.items():
        conn.execute("UPDATE project_work_items SET flow_group='main',sequence_rank=? WHERE name=? AND (flow_group IS NULL OR flow_group='independent')", (rank, name))
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
        ("flow_group", "TEXT DEFAULT 'independent'"),
        ("sequence_rank", "INTEGER DEFAULT 1000"),
        ("stage_view_priority", "INTEGER"),
        ("archived_at", "TEXT"),
        ("archived_by", "TEXT DEFAULT ''"),
        ("archived_reason", "TEXT DEFAULT ''"),
    ]:
        if not column_exists(conn, "work_item_templates", column):
            conn.execute(f"ALTER TABLE work_item_templates ADD COLUMN {column} {definition}")
    for name, stage, rank in [
        ("学院流程", "未立项", 1), ("PMO 审核", "未立项", 2),
        ("专家评审", "未立项", 3), ("委员会", "未立项", 4), ("会议", "未立项", 5),
        ("预算审核", "项目库—推进中", 1), ("采购需求", "项目库—推进中", 2),
        ("采购申请", "项目库—推进中", 3), ("招标", "项目库—推进中", 4),
        ("实施", "项目库—推进中", 5), ("验收", "项目库—推进中", 6),
    ]:
        conn.execute(
            """INSERT OR IGNORE INTO work_item_templates
            (name,recommended_stage,execution_mode,completion_rule_json,is_common,flow_group,sequence_rank,stage_view_priority)
            VALUES (?,?, 'tracking','{}',1,'main',?,?)""",
            (name, stage, rank * 100, rank),
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_advancement_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        advancement_year INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
        included_at TEXT NOT NULL, included_reason TEXT NOT NULL, included_by TEXT NOT NULL,
        ended_at TEXT, ended_reason TEXT DEFAULT '', ended_by TEXT DEFAULT ''
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
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            status_updated_at TEXT DEFAULT (datetime('now','localtime'))
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
    for column, definition in [("archived_at", "TEXT"), ("archived_by", "TEXT DEFAULT ''"), ("archived_reason", "TEXT DEFAULT ''"), ("scope_kind", "TEXT DEFAULT 'manual'"), ("scope_value", "TEXT DEFAULT ''")]:
        if not column_exists(conn, "external_constraint_templates", column):
            conn.execute(f"ALTER TABLE external_constraint_templates ADD COLUMN {column} {definition}")
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
            clearance_status TEXT DEFAULT 'unresolved',
            outcome_json TEXT DEFAULT '{}',
            evidence_note TEXT DEFAULT '',
            concluded_at TEXT,
            concluded_by TEXT DEFAULT '',
            invalidated_at TEXT,
            invalidated_by TEXT DEFAULT '',
            invalidated_reason TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
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
    create_indexes(conn)
    seed_statuses(conn)
    seed_transitions(conn)


def ensure_project_schema(conn: sqlite3.Connection) -> None:
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
    if not column_exists(conn, "projects", "project_type"):
        conn.execute("ALTER TABLE projects ADD COLUMN project_type TEXT")
    if not column_exists(conn, "projects", "contract_amount"):
        conn.execute("ALTER TABLE projects ADD COLUMN contract_amount REAL DEFAULT NULL")
    for column, definition in [
        ("major", "TEXT DEFAULT ''"),
        ("location", "TEXT DEFAULT ''"),
        ("establishment_document_no", "TEXT DEFAULT ''"),
        ("workflow_version_id", "INTEGER DEFAULT 1"),
        ("library_implementation_view", "TEXT DEFAULT 'unimplemented'"),
        ("advancement_year", "INTEGER"),
        ("advancement_date", "TEXT"),
        ("special_advancement_active", "INTEGER DEFAULT 0"),
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
        "CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(category)",
        "CREATE INDEX IF NOT EXISTS idx_history_project ON status_history(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_transition_from ON transition_rules(from_status)",
        "CREATE INDEX IF NOT EXISTS idx_external_constraints_project ON project_external_constraints(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_constraint_scope_project ON project_external_constraint_scope_confirmations(project_id)",
    ]
    for sql in statements:
        conn.execute(sql)
