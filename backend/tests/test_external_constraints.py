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
                "set_effective_budget_source": True,
                "reason": "采用本次核定预算",
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


def test_known_unresolved_blocking_constraint_is_pending_without_scope_confirmation(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    constraint = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"name": "待核实政策", "is_blocking": True, "operator": "PMO"},
    )
    assert constraint.status_code == 200

    listed = _listed_project(client, project["id"])
    assert listed["external_constraints_cleared"] == "false"


def test_marking_constraint_not_applicable_requires_a_reason(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    constraint = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"name": "专项备案", "is_blocking": True, "operator": "PMO"},
    ).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints/{constraint['id']}/actions",
        json={"action": "mark_not_applicable", "operator": "PMO"},
    )
    assert response.status_code == 422


def test_budget_source_is_explicit_and_switches_atomically(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    first = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"name": "预算核定甲", "is_blocking": True, "operator": "PMO"},
    ).json()
    second = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"name": "预算核定乙", "is_blocking": True, "operator": "PMO"},
    ).json()

    for constraint, budget, current in ((first, 88.5, True), (second, 90, False)):
        response = client.post(
            f"/api/v1/projects/{project['id']}/external-constraints/{constraint['id']}/actions",
            json={
                "action": "conclude",
                "operator": "PMO",
                "cleared": True,
                "outcome": {"approved_budget": budget},
                "set_effective_budget_source": current,
                "reason": "登记预算核定结论",
            },
        )
        assert response.status_code == 200

    assert _listed_project(client, project["id"])["effective_budget"] == 88.5
    switched = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints/{second['id']}/actions",
        json={"action": "set_effective_budget_source", "operator": "PMO", "reason": "采用最新核定"},
    )
    assert switched.status_code == 200
    assert _listed_project(client, project["id"])["effective_budget"] == 90
    constraints = client.get(f"/api/v1/projects/{project['id']}/external-constraints").json()
    assert sum(item["is_effective_budget_source"] for item in constraints) == 1


def test_batch_template_scope_rejects_mismatched_project_type_before_creating(client, create_project_payload):
    software = client.post("/api/v1/projects", json=create_project_payload(project_type="teaching_software")).json()
    laboratory = client.post("/api/v1/projects", json=create_project_payload(name="场所项目", project_type="practical_teaching_site")).json()
    template = client.post(
        "/api/v1/external-constraint-templates",
        json={"name": "软件专项审核", "scope_kind": "project_type", "scope_value": "software", "operator": "PMO"},
    ).json()

    response = client.post(
        "/api/v1/projects/batch-external-constraints",
        json={"project_ids": [software["id"], laboratory["id"]], "operator": "PMO", "constraints": [{"template_id": template["id"]}]},
    )
    assert response.status_code == 422
    assert client.get(f"/api/v1/projects/{software['id']}/external-constraints").json() == []
    assert client.get(f"/api/v1/projects/{laboratory['id']}/external-constraints").json() == []


def test_constraint_template_rejects_unsupported_scope_kind(client):
    response = client.post(
        "/api/v1/external-constraint-templates",
        json={"name": "无效范围模板", "scope_kind": "year", "operator": "PMO"},
    )
    assert response.status_code == 422


def test_constraint_conclusion_is_visible_in_management_timeline(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    constraint = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"name": "备案", "is_blocking": False, "operator": "PMO"},
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/external-constraints/{constraint['id']}/actions",
        json={"action": "conclude", "operator": "PMO", "outcome": {"result": "已备案"}, "reason": "登记备案结果"},
    ).status_code == 200

    timeline = client.get(f"/api/v1/projects/{project['id']}/management-timeline").json()
    assert any(item["kind"] == "EXTERNAL_CONSTRAINT_CONCLUDE" for item in timeline)


def test_constraint_progress_logs_are_editable_soft_deleted_and_excluded_from_default_list(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    constraint = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"name": "数据安全审核", "operator": "PMO"},
    ).json()
    endpoint = f"/api/v1/projects/{project['id']}/external-constraints/{constraint['id']}/progress-logs"

    created = client.post(endpoint, json={"operator": "PMO", "content": "已提交材料"})
    assert created.status_code == 200
    edited = client.patch(f"{endpoint}/{created.json()['id']}", json={"operator": "PMO", "content": "已补充材料"})
    assert edited.status_code == 200
    assert edited.json()["content"] == "已补充材料"
    assert client.request("DELETE", f"{endpoint}/{created.json()['id']}", json={"operator": "PMO", "reason": "重复记录"}).status_code == 200
    assert client.get(endpoint).json() == []
    audit = client.get(f"/api/v1/projects/{project['id']}/audit-events").json()
    assert any(event["event_type"] == "EXTERNAL_CONSTRAINT_PROGRESS_DELETED" for event in audit)


def test_external_pending_count_ignores_non_blocking_constraints_and_exposes_compact_cells(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    non_blocking = client.post(
        f"/api/v1/projects/{project['id']}/external-constraints",
        json={"name": "普通备案", "is_blocking": False, "operator": "PMO"},
    )
    assert non_blocking.status_code == 200
    listed = _listed_project(client, project["id"])
    assert listed["external_constraints_cleared"] == "true"
    assert listed["external_constraint_open_count"] == 0
    assert listed["external_constraint_states"][0]["name"] == "普通备案"


def test_batch_clear_creates_per_project_and_batch_audit_records(client, create_project_payload):
    first = client.post("/api/v1/projects", json=create_project_payload(name="项目甲")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="项目乙")).json()
    template = client.post("/api/v1/external-constraint-templates", json={"name": "统一政策", "operator": "PMO"}).json()
    created = client.post("/api/v1/projects/batch-external-constraints", json={
        "project_ids": [first["id"], second["id"]], "operator": "PMO", "constraints": [{"template_id": template["id"]}],
    })
    assert created.status_code == 200
    preview = client.post("/api/v1/projects/batch-external-constraint-actions/preflight", json={
        "project_ids": [first["id"], second["id"]], "template_id": template["id"], "action": "clear", "operator": "PMO",
    })
    assert preview.status_code == 200
    assert len(preview.json()["eligible"]) == 2
    executed = client.post("/api/v1/projects/batch-external-constraint-actions", json={
        "project_ids": [first["id"], second["id"]], "template_id": template["id"], "action": "clear", "operator": "PMO", "reason": "政策已明确",
    })
    assert executed.status_code == 200
    for project in (first, second):
        constraint = client.get(f"/api/v1/projects/{project['id']}/external-constraints").json()[0]
        assert constraint["clearance_status"] == "cleared"
        audit = client.get(f"/api/v1/projects/{project['id']}/audit-events").json()
        assert any(event["event_type"] == "EXTERNAL_CONSTRAINT_CLEAR" for event in audit)
    assert executed.json()["batch_audit_id"]


def test_batch_constraint_action_accepts_exact_project_instance_targets(client, create_project_payload):
    first = client.post("/api/v1/projects", json=create_project_payload(name="精确目标甲")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="精确目标乙")).json()
    created = client.post("/api/v1/projects/batch-external-constraints", json={
        "project_ids": [first["id"], second["id"]], "operator": "PMO", "constraints": [{"name": "同名约束", "outcome_schema": {"kind": "custom"}}],
    })
    assert created.status_code == 200
    first_constraint = client.get(f"/api/v1/projects/{first['id']}/external-constraints").json()[0]
    second_constraint = client.get(f"/api/v1/projects/{second['id']}/external-constraints").json()[0]
    payload = {
        "project_ids": [first["id"], second["id"]],
        "targets": [{"project_id": first["id"], "constraint_id": first_constraint["id"]}, {"project_id": second["id"], "constraint_id": second_constraint["id"]}],
        "action": "progress", "operator": "PMO", "defaults": {"content": "统一办理进展"},
    }
    assert client.post("/api/v1/projects/batch-external-constraint-actions/preflight", json=payload).json()["ineligible"] == []
    assert client.post("/api/v1/projects/batch-external-constraint-actions", json=payload).status_code == 200
    assert client.get(f"/api/v1/projects/{first['id']}/external-constraints/{first_constraint['id']}/progress-logs").json()[0]["content"] == "统一办理进展"


def test_batch_budget_conclusion_requires_per_project_results(client, create_project_payload):
    first = client.post("/api/v1/projects", json=create_project_payload(name="预算项目甲")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="预算项目乙")).json()
    template = client.post("/api/v1/external-constraint-templates", json={"name": "预算批量核定", "outcome_schema": {"kind": "budget_determination"}, "operator": "PMO"}).json()
    assert client.post("/api/v1/projects/batch-external-constraints", json={"project_ids": [first["id"], second["id"]], "operator": "PMO", "constraints": [{"template_id": template["id"]}]}).status_code == 200
    rejected = client.post("/api/v1/projects/batch-external-constraint-actions", json={"project_ids": [first["id"], second["id"]], "template_id": template["id"], "action": "conclude", "operator": "PMO", "outcome": {"approved_budget": 80}})
    assert rejected.status_code == 422
    assert all(item["handling_status"] == "not_started" for project in (first, second) for item in client.get(f"/api/v1/projects/{project['id']}/external-constraints").json())
