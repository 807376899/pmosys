from __future__ import annotations

import sqlite3

from backend.app.db.seeds import seed_statuses, seed_transitions


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def init_database(conn: sqlite3.Connection) -> None:
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


def create_indexes(conn: sqlite3.Connection) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(current_status)",
        "CREATE INDEX IF NOT EXISTS idx_projects_department ON projects(department)",
        "CREATE INDEX IF NOT EXISTS idx_projects_manager ON projects(project_manager)",
        "CREATE INDEX IF NOT EXISTS idx_projects_type ON projects(project_type)",
        "CREATE INDEX IF NOT EXISTS idx_projects_status_updated ON projects(status_updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_history_project ON status_history(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_transition_from ON transition_rules(from_status)",
    ]
    for sql in statements:
        conn.execute(sql)
