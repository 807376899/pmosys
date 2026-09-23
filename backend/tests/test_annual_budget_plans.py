from __future__ import annotations

import io

import pandas as pd


def _establish(client, project_id: int) -> None:
    assert client.post(f"/api/v1/projects/{project_id}/pmo-override", json={
        "to_status": "established", "operator": "PMO", "comment": "测试立项",
    }).status_code == 200


def _active(client, project_id: int, year: int) -> None:
    _establish(client, project_id)
    assert client.post(f"/api/v1/projects/{project_id}/include-in-advancement", json={
        "advancement_year": year, "operator": "PMO", "reason": "既有推进",
    }).status_code == 200


def test_annual_budget_plan_derives_carryovers_and_saves_candidate_amounts_atomically(client, create_project_payload):
    carryover = client.post("/api/v1/projects", json=create_project_payload(name="续建项目", budget=80)).json()
    pool = client.post("/api/v1/projects", json=create_project_payload(name="新增项目", budget=50)).json()
    special = client.post("/api/v1/projects", json=create_project_payload(name="未立项候选", budget=20)).json()
    finished = client.post("/api/v1/projects", json=create_project_payload(name="完成项目", budget=10)).json()
    _active(client, carryover["id"], 2025)
    _establish(client, pool["id"])
    assert client.post(f"/api/v1/projects/{finished['id']}/pmo-override", json={"to_status": "closed", "operator": "PMO", "comment": "完成"}).status_code == 200

    plan = client.get("/api/v1/projects/annual-budget-plans/2027").json()
    indexed = {row["project_id"]: row for row in plan["members"]}
    assert indexed[carryover["id"]]["plan_kind"] == "carryover"
    assert indexed[carryover["id"]]["selected"] is True
    assert indexed[carryover["id"]]["planned_new_amount"] == 0
    assert indexed[pool["id"]]["selected"] is False
    assert indexed[pool["id"]]["default_planned_new_amount"] == 50
    assert indexed[special["id"]]["stage"] == "未立项"
    assert finished["id"] not in indexed

    saved = client.put("/api/v1/projects/annual-budget-plans/2027", json={"operator": "PMO", "members": [
        {"project_id": carryover["id"], "planned_new_amount": 15},
        {"project_id": pool["id"], "planned_new_amount": 50},
    ]})
    assert saved.status_code == 200
    saved_rows = {row["project_id"]: row for row in saved.json()["members"]}
    assert saved_rows[carryover["id"]]["planned_new_amount"] == 15
    assert saved_rows[pool["id"]]["selected"] is True
    assert saved.json()["planned_new_amount_total"] == 65
    assert client.get(f"/api/v1/projects/{pool['id']}").json()["stage"] == "项目库—未实施"

    rejected = client.put("/api/v1/projects/annual-budget-plans/2027", json={"operator": "PMO", "members": [
        {"project_id": carryover["id"], "planned_new_amount": -1},
    ]})
    assert rejected.status_code == 422
    assert client.get("/api/v1/projects/annual-budget-plans/2027").json()["planned_new_amount_total"] == 65


def test_annual_plan_confirmation_does_not_duplicate_carryover_cycle(client, create_project_payload):
    carryover = client.post("/api/v1/projects", json=create_project_payload(name="持续推进", budget=60)).json()
    candidate = client.post("/api/v1/projects", json=create_project_payload(name="年度新增", budget=40)).json()
    _active(client, carryover["id"], 2025); _establish(client, candidate["id"])
    assert client.put("/api/v1/projects/annual-budget-plans/2027", json={"operator": "PMO", "members": [
        {"project_id": carryover["id"], "planned_new_amount": 0},
        {"project_id": candidate["id"], "planned_new_amount": 40},
    ]}).status_code == 200
    before = client.get(f"/api/v1/projects/{carryover['id']}/advancement-cycles").json()
    confirmed = client.post("/api/v1/projects/annual-budget-plans/2027/confirm", json={"operator": "PMO", "normal_reason": "年度确认", "special_entries": []})
    assert confirmed.status_code == 200
    assert client.get(f"/api/v1/projects/{candidate['id']}").json()["stage"] == "项目库—推进中"
    assert client.get(f"/api/v1/projects/{carryover['id']}/advancement-cycles").json() == before


def test_current_year_confirmed_member_stays_new_and_zero_carryover_is_excluded_from_statistics(client, create_project_payload):
    carryover = client.post("/api/v1/projects", json=create_project_payload(name="零新增续建", budget=60)).json()
    candidate = client.post("/api/v1/projects", json=create_project_payload(name="本年新增", budget=40)).json()
    _active(client, carryover["id"], 2025); _establish(client, candidate["id"])
    assert client.put("/api/v1/projects/annual-budget-plans/2027", json={"operator": "PMO", "members": [
        {"project_id": carryover["id"], "planned_new_amount": 0},
        {"project_id": candidate["id"], "planned_new_amount": 40},
    ]}).status_code == 200
    assert client.post("/api/v1/projects/annual-budget-plans/2027/confirm", json={"operator": "PMO", "normal_reason": "年度确认", "special_entries": []}).status_code == 200

    plan = client.get("/api/v1/projects/annual-budget-plans/2027").json()
    rows = {row["project_id"]: row for row in plan["members"]}
    assert rows[carryover["id"]]["plan_kind"] == "carryover"
    assert rows[candidate["id"]]["plan_kind"] == "new_confirmed"
    assert plan["planned_project_count"] == 1
    assert plan["planned_new_amount_total"] == 40


def test_same_year_confirmation_stays_in_its_plan_and_future_year_becomes_carryover(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="当年纳入", budget=40)).json()
    _establish(client, project["id"])

    assert client.put("/api/v1/projects/annual-budget-plans/2026", json={"operator": "PMO", "members": [
        {"project_id": project["id"], "planned_new_amount": 40},
    ]}).status_code == 200
    before_confirmation = client.get(f"/api/v1/projects/{project['id']}").json()
    assert before_confirmation["planned_advancement_year"] == 2026
    assert before_confirmation["planned_advancement_status"] == "draft"

    assert client.post("/api/v1/projects/annual-budget-plans/2026/confirm", json={
        "operator": "PMO", "normal_reason": "年度确认", "special_entries": [],
    }).status_code == 200
    same_year = {row["project_id"]: row for row in client.get("/api/v1/projects/annual-budget-plans/2026").json()["members"]}
    previous_year = {row["project_id"]: row for row in client.get("/api/v1/projects/annual-budget-plans/2025").json()["members"]}
    next_year = {row["project_id"]: row for row in client.get("/api/v1/projects/annual-budget-plans/2027").json()["members"]}
    assert same_year[project["id"]]["plan_kind"] == "new_confirmed"
    assert same_year[project["id"]]["planned_new_amount"] == 40
    assert project["id"] not in previous_year
    assert next_year[project["id"]]["plan_kind"] == "carryover"
    assert next_year[project["id"]]["planned_new_amount"] == 0
    confirmed = client.get(f"/api/v1/projects/{project['id']}").json()
    assert confirmed["planned_advancement_year"] == 2026
    assert confirmed["planned_advancement_status"] == "confirmed"


def test_zero_amount_selected_project_is_retained_but_excluded_from_all_plan_counts(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="零安排项目", budget=40)).json()
    _establish(client, project["id"])
    response = client.put("/api/v1/projects/annual-budget-plans/2026", json={"operator": "PMO", "members": [
        {"project_id": project["id"], "planned_new_amount": 0, "planned_amount_is_manual": True},
    ]})
    assert response.status_code == 200
    plan = response.json()
    row = next(item for item in plan["members"] if item["project_id"] == project["id"])
    assert row["selected"] is True
    assert row["planned_amount_is_manual"] is True
    assert row["counts_toward_stats"] is False
    assert plan["planned_project_count"] == 0
    assert plan["category_stats"] == {}


def test_annual_exception_actions_cancel_defer_resume_and_special_are_atomic(client, create_project_payload):
    normal = client.post("/api/v1/projects", json=create_project_payload(name="可撤回项目", budget=40)).json()
    special = client.post("/api/v1/projects", json=create_project_payload(name="特批项目", budget=20)).json()
    _establish(client, normal["id"])
    assert client.put("/api/v1/projects/annual-budget-plans/2027", json={"operator": "PMO", "members": [{"project_id": normal["id"], "planned_new_amount": 40}]}).status_code == 200
    assert client.post("/api/v1/projects/annual-budget-plans/2027/confirm", json={"operator": "PMO", "normal_reason": "年度确认", "special_entries": []}).status_code == 200

    deferred = client.post("/api/v1/projects/annual-budget-plans/2027/exception-actions", json={"action": "defer", "operator": "PMO", "reason": "暂缓", "project_ids": [normal["id"]]})
    assert deferred.status_code == 200
    assert client.get(f"/api/v1/projects/{normal['id']}").json()["stage"] == "项目库—未实施"
    resumed = client.post("/api/v1/projects/annual-budget-plans/2027/exception-actions", json={"action": "resume", "operator": "PMO", "reason": "恢复", "project_ids": [normal["id"]]})
    assert resumed.status_code == 200
    assert client.get(f"/api/v1/projects/{normal['id']}").json()["stage"] == "项目库—推进中"
    cancelled = client.post("/api/v1/projects/annual-budget-plans/2027/exception-actions", json={"action": "cancel", "operator": "PMO", "reason": "误确认撤回", "project_ids": [normal["id"]]})
    assert cancelled.status_code == 200
    plan = client.get("/api/v1/projects/annual-budget-plans/2027").json()
    assert normal["id"] not in {row["project_id"] for row in plan["members"] if row["selected"]}

    special_result = client.post("/api/v1/projects/annual-budget-plans/2027/exception-actions", json={
        "action": "special", "operator": "PMO", "reason": "特批", "project_ids": [special["id"]],
        "special_entries": [{"project_id": special["id"], "reason": "特批", "approval_basis": "会议纪要"}],
    })
    assert special_result.status_code == 200
    special_row = next(row for row in special_result.json()["members"] if row["project_id"] == special["id"])
    assert special_row["plan_kind"] == "new_confirmed"


def test_financial_import_rejects_projects_outside_saved_annual_plan(client, create_project_payload):
    included = client.post("/api/v1/projects", json=create_project_payload(name="计划内", budget=40)).json()
    excluded = client.post("/api/v1/projects", json=create_project_payload(name="计划外", budget=30)).json()
    _establish(client, included["id"]); _establish(client, excluded["id"])
    assert client.put("/api/v1/projects/annual-budget-plans/2027", json={"operator": "PMO", "members": [{"project_id": included["id"], "planned_new_amount": 40}]}).status_code == 200
    frame = pd.DataFrame([
        {"项目编号": included["project_code"], "项目名称": included["name"], "资金号": "A001", "资金参考金额": 100, "分配金额": 40},
        {"项目编号": excluded["project_code"], "项目名称": excluded["name"], "资金号": "A001", "资金参考金额": 100, "分配金额": 30},
    ])
    content = io.BytesIO(); frame.to_excel(content, index=False)
    preview = client.post("/api/v1/funding/allocations/import/preview?planning_year=2027", files={"file": ("plan.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] == 1
    assert preview.json()["errors"][0]["code"] == "PROJECT_NOT_IN_ANNUAL_PLAN"


def test_supplement_includes_project_and_writes_same_annual_plan(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="补充项目", budget=35)).json()
    _establish(client, project["id"])
    response = client.post("/api/v1/projects/annual-budget-plans/2027/supplement", json={
        "operator": "PMO", "project_ids": [project["id"]], "reason": "方案补充",
    })
    assert response.status_code == 200
    row = next(item for item in response.json()["members"] if item["project_id"] == project["id"])
    assert row["member_status"] == "confirmed"
    assert row["planned_new_amount"] == 35
    assert client.get(f"/api/v1/projects/{project['id']}").json()["stage"] == "项目库—推进中"
