from __future__ import annotations

import sqlite3
from datetime import datetime

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


def transition_allows_budget_adjustment(from_status: str, to_status: str) -> bool:
    return from_status == "submission_review" or to_status == "submission_review"


def create_project_internal(payload: dict) -> dict:
    with get_connection() as conn:
        project_code = payload.get("project_code", "").strip()
        project_type = payload["project_type"]
        if project_code:
            project_code = validate_manual_project_code(project_code, project_type)
            if project_repo.project_code_exists(conn, project_code):
                raise DuplicateProjectCodeError(f"项目编号已存在: {project_code}")
        else:
            project_code = generate_project_code(conn, project_type)
        project_id = project_repo.insert_project(
            conn,
            {
                **payload,
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
    return {
        "items": items,
        "total": total,
        "page": int(filters.get("page", 1)),
        "page_size": int(filters.get("page_size", 20)),
    }


def get_project(project_id: int) -> dict:
    with get_connection() as conn:
        project = project_repo.fetch_project_by_id(conn, project_id)
    if not project:
        raise NotFoundError(f"项目不存在: {project_id}")
    return project


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
        if "project_type" in updates and project["project_code"]:
            updates["project_code"] = validate_manual_project_code(project["project_code"], updates["project_type"])
        project_repo.update_project_fields(conn, project_id, updates)
        updated = project_repo.fetch_project_by_id(conn, project_id)
    assert updated is not None
    return updated


def delete_project(project_id: int) -> None:
    with get_connection() as conn:
        if not project_repo.delete_project(conn, project_id):
            raise NotFoundError(f"项目不存在: {project_id}")


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
