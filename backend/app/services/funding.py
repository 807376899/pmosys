from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime

import pandas as pd

from backend.app.core.errors import NotFoundError, ValidationError
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _operator(payload: dict) -> str:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    return operator


def _amount(value: object, label: str, *, required: bool = True) -> float | None:
    if value in (None, ""):
        if required:
            raise ValidationError(f"{label}不能为空")
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}必须为数字") from exc
    if result < 0:
        raise ValidationError(f"{label}不能小于 0")
    return result


def _year(value: object, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}必须为四位年份") from exc
    if not 1900 <= result <= 9999:
        raise ValidationError(f"{label}必须为四位年份")
    return result


def _funding_audit(conn: sqlite3.Connection, entity_type: str, entity_id: int | None, event_type: str, operator: str, payload: dict, reason: str = "") -> None:
    conn.execute(
        "INSERT INTO funding_audit_events (entity_type,entity_id,event_type,operator,reason,payload_json) VALUES (?,?,?,?,?,?)",
        (entity_type, entity_id, event_type, operator, reason, json.dumps(payload, ensure_ascii=False)),
    )


def _project_audit(conn: sqlite3.Connection, project_id: int, event_type: str, operator: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO audit_events (project_id,event_type,operator,payload_json) VALUES (?,?,?,?)",
        (project_id, event_type, operator, json.dumps(payload, ensure_ascii=False)),
    )


def _source_stats(conn: sqlite3.Connection, source: dict) -> dict:
    totals = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN allocation_amount_recorded=1 THEN allocated_amount ELSE 0 END),0) AS total, COUNT(DISTINCT project_id) AS projects FROM project_funding_allocations WHERE funding_source_id=?",
        (source["id"],),
    ).fetchone()
    return {
        **source,
        "allocated_total": float(totals["total"]),
        "project_count": int(totals["projects"]),
    }


def _source_by_id(conn: sqlite3.Connection, source_id: int) -> dict:
    row = conn.execute("SELECT * FROM funding_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise NotFoundError("资金号不存在")
    return dict(row)


def list_arrangements(year: int) -> list[dict]:
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM annual_funding_arrangements WHERE planning_year=? ORDER BY id DESC", (year,)).fetchall()]


def create_arrangement(payload: dict) -> dict:
    operator = _operator(payload)
    year = _year(payload.get("planning_year"), "年度")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValidationError("名称不能为空")
    amount = _amount(payload.get("estimated_amount"), "预计总额")
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO annual_funding_arrangements (planning_year,name,estimated_amount,fund_code,note,created_by,updated_by) VALUES (?,?,?,?,?,?,?)",
            (year, name, amount, str(payload.get("fund_code") or "").strip(), str(payload.get("note") or "").strip(), operator, operator),
        )
        result = dict(conn.execute("SELECT * FROM annual_funding_arrangements WHERE id=?", (cursor.lastrowid,)).fetchone())
        _funding_audit(conn, "annual_arrangement", result["id"], "ANNUAL_FUNDING_ARRANGEMENT_CREATED", operator, result)
        return result


def update_arrangement(arrangement_id: int, payload: dict) -> dict:
    operator = _operator(payload)
    with get_connection() as conn:
        before = conn.execute("SELECT * FROM annual_funding_arrangements WHERE id=?", (arrangement_id,)).fetchone()
        if not before:
            raise NotFoundError("年度资金安排不存在")
        fields: dict[str, object] = {}
        if "planning_year" in payload:
            fields["planning_year"] = _year(payload["planning_year"], "年度")
        if "name" in payload:
            fields["name"] = str(payload["name"] or "").strip()
            if not fields["name"]:
                raise ValidationError("名称不能为空")
        if "estimated_amount" in payload:
            fields["estimated_amount"] = _amount(payload["estimated_amount"], "预计总额")
        for key in ("fund_code", "note"):
            if key in payload:
                fields[key] = str(payload[key] or "").strip()
        if not fields:
            raise ValidationError("没有可更新的字段")
        fields.update({"updated_by": operator, "updated_at": _now()})
        conn.execute(f"UPDATE annual_funding_arrangements SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?", [*fields.values(), arrangement_id])
        result = dict(conn.execute("SELECT * FROM annual_funding_arrangements WHERE id=?", (arrangement_id,)).fetchone())
        _funding_audit(conn, "annual_arrangement", arrangement_id, "ANNUAL_FUNDING_ARRANGEMENT_UPDATED", operator, {"before": dict(before), "after": result})
        return result


def delete_arrangement(arrangement_id: int, payload: dict) -> None:
    operator = _operator(payload)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValidationError("删除年度资金安排必须填写原因")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM annual_funding_arrangements WHERE id=?", (arrangement_id,)).fetchone()
        if not row:
            raise NotFoundError("年度资金安排不存在")
        conn.execute("DELETE FROM annual_funding_arrangements WHERE id=?", (arrangement_id,))
        _funding_audit(conn, "annual_arrangement", arrangement_id, "ANNUAL_FUNDING_ARRANGEMENT_DELETED", operator, dict(row), reason)


def create_source(payload: dict) -> dict:
    operator = _operator(payload)
    code = str(payload.get("fund_code") or "").strip()
    if not code:
        raise ValidationError("资金号不能为空")
    start, end = _year(payload.get("valid_from_year"), "有效起始年份"), _year(payload.get("valid_until_year"), "有效结束年份")
    if end < start:
        raise ValidationError("有效结束年份不能早于有效起始年份")
    reference = _amount(payload.get("reference_amount"), "资金参考金额", required=False)
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO funding_sources (fund_code,fund_name,fund_manager,reference_amount,valid_from_year,valid_until_year,scope_note,note,created_by,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (code, str(payload.get("fund_name") or "").strip(), str(payload.get("fund_manager") or "").strip(), reference, start, end, str(payload.get("scope_note") or "").strip(), str(payload.get("note") or "").strip(), operator, operator),
            )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"资金号已存在: {code}") from exc
        source = _source_stats(conn, dict(conn.execute("SELECT * FROM funding_sources WHERE id=?", (cursor.lastrowid,)).fetchone()))
        _funding_audit(conn, "funding_source", source["id"], "FUNDING_SOURCE_CREATED", operator, source)
        return source


def list_sources(year: int | None = None) -> list[dict]:
    with get_connection() as conn:
        sql, params = "SELECT * FROM funding_sources", []
        if year is not None:
            sql += " WHERE valid_from_year<=? AND valid_until_year>=?"
            params = [year, year]
        return [_source_stats(conn, dict(row)) for row in conn.execute(f"{sql} ORDER BY fund_code", params).fetchall()]


def update_source(source_id: int, payload: dict) -> dict:
    operator = _operator(payload)
    with get_connection() as conn:
        before = _source_by_id(conn, source_id)
        fields: dict[str, object] = {}
        if "fund_code" in payload:
            code = str(payload["fund_code"] or "").strip()
            if not code:
                raise ValidationError("资金号不能为空")
            fields["fund_code"] = code
        if "reference_amount" in payload:
            fields["reference_amount"] = _amount(payload["reference_amount"], "资金参考金额", required=False)
        for key in ("valid_from_year", "valid_until_year"):
            if key in payload:
                fields[key] = _year(payload[key], "有效起始年份" if key.endswith("from_year") else "有效结束年份")
        start, end = int(fields.get("valid_from_year", before["valid_from_year"])), int(fields.get("valid_until_year", before["valid_until_year"]))
        if end < start:
            raise ValidationError("有效结束年份不能早于有效起始年份")
        for key in ("fund_name", "fund_manager", "scope_note", "note"):
            if key in payload:
                fields[key] = str(payload[key] or "").strip()
        if not fields:
            raise ValidationError("没有可更新的字段")
        fields.update({"updated_by": operator, "updated_at": _now()})
        try:
            conn.execute(f"UPDATE funding_sources SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?", [*fields.values(), source_id])
        except sqlite3.IntegrityError as exc:
            raise ValidationError("资金号已存在") from exc
        result = _source_stats(conn, _source_by_id(conn, source_id))
        _funding_audit(conn, "funding_source", source_id, "FUNDING_SOURCE_UPDATED", operator, {"before": before, "after": result})
        return result


def delete_source(source_id: int, payload: dict) -> None:
    operator = _operator(payload)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValidationError("删除资金号必须填写原因")
    with get_connection() as conn:
        source = _source_by_id(conn, source_id)
        allocated = conn.execute("SELECT 1 FROM project_funding_allocations WHERE funding_source_id=? LIMIT 1", (source_id,)).fetchone()
        if allocated:
            raise ValidationError("已有项目分配的资金号不能删除，请先移除分配")
        conn.execute("DELETE FROM funding_sources WHERE id=?", (source_id,))
        _funding_audit(conn, "funding_source", source_id, "FUNDING_SOURCE_DELETED", operator, source, reason)


def _allocation_rows(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = [dict(row) for row in conn.execute(
        """SELECT a.*,s.fund_code,s.fund_name,s.fund_manager,s.reference_amount,s.valid_from_year,s.valid_until_year,s.scope_note
           FROM project_funding_allocations a JOIN funding_sources s ON s.id=a.funding_source_id
           WHERE a.project_id=? ORDER BY s.fund_code""",
        (project_id,),
    ).fetchall()]
    for row in rows:
        row["allocation_amount_recorded"] = bool(row["allocation_amount_recorded"])
        if not row["allocation_amount_recorded"]:
            row["allocated_amount"] = None
    return rows


def project_funding_projection(conn: sqlite3.Connection, project_id: int) -> dict:
    rows = _allocation_rows(conn, project_id)
    recorded = [float(row["allocated_amount"]) for row in rows if row["allocated_amount"] is not None]
    return {"funding_allocations": rows, "formal_allocation_total": float(sum(recorded)) if recorded else None}


def get_project_allocations(project_id: int) -> list[dict]:
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        return _allocation_rows(conn, project_id)


def _allocation_warnings(conn: sqlite3.Connection, project_id: int, source_id: int) -> list[str]:
    from backend.app.services.projects import _hydrate_project_projection

    warnings: list[str] = []
    project = project_repo.fetch_project_by_id(conn, project_id)
    assert project is not None
    _hydrate_project_projection(conn, project)
    total = conn.execute("SELECT COALESCE(SUM(CASE WHEN allocation_amount_recorded=1 THEN allocated_amount ELSE 0 END),0) FROM project_funding_allocations WHERE project_id=?", (project_id,)).fetchone()[0]
    budget = project.get("effective_budget")
    if budget is not None and float(total) > float(budget):
        warnings.append(f"项目正式分配 {float(total):g} 万，已超过当前有效预算 {float(budget):g} 万")
    source = _source_stats(conn, _source_by_id(conn, source_id))
    if source.get("reference_amount") is not None and float(source["allocated_total"]) > float(source["reference_amount"]):
        warnings.append(f"资金号 {source['fund_code']} 已分配 {float(source['allocated_total']):g} 万，超过参考金额 {float(source['reference_amount']):g} 万")
    return warnings


def upsert_project_allocation(project_id: int, payload: dict) -> dict:
    operator = _operator(payload)
    source_id = int(payload.get("funding_source_id") or 0)
    amount = _amount(payload.get("allocated_amount"), "分配金额")
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        _source_by_id(conn, source_id)
        before = conn.execute("SELECT * FROM project_funding_allocations WHERE project_id=? AND funding_source_id=?", (project_id, source_id)).fetchone()
        now = _now()
        if before:
            conn.execute("UPDATE project_funding_allocations SET allocated_amount=?,allocation_amount_recorded=1,updated_by=?,updated_at=? WHERE id=?", (amount, operator, now, before["id"]))
            event = "PROJECT_FUNDING_ALLOCATION_UPDATED"
        else:
            cursor = conn.execute("INSERT INTO project_funding_allocations (project_id,funding_source_id,allocated_amount,allocation_amount_recorded,created_by,updated_by) VALUES (?,?,?,?,?,?)", (project_id, source_id, amount, 1, operator, operator))
            before = {"id": cursor.lastrowid}
            event = "PROJECT_FUNDING_ALLOCATION_CREATED"
        result = dict(conn.execute("SELECT * FROM project_funding_allocations WHERE id=?", (before["id"],)).fetchone())
        _project_audit(conn, project_id, event, operator, {"before": dict(before), "after": result})
        _funding_audit(conn, "project_allocation", result["id"], event, operator, {"project_id": project_id, "before": dict(before), "after": result})
        return {**result, "warnings": _allocation_warnings(conn, project_id, source_id)}


def bulk_upsert_source_allocations(source_id: int, payload: dict) -> dict:
    operator = _operator(payload)
    allocations = payload.get("allocations") or []
    if not allocations:
        raise ValidationError("请至少选择一个项目")
    with get_connection() as conn:
        _source_by_id(conn, source_id)
        normalized: list[tuple[int, float]] = []
        for item in allocations:
            project_id = int(item.get("project_id") or 0)
            if not project_repo.fetch_project_by_id(conn, project_id):
                raise ValidationError(f"项目不存在: {project_id}")
            normalized.append((project_id, _amount(item.get("allocated_amount"), "分配金额") or 0))
        if len({item[0] for item in normalized}) != len(normalized):
            raise ValidationError("同一项目只能填写一次")
        for project_id, amount in normalized:
            existing = conn.execute("SELECT id,allocated_amount FROM project_funding_allocations WHERE project_id=? AND funding_source_id=?", (project_id, source_id)).fetchone()
            if existing:
                conn.execute("UPDATE project_funding_allocations SET allocated_amount=?,allocation_amount_recorded=1,updated_by=?,updated_at=? WHERE id=?", (amount, operator, _now(), existing["id"]))
                event = "PROJECT_FUNDING_ALLOCATION_UPDATED"
                allocation_id = existing["id"]
            else:
                allocation_id = conn.execute("INSERT INTO project_funding_allocations (project_id,funding_source_id,allocated_amount,allocation_amount_recorded,created_by,updated_by) VALUES (?,?,?,?,?,?)", (project_id, source_id, amount, 1, operator, operator)).lastrowid
                event = "PROJECT_FUNDING_ALLOCATION_CREATED"
            _project_audit(conn, project_id, event, operator, {"funding_source_id": source_id, "allocated_amount": amount})
            _funding_audit(conn, "project_allocation", allocation_id, event, operator, {"project_id": project_id, "funding_source_id": source_id, "allocated_amount": amount})
        warnings = []
        for project_id, _ in normalized:
            warnings.extend(_allocation_warnings(conn, project_id, source_id))
        return {"processed_count": len(normalized), "warnings": list(dict.fromkeys(warnings))}


def delete_project_allocation(project_id: int, allocation_id: int, payload: dict) -> None:
    operator = _operator(payload)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValidationError("移除资金分配必须填写原因")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project_funding_allocations WHERE id=? AND project_id=?", (allocation_id, project_id)).fetchone()
        if not row:
            raise NotFoundError("项目资金分配不存在")
        conn.execute("DELETE FROM project_funding_allocations WHERE id=?", (allocation_id,))
        _project_audit(conn, project_id, "PROJECT_FUNDING_ALLOCATION_DELETED", operator, dict(row))
        _funding_audit(conn, "project_allocation", allocation_id, "PROJECT_FUNDING_ALLOCATION_DELETED", operator, dict(row), reason)


def funding_overview(year: int) -> dict:
    with get_connection() as conn:
        arrangements = [dict(row) for row in conn.execute("SELECT * FROM annual_funding_arrangements WHERE planning_year=? ORDER BY id DESC", (year,)).fetchall()]
        from backend.app.services.projects import _hydrate_project_projection

        projects = [dict(row) for row in conn.execute(
            """SELECT DISTINCT p.* FROM projects p JOIN project_advancement_records ar ON ar.project_id=p.id
               WHERE ar.advancement_year=? AND ar.status='active' AND p.deleted_at IS NULL ORDER BY p.project_code""", (year,)
        ).fetchall()]
        for project in projects:
            _hydrate_project_projection(conn, project, omit_legacy_status=True)
        estimated = float(sum(float(row["estimated_amount"]) for row in arrangements))
        advancing = float(sum(float(project["effective_budget"] or 0) for project in projects))
        return {
            "year": year, "arrangements": arrangements, "estimated_total": estimated,
            "advancing_effective_budget_total": advancing, "difference": estimated - advancing,
            "over_expected": advancing > estimated if arrangements else False,
            "advancing_project_count": len(projects), "advancing_projects": projects,
            "sources": [_source_stats(conn, dict(row)) for row in conn.execute("SELECT * FROM funding_sources WHERE valid_from_year<=? AND valid_until_year>=? ORDER BY fund_code", (year, year)).fetchall()],
        }


_IMPORT_REQUIRED_COLUMNS = ("项目编号", "资金代码", "资金金额")
_IMPORT_COMPATIBILITY_ALIASES = {"资金号": "资金代码", "资金参考金额": "资金金额", "本年新增安排": "预算（本年资金安排）"}


def _read_import(content: bytes) -> pd.DataFrame:
    try:
        frame = pd.read_excel(io.BytesIO(content), dtype=object)
    except Exception as exc:
        raise ValidationError("无法读取正式资金分配文件") from exc
    for legacy, current in _IMPORT_COMPATIBILITY_ALIASES.items():
        if current not in frame.columns and legacy in frame.columns:
            frame = frame.rename(columns={legacy: current})
    missing = [column for column in _IMPORT_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValidationError(f"缺少列: {', '.join(missing)}")
    for column in ("项目名称", "项目分类", "学院", "预算（本年资金安排）", "资金名称", "资金负责人", "分配金额"):
        if column not in frame.columns:
            frame[column] = ""
    return frame.where(pd.notna(frame), "")


def _saved_plan_project_ids(conn: sqlite3.Connection, planning_year: int) -> set[int]:
    row = conn.execute("SELECT id FROM annual_advancement_drafts WHERE advancement_year=?", (planning_year,)).fetchone()
    if not row:
        return set()
    return {int(item[0]) for item in conn.execute(
        "SELECT project_id FROM annual_advancement_draft_members WHERE draft_id=? AND member_status!='removed'", (row["id"],)
    ).fetchall()}


def _import_record(conn: sqlite3.Connection, row_number: int, values: dict, allowed_project_ids: set[int] | None = None, planning_year: int | None = None) -> tuple[dict | None, dict | None]:
    code = str(values.get("项目编号") or "").strip()
    name = str(values.get("项目名称") or "").strip()
    fund_code = str(values.get("资金代码") or "").strip()
    if not code or not fund_code:
        return None, {"row_number": row_number, "code": "REQUIRED", "message": "项目编号、资金代码不能为空", "name": name}
    project = conn.execute("SELECT * FROM projects WHERE project_code=? AND deleted_at IS NULL", (code,)).fetchone()
    if not project:
        return None, {"row_number": row_number, "code": "PROJECT_NOT_FOUND", "message": f"项目编号不存在: {code}", "name": name}
    if allowed_project_ids is not None and project["id"] not in allowed_project_ids:
        return None, {"row_number": row_number, "code": "PROJECT_NOT_IN_ANNUAL_PLAN", "message": "项目不在当前已保存年度计划内", "name": project["name"]}
    if name and name != project["name"]:
        return None, {"row_number": row_number, "code": "PROJECT_NAME_MISMATCH", "message": "项目名称与项目编号不一致", "name": name}
    try:
        reference = _amount(values.get("资金金额"), "资金金额")
        allocated = _amount(values.get("分配金额"), "分配金额", required=False)
    except ValidationError as exc:
        return None, {"row_number": row_number, "code": "INVALID_AMOUNT", "message": str(exc), "name": project["name"]}
    source = conn.execute("SELECT * FROM funding_sources WHERE fund_code=?", (fund_code,)).fetchone()
    warnings: list[str] = []
    if source and source["reference_amount"] != reference:
        warnings.append("资金参考金额与系统现值不同，确认导入后将更新并写入审计")
    implementation_year = project["advancement_year"] or planning_year
    if not source and implementation_year is None:
        return None, {"row_number": row_number, "code": "IMPLEMENTATION_YEAR_REQUIRED", "message": "新资金号需关联具有实施年份的项目以确定有效期", "name": project["name"]}
    return {
        "row_number": row_number, "project_id": project["id"], "project_code": code, "project_name": project["name"],
        "fund_code": fund_code, "fund_name": str(values.get("资金名称") or "").strip(), "fund_manager": str(values.get("资金负责人") or "").strip(), "reference_amount": reference, "allocated_amount": allocated,
        "implementation_year": implementation_year, "is_new_source": not bool(source), "source_amount_changed": bool(warnings), "warnings": warnings,
    }, None


def preview_funding_import(content: bytes, planning_year: int | None = None) -> dict:
    frame = _read_import(content)
    with get_connection() as conn:
        allowed = _saved_plan_project_ids(conn, planning_year) if planning_year is not None else None
        records, errors, pairs = [], [], set()
        for index, row in frame.iterrows():
            record, error = _import_record(conn, index + 2, row.to_dict(), allowed, planning_year)
            if error:
                errors.append(error)
                continue
            assert record is not None
            pair = (record["project_id"], record["fund_code"])
            if pair in pairs:
                errors.append({"row_number": record["row_number"], "code": "DUPLICATE_PAIR", "message": "同一文件内项目与资金号不能重复", "name": record["project_name"]})
                continue
            pairs.add(pair); records.append(record)
    return {"total_rows": len(frame.index), "valid_rows": len(records), "invalid_rows": len(errors), "records": records, "errors": errors}


def commit_funding_import(records: list[dict], operator: str, confirm_source_amount_updates: bool, planning_year: int | None = None) -> dict:
    operator = _operator({"operator": operator})
    if not records:
        raise ValidationError("没有可导入的正式资金分配记录")
    with get_connection() as conn:
        allowed = _saved_plan_project_ids(conn, planning_year) if planning_year is not None else None
        normalized, errors, pairs = [], [], set()
        for raw in records:
            values = {"项目编号": raw.get("project_code"), "项目名称": raw.get("project_name"), "资金代码": raw.get("fund_code"), "资金名称": raw.get("fund_name"), "资金负责人": raw.get("fund_manager"), "资金金额": raw.get("reference_amount"), "分配金额": raw.get("allocated_amount")}
            record, error = _import_record(conn, int(raw.get("row_number") or 0), values, allowed, planning_year)
            if error:
                errors.append(error); continue
            assert record is not None
            pair = (record["project_id"], record["fund_code"])
            if pair in pairs:
                errors.append({"row_number": record["row_number"], "code": "DUPLICATE_PAIR", "message": "同一文件内项目与资金号不能重复", "name": record["project_name"]})
            else:
                pairs.add(pair); normalized.append(record)
        if errors:
            return {"total": len(records), "success": 0, "failed": len(errors), "errors": errors}
        if any(record["source_amount_changed"] for record in normalized) and not confirm_source_amount_updates:
            raise ValidationError("存在与系统不同的资金参考金额，请确认后再导入")
        by_code: dict[str, list[dict]] = {}
        for record in normalized:
            by_code.setdefault(record["fund_code"], []).append(record)
        import_id = conn.execute("INSERT INTO funding_audit_events (entity_type,event_type,operator,payload_json) VALUES (?,?,?,?)", ("funding_import", "FUNDING_ALLOCATION_IMPORTED", operator, json.dumps({"record_count": len(normalized)}, ensure_ascii=False))).lastrowid
        for code, items in by_code.items():
            source = conn.execute("SELECT * FROM funding_sources WHERE fund_code=?", (code,)).fetchone()
            reference = items[0]["reference_amount"]
            if source:
                source_id = source["id"]
                if source["reference_amount"] != reference:
                    conn.execute("UPDATE funding_sources SET reference_amount=?,updated_by=?,updated_at=? WHERE id=?", (reference, operator, _now(), source_id))
                    _funding_audit(conn, "funding_source", source_id, "FUNDING_SOURCE_REFERENCE_AMOUNT_IMPORTED", operator, {"before": source["reference_amount"], "after": reference, "import_audit_id": import_id})
                fields = {key: items[0][key] for key in ("fund_name", "fund_manager") if items[0][key]}
                if fields:
                    conn.execute(f"UPDATE funding_sources SET {', '.join(f'{key}=?' for key in fields)},updated_by=?,updated_at=? WHERE id=?", [*fields.values(), operator, _now(), source_id])
            else:
                years = [int(item["implementation_year"]) for item in items if item["implementation_year"] is not None]
                source_id = conn.execute("INSERT INTO funding_sources (fund_code,fund_name,fund_manager,reference_amount,valid_from_year,valid_until_year,created_by,updated_by) VALUES (?,?,?,?,?,?,?,?)", (code, items[0]["fund_name"], items[0]["fund_manager"], reference, min(years), max(years), operator, operator)).lastrowid
                _funding_audit(conn, "funding_source", source_id, "FUNDING_SOURCE_IMPORTED", operator, {"fund_code": code, "valid_from_year": min(years), "valid_until_year": max(years), "import_audit_id": import_id})
            for item in items:
                existing = conn.execute("SELECT id,allocated_amount FROM project_funding_allocations WHERE project_id=? AND funding_source_id=?", (item["project_id"], source_id)).fetchone()
                if existing:
                    conn.execute("UPDATE project_funding_allocations SET allocated_amount=?,allocation_amount_recorded=?,updated_by=?,updated_at=? WHERE id=?", (item["allocated_amount"] or 0, int(item["allocated_amount"] is not None), operator, _now(), existing["id"]))
                    event, allocation_id = "PROJECT_FUNDING_ALLOCATION_IMPORTED_UPDATED", existing["id"]
                else:
                    allocation_id = conn.execute("INSERT INTO project_funding_allocations (project_id,funding_source_id,allocated_amount,allocation_amount_recorded,created_by,updated_by) VALUES (?,?,?,?,?,?)", (item["project_id"], source_id, item["allocated_amount"] or 0, int(item["allocated_amount"] is not None), operator, operator)).lastrowid
                    event = "PROJECT_FUNDING_ALLOCATION_IMPORTED_CREATED"
                _project_audit(conn, item["project_id"], event, operator, {"funding_source_id": source_id, "allocated_amount": item["allocated_amount"], "import_audit_id": import_id})
        return {"total": len(records), "success": len(normalized), "failed": 0, "errors": []}


def funding_import_template(year: int) -> bytes:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.project_code,p.name,p.project_type,p.department,p.budget,p.approved_budget,
                      p.current_status,p.library_implementation_view,p.special_advancement_active,m.planned_new_amount,t.name AS project_type_name
               FROM annual_advancement_drafts d
               JOIN annual_advancement_draft_members m ON m.draft_id=d.id AND m.member_status!='removed'
               JOIN projects p ON p.id=m.project_id AND p.deleted_at IS NULL
               LEFT JOIN project_types t ON t.code=p.project_type
               WHERE d.advancement_year=? ORDER BY p.project_code""", (year,)
        ).fetchall()
    template_columns = ["项目编号", "项目名称", "项目分类", "学院", "预算（本年资金安排）", "资金代码", "资金名称", "资金负责人", "资金金额", "分配金额"]
    frame = pd.DataFrame([{
        "项目编号": row["project_code"], "项目名称": row["name"], "项目分类": row["project_type_name"] or "未分类", "学院": row["department"],
        "预算（本年资金安排）": row["planned_new_amount"], "资金代码": "", "资金名称": "", "资金负责人": "", "资金金额": "", "分配金额": "",
    } for row in rows], columns=template_columns)
    info = pd.DataFrame([
        ["填写说明", "仅可导入当前年度已保存计划中的项目；一行对应一个项目 × 资金代码关系；同一项目可占多行。"],
        ["项目分类 / 学院 / 预算（本年资金安排）", "系统导出的参考信息，项目分类使用用户可读名称；不用于识别或修改项目。"],
        ["资金代码", "必填；新资金代码会按关联项目规划年度创建有效期。"],
        ["资金名称 / 资金负责人", "选填；保存到资金代码信息。"],
        ["资金金额", "必填，单位：万元；表示资金代码的金额，不是该项目分配金额。"],
        ["分配金额", "选填，单位：万元；留空仍保存项目 × 资金代码关系，后续可再补录。"],
    ], columns=["字段", "说明"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="正式资金分配")
        info.to_excel(writer, index=False, sheet_name="填写说明")
    return output.getvalue()
