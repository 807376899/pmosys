from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from backend.app.core.errors import ConflictError, NotFoundError, ValidationError
from backend.app.core.money import decimal_of, difference, legacy_number, parse_money, preferred, total
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo


CONTRACT_STATUSES = {"not_started", "performing", "completed", "terminated", "paused"}
ACCEPTANCE_STATUSES = {"not_accepted", "accepting", "needs_rectification", "accepted"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _operator(payload: dict) -> str:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    return operator


def _text(value: object) -> str:
    return str(value or "").strip()


def _date(value: object, label: str, *, required: bool = False) -> str | None:
    result = _text(value)
    if not result:
        if required:
            raise ValidationError(f"{label}不能为空")
        return None
    try:
        return date.fromisoformat(result).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{label}必须为 YYYY-MM-DD") from exc


def _amount(value: object, label: str, *, required: bool = False) -> str | None:
    return parse_money(value, label, required=required)


def _contract_row(conn: sqlite3.Connection, contract_id: int) -> dict:
    row = conn.execute("SELECT * FROM contracts WHERE id=?", (contract_id,)).fetchone()
    if not row:
        raise NotFoundError("合同不存在")
    return dict(row)


def _project_stage(project: dict) -> str:
    from backend.app.services.projects import _project_stage as stage

    return stage(project)


def _project_rows(conn: sqlite3.Connection, project_ids: list[int]) -> list[dict]:
    unique_ids = list(dict.fromkeys(int(project_id) for project_id in project_ids))
    if not unique_ids:
        raise ValidationError("请至少关联一个项目")
    projects = project_repo.fetch_projects_by_ids(conn, unique_ids)
    if len(projects) != len(unique_ids):
        raise NotFoundError("关联项目不存在或已移除")
    return projects


def _validate_project_links(conn: sqlite3.Connection, project_ids: list[int], *, allow_completed: bool) -> list[dict]:
    projects = _project_rows(conn, project_ids)
    invalid = []
    for project in projects:
        stage = _project_stage(project)
        if stage == "项目库—推进中":
            continue
        if allow_completed and stage == "已完成":
            continue
        invalid.append(project["name"])
    if invalid:
        required = "推进中或已完成" if allow_completed else "推进中"
        raise ValidationError(f"仅{required}项目可关联合同：{'、'.join(invalid)}")
    return projects


def _project_audit(conn: sqlite3.Connection, project_ids: list[int], event_type: str, operator: str, *, reason: str = "", payload: dict | None = None) -> None:
    from backend.app.services.projects import _audit

    for project_id in dict.fromkeys(project_ids):
        _audit(conn, project_id, event_type, operator, reason, payload)


def _contract_audit(conn: sqlite3.Connection, contract_id: int, event_type: str, operator: str, *, reason: str = "", payload: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO contract_audit_events (contract_id,event_type,operator,reason,payload_json) VALUES (?,?,?,?,?)",
        (contract_id, event_type, operator, reason, json.dumps(payload or {}, ensure_ascii=False)),
    )


def _linked_projects(conn: sqlite3.Connection, contract_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute(
        """SELECT p.id,p.project_code,p.name,p.department,p.current_status,p.library_implementation_view,p.special_advancement_active,cp.allocated_amount,cp.allocated_amount_decimal
           FROM contract_projects cp JOIN projects p ON p.id=cp.project_id
           WHERE cp.contract_id=? AND p.deleted_at IS NULL ORDER BY p.project_code""",
        (contract_id,),
    ).fetchall()]


def _latest_progress(conn: sqlite3.Connection, contract_id: int) -> dict | None:
    row = conn.execute(
        """SELECT * FROM contract_progress_logs WHERE contract_id=? AND deleted_at IS NULL
           ORDER BY created_at DESC,id DESC LIMIT 1""",
        (contract_id,),
    ).fetchone()
    return dict(row) if row else None


def _acceptance_records(conn: sqlite3.Connection, contract_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM contract_acceptance_records WHERE contract_id=? ORDER BY acceptance_date DESC,id DESC",
        (contract_id,),
    ).fetchall()]


def _serialize_contract(conn: sqlite3.Connection, contract: dict, *, include_history: bool = False) -> dict:
    latest_progress = _latest_progress(conn, contract["id"])
    projects = _linked_projects(conn, contract["id"])
    contract["total_amount"] = preferred(contract, "total_amount")
    for project in projects:
        project["allocated_amount"] = preferred(project, "allocated_amount")
    allocated = [item["allocated_amount"] for item in projects]
    allocation_complete = bool(projects) and all(amount is not None for amount in allocated)
    allocation_total = total(amount for amount in allocated if amount is not None)
    result = {
        **contract,
        "projects": projects,
        "latest_progress": latest_progress,
        "allocation_complete": allocation_complete,
        "allocation_total": allocation_total,
        "allocation_difference": None if contract["total_amount"] is None or not allocation_complete else difference(contract["total_amount"], allocation_total),
    }
    if include_history:
        result["progress_logs"] = get_contract_progress_logs_for_connection(conn, contract["id"])
        result["acceptance_records"] = _acceptance_records(conn, contract["id"])
    return result


def _contract_summary(rows: list[dict]) -> dict:
    count = len(rows)
    if not count:
        return {"count": 0, "label": "暂无合同", "performing_count": 0, "pending_acceptance_count": 0, "contracts": []}
    performing = sum(row["status"] == "performing" for row in rows)
    pending = sum(row["status"] == "completed" and row["acceptance_status"] != "accepted" for row in rows)
    not_started = sum(row["status"] == "not_started" for row in rows)
    paused = sum(row["status"] == "paused" for row in rows)
    terminated = sum(row["status"] == "terminated" for row in rows)
    all_accepted = all(row["status"] == "completed" and row["acceptance_status"] == "accepted" for row in rows)
    if performing:
        label = f"{count}份 · {performing}履约中"
    elif pending:
        label = f"{count}份 · {pending}待验收"
    elif not_started:
        label = f"{count}份 · {not_started}未开始"
    elif paused:
        label = f"{count}份 · {paused}暂停"
    elif terminated:
        label = f"{count}份 · {terminated}已解除"
    elif all_accepted:
        label = f"{count}份 · 已全部验收"
    else:
        label = f"{count}份"
    return {
        "count": count,
        "label": label,
        "performing_count": performing,
        "pending_acceptance_count": pending,
        "contracts": [
            {"id": row["id"], "contract_no": row["contract_no"], "name": row["name"], "status": row["status"]}
            for row in rows
        ],
    }


def project_contract_projection(conn: sqlite3.Connection, project_id: int, *, include_contracts: bool = False) -> dict:
    rows = [dict(row) for row in conn.execute(
        """SELECT c.* FROM contracts c JOIN contract_projects cp ON cp.contract_id=c.id
           WHERE cp.project_id=? ORDER BY c.updated_at DESC,c.id DESC""",
        (project_id,),
    ).fetchall()]
    result = {"contract_summary": _contract_summary(rows)}
    if include_contracts:
        result["contracts"] = [_serialize_contract(conn, row) for row in rows]
    return result


def _project_links(payload: dict, *, current: list[dict] | None = None) -> tuple[list[int], dict[int, str | None]]:
    raw_links = payload.get("project_links")
    if raw_links is None:
        ids = list(dict.fromkeys(int(project_id) for project_id in payload.get("project_ids") or []))
        existing = {item["id"]: item.get("allocated_amount") for item in current or []}
        return ids, {project_id: existing.get(project_id) for project_id in ids}
    if not isinstance(raw_links, list):
        raise ValidationError("关联项目格式不合法")
    links: dict[int, float | None] = {}
    for item in raw_links:
        if not isinstance(item, dict) or not item.get("project_id"):
            raise ValidationError("关联项目格式不合法")
        project_id = int(item["project_id"])
        if project_id in links:
            raise ValidationError("同一项目不能重复关联合同")
        links[project_id] = _amount(item.get("allocated_amount"), "项目合同分摊金额")
    return list(links), links


def create_contract(payload: dict) -> dict:
    operator = _operator(payload)
    name = _text(payload.get("name"))
    if not name:
        raise ValidationError("合同名称不能为空")
    project_ids, allocations = _project_links(payload)
    status = _text(payload.get("status")) or "not_started"
    if status not in CONTRACT_STATUSES:
        raise ValidationError("合同状态不合法")
    data = _contract_fields(payload, status)
    completion_acceptance = payload.get("completion_acceptance") or None
    if status == "completed" and (not isinstance(completion_acceptance, dict) or _text(completion_acceptance.get("acceptance_status")) != "accepted"):
        raise ValidationError("合同验收通过后才能标记为已完成")
    history_correction = bool(payload.get("history_correction"))
    reason = _text(payload.get("reason"))
    if history_correction and not reason:
        raise ValidationError("补录历史合同必须填写原因")
    with get_connection() as conn:
        projects = _validate_project_links(conn, project_ids, allow_completed=history_correction)
        _assert_contract_number_available(conn, data["contract_no"])
        cursor = conn.execute(
            """INSERT INTO contracts (name,contract_no,supplier,total_amount,total_amount_decimal,signed_on,planned_completion_on,note,status,created_by,updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (name, data["contract_no"], data["supplier"], legacy_number(data["total_amount"]), data["total_amount"], data["signed_on"], data["planned_completion_on"], data["note"], status, operator, operator),
        )
        contract_id = cursor.lastrowid
        for project in projects:
            amount = allocations[project["id"]]
            conn.execute("INSERT INTO contract_projects (contract_id,project_id,linked_by,allocated_amount,allocated_amount_decimal) VALUES (?,?,?,?,?)", (contract_id, project["id"], operator, legacy_number(amount), amount))
        if completion_acceptance:
            _record_contract_acceptance(conn, contract_id, completion_acceptance, operator)
        event = "CONTRACT_HISTORICAL_CREATED" if history_correction else "CONTRACT_CREATED"
        _contract_audit(conn, contract_id, event, operator, reason=reason, payload={"project_ids": [project["id"] for project in projects], "allocations": allocations})
        _project_audit(conn, [project["id"] for project in projects], event, operator, reason=reason, payload={"contract_id": contract_id})
        return _serialize_contract(conn, _contract_row(conn, contract_id), include_history=True)


def _contract_fields(payload: dict, status: str) -> dict:
    contract_no = _text(payload.get("contract_no"))
    supplier = _text(payload.get("supplier"))
    total_amount = _amount(payload.get("total_amount"), "合同总金额")
    signed_on = _date(payload.get("signed_on"), "签订日期")
    planned_completion_on = _date(payload.get("planned_completion_on"), "计划完成日期")
    missing = []
    if not contract_no:
        missing.append("合同编号")
    if status in {"performing", "completed"}:
        if not supplier:
            missing.append("供应商")
        if total_amount is None:
            missing.append("合同总金额")
        if not signed_on:
            missing.append("签订日期")
    if missing:
        prefix = f"{status}合同必须填写：" if status in {"performing", "completed"} else "合同必须填写："
        raise ValidationError(f"{prefix}{'、'.join(missing)}")
    return {
        "contract_no": contract_no,
        "supplier": supplier,
        "total_amount": total_amount,
        "signed_on": signed_on,
        "planned_completion_on": planned_completion_on,
        "note": _text(payload.get("note")),
    }


def _assert_contract_number_available(conn: sqlite3.Connection, contract_no: str, contract_id: int | None = None) -> None:
    if not contract_no:
        return
    row = conn.execute("SELECT id FROM contracts WHERE contract_no=?", (contract_no,)).fetchone()
    if row and row["id"] != contract_id:
        raise ConflictError("合同编号已存在，请关联已有合同")


def get_contract(contract_id: int) -> dict:
    with get_connection() as conn:
        return _serialize_contract(conn, _contract_row(conn, contract_id), include_history=True)


def search_contracts(query: str = "") -> list[dict]:
    text = _text(query)
    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute(
            """SELECT * FROM contracts
               WHERE name LIKE ? OR COALESCE(contract_no,'') LIKE ? OR supplier LIKE ?
               ORDER BY updated_at DESC,id DESC LIMIT 50""",
            (f"%{text}%", f"%{text}%", f"%{text}%"),
        ).fetchall()]
        return [_serialize_contract(conn, row) for row in rows]


def list_project_contracts(project_id: int) -> list[dict]:
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        return project_contract_projection(conn, project_id, include_contracts=True)["contracts"]


def update_contract(contract_id: int, payload: dict) -> dict:
    operator = _operator(payload)
    with get_connection() as conn:
        before = _contract_row(conn, contract_id)
        status = _text(payload.get("status")) or before["status"]
        if status not in CONTRACT_STATUSES:
            raise ValidationError("合同状态不合法")
        merged = {**before, **{key: value for key, value in payload.items() if key in {"contract_no", "supplier", "total_amount", "signed_on", "planned_completion_on", "note"}}}
        data = _contract_fields(merged, status)
        _assert_contract_number_available(conn, data["contract_no"], contract_id)
        reason = _text(payload.get("reason"))
        if status == "terminated" and before["status"] != "terminated" and not reason:
            raise ValidationError("解除合同必须填写原因")
        name = _text(payload.get("name")) if "name" in payload else before["name"]
        if not name:
            raise ValidationError("合同名称不能为空")
        completion_acceptance = payload.get("completion_acceptance") or None
        if status == "completed" and before["status"] != "completed":
            accepted_inline = isinstance(completion_acceptance, dict) and _text(completion_acceptance.get("acceptance_status")) == "accepted"
            if before["acceptance_status"] != "accepted" and not accepted_inline:
                raise ValidationError("合同验收通过后才能标记为已完成")
        conn.execute(
            """UPDATE contracts SET name=?,contract_no=?,supplier=?,total_amount=?,total_amount_decimal=?,signed_on=?,planned_completion_on=?,note=?,status=?,updated_by=?,updated_at=? WHERE id=?""",
            (name, data["contract_no"], data["supplier"], legacy_number(data["total_amount"]), data["total_amount"], data["signed_on"], data["planned_completion_on"], data["note"], status, operator, _now(), contract_id),
        )
        projects = _linked_projects(conn, contract_id)
        if completion_acceptance:
            _record_contract_acceptance(conn, contract_id, completion_acceptance, operator)
        event = "CONTRACT_STATUS_UPDATED" if status != before["status"] else "CONTRACT_UPDATED"
        _contract_audit(conn, contract_id, event, operator, reason=reason, payload={"before": before, "after": _contract_row(conn, contract_id)})
        _project_audit(conn, [project["id"] for project in projects], event, operator, reason=reason, payload={"contract_id": contract_id})
        return _serialize_contract(conn, _contract_row(conn, contract_id), include_history=True)


def update_contract_projects(contract_id: int, payload: dict) -> dict:
    operator = _operator(payload)
    history_correction = bool(payload.get("history_correction"))
    reason = _text(payload.get("reason"))
    with get_connection() as conn:
        _contract_row(conn, contract_id)
        current_links = _linked_projects(conn, contract_id)
        current_ids = [project["id"] for project in current_links]
        target_ids, allocations = _project_links(payload, current=current_links)
        if not target_ids:
            raise ValidationError("合同必须至少关联一个项目")
        added = [project_id for project_id in target_ids if project_id not in current_ids]
        removed = [project_id for project_id in current_ids if project_id not in target_ids]
        if removed and not reason:
            raise ValidationError("解除错误关联必须填写原因")
        if history_correction and not reason:
            raise ValidationError("补录历史关联必须填写原因")
        if added:
            _validate_project_links(conn, added, allow_completed=history_correction)
        if removed:
            placeholders = ",".join("?" for _ in removed)
            conn.execute(f"DELETE FROM contract_projects WHERE contract_id=? AND project_id IN ({placeholders})", [contract_id, *removed])
        for project_id in added:
            amount = allocations[project_id]
            conn.execute("INSERT INTO contract_projects (contract_id,project_id,linked_by,allocated_amount,allocated_amount_decimal) VALUES (?,?,?,?,?)", (contract_id, project_id, operator, legacy_number(amount), amount))
        for project_id in target_ids:
            if project_id in current_ids:
                amount = allocations[project_id]
                conn.execute("UPDATE contract_projects SET allocated_amount=?,allocated_amount_decimal=? WHERE contract_id=? AND project_id=?", (legacy_number(amount), amount, contract_id, project_id))
        affected = [*current_ids, *added]
        _contract_audit(conn, contract_id, "CONTRACT_PROJECTS_UPDATED", operator, reason=reason, payload={"added": added, "removed": removed, "history_correction": history_correction, "allocations": allocations})
        _project_audit(conn, affected, "CONTRACT_PROJECTS_UPDATED", operator, reason=reason, payload={"contract_id": contract_id, "added": added, "removed": removed, "allocations": allocations})
        return _serialize_contract(conn, _contract_row(conn, contract_id), include_history=True)


def get_contract_progress_logs_for_connection(conn: sqlite3.Connection, contract_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute(
        """SELECT * FROM contract_progress_logs WHERE contract_id=? AND deleted_at IS NULL
           ORDER BY created_at ASC,id ASC""",
        (contract_id,),
    ).fetchall()]


def get_contract_progress_logs(contract_id: int) -> list[dict]:
    with get_connection() as conn:
        _contract_row(conn, contract_id)
        return get_contract_progress_logs_for_connection(conn, contract_id)


def create_contract_progress_log(contract_id: int, payload: dict) -> dict:
    operator, content = _operator(payload), _text(payload.get("content"))
    if not content:
        raise ValidationError("进展内容不能为空")
    with get_connection() as conn:
        _contract_row(conn, contract_id)
        cursor = conn.execute("INSERT INTO contract_progress_logs (contract_id,content,operator,updated_by) VALUES (?,?,?,?)", (contract_id, content, operator, operator))
        result = dict(conn.execute("SELECT * FROM contract_progress_logs WHERE id=?", (cursor.lastrowid,)).fetchone())
        project_ids = [project["id"] for project in _linked_projects(conn, contract_id)]
        _contract_audit(conn, contract_id, "CONTRACT_PROGRESS_RECORDED", operator, payload={"progress_log_id": result["id"]})
        _project_audit(conn, project_ids, "CONTRACT_PROGRESS_RECORDED", operator, payload={"contract_id": contract_id, "progress_log_id": result["id"]})
        return result


def update_contract_progress_log(contract_id: int, log_id: int, payload: dict) -> dict:
    operator, content = _operator(payload), _text(payload.get("content"))
    if not content:
        raise ValidationError("进展内容不能为空")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM contract_progress_logs WHERE id=? AND contract_id=? AND deleted_at IS NULL", (log_id, contract_id)).fetchone()
        if not row:
            raise NotFoundError("合同进展不存在")
        conn.execute("UPDATE contract_progress_logs SET content=?,updated_at=?,updated_by=? WHERE id=?", (content, _now(), operator, log_id))
        result = dict(conn.execute("SELECT * FROM contract_progress_logs WHERE id=?", (log_id,)).fetchone())
        project_ids = [project["id"] for project in _linked_projects(conn, contract_id)]
        _contract_audit(conn, contract_id, "CONTRACT_PROGRESS_UPDATED", operator, payload={"progress_log_id": log_id})
        _project_audit(conn, project_ids, "CONTRACT_PROGRESS_UPDATED", operator, payload={"contract_id": contract_id, "progress_log_id": log_id})
        return result


def delete_contract_progress_log(contract_id: int, log_id: int, payload: dict) -> None:
    operator, reason = _operator(payload), _text(payload.get("reason"))
    if not reason:
        raise ValidationError("删除合同进展必须填写原因")
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM contract_progress_logs WHERE id=? AND contract_id=? AND deleted_at IS NULL", (log_id, contract_id)).fetchone()
        if not row:
            raise NotFoundError("合同进展不存在")
        conn.execute("UPDATE contract_progress_logs SET deleted_at=?,deleted_by=?,deleted_reason=? WHERE id=?", (_now(), operator, reason, log_id))
        project_ids = [project["id"] for project in _linked_projects(conn, contract_id)]
        _contract_audit(conn, contract_id, "CONTRACT_PROGRESS_DELETED", operator, reason=reason, payload={"progress_log_id": log_id})
        _project_audit(conn, project_ids, "CONTRACT_PROGRESS_DELETED", operator, reason=reason, payload={"contract_id": contract_id, "progress_log_id": log_id})


def _record_contract_acceptance(conn: sqlite3.Connection, contract_id: int, payload: dict, operator: str) -> dict:
    status = _text(payload.get("acceptance_status"))
    if status not in ACCEPTANCE_STATUSES - {"not_accepted"}:
        raise ValidationError("验收状态不合法")
    acceptance_date = _date(payload.get("acceptance_date"), "验收日期", required=True)
    result = _text(payload.get("result"))
    if status == "accepted" and not result:
        raise ValidationError("验收通过必须填写验收结果")
    cursor = conn.execute(
        "INSERT INTO contract_acceptance_records (contract_id,acceptance_status,acceptance_date,result,note,operator) VALUES (?,?,?,?,?,?)",
        (contract_id, status, acceptance_date, result, _text(payload.get("note")), operator),
    )
    conn.execute("UPDATE contracts SET acceptance_status=?,updated_by=?,updated_at=? WHERE id=?", (status, operator, _now(), contract_id))
    record = dict(conn.execute("SELECT * FROM contract_acceptance_records WHERE id=?", (cursor.lastrowid,)).fetchone())
    project_ids = [project["id"] for project in _linked_projects(conn, contract_id)]
    _contract_audit(conn, contract_id, "CONTRACT_ACCEPTANCE_RECORDED", operator, payload={"acceptance_record_id": record["id"], "acceptance_status": status})
    _project_audit(conn, project_ids, "CONTRACT_ACCEPTANCE_RECORDED", operator, payload={"contract_id": contract_id, "acceptance_record_id": record["id"]})
    return record


def record_contract_acceptance(contract_id: int, payload: dict) -> dict:
    operator = _operator(payload)
    with get_connection() as conn:
        contract = _contract_row(conn, contract_id)
        if contract["status"] not in {"performing", "completed"}:
            raise ValidationError("仅履约中合同可登记验收")
        return _record_contract_acceptance(conn, contract_id, payload, operator)


def supplier_suggestions(query: str = "") -> list[str]:
    with get_connection() as conn:
        return [row["supplier"] for row in conn.execute(
            "SELECT DISTINCT supplier FROM contracts WHERE supplier<>'' AND supplier LIKE ? ORDER BY supplier LIMIT 20",
            (f"%{_text(query)}%",),
        ).fetchall()]
