from __future__ import annotations


def _listed_project(client, project_id: int) -> dict:
    return next(
        item
        for item in client.get("/api/v1/projects", params={"page_size": 50}).json()["items"]
        if item["id"] == project_id
    )


def test_external_constraints_need_scope_confirmation_and_expose_effective_budget(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()

    initial = _listed_project(client, project["id"])
    assert initial["external_constraints_cleared"] == "true"
    assert initial["effective_budget"] == 100
    assert initial["effective_budget_source"] == "initial_budget"

    template = client.post(
        "/api/v1/external-constraint-templates",
        json={
            "name": "上级预算核定",
            "recommended_stage": "项目库—未实施",
            "is_blocking": True,
            "project_field_effects": {"effective_budget": "outcome.approved_budget"},
            "operator": "PMO",
        },
    )
    assert template.status_code == 200

    constraint = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"template_id": template.json()["id"], "operator": "PMO"},
    )
    assert constraint.status_code == 200
    assert client.post(
        f"/api/v1/projects/{project['id']}/confirm-external-constraint-scope",
        json={"operator": "PMO", "note": "本项目适用上级预算核定"},
    ).status_code == 200

    unresolved = _listed_project(client, project["id"])
    assert unresolved["external_constraints_cleared"] == "false"

    concluded = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints/{constraint.json()['id']}/actions",
        json={
            "action": "conclude",
            "operator": "PMO",
            "cleared": True,
            "outcome": {"approved_budget": 88.5, "result": "核定通过"},
        },
    )
    assert concluded.status_code == 200
    resolved = _listed_project(client, project["id"])
    assert resolved["external_constraints_cleared"] == "true"
    assert resolved["effective_budget"] == 88.5
    assert resolved["effective_budget_source"] == "budget_constraint"


def test_non_blocking_constraint_does_not_block_confirmed_external_conditions(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    template = client.post(
        "/api/v1/external-constraint-templates",
        json={"name": "信息备案", "is_blocking": False, "operator": "PMO"},
    ).json()
    created = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"template_id": template["id"], "operator": "PMO"},
    )
    assert created.status_code == 200
    assert client.post(
        f"/api/v1/projects/{project['id']}/confirm-external-constraint-scope",
        json={"operator": "PMO", "note": "仅适用非阻断备案"},
    ).status_code == 200
    assert _listed_project(client, project["id"])["external_constraints_cleared"] == "true"


def test_batch_constraint_can_be_saved_as_common_template_and_filtered_as_ongoing(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()

    created = client.post(
        "/api/v1/projects/batch-external-constraints",
        json={
            "project_ids": [project["id"]],
            "operator": "PMO",
            "constraints": [{"name": "上级预算核定", "is_blocking": True, "handling_status": "not_started"}],
            "save_as_common": True,
        },
    )
    assert created.status_code == 200
    assert any(item["name"] == "上级预算核定" for item in client.get("/api/v1/external-constraint-templates").json())

    assert client.post(
        f"/api/v1/projects/{project['id']}/confirm-external-constraint-scope",
        json={"operator": "PMO", "note": "本项目适用该约束"},
    ).status_code == 200
    rows = client.get("/api/v1/projects", params={"external_conditions": "ongoing", "page_size": 20})
    assert rows.status_code == 200
    assert [item["id"] for item in rows.json()["items"]] == [project["id"]]


def test_standard_project_list_projection_omits_legacy_status(client, create_project_payload):
    client.post("/api/v1/projects", json=create_project_payload())
    listed = client.get("/api/v1/projects", params={"page_size": 10})
    assert listed.status_code == 200
    assert "current_status" not in listed.json()["items"][0]
    assert listed.json()["items"][0]["stage"] == "未立项"


def test_completion_can_create_and_reopen_can_void_a_milestone(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    item = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "立项发文", "operator": "PMO"},
    ).json()
    completed = client.post(
        f"/api/v1/projects/{project['id']}/work-items/{item['id']}/complete",
        json={"operator": "PMO", "result": "已发文", "create_milestone": True, "milestone_name": "项目正式立项"},
    )
    assert completed.status_code == 200
    timeline = client.get(f"/api/v1/projects/{project['id']}/management-timeline").json()
    assert any(event["summary"] == "项目正式立项" for event in timeline)
    assert client.post(
        f"/api/v1/projects/{project['id']}/work-items/{item['id']}/reopen",
        json={"operator": "PMO", "reason": "文件号有误"},
    ).status_code == 200
    milestones = client.get(f"/api/v1/projects/{project['id']}/milestones").json()
    assert milestones[0]["is_void"] == 1


def test_work_package_can_preview_and_apply_external_constraints(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    template = client.post(
        "/api/v1/external-constraint-templates",
        json={"name": "采购准入确认", "is_blocking": True, "operator": "PMO"},
    ).json()
    package = client.post(
        "/api/v1/work-packages",
        json={
            "name": "采购前期准备（含约束）",
            "operator": "PMO",
            "items": [{"name": "采购需求书"}],
            "constraints": [{"template_id": template["id"]}],
        },
    )
    assert package.status_code == 200
    assert package.json()["constraints"][0]["template_id"] == template["id"]
    applied = client.post(
        "/api/v1/projects/apply-work-package",
        json={"project_ids": [project["id"]], "package_id": package.json()["id"], "operator": "PMO"},
    )
    assert applied.status_code == 200
    assert applied.json()["constraint_created_count"] == 1
    assert client.get(f"/api/v1/projects/{project['id']}/external-constraints").json()[0]["name"] == "采购准入确认"
