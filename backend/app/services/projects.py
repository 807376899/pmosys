from __future__ import annotations

import sqlite3
from contextlib import nullcontext
import json
import math
from datetime import date, datetime

from backend.app.core.errors import (
    DuplicateProjectCodeError,
    InvalidTransitionError,
    NotFoundError,
    StaleStateError,
    ValidationError,
)
from backend.app.core.config import get_settings
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo
from backend.app.repositories import workflow as workflow_repo
from backend.app.schemas.project import PATCHABLE_PROJECT_FIELDS, ProjectUpdate
from backend.app.services.project_codes import generate_project_code, validate_manual_project_code

_PROJECT_TYPE_ALIASES = {"teaching_software": "software", "practical_teaching_site": "laboratory"}
_PROCUREMENT_NATURES = {"goods", "service", "mixed"}
_WORK_ITEM_STATUSES = {"not_started", "in_progress", "paused", "not_applicable", "completed"}


def transition_allows_budget_adjustment(from_status: str, to_status: str) -> bool:
    return from_status == "submission_review" or to_status == "submission_review"


def create_project_internal(
    payload: dict,
    conn: sqlite3.Connection | None = None,
    *,
    allow_historical_project_code: bool = False,
) -> dict:
    with (nullcontext(conn) if conn is not None else get_connection()) as conn:
        assert conn is not None
        project_code = payload.get("project_code", "").strip()
        project_type = _PROJECT_TYPE_ALIASES.get(payload["project_type"], payload["project_type"])
        procurement_nature = str(payload.get("procurement_nature") or "").strip()
        if procurement_nature and procurement_nature not in _PROCUREMENT_NATURES:
            raise ValidationError("采购属性必须为 goods、service 或 mixed")
        if project_code:
            project_code = validate_manual_project_code(
                conn,
                project_code,
                project_type,
                allow_historical_year=allow_historical_project_code,
            )
            if project_repo.project_code_exists(conn, project_code):
                raise DuplicateProjectCodeError(f"项目编号已存在: {project_code}")
        else:
            project_code = generate_project_code(conn, project_type)
        project_id = project_repo.insert_project(
            conn,
            {
                **payload,
                "project_type": project_type,
                "procurement_nature": procurement_nature,
                "project_code": project_code,
                "current_status": payload.get("current_status", "draft"),
            },
        )
        project_repo.insert_status_history(
            conn,
            project_id=project_id,
            from_status=None,
            to_status=payload.get("current_status", "draft"),
            action="创建项目" if payload.get("current_status", "draft") == "draft" else "批量导入",
            operator=payload["operator"],
            comment="项目创建" if payload.get("current_status", "draft") == "draft" else "历史项目导入",
        )
        project = project_repo.fetch_project_by_id(conn, project_id)
        assert project is not None
        return project


def create_project(payload: dict) -> dict:
    return create_project_internal(payload)


def list_projects(filters: dict) -> dict:
    filters = {**filters, "department_order": list(get_settings().department_order)}
    with get_connection() as conn:
        items, total = project_repo.fetch_project_page(conn, filters)
        filter_options = project_repo.fetch_project_filter_options(conn, filters)
        for project in items:
            _hydrate_project_projection(conn, project, omit_legacy_status=True)
    return {
        "items": items,
        "total": total,
        "page": int(filters.get("page", 1)),
        "page_size": int(filters.get("page_size", 20)),
        "filter_options": filter_options,
    }


def _project_stage(project: dict) -> str:
    status = project.get("current_status")
    if status in {"draft", "under_review"}:
        return "未立项"
    if status in {"closed"}:
        return "已完成"
    if status in {"terminated"}:
        return "已废弃"
    if project.get("library_implementation_view") == "advancing":
        return "项目库—推进中"
    return "项目库—未实施"


def _external_constraint_projection(conn: sqlite3.Connection, project_id: int, project: dict) -> dict:
    rows = [dict(row) for row in conn.execute(
        "SELECT * FROM project_external_constraints WHERE project_id=? ORDER BY id DESC", (project_id,)
    ).fetchall()]
    confirmed = conn.execute(
        "SELECT * FROM project_external_constraint_scope_confirmations WHERE project_id=? ORDER BY id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    # Every recorded external constraint is a PMO-managed condition.  The
    # retired blocking flag remains only for database compatibility.
    open_rows = [row for row in rows if row.get("clearance_status") == "unresolved"]
    cleared = "false" if open_rows else "true"

    effective_budget = None
    for row in rows:
        if not row.get("is_effective_budget_source") or row.get("clearance_status") != "cleared":
            continue
        try:
            outcome = json.loads(row.get("outcome_json") or "{}")
        except json.JSONDecodeError:
            outcome = {}
        value = outcome.get("approved_budget")
        if isinstance(value, (int, float)):
            effective_budget = float(value)
            break
    if effective_budget is not None:
        source = "budget_constraint"
    elif project.get("approved_budget") is not None:
        effective_budget = float(project["approved_budget"])
        source = "historical_review"
    elif project.get("budget") is not None:
        effective_budget = float(project["budget"])
        source = "initial_budget"
    else:
        effective_budget = None
        source = "unrecorded"
    cells = [_constraint_cell_projection(conn, row) for row in rows]
    return {
        "external_constraints_cleared": cleared,
        "external_constraint_count": len(rows),
        "external_constraint_open_count": len(open_rows),
        "external_constraint_states": cells,
        "external_constraint_scope_confirmation": dict(confirmed) if confirmed else None,
        "effective_budget": effective_budget,
        "effective_budget_source": source,
    }


def _constraint_cell_projection(conn: sqlite3.Connection, constraint: dict) -> dict:
    latest = conn.execute(
        """SELECT content,created_at FROM external_constraint_progress_logs
           WHERE project_external_constraint_id=? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1""",
        (constraint["id"],),
    ).fetchone()
    outcome = _serialize_project_constraint(constraint).get("outcome_json") or {}
    return {
        "id": constraint["id"], "template_id": constraint.get("template_id"), "name": constraint["name"],
        "outcome_kind": _constraint_outcome_kind(constraint),
        "impact_scope": _constraint_impact_scope(constraint), "impact_note": constraint.get("impact_note") or "", "handling_status": constraint.get("handling_status"),
        "clearance_status": constraint.get("clearance_status"),
        "handling_started_on": constraint.get("handling_started_on"),
        "concluded_at": constraint.get("concluded_at"), "cleared_at": constraint.get("cleared_at"),
        "invalidated_at": constraint.get("invalidated_at"),
        "outcome_summary": str(outcome.get("result") or outcome.get("record_number") or ""),
        "latest_progress_summary": latest["content"] if latest else "",
        "latest_progress_at": latest["created_at"] if latest else None,
    }


def _hydrate_project_projection(conn: sqlite3.Connection, project: dict, *, omit_legacy_status: bool = False) -> dict:
    project["stage"] = _project_stage(project)
    advancement_status = "special_active" if project.get("special_advancement_active") else (
        "active" if project.get("library_implementation_view") == "advancing" else (
            "completed" if project["stage"] == "已完成" else "none"
        )
    )
    project["advancement"] = {
        "year": project.get("advancement_year"),
        "date": project.get("advancement_date"),
        "view": project.get("library_implementation_view") or "unimplemented",
        "status": advancement_status,
    }
    project["implementation_year"] = project.get("advancement_year") if project.get("stage") in {"项目库—推进中", "已完成"} else None
    project.update(_planned_advancement_projection(conn, project))
    project["has_completed_advancement_cycle"] = bool(conn.execute(
        "SELECT 1 FROM project_advancement_records WHERE project_id=? AND status='completed' LIMIT 1",
        (project["id"],),
    ).fetchone())
    work_items = _work_items_for_project(conn, project["id"])
    from backend.app.services.batches import current_batch_summaries_for_items
    batch_summaries = current_batch_summaries_for_items(conn, [item["id"] for item in work_items])
    for item in work_items:
        item["batch_summaries"] = batch_summaries.get(item["id"], [])
    project["work_item_summary"] = _work_item_summary(work_items)
    project["work_item_count"] = len(work_items)
    project["work_item_states"] = {item["name"]: item["status"] for item in work_items}
    project["work_item_column_states"] = [_work_item_column_projection(item) for item in work_items]
    active_items = _active_work_items(work_items)
    project["active_work_item_count"] = len(active_items)
    project["project_summary_display"] = _project_summary_display(conn, project)
    project.update(_external_constraint_projection(conn, project["id"], project))
    # Formal funding is independent of budgets and Stage; expose its factual
    # allocation projection alongside every list/detail project representation.
    from backend.app.services.funding import project_funding_projection
    project.update(project_funding_projection(conn, project["id"]))
    from backend.app.services.contracts import project_contract_projection
    project.update(project_contract_projection(conn, project["id"], include_contracts=not omit_legacy_status))
    if omit_legacy_status:
        project.pop("current_status", None)
    return project


def _work_items_for_project(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute(
        """SELECT wi.*,
                  (SELECT MAX(created_at) FROM work_item_progress_logs log
                   WHERE log.project_work_item_id=wi.id AND log.deleted_at IS NULL) AS last_progress_at,
                  (SELECT MIN(created_at) FROM work_item_progress_logs log
                   WHERE log.project_work_item_id=wi.id AND log.deleted_at IS NULL) AS first_progress_at,
                  (SELECT content FROM work_item_progress_logs log
                   WHERE log.project_work_item_id=wi.id AND log.deleted_at IS NULL
                   ORDER BY log.created_at DESC, log.id DESC LIMIT 1) AS latest_progress_summary
           FROM project_work_items wi WHERE wi.project_id=?""",
        (project_id,),
    ).fetchall()]


def _planned_advancement_projection(conn: sqlite3.Connection, project: dict) -> dict:
    if project.get("advancement_year") is not None:
        return {"planned_advancement_year": project["advancement_year"], "planned_advancement_status": "confirmed"}
    row = conn.execute(
        """SELECT d.advancement_year,m.member_status
           FROM annual_advancement_draft_members m
           JOIN annual_advancement_drafts d ON d.id=m.draft_id
           WHERE m.project_id=? AND m.member_status IN ('draft','confirmed')
           ORDER BY d.advancement_year ASC LIMIT 1""",
        (project["id"],),
    ).fetchone()
    return {
        "planned_advancement_year": row["advancement_year"] if row else None,
        "planned_advancement_status": row["member_status"] if row else None,
    }


def _detail_stage_events(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    mapping = {
        "established": ("established", "立项入项目库"),
        "closed": ("completed", "项目完成"),
        "terminated": ("abandoned", "项目废弃"),
    }
    events = []
    for row in project_repo.fetch_status_history(conn, project_id):
        mapped = mapping.get(row.get("to_status"))
        if not mapped:
            continue
        kind, label = mapped
        events.append({
            "id": row["id"], "kind": kind, "label": label,
            "occurred_at": row["transition_date"], "operator": row["operator"],
            "comment": row.get("comment") or "",
        })
    return events


def _work_item_order(item: dict) -> tuple:
    return (int(item.get("sequence_rank") or 1000), item["id"])


def _work_item_summary(items: list[dict]) -> list[dict]:
    selected = sorted(_active_work_items(items), key=_work_item_order)[:2]
    selected_ids = {item["id"] for item in selected}
    selected.extend(
        item for item in items
        if item.get("track_as_key_node")
        and item["id"] not in selected_ids
        and item.get("status") not in {"completed", "not_applicable"}
        and not item.get("cancelled_at")
        and not item.get("skipped_at")
    )
    return [_work_item_projection(item) for item in selected]


def _active_work_items(items: list[dict]) -> list[dict]:
    return [
        item for item in items
        if item.get("status") not in {"completed", "not_applicable"}
        and not item.get("cancelled_at") and not item.get("skipped_at")
    ]


def _work_item_projection(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "status": item["status"],
        "planned_date": item.get("planned_date") or "",
        "track_as_key_node": bool(item.get("track_as_key_node")),
        "last_progress_at": item.get("last_progress_at"),
        "last_activity_at": max(item.get("last_progress_at") or "", item.get("updated_at") or "") or None,
        "batch_summaries": item.get("batch_summaries") or [],
    }


def _work_item_column_projection(item: dict) -> dict:
    record = _serialize_work_item(item).get("completion_record_json") or {}
    return {
        "id": item["id"], "source_template_id": item.get("source_template_id"), "name": item["name"],
        "status": item["status"], "cancelled_at": item.get("cancelled_at"), "skipped_at": item.get("skipped_at"),
        "planned_date": item.get("planned_date") or "",
        "started_on": item.get("started_on"),
        "completed_on": record.get("completed_on") or (str(record.get("completed_at") or "")[:10] or None),
        "completion_result": record.get("result") or "", "completion_note": record.get("note") or "",
        "track_as_key_node": bool(item.get("track_as_key_node")),
        "actionable": not bool(item.get("cancelled_at")) and not bool(item.get("skipped_at")) and item["status"] not in {"completed", "paused", "not_applicable"},
        "batch_summaries": item.get("batch_summaries") or [],
    }


def _project_summary_display(conn: sqlite3.Connection, project: dict) -> str:
    row = conn.execute("SELECT name FROM project_types WHERE code=?", (project.get("project_type"),)).fetchone()
    name = row["name"] if row else "未分类"
    if project.get("project_type") == "software":
        nature = {"goods": "货物", "service": "服务", "mixed": "混合"}.get(project.get("procurement_nature"), "未设置")
        return f"{name} · {nature}"
    if project.get("project_type") == "laboratory":
        return f"{name} · {project.get('location') or '未设置'}"
    return name


def get_project(project_id: int) -> dict:
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            raise NotFoundError(f"项目不存在: {project_id}")
        detail = _hydrate_project_projection(conn, project)
        detail["stage_events"] = _detail_stage_events(conn, project_id)
        return detail


def update_project(project_id: int, payload: ProjectUpdate) -> dict:
    updates = payload.cleaned_updates()
    if not updates:
        raise ValidationError("没有可更新的字段")
    invalid = sorted(set(updates) - PATCHABLE_PROJECT_FIELDS)
    if invalid:
        raise ValidationError(f"不允许更新的字段: {', '.join(invalid)}")
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            raise NotFoundError(f"项目不存在: {project_id}")
        next_type = _PROJECT_TYPE_ALIASES.get(updates.get("project_type", project.get("project_type")), updates.get("project_type", project.get("project_type")))
        if "project_type" in updates:
            updates["project_type"] = next_type
        if next_type != "software":
            updates["procurement_nature"] = ""
        elif "procurement_nature" in updates and updates["procurement_nature"] and updates["procurement_nature"] not in _PROCUREMENT_NATURES:
            raise ValidationError("采购属性必须为 goods、service 或 mixed")
        if "project_type" in updates and project["project_code"]:
            updates["project_code"] = validate_manual_project_code(conn, project["project_code"], updates["project_type"])
        before = {field: project.get(field) for field in updates}
        project_repo.update_project_fields(conn, project_id, updates)
        _audit(conn, project_id, "PROJECT_UPDATED", payload.operator, payload.reason, {"before": before, "after": updates})
        updated = project_repo.fetch_project_by_id(conn, project_id)
        assert updated is not None
        return _hydrate_project_projection(conn, updated)


def delete_project(project_id: int, operator: str, reason: str) -> None:
    operator, reason = operator.strip(), reason.strip()
    if not operator or not reason:
        raise ValidationError("删除项目必须填写操作人和原因")
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            raise NotFoundError(f"项目不存在: {project_id}")
        project_repo.delete_project(conn, project_id, operator, reason)
        _audit(conn, project_id, "PROJECT_SOFT_DELETED", operator, reason, {"project_code": project["project_code"], "name": project["name"]})


def restore_project(project_id: int, operator: str, reason: str) -> dict:
    operator, reason = operator.strip(), reason.strip()
    if not operator or not reason:
        raise ValidationError("恢复项目必须填写操作人和原因")
    with get_connection() as conn:
        project = project_repo.fetch_project_any_by_id(conn, project_id)
        if not project:
            raise NotFoundError("项目不存在")
        if not project.get("deleted_at"):
            raise ValidationError("项目未处于移除状态")
        project_repo.restore_project(conn, project_id)
        _audit(conn, project_id, "PROJECT_RESTORED", operator, reason, {"project_code": project["project_code"], "name": project["name"]})
        restored = project_repo.fetch_project_by_id(conn, project_id)
        assert restored is not None
        return _hydrate_project_projection(conn, restored)


def get_project_history(project_id: int) -> list[dict]:
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            raise NotFoundError(f"项目不存在: {project_id}")
        return project_repo.fetch_status_history(conn, project_id)


def _ensure_transition_expected_state(project: dict, expected_status: str | None, expected_updated_at: str | None) -> None:
    if expected_status and project["current_status"] != expected_status:
        raise StaleStateError(
            f"项目状态已变化，当前状态为 {project['current_status']}",
        )
    if expected_updated_at and (project.get("status_updated_at") or "") != expected_updated_at:
        raise StaleStateError("项目状态更新时间已变化")


def _build_transition_options(projects: list[dict], force: bool, conn: sqlite3.Connection) -> list[dict]:
    if not projects:
        return []
    if force:
        statuses = workflow_repo.fetch_all_statuses(conn)
        return [
            {
                "to_status": item["status_code"],
                "status_name": item["status_name"],
                "requires_approval": True,
                "approver_roles": ["PMO"],
                "action_names": ["PMO特批强制变更"],
            }
            for item in statuses
        ]
    maps = []
    for status in sorted({item["current_status"] for item in projects}):
        option_map = {}
        for transition in workflow_repo.fetch_allowed_transitions(conn, status):
            option_map[transition["to_status"]] = {
                "to_status": transition["to_status"],
                "status_name": transition["to_status_name"] or transition["to_status"],
                "requires_approval": bool(transition["requires_approval"]),
                "approver_roles": {transition.get("approver_role") or ""},
                "action_names": {transition["action_name"]},
            }
        maps.append(option_map)
    common_targets = set(maps[0].keys())
    for item in maps[1:]:
        common_targets &= set(item.keys())
    merged = []
    for to_status in common_targets:
        requires_approval = False
        approver_roles: set[str] = set()
        action_names: set[str] = set()
        for option_map in maps:
            option = option_map[to_status]
            requires_approval = requires_approval or option["requires_approval"]
            approver_roles |= option["approver_roles"]
            action_names |= option["action_names"]
        merged.append(
            {
                "to_status": to_status,
                "status_name": maps[0][to_status]["status_name"],
                "requires_approval": requires_approval,
                "approver_roles": sorted(role for role in approver_roles if role),
                "action_names": sorted(action_names),
            }
        )
    return merged


def preview_batch_transition(payload: dict) -> dict:
    unique_ids = list(dict.fromkeys(payload["project_ids"]))
    with get_connection() as conn:
        projects = project_repo.fetch_projects_by_ids(conn, unique_ids)
        available_targets = _build_transition_options(projects, payload.get("force", False), conn)
        requested = next((item for item in available_targets if item["to_status"] == payload["to_status"]), None)
        conflicts = []
        project_map = {item["id"]: item for item in projects}
        for project_id in unique_ids:
            project = project_map.get(project_id)
            if not project:
                conflicts.append(
                    {
                        "project_id": project_id,
                        "project_code": "-",
                        "name": "-",
                        "code": "NOT_FOUND",
                        "message": f"项目不存在: {project_id}",
                    }
                )
                continue
            try:
                _ensure_transition_expected_state(
                    project,
                    (payload.get("expected_statuses") or {}).get(project_id),
                    (payload.get("expected_status_updated_at") or {}).get(project_id),
                )
                if payload.get("force") and payload.get("operator_role") != "PMO":
                    raise ValidationError("PMO 特批仅允许 PMO 角色使用", code="PMO_ROLE_REQUIRED")
                if not requested:
                    raise InvalidTransitionError(
                        f"这批项目没有共同合法目标状态: {payload['to_status']}",
                    )
            except Exception as exc:
                conflicts.append(
                    {
                        "project_id": project_id,
                        "project_code": project["project_code"],
                        "name": project["name"],
                        "code": getattr(exc, "code", "VALIDATION_ERROR"),
                        "message": str(exc),
                    }
                )
    return {
        "total": len(unique_ids),
        "project_ids": unique_ids,
        "available_targets": available_targets,
        "requested_target": requested,
        "requires_approval": bool(requested["requires_approval"]) if requested else False,
        "approved_budget_allowed": any(
            transition_allows_budget_adjustment(project["current_status"], payload["to_status"]) for project in projects
        ) if requested else False,
        "conflicts": conflicts,
    }


def transition_project(conn: sqlite3.Connection, project_id: int, payload: dict) -> dict:
    project = project_repo.fetch_project_by_id(conn, project_id)
    if not project:
        raise NotFoundError(f"项目不存在: {project_id}")
    _ensure_transition_expected_state(project, payload.get("expected_current_status"), payload.get("expected_status_updated_at"))
    from_status = project["current_status"]
    to_status = payload["to_status"]
    if from_status == to_status:
        raise InvalidTransitionError("目标状态不能与当前状态相同")
    approved_budget = payload.get("approved_budget")
    if approved_budget is not None and approved_budget < 0:
        raise ValidationError("审核后预算不能小于 0", code="NEGATIVE_APPROVED_BUDGET")
    if approved_budget is not None and not transition_allows_budget_adjustment(from_status, to_status):
        raise ValidationError(
            "仅在进入送审中或从送审中流转时允许调整审核后预算",
            code="APPROVED_BUDGET_NOT_ALLOWED",
        )
    if payload.get("force"):
        if payload.get("operator_role") != "PMO":
            raise ValidationError("PMO 特批仅允许 PMO 角色使用", code="PMO_ROLE_REQUIRED")
        status_exists = conn.execute(
            "SELECT 1 FROM status_definitions WHERE status_code = ? AND is_active = 1",
            (to_status,),
        ).fetchone()
        if not status_exists:
            raise InvalidTransitionError(f"目标状态不存在: {to_status}")
        action_name = "PMO特批强制变更"
        approver = payload.get("approver") or payload["operator"]
        comment = f"PMO特批: {payload['comment'].strip()}" if payload["comment"].strip() else "PMO特批"
        deliverable = payload.get("deliverable", "")
    else:
        rule = conn.execute(
            """
            SELECT * FROM transition_rules
            WHERE from_status = ? AND to_status = ? AND is_active = 1
            """,
            (from_status, to_status),
        ).fetchone()
        if not rule:
            raise InvalidTransitionError(f"不允许的流转: {from_status} -> {to_status}")
        if rule["requires_approval"] and not payload.get("approver"):
            raise ValidationError(
                f"该流转需要审批人，审批角色: {rule['approver_role']}",
                code="APPROVER_REQUIRED",
            )
        action_name = rule["action_name"]
        approver = payload.get("approver")
        comment = payload["comment"].strip()
        deliverable = payload.get("deliverable") or rule["required_deliverable"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates = {"current_status": to_status, "updated_at": now, "status_updated_at": now}
    if approved_budget is not None:
        updates["approved_budget"] = approved_budget
    if to_status == "implementing" and not project.get("actual_start_date"):
        updates["actual_start_date"] = now[:10]
    if to_status in {"closed", "terminated"} and not project.get("actual_end_date"):
        updates["actual_end_date"] = now[:10]
    project_repo.update_project_status(conn, project_id, updates)
    project_repo.insert_status_history(
        conn,
        project_id=project_id,
        from_status=from_status,
        to_status=to_status,
        action=action_name,
        operator=payload["operator"],
        approver=approver,
        comment=comment,
        deliverable=deliverable,
    )
    action_desc = "PMO特批" if payload.get("force") else action_name
    return {"success": True, "message": f"状态流转成功: {from_status} -> {to_status} ({action_desc})"}


def transition_project_by_id(project_id: int, payload: dict) -> dict:
    with get_connection() as conn:
        return transition_project(conn, project_id, payload)


def pmo_override_project(project_id: int, payload: dict) -> dict:
    comment = str(payload.get("comment") or "").strip()
    operator = str(payload.get("operator") or "").strip()
    if not operator or not comment:
        raise ValidationError("PMO 特批调整必须填写操作人和调整理由")
    result = transition_project_by_id(project_id, {
        "to_status": payload["to_status"], "operator": operator, "operator_role": "PMO",
        "approver": None, "comment": comment, "deliverable": "", "force": True,
        "approved_budget": None,
    })
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        assert project is not None
        if project["current_status"] == "submission_review":
            project_repo.update_project_fields(conn, project_id, {"library_implementation_view": "unimplemented"})
            project = project_repo.fetch_project_by_id(conn, project_id)
            assert project is not None
    return project


def complete_submission_review(project_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    budget = payload.get("approved_budget")
    if not operator or budget is None:
        raise ValidationError("送审结束必须填写操作人和审核预算")
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            raise NotFoundError(f"项目不存在: {project_id}")
        if project["current_status"] != "submission_review":
            raise InvalidTransitionError("仅送审中项目可登记审核预算")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        project_repo.update_project_status(conn, project_id, {"current_status": "established", "approved_budget": float(budget), "updated_at": now, "status_updated_at": now})
        project_repo.insert_status_history(conn, project_id=project_id, from_status="submission_review", to_status="established", action="送审结束，返回项目库", operator=operator, comment="已录入审核预算", deliverable="")
        updated = project_repo.fetch_project_by_id(conn, project_id)
    assert updated is not None
    return updated


_PROJECT_ACTIVITY_EVENTS = {
    "WORK_ITEM_UPDATED", "WORK_ITEM_CANCELLED", "WORK_ITEM_SKIPPED", "WORK_ITEM_COMPLETED",
    "WORK_ITEM_COMPLETION_CORRECTED", "WORK_ITEM_REOPENED", "WORK_ITEM_PROGRESS_RECORDED",
    "WORK_ITEM_PROGRESS_UPDATED", "WORK_ITEM_PROGRESS_DELETED", "EXTERNAL_CONSTRAINT_BEGIN",
    "EXTERNAL_CONSTRAINT_NEEDS_SUPPLEMENT", "EXTERNAL_CONSTRAINT_CONCLUDE", "EXTERNAL_CONSTRAINT_CLEAR", "EXTERNAL_CONSTRAINT_MARK_NOT_APPLICABLE",
    "EXTERNAL_CONSTRAINT_INVALIDATE", "EXTERNAL_CONSTRAINT_SET_EFFECTIVE_BUDGET_SOURCE",
    "EXTERNAL_CONSTRAINT_PROGRESS_RECORDED", "EXTERNAL_CONSTRAINT_PROGRESS_UPDATED",
    "EXTERNAL_CONSTRAINT_PROGRESS_DELETED",
    "CONTRACT_CREATED", "CONTRACT_UPDATED", "CONTRACT_STATUS_UPDATED", "CONTRACT_PROJECTS_UPDATED",
    "CONTRACT_PROGRESS_RECORDED", "CONTRACT_PROGRESS_UPDATED", "CONTRACT_PROGRESS_DELETED",
    "CONTRACT_ACCEPTANCE_RECORDED",
}


def _audit(conn, project_id: int, event_type: str, operator: str, reason: str = "", payload: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_events (project_id,event_type,operator,reason,payload_json) VALUES (?,?,?,?,?)", (project_id,event_type,operator,reason,json.dumps(payload or {}, ensure_ascii=False)))
    if event_type in _PROJECT_ACTIVITY_EVENTS:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE projects SET latest_activity_at=CASE WHEN latest_activity_at IS NULL OR latest_activity_at<? THEN ? ELSE latest_activity_at END WHERE id=?",
            (now, now, project_id),
        )


def create_external_constraint_template(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    operator = str(payload.get("operator") or "").strip()
    if not name or not operator:
        raise ValidationError("约束名称和操作人不能为空")
    scope_kind = str(payload.get("scope_kind") or "all")
    if scope_kind == "manual":
        scope_kind = "all"
    if scope_kind not in {"all", "project_type"}:
        raise ValidationError("外部约束模板的适用范围仅支持全部项目或项目分类")
    if scope_kind == "project_type" and not str(payload.get("scope_value") or "").strip():
        raise ValidationError("按项目分类适用时必须选择项目分类")
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO external_constraint_templates
            (name,recommended_stage,is_blocking,outcome_schema_json,project_field_effects_json,is_common,scope_kind,scope_value,effective_from,effective_until,applicability_basis,impact_scope,impact_note)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET recommended_stage=excluded.recommended_stage,
                is_blocking=excluded.is_blocking,outcome_schema_json=excluded.outcome_schema_json,
                project_field_effects_json=excluded.project_field_effects_json,is_common=excluded.is_common,
                scope_kind=excluded.scope_kind,scope_value=excluded.scope_value,
                effective_from=excluded.effective_from,effective_until=excluded.effective_until,
                applicability_basis=excluded.applicability_basis,
                impact_scope=excluded.impact_scope,impact_note=excluded.impact_note,
                archived_at=NULL,archived_by='',archived_reason=''""",
            (
                name,
                str(payload.get("recommended_stage") or ""),
                1,
                json.dumps({"kind": "text"}, ensure_ascii=False),
                json.dumps(payload.get("project_field_effects") or {}, ensure_ascii=False),
                int(bool(payload.get("is_common", True))),
                scope_kind,
                str(payload.get("scope_value") or ""),
                "", "", "",
                _normalise_constraint_impact_scope(payload.get("impact_scope")),
                _constraint_impact_note(payload),
            ),
        )
        row = conn.execute("SELECT * FROM external_constraint_templates WHERE name=?", (name,)).fetchone()
        assert row is not None
        return _serialize_constraint_template(dict(row))


def _serialize_constraint_template(template: dict) -> dict:
    result = dict(template)
    for field in ("outcome_schema_json", "project_field_effects_json"):
        try:
            result[field] = json.loads(result.get(field) or "{}")
        except json.JSONDecodeError:
            result[field] = {}
    return result


def _normalise_constraint_impact_scope(value: object) -> str:
    scope = str(value or "none")
    if scope not in {"none", "effective_budget", "other"}:
        raise ValidationError("约束影响范围无效")
    return scope


def _constraint_impact_note(payload: dict) -> str:
    scope = _normalise_constraint_impact_scope(payload.get("impact_scope"))
    note = str(payload.get("impact_note") or "").strip()
    if scope == "other" and not note:
        raise ValidationError("其他影响必须填写影响说明")
    return note


def _constraint_impact_scope(constraint: dict) -> str:
    direct = str(constraint.get("impact_scope") or "")
    if direct in {"none", "effective_budget", "other"}:
        return direct
    snapshot = constraint.get("template_snapshot_json") or {}
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError:
            snapshot = {}
    if isinstance(snapshot, dict):
        scope = str(snapshot.get("impact_scope") or "")
        if scope in {"none", "effective_budget", "other"}:
            return scope
        effects = snapshot.get("project_field_effects_json") or snapshot.get("project_field_effects") or {}
        if isinstance(effects, dict) and effects.get("effective_budget"):
            return "effective_budget"
    return "effective_budget" if constraint.get("is_effective_budget_source") else "none"


def list_external_constraint_templates(keyword: str = "", include_archived: bool = False) -> list[dict]:
    with get_connection() as conn:
        archived_filter = "" if include_archived else " AND archived_at IS NULL"
        rows = conn.execute(
            f"SELECT * FROM external_constraint_templates WHERE is_common=1{archived_filter} AND name LIKE ? ORDER BY name",
            (f"%{keyword.strip()}%",),
        ).fetchall()
        return [_serialize_constraint_template(dict(row)) for row in rows]


_TEMPLATE_TABLES = {
    "work_item": "work_item_templates",
    "work_package": "work_packages",
    "external_constraint": "external_constraint_templates",
}


def _template_table(kind: str) -> str:
    table = _TEMPLATE_TABLES.get(kind.replace("-", "_"))
    if not table:
        raise ValidationError("不支持的模板类型")
    return table


def archive_template(kind: str, template_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason:
        raise ValidationError("归档模板必须填写操作人和原因")
    table = _template_table(kind)
    with get_connection() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise NotFoundError("模板不存在")
        conn.execute(f"UPDATE {table} SET archived_at=?, archived_by=?, archived_reason=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), operator, reason, template_id))
        result = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        assert result is not None
        return _serialize_template_result(kind, dict(result))


def restore_template(kind: str, template_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("恢复模板必须填写操作人")
    table = _template_table(kind)
    with get_connection() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise NotFoundError("模板不存在")
        conn.execute(f"UPDATE {table} SET archived_at=NULL, archived_by='', archived_reason='' WHERE id=?", (template_id,))
        result = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        assert result is not None
        return _serialize_template_result(kind, dict(result))


def delete_template_permanently(kind: str, template_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason:
        raise ValidationError("永久删除模板必须填写操作人和原因")
    normalized = kind.replace("-", "_")
    table = _template_table(kind)
    with get_connection() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise NotFoundError("模板不存在")
        if normalized == "work_item":
            references = conn.execute("SELECT COUNT(*) FROM project_work_items WHERE source_template_id=?", (template_id,)).fetchone()[0]
        elif normalized == "external_constraint":
            references = conn.execute("SELECT COUNT(*) FROM project_external_constraints WHERE template_id=?", (template_id,)).fetchone()[0]
        else:
            references = conn.execute("SELECT COUNT(*) FROM audit_events WHERE payload_json LIKE ?", (f'%"package_id": {template_id}%',)).fetchone()[0]
        if references:
            raise ValidationError("模板已经产生业务引用，只能归档，不能永久删除")
        conn.execute(f"DELETE FROM {table} WHERE id=?", (template_id,))
        return {"success": True, "deleted_id": template_id}


def update_template(kind: str, template_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("编辑模板必须填写操作人")
    table = _template_table(kind)
    if kind == "work_package" and "items" in payload:
        with get_connection() as conn:
            current = _get_work_package(conn, template_id)
            name = str(payload.get("name") or current["name"]).strip()
            items = _normalise_package_items(payload.get("items") or [])
            if not name or not items:
                raise ValidationError("工作包名称和事项不能为空")
            constraints = payload.get("constraints", current.get("constraints") or [])
            duplicate = conn.execute("SELECT id FROM work_packages WHERE name=? AND id<>?", (name, template_id)).fetchone()
            if duplicate:
                raise ValidationError("工作包名称已存在")
            conn.execute("UPDATE work_packages SET name=?, constraints_json=? WHERE id=?", (name, json.dumps(constraints, ensure_ascii=False), template_id))
            conn.execute("DELETE FROM work_package_items WHERE package_id=?", (template_id,))
            for index, item in enumerate(items):
                conn.execute("INSERT INTO work_package_items (package_id,item_json,sort_order) VALUES (?,?,?)", (template_id, json.dumps(item, ensure_ascii=False), index))
            return _get_work_package(conn, template_id)
    allowed = {
        "work_item": {"name", "default_content", "recommended_stage", "is_common", "stage_view_priority"},
        "work_package": {"name", "constraints_json"},
        "external_constraint": {"name", "recommended_stage", "is_common", "scope_kind", "scope_value", "impact_scope", "impact_note"},
    }[kind]
    updates = {key: value for key, value in payload.items() if key in allowed}
    if not updates:
        raise ValidationError("没有可更新的模板字段")
    for key in ("completion_rule_json", "outcome_schema_json", "project_field_effects_json", "constraints_json"):
        if key in updates and not isinstance(updates[key], str):
            updates[key] = json.dumps(updates[key], ensure_ascii=False)
    with get_connection() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        if not row:
            raise NotFoundError("模板不存在")
        if kind == "external_constraint":
            scope_kind = str(updates.get("scope_kind", row["scope_kind"]) or "all")
            if scope_kind == "manual":
                scope_kind = "all"
                updates["scope_kind"] = scope_kind
            scope_value = str(updates.get("scope_value", row["scope_value"]) or "").strip()
            if scope_kind not in {"all", "project_type"}:
                raise ValidationError("外部约束模板的适用范围仅支持全部项目或项目分类")
            if scope_kind == "project_type" and not scope_value:
                raise ValidationError("按项目分类适用时必须选择项目分类")
            if "impact_scope" in updates:
                updates["impact_scope"] = _normalise_constraint_impact_scope(updates["impact_scope"])
            scope = _normalise_constraint_impact_scope(updates.get("impact_scope", row["impact_scope"]))
            note = str(updates.get("impact_note", row["impact_note"]) or "").strip()
            if scope == "other" and not note:
                raise ValidationError("其他影响必须填写影响说明")
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id=?", [*updates.values(), template_id])
        result = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        assert result is not None
        return _serialize_template_result(kind, dict(result))


def _serialize_template_result(kind: str, row: dict) -> dict:
    if kind == "external_constraint":
        return _serialize_constraint_template(row)
    if kind == "work_item":
        for field in ("flow_group", "sequence_rank", "execution_mode", "completion_rule_json"):
            row.pop(field, None)
    return row


def _normalise_package_items(items: list[dict]) -> list[dict]:
    """The package array is the only PMO-facing order."""
    result: list[dict] = []
    for item in items:
        entry = dict(item)
        for field in ("flow_group", "sequence_rank", "priority", "execution_mode", "completion_effects"):
            entry.pop(field, None)
        result.append(entry)
    return result


def _serialize_project_constraint(constraint: dict) -> dict:
    result = dict(constraint)
    for field in ("template_snapshot_json", "outcome_json"):
        try:
            result[field] = json.loads(result.get(field) or "{}")
        except json.JSONDecodeError:
            result[field] = {}
    return result


def _template_applies_to_project(template: dict, project: dict) -> bool:
    """Scope metadata is a PMO guardrail, never a date or stage inference engine."""
    if template.get("scope_kind") != "project_type":
        return True
    expected = _PROJECT_TYPE_ALIASES.get(str(template.get("scope_value") or ""), str(template.get("scope_value") or ""))
    actual = _PROJECT_TYPE_ALIASES.get(str(project.get("project_type") or ""), str(project.get("project_type") or ""))
    return bool(expected) and actual == expected


def _validate_constraint_scope(conn: sqlite3.Connection, project_id: int, template: dict | None) -> None:
    if not template:
        return
    project = project_repo.fetch_project_by_id(conn, project_id)
    if not project:
        raise NotFoundError("项目不存在")
    if not _template_applies_to_project(template, project):
        raise ValidationError(f"外部约束模板“{template['name']}”不适用于项目“{project['name']}”的项目分类")


def create_project_external_constraint(project_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        template = None
        if payload.get("template_id"):
            template = conn.execute("SELECT * FROM external_constraint_templates WHERE id=?", (payload["template_id"],)).fetchone()
            if not template:
                raise NotFoundError("外部约束模板不存在")
            template = _serialize_constraint_template(dict(template))
        _validate_constraint_scope(conn, project_id, template)
        name = str(payload.get("name") or (template or {}).get("name") or "").strip()
        if not name:
            raise ValidationError("外部约束名称不能为空")
        snapshot = template or {
            "name": name,
            "recommended_stage": payload.get("recommended_stage") or "",
            "impact_scope": _normalise_constraint_impact_scope(payload.get("impact_scope")),
            "impact_note": _constraint_impact_note(payload),
        }
        impact_scope = _normalise_constraint_impact_scope((template or {}).get("impact_scope") if template else payload.get("impact_scope"))
        impact_note = str((template or {}).get("impact_note", "") if template else payload.get("impact_note") or "").strip()
        if impact_scope == "other" and not impact_note:
            raise ValidationError("其他影响必须填写影响说明")
        snapshot = {**snapshot, "impact_scope": impact_scope, "impact_note": impact_note}
        handling_status = payload.get("handling_status") or "not_started"
        handling_started_on = date.today().isoformat() if handling_status == "in_progress" else None
        cursor = conn.execute(
            """INSERT INTO project_external_constraints
            (project_id,template_id,name,template_snapshot_json,is_blocking,primary_work_item_id,handling_status,handling_started_on,clearance_status,impact_scope,impact_note)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, payload.get("template_id"), name, json.dumps(snapshot, ensure_ascii=False), 1,
             payload.get("primary_work_item_id"), handling_status, handling_started_on, "unresolved", impact_scope, impact_note),
        )
        row = dict(conn.execute("SELECT * FROM project_external_constraints WHERE id=?", (cursor.lastrowid,)).fetchone())
        _audit(conn, project_id, "EXTERNAL_CONSTRAINT_CREATED", operator, payload={"constraint_id": row["id"], "name": name})
        return _serialize_project_constraint(row)


def get_project_external_constraints(project_id: int) -> list[dict]:
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        return [_serialize_project_constraint_with_progress(conn, dict(row)) for row in conn.execute(
            "SELECT * FROM project_external_constraints WHERE project_id=? ORDER BY id DESC", (project_id,)
        ).fetchall()]


def _serialize_project_constraint_with_progress(conn: sqlite3.Connection, row: dict) -> dict:
    result = _serialize_project_constraint(row)
    result["recent_progress_logs"] = get_external_constraint_progress_logs_for_connection(conn, row["project_id"], row["id"], limit=3)
    result["latest_progress_summary"] = result["recent_progress_logs"][0]["content"] if result["recent_progress_logs"] else ""
    return result


def batch_create_project_external_constraints(payload: dict) -> dict:
    project_ids = list(dict.fromkeys(payload.get("project_ids") or []))
    constraints = payload.get("constraints") or []
    operator = str(payload.get("operator") or "").strip()
    if not project_ids or not constraints or not operator:
        raise ValidationError("请选择项目、至少一个外部约束并填写操作人")
    # Saving as common is deliberate: it creates a reusable template first,
    # then each instance points at that immutable source instead of silently
    # creating unrelated temporary constraints.
    if payload.get("save_as_common"):
        common_by_name: dict[str, int] = {}
        prepared: list[dict] = []
        for constraint in constraints:
            item = dict(constraint)
            if not item.get("template_id"):
                name = str(item.get("name") or "").strip()
                if not name:
                    raise ValidationError("保存为常用约束时必须填写约束名称")
                template_id = common_by_name.get(name)
                if template_id is None:
                    template = create_external_constraint_template({
                        "name": name,
                        "operator": operator,
                        "recommended_stage": item.get("recommended_stage") or "",
                        "impact_scope": item.get("impact_scope"),
                        "impact_note": item.get("impact_note") or "",
                        "is_common": True,
                    })
                    template_id = int(template["id"])
                    common_by_name[name] = template_id
                item["template_id"] = template_id
            prepared.append(item)
        constraints = prepared
    with get_connection() as conn:
        for project_id in project_ids:
            for constraint in constraints:
                template = None
                if constraint.get("template_id"):
                    row = conn.execute("SELECT * FROM external_constraint_templates WHERE id=?", (constraint["template_id"],)).fetchone()
                    if not row:
                        raise NotFoundError("外部约束模板不存在")
                    template = _serialize_constraint_template(dict(row))
                _validate_constraint_scope(conn, project_id, template)
    count = 0
    for project_id in project_ids:
        for constraint in constraints:
            create_project_external_constraint(project_id, {**constraint, "operator": operator})
            count += 1
    return {"project_count": len(project_ids), "created_count": count}


def confirm_external_constraint_scope(project_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    note = str(payload.get("note") or "").strip()
    if not operator:
        raise ValidationError("确认人不能为空")
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "INSERT INTO project_external_constraint_scope_confirmations (project_id,confirmed_at,confirmed_by,note) VALUES (?,?,?,?)",
            (project_id, now, operator, note),
        )
        _audit(conn, project_id, "EXTERNAL_CONSTRAINT_SCOPE_CONFIRMED", operator, note, {"confirmation_id": cursor.lastrowid})
        return dict(conn.execute("SELECT * FROM project_external_constraint_scope_confirmations WHERE id=?", (cursor.lastrowid,)).fetchone())


def _constraint_outcome_kind(current: dict) -> str:
    snapshot = current.get("template_snapshot_json") or {}
    if isinstance(snapshot, str):
        try: snapshot = json.loads(snapshot)
        except json.JSONDecodeError: snapshot = {}
    schema = snapshot.get("outcome_schema_json") or snapshot.get("outcome_schema") or {}
    return str(schema.get("kind") or "custom") if isinstance(schema, dict) else "custom"


def _act_on_constraint(conn: sqlite3.Connection, project_id: int, constraint_id: int, payload: dict, *, batch_audit_id: int | None = None) -> dict:
    operator = str(payload.get("operator") or "").strip()
    action = str(payload.get("action") or "").strip()
    if not operator or action not in {"begin", "conclude", "clear", "mark_not_applicable", "invalidate", "set_effective_budget_source"}:
        raise ValidationError("请提供有效的约束办理动作和操作人")
    row = conn.execute("SELECT * FROM project_external_constraints WHERE id=? AND project_id=?", (constraint_id, project_id)).fetchone()
    if not row:
        raise NotFoundError("外部约束不存在")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current = dict(row)
    reason = str(payload.get("reason") or "").strip()
    updates: dict[str, object] = {"updated_at": now}
    if action == "begin":
        updates.update({"handling_status": "in_progress", "clearance_status": "unresolved"})
        if not current.get("handling_started_on"):
            updates["handling_started_on"] = now[:10]
    elif action == "conclude":
        outcome = payload.get("outcome") or {}
        if not isinstance(outcome, dict):
            raise ValidationError("结论内容格式不正确")
        make_source = bool(payload.get("set_effective_budget_source"))
        if make_source and (not bool(payload.get("cleared")) or not isinstance(outcome.get("approved_budget"), (int, float))):
            raise ValidationError("设为当前有效预算来源需要已解除阻断的核定金额")
        if make_source:
            conn.execute("UPDATE project_external_constraints SET is_effective_budget_source=0 WHERE project_id=?", (project_id,))
        updates.update({
            "handling_status": "concluded",
            "clearance_status": "cleared" if bool(payload.get("cleared")) else "unresolved",
            "outcome_json": json.dumps(outcome, ensure_ascii=False),
            "evidence_note": str(payload.get("evidence_note") or ""),
            "concluded_at": str(payload.get("concluded_on") or now[:10]),
            "concluded_by": operator,
            "is_effective_budget_source": int(make_source),
        })
    elif action == "clear":
        impact_scope = _constraint_impact_scope(current)
        result = str(payload.get("result") or "").strip()
        note = str(payload.get("note") or reason).strip()
        outcome = _serialize_project_constraint(current).get("outcome_json") or {}
        if result:
            outcome["result"] = result
        if note:
            outcome["note"] = note
        make_source = impact_scope == "effective_budget"
        if make_source:
            value = payload.get("effective_budget")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValidationError("影响有效预算的约束解除时必须填写有效预算")
            outcome["approved_budget"] = float(value)
            conn.execute("UPDATE project_external_constraints SET is_effective_budget_source=0 WHERE project_id=?", (project_id,))
        updates.update({
            "handling_status": "concluded", "clearance_status": "cleared", "cleared_at": now, "cleared_by": operator,
            "clearance_reason": note, "outcome_json": json.dumps(outcome, ensure_ascii=False),
            "concluded_at": now[:10], "concluded_by": operator, "is_effective_budget_source": int(make_source),
        })
    elif action == "mark_not_applicable":
        if not reason:
            raise ValidationError("标记不适用必须填写原因")
        updates.update({"handling_status": "not_started", "clearance_status": "not_applicable", "is_effective_budget_source": 0})
    elif action == "invalidate":
        if not reason:
            raise ValidationError("结论失效必须填写原因")
        updates.update({
            "handling_status": "invalidated", "clearance_status": "unresolved", "invalidated_at": now,
            "invalidated_by": operator, "invalidated_reason": reason, "is_effective_budget_source": 0,
        })
    else:
        try:
            outcome = json.loads(current.get("outcome_json") or "{}")
        except json.JSONDecodeError:
            outcome = {}
        if current.get("handling_status") != "concluded" or current.get("clearance_status") != "cleared" or not isinstance(outcome.get("approved_budget"), (int, float)):
            raise ValidationError("仅已解除的预算核定结论可设为当前有效预算来源")
        if not reason:
            raise ValidationError("切换当前有效预算来源必须填写原因")
        conn.execute("UPDATE project_external_constraints SET is_effective_budget_source=0 WHERE project_id=?", (project_id,))
        updates["is_effective_budget_source"] = 1
    assignments = ", ".join(f"{field}=?" for field in updates)
    conn.execute(f"UPDATE project_external_constraints SET {assignments} WHERE id=?", [*updates.values(), constraint_id])
    _audit(conn, project_id, f"EXTERNAL_CONSTRAINT_{action.upper()}", operator, reason, {
        "constraint_id": constraint_id, "batch_audit_id": batch_audit_id,
        "before": {"handling_status": current.get("handling_status"), "clearance_status": current.get("clearance_status"), "outcome_json": current.get("outcome_json"), "is_effective_budget_source": current.get("is_effective_budget_source")},
        "after": {**updates, "outcome": payload.get("outcome") if action == "conclude" else (json.loads(str(updates.get("outcome_json") or "{}")) if action == "clear" else None)},
    })
    result = conn.execute("SELECT * FROM project_external_constraints WHERE id=?", (constraint_id,)).fetchone()
    assert result is not None
    return _serialize_project_constraint_with_progress(conn, dict(result))


def act_on_project_external_constraint(project_id: int, constraint_id: int, payload: dict) -> dict:
    with get_connection() as conn:
        return _act_on_constraint(conn, project_id, constraint_id, payload)


def create_work_item(project_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator: raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id): raise NotFoundError("项目不存在")
        return _create_work_item(conn, project_id, payload, operator)


def _completion_rule(payload: dict) -> dict:
    return {"effects": {"create_milestone": False, "require_result": False, "result_type": "free_text", "result_options": [], "milestone_name": "", "require_business_record": False}}


def _create_work_item(conn: sqlite3.Connection, project_id: int, payload: dict, operator: str) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name: raise ValidationError("事项名称不能为空")
    rule = _completion_rule(payload)
    status = payload.get("status") or "not_started"
    if status not in _WORK_ITEM_STATUSES:
        raise ValidationError("事项状态无效")
    cursor = conn.execute(
        """INSERT INTO project_work_items
        (project_id,name,status,track_as_key_node,completion_rule_snapshot,execution_mode,assignee,planned_date,priority,note,source_template_id,content,flow_group,sequence_rank,started_on)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (project_id, name, status, int(bool(payload.get("track_as_key_node"))),
         json.dumps(rule, ensure_ascii=False), "tracking", payload.get("assignee") or "",
         payload.get("planned_date") or "", "normal", payload.get("note") or "", payload.get("source_template_id"), payload.get("content") or "", "main", _next_sequence_rank(conn, project_id, payload), date.today().isoformat() if status == "in_progress" else None),
    )
    item = _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (cursor.lastrowid,)).fetchone()))
    _audit(conn, project_id, "WORK_ITEM_CREATED", operator, payload={"work_item_id": item["id"], "name": name})
    return item


def _next_sequence_rank(conn: sqlite3.Connection, project_id: int, payload: dict) -> int:
    after_id = payload.get("insert_after_id")
    if after_id:
        before = conn.execute("SELECT sequence_rank FROM project_work_items WHERE id=? AND project_id=?", (after_id, project_id)).fetchone()
        if before:
            following = conn.execute("SELECT sequence_rank FROM project_work_items WHERE project_id=? AND sequence_rank>? ORDER BY sequence_rank,id LIMIT 1", (project_id, before["sequence_rank"])).fetchone()
            if following and following["sequence_rank"] - before["sequence_rank"] > 1:
                return (before["sequence_rank"] + following["sequence_rank"]) // 2
            if not following:
                return int(before["sequence_rank"]) + 100
            _renumber_work_items(conn, project_id)
            return _next_sequence_rank(conn, project_id, payload)
    latest = conn.execute("SELECT MAX(sequence_rank) AS rank FROM project_work_items WHERE project_id=?", (project_id,)).fetchone()
    return int(latest["rank"] or 0) + 100


def _renumber_work_items(conn: sqlite3.Connection, project_id: int) -> None:
    rows = conn.execute("SELECT id FROM project_work_items WHERE project_id=? ORDER BY sequence_rank,id", (project_id,)).fetchall()
    for index, row in enumerate(rows, start=1):
        conn.execute("UPDATE project_work_items SET sequence_rank=? WHERE id=?", (index * 100, row["id"]))


def reorder_work_items(project_id: int, payload: dict) -> list[dict]:
    operator = str(payload.get("operator") or "").strip()
    item_ids = [int(item_id) for item_id in payload.get("item_ids") or []]
    if not operator or not item_ids:
        raise ValidationError("操作人和事项顺序不能为空")
    if len(item_ids) != len(set(item_ids)):
        raise ValidationError("事项不能重复")
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id FROM project_work_items WHERE project_id=? AND id IN ({','.join('?' for _ in item_ids)})",
            [project_id, *item_ids],
        ).fetchall()
        if {row["id"] for row in rows} != set(item_ids):
            raise ValidationError("只能重排当前项目的事项")
        for index, item_id in enumerate(item_ids, start=1):
            conn.execute("UPDATE project_work_items SET flow_group='main',sequence_rank=?,updated_at=? WHERE id=?", (index * 100, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item_id))
        _audit(conn, project_id, "WORK_ITEM_REORDERED", operator, payload={"item_ids": item_ids})
        items = [dict(row) for row in conn.execute("SELECT * FROM project_work_items WHERE project_id=?", (project_id,)).fetchall()]
        return [_serialize_work_item(item) for item in sorted(items, key=_work_item_order)]


def _serialize_work_item(item: dict) -> dict:
    item = dict(item)
    for field in ("completion_rule_snapshot", "completion_record_json"):
        if isinstance(item.get(field), str):
            try:
                item[field] = json.loads(item[field])
            except json.JSONDecodeError:
                pass
    item.pop("flow_group", None)
    item.pop("sequence_rank", None)
    item.pop("priority", None)
    item.pop("execution_mode", None)
    completion = item.get("completion_record_json") or {}
    activity_candidates = [
        item.get("started_on"), item.get("first_progress_at"),
        completion.get("completed_on") if isinstance(completion, dict) else None,
        str(completion.get("completed_at") or "")[:10] if isinstance(completion, dict) else None,
        item.get("created_at"),
    ]
    item["first_activity_at"] = min(value for value in activity_candidates if value) if any(activity_candidates) else None
    return item


def update_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator: raise ValidationError("操作人不能为空")
    allowed = {"name", "content", "status", "track_as_key_node", "assignee", "planned_date", "started_on", "note"}
    updates = {key: value for key, value in payload.items() if key in allowed}
    if not updates: raise ValidationError("没有可更新的事项字段")
    if "status" in updates and updates["status"] not in _WORK_ITEM_STATUSES: raise ValidationError("事项状态无效")
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
        if updates.get("status") == "in_progress" and not item["started_on"]:
            updates["started_on"] = date.today().isoformat()
        updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        assignments = ", ".join(f"{field}=?" for field in updates)
        conn.execute(f"UPDATE project_work_items SET {assignments} WHERE id=?", [*updates.values(), item_id])
        _audit(conn, project_id, "WORK_ITEM_UPDATED", operator, payload={"work_item_id": item_id, "fields": list(updates)})
        return _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (item_id,)).fetchone()))


def quick_update_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    """Save item fields and an optional progress entry atomically."""
    operator = str(payload.get("operator") or "").strip()
    progress_content = str(payload.get("progress_content") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    updates = {key: value for key, value in payload.items() if key in {"status", "track_as_key_node", "planned_date", "started_on"}}
    if not updates and not progress_content:
        raise ValidationError("请至少保存事项变更或进展记录")
    if "status" in updates and updates["status"] not in _WORK_ITEM_STATUSES: raise ValidationError("事项状态无效")
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item:
            raise NotFoundError("事项不存在")
        if updates:
            if updates.get("status") == "in_progress" and not item["started_on"]:
                updates["started_on"] = date.today().isoformat()
            updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            assignments = ", ".join(f"{field}=?" for field in updates)
            conn.execute(f"UPDATE project_work_items SET {assignments} WHERE id=?", [*updates.values(), item_id])
            _audit(conn, project_id, "WORK_ITEM_UPDATED", operator, payload={"work_item_id": item_id, "fields": list(updates)})
        log = None
        if progress_content:
            cursor = conn.execute(
                "INSERT INTO work_item_progress_logs (project_work_item_id,content,operator,is_timeline_highlight) VALUES (?,?,?,0)",
                (item_id, progress_content, operator),
            )
            log = dict(conn.execute("SELECT * FROM work_item_progress_logs WHERE id=?", (cursor.lastrowid,)).fetchone())
            _audit(conn, project_id, "WORK_ITEM_PROGRESS_RECORDED", operator, payload={"work_item_id": item_id, "progress_log_id": log["id"], "highlight": bool(log["is_timeline_highlight"])})
        updated = _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (item_id,)).fetchone()))
        return {"work_item": updated, "progress_log": log}


def cancel_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason: raise ValidationError("取消事项必须填写操作人和原因")
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE project_work_items SET cancelled_at=?,cancelled_reason=?,cancelled_by=?,updated_at=? WHERE id=?", (now, reason, operator, now, item_id))
        _audit(conn, project_id, "WORK_ITEM_CANCELLED", operator, reason, {"work_item_id": item_id})
        return _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (item_id,)).fetchone()))


def skip_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason: raise ValidationError("跳过事项必须填写操作人和原因")
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE project_work_items SET skipped_at=?,skipped_reason=?,updated_at=? WHERE id=?", (now, reason, now, item_id))
        _audit(conn, project_id, "WORK_ITEM_SKIPPED", operator, reason, {"work_item_id": item_id})
        return _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (item_id,)).fetchone()))


def batch_create_work_items(payload: dict) -> dict:
    project_ids = list(dict.fromkeys(payload.get("project_ids") or []))
    operator = str(payload.get("operator") or "").strip()
    items = payload.get("items") or []
    if not project_ids or not operator or not items: raise ValidationError("请选择项目、填写操作人并至少添加一项事项")
    created_count = 0
    with get_connection() as conn:
        for project_id in project_ids:
            if not project_repo.fetch_project_by_id(conn, project_id): raise NotFoundError(f"项目不存在: {project_id}")
        anchors: dict[int, int | None] = {}
        for project_id in project_ids:
            current = next(iter(sorted(_active_work_items(_work_items_for_project(conn, project_id)), key=_work_item_order)), None)
            anchors[project_id] = current["id"] if current else None
        for item_payload in items:
            insert_mode = str(item_payload.get("insert_mode") or payload.get("insert_mode") or "last")
            for project_id in project_ids:
                draft = dict(item_payload)
                if insert_mode == "after_current" and anchors[project_id]:
                    draft["insert_after_id"] = anchors[project_id]
                created = _create_work_item(conn, project_id, draft, operator)
                if insert_mode == "after_current":
                    anchors[project_id] = created["id"]
                created_count += 1
            if item_payload.get("save_as_common", payload.get("save_as_common", False)):
                _save_work_item_template(conn, item_payload)
        package_name = str(payload.get("save_as_package_name") or "").strip()
        package = _save_work_package(conn, package_name, items) if package_name else None
    return {"created_count": created_count, "project_count": len(project_ids), "package": package}


def _batch_work_item_values(payload: dict, project_id: int) -> dict:
    return dict(payload.get("defaults") or {})


def _batch_work_item_error_message(ineligible: list[dict]) -> str:
    details = "；".join(f"{item.get('name') or ('项目 ' + str(item.get('project_id')))}：{item['message']}" for item in ineligible)
    return f"以下项目无法批量办理：{details}"


def _batch_work_item_preflight(conn: sqlite3.Connection, payload: dict, *, validate_values: bool = False) -> dict:
    action = str(payload.get("action") or "").strip()
    targets = payload.get("targets") or []
    if action not in {"progress", "update", "complete"} or not isinstance(targets, list) or not targets:
        raise ValidationError("请选择事项实例并提供有效的批量办理动作")
    eligible, ineligible, seen_projects = [], [], set()
    for target in targets:
        project_id, item_id = int(target.get("project_id") or 0), int(target.get("work_item_id") or 0)
        if not project_id or not item_id or project_id in seen_projects:
            ineligible.append({"project_id": project_id, "message": "事项目标无效或项目重复"})
            continue
        seen_projects.add(project_id)
        project = project_repo.fetch_project_by_id(conn, project_id)
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not project or not item:
            ineligible.append({"project_id": project_id, "message": "项目或事项实例不存在"})
            continue
        item = dict(item)
        if item.get("cancelled_at"):
            ineligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "message": "事项已取消"})
            continue
        if item["status"] in {"completed", "not_applicable"}:
            ineligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "message": "事项已完成或不适用，请单项目重开后再办理"})
            continue
        values = _batch_work_item_values(payload, project_id)
        validate_submitted_values = validate_values or bool(payload.get("defaults"))
        if validate_submitted_values and action == "progress" and not str(values.get("progress_content") or "").strip():
            ineligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "message": "请填写进展内容"})
            continue
        if validate_submitted_values and action == "update" and not any(key in values and values[key] not in {None, ""} for key in {"status", "planned_date", "track_as_key_node"}):
            ineligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "message": "请至少填写一项事项设置"})
            continue
        if validate_submitted_values and action == "complete":
            rule = _serialize_work_item(item).get("completion_rule_snapshot") or {}
            if (rule.get("effects") or {}).get("require_result") and not str(values.get("result") or "").strip():
                ineligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "message": "该事项完成时必须填写结果"})
                continue
        eligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "work_item_id": item_id, "status": item["status"]})
    return {"action": action, "eligible": eligible, "ineligible": ineligible}


def preview_batch_work_item_action(payload: dict) -> dict:
    with get_connection() as conn:
        return _batch_work_item_preflight(conn, payload)


def execute_batch_work_item_action(payload: dict) -> dict:
    operator, action = str(payload.get("operator") or "").strip(), str(payload.get("action") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        preview = _batch_work_item_preflight(conn, payload, validate_values=True)
        if preview["ineligible"]:
            raise ValidationError(_batch_work_item_error_message(preview["ineligible"]))
        if not preview["eligible"]:
            raise ValidationError("没有可执行的事项")
        cursor = conn.execute("INSERT INTO work_item_batch_operations (action,operator,payload_json) VALUES (?,?,?)", (action, operator, json.dumps({"targets": payload.get("targets"), "defaults": payload.get("defaults")}, ensure_ascii=False)))
        batch_audit_id = cursor.lastrowid
        processed_targets = []
        for target in preview["eligible"]:
            item_id, project_id = target["work_item_id"], target["project_id"]
            values = _batch_work_item_values(payload, project_id)
            if action == "progress":
                content = str(values.get("progress_content") or "").strip()
                if not content:
                    raise ValidationError("批量记录进展必须填写内容")
                log = conn.execute("INSERT INTO work_item_progress_logs (project_work_item_id,content,operator,is_timeline_highlight) VALUES (?,?,?,0)", (item_id, content, operator)).lastrowid
                _audit(conn, project_id, "WORK_ITEM_PROGRESS_RECORDED", operator, payload={"work_item_id": item_id, "progress_log_id": log, "batch_audit_id": batch_audit_id})
            elif action == "update":
                updates = {key: values[key] for key in {"status", "planned_date", "started_on", "track_as_key_node"} if key in values}
                if not updates:
                    raise ValidationError("批量修改至少需要一个事项设置")
                item = conn.execute("SELECT started_on FROM project_work_items WHERE id=?", (item_id,)).fetchone()
                if updates.get("status") == "in_progress" and item and not item["started_on"]:
                    updates["started_on"] = date.today().isoformat()
                updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(f"UPDATE project_work_items SET {', '.join(f'{key}=?' for key in updates)} WHERE id=?", [*updates.values(), item_id])
                _audit(conn, project_id, "WORK_ITEM_UPDATED", operator, payload={"work_item_id": item_id, "fields": list(updates), "batch_audit_id": batch_audit_id})
            else:
                item = dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (item_id,)).fetchone())
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                completed_on = str(values.get("completed_on") or now[:10])
                record = {"result": values.get("result", ""), "operator": operator, "completed_at": now, "completed_on": completed_on, "note": values.get("note", ""), "create_milestone": False}
                conn.execute("UPDATE project_work_items SET status='completed',completion_record_json=?,updated_at=? WHERE id=?", (json.dumps(record, ensure_ascii=False), now, item_id))
                _audit(conn, project_id, "WORK_ITEM_COMPLETED", operator, payload={"work_item_id": item_id, "record": record, "batch_audit_id": batch_audit_id})
            processed_targets.append({"project_id": project_id, "work_item_id": item_id})
        return {"success": True, "processed_count": len(processed_targets), "processed_targets": processed_targets, "batch_audit_id": batch_audit_id}


def _save_work_item_template(conn: sqlite3.Connection, payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    rule = _completion_rule(payload)
    conn.execute("INSERT OR IGNORE INTO work_item_templates (name,default_content,recommended_stage,execution_mode,completion_rule_json,is_common,flow_group,sequence_rank) VALUES (?,?,?,?,?,1,?,?)", (name, payload.get("content") or payload.get("default_content") or "", payload.get("recommended_stage") or "", "tracking", json.dumps(rule, ensure_ascii=False), "main", 1000))
    return _serialize_template_result("work_item", dict(conn.execute("SELECT * FROM work_item_templates WHERE name=?", (name,)).fetchone()))


def create_work_item_template(payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("创建常用事项必须填写操作人")
    with get_connection() as conn:
        return _save_work_item_template(conn, payload)


def list_work_item_templates(include_archived: bool = False) -> list[dict]:
    with get_connection() as conn:
        archived_filter = "" if include_archived else " AND archived_at IS NULL"
        return [_serialize_template_result("work_item", dict(row)) for row in conn.execute(f"SELECT * FROM work_item_templates WHERE is_common=1{archived_filter} ORDER BY name").fetchall()]


def _save_work_package(conn: sqlite3.Connection, name: str, items: list[dict], constraints: list[dict] | None = None) -> dict | None:
    if not name: return None
    conn.execute("INSERT OR IGNORE INTO work_packages (name) VALUES (?)", (name,))
    package = dict(conn.execute("SELECT * FROM work_packages WHERE name=?", (name,)).fetchone())
    conn.execute("UPDATE work_packages SET constraints_json=? WHERE id=?", (json.dumps(constraints or [], ensure_ascii=False), package["id"]))
    conn.execute("DELETE FROM work_package_items WHERE package_id=?", (package["id"],))
    for index, item in enumerate(_normalise_package_items(items)):
        conn.execute("INSERT INTO work_package_items (package_id,item_json,sort_order) VALUES (?,?,?)", (package["id"], json.dumps(item, ensure_ascii=False), index))
    return _get_work_package(conn, package["id"])


def create_work_package(payload: dict) -> dict:
    name, operator = str(payload.get("name") or "").strip(), str(payload.get("operator") or "").strip()
    if not name or not operator or not payload.get("items"): raise ValidationError("工作包名称、操作人和事项不能为空")
    with get_connection() as conn:
        return _save_work_package(conn, name, payload["items"], payload.get("constraints") or [])


def _get_work_package(conn: sqlite3.Connection, package_id: int) -> dict:
    package = conn.execute("SELECT * FROM work_packages WHERE id=?", (package_id,)).fetchone()
    if not package: raise NotFoundError("工作包不存在")
    result = dict(package)
    result["items"] = [json.loads(row["item_json"]) for row in conn.execute("SELECT item_json FROM work_package_items WHERE package_id=? ORDER BY sort_order", (package_id,)).fetchall()]
    try:
        result["constraints"] = json.loads(result.get("constraints_json") or "[]")
    except json.JSONDecodeError:
        result["constraints"] = []
    return result


def list_work_packages(include_archived: bool = False) -> list[dict]:
    with get_connection() as conn:
        archived_filter = "" if include_archived else " WHERE archived_at IS NULL"
        ids = [row["id"] for row in conn.execute(f"SELECT id FROM work_packages{archived_filter} ORDER BY name").fetchall()]
        return [_get_work_package(conn, package_id) for package_id in ids]


def apply_work_package(payload: dict) -> dict:
    project_ids = list(dict.fromkeys(payload.get("project_ids") or []))
    operator = str(payload.get("operator") or "").strip()
    if not project_ids or not operator: raise ValidationError("请选择项目并填写操作人")
    with get_connection() as conn:
        package = _get_work_package(conn, int(payload.get("package_id") or 0))
    result = batch_create_work_items({"project_ids": project_ids, "operator": operator, "items": package["items"]})
    constraint_created_count = 0
    for project_id in project_ids:
        for constraint in package.get("constraints") or []:
            create_project_external_constraint(project_id, {**constraint, "operator": operator})
            constraint_created_count += 1
    return {**result, "constraint_created_count": constraint_created_count}


def batch_include_in_advancement(payload: dict) -> dict:
    project_ids = list(dict.fromkeys(payload.get("project_ids") or []))
    if not project_ids:
        raise ValidationError("请选择项目")
    with get_connection() as conn:
        projects = project_repo.fetch_projects_by_ids(conn, project_ids)
        if len(projects) != len(project_ids):
            raise NotFoundError("项目不存在")
        invalid = [project["name"] for project in projects if _project_stage(project) != "项目库—未实施"]
        if invalid:
            raise ValidationError(f"仅项目库—未实施项目可纳入推进：{'、'.join(invalid)}")
    success = 0
    for project_id in project_ids:
        include_in_advancement(project_id, payload)
        success += 1
    return {"total": len(project_ids), "success": success}


def batch_defer_advancement(payload: dict) -> dict:
    project_ids = list(dict.fromkeys(payload.get("project_ids") or []))
    if not project_ids:
        raise ValidationError("请选择项目")
    with get_connection() as conn:
        projects = project_repo.fetch_projects_by_ids(conn, project_ids)
        if len(projects) != len(project_ids):
            raise NotFoundError("项目不存在")
        invalid = [project["name"] for project in projects if project.get("library_implementation_view") != "advancing" and not project.get("special_advancement_active")]
        if invalid:
            raise ValidationError(f"仅推进中或特批推进中项目可暂缓推进：{'、'.join(invalid)}")
    for project_id in project_ids:
        defer_advancement(project_id, payload)
    return {"total": len(project_ids), "success": len(project_ids)}


def batch_backfill_completed_advancement(payload: dict) -> dict:
    project_ids = list(dict.fromkeys(payload.get("project_ids") or []))
    operator = str(payload.get("operator") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    year = int(payload.get("advancement_year") or 0)
    if not project_ids:
        raise ValidationError("请选择已完成项目")
    if not operator or not reason:
        raise ValidationError("补录历史实施必须填写操作人和理由")
    if not 1900 <= year <= date.today().year:
        raise ValidationError("实施年份必须在 1900 至当前年份之间")
    with get_connection() as conn:
        projects = project_repo.fetch_projects_by_ids(conn, project_ids)
        if len(projects) != len(project_ids):
            raise NotFoundError("项目不存在")
        completed_cycle_ids = {
            row["project_id"]
            for row in conn.execute(
                f"SELECT project_id FROM project_advancement_records WHERE status='completed' AND project_id IN ({','.join('?' for _ in project_ids)})",
                project_ids,
            ).fetchall()
        }
        invalid = [
            project["name"]
            for project in projects
            if _project_stage(project) != "已完成" or (project.get("advancement_year") and project["id"] in completed_cycle_ids)
        ]
        if invalid:
            raise ValidationError(f"仅缺少历史实施记录的已完成项目可补录：{'、'.join(invalid)}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for project in projects:
            cycle = conn.execute(
                "SELECT id FROM project_advancement_records WHERE project_id=? AND status='completed' ORDER BY id DESC LIMIT 1",
                (project["id"],),
            ).fetchone()
            if cycle:
                conn.execute("UPDATE project_advancement_records SET advancement_year=? WHERE id=?", (year, cycle["id"]))
            else:
                conn.execute(
                    """INSERT INTO project_advancement_records
                    (project_id,advancement_year,status,included_at,included_reason,included_by,ended_at,ended_reason,ended_by)
                    VALUES (?,?, 'completed',?,?,?,?,?,?)""",
                    (project["id"], year, now, reason, operator, now, reason, operator),
                )
            updates = {"advancement_year": year, "advancement_date": now, "updated_at": now}
            if payload.get("clear_zero_budget") and project.get("budget") == 0:
                updates["budget"] = None
            project_repo.update_project_status(conn, project["id"], updates)
            _audit(conn, project["id"], "PROJECT_COMPLETED_ADVANCEMENT_BACKFILLED", operator, reason, {
                "advancement_year": year,
                "cleared_zero_budget": "budget" in updates,
            })
    return {"total": len(project_ids), "success": len(project_ids)}


def complete_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator=str(payload.get("operator") or "").strip()
    if not operator: raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        item=conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        completed_on = str(payload.get("completed_on") or now[:10])
        record={"result":payload.get("result", ""),"operator":operator,"completed_at":now,"completed_on":completed_on,"note":payload.get("note", ""),"create_milestone":False}
        conn.execute("UPDATE project_work_items SET status='completed',completion_record_json=?,updated_at=? WHERE id=?",(json.dumps(record,ensure_ascii=False),now,item_id)); _audit(conn,project_id,"WORK_ITEM_COMPLETED",operator,payload={"work_item_id":item_id,"record":record})
        return _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?",(item_id,)).fetchone()))


def correct_work_item_completion(project_id: int, item_id: int, payload: dict) -> dict:
    """Correct a completed fact without reopening the underlying Work Item."""
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not row:
            raise NotFoundError("事项不存在")
        item = _serialize_work_item(dict(row))
        if item.get("status") != "completed":
            raise ValidationError("仅已完成事项可更正完成信息")
        before = item.get("completion_record_json") or {}
        if not isinstance(before, dict):
            before = {}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        after = {
            **before,
            "result": str(payload.get("result") if "result" in payload else before.get("result") or ""),
            "note": str(payload.get("note") if "note" in payload else before.get("note") or ""),
            "completed_on": str(payload.get("completed_on") or before.get("completed_on") or str(before.get("completed_at") or now)[:10]),
            "corrected_at": now,
            "corrected_by": operator,
        }
        conn.execute(
            "UPDATE project_work_items SET completion_record_json=?,updated_at=? WHERE id=?",
            (json.dumps(after, ensure_ascii=False), now, item_id),
        )
        _audit(conn, project_id, "WORK_ITEM_COMPLETION_CORRECTED", operator, str(payload.get("reason") or ""), {
            "work_item_id": item_id, "before": before, "after": after,
            "milestone_before": None, "milestone_after": None,
        })
        return _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (item_id,)).fetchone()))


def reopen_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator, reason=str(payload.get("operator") or "").strip(),str(payload.get("reason") or "").strip()
    if not operator or not reason: raise ValidationError("重开事项必须填写操作人和原因")
    with get_connection() as conn:
        item=conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prior = _serialize_work_item(dict(item)).get("completion_record_json") or {}
        conn.execute("UPDATE project_work_items SET status='in_progress',started_on=COALESCE(started_on,?),updated_at=? WHERE id=?",(now[:10],now,item_id)); _audit(conn,project_id,"WORK_ITEM_REOPENED",operator,reason,{"work_item_id":item_id,"prior_completion":item["completion_record_json"]})
        return _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?",(item_id,)).fetchone()))


def get_milestones(project_id: int) -> list[dict]:
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        return [dict(row) for row in conn.execute(
            "SELECT * FROM project_milestones WHERE project_id=? ORDER BY occurred_on DESC,id DESC", (project_id,)
        ).fetchall()]


def include_in_advancement(project_id: int, payload: dict) -> dict:
    operator,reason=str(payload.get("operator") or "").strip(),str(payload.get("reason") or "").strip()
    if not operator or not reason: raise ValidationError("纳入推进必须填写操作人和理由")
    with get_connection() as conn:
        project=project_repo.fetch_project_by_id(conn,project_id)
        if not project: raise NotFoundError("项目不存在")
        if _project_stage(project) != "项目库—未实施": raise ValidationError("仅项目库—未实施项目可纳入推进")
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO project_advancement_records (project_id,advancement_year,status,included_at,included_reason,included_by) VALUES (?,?, 'active',?,?,?)", (project_id, int(payload.get("advancement_year") or date.today().year), now, reason, operator))
        project_repo.update_project_status(conn,project_id,{"library_implementation_view":"advancing","advancement_year":payload.get("advancement_year"),"advancement_date":now,"updated_at":now}); _audit(conn,project_id,"PROJECT_INCLUDED_IN_ADVANCEMENT",operator,reason,{"year":payload.get("advancement_year")}); return project_repo.fetch_project_by_id(conn,project_id)


def defer_advancement(project_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason: raise ValidationError("暂缓推进必须填写操作人和原因")
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project: raise NotFoundError("项目不存在")
        is_special = bool(project.get("special_advancement_active"))
        if project.get("library_implementation_view") != "advancing" and not is_special:
            raise ValidationError("仅推进中或特批推进中项目可暂缓推进")
        active = conn.execute("SELECT id FROM project_advancement_records WHERE project_id=? AND status='active' ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if active: conn.execute("UPDATE project_advancement_records SET status='deferred',ended_at=?,ended_reason=?,ended_by=? WHERE id=?", (now, reason, operator, active["id"]))
        project_repo.update_project_status(conn, project_id, {
            "library_implementation_view": "unimplemented",
            "special_advancement_active": 0,
            "updated_at": now,
        })
        _audit(conn, project_id, "PROJECT_ADVANCEMENT_DEFERRED", operator, reason)
        return project_repo.fetch_project_by_id(conn, project_id)


def complete_advancement_cycle(project_id: int, payload: dict) -> dict:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason: raise ValidationError("结束推进周期必须填写操作人和说明")
    with get_connection() as conn:
        active = conn.execute("SELECT id FROM project_advancement_records WHERE project_id=? AND status='active' ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
        if not active: raise ValidationError("当前没有进行中的推进周期")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE project_advancement_records SET status='completed',ended_at=?,ended_reason=?,ended_by=? WHERE id=?", (now, reason, operator, active["id"]))
        _audit(conn, project_id, "PROJECT_ADVANCEMENT_COMPLETED", operator, reason)
        project = project_repo.fetch_project_by_id(conn, project_id)
        assert project is not None
        return project


def _stage_advance_blockers(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """Work Items that still require an explicit PMO decision before normal Stage advance."""
    return _active_work_items(_work_items_for_project(conn, project_id))


def advance_projects_by_stage(payload: dict) -> dict:
    """Apply one normal Stage action atomically; legacy transition rules remain force-only compatibility."""
    project_ids = list(dict.fromkeys(int(project_id) for project_id in payload.get("project_ids") or []))
    action = str(payload.get("action") or "")
    operator = str(payload.get("operator") or "").strip()
    document_no = str(payload.get("establishment_document_no") or "").strip()
    if not project_ids or action not in {"establish", "complete"} or not operator:
        raise ValidationError("请选择项目、Stage 推进动作并填写操作人")
    if action == "establish" and not document_no:
        raise ValidationError("登记立项并进入项目库必须填写立项文件号")

    with get_connection() as conn:
        projects = {project["id"]: project for project in project_repo.fetch_projects_by_ids(conn, project_ids)}
        errors: list[str] = []
        for project_id in project_ids:
            project = projects.get(project_id)
            if not project:
                errors.append(f"项目 {project_id} 不存在")
                continue
            stage = _project_stage(project)
            expected_stage = "未立项" if action == "establish" else "项目库—推进中"
            if stage != expected_stage:
                errors.append(f"{project['name']}：当前为“{stage}”，不能{('登记立项' if action == 'establish' else '完成项目')}")
                continue
            if action == "establish" and project.get("special_advancement_active"):
                errors.append(f"{project['name']}：特批推进中，请先暂缓推进后再登记立项")
                continue
            if action == "complete":
                active_cycle = conn.execute(
                    "SELECT id FROM project_advancement_records WHERE project_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
                if not active_cycle:
                    errors.append(f"{project['name']}：没有可完成的推进周期")
                    continue
            blockers = _stage_advance_blockers(conn, project_id)
            if blockers:
                errors.append(f"{project['name']}：存在未终止事项“{'、'.join(item['name'] for item in blockers)}”")
        if errors:
            raise ValidationError("不能直接推进：" + "；".join(errors), code="STAGE_ADVANCE_BLOCKED")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        completed_on = date.today().isoformat()
        updated: list[dict] = []
        for project_id in project_ids:
            project = projects[project_id]
            if action == "establish":
                project_repo.update_project_status(conn, project_id, {
                    "current_status": "established",
                    "library_implementation_view": "unimplemented",
                    "special_advancement_active": 0,
                    "establishment_document_no": document_no,
                    "updated_at": now,
                    "status_updated_at": now,
                })
                project_repo.insert_status_history(
                    conn, project_id=project_id, from_status=project["current_status"], to_status="established",
                    action="登记立项并进入项目库", operator=operator, comment=f"立项文件号：{document_no}", deliverable="",
                )
                _audit(conn, project_id, "PROJECT_STAGE_ADVANCED", operator, payload={
                    "action": action, "from_stage": "未立项", "to_stage": "项目库—未实施", "establishment_document_no": document_no,
                })
            else:
                active_cycle = conn.execute(
                    "SELECT id FROM project_advancement_records WHERE project_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
                assert active_cycle is not None
                conn.execute(
                    "UPDATE project_advancement_records SET status='completed',ended_at=?,ended_reason=?,ended_by=? WHERE id=?",
                    (now, "事项已全部结束，完成项目", operator, active_cycle["id"]),
                )
                project_repo.update_project_status(conn, project_id, {
                    "current_status": "closed",
                    "library_implementation_view": "unimplemented",
                    "special_advancement_active": 0,
                    "actual_end_date": project.get("actual_end_date") or completed_on,
                    "updated_at": now,
                    "status_updated_at": now,
                })
                project_repo.insert_status_history(
                    conn, project_id=project_id, from_status=project["current_status"], to_status="closed",
                    action="完成项目", operator=operator, comment="事项已全部结束", deliverable="",
                )
                _audit(conn, project_id, "PROJECT_STAGE_ADVANCED", operator, payload={
                    "action": action, "from_stage": "项目库—推进中", "to_stage": "已完成", "actual_end_date": project.get("actual_end_date") or completed_on,
                    "advancement_record_id": active_cycle["id"],
                })
            current = project_repo.fetch_project_by_id(conn, project_id)
            assert current is not None
            updated.append(_hydrate_project_projection(conn, current))
    return {"total": len(project_ids), "success": len(updated), "projects": updated}


def get_advancement_cycles(project_id: int) -> list[dict]:
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM project_advancement_records WHERE project_id=? ORDER BY id", (project_id,)).fetchall()]


def create_early_preparation(project_id: int, payload: dict) -> dict:
    operator, reason, basis = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip(), str(payload.get("approval_basis") or "").strip()
    if not operator or not reason or not basis: raise ValidationError("提前推进准备必须填写操作人、理由和审批依据")
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project: raise NotFoundError("项目不存在")
        if _project_stage(project) != "未立项": raise ValidationError("仅未立项项目可登记提前推进准备")
        cursor = conn.execute("INSERT INTO project_early_preparations (project_id,preparation_year,reason,approval_basis,operator) VALUES (?,?,?,?,?)", (project_id, int(payload.get("preparation_year") or date.today().year), reason, basis, operator))
        _audit(conn, project_id, "PROJECT_EARLY_PREPARATION_CREATED", operator, reason, {"preparation_id": cursor.lastrowid})
        return dict(conn.execute("SELECT * FROM project_early_preparations WHERE id=?", (cursor.lastrowid,)).fetchone())


def special_include_in_advancement(project_id: int, payload: dict) -> dict:
    """PMO exception for pre-establishment preparation management.

    It is intentionally not a Stage transition.  The project remains in the
    unestablished card and gets a distinct annual governance-cycle record.
    """
    operator = str(payload.get("operator") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    basis = str(payload.get("approval_basis") or "").strip()
    if not operator or not reason or not basis:
        raise ValidationError("特批纳入推进必须填写操作人、原因和审批依据")
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            raise NotFoundError("项目不存在")
        if _project_stage(project) != "未立项":
            raise ValidationError("仅未立项项目可特批纳入推进")
        if project.get("special_advancement_active"):
            raise ValidationError("项目已处于特批推进中")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        year = int(payload.get("advancement_year") or date.today().year)
        conn.execute(
            """INSERT INTO project_advancement_records
            (project_id,advancement_year,status,included_at,included_reason,included_by)
            VALUES (?,?, 'active',?,?,?)""",
            (project_id, year, now, reason, operator),
        )
        project_repo.update_project_status(conn, project_id, {
            "special_advancement_active": 1,
            "advancement_year": year,
            "advancement_date": now,
            "updated_at": now,
        })
        _audit(conn, project_id, "PROJECT_SPECIAL_INCLUDED_IN_ADVANCEMENT", operator, reason, {"year": year, "approval_basis": basis})
        result = project_repo.fetch_project_by_id(conn, project_id)
        assert result is not None
        return _hydrate_project_projection(conn, result)


def get_audit_events(project_id: int) -> list[dict]:
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM audit_events WHERE project_id=? ORDER BY id",(project_id,)).fetchall()]


def get_work_items(project_id: int) -> list[dict]:
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id): raise NotFoundError("项目不存在")
        items = _work_items_for_project(conn, project_id)
        from backend.app.services.batches import current_batch_summaries_for_items
        summaries = current_batch_summaries_for_items(conn, [item["id"] for item in items])
        for item in items:
            item["batch_summaries"] = summaries.get(item["id"], [])
        return [_serialize_work_item(item) for item in sorted(items, key=_work_item_order)]


def create_progress_log(project_id: int, item_id: int, payload: dict) -> dict:
    operator, content = str(payload.get("operator") or "").strip(), str(payload.get("content") or "").strip()
    if not operator or not content:
        raise ValidationError("进展内容和操作人不能为空")
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item:
            raise NotFoundError("事项不存在")
        cursor = conn.execute(
            "INSERT INTO work_item_progress_logs (project_work_item_id,content,operator,is_timeline_highlight) VALUES (?,?,?,0)",
            (item_id, content, operator),
        )
        log = dict(conn.execute("SELECT * FROM work_item_progress_logs WHERE id=?", (cursor.lastrowid,)).fetchone())
        _audit(conn, project_id, "WORK_ITEM_PROGRESS_RECORDED", operator, payload={"work_item_id": item_id, "progress_log_id": log["id"], "highlight": bool(log["is_timeline_highlight"])})
        return log


def get_progress_logs(project_id: int, item_id: int) -> list[dict]:
    with get_connection() as conn:
        item = conn.execute("SELECT 1 FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item:
            raise NotFoundError("事项不存在")
        return [dict(row) for row in conn.execute("SELECT * FROM work_item_progress_logs WHERE project_work_item_id=? AND deleted_at IS NULL ORDER BY created_at ASC, id ASC", (item_id,)).fetchall()]


def update_progress_log(project_id: int, item_id: int, log_id: int, payload: dict) -> dict:
    operator, content = str(payload.get("operator") or "").strip(), str(payload.get("content") or "").strip()
    if not operator or not content:
        raise ValidationError("进展内容和操作人不能为空")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM work_item_progress_logs WHERE id=? AND project_work_item_id=? AND deleted_at IS NULL", (log_id, item_id)).fetchone()
        if not row:
            raise NotFoundError("进展记录不存在")
        before = dict(row)
        conn.execute("UPDATE work_item_progress_logs SET content=?, is_timeline_highlight=0 WHERE id=?", (content, log_id))
        result = dict(conn.execute("SELECT * FROM work_item_progress_logs WHERE id=?", (log_id,)).fetchone())
        _audit(conn, project_id, "WORK_ITEM_PROGRESS_UPDATED", operator, payload={"work_item_id": item_id, "progress_log_id": log_id, "before": before["content"], "after": content})
        return result


def delete_progress_log(project_id: int, item_id: int, log_id: int, payload: dict) -> None:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason:
        raise ValidationError("删除进展需要操作人和原因")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM work_item_progress_logs WHERE id=? AND project_work_item_id=? AND deleted_at IS NULL", (log_id, item_id)).fetchone()
        if not row:
            raise NotFoundError("进展记录不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE work_item_progress_logs SET deleted_at=?, deleted_by=?, deleted_reason=? WHERE id=?", (now, operator, reason, log_id))
        _audit(conn, project_id, "WORK_ITEM_PROGRESS_DELETED", operator, reason, {"work_item_id": item_id, "progress_log_id": log_id, "content": row["content"]})


def _require_constraint(conn: sqlite3.Connection, project_id: int, constraint_id: int) -> dict:
    row = conn.execute("SELECT * FROM project_external_constraints WHERE id=? AND project_id=?", (constraint_id, project_id)).fetchone()
    if not row:
        raise NotFoundError("外部约束不存在")
    return dict(row)


def get_external_constraint_progress_logs_for_connection(conn: sqlite3.Connection, project_id: int, constraint_id: int, *, limit: int | None = None) -> list[dict]:
    _require_constraint(conn, project_id, constraint_id)
    order = "created_at DESC, id DESC" if limit is not None else "created_at ASC, id ASC"
    sql = f"SELECT * FROM external_constraint_progress_logs WHERE project_external_constraint_id=? AND deleted_at IS NULL ORDER BY {order}"
    params: list[object] = [constraint_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_external_constraint_progress_logs(project_id: int, constraint_id: int) -> list[dict]:
    with get_connection() as conn:
        return get_external_constraint_progress_logs_for_connection(conn, project_id, constraint_id)


def create_external_constraint_progress_log(project_id: int, constraint_id: int, payload: dict) -> dict:
    operator, content = str(payload.get("operator") or "").strip(), str(payload.get("content") or "").strip()
    if not operator or not content:
        raise ValidationError("进展内容和操作人不能为空")
    with get_connection() as conn:
        _require_constraint(conn, project_id, constraint_id)
        cursor = conn.execute("INSERT INTO external_constraint_progress_logs (project_external_constraint_id,content,operator,updated_by) VALUES (?,?,?,?)", (constraint_id, content, operator, operator))
        result = dict(conn.execute("SELECT * FROM external_constraint_progress_logs WHERE id=?", (cursor.lastrowid,)).fetchone())
        _audit(conn, project_id, "EXTERNAL_CONSTRAINT_PROGRESS_RECORDED", operator, payload={"constraint_id": constraint_id, "progress_log_id": result["id"]})
        return result


def update_external_constraint_progress_log(project_id: int, constraint_id: int, log_id: int, payload: dict) -> dict:
    operator, content = str(payload.get("operator") or "").strip(), str(payload.get("content") or "").strip()
    if not operator or not content:
        raise ValidationError("进展内容和操作人不能为空")
    with get_connection() as conn:
        _require_constraint(conn, project_id, constraint_id)
        row = conn.execute("SELECT * FROM external_constraint_progress_logs WHERE id=? AND project_external_constraint_id=? AND deleted_at IS NULL", (log_id, constraint_id)).fetchone()
        if not row:
            raise NotFoundError("进展记录不存在")
        before = dict(row)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE external_constraint_progress_logs SET content=?,updated_at=?,updated_by=? WHERE id=?", (content, now, operator, log_id))
        result = dict(conn.execute("SELECT * FROM external_constraint_progress_logs WHERE id=?", (log_id,)).fetchone())
        _audit(conn, project_id, "EXTERNAL_CONSTRAINT_PROGRESS_UPDATED", operator, payload={"constraint_id": constraint_id, "progress_log_id": log_id, "before": before["content"], "after": content})
        return result


def delete_external_constraint_progress_log(project_id: int, constraint_id: int, log_id: int, payload: dict) -> None:
    operator, reason = str(payload.get("operator") or "").strip(), str(payload.get("reason") or "").strip()
    if not operator or not reason:
        raise ValidationError("删除进展需要操作人和原因")
    with get_connection() as conn:
        _require_constraint(conn, project_id, constraint_id)
        row = conn.execute("SELECT * FROM external_constraint_progress_logs WHERE id=? AND project_external_constraint_id=? AND deleted_at IS NULL", (log_id, constraint_id)).fetchone()
        if not row:
            raise NotFoundError("进展记录不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE external_constraint_progress_logs SET deleted_at=?,deleted_by=?,deleted_reason=? WHERE id=?", (now, operator, reason, log_id))
        _audit(conn, project_id, "EXTERNAL_CONSTRAINT_PROGRESS_DELETED", operator, reason, {"constraint_id": constraint_id, "progress_log_id": log_id, "content": row["content"]})


def _batch_constraint_matches(constraint: dict, payload: dict) -> bool:
    if payload.get("template_id"):
        return int(constraint.get("template_id") or 0) == int(payload["template_id"])
    name = str(payload.get("name") or "").strip().casefold()
    if not name or constraint["name"].strip().casefold() != name:
        return False
    return not payload.get("outcome_kind") or _constraint_outcome_kind(constraint) == payload.get("outcome_kind")


def _batch_constraint_preflight(conn: sqlite3.Connection, payload: dict) -> dict:
    project_ids = list(dict.fromkeys(payload.get("project_ids") or []))
    target_ids = {int(item.get("project_id")): int(item.get("constraint_id")) for item in (payload.get("targets") or []) if item.get("project_id") and item.get("constraint_id")}
    action = str(payload.get("action") or "").strip()
    if not project_ids or action not in {"begin", "progress", "clear", "conclude", "mark_not_applicable", "invalidate"}:
        raise ValidationError("请选择项目并提供有效的批量约束动作")
    eligible, ineligible = [], []
    for project_id in project_ids:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            ineligible.append({"project_id": project_id, "message": "项目不存在"})
            continue
        if target_ids:
            target_id = target_ids.get(int(project_id))
            matches = [dict(conn.execute("SELECT * FROM project_external_constraints WHERE id=? AND project_id=?", (target_id, project_id)).fetchone() or {})] if target_id else []
            matches = [item for item in matches if item]
        else:
            matches = [dict(row) for row in conn.execute("SELECT * FROM project_external_constraints WHERE project_id=?", (project_id,)).fetchall() if _batch_constraint_matches(dict(row), payload)]
        if len(matches) != 1:
            ineligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "message": "未找到唯一的同类型外部约束，请在项目详情单独办理"})
            continue
        constraint = matches[0]
        if constraint["clearance_status"] == "not_applicable":
            ineligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "message": "约束已标记不适用"})
            continue
        eligible.append({"project_id": project_id, "project_code": project["project_code"], "name": project["name"], "constraint_id": constraint["id"], "outcome_kind": _constraint_outcome_kind(constraint), "impact_scope": _constraint_impact_scope(constraint)})
    return {"action": action, "eligible": eligible, "ineligible": ineligible}


def preview_batch_external_constraint_action(payload: dict) -> dict:
    with get_connection() as conn:
        return _batch_constraint_preflight(conn, payload)


def execute_batch_external_constraint_action(payload: dict) -> dict:
    operator, action = str(payload.get("operator") or "").strip(), str(payload.get("action") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    defaults = payload.get("defaults") or {}
    if action in {"mark_not_applicable", "invalidate"} and not str(defaults.get("reason") or payload.get("reason") or "").strip():
        raise ValidationError("该批量动作必须填写原因或说明")
    with get_connection() as conn:
        preview = _batch_constraint_preflight(conn, payload)
        if preview["ineligible"]:
            raise ValidationError("存在不符合条件的项目，请根据预检结果分别处理")
        if not preview["eligible"]:
            raise ValidationError("没有可执行的项目")
        cursor = conn.execute("INSERT INTO external_constraint_batch_operations (action,operator,reason,payload_json) VALUES (?,?,?,?)", (action, operator, str(defaults.get("reason") or payload.get("reason") or ""), json.dumps({"project_ids": payload.get("project_ids"), "targets": payload.get("targets"), "template_id": payload.get("template_id"), "name": payload.get("name"), "defaults": defaults, "overrides": payload.get("overrides") or {}}, ensure_ascii=False)))
        batch_audit_id = cursor.lastrowid
        for item in preview["eligible"]:
            action_payload = {**payload, **defaults, **((payload.get("overrides") or {}).get(str(item["project_id"]), {}) or {}), "operator": operator}
            if action == "progress":
                content = str(action_payload.get("content") or "").strip()
                if not content:
                    raise ValidationError("批量记录进展必须填写内容")
                log_cursor = conn.execute("INSERT INTO external_constraint_progress_logs (project_external_constraint_id,content,operator,updated_by) VALUES (?,?,?,?)", (item["constraint_id"], content, operator, operator))
                _audit(conn, item["project_id"], "EXTERNAL_CONSTRAINT_PROGRESS_RECORDED", operator, payload={"constraint_id": item["constraint_id"], "progress_log_id": log_cursor.lastrowid, "batch_audit_id": batch_audit_id})
            else:
                if (action == "conclude" and item["outcome_kind"] == "budget_determination") or (action == "clear" and item["impact_scope"] == "effective_budget"):
                    per_project = next((entry for entry in payload.get("project_outcomes") or [] if int(entry.get("project_id") or 0) == item["project_id"]), None)
                    if not per_project:
                        raise ValidationError("影响有效预算的约束必须分别填写每个项目的有效预算")
                    action_payload.update(per_project)
                _act_on_constraint(conn, item["project_id"], item["constraint_id"], action_payload, batch_audit_id=batch_audit_id)
        return {"success": True, "processed_count": len(preview["eligible"]), "batch_audit_id": batch_audit_id}


def get_management_timeline(project_id: int) -> list[dict]:
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        events = []
        for row in conn.execute("SELECT * FROM audit_events WHERE project_id=? ORDER BY id DESC", (project_id,)).fetchall():
            item = dict(row)
            labels = {
                "PROJECT_INCLUDED_IN_ADVANCEMENT": "纳入年度推进",
                "PROJECT_SPECIAL_INCLUDED_IN_ADVANCEMENT": "特批纳入推进",
                "PROJECT_ADVANCEMENT_DEFERRED": "暂缓年度推进",
                "PROJECT_ADVANCEMENT_COMPLETED": "结束年度推进周期",
                "WORK_ITEM_CREATED": "新增跟踪事项",
                "WORK_ITEM_CANCELLED": "取消跟踪事项",
                "WORK_ITEM_SKIPPED": "跳过主流程节点",
                "WORK_ITEM_COMPLETED": "事项已完成",
                "WORK_ITEM_COMPLETION_CORRECTED": "更正事项完成记录",
                "WORK_ITEM_REOPENED": "事项已重开",
                "EXTERNAL_CONSTRAINT_CREATED": "新增外部约束",
                "EXTERNAL_CONSTRAINT_BEGIN": "开始办理外部约束",
                "EXTERNAL_CONSTRAINT_NEEDS_SUPPLEMENT": "外部约束过程记录",
                "EXTERNAL_CONSTRAINT_CONCLUDE": "形成外部约束结论",
                "EXTERNAL_CONSTRAINT_CLEAR": "解除外部约束",
                "EXTERNAL_CONSTRAINT_MARK_NOT_APPLICABLE": "外部约束标记为不适用",
                "EXTERNAL_CONSTRAINT_INVALIDATE": "外部约束结论失效",
                "EXTERNAL_CONSTRAINT_SET_EFFECTIVE_BUDGET_SOURCE": "切换当前有效预算来源",
                "EXTERNAL_CONSTRAINT_PROGRESS_RECORDED": "记录外部约束进展",
            }
            if item["event_type"] in labels:
                events.append({"id": f"audit-{item['id']}", "summary": labels[item["event_type"]], "created_at": item["created_at"], "operator": item["operator"], "kind": item["event_type"]})
        for row in conn.execute("SELECT * FROM work_item_progress_logs WHERE is_timeline_highlight=1 AND project_work_item_id IN (SELECT id FROM project_work_items WHERE project_id=?) ORDER BY id DESC", (project_id,)).fetchall():
            item = dict(row)
            events.append({"id": f"progress-{item['id']}", "summary": item["content"], "created_at": item["created_at"], "operator": item["operator"], "kind": "WORK_ITEM_PROGRESS"})
        for row in conn.execute("SELECT * FROM project_milestones WHERE project_id=? AND is_void=0 ORDER BY id DESC", (project_id,)).fetchall():
            milestone = dict(row)
            events.append({"id": f"milestone-{milestone['id']}", "summary": milestone["title"], "created_at": milestone["occurred_on"], "operator": milestone["created_by"], "kind": "MILESTONE"})
    return sorted(events, key=lambda item: (item["created_at"], item["id"]), reverse=True)


def execute_batch_transition(payload: dict) -> dict:
    unique_ids = list(dict.fromkeys(payload["project_ids"]))
    result = {"total": len(unique_ids), "success": 0, "failed": 0, "errors": []}
    expected_statuses = payload.get("expected_statuses") or {}
    expected_status_updated_at = payload.get("expected_status_updated_at") or {}
    with get_connection() as conn:
        for project_id in unique_ids:
            savepoint = f"sp_{project_id}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                project = project_repo.fetch_project_by_id(conn, project_id)
                if not project:
                    raise NotFoundError(f"项目不存在: {project_id}")
                item_payload = {
                    **payload,
                    "expected_current_status": expected_statuses.get(project_id),
                    "expected_status_updated_at": expected_status_updated_at.get(project_id),
                }
                transition_project(conn, project_id, item_payload)
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                result["success"] += 1
            except Exception as exc:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                result["failed"] += 1
                project = project_repo.fetch_project_by_id(conn, project_id)
                result["errors"].append(
                    {
                        "project_id": project_id,
                        "project_code": project["project_code"] if project else "-",
                        "name": project["name"] if project else "-",
                        "code": getattr(exc, "code", "VALIDATION_ERROR"),
                        "message": str(exc),
                    }
                )
    return result
