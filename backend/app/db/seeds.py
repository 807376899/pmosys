from __future__ import annotations

import sqlite3

from lib.workflow import DEFAULT_STATUSES, DEFAULT_TRANSITIONS


def seed_statuses(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM status_definitions").fetchone()[0]
    if count:
        return
    for status in DEFAULT_STATUSES:
        conn.execute(
            """
            INSERT INTO status_definitions (
                status_code, status_name, description, entry_condition, exit_condition,
                responsible_role, key_deliverable, is_terminal, sort_order, color, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                status["status_code"],
                status["status_name"],
                status["description"],
                status["entry_condition"],
                status["exit_condition"],
                status["responsible_role"],
                status["key_deliverable"],
                int(status["is_terminal"]),
                status["sort_order"],
                status["color"],
            ),
        )


def seed_transitions(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM transition_rules").fetchone()[0]
    if count:
        return
    for rule in DEFAULT_TRANSITIONS:
        conn.execute(
            """
            INSERT INTO transition_rules (
                from_status, to_status, action_name, requires_approval,
                approver_role, required_deliverable, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                rule["from_status"],
                rule["to_status"],
                rule["action_name"],
                int(rule["requires_approval"]),
                rule["approver_role"],
                rule["required_deliverable"],
            ),
        )

