from __future__ import annotations


def _create(client, payload):
    return client.post("/api/v1/projects", json=payload).json()


def test_batch_preview_and_execute_partial_success(client, create_project_payload):
    p1 = _create(client, create_project_payload(name="A"))
    p2 = _create(client, create_project_payload(name="B"))
    client.post(
        f"/api/v1/projects/{p1['id']}/transitions",
        json={
            "to_status": "under_review",
            "operator": "王敏",
            "operator_role": "PMO",
            "approver": "周主任",
            "comment": "提交评审",
            "deliverable": "项目申报书",
            "force": False,
            "approved_budget": None,
        },
    )
    preview = client.post(
        "/api/v1/projects/batch-transition/preview",
        json={
            "project_ids": [p1["id"], p2["id"]],
            "to_status": "under_review",
            "operator_role": "PMO",
            "force": False,
        },
    )
    assert preview.status_code == 200
    assert preview.json()["conflicts"]

    execute = client.post(
        "/api/v1/projects/batch-transition",
        json={
            "project_ids": [p1["id"], p2["id"]],
            "to_status": "under_review",
            "operator": "王敏",
            "operator_role": "PMO",
            "approver": "周主任",
            "comment": "批量提交流转",
            "deliverable": "项目申报书",
            "force": False,
            "approved_budget": None,
        },
    )
    assert execute.status_code == 200
    body = execute.json()
    assert body["success"] == 1
    assert body["failed"] == 1


def test_direct_stage_establishment_allows_only_terminal_work_items_and_records_document(client, create_project_payload):
    """Normal establishment must not be blocked by completed/cancelled/skipped/not-applicable items."""
    project = _create(client, create_project_payload(name="可立项项目"))
    completed = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "已完成事项", "operator": "PMO"}).json()
    cancelled = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "已取消事项", "operator": "PMO"}).json()
    skipped = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "已跳过事项", "operator": "PMO"}).json()
    client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "不适用事项", "operator": "PMO", "status": "not_applicable"})
    assert client.post(f"/api/v1/projects/{project['id']}/work-items/{completed['id']}/complete", json={"operator": "PMO", "completed_on": "2026-09-15"}).status_code == 200
    assert client.post(f"/api/v1/projects/{project['id']}/work-items/{cancelled['id']}/cancel", json={"operator": "PMO", "reason": "无需办理"}).status_code == 200
    assert client.post(f"/api/v1/projects/{project['id']}/work-items/{skipped['id']}/skip", json={"operator": "PMO", "reason": "无需办理"}).status_code == 200

    response = client.post(
        "/api/v1/projects/batch-stage-advance",
        json={"project_ids": [project["id"]], "action": "establish", "operator": "PMO", "establishment_document_no": "杭校立〔2026〕12号"},
    )

    assert response.status_code == 200
    detail = client.get(f"/api/v1/projects/{project['id']}").json()
    assert detail["stage"] == "项目库—未实施"
    assert detail["establishment_document_no"] == "杭校立〔2026〕12号"
    history = client.get(f"/api/v1/projects/{project['id']}/history").json()
    assert history[-1]["action"] == "登记立项并进入项目库"


def test_direct_stage_establishment_rejects_unfinished_item_atomically(client, create_project_payload):
    """One unfinished item must reject the whole direct Stage request without writing either project."""
    blocked = _create(client, create_project_payload(name="有未完成事项"))
    allowed = _create(client, create_project_payload(name="可立项但应回滚"))
    client.post(f"/api/v1/projects/{blocked['id']}/work-items", json={"name": "仍在办理", "operator": "PMO", "status": "in_progress"})

    response = client.post(
        "/api/v1/projects/batch-stage-advance",
        json={"project_ids": [blocked["id"], allowed["id"]], "action": "establish", "operator": "PMO", "establishment_document_no": "杭校立〔2026〕13号"},
    )

    assert response.status_code == 422
    assert "有未完成事项" in response.text
    assert "仍在办理" in response.text
    for project in (blocked, allowed):
        detail = client.get(f"/api/v1/projects/{project['id']}").json()
        assert detail["stage"] == "未立项"
        assert not detail["establishment_document_no"]


def test_direct_stage_completion_closes_active_cycle_and_sets_completion_date(client, create_project_payload):
    """A progressing project with no open items completes its Stage and active advancement cycle together."""
    project = _create(client, create_project_payload(name="可完成项目"))
    assert client.post(
        "/api/v1/projects/batch-stage-advance",
        json={"project_ids": [project["id"]], "action": "establish", "operator": "PMO", "establishment_document_no": "杭校立〔2026〕14号"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project['id']}/include-in-advancement",
        json={"operator": "PMO", "reason": "年度计划", "advancement_year": 2026},
    ).status_code == 200

    response = client.post(
        "/api/v1/projects/batch-stage-advance",
        json={"project_ids": [project["id"]], "action": "complete", "operator": "PMO"},
    )

    assert response.status_code == 200
    detail = client.get(f"/api/v1/projects/{project['id']}").json()
    assert detail["stage"] == "已完成"
    assert detail["actual_end_date"]
    cycles = client.get(f"/api/v1/projects/{project['id']}/advancement-cycles").json()
    assert cycles[-1]["status"] == "completed"
