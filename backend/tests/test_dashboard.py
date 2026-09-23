from __future__ import annotations


def test_dashboard_groups(client, create_project_payload):
    client.post("/api/v1/projects", json=create_project_payload())
    response = client.get("/api/v1/dashboard/groups")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 5
    assert [item["key"] for item in items] == [
        "pre_establish",
        "pool_pending",
        "pool_active",
        "completed",
        "abandoned",
    ]
    assert items[0]["label"] == "未立项"
    assert items[0]["count"] == 1
    assert items[0]["total_budget"] == "100"
    assert items[0]["total_approved_budget"] == "0"
    assert items[0]["total_contract_amount"] == "0"


def test_completed_group_includes_contract_amount(client, create_project_payload):
    project = client.post(
        "/api/v1/projects",
        json=create_project_payload(name="已完成合同项目", contract_amount=66),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/transitions",
        json={
            "to_status": "closed",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "PMO办公室",
            "comment": "历史项目补录关闭",
            "force": True,
        },
    )

    response = client.get("/api/v1/dashboard/groups")
    assert response.status_code == 200
    completed = next(item for item in response.json() if item["key"] == "completed")
    assert completed["count"] == 1
    assert completed["total_contract_amount"] == "66"


def test_included_project_uses_advancing_stage_for_groups_and_list(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="推进项目")).json()
    client.post(f"/api/v1/projects/{project['id']}/transitions", json={"to_status": "under_review", "operator": "PMO", "operator_role": "PMO", "approver": "PMO", "comment": "历史流程"})
    client.post(f"/api/v1/projects/{project['id']}/transitions", json={"to_status": "established", "operator": "PMO", "operator_role": "PMO", "approver": "PMO", "comment": "立项"})
    client.post(f"/api/v1/projects/{project['id']}/transitions", json={"to_status": "submission_review", "operator": "PMO", "operator_role": "PMO", "comment": "历史送审"})
    included = client.post(f"/api/v1/projects/{project['id']}/include-in-advancement", json={"operator": "PMO", "reason": "年度计划", "advancement_year": 2026})
    assert included.status_code == 200

    advancing = client.get("/api/v1/projects", params={"group": "pool_active"}).json()["items"]
    pending = client.get("/api/v1/projects", params={"group": "pool_pending"}).json()["items"]
    groups = {item["key"]: item for item in client.get("/api/v1/dashboard/groups").json()}

    assert [item["id"] for item in advancing] == [project["id"]]
    assert pending == []
    assert groups["pool_active"]["count"] == 1


def test_advancing_management_view_overlaps_special_unestablished_projects(client, create_project_payload):
    normal = client.post("/api/v1/projects", json=create_project_payload(name="正常推进项目")).json()
    client.post(f"/api/v1/projects/{normal['id']}/pmo-override", json={"operator": "PMO", "comment": "测试立项", "to_status": "established"})
    assert client.post(
        f"/api/v1/projects/{normal['id']}/include-in-advancement",
        json={"operator": "PMO", "reason": "年度安排", "advancement_year": 2026},
    ).status_code == 200

    special = client.post("/api/v1/projects", json=create_project_payload(name="特批推进项目")).json()
    assert client.post(
        f"/api/v1/projects/{special['id']}/special-include-in-advancement",
        json={"operator": "PMO", "reason": "窗口紧张", "approval_basis": "PMO 特批", "advancement_year": 2026},
    ).status_code == 200

    active_ids = {item["id"] for item in client.get("/api/v1/projects", params={"group": "pool_active"}).json()["items"]}
    unestablished_ids = {item["id"] for item in client.get("/api/v1/projects", params={"group": "pre_establish"}).json()["items"]}
    groups = {item["key"]: item for item in client.get("/api/v1/dashboard/groups").json()}

    assert active_ids == {normal["id"], special["id"]}
    assert special["id"] in unestablished_ids
    assert groups["pool_active"]["label"] == "推进中"
    assert groups["pool_active"]["count"] == 2


def test_dashboard_summary_project_library_metrics(client, create_project_payload):
    client.post("/api/v1/projects", json=create_project_payload(name="草稿项目", budget=10))
    reviewing = client.post("/api/v1/projects", json=create_project_payload(name="评审项目", budget=20)).json()
    library = client.post("/api/v1/projects", json=create_project_payload(name="项目库项目", budget=30)).json()
    reviewing_submission = client.post("/api/v1/projects", json=create_project_payload(name="送审项目", budget=40)).json()
    reviewed = client.post("/api/v1/projects", json=create_project_payload(name="已审核项目", budget=50)).json()

    client.post(
        f"/api/v1/projects/{reviewing['id']}/transitions",
        json={
            "to_status": "under_review",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "周主任",
            "comment": "提交评审",
            "deliverable": "项目申报书",
        },
    )
    client.post(
        f"/api/v1/projects/{library['id']}/transitions",
        json={
            "to_status": "under_review",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "周主任",
            "comment": "提交评审",
            "deliverable": "项目申报书",
        },
    )
    client.post(
        f"/api/v1/projects/{library['id']}/transitions",
        json={
            "to_status": "established",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "评审委员会",
            "comment": "评审通过",
            "deliverable": "评审通过决议",
        },
    )
    client.post(
        f"/api/v1/projects/{reviewing_submission['id']}/transitions",
        json={
            "to_status": "under_review",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "周主任",
            "comment": "提交评审",
            "deliverable": "项目申报书",
        },
    )
    client.post(
        f"/api/v1/projects/{reviewing_submission['id']}/transitions",
        json={
            "to_status": "established",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "评审委员会",
            "comment": "评审通过",
            "deliverable": "评审通过决议",
        },
    )
    client.post(
        f"/api/v1/projects/{reviewing_submission['id']}/transitions",
        json={
            "to_status": "submission_review",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "comment": "进入送审",
            "deliverable": "送审材料",
        },
    )
    client.post(
        f"/api/v1/projects/{reviewed['id']}/transitions",
        json={
            "to_status": "under_review",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "周主任",
            "comment": "提交评审",
            "deliverable": "项目申报书",
        },
    )
    client.post(
        f"/api/v1/projects/{reviewed['id']}/transitions",
        json={
            "to_status": "established",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "评审委员会",
            "comment": "评审通过",
            "deliverable": "评审通过决议",
        },
    )
    client.post(
        f"/api/v1/projects/{reviewed['id']}/transitions",
        json={
            "to_status": "submission_review",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "comment": "进入送审",
            "deliverable": "送审材料",
            "approved_budget": 36,
        },
    )
    client.post(
        f"/api/v1/projects/{reviewed['id']}/transitions",
        json={
            "to_status": "procuring",
            "operator": "PMO办公室",
            "operator_role": "PMO",
            "approver": "主管部门",
            "comment": "送审通过",
            "deliverable": "审批批复",
        },
    )

    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_projects"] == 5
    assert body["project_library_count"] == 3
    assert body["project_library_total_budget"] == "120"
    assert body["review_in_progress_count"] == 1
    assert body["reviewed_count"] == 1
    assert body["reviewed_total_approved_budget"] == "36"


def test_not_found_error_uses_uniform_shape(client):
    response = client.get("/api/v1/unknown-path")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert "message" in body
