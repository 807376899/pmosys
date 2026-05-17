from __future__ import annotations

import sqlite3


def fetch_all_statuses(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM status_definitions WHERE is_active = 1 ORDER BY sort_order"
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_all_transition_rules(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT tr.*, sd.status_name AS to_status_name
        FROM transition_rules tr
        LEFT JOIN status_definitions sd ON sd.status_code = tr.to_status
        WHERE tr.is_active = 1
        ORDER BY tr.from_status, tr.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_allowed_transitions(conn: sqlite3.Connection, from_status: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT tr.*, sd.status_name AS to_status_name
        FROM transition_rules tr
        LEFT JOIN status_definitions sd ON sd.status_code = tr.to_status
        WHERE tr.from_status = ? AND tr.is_active = 1
        ORDER BY sd.sort_order, tr.id
        """,
        (from_status,),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_status_stats(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT sd.status_code, sd.status_name, sd.color, sd.is_terminal,
               COUNT(p.id) AS project_count
        FROM status_definitions sd
        LEFT JOIN projects p ON p.current_status = sd.status_code
        WHERE sd.is_active = 1
        GROUP BY sd.status_code
        ORDER BY sd.sort_order
        """
    ).fetchall()
    return [dict(row) for row in rows]

