from __future__ import annotations


def test_zero_blocking_constraints_are_ready_and_dashboard_uses_effective_budget(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(budget=120)).json()
    client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={"to_status": "established", "operator": "PMO", "comment": "测试立项"})
    listed = client.get("/api/v1/projects", params={"page_size": 20}).json()["items"]
    assert next(item for item in listed if item["id"] == project["id"])["external_constraints_cleared"] == "true"
    summary = client.get("/api/v1/dashboard/summary").json()
    assert summary["external_conditions_ready_count"] == 1
    assert summary["external_conditions_ready_effective_budget"] == 120


def test_project_edit_requires_audited_operator_and_reason(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    denied = client.patch(f"/api/v1/projects/{project['id']}", json={"name": "修正名称"})
    assert denied.status_code == 422
    updated = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "修正名称", "budget": 110, "operator": "PMO", "reason": "导入金额录错"},
    )
    assert updated.status_code == 200
    audit = client.get(f"/api/v1/projects/{project['id']}/audit-events").json()
    assert audit[0]["event_type"] == "PROJECT_UPDATED"
    assert audit[0]["reason"] == "导入金额录错"


def test_progress_log_can_be_updated_and_soft_deleted(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    item = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "预算审核", "operator": "PMO"}).json()
    log = client.post(
        f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs",
        json={"operator": "PMO", "content": "已提交材料"},
    ).json()
    assert client.patch(
        f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs/{log['id']}",
        json={"operator": "PMO", "content": "已补齐材料"},
    ).status_code == 200
    assert client.request(
        "DELETE",
        f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs/{log['id']}",
        json={"operator": "PMO", "reason": "重复录入"},
    ).status_code == 200
    assert client.get(f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs").json() == []


def test_used_template_archives_but_never_deletes_project_instances(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    client.post(
        "/api/v1/projects/batch-work-items",
        json={"project_ids": [project["id"]], "operator": "PMO", "items": [{"name": "专家评审"}], "save_as_common": True},
    )
    template = next(item for item in client.get("/api/v1/work-item-templates").json() if item["name"] == "专家评审")
    archived = client.post(f"/api/v1/work-item-templates/{template['id']}/archive", json={"operator": "PMO", "reason": "模板过期"})
    assert archived.status_code == 200
    assert all(item["id"] != template["id"] for item in client.get("/api/v1/work-item-templates").json())
    assert client.get(f"/api/v1/projects/{project['id']}/work-items").json()[0]["name"] == "专家评审"


def test_unestablished_special_advancement_keeps_stage_and_exposes_management_label(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/special-include-in-advancement",
        json={"advancement_year": 2026, "reason": "时间窗口紧张", "approval_basis": "PMO 特批", "operator": "PMO"},
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "未立项"
    assert response.json()["advancement"]["status"] == "special_active"
    listed = client.get("/api/v1/projects", params={"advancement_status": "special_active"}).json()["items"]
    assert [item["id"] for item in listed] == [project["id"]]


def test_project_list_projects_uses_unified_order_for_summary(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    first = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "PMO 审核", "flow_group": "main", "sequence_rank": 100, "status": "not_started", "operator": "PMO"},
    ).json()
    second = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "预算结论补充", "status": "in_progress", "operator": "PMO"},
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "材料补充", "flow_group": "independent", "status": "in_progress", "operator": "PMO"},
    )

    listed = client.get("/api/v1/projects").json()["items"]
    projection = next(item for item in listed if item["id"] == project["id"])
    assert [item["id"] for item in projection["work_item_summary"][:2]] == [first["id"], second["id"]]
    assert "next_key_node" not in projection
    assert projection["active_work_item_count"] == 3


def test_summary_keeps_focus_items_without_reordering_the_list(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "主流程节点", "flow_group": "main", "sequence_rank": 100, "operator": "PMO"},
    )
    attention = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "持续重点关注", "track_as_key_node": True, "operator": "PMO"},
    ).json()
    recent = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "刚刚推进的事项", "status": "in_progress", "operator": "PMO"},
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/work-items/{recent['id']}/progress-logs",
        json={"operator": "PMO", "content": "刚完成本次沟通"},
    ).status_code == 200

    projection = next(item for item in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"] if item["id"] == project["id"])
    assert [item["name"] for item in projection["work_item_summary"]] == ["主流程节点", "持续重点关注"]
    assert projection["work_item_summary"][1]["id"] == attention["id"]


def test_batch_groups_existing_same_name_items_without_creating_or_changing_them(client, create_project_payload):
    """A batch schedules existing instances; it never creates a second Work Item."""
    first = client.post("/api/v1/projects", json=create_project_payload(name="批次甲")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="批次乙")).json()
    first_item = client.post(
        f"/api/v1/projects/{first['id']}/work-items",
        json={"name": "专家评审", "operator": "PMO", "status": "not_started"},
    ).json()
    second_item = client.post(
        f"/api/v1/projects/{second['id']}/work-items",
        json={"name": "专家评审", "operator": "PMO", "status": "not_started"},
    ).json()

    created = client.post(
        "/api/v1/work-item-batches",
        json={
            "name": "9 月第 1 批专家评审",
            "work_item_name": "专家评审",
            "scheduled_on": "2026-09-25",
            "operator": "PMO",
            "targets": [
                {"project_id": first["id"], "work_item_id": first_item["id"]},
                {"project_id": second["id"], "work_item_id": second_item["id"]},
            ],
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "open"
    assert [member["work_item_id"] for member in body["members"]] == [first_item["id"], second_item["id"]]
    for project, item in ((first, first_item), (second, second_item)):
        items = client.get(f"/api/v1/projects/{project['id']}/work-items").json()
        assert [(entry["id"], entry["status"]) for entry in items] == [(item["id"], "not_started")]


def test_batch_completion_and_rehandle_preserve_the_original_item_instance(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="批次完成项目")).json()
    item = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "专家评审", "operator": "PMO"},
    ).json()
    batch = client.post(
        "/api/v1/work-item-batches",
        json={"name": "9 月专家评审", "work_item_name": "专家评审", "operator": "PMO", "targets": [{"project_id": project["id"], "work_item_id": item["id"]}]},
    ).json()

    completed = client.post(
        f"/api/v1/work-item-batches/{batch['id']}/complete",
        json={"operator": "PMO", "member_ids": [batch["members"][0]["id"]], "completed_on": "2026-09-25", "result": "通过", "note": "评审通过"},
    )

    assert completed.status_code == 200
    assert completed.json()["status"] == "closed"
    assert client.get(f"/api/v1/projects/{project['id']}/work-items").json()[0]["status"] == "completed"

    reopened = client.post(
        f"/api/v1/work-item-batches/{batch['id']}/follow-up",
        json={"operator": "PMO", "action": "rehandle", "member_ids": [batch["members"][0]["id"]]},
    )

    assert reopened.status_code == 200
    restored = client.get(f"/api/v1/projects/{project['id']}/work-items").json()[0]
    assert restored["id"] == item["id"]
    assert restored["status"] == "not_started"
    assert restored["completion_record_json"]["result"] == "通过"


def test_project_projection_exposes_a_single_category_summary_display(client, create_project_payload):
    software = client.post(
        "/api/v1/projects",
        json=create_project_payload(project_type="software", procurement_nature="service"),
    ).json()
    laboratory = client.post(
        "/api/v1/projects",
        json=create_project_payload(project_type="laboratory", location="下沙实验室"),
    ).json()

    listed = {item["id"]: item for item in client.get("/api/v1/projects").json()["items"]}
    assert listed[software["id"]]["project_summary_display"] == "专业教学软件项目 · 服务"
    assert listed[laboratory["id"]]["project_summary_display"] == "实践教学场所项目 · 下沙实验室"


def test_category_and_department_dictionary_order_project_lists(client, create_project_payload):
    client.post("/api/v1/meta/project-categories", json={"name": "教学软件项目", "sort_order": 20, "operator": "PMO"})
    client.post("/api/v1/meta/project-categories", json={"name": "实验室建设项目", "sort_order": 10, "operator": "PMO"})
    client.patch("/api/v1/meta/departments/信息中心/order", json={"sort_order": 30, "operator": "PMO"})
    client.patch("/api/v1/meta/departments/教务处/order", json={"sort_order": 10, "operator": "PMO"})
    first = client.post("/api/v1/projects", json=create_project_payload(name="软件项目", category="教学软件项目", department="信息中心")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="实验室项目", category="实验室建设项目", department="教务处")).json()
    rows = client.get("/api/v1/projects", params={"sort_by": "category", "sort_dir": "asc"}).json()["items"]
    assert [row["id"] for row in rows] == [second["id"], first["id"]]
