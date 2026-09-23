from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from backend.app.core.errors import NotFoundError, ValidationError
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo


_ACTIONABLE = {"not_started", "in_progress"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _audit(conn: sqlite3.Connection, project_id: int, event: str, operator: str, payload: dict) -> None:
    from backend.app.services.projects import _audit as project_audit
    project_audit(conn, project_id, event, operator, payload=payload)


def _event(conn: sqlite3.Connection, activity_id: int, event: str, operator: str, payload: dict | None = None) -> None:
    conn.execute("INSERT INTO work_item_activity_events (activity_id,event_type,operator,payload_json) VALUES (?,?,?,?)", (activity_id, event, operator, json.dumps(payload or {}, ensure_ascii=False)))


def _activity(conn: sqlite3.Connection, activity_id: int, editable: bool = False) -> dict:
    row = conn.execute("SELECT * FROM work_item_activities WHERE id=?", (activity_id,)).fetchone()
    if not row:
        raise NotFoundError("办理活动不存在")
    result = dict(row)
    if editable and result["status"] in {"ended", "voided"}:
        raise ValidationError("已结束或已作废活动不可修改")
    return result


def _target(conn: sqlite3.Connection, target: dict, item_name: str) -> tuple[dict, dict]:
    project_id, item_id = int(target.get("project_id") or 0), int(target.get("work_item_id") or 0)
    project = project_repo.fetch_project_by_id(conn, project_id)
    item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
    if not project or not item:
        raise ValidationError("项目或事项实例不存在")
    item = dict(item)
    if item["name"] != item_name:
        raise ValidationError(f"{project['name']}：事项名称与办理活动不一致")
    if item.get("cancelled_at") or item.get("skipped_at") or item["status"] not in _ACTIONABLE:
        raise ValidationError(f"{project['name']}：事项当前不可参加办理活动")
    return project, item


def _refresh_status(conn: sqlite3.Connection, activity_id: int) -> None:
    activity = _activity(conn, activity_id)
    if activity["status"] in {"ended", "voided"}:
        return
    active = conn.execute("SELECT COUNT(*) FROM work_item_activity_members WHERE activity_id=? AND member_status='active'", (activity_id,)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM work_item_activity_members WHERE activity_id=? AND member_status='active' AND outcome_status='unrecorded'", (activity_id,)).fetchone()[0]
    if active and not pending:
        conn.execute("UPDATE work_item_activities SET status='ended',ended_at=?,updated_at=? WHERE id=?", (_now(), _now(), activity_id))


def _serialize(conn: sqlite3.Connection, activity_id: int) -> dict:
    _refresh_status(conn, activity_id)
    activity = _activity(conn, activity_id)
    members = [dict(row) for row in conn.execute(
        """SELECT m.*,p.project_code,p.name AS project_name,wi.status AS work_item_status,wi.cancelled_at,wi.skipped_at
           FROM work_item_activity_members m JOIN projects p ON p.id=m.project_id
           JOIN project_work_items wi ON wi.id=m.work_item_id WHERE m.activity_id=? ORDER BY p.project_code,m.id""", (activity_id,)
    ).fetchall()]
    for member in members:
        member["outcome"] = json.loads(member.pop("outcome_json") or "{}")
    activity["members"] = members
    activity["member_count"] = len(members)
    activity["recorded_outcome_count"] = sum(member["outcome_status"] == "recorded" for member in members)
    activity["progress_logs"] = [dict(row) for row in conn.execute("SELECT * FROM work_item_activity_progress_logs WHERE activity_id=? AND deleted_at IS NULL ORDER BY created_at,id", (activity_id,)).fetchall()]
    return activity


def list_work_item_activities(filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    with get_connection() as conn:
        where, values = ["1=1"], []
        for key, column in (("status", "a.status"), ("work_item_name", "a.work_item_name")):
            if filters.get(key): where.append(f"{column}=?"); values.append(filters[key])
        if filters.get("year"): where.append("substr(COALESCE(a.scheduled_on,''),1,4)=?"); values.append(str(filters["year"]))
        if filters.get("project_id"): where.append("EXISTS (SELECT 1 FROM work_item_activity_members m WHERE m.activity_id=a.id AND m.project_id=?)"); values.append(int(filters["project_id"]))
        if filters.get("keyword"):
            where.append("(a.name LIKE ? OR a.work_item_name LIKE ?)"); values.extend([f"%{filters['keyword'].strip()}%"] * 2)
        rows = conn.execute(f"SELECT id FROM work_item_activities a WHERE {' AND '.join(where)} ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'not_started' THEN 1 WHEN 'ended' THEN 2 ELSE 3 END,COALESCE(scheduled_on,'') DESC,updated_at DESC,id DESC", values).fetchall()
        return [_serialize(conn, row["id"]) for row in rows]


def get_work_item_activity(activity_id: int) -> dict:
    with get_connection() as conn:
        return _serialize(conn, activity_id)


def current_activity_summaries_for_items(conn: sqlite3.Connection, item_ids: list[int]) -> dict[int, list[dict]]:
    if not item_ids: return {}
    marks = ",".join("?" for _ in item_ids)
    rows = conn.execute(f"SELECT m.work_item_id,a.id,a.name,a.scheduled_on FROM work_item_activity_members m JOIN work_item_activities a ON a.id=m.activity_id WHERE m.work_item_id IN ({marks}) AND m.member_status='active' AND a.status IN ('not_started','in_progress') ORDER BY m.work_item_id,COALESCE(a.scheduled_on,'') DESC,a.id DESC", item_ids).fetchall()
    result: dict[int, list[dict]] = {}
    for row in rows: result.setdefault(row["work_item_id"], []).append({"id": row["id"], "name": row["name"], "scheduled_on": row["scheduled_on"]})
    return result


def create_work_item_activity(payload: dict) -> dict:
    name, item_name, operator = (str(payload.get(key) or "").strip() for key in ("name", "work_item_name", "operator"))
    targets = payload.get("targets") or []
    if not name or not item_name or not operator or not isinstance(targets, list) or not targets:
        raise ValidationError("请填写活动名称、事项名称、操作人并选择至少一个事项")
    with get_connection() as conn:
        rows, seen = [], set()
        for target in targets:
            project, item = _target(conn, target, item_name)
            if item["id"] in seen: raise ValidationError("同一事项不能重复加入同一办理活动")
            seen.add(item["id"]); rows.append((project, item))
        now = _now()
        activity_id = conn.execute("INSERT INTO work_item_activities (name,work_item_name,scheduled_on,note,created_by,updated_by,updated_at) VALUES (?,?,?,?,?,?,?)", (name, item_name, str(payload.get("scheduled_on") or "").strip(), str(payload.get("note") or "").strip(), operator, operator, now)).lastrowid
        for project, item in rows:
            conn.execute("INSERT INTO work_item_activity_members (activity_id,project_id,work_item_id,added_by) VALUES (?,?,?,?)", (activity_id, project["id"], item["id"], operator))
            _audit(conn, project["id"], "WORK_ITEM_ACTIVITY_MEMBER_ADDED", operator, {"activity_id": activity_id, "work_item_id": item["id"], "activity_name": name})
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_CREATED", operator, {"target_count": len(rows)})
        return _serialize(conn, activity_id)


def record_work_item_activity_results(activity_id: int, payload: dict) -> dict:
    operator, member_ids = str(payload.get("operator") or "").strip(), payload.get("member_ids") or []
    if not operator or not member_ids: raise ValidationError("请选择成员并填写操作人")
    with get_connection() as conn:
        activity = _activity(conn, activity_id, editable=True)
        marks = ",".join("?" for _ in member_ids)
        members = [dict(row) for row in conn.execute(f"SELECT * FROM work_item_activity_members WHERE activity_id=? AND id IN ({marks})", [activity_id, *member_ids]).fetchall()]
        if len(members) != len(set(member_ids)) or any(member["member_status"] != "active" for member in members): raise ValidationError("选择中包含不可办理活动成员")
        now = _now(); outcome = {"result": str(payload.get("result") or ""), "note": str(payload.get("note") or ""), "result_on": str(payload.get("result_on") or now[:10])}
        for member in members:
            conn.execute("UPDATE work_item_activity_members SET outcome_status='recorded',outcome_json=?,outcome_recorded_at=?,outcome_recorded_by=?,processed_at=?,processed_by=? WHERE id=?", (json.dumps(outcome, ensure_ascii=False), now, operator, now, operator, member["id"]))
            _audit(conn, member["project_id"], "WORK_ITEM_ACTIVITY_RESULT_RECORDED", operator, {"activity_id": activity_id, "work_item_id": member["work_item_id"], "outcome": outcome})
        conn.execute("UPDATE work_item_activities SET status=CASE WHEN status='not_started' THEN 'in_progress' ELSE status END,updated_by=?,updated_at=? WHERE id=?", (operator, now, activity_id))
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_RESULTS_RECORDED", operator, {"member_ids": member_ids, "outcome": outcome})
        return _serialize(conn, activity_id)


def create_work_item_activity_progress_log(activity_id: int, payload: dict) -> dict:
    operator, content = str(payload.get("operator") or "").strip(), str(payload.get("content") or "").strip()
    if not operator or not content: raise ValidationError("请填写活动进展和操作人")
    with get_connection() as conn:
        _activity(conn, activity_id, editable=True); now = _now()
        log_id = conn.execute("INSERT INTO work_item_activity_progress_logs (activity_id,content,operator,updated_by) VALUES (?,?,?,?)", (activity_id, content, operator, operator)).lastrowid
        conn.execute("UPDATE work_item_activities SET status=CASE WHEN status='not_started' THEN 'in_progress' ELSE status END,updated_by=?,updated_at=? WHERE id=?", (operator, now, activity_id))
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_PROGRESS_RECORDED", operator, {"progress_log_id": log_id})
        return _serialize(conn, activity_id)


def update_work_item_activity(activity_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("请填写操作人")
    with get_connection() as conn:
        before = _activity(conn, activity_id, editable=True)
        name = str(payload.get("name", before["name"]) or "").strip()
        if not name:
            raise ValidationError("请填写活动名称")
        now = _now()
        conn.execute("UPDATE work_item_activities SET name=?,scheduled_on=?,note=?,updated_by=?,updated_at=? WHERE id=?", (name, str(payload.get("scheduled_on", before["scheduled_on"]) or "").strip(), str(payload.get("note", before["note"]) or "").strip(), operator, now, activity_id))
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_UPDATED", operator, {"before": before, "name": name})
        return _serialize(conn, activity_id)


def start_work_item_activity(activity_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("请填写操作人")
    with get_connection() as conn:
        activity = _activity(conn, activity_id, editable=True)
        if activity["status"] == "not_started":
            now = _now()
            conn.execute("UPDATE work_item_activities SET status='in_progress',updated_by=?,updated_at=? WHERE id=?", (operator, now, activity_id))
            _event(conn, activity_id, "WORK_ITEM_ACTIVITY_STARTED", operator)
        return _serialize(conn, activity_id)


def add_work_item_activity_members(activity_id: int, payload: dict) -> dict:
    operator, targets = str(payload.get("operator") or "").strip(), payload.get("targets") or []
    if not operator or not targets:
        raise ValidationError("请选择至少一个事项并填写操作人")
    with get_connection() as conn:
        activity = _activity(conn, activity_id, editable=True)
        rows, seen = [], set()
        for target in targets:
            project, item = _target(conn, target, activity["work_item_name"])
            if item["id"] in seen:
                raise ValidationError("同一事项不能重复加入活动")
            seen.add(item["id"])
            existing = conn.execute("SELECT member_status FROM work_item_activity_members WHERE activity_id=? AND work_item_id=?", (activity_id, item["id"])).fetchone()
            if existing and existing["member_status"] == "active":
                raise ValidationError(f"{project['name']}：已属于当前活动")
            rows.append((project, item, bool(existing)))
        now = _now()
        for project, item, exists in rows:
            if exists:
                conn.execute("UPDATE work_item_activity_members SET member_status='active',removed_at=NULL,removed_by='',removed_reason='',outcome_status='unrecorded',outcome_json='{}',outcome_recorded_at=NULL,outcome_recorded_by='',added_by=?,added_at=? WHERE activity_id=? AND work_item_id=?", (operator, now, activity_id, item["id"]))
            else:
                conn.execute("INSERT INTO work_item_activity_members (activity_id,project_id,work_item_id,added_by) VALUES (?,?,?,?)", (activity_id, project["id"], item["id"], operator))
            _audit(conn, project["id"], "WORK_ITEM_ACTIVITY_MEMBER_ADDED", operator, {"activity_id": activity_id, "work_item_id": item["id"]})
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_MEMBERS_ADDED", operator, {"work_item_ids": [item["id"] for _, item, _ in rows]})
        return _serialize(conn, activity_id)


def remove_work_item_activity_members(activity_id: int, payload: dict) -> dict:
    operator, member_ids, reason = str(payload.get("operator") or "").strip(), payload.get("member_ids") or [], str(payload.get("reason") or "").strip()
    if not operator or not member_ids or not reason:
        raise ValidationError("移出活动成员必须填写原因和操作人")
    with get_connection() as conn:
        _activity(conn, activity_id, editable=True)
        marks = ",".join("?" for _ in member_ids)
        rows = [dict(row) for row in conn.execute(f"SELECT * FROM work_item_activity_members WHERE activity_id=? AND id IN ({marks})", [activity_id, *member_ids]).fetchall()]
        if len(rows) != len(set(member_ids)) or any(row["member_status"] != "active" for row in rows):
            raise ValidationError("选择中包含不可移出的活动成员")
        active_count = conn.execute("SELECT COUNT(*) FROM work_item_activity_members WHERE activity_id=? AND member_status='active'", (activity_id,)).fetchone()[0]
        if active_count <= len(rows):
            raise ValidationError("办理活动至少保留一个关联项目")
        now = _now()
        for row in rows:
            conn.execute("UPDATE work_item_activity_members SET member_status='removed',removed_at=?,removed_by=?,removed_reason=? WHERE id=?", (now, operator, reason, row["id"]))
            _audit(conn, row["project_id"], "WORK_ITEM_ACTIVITY_MEMBER_REMOVED", operator, {"activity_id": activity_id, "work_item_id": row["work_item_id"], "reason": reason})
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_MEMBERS_REMOVED", operator, {"member_ids": member_ids, "reason": reason})
        return _serialize(conn, activity_id)


def void_work_item_activity(activity_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason:
        raise ValidationError("作废办理活动必须填写原因和操作人")
    with get_connection() as conn:
        _activity(conn, activity_id, editable=True)
        now = _now()
        conn.execute("UPDATE work_item_activities SET status='voided',voided_at=?,voided_by=?,voided_reason=?,updated_by=?,updated_at=? WHERE id=?", (now, operator, reason, operator, now, activity_id))
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_VOIDED", operator, {"reason": reason})
        return _serialize(conn, activity_id)


def end_work_item_activity(activity_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator: raise ValidationError("请填写操作人")
    with get_connection() as conn:
        _activity(conn, activity_id, editable=True); now = _now()
        conn.execute("UPDATE work_item_activities SET status='ended',ended_at=?,ended_by=?,updated_by=?,updated_at=? WHERE id=?", (now, operator, operator, now, activity_id))
        _event(conn, activity_id, "WORK_ITEM_ACTIVITY_ENDED", operator)
        return _serialize(conn, activity_id)
