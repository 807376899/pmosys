from __future__ import annotations

import sqlite3
import json
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


def transition_allows_budget_adjustment(from_status: str, to_status: str) -> bool:
    return from_status == "submission_review" or to_status == "submission_review"


def create_project_internal(payload: dict) -> dict:
    with get_connection() as conn:
        project_code = payload.get("project_code", "").strip()
        project_type = _PROJECT_TYPE_ALIASES.get(payload["project_type"], payload["project_type"])
        procurement_nature = str(payload.get("procurement_nature") or "").strip()
        if project_type != "software":
            procurement_nature = ""
        elif procurement_nature and procurement_nature not in _PROCUREMENT_NATURES:
            raise ValidationError("采购属性必须为 goods、service 或 mixed")
        if project_code:
            project_code = validate_manual_project_code(conn, project_code, project_type)
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
        for project in items:
            _hydrate_project_projection(conn, project, omit_legacy_status=True)
    return {
        "items": items,
        "total": total,
        "page": int(filters.get("page", 1)),
        "page_size": int(filters.get("page_size", 20)),
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
    blocking = [row for row in rows if bool(row.get("is_blocking")) and row.get("clearance_status") != "not_applicable"]
    # A project with no applicable blocking constraint is ready from the
    # external-governance perspective.  Non-blocking constraints remain
    # visible and actionable, but must not suppress this dashboard signal.
    if not blocking:
        cleared = "true"
    elif any(row.get("clearance_status") != "cleared" for row in blocking):
        cleared = "false"
    else:
        cleared = "true"

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
    else:
        effective_budget = float(project.get("budget") or 0)
        source = "initial_budget"
    return {
        "external_constraints_cleared": cleared,
        "external_constraint_count": len(rows),
        "external_constraint_open_count": sum(
            1 for row in rows if row.get("clearance_status") not in {"cleared", "not_applicable"}
        ),
        "external_constraint_scope_confirmation": dict(confirmed) if confirmed else None,
        "effective_budget": effective_budget,
        "effective_budget_source": source,
    }


def _hydrate_project_projection(conn: sqlite3.Connection, project: dict, *, omit_legacy_status: bool = False) -> dict:
    project["stage"] = _project_stage(project)
    project["advancement"] = {
        "year": project.get("advancement_year"),
        "date": project.get("advancement_date"),
        "view": project.get("library_implementation_view") or "unimplemented",
        "status": "special_active" if project.get("special_advancement_active") else (
            "active" if project.get("library_implementation_view") == "advancing" else "none"
        ),
    }
    work_items = _work_items_for_project(conn, project["id"])
    project["work_item_summary"] = _work_item_summary(work_items)
    project["work_item_count"] = len(work_items)
    project["work_item_states"] = {item["name"]: item["status"] for item in work_items}
    project["next_key_node"] = _next_key_node(work_items)
    active_items = _active_work_items(work_items)
    project["active_work_item_count"] = len(active_items)
    project["progress_focus_item"] = _progress_focus_item(active_items, project["next_key_node"])
    project["project_summary_display"] = _project_summary_display(conn, project)
    project.update(_external_constraint_projection(conn, project["id"], project))
    if omit_legacy_status:
        project.pop("current_status", None)
    return project


def _work_items_for_project(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT * FROM project_work_items WHERE project_id = ?", (project_id,)).fetchall()]


def _work_item_order(item: dict) -> tuple:
    if item.get("flow_group") == "main":
        return (0, int(item.get("sequence_rank") or 1000), item["id"])
    planned = item.get("planned_date") or ""
    overdue = bool(planned and planned < date.today().isoformat() and item.get("status") not in {"completed", "paused", "not_applicable"})
    status_rank = {"waiting_external": 1, "in_progress": 2, "not_started": 3}.get(item.get("status"), 9)
    planned_sort = planned or "9999-12-31"
    priority_rank = {"high": 1, "normal": 2, "low": 3}.get(item.get("priority"), 2)
    return (1, -int(overdue), status_rank, -int(bool(item.get("track_as_key_node"))), planned_sort, priority_rank, item["id"])


def _work_item_summary(items: list[dict]) -> list[dict]:
    return [_work_item_projection(item) for item in sorted(_active_work_items(items), key=_work_item_order)[:2]]


def _active_work_items(items: list[dict]) -> list[dict]:
    return [
        item for item in items
        if item.get("status") not in {"completed", "paused", "not_applicable"}
        and not item.get("cancelled_at") and not item.get("skipped_at")
    ]


def _work_item_projection(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "status": item["status"],
        "planned_date": item.get("planned_date") or "",
        "track_as_key_node": bool(item.get("track_as_key_node")),
    }


def _progress_focus_item(active_items: list[dict], next_key_node: dict | None) -> dict | None:
    next_id = (next_key_node or {}).get("id")
    candidates = [item for item in active_items if item["id"] != next_id]
    if not candidates:
        return None
    status_rank = {"in_progress": 0, "waiting_external": 1, "not_started": 3}
    candidates.sort(
        key=lambda item: (
            status_rank.get(item.get("status"), 9),
            -int(bool(item.get("track_as_key_node"))),
            item.get("planned_date") or "9999-12-31",
            {"high": 0, "normal": 1, "low": 2}.get(item.get("priority"), 1),
            item["id"],
        )
    )
    return _work_item_projection(candidates[0])


def _project_summary_display(conn: sqlite3.Connection, project: dict) -> str:
    row = conn.execute("SELECT name FROM project_types WHERE code=?", (project.get("project_type"),)).fetchone()
    name = row["name"] if row else "未分类"
    if project.get("project_type") == "software":
        nature = {"goods": "货物", "service": "服务", "mixed": "混合"}.get(project.get("procurement_nature"), "未设置")
        return f"{name} · {nature}"
    if project.get("project_type") == "laboratory":
        return f"{name} · {project.get('location') or '未设置'}"
    return name


def _next_key_node(items: list[dict]) -> dict | None:
    candidates = [item for item in items if item.get("flow_group") == "main" and item.get("status") not in {"completed", "not_applicable"} and not item.get("cancelled_at") and not item.get("skipped_at")]
    if not candidates:
        candidates = [item for item in items if item.get("track_as_key_node") and item.get("status") not in {"completed", "paused", "not_applicable"} and not item.get("cancelled_at") and not item.get("skipped_at")]
    if not candidates:
        return None
    item = sorted(candidates, key=_work_item_order)[0]
    return _work_item_projection(item)


def get_project(project_id: int) -> dict:
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
        if not project:
            raise NotFoundError(f"项目不存在: {project_id}")
        return _hydrate_project_projection(conn, project)


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


def _audit(conn, project_id: int, event_type: str, operator: str, reason: str = "", payload: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_events (project_id,event_type,operator,reason,payload_json) VALUES (?,?,?,?,?)", (project_id,event_type,operator,reason,json.dumps(payload or {}, ensure_ascii=False)))


def create_external_constraint_template(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    operator = str(payload.get("operator") or "").strip()
    if not name or not operator:
        raise ValidationError("约束名称和操作人不能为空")
    scope_kind = str(payload.get("scope_kind") or "manual")
    if scope_kind not in {"all", "project_type", "manual"}:
        raise ValidationError("外部约束模板的适用范围仅支持全部项目、项目分类或手工指定")
    if scope_kind == "project_type" and not str(payload.get("scope_value") or "").strip():
        raise ValidationError("按项目分类适用时必须选择项目分类")
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO external_constraint_templates
            (name,recommended_stage,is_blocking,outcome_schema_json,project_field_effects_json,is_common,scope_kind,scope_value,effective_from,effective_until,applicability_basis)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET recommended_stage=excluded.recommended_stage,
                is_blocking=excluded.is_blocking,outcome_schema_json=excluded.outcome_schema_json,
                project_field_effects_json=excluded.project_field_effects_json,is_common=excluded.is_common,
                scope_kind=excluded.scope_kind,scope_value=excluded.scope_value,
                effective_from=excluded.effective_from,effective_until=excluded.effective_until,
                applicability_basis=excluded.applicability_basis,
                archived_at=NULL,archived_by='',archived_reason=''""",
            (
                name,
                str(payload.get("recommended_stage") or ""),
                int(bool(payload.get("is_blocking", True))),
                json.dumps(payload.get("outcome_schema") or {}, ensure_ascii=False),
                json.dumps(payload.get("project_field_effects") or {}, ensure_ascii=False),
                int(bool(payload.get("is_common", True))),
                scope_kind,
                str(payload.get("scope_value") or ""),
                str(payload.get("effective_from") or ""),
                str(payload.get("effective_until") or ""),
                str(payload.get("applicability_basis") or ""),
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
        "work_item": {"name", "default_content", "recommended_stage", "execution_mode", "completion_rule_json", "is_common", "flow_group", "sequence_rank", "stage_view_priority"},
        "work_package": {"name", "constraints_json"},
        "external_constraint": {"name", "recommended_stage", "is_blocking", "outcome_schema_json", "project_field_effects_json", "is_common", "scope_kind", "scope_value", "effective_from", "effective_until", "applicability_basis"},
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
            scope_kind = str(updates.get("scope_kind", row["scope_kind"]) or "manual")
            scope_value = str(updates.get("scope_value", row["scope_value"]) or "").strip()
            if scope_kind not in {"all", "project_type", "manual"}:
                raise ValidationError("外部约束模板的适用范围仅支持全部项目、项目分类或手工指定")
            if scope_kind == "project_type" and not scope_value:
                raise ValidationError("按项目分类适用时必须选择项目分类")
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id=?", [*updates.values(), template_id])
        result = conn.execute(f"SELECT * FROM {table} WHERE id=?", (template_id,)).fetchone()
        assert result is not None
        return _serialize_template_result(kind, dict(result))


def _serialize_template_result(kind: str, row: dict) -> dict:
    if kind == "external_constraint":
        return _serialize_constraint_template(row)
    return row


def _normalise_package_items(items: list[dict]) -> list[dict]:
    """The package array is the PMO-facing order; ranks stay internal."""
    main_rank = 100
    result: list[dict] = []
    for item in items:
        entry = dict(item)
        if entry.get("flow_group") == "main":
            entry["sequence_rank"] = main_rank
            main_rank += 100
        else:
            entry.pop("sequence_rank", None)
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
        blocking = bool(payload.get("is_blocking", (template or {}).get("is_blocking", True)))
        snapshot = template or {
            "name": name,
            "recommended_stage": payload.get("recommended_stage") or "",
            "project_field_effects_json": payload.get("project_field_effects") or {},
        }
        cursor = conn.execute(
            """INSERT INTO project_external_constraints
            (project_id,template_id,name,template_snapshot_json,is_blocking,primary_work_item_id,handling_status,clearance_status)
            VALUES (?,?,?,?,?,?,?,?)""",
            (project_id, payload.get("template_id"), name, json.dumps(snapshot, ensure_ascii=False), int(blocking),
             payload.get("primary_work_item_id"), payload.get("handling_status") or "not_started", "unresolved"),
        )
        row = dict(conn.execute("SELECT * FROM project_external_constraints WHERE id=?", (cursor.lastrowid,)).fetchone())
        _audit(conn, project_id, "EXTERNAL_CONSTRAINT_CREATED", operator, payload={"constraint_id": row["id"], "name": name})
        return _serialize_project_constraint(row)


def get_project_external_constraints(project_id: int) -> list[dict]:
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id):
            raise NotFoundError("项目不存在")
        return [_serialize_project_constraint(dict(row)) for row in conn.execute(
            "SELECT * FROM project_external_constraints WHERE project_id=? ORDER BY id DESC", (project_id,)
        ).fetchall()]


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
                        "is_blocking": item.get("is_blocking", True),
                        "outcome_schema": item.get("outcome_schema") or {},
                        "project_field_effects": item.get("project_field_effects") or {},
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


def act_on_project_external_constraint(project_id: int, constraint_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    action = str(payload.get("action") or "").strip()
    if not operator or action not in {"begin", "needs_supplement", "conclude", "mark_not_applicable", "invalidate", "set_effective_budget_source"}:
        raise ValidationError("请提供有效的约束办理动作和操作人")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM project_external_constraints WHERE id=? AND project_id=?", (constraint_id, project_id)).fetchone()
        if not row:
            raise NotFoundError("外部约束不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current = dict(row)
        reason = str(payload.get("reason") or "").strip()
        updates: dict[str, object] = {"updated_at": now}
        if action == "begin":
            updates.update({"handling_status": "in_progress", "clearance_status": "unresolved"})
        elif action == "needs_supplement":
            if not reason:
                raise ValidationError("要求补充必须填写说明")
            updates.update({"handling_status": "needs_supplement", "clearance_status": "unresolved"})
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
        elif action == "mark_not_applicable":
            if not reason:
                raise ValidationError("标记不适用必须填写原因")
            updates.update({"handling_status": "not_started", "clearance_status": "not_applicable", "is_effective_budget_source": 0})
        elif action == "invalidate":
            if not reason:
                raise ValidationError("结论失效必须填写原因")
            updates.update({
                "handling_status": "in_progress", "clearance_status": "unresolved", "invalidated_at": now,
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
            "constraint_id": constraint_id,
            "before": {"handling_status": current.get("handling_status"), "clearance_status": current.get("clearance_status"), "outcome_json": current.get("outcome_json"), "is_effective_budget_source": current.get("is_effective_budget_source")},
            "after": {**updates, "outcome": payload.get("outcome") if action == "conclude" else None},
        })
        result = conn.execute("SELECT * FROM project_external_constraints WHERE id=?", (constraint_id,)).fetchone()
        assert result is not None
        return _serialize_project_constraint(dict(result))


def create_work_item(project_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator: raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        if not project_repo.fetch_project_by_id(conn, project_id): raise NotFoundError("项目不存在")
        return _create_work_item(conn, project_id, payload, operator)


def _completion_rule(payload: dict) -> dict:
    effects = payload.get("completion_effects")
    if effects is not None:
        return {
            "effects": {
                "create_milestone": bool(effects.get("create_milestone")),
                "require_result": bool(effects.get("require_result")),
                "result_type": effects.get("result_type") or "free_text",
                "result_options": effects.get("result_options") or [],
                "milestone_name": effects.get("milestone_name") or "",
                "require_business_record": bool(effects.get("require_business_record")),
            },
        }
    mode = payload.get("completion_mode") or "record_only"
    if mode not in {"record_only", "milestone", "required_fields"}:
        raise ValidationError("不支持的完成后处理方式")
    return {"effects": {"create_milestone": mode == "milestone", "require_result": mode == "required_fields", "result_type": "free_text", "result_options": [], "milestone_name": "", "require_business_record": False}}


def _create_work_item(conn: sqlite3.Connection, project_id: int, payload: dict, operator: str) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name: raise ValidationError("事项名称不能为空")
    rule = _completion_rule(payload)
    cursor = conn.execute(
        """INSERT INTO project_work_items
        (project_id,name,status,track_as_key_node,completion_rule_snapshot,execution_mode,assignee,planned_date,priority,note,source_template_id,content,flow_group,sequence_rank)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (project_id, name, payload.get("status") or "not_started", int(bool(payload.get("track_as_key_node"))),
         json.dumps(rule, ensure_ascii=False), payload.get("execution_mode") or "tracking", payload.get("assignee") or "",
         payload.get("planned_date") or "", payload.get("priority") or "normal", payload.get("note") or "", payload.get("source_template_id"), payload.get("content") or "", payload.get("flow_group") or "independent", _next_sequence_rank(conn, project_id, payload)),
    )
    item = _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?", (cursor.lastrowid,)).fetchone()))
    _audit(conn, project_id, "WORK_ITEM_CREATED", operator, payload={"work_item_id": item["id"], "name": name})
    return item


def _next_sequence_rank(conn: sqlite3.Connection, project_id: int, payload: dict) -> int:
    if payload.get("sequence_rank") is not None:
        return int(payload["sequence_rank"])
    if payload.get("flow_group") != "main":
        return 1000
    after_id = payload.get("insert_after_id")
    if after_id:
        before = conn.execute("SELECT sequence_rank FROM project_work_items WHERE id=? AND project_id=?", (after_id, project_id)).fetchone()
        if before:
            following = conn.execute("SELECT sequence_rank FROM project_work_items WHERE project_id=? AND flow_group='main' AND sequence_rank>? ORDER BY sequence_rank LIMIT 1", (project_id, before["sequence_rank"])).fetchone()
            if following and following["sequence_rank"] - before["sequence_rank"] > 1:
                return (before["sequence_rank"] + following["sequence_rank"]) // 2
            if not following:
                return int(before["sequence_rank"]) + 100
            _renumber_main_flow(conn, project_id)
            return _next_sequence_rank(conn, project_id, payload)
    latest = conn.execute("SELECT MAX(sequence_rank) AS rank FROM project_work_items WHERE project_id=? AND flow_group='main'", (project_id,)).fetchone()
    return int(latest["rank"] or 0) + 100


def _renumber_main_flow(conn: sqlite3.Connection, project_id: int) -> None:
    rows = conn.execute("SELECT id FROM project_work_items WHERE project_id=? AND flow_group='main' ORDER BY sequence_rank,id", (project_id,)).fetchall()
    for index, row in enumerate(rows, start=1):
        conn.execute("UPDATE project_work_items SET sequence_rank=? WHERE id=?", (index * 100, row["id"]))


def reorder_main_work_items(project_id: int, payload: dict) -> list[dict]:
    operator = str(payload.get("operator") or "").strip()
    item_ids = [int(item_id) for item_id in payload.get("item_ids") or []]
    if not operator or not item_ids:
        raise ValidationError("操作人和主流程事项顺序不能为空")
    if len(item_ids) != len(set(item_ids)):
        raise ValidationError("主流程事项不能重复")
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id FROM project_work_items WHERE project_id=? AND flow_group='main' AND id IN ({','.join('?' for _ in item_ids)})",
            [project_id, *item_ids],
        ).fetchall()
        if {row["id"] for row in rows} != set(item_ids):
            raise ValidationError("只能重排当前项目的主流程事项")
        for index, item_id in enumerate(item_ids, start=1):
            conn.execute("UPDATE project_work_items SET sequence_rank=?,updated_at=? WHERE id=?", (index * 100, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item_id))
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
    return item


def update_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator: raise ValidationError("操作人不能为空")
    allowed = {"name", "content", "status", "track_as_key_node", "execution_mode", "assignee", "planned_date", "priority", "note"}
    updates = {key: value for key, value in payload.items() if key in allowed}
    if not updates: raise ValidationError("没有可更新的事项字段")
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
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
    updates = {key: value for key, value in payload.items() if key in {"status", "track_as_key_node", "planned_date"}}
    if not updates and not progress_content:
        raise ValidationError("请至少保存事项变更或进展记录")
    with get_connection() as conn:
        item = conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item:
            raise NotFoundError("事项不存在")
        if updates:
            updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            assignments = ", ".join(f"{field}=?" for field in updates)
            conn.execute(f"UPDATE project_work_items SET {assignments} WHERE id=?", [*updates.values(), item_id])
            _audit(conn, project_id, "WORK_ITEM_UPDATED", operator, payload={"work_item_id": item_id, "fields": list(updates)})
        log = None
        if progress_content:
            cursor = conn.execute(
                "INSERT INTO work_item_progress_logs (project_work_item_id,content,operator,is_timeline_highlight) VALUES (?,?,?,?)",
                (item_id, progress_content, operator, int(bool(payload.get("is_timeline_highlight")))),
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
        for item_payload in items:
            for project_id in project_ids:
                _create_work_item(conn, project_id, item_payload, operator)
                created_count += 1
            if payload.get("save_as_common"):
                _save_work_item_template(conn, item_payload)
        package_name = str(payload.get("save_as_package_name") or "").strip()
        package = _save_work_package(conn, package_name, items) if package_name else None
    return {"created_count": created_count, "project_count": len(project_ids), "package": package}


def _save_work_item_template(conn: sqlite3.Connection, payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    rule = _completion_rule(payload)
    conn.execute("INSERT OR IGNORE INTO work_item_templates (name,default_content,recommended_stage,execution_mode,completion_rule_json,is_common,flow_group,sequence_rank) VALUES (?,?,?,?,?,1,?,?)", (name, payload.get("content") or payload.get("default_content") or "", payload.get("recommended_stage") or "", payload.get("execution_mode") or "tracking", json.dumps(rule, ensure_ascii=False), payload.get("flow_group") or "independent", int(payload.get("sequence_rank") or 1000)))
    return dict(conn.execute("SELECT * FROM work_item_templates WHERE name=?", (name,)).fetchone())


def create_work_item_template(payload: dict) -> dict:
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("创建常用事项必须填写操作人")
    with get_connection() as conn:
        return _save_work_item_template(conn, payload)


def list_work_item_templates(include_archived: bool = False) -> list[dict]:
    with get_connection() as conn:
        archived_filter = "" if include_archived else " AND archived_at IS NULL"
        return [dict(row) for row in conn.execute(f"SELECT * FROM work_item_templates WHERE is_common=1{archived_filter} ORDER BY name").fetchall()]


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


def complete_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator=str(payload.get("operator") or "").strip()
    if not operator: raise ValidationError("操作人不能为空")
    with get_connection() as conn:
        item=conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        create_milestone = bool(payload.get("create_milestone"))
        record={"result":payload.get("result", ""),"operator":operator,"completed_at":now,"note":payload.get("note", ""),"create_milestone":create_milestone}
        if create_milestone:
            title = str(payload.get("milestone_name") or item["name"]).strip()
            cursor = conn.execute(
                """INSERT INTO project_milestones
                (project_id,source_work_item_id,title,occurred_on,result,note,created_by)
                VALUES (?,?,?,?,?,?,?)""",
                (project_id, item_id, title, str(payload.get("completed_on") or now[:10]), record["result"], record["note"], operator),
            )
            record["milestone_id"] = cursor.lastrowid
        conn.execute("UPDATE project_work_items SET status='completed',completion_record_json=?,updated_at=? WHERE id=?",(json.dumps(record,ensure_ascii=False),now,item_id)); _audit(conn,project_id,"WORK_ITEM_COMPLETED",operator,payload={"work_item_id":item_id,"record":record})
        return _serialize_work_item(dict(conn.execute("SELECT * FROM project_work_items WHERE id=?",(item_id,)).fetchone()))


def reopen_work_item(project_id: int, item_id: int, payload: dict) -> dict:
    operator, reason=str(payload.get("operator") or "").strip(),str(payload.get("reason") or "").strip()
    if not operator or not reason: raise ValidationError("重开事项必须填写操作人和原因")
    with get_connection() as conn:
        item=conn.execute("SELECT * FROM project_work_items WHERE id=? AND project_id=?",(item_id,project_id)).fetchone()
        if not item: raise NotFoundError("事项不存在")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prior = _serialize_work_item(dict(item)).get("completion_record_json") or {}
        milestone_id = prior.get("milestone_id") if isinstance(prior, dict) else None
        if milestone_id:
            conn.execute("UPDATE project_milestones SET is_void=1,voided_at=?,voided_by=?,voided_reason=? WHERE id=? AND project_id=?", (now, operator, reason, milestone_id, project_id))
        conn.execute("UPDATE project_work_items SET status='in_progress',updated_at=? WHERE id=?",(now,item_id)); _audit(conn,project_id,"WORK_ITEM_REOPENED",operator,reason,{"work_item_id":item_id,"prior_completion":item["completion_record_json"], "voided_milestone_id": milestone_id})
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
        items = [dict(row) for row in conn.execute("SELECT * FROM project_work_items WHERE project_id=?", (project_id,)).fetchall()]
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
            "INSERT INTO work_item_progress_logs (project_work_item_id,content,operator,is_timeline_highlight) VALUES (?,?,?,?)",
            (item_id, content, operator, int(bool(payload.get("is_timeline_highlight")))),
        )
        log = dict(conn.execute("SELECT * FROM work_item_progress_logs WHERE id=?", (cursor.lastrowid,)).fetchone())
        _audit(conn, project_id, "WORK_ITEM_PROGRESS_RECORDED", operator, payload={"work_item_id": item_id, "progress_log_id": log["id"], "highlight": bool(log["is_timeline_highlight"])})
        return log


def get_progress_logs(project_id: int, item_id: int) -> list[dict]:
    with get_connection() as conn:
        item = conn.execute("SELECT 1 FROM project_work_items WHERE id=? AND project_id=?", (item_id, project_id)).fetchone()
        if not item:
            raise NotFoundError("事项不存在")
        return [dict(row) for row in conn.execute("SELECT * FROM work_item_progress_logs WHERE project_work_item_id=? AND deleted_at IS NULL ORDER BY id DESC", (item_id,)).fetchall()]


def update_progress_log(project_id: int, item_id: int, log_id: int, payload: dict) -> dict:
    operator, content = str(payload.get("operator") or "").strip(), str(payload.get("content") or "").strip()
    if not operator or not content:
        raise ValidationError("进展内容和操作人不能为空")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM work_item_progress_logs WHERE id=? AND project_work_item_id=? AND deleted_at IS NULL", (log_id, item_id)).fetchone()
        if not row:
            raise NotFoundError("进展记录不存在")
        before = dict(row)
        conn.execute("UPDATE work_item_progress_logs SET content=?, is_timeline_highlight=? WHERE id=?", (content, int(bool(payload.get("is_timeline_highlight"))), log_id))
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
                "WORK_ITEM_REOPENED": "事项已重开",
                "EXTERNAL_CONSTRAINT_CREATED": "新增外部约束",
                "EXTERNAL_CONSTRAINT_BEGIN": "开始办理外部约束",
                "EXTERNAL_CONSTRAINT_NEEDS_SUPPLEMENT": "外部约束需补充",
                "EXTERNAL_CONSTRAINT_CONCLUDE": "形成外部约束结论",
                "EXTERNAL_CONSTRAINT_MARK_NOT_APPLICABLE": "外部约束标记为不适用",
                "EXTERNAL_CONSTRAINT_INVALIDATE": "外部约束结论失效",
                "EXTERNAL_CONSTRAINT_SET_EFFECTIVE_BUDGET_SOURCE": "切换当前有效预算来源",
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
