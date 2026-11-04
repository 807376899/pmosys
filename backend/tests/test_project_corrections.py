from __future__ import annotations

from backend.app.db.connection import get_connection


def test_project_correction_updates_historical_facts_and_moves_annual_member(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="待更正项目")).json()
    now = "2026-11-04 10:00:00"
    with get_connection() as conn:
        cycle_id = conn.execute(
            """INSERT INTO project_advancement_records
               (project_id,advancement_year,status,included_at,included_reason,included_by,ended_at,ended_reason,ended_by)
               VALUES (?,?, 'completed',?,?,?,?,?,?)""",
            (project["id"], 2025, now, "历史导入", "PMO", now, "历史完成", "PMO"),
        ).lastrowid
        conn.execute(
            "UPDATE projects SET current_status='closed',advancement_year=2025,advancement_date=? WHERE id=?",
            (now, project["id"]),
        )
        draft_id = conn.execute(
            "INSERT INTO annual_advancement_drafts (advancement_year,created_by) VALUES (?,?)",
            (2025, "PMO"),
        ).lastrowid
        conn.execute(
            """INSERT INTO annual_advancement_draft_members
               (draft_id,project_id,member_status,added_by,planned_new_amount,planned_new_amount_decimal,member_kind)
               VALUES (?,?, 'confirmed',?,?,?, 'new')""",
            (draft_id, project["id"], "PMO", 12.5896, "12.5896"),
        )

    response = client.patch(f"/api/v1/projects/{project['id']}/correction", json={
        "project_code": "SW20250001",
        "name": "已更正项目",
        "project_type": "software",
        "budget": "12.5896",
        "approved_budget": "11.5896",
        "current_status": "closed",
        "advancement_year": 2024,
        "actual_end_date": "2025-02",
        "reason": "更正历史导入资料",
        "operator": "PMO办公室",
    })

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["project_code"] == "SW20250001"
    assert detail["budget"] == "12.5896"
    assert detail["effective_budget"] == "11.5896"
    assert detail["stage"] == "已完成"
    assert detail["implementation_year"] == 2024
    assert detail["actual_end_date"] == "2025-02"

    with get_connection() as conn:
        cycle = conn.execute("SELECT advancement_year,status FROM project_advancement_records WHERE id=?", (cycle_id,)).fetchone()
        assert tuple(cycle) == (2024, "completed")
        old_member = conn.execute(
            "SELECT member_status FROM annual_advancement_draft_members WHERE draft_id=? AND project_id=?",
            (draft_id, project["id"]),
        ).fetchone()
        assert old_member["member_status"] == "removed"
        moved = conn.execute(
            """SELECT d.advancement_year,m.member_status FROM annual_advancement_draft_members m
               JOIN annual_advancement_drafts d ON d.id=m.draft_id
               WHERE m.project_id=? AND d.advancement_year=2024""",
            (project["id"],),
        ).fetchone()
        assert tuple(moved) == (2024, "confirmed")
        audit = conn.execute(
            "SELECT event_type FROM audit_events WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project["id"],),
        ).fetchone()
        assert audit["event_type"] == "PROJECT_DATA_CORRECTED"


def test_project_correction_creates_active_cycle_and_rejects_incomplete_completion(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="推进年份更正项目")).json()

    rejected = client.patch(f"/api/v1/projects/{project['id']}/correction", json={
        "stage": "已完成", "advancement_year": 2025, "reason": "缺少完成日期", "operator": "PMO办公室",
    })
    assert rejected.status_code == 422
    assert client.get(f"/api/v1/projects/{project['id']}").json()["stage"] == "未立项"
    assert client.get(f"/api/v1/projects/{project['id']}/advancement-cycles").json() == []

    corrected = client.patch(f"/api/v1/projects/{project['id']}/correction", json={
        "stage": "项目库—推进中", "advancement_year": 2026,
        "reason": "补正推进事实", "operator": "PMO办公室",
    })
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["stage"] == "项目库—推进中"
    assert corrected.json()["implementation_year"] == 2026
    assert client.get(f"/api/v1/projects/{project['id']}/advancement-cycles").json()[0]["status"] == "active"
    plan = client.get("/api/v1/projects/annual-budget-plans/2026").json()
    assert next(member for member in plan["members"] if member["project_id"] == project["id"])["member_status"] == "confirmed"


def test_project_correction_supports_all_project_stages(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="五状态更正项目")).json()

    def correct(**changes):
        return client.patch(f"/api/v1/projects/{project['id']}/correction", json={
            "reason": "校正历史状态", "operator": "PMO办公室", **changes,
        })

    assert correct(stage="未立项").json()["stage"] == "未立项"
    assert correct(stage="项目库—未实施").json()["stage"] == "项目库—未实施"
    assert correct(stage="项目库—推进中", advancement_year=2026).json()["stage"] == "项目库—推进中"
    assert correct(stage="已完成", advancement_year=2026, actual_end_date="2026-10-01").json()["stage"] == "已完成"

    missing_reason = correct(stage="已废弃")
    assert missing_reason.status_code == 422
    abandoned = correct(stage="已废弃", termination_reason="历史项目停止建设")
    assert abandoned.status_code == 200, abandoned.text
    assert abandoned.json()["stage"] == "已废弃"
