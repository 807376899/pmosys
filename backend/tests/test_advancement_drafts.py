from __future__ import annotations


def _establish(client, project_id: int) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/pmo-override",
        json={"to_status": "established", "operator": "PMO", "comment": "测试立项"},
    )
    assert response.status_code == 200


def test_annual_draft_adjustment_keeps_project_lifecycle_unchanged(client, create_project_payload):
    unestablished = client.post("/api/v1/projects", json=create_project_payload(name="待特批项目", budget=30)).json()
    pool = client.post("/api/v1/projects", json=create_project_payload(name="待纳入项目", budget=50)).json()
    _establish(client, pool["id"])

    added = client.post("/api/v1/projects/advancement-drafts/2027/members", json={
        "project_ids": [unestablished["id"], pool["id"]], "operator": "PMO",
    })
    assert added.status_code == 200
    draft = client.get("/api/v1/projects/advancement-drafts/2027").json()
    assert draft["member_count"] == 2
    assert draft["effective_budget_total"] == 80
    assert {member["next_action"] for member in draft["members"]} == {"special", "include"}
    assert client.get(f"/api/v1/projects/{unestablished['id']}").json()["stage"] == "未立项"
    assert client.get(f"/api/v1/projects/{pool['id']}").json()["stage"] == "项目库—未实施"
    assert client.get(f"/api/v1/projects/{unestablished['id']}/advancement-cycles").json() == []
    assert client.get(f"/api/v1/projects/{pool['id']}/advancement-cycles").json() == []


def test_draft_summary_reuses_same_year_funding_arrangements(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="草案资金项目", budget=80)).json()
    assert client.post("/api/v1/projects/advancement-drafts/2027/members", json={"project_ids": [project["id"]], "operator": "PMO"}).status_code == 200
    assert client.post("/api/v1/funding/arrangements", json={
        "planning_year": 2027, "name": "2027 年筹划资金", "estimated_amount": 100,
        "fund_code": "", "note": "", "operator": "PMO",
    }).status_code == 200
    draft = client.get("/api/v1/projects/advancement-drafts/2027").json()
    assert draft["estimated_total"] == 100
    assert draft["effective_budget_total"] == 80
    assert draft["difference"] == 20
    assert draft["arrangements"][0]["name"] == "2027 年筹划资金"


def test_draft_confirmation_mixes_normal_special_and_existing_advancement_atomically(client, create_project_payload):
    special = client.post("/api/v1/projects", json=create_project_payload(name="未立项特批", budget=30)).json()
    normal = client.post("/api/v1/projects", json=create_project_payload(name="正常纳入", budget=50)).json()
    active = client.post("/api/v1/projects", json=create_project_payload(name="已在推进", budget=70)).json()
    _establish(client, normal["id"]); _establish(client, active["id"])
    assert client.post(f"/api/v1/projects/{active['id']}/include-in-advancement", json={
        "advancement_year": 2027, "operator": "PMO", "reason": "已纳入",
    }).status_code == 200
    before_cycles = client.get(f"/api/v1/projects/{active['id']}/advancement-cycles").json()
    assert client.post("/api/v1/projects/advancement-drafts/2027/members", json={
        "project_ids": [special["id"], normal["id"], active["id"]], "operator": "PMO",
    }).status_code == 200

    confirmed = client.post("/api/v1/projects/advancement-drafts/2027/confirm", json={
        "operator": "PMO", "normal_reason": "年度确认纳入",
        "special_entries": [{"project_id": special["id"], "reason": "提前启动", "approval_basis": "专项批准"}],
    })
    assert confirmed.status_code == 200
    assert client.get(f"/api/v1/projects/{normal['id']}").json()["stage"] == "项目库—推进中"
    special_detail = client.get(f"/api/v1/projects/{special['id']}").json()
    assert special_detail["stage"] == "未立项"
    assert special_detail["advancement"]["status"] == "special_active"
    assert client.get(f"/api/v1/projects/{active['id']}/advancement-cycles").json() == before_cycles
    assert {member["member_status"] for member in client.get("/api/v1/projects/advancement-drafts/2027").json()["members"]} == {"confirmed"}


def test_draft_confirmation_includes_normal_project_without_reason(client, create_project_payload):
    normal = client.post("/api/v1/projects", json=create_project_payload(name="无需理由的正常纳入", budget=50)).json()
    _establish(client, normal["id"])
    assert client.post("/api/v1/projects/advancement-drafts/2027/members", json={"project_ids": [normal["id"]], "operator": "PMO"}).status_code == 200

    confirmed = client.post("/api/v1/projects/advancement-drafts/2027/confirm", json={"operator": "PMO", "special_entries": []})

    assert confirmed.status_code == 200
    assert client.get(f"/api/v1/projects/{normal['id']}").json()["stage"] == "项目库—推进中"


def test_draft_rejects_terminal_projects_and_confirmation_rolls_back_on_missing_special_fields(client, create_project_payload):
    completed = client.post("/api/v1/projects", json=create_project_payload(name="已完成项目", budget=10)).json()
    normal = client.post("/api/v1/projects", json=create_project_payload(name="正常项目", budget=20)).json()
    special = client.post("/api/v1/projects", json=create_project_payload(name="特批项目", budget=30)).json()
    assert client.post(f"/api/v1/projects/{completed['id']}/pmo-override", json={"to_status": "closed", "operator": "PMO", "comment": "测试终态"}).status_code == 200
    rejected = client.post("/api/v1/projects/advancement-drafts/2027/members", json={"project_ids": [completed["id"]], "operator": "PMO"})
    assert rejected.status_code == 422

    _establish(client, normal["id"])
    assert client.post("/api/v1/projects/advancement-drafts/2027/members", json={"project_ids": [normal["id"], special["id"]], "operator": "PMO"}).status_code == 200
    rejected_confirm = client.post("/api/v1/projects/advancement-drafts/2027/confirm", json={"operator": "PMO", "normal_reason": "年度安排", "special_entries": []})
    assert rejected_confirm.status_code == 422
    assert client.get(f"/api/v1/projects/{normal['id']}").json()["stage"] == "项目库—未实施"
    assert client.get(f"/api/v1/projects/{special['id']}").json()["stage"] == "未立项"
    assert client.get(f"/api/v1/projects/{normal['id']}/advancement-cycles").json() == []


def test_confirmed_draft_member_can_be_deferred_and_retains_draft_audit(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="待暂缓项目", budget=40)).json()
    _establish(client, project["id"])
    assert client.post("/api/v1/projects/advancement-drafts/2027/members", json={"project_ids": [project["id"]], "operator": "PMO"}).status_code == 200
    assert client.post("/api/v1/projects/advancement-drafts/2027/confirm", json={"operator": "PMO", "normal_reason": "确认推进"}).status_code == 200
    deferred = client.post(f"/api/v1/projects/advancement-drafts/2027/members/{project['id']}/defer", json={"operator": "PMO", "reason": "年度调整"})
    assert deferred.status_code == 200
    assert deferred.json()["member_count"] == 0
    assert client.get(f"/api/v1/projects/{project['id']}").json()["stage"] == "项目库—未实施"
    assert client.get(f"/api/v1/projects/{project['id']}/advancement-cycles").json()[-1]["status"] == "deferred"
    events = client.get(f"/api/v1/projects/{project['id']}/audit-events").json()
    assert any(event["event_type"] == "PROJECT_ADVANCEMENT_DEFERRED" for event in events)
