from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from backend.app.core.errors import NotFoundError, ValidationError
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo


_ACTIONABLE_STATUSES = {"not_started", "in_progress"}
_TERMINAL_STATUSES = {"completed", "not_applicable"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _event(conn: sqlite3.Connection, batch_id: int, event_type: str, operator: str, payload: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO work_item_batch_events (batch_id,event_type,operator,payload_json) VALUES (?,?,?,?)",
        (batch_id, event_type, operator, json.dumps(payload or {}, ensure_ascii=False)),
    )


def _audit_project_batch(conn: sqlite3.Connection, project_id: int, event_type: str, operator: str, payload: dict) -> None:
    # Import lazily because project projections also consume batch summaries.
    from backend.app.services.projects import _audit

    _audit(conn, project_id, event_type, operator, payload=payload)


def _member_row(conn: sqlite3.Connection, target: dict, work_item_name: str) -> tuple[dict, dict]:
    project_id = int(target.get("project_id") or 0)
    item_id = int(target.get("work_item_id") or 0)
    project = project_repo.fetch_project_by_id(conn, project_id)
    item = conn.execute(
        "SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)
    ).fetchone()
    if not project or not item:
        raise ValidationError("项目或事项实例不存在")
    item_data = dict(item)
    if item_data["name"] != work_item_name:
        raise ValidationError(f"{project['name']}：事项名称与批次不一致")
    if item_data.get("cancelled_at") or item_data.get("skipped_at") or item_data["status"] not in _ACTIONABLE_STATUSES:
        raise ValidationError(f"{project['name']}：事项当前不可参加批次")
    return project, item_data


def _refresh_batch_status(conn: sqlite3.Connection, batch_id: int) -> None:
    batch = conn.execute("SELECT status FROM work_item_batches WHERE id=?", (batch_id,)).fetchone()
    if not batch or batch["status"] != "open":
        return
    pending = conn.execute(
        """SELECT m.id,wi.status,wi.cancelled_at,wi.skipped_at
           FROM work_item_batch_members m
           JOIN project_work_items wi ON wi.id=m.work_item_id
           WHERE m.batch_id=? AND m.member_status='scheduled'""",
        (batch_id,),
    ).fetchall()
    for row in pending:
        if row["cancelled_at"] or row["skipped_at"] or row["status"] in _TERMINAL_STATUSES:
            conn.execute(
                "UPDATE work_item_batch_members SET member_status='external_completed' WHERE id=?",
                (row["id"],),
            )
    still_open = conn.execute(
        "SELECT 1 FROM work_item_batch_members WHERE batch_id=? AND member_status='scheduled' LIMIT 1",
        (batch_id,),
    ).fetchone()
    if not still_open:
        conn.execute("UPDATE work_item_batches SET status='closed',updated_at=? WHERE id=?", (_now(), batch_id))


def _serialize_batch(conn: sqlite3.Connection, batch_id: int) -> dict:
    _refresh_batch_status(conn, batch_id)
    row = conn.execute("SELECT * FROM work_item_batches WHERE id=?", (batch_id,)).fetchone()
    if not row:
        raise NotFoundError("批次不存在")
    batch = dict(row)
    members = [dict(member) for member in conn.execute(
        """SELECT m.*,p.project_code,p.name AS project_name,wi.name AS work_item_name,wi.status AS work_item_status,
                  wi.cancelled_at,wi.skipped_at
           FROM work_item_batch_members m
           JOIN projects p ON p.id=m.project_id
           JOIN project_work_items wi ON wi.id=m.work_item_id
           WHERE m.batch_id=? ORDER BY p.project_code,m.id""",
        (batch_id,),
    ).fetchall()]
    for member in members:
        try:
            member["completion_record"] = json.loads(member.pop("completion_record_json") or "{}")
        except json.JSONDecodeError:
            member["completion_record"] = {}
    batch["members"] = members
    batch["member_count"] = len(members)
    batch["open_member_count"] = sum(1 for member in members if member["member_status"] == "scheduled")
    return batch


def get_work_item_batch(batch_id: int) -> dict:
    with get_connection() as conn:
        return _serialize_batch(conn, batch_id)


def list_work_item_batches(filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    with get_connection() as conn:
        clauses, params = ["1=1"], []
        if filters.get("status"):
            clauses.append("b.status=?")
            params.append(filters["status"])
        if filters.get("work_item_name"):
            clauses.append("b.work_item_name=?")
            params.append(filters["work_item_name"])
        if filters.get("project_id"):
            clauses.append("EXISTS (SELECT 1 FROM work_item_batch_members fm WHERE fm.batch_id=b.id AND fm.project_id=?)")
            params.append(int(filters["project_id"]))
        if filters.get("year"):
            clauses.append("substr(COALESCE(b.scheduled_on,''),1,4)=?")
            params.append(str(filters["year"]))
        if filters.get("keyword"):
            clauses.append("(b.name LIKE ? OR b.work_item_name LIKE ?)")
            keyword = f"%{str(filters['keyword']).strip()}%"
            params.extend([keyword, keyword])
        rows = conn.execute(
            f"SELECT b.id FROM work_item_batches b WHERE {' AND '.join(clauses)} "
            "ORDER BY CASE b.status WHEN 'open' THEN 0 WHEN 'closed' THEN 1 ELSE 2 END, "
            "COALESCE(b.scheduled_on,'') DESC,b.updated_at DESC,b.id DESC",
            params,
        ).fetchall()
        return [_serialize_batch(conn, int(row["id"])) for row in rows]


def current_batch_summaries_for_items(conn: sqlite3.Connection, item_ids: list[int]) -> dict[int, list[dict]]:
    """Return open scheduling summaries without treating batch membership as item state."""
    if not item_ids:
        return {}
    placeholders = ",".join("?" for _ in item_ids)
    rows = conn.execute(
        f"""SELECT m.work_item_id,b.id,b.name,b.scheduled_on,b.updated_at
            FROM work_item_batch_members m JOIN work_item_batches b ON b.id=m.batch_id
            WHERE m.work_item_id IN ({placeholders}) AND b.status='open' AND m.member_status='scheduled'
            ORDER BY m.work_item_id,COALESCE(b.scheduled_on,'') DESC,b.updated_at DESC,b.id DESC""",
        item_ids,
    ).fetchall()
    result: dict[int, list[dict]] = {}
    for row in rows:
        result.setdefault(int(row["work_item_id"]), []).append({
            "id": int(row["id"]), "name": row["name"], "scheduled_on": row["scheduled_on"],
        })
    return result


def _batch_or_error(conn: sqlite3.Connection, batch_id: int, *, open_only: bool = False) -> dict:
    row = conn.execute("SELECT * FROM work_item_batches WHERE id=?", (batch_id,)).fetchone()
    if not row:
        raise NotFoundError("批次不存在")
    batch = dict(row)
    if open_only and batch["status"] != "open":
        raise ValidationError("仅未办结批次可执行此操作")
    return batch


def _selected_members(conn: sqlite3.Connection, batch_id: int, member_ids: list[int], *, scheduled_only: bool = True) -> list[dict]:
    if not isinstance(member_ids, list) or not member_ids:
        raise ValidationError("请选择至少一个批次成员")
    normalized = [int(member_id) for member_id in member_ids]
    if len(set(normalized)) != len(normalized):
        raise ValidationError("批次成员不能重复")
    placeholders = ",".join("?" for _ in normalized)
    rows = [dict(row) for row in conn.execute(
        f"""SELECT m.*,p.name AS project_name,wi.name AS work_item_name,wi.status AS work_item_status,
                   wi.cancelled_at,wi.skipped_at,wi.completion_record_json
            FROM work_item_batch_members m
            JOIN projects p ON p.id=m.project_id JOIN project_work_items wi ON wi.id=m.work_item_id
            WHERE m.batch_id=? AND m.id IN ({placeholders})""",
        [batch_id, *normalized],
    ).fetchall()]
    if len(rows) != len(normalized):
        raise ValidationError("选择中包含不属于当前批次的事项")
    if scheduled_only:
        invalid = [row for row in rows if row["member_status"] != "scheduled" or row["cancelled_at"] or row["skipped_at"] or row["work_item_status"] not in _ACTIONABLE_STATUSES]
        if invalid:
            details = "；".join(f"{row['project_name']}：事项当前不可办理" for row in invalid)
            raise ValidationError(details)
    return rows


def update_work_item_batch(batch_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        batch = _batch_or_error(conn, batch_id, open_only=True)
        name = str(payload.get("name") if "name" in payload else batch["name"]).strip()
        if not name:
            raise ValidationError("批次名称不能为空")
        now = _now()
        conn.execute("UPDATE work_item_batches SET name=?,scheduled_on=?,note=?,updated_by=?,updated_at=? WHERE id=?", (
            name, str(payload.get("scheduled_on") if "scheduled_on" in payload else batch["scheduled_on"] or "").strip(),
            str(payload.get("note") if "note" in payload else batch["note"] or "").strip(), operator, now, batch_id,
        ))
        _event(conn, batch_id, "WORK_ITEM_BATCH_UPDATED", operator, {"before": batch, "name": name})
        return _serialize_batch(conn, batch_id)


def add_work_item_batch_members(batch_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    targets = payload.get("targets") or []
    if not operator or not isinstance(targets, list) or not targets:
        raise ValidationError("请选择成员并填写操作人")
    with get_connection() as conn:
        batch = _batch_or_error(conn, batch_id, open_only=True)
        rows, seen = [], set()
        for target in targets:
            project, item = _member_row(conn, target, batch["work_item_name"])
            if item["id"] in seen:
                raise ValidationError("同一事项不能重复加入批次")
            seen.add(item["id"])
            existing = conn.execute("SELECT member_status FROM work_item_batch_members WHERE batch_id=? AND work_item_id=?", (batch_id, item["id"])).fetchone()
            if existing and existing["member_status"] != "removed":
                raise ValidationError(f"{project['name']}：已属于当前批次")
            rows.append((project, item, bool(existing)))
        for project, item, existed in rows:
            if existed:
                conn.execute("UPDATE work_item_batch_members SET member_status='scheduled',removed_at=NULL,removed_by=NULL,removed_reason=NULL,added_by=? WHERE batch_id=? AND work_item_id=?", (operator, batch_id, item["id"]))
            else:
                conn.execute("INSERT INTO work_item_batch_members (batch_id,project_id,work_item_id,added_by) VALUES (?,?,?,?)", (batch_id, project["id"], item["id"], operator))
            _audit_project_batch(conn, project["id"], "WORK_ITEM_BATCH_MEMBER_ADDED", operator, {"batch_id": batch_id, "work_item_id": item["id"], "batch_name": batch["name"]})
        conn.execute("UPDATE work_item_batches SET updated_by=?,updated_at=? WHERE id=?", (operator, _now(), batch_id))
        _event(conn, batch_id, "WORK_ITEM_BATCH_MEMBERS_ADDED", operator, {"count": len(rows)})
        return _serialize_batch(conn, batch_id)


def remove_work_item_batch_members(batch_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason:
        raise ValidationError("移出成员必须填写操作人和原因")
    with get_connection() as conn:
        _batch_or_error(conn, batch_id, open_only=True)
        members = _selected_members(conn, batch_id, payload.get("member_ids") or [])
        now = _now()
        for member in members:
            conn.execute("UPDATE work_item_batch_members SET member_status='removed',removed_at=?,removed_by=?,removed_reason=? WHERE id=?", (now, operator, reason, member["id"]))
            _audit_project_batch(conn, member["project_id"], "WORK_ITEM_BATCH_MEMBER_REMOVED", operator, {"batch_id": batch_id, "work_item_id": member["work_item_id"], "reason": reason})
        _event(conn, batch_id, "WORK_ITEM_BATCH_MEMBERS_REMOVED", operator, {"count": len(members), "reason": reason})
        _refresh_batch_status(conn, batch_id)
        return _serialize_batch(conn, batch_id)


def complete_work_item_batch(batch_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        batch = _batch_or_error(conn, batch_id, open_only=True)
        members = _selected_members(conn, batch_id, payload.get("member_ids") or [])
        now = _now()
        completed_on = str(payload.get("completed_on") or now[:10])
        records = []
        for member in members:
            record = {"result": str(payload.get("result") or ""), "operator": operator, "completed_at": now,
                      "completed_on": completed_on, "note": str(payload.get("note") or ""), "create_milestone": False}
            conn.execute("UPDATE project_work_items SET status='completed',completion_record_json=?,updated_at=? WHERE id=?", (json.dumps(record, ensure_ascii=False), now, member["work_item_id"]))
            conn.execute("UPDATE work_item_batch_members SET member_status='completed',completion_record_json=?,processed_at=?,processed_by=? WHERE id=?", (json.dumps(record, ensure_ascii=False), now, operator, member["id"]))
            _audit_project_batch(conn, member["project_id"], "WORK_ITEM_COMPLETED", operator, {"work_item_id": member["work_item_id"], "record": record, "batch_id": batch_id})
            records.append({"member_id": member["id"], "project_id": member["project_id"], "work_item_id": member["work_item_id"], "record": record})
        _event(conn, batch_id, "WORK_ITEM_BATCH_COMPLETED", operator, {"member_ids": [member["id"] for member in members], "result": payload.get("result") or ""})
        _refresh_batch_status(conn, batch_id)
        return {**_serialize_batch(conn, batch_id), "processed": records, "next_groups": _next_groups(conn, members)}


def _next_groups(conn: sqlite3.Connection, members: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for member in members:
        current = conn.execute("SELECT sequence_rank FROM project_work_items WHERE id=?", (member["work_item_id"],)).fetchone()
        next_item = conn.execute(
            """SELECT id,name FROM project_work_items WHERE project_id=? AND sequence_rank>? AND status NOT IN ('completed','not_applicable')
               AND cancelled_at IS NULL AND skipped_at IS NULL ORDER BY sequence_rank,id LIMIT 1""",
            (member["project_id"], current["sequence_rank"] if current else -1),
        ).fetchone()
        key = str(next_item["name"]) if next_item else "__none__"
        groups.setdefault(key, {"work_item_name": None if key == "__none__" else key, "targets": []})["targets"].append({"project_id": member["project_id"], "work_item_id": None if not next_item else next_item["id"]})
    return list(groups.values())


def apply_work_item_batch_follow_up(batch_id: int, payload: dict) -> dict:
    operator, action = str(payload.get("operator") or "").strip(), str(payload.get("action") or "").strip()
    if not operator or action not in {"next", "rehandle", "hold"}:
        raise ValidationError("请选择有效后续处理并填写操作人")
    with get_connection() as conn:
        _batch_or_error(conn, batch_id)
        members = _selected_members(conn, batch_id, payload.get("member_ids") or [], scheduled_only=False)
        invalid = [member for member in members if member["member_status"] != "completed"]
        if invalid:
            raise ValidationError("后续处理仅适用于已在本批次完成的事项")
        now, note = _now(), str(payload.get("note") or "").strip()
        for member in members:
            member_status = "rehandled" if action == "rehandle" else "completed"
            if action == "rehandle":
                conn.execute("UPDATE project_work_items SET status='not_started',updated_at=? WHERE id=?", (now, member["work_item_id"]))
                _audit_project_batch(conn, member["project_id"], "WORK_ITEM_REOPENED", operator, {"work_item_id": member["work_item_id"], "prior_completion": member["completion_record_json"], "batch_id": batch_id, "reason": note})
            conn.execute("UPDATE work_item_batch_members SET member_status=?,follow_up_action=?,follow_up_note=?,processed_at=?,processed_by=? WHERE id=?", (member_status, action, note, now, operator, member["id"]))
        _event(conn, batch_id, "WORK_ITEM_BATCH_FOLLOW_UP", operator, {"action": action, "member_ids": [member["id"] for member in members], "note": note})
        return _serialize_batch(conn, batch_id)


def void_work_item_batch(batch_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason:
        raise ValidationError("作废批次必须填写操作人和原因")
    with get_connection() as conn:
        _batch_or_error(conn, batch_id, open_only=True)
        now = _now()
        members = [dict(row) for row in conn.execute("SELECT * FROM work_item_batch_members WHERE batch_id=? AND member_status='scheduled'", (batch_id,)).fetchall()]
        conn.execute("UPDATE work_item_batches SET status='voided',voided_at=?,voided_by=?,void_reason=?,updated_by=?,updated_at=? WHERE id=?", (now, operator, reason, operator, now, batch_id))
        conn.execute("UPDATE work_item_batch_members SET member_status='released',removed_at=?,removed_by=?,removed_reason=? WHERE batch_id=? AND member_status='scheduled'", (now, operator, reason, batch_id))
        for member in members:
            _audit_project_batch(conn, member["project_id"], "WORK_ITEM_BATCH_VOIDED", operator, {"batch_id": batch_id, "work_item_id": member["work_item_id"], "reason": reason})
        _event(conn, batch_id, "WORK_ITEM_BATCH_VOIDED", operator, {"reason": reason})
        return _serialize_batch(conn, batch_id)


def create_work_item_batch(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    work_item_name = str(payload.get("work_item_name") or "").strip()
    operator = str(payload.get("operator") or "").strip()
    targets = payload.get("targets") or []
    if not name or not work_item_name or not operator or not isinstance(targets, list) or not targets:
        raise ValidationError("请填写批次名称、事项名称、操作人并选择至少一个事项")
    with get_connection() as conn:
        validated: list[tuple[dict, dict]] = []
        seen_items: set[int] = set()
        for target in targets:
            project, item = _member_row(conn, target, work_item_name)
            if item["id"] in seen_items:
                raise ValidationError("同一事项不能重复加入同一批次")
            seen_items.add(item["id"])
            validated.append((project, item))
        now = _now()
        cursor = conn.execute(
            """INSERT INTO work_item_batches (name,work_item_name,scheduled_on,note,status,created_by,updated_by,updated_at)
               VALUES (?,?,?,?, 'open',?,?,?)""",
            (name, work_item_name, str(payload.get("scheduled_on") or "").strip(), str(payload.get("note") or "").strip(), operator, operator, now),
        )
        batch_id = int(cursor.lastrowid)
        for project, item in validated:
            conn.execute(
                "INSERT INTO work_item_batch_members (batch_id,project_id,work_item_id,added_by) VALUES (?,?,?,?)",
                (batch_id, project["id"], item["id"], operator),
            )
            _audit_project_batch(conn, project["id"], "WORK_ITEM_BATCH_MEMBER_ADDED", operator, {"batch_id": batch_id, "work_item_id": item["id"], "batch_name": name})
        _event(conn, batch_id, "WORK_ITEM_BATCH_CREATED", operator, {"target_count": len(validated)})
        return _serialize_batch(conn, batch_id)
