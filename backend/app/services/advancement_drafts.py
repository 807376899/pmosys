from __future__ import annotations

import json
from datetime import datetime

from backend.app.core.errors import NotFoundError, ValidationError
from backend.app.core.money import decimal_of, difference, legacy_number, parse_money, preferred, total
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo
from backend.app.services.projects import _audit, _hydrate_project_projection, _project_stage


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _year(value: object) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("年度必须为四位年份") from exc
    if not 1900 <= year <= 9999:
        raise ValidationError("年度必须在 1900 至 9999 之间")
    return year


def _operator(payload: dict) -> str:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("请填写操作人")
    return operator


def _draft(conn, year: int, operator: str) -> dict:
    row = conn.execute("SELECT * FROM annual_advancement_drafts WHERE advancement_year=?", (year,)).fetchone()
    if row:
        return dict(row)
    draft_id = conn.execute(
        "INSERT INTO annual_advancement_drafts (advancement_year,created_by) VALUES (?,?)", (year, operator)
    ).lastrowid
    return dict(conn.execute("SELECT * FROM annual_advancement_drafts WHERE id=?", (draft_id,)).fetchone())


def _event(conn, draft_id: int, event_type: str, operator: str, project_id: int | None = None, reason: str = "", payload: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO annual_advancement_draft_events (draft_id,project_id,event_type,operator,reason,payload_json) VALUES (?,?,?,?,?,?)",
        (draft_id, project_id, event_type, operator, reason, json.dumps(payload or {}, ensure_ascii=False)),
    )


def _member_action(project: dict) -> str:
    stage = _project_stage(project)
    if stage in {"已完成", "已废弃"}:
        return "terminal"
    if project.get("special_advancement_active"):
        return "already_special"
    if project.get("library_implementation_view") == "advancing":
        return "already_active"
    return "special" if stage == "未立项" else "include"


def _member_projection(conn, row: dict) -> dict:
    project = project_repo.fetch_project_by_id(conn, row["project_id"])
    if not project:
        raise NotFoundError("草案项目不存在")
    next_action = _member_action(project)
    projected = _hydrate_project_projection(conn, project, omit_legacy_status=True)
    return {
        "id": row["id"], "project_id": projected["id"], "project_code": projected["project_code"],
        "name": projected["name"], "stage": projected["stage"], "advancement": projected["advancement"],
        "effective_budget": projected["effective_budget"], "member_status": row["member_status"],
        "next_action": next_action, "added_at": row["added_at"], "confirmed_at": row["confirmed_at"],
        "planned_new_amount": preferred(row, "planned_new_amount") or "0",
    }


def _arrangements(conn, year: int) -> list[dict]:
    rows = [dict(row) for row in conn.execute(
        "SELECT * FROM annual_funding_arrangements WHERE planning_year=? ORDER BY id DESC", (year,)
    ).fetchall()]
    for row in rows:
        row["estimated_amount"] = preferred(row, "estimated_amount")
    return rows


def _latest_cycle(conn, project_id: int, statuses: tuple[str, ...] = ("active", "deferred")) -> dict | None:
    placeholders = ",".join("?" for _ in statuses)
    row = conn.execute(
        f"SELECT * FROM project_advancement_records WHERE project_id=? AND status IN ({placeholders}) ORDER BY id DESC LIMIT 1",
        (project_id, *statuses),
    ).fetchone()
    return dict(row) if row else None


def _plan_kind(conn, project: dict, row: dict | None, year: int) -> str | None:
    action = _member_action(project)
    if action in {"already_active", "already_special"}:
        cycle = _latest_cycle(conn, project["id"], ("active",))
        if cycle and int(cycle["advancement_year"]) < year:
            return "carryover"
        if cycle and int(cycle["advancement_year"]) == year:
            if row and row["member_status"] != "removed":
                return "current_year_planned" if row.get("member_kind") == "current_year" else "new_confirmed"
            return "current_year_unplanned"
        # A project cannot be a historical-year plan member before it was
        # actually included in advancement.
        return None
    if row and row["member_status"] != "removed":
        return "new_confirmed" if row["member_status"] == "confirmed" else "candidate"
    return "candidate" if action in {"include", "special"} else None


def _annual_plan_member(conn, project: dict, row: dict | None, year: int) -> dict:
    projected = _hydrate_project_projection(conn, project, omit_legacy_status=True)
    kind = _plan_kind(conn, project, row, year)
    assert kind is not None
    selected = kind in {"carryover", "new_confirmed", "current_year_planned"} or bool(row and row["member_status"] != "removed")
    manual_amount = bool(row and row.get("planned_amount_is_manual"))
    amount = preferred(row, "planned_new_amount") if row else ("0" if kind == "carryover" else None)
    # Legacy draft rows stored 0 even when that was only the former default.
    # Once a user edits an amount, including an explicit 0, the new flag wins.
    if row and not manual_amount and kind in {"candidate", "new_confirmed", "current_year_planned"} and decimal_of(amount) == 0:
        amount = projected["effective_budget"] or "0"
    if kind == "current_year_unplanned" and amount is None:
        amount = projected["effective_budget"] or "0"
    return {
        "id": row["id"] if row else None,
        "project_id": projected["id"],
        "project_code": projected["project_code"],
        "name": projected["name"],
        "department": projected.get("department") or "",
        "project_type": projected.get("project_type") or "",
        "stage": projected["stage"],
        "advancement": projected["advancement"],
        "effective_budget": projected["effective_budget"],
        "plan_kind": kind,
        "selected": selected,
        "member_status": row["member_status"] if row else None,
        "can_select": kind in {"candidate", "current_year_unplanned"},
        "can_cancel": kind == "new_confirmed",
        "counts_toward_stats": selected and decimal_of(amount) > 0,
        "planned_new_amount": amount,
        "planned_amount_is_manual": manual_amount,
        "default_planned_new_amount": projected["effective_budget"] or "0",
        "next_action": _member_action(project),
        "confirmed_at": row["confirmed_at"] if row else None,
    }


def get_annual_budget_plan(year_value: object) -> dict:
    """Return the complete annual planning board, not just persisted draft rows.

    Carryovers are derived from current advancement state every time.  Candidate
    selection remains explicit and is represented by a persisted draft member.
    """
    year = _year(year_value)
    with get_connection() as conn:
        draft = conn.execute("SELECT * FROM annual_advancement_drafts WHERE advancement_year=?", (year,)).fetchone()
        persisted = {}
        if draft:
            persisted = {row["project_id"]: dict(row) for row in conn.execute(
                "SELECT * FROM annual_advancement_draft_members WHERE draft_id=?", (draft["id"],)
            ).fetchall()}
        projects = [dict(row) for row in conn.execute(
            "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY department, project_code"
        ).fetchall()]
        members = [
            _annual_plan_member(conn, project, persisted.get(project["id"]), year)
            for project in projects
            if _plan_kind(conn, project, persisted.get(project["id"]), year) is not None
        ]
        # One-time repair for the former implicit-zero default.  It is safe to
        # persist only rows that have never been explicitly adjusted.
        for member in members:
            row = persisted.get(member["project_id"])
            if row and not row.get("planned_amount_is_manual") and member["plan_kind"] in {"candidate", "new_confirmed", "current_year_planned"} and decimal_of(preferred(row, "planned_new_amount")) == 0:
                conn.execute("UPDATE annual_advancement_draft_members SET planned_new_amount=?,planned_new_amount_decimal=? WHERE id=?", (legacy_number(member["planned_new_amount"]), member["planned_new_amount"], row["id"]))
        members.sort(key=lambda item: (0 if item["plan_kind"] == "carryover" else (1 if item["plan_kind"] in {"new_confirmed", "current_year_planned", "current_year_unplanned"} else (2 if item["stage"] == "项目库—未实施" else 3)), item["department"], item["project_code"]))
        selected = [item for item in members if item["selected"]]
        arrangements = _arrangements(conn, year)
        estimated_total = total(item["estimated_amount"] for item in arrangements)
        planned_total = total(item["planned_new_amount"] for item in selected)
        categories: dict[str, dict] = {}
        for item in selected:
            if not item["counts_toward_stats"]:
                continue
            code = item["project_type"]
            bucket = categories.setdefault(code, {"count": 0, "planned_new_amount": "0"})
            bucket["count"] += 1
            bucket["planned_new_amount"] = total((bucket["planned_new_amount"], item["planned_new_amount"]))
        return {
            "id": draft["id"] if draft else None,
            "year": year,
            "members": members,
            "planned_project_count": sum(item["counts_toward_stats"] for item in selected),
            "carryover_count": sum(item["plan_kind"] == "carryover" for item in selected),
            "draft_count": sum(item["member_status"] == "draft" for item in selected),
            "confirmed_count": sum(item["member_status"] == "confirmed" for item in selected),
            "planned_new_amount_total": planned_total,
            "estimated_total": estimated_total,
            "difference": difference(estimated_total, planned_total),
            "over_expected": decimal_of(planned_total) > decimal_of(estimated_total) if arrangements else False,
            "category_stats": categories,
            "arrangements": arrangements,
        }


def save_annual_budget_plan(year_value: object, payload: dict) -> dict:
    """Atomically persist the visible annual plan selection and annual amounts."""
    year, operator = _year(year_value), _operator(payload)
    raw_members = payload.get("members") or []
    if not isinstance(raw_members, list):
        raise ValidationError("年度计划成员格式无效")
    normalized: dict[int, tuple[str, bool | None]] = {}
    for item in raw_members:
        try:
            project_id = int(item.get("project_id") or 0)
            amount = parse_money(item.get("planned_new_amount"), "本年新增安排")
        except (TypeError, ValueError) as exc:
            raise ValidationError("本年新增安排必须为非负数字") from exc
        if project_id <= 0:
            raise ValidationError("本年新增安排必须为非负数字")
        if project_id in normalized:
            raise ValidationError("年度计划中存在重复项目")
        manual = bool(item["planned_amount_is_manual"]) if "planned_amount_is_manual" in item else None
        normalized[project_id] = (amount, manual)
    with get_connection() as conn:
        projects = {item["id"]: item for item in project_repo.fetch_projects_by_ids(conn, list(normalized))}
        if len(projects) != len(normalized):
            raise NotFoundError("年度计划包含不存在的项目")
        draft = _draft(conn, year, operator)
        existing = {row["project_id"]: dict(row) for row in conn.execute(
            "SELECT * FROM annual_advancement_draft_members WHERE draft_id=?", (draft["id"],)
        ).fetchall()}
        errors = []
        for project_id, project in projects.items():
            if _plan_kind(conn, project, existing.get(project_id), year) is None:
                errors.append(f"{project['name']}：已完成或已废弃项目不能进入年度计划")
        if errors:
            raise ValidationError("；".join(errors))
        now = _now()
        # Current carryovers are compulsory plan rows; a stale client may not
        # silently remove them from the annual plan.
        carryovers = [project for project in [dict(row) for row in conn.execute("SELECT * FROM projects WHERE deleted_at IS NULL").fetchall()] if _plan_kind(conn, project, existing.get(project["id"]), year) == "carryover"]
        missing_carryovers = [project["name"] for project in carryovers if project["id"] not in normalized]
        if missing_carryovers:
            raise ValidationError(f"请保留续建项目：{'、'.join(missing_carryovers)}")
        for project_id, (amount, requested_manual) in normalized.items():
            current = existing.get(project_id)
            kind = _plan_kind(conn, projects[project_id], current, year)
            if current:
                status = current["member_status"] if current["member_status"] == "confirmed" else ("confirmed" if kind in {"carryover", "current_year_unplanned"} else "draft")
                manual_amount = bool(current.get("planned_amount_is_manual")) if requested_manual is None else requested_manual
                conn.execute(
                    "UPDATE annual_advancement_draft_members SET member_status=?,planned_new_amount=?,planned_new_amount_decimal=?,planned_amount_is_manual=?,added_by=?,added_at=?,removed_by='',removed_at=NULL,removal_reason='' WHERE id=?",
                    (status, legacy_number(amount), amount, int(manual_amount), operator, now, current["id"]),
                )
            else:
                status = "confirmed" if kind in {"carryover", "current_year_unplanned"} else "draft"
                member_kind = "carryover" if kind == "carryover" else ("current_year" if kind == "current_year_unplanned" else "new")
                conn.execute(
                "INSERT INTO annual_advancement_draft_members (draft_id,project_id,member_status,added_by,planned_new_amount,planned_new_amount_decimal,planned_amount_is_manual,member_kind) VALUES (?,?,?,?,?,?,?,?)",
                (draft["id"], project_id, status, operator, legacy_number(amount), amount, int(bool(requested_manual)), member_kind),
                )
            _event(conn, draft["id"], "ANNUAL_BUDGET_PLAN_MEMBER_SAVED", operator, project_id, payload={"year": year, "planned_new_amount": amount})
            if kind == "current_year_unplanned":
                _event(conn, draft["id"], "ANNUAL_BUDGET_PLAN_CURRENT_YEAR_RECONCILED", operator, project_id, payload={"year": year, "planned_new_amount": amount})
        for project_id, current in existing.items():
            if project_id not in normalized and current["member_status"] == "draft":
                conn.execute(
                    "UPDATE annual_advancement_draft_members SET member_status='removed',removed_by=?,removed_at=? WHERE id=?",
                    (operator, now, current["id"]),
                )
                _event(conn, draft["id"], "ANNUAL_BUDGET_PLAN_MEMBER_REMOVED", operator, project_id, payload={"year": year})
        conn.execute("UPDATE annual_advancement_drafts SET updated_at=? WHERE id=?", (now, draft["id"]))
        _event(conn, draft["id"], "ANNUAL_BUDGET_PLAN_SAVED", operator, payload={"year": year, "member_count": len(normalized)})
    return get_annual_budget_plan(year)


def supplement_annual_budget_plan(year_value: object, payload: dict) -> dict:
    """Exception path: formally include selected pool projects and record them
    in the same annual plan, without confirming unrelated draft candidates."""
    year, operator = _year(year_value), _operator(payload)
    reason = str(payload.get("reason") or "").strip()
    project_ids = list(dict.fromkeys(int(value) for value in payload.get("project_ids") or []))
    if not project_ids or not reason:
        raise ValidationError("请选择项目并填写补充纳入理由")
    with get_connection() as conn:
        projects = project_repo.fetch_projects_by_ids(conn, project_ids)
        if len(projects) != len(project_ids):
            raise NotFoundError("项目不存在")
        invalid = [project["name"] for project in projects if _member_action(project) != "include"]
        if invalid:
            raise ValidationError(f"仅项目库—未实施项目可补充纳入：{'、'.join(invalid)}")
        draft = _draft(conn, year, operator)
        now = _now()
        for project in projects:
            member = conn.execute("SELECT * FROM annual_advancement_draft_members WHERE draft_id=? AND project_id=?", (draft["id"], project["id"])).fetchone()
            planned_amount = preferred(dict(member), "planned_new_amount") if member else (_hydrate_project_projection(conn, project)["effective_budget"] or "0")
            conn.execute(
                "INSERT INTO project_advancement_records (project_id,advancement_year,status,included_at,included_reason,included_by) VALUES (?,?, 'active',?,?,?)",
                (project["id"], year, now, reason, operator),
            )
            project_repo.update_project_status(conn, project["id"], {"library_implementation_view": "advancing", "advancement_year": year, "advancement_date": now, "updated_at": now})
            _audit(conn, project["id"], "PROJECT_INCLUDED_IN_ADVANCEMENT", operator, reason, {"year": year, "source": "annual_plan_supplement"})
            if member:
                conn.execute("UPDATE annual_advancement_draft_members SET member_status='confirmed',planned_new_amount=?,planned_new_amount_decimal=?,confirmed_by=?,confirmed_at=? WHERE id=?", (legacy_number(planned_amount), planned_amount, operator, now, member["id"]))
            else:
                conn.execute("INSERT INTO annual_advancement_draft_members (draft_id,project_id,member_status,added_by,planned_new_amount,planned_new_amount_decimal,member_kind,confirmed_by,confirmed_at) VALUES (?,?, 'confirmed',?,?,?,?,?,?)", (draft["id"], project["id"], operator, legacy_number(planned_amount), planned_amount, "new", operator, now))
            _event(conn, draft["id"], "ANNUAL_BUDGET_PLAN_SUPPLEMENTED", operator, project["id"], reason, {"year": year, "planned_new_amount": planned_amount})
        conn.execute("UPDATE annual_advancement_drafts SET updated_at=? WHERE id=?", (now, draft["id"]))
    return get_annual_budget_plan(year)


def annual_plan_exception_action(year_value: object, payload: dict) -> dict:
    """Apply one annual-plan exception atomically and retain both audit trails."""
    year, operator = _year(year_value), _operator(payload)
    action = str(payload.get("action") or "")
    reason = str(payload.get("reason") or "").strip()
    project_ids = list(dict.fromkeys(int(value) for value in payload.get("project_ids") or []))
    if action not in {"supplement", "cancel", "defer", "resume", "special"} or not project_ids or not reason:
        raise ValidationError("请选择例外操作、项目并填写原因")
    special_entries = {int(item.get("project_id") or 0): item for item in payload.get("special_entries") or []}
    with get_connection() as conn:
        projects = {project["id"]: project for project in project_repo.fetch_projects_by_ids(conn, project_ids)}
        if len(projects) != len(project_ids):
            raise NotFoundError("项目不存在")
        draft = _draft(conn, year, operator)
        members = {row["project_id"]: dict(row) for row in conn.execute(
            "SELECT * FROM annual_advancement_draft_members WHERE draft_id=?", (draft["id"],)
        ).fetchall()}
        errors: list[str] = []
        for project_id in project_ids:
            project, member = projects[project_id], members.get(project_id)
            cycle = _latest_cycle(conn, project_id)
            if action == "supplement" and _member_action(project) != "include":
                errors.append(f"{project['name']}：仅项目库—未实施项目可补充纳入")
            elif action == "special":
                entry = special_entries.get(project_id, {})
                if _member_action(project) != "special": errors.append(f"{project['name']}：仅未立项项目可特批推进")
                elif not str(entry.get("approval_basis") or "").strip(): errors.append(f"{project['name']}：特批推进必须填写审批依据")
            elif action == "defer":
                if _member_action(project) not in {"already_active", "already_special"}: errors.append(f"{project['name']}：当前不在推进中")
            elif action == "resume":
                if not member or member["member_status"] != "confirmed" or not cycle or cycle["status"] != "deferred": errors.append(f"{project['name']}：仅已暂缓的年度计划项目可恢复推进")
            elif action == "cancel":
                if not member or member["member_status"] != "confirmed" or member.get("member_kind") != "new" or not cycle or int(cycle["advancement_year"]) != year:
                    errors.append(f"{project['name']}：仅本年度已确认推进项目可取消推进")
        if errors:
            raise ValidationError("；".join(errors))
        now = _now()
        for project_id in project_ids:
            project, member = projects[project_id], members.get(project_id)
            is_special = _project_stage(project) == "未立项"
            if action in {"supplement", "special", "resume"}:
                conn.execute(
                    "INSERT INTO project_advancement_records (project_id,advancement_year,status,included_at,included_reason,included_by) VALUES (?,?, 'active',?,?,?)",
                    (project_id, year, now, reason, operator),
                )
                project_repo.update_project_status(conn, project_id, {
                    "library_implementation_view": "unimplemented" if is_special else "advancing",
                    "special_advancement_active": 1 if is_special else 0,
                    "advancement_year": year, "advancement_date": now, "updated_at": now,
                })
                event = "PROJECT_SPECIAL_INCLUDED_IN_ADVANCEMENT" if is_special else ("PROJECT_ADVANCEMENT_RESUMED" if action == "resume" else "PROJECT_INCLUDED_IN_ADVANCEMENT")
                _audit(conn, project_id, event, operator, reason, {"year": year, "source": "annual_plan_exception", "action": action})
                if member:
                    planned_amount = preferred(dict(member), "planned_new_amount") or (_hydrate_project_projection(conn, project)["effective_budget"] or "0")
                    conn.execute("UPDATE annual_advancement_draft_members SET member_status='confirmed',member_kind='new',planned_new_amount=?,planned_new_amount_decimal=?,confirmed_by=?,confirmed_at=?,removed_by='',removed_at=NULL,removal_reason='' WHERE id=?", (legacy_number(planned_amount), planned_amount, operator, now, member["id"]))
                else:
                    planned_amount = _hydrate_project_projection(conn, project)["effective_budget"] or "0"
                    conn.execute("INSERT INTO annual_advancement_draft_members (draft_id,project_id,member_status,added_by,planned_new_amount,planned_new_amount_decimal,member_kind,confirmed_by,confirmed_at) VALUES (?,?, 'confirmed',?,?,?,?,?,?)", (draft["id"], project_id, operator, legacy_number(planned_amount), planned_amount, "new", operator, now))
            elif action == "defer":
                active = _latest_cycle(conn, project_id, ("active",))
                assert active is not None
                conn.execute("UPDATE project_advancement_records SET status='deferred',ended_at=?,ended_reason=?,ended_by=? WHERE id=?", (now, reason, operator, active["id"]))
                project_repo.update_project_status(conn, project_id, {"library_implementation_view": "unimplemented", "special_advancement_active": 0, "updated_at": now})
                _audit(conn, project_id, "PROJECT_ADVANCEMENT_DEFERRED", operator, reason, {"year": year, "source": "annual_plan_exception"})
                if not member:
                    conn.execute("INSERT INTO annual_advancement_draft_members (draft_id,project_id,member_status,added_by,planned_new_amount,member_kind,confirmed_by,confirmed_at) VALUES (?,?, 'confirmed',?,?,?,?,?)", (draft["id"], project_id, operator, 0, "carryover", operator, now))
            else:  # cancel
                latest = _latest_cycle(conn, project_id)
                assert latest is not None
                conn.execute("UPDATE project_advancement_records SET status='cancelled',ended_at=?,ended_reason=?,ended_by=? WHERE id=?", (now, reason, operator, latest["id"]))
                project_repo.update_project_status(conn, project_id, {"library_implementation_view": "unimplemented", "special_advancement_active": 0, "advancement_year": None, "advancement_date": None, "updated_at": now})
                _audit(conn, project_id, "PROJECT_ADVANCEMENT_CANCELLED", operator, reason, {"year": year, "source": "annual_plan_exception"})
                conn.execute("UPDATE annual_advancement_draft_members SET member_status='removed',removed_by=?,removed_at=?,removal_reason=? WHERE id=?", (operator, now, reason, member["id"]))
            _event(conn, draft["id"], f"ANNUAL_PLAN_EXCEPTION_{action.upper()}", operator, project_id, reason, {"year": year, "action": action})
        conn.execute("UPDATE annual_advancement_drafts SET updated_at=? WHERE id=?", (now, draft["id"]))
    return get_annual_budget_plan(year)


def get_advancement_draft(year_value: object) -> dict:
    year = _year(year_value)
    with get_connection() as conn:
        draft = conn.execute("SELECT * FROM annual_advancement_drafts WHERE advancement_year=?", (year,)).fetchone()
        if not draft:
            return {
                "year": year, "members": [], "member_count": 0, "draft_count": 0, "confirmed_count": 0,
                "effective_budget_total": "0", "estimated_total": "0", "difference": "0", "over_expected": False,
                "arrangements": [],
            }
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM annual_advancement_draft_members WHERE draft_id=? AND member_status!='removed' ORDER BY id",
            (draft["id"],),
        ).fetchall()]
        members = [_member_projection(conn, row) for row in rows]
        arrangements = [dict(row) for row in conn.execute(
            "SELECT * FROM annual_funding_arrangements WHERE planning_year=? ORDER BY id DESC", (year,)
        ).fetchall()]
        estimated_total = total(preferred(item, "estimated_amount") for item in arrangements)
        effective_budget_total = total(item["effective_budget"] for item in members)
        return {
            "id": draft["id"], "year": year, "members": members, "member_count": len(members),
            "draft_count": sum(item["member_status"] == "draft" for item in members),
            "confirmed_count": sum(item["member_status"] == "confirmed" for item in members),
            "effective_budget_total": effective_budget_total, "estimated_total": estimated_total,
            "difference": difference(estimated_total, effective_budget_total), "over_expected": decimal_of(effective_budget_total) > decimal_of(estimated_total) if arrangements else False,
            "arrangements": arrangements,
        }


def add_draft_members(year_value: object, payload: dict) -> dict:
    year, operator = _year(year_value), _operator(payload)
    project_ids = list(dict.fromkeys(int(item) for item in payload.get("project_ids") or []))
    if not project_ids:
        raise ValidationError("请选择项目")
    with get_connection() as conn:
        draft = _draft(conn, year, operator)
        projects = project_repo.fetch_projects_by_ids(conn, project_ids)
        if len(projects) != len(project_ids):
            raise NotFoundError("项目不存在")
        invalid = [project["name"] for project in projects if _project_stage(project) in {"已完成", "已废弃"}]
        if invalid:
            raise ValidationError(f"已完成或已废弃项目不可加入草案：{'、'.join(invalid)}")
        for project in projects:
            existing = conn.execute(
                "SELECT id,member_status FROM annual_advancement_draft_members WHERE draft_id=? AND project_id=?",
                (draft["id"], project["id"]),
            ).fetchone()
            if existing and existing["member_status"] != "removed":
                continue
            if existing:
                conn.execute(
                    "UPDATE annual_advancement_draft_members SET member_status='draft',added_by=?,added_at=?,removed_by='',removed_at=NULL,removal_reason='' WHERE id=?",
                    (operator, _now(), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO annual_advancement_draft_members (draft_id,project_id,added_by) VALUES (?,?,?)",
                    (draft["id"], project["id"], operator),
                )
            _event(conn, draft["id"], "ADVANCEMENT_DRAFT_MEMBER_ADDED", operator, project["id"], payload={"year": year})
    return get_advancement_draft(year)


def remove_draft_member(year_value: object, project_id: int, payload: dict) -> dict:
    year, operator = _year(year_value), _operator(payload)
    with get_connection() as conn:
        draft = conn.execute("SELECT * FROM annual_advancement_drafts WHERE advancement_year=?", (year,)).fetchone()
        if not draft:
            raise NotFoundError("年度推进草案不存在")
        member = conn.execute(
            "SELECT * FROM annual_advancement_draft_members WHERE draft_id=? AND project_id=?", (draft["id"], project_id)
        ).fetchone()
        if not member or member["member_status"] != "draft":
            raise ValidationError("仅待确认草案成员可直接移出")
        conn.execute(
            "UPDATE annual_advancement_draft_members SET member_status='removed',removed_by=?,removed_at=? WHERE id=?",
            (operator, _now(), member["id"]),
        )
        _event(conn, draft["id"], "ADVANCEMENT_DRAFT_MEMBER_REMOVED", operator, project_id, payload={"year": year})
    return get_advancement_draft(year)


def confirm_advancement_draft(year_value: object, payload: dict) -> dict:
    year, operator = _year(year_value), _operator(payload)
    special_entries = {int(item.get("project_id") or 0): item for item in payload.get("special_entries") or []}
    with get_connection() as conn:
        draft = conn.execute("SELECT * FROM annual_advancement_drafts WHERE advancement_year=?", (year,)).fetchone()
        if not draft:
            raise NotFoundError("年度推进草案不存在")
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM annual_advancement_draft_members WHERE draft_id=? AND member_status='draft' ORDER BY id", (draft["id"],)
        ).fetchall()]
        if not rows:
            raise ValidationError("当前没有待确认的草案项目")
        projects = {row["id"]: row for row in project_repo.fetch_projects_by_ids(conn, [row["project_id"] for row in rows])}
        errors: list[str] = []
        actions: list[tuple[dict, dict, str]] = []
        for member in rows:
            project = projects.get(member["project_id"])
            if not project:
                errors.append(f"项目 {member['project_id']} 不存在")
                continue
            action = _member_action(project)
            if action == "terminal":
                errors.append(f"{project['name']}：已完成或已废弃，不能确认推进")
            elif action == "special":
                entry = special_entries.get(project["id"], {})
                if not str(entry.get("reason") or "").strip() or not str(entry.get("approval_basis") or "").strip():
                    errors.append(f"{project['name']}：特批推进必须填写理由和审批依据")
            actions.append((member, project, action))
        if errors:
            raise ValidationError("；".join(errors))
        now = _now()
        for member, project, action in actions:
            if action == "include":
                conn.execute(
                    "INSERT INTO project_advancement_records (project_id,advancement_year,status,included_at,included_reason,included_by) VALUES (?,?, 'active',?,?,?)",
                    (project["id"], year, now, "", operator),
                )
                project_repo.update_project_status(conn, project["id"], {"library_implementation_view": "advancing", "advancement_year": year, "advancement_date": now, "updated_at": now})
                _audit(conn, project["id"], "PROJECT_INCLUDED_IN_ADVANCEMENT", operator, "", {"year": year, "source": "annual_draft"})
            elif action == "special":
                entry = special_entries[project["id"]]
                reason, basis = str(entry["reason"]).strip(), str(entry["approval_basis"]).strip()
                conn.execute(
                    "INSERT INTO project_advancement_records (project_id,advancement_year,status,included_at,included_reason,included_by) VALUES (?,?, 'active',?,?,?)",
                    (project["id"], year, now, reason, operator),
                )
                project_repo.update_project_status(conn, project["id"], {"special_advancement_active": 1, "advancement_year": year, "advancement_date": now, "updated_at": now})
                _audit(conn, project["id"], "PROJECT_SPECIAL_INCLUDED_IN_ADVANCEMENT", operator, reason, {"year": year, "approval_basis": basis, "source": "annual_draft"})
            conn.execute(
                "UPDATE annual_advancement_draft_members SET member_status='confirmed',confirmed_by=?,confirmed_at=? WHERE id=?",
                (operator, now, member["id"]),
            )
            _event(conn, draft["id"], "ADVANCEMENT_DRAFT_MEMBER_CONFIRMED", operator, project["id"], payload={"year": year, "action": action})
        conn.execute("UPDATE annual_advancement_drafts SET updated_at=? WHERE id=?", (now, draft["id"]))
    return get_advancement_draft(year)


def defer_confirmed_draft_member(year_value: object, project_id: int, payload: dict) -> dict:
    year, operator = _year(year_value), _operator(payload)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValidationError("暂缓移出必须填写原因")
    with get_connection() as conn:
        draft = conn.execute("SELECT * FROM annual_advancement_drafts WHERE advancement_year=?", (year,)).fetchone()
        if not draft:
            raise NotFoundError("年度推进草案不存在")
        member = conn.execute(
            "SELECT * FROM annual_advancement_draft_members WHERE draft_id=? AND project_id=?", (draft["id"], project_id)
        ).fetchone()
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not member or member["member_status"] != "confirmed" or not project:
            raise ValidationError("仅已确认草案成员可暂缓移出")
        if _member_action(project) not in {"already_active", "already_special"}:
            raise ValidationError("当前项目不是可暂缓的推进项目")
        active = conn.execute(
            "SELECT id FROM project_advancement_records WHERE project_id=? AND status='active' ORDER BY id DESC LIMIT 1", (project_id,)
        ).fetchone()
        if not active:
            raise ValidationError("当前没有进行中的推进周期")
        now = _now()
        conn.execute("UPDATE project_advancement_records SET status='deferred',ended_at=?,ended_reason=?,ended_by=? WHERE id=?", (now, reason, operator, active["id"]))
        project_repo.update_project_status(conn, project_id, {
            "library_implementation_view": "unimplemented", "special_advancement_active": 0, "updated_at": now,
        })
        _audit(conn, project_id, "PROJECT_ADVANCEMENT_DEFERRED", operator, reason, {"source": "annual_draft", "year": year})
        conn.execute(
            "UPDATE annual_advancement_draft_members SET member_status='removed',removed_by=?,removed_at=?,removal_reason=? WHERE id=?",
            (operator, now, reason, member["id"]),
        )
        _event(conn, draft["id"], "ADVANCEMENT_DRAFT_CONFIRMED_MEMBER_DEFERRED", operator, project_id, reason, {"year": year})
    return get_advancement_draft(year)
