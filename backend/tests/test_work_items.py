from __future__ import annotations


def test_work_item_completion_and_reopen_keep_audit_history(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    item = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": "采购需求书", "operator": "PMO", "track_as_key_node": True},
    )
    assert item.status_code == 200
    completed = client.post(f"/api/v1/projects/{project['id']}/work-items/{item.json()['id']}/complete", json={"operator": "PMO", "result": "已提交"})
    assert completed.status_code == 200
    reopened = client.post(f"/api/v1/projects/{project['id']}/work-items/{item.json()['id']}/reopen", json={"operator": "PMO", "reason": "补充材料"})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "in_progress"
    audit = client.get(f"/api/v1/projects/{project['id']}/audit-events")
    assert [event["event_type"] for event in audit.json()] == ["WORK_ITEM_CREATED", "WORK_ITEM_COMPLETED", "WORK_ITEM_REOPENED"]


def test_include_in_advancement_is_explicit_pmo_action(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={"operator": "PMO", "comment": "测试立项", "to_status": "established"})
    response = client.post(f"/api/v1/projects/{project['id']}/include-in-advancement", json={"operator": "PMO", "reason": "纳入年度推进", "advancement_year": 2026})
    assert response.status_code == 200
    assert response.json()["library_implementation_view"] == "advancing"


def test_batch_advancement_preflight_rejects_mixed_projects_without_partial_writes(client, create_project_payload):
    eligible = client.post("/api/v1/projects", json=create_project_payload(name="已立项项目")).json()
    ineligible = client.post("/api/v1/projects", json=create_project_payload(name="未立项项目")).json()
    client.post(f"/api/v1/projects/{eligible['id']}/pmo-override", json={"operator": "PMO", "comment": "测试立项", "to_status": "established"})
    result = client.post(
        "/api/v1/projects/batch-include-in-advancement",
        json={"project_ids": [eligible["id"], ineligible["id"]], "operator": "PMO", "reason": "年度安排", "advancement_year": 2026},
    )
    assert result.status_code == 422
    assert client.get(f"/api/v1/projects/{eligible['id']}").json()["stage"] == "项目库—未实施"


def test_batch_work_items_are_projected_into_list_and_can_be_saved_as_a_package(client, create_project_payload):
    first = client.post("/api/v1/projects", json=create_project_payload(name="项目 A")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="项目 B")).json()

    response = client.post(
        "/api/v1/projects/batch-work-items",
        json={
            "project_ids": [first["id"], second["id"]],
            "operator": "PMO",
            "items": [
                {
                    "name": "预算审核",
                    "execution_mode": "external",
                    "assignee": "财务老师",
                    "planned_date": "2026-08-30",
                    "priority": "high",
                    "track_as_key_node": True,
                    "completion_mode": "record_only",
                },
                {"name": "采购需求书", "track_as_key_node": False, "completion_mode": "milestone"},
            ],
            "save_as_common": True,
            "save_as_package_name": "采购前期准备",
        },
    )
    assert response.status_code == 200
    assert response.json()["created_count"] == 4

    projects = client.get("/api/v1/projects", params={"page_size": 10}).json()["items"]
    first_projection = next(item for item in projects if item["id"] == first["id"])
    assert first_projection["stage"] == "未立项"
    assert first_projection["work_item_summary"][0]["name"] == "预算审核"
    assert first_projection["work_item_count"] == 2
    assert first_projection["work_item_states"]["采购需求书"] == "not_started"
    assert first_projection["next_key_node"]["name"] == "预算审核"

    templates = client.get("/api/v1/work-item-templates").json()
    packages = client.get("/api/v1/work-packages").json()
    assert any(item["name"] == "预算审核" for item in templates)
    assert any(package["name"] == "采购前期准备" for package in packages)


def test_apply_work_package_and_batch_include_advancement(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={"operator": "PMO", "comment": "测试立项", "to_status": "established"})
    package = client.post(
        "/api/v1/work-packages",
        json={"name": "临时包", "operator": "PMO", "items": [{"name": "采购申请", "track_as_key_node": True}]},
    ).json()
    apply_result = client.post(
        "/api/v1/projects/apply-work-package",
        json={"project_ids": [project["id"]], "package_id": package["id"], "operator": "PMO"},
    )
    assert apply_result.status_code == 200
    assert apply_result.json()["created_count"] == 1

    advancement = client.post(
        "/api/v1/projects/batch-include-in-advancement",
        json={"project_ids": [project["id"]], "operator": "PMO", "reason": "年度采购安排", "advancement_year": 2026},
    )
    assert advancement.status_code == 200
    assert advancement.json()["success"] == 1


def test_default_pmo_package_starts_at_pmo_review_and_is_snapshotted(client, create_project_payload):
    package = next(item for item in client.get("/api/v1/work-packages").json() if item["name"] == "未立项 PMO 工作包")
    assert [item["name"] for item in package["items"]] == [
        "PMO 审核", "校外专家/小组评审", "实验室建设与管理委员会", "校长办公会", "党委会", "立项发文",
    ]

    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    assert client.get(f"/api/v1/projects/{project['id']}/work-items").json() == []
    assert client.post("/api/v1/projects/apply-work-package", json={"project_ids": [project["id"]], "package_id": package["id"], "operator": "PMO"}).status_code == 200
    items = client.get(f"/api/v1/projects/{project['id']}/work-items").json()
    assert [item["name"] for item in items] == [entry["name"] for entry in package["items"]]
    listed = next(item for item in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"] if item["id"] == project["id"])
    assert listed["next_key_node"]["name"] == "PMO 审核"


def test_updating_a_package_changes_future_applications_not_existing_items(client, create_project_payload):
    package = client.post("/api/v1/work-packages", json={"name": "评审包", "operator": "PMO", "items": [{"name": "PMO 审核", "flow_group": "main", "sequence_rank": 100}]}).json()
    first = client.post("/api/v1/projects", json=create_project_payload(name="项目 A")).json()
    assert client.post("/api/v1/projects/apply-work-package", json={"project_ids": [first["id"]], "package_id": package["id"], "operator": "PMO"}).status_code == 200

    updated = client.patch("/api/v1/work-packages/" + str(package["id"]), json={"operator": "PMO", "name": "更新后的评审包", "items": [{"name": "党委会", "flow_group": "main", "sequence_rank": 600}]})
    assert updated.status_code == 200
    assert updated.json()["id"] == package["id"]
    assert updated.json()["name"] == "更新后的评审包"
    second = client.post("/api/v1/projects", json=create_project_payload(name="项目 B")).json()
    assert client.post("/api/v1/projects/apply-work-package", json={"project_ids": [second["id"]], "package_id": package["id"], "operator": "PMO"}).status_code == 200
    assert [item["name"] for item in client.get(f"/api/v1/projects/{first['id']}/work-items").json()] == ["PMO 审核"]
    assert [item["name"] for item in client.get(f"/api/v1/projects/{second['id']}/work-items").json()] == ["党委会"]


def test_package_order_is_normalized_and_applied_to_future_projects(client, create_project_payload):
    package = client.post(
        "/api/v1/work-packages",
        json={"name": "排序包", "operator": "PMO", "items": [
            {"name": "党委会", "flow_group": "main", "sequence_rank": 600},
            {"name": "PMO 审核", "flow_group": "main", "sequence_rank": 100},
        ]},
    ).json()
    updated = client.patch(
        f"/api/v1/work-packages/{package['id']}",
        json={"operator": "PMO", "items": [
            {"name": "党委会", "flow_group": "main", "sequence_rank": 600},
            {"name": "PMO 审核", "flow_group": "main", "sequence_rank": 100},
        ]},
    )
    assert updated.status_code == 200
    assert [item["sequence_rank"] for item in updated.json()["items"]] == [100, 200]

    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    assert client.post("/api/v1/projects/apply-work-package", json={"project_ids": [project["id"]], "package_id": package["id"], "operator": "PMO"}).status_code == 200
    assert [item["name"] for item in client.get(f"/api/v1/projects/{project['id']}/work-items").json()] == ["党委会", "PMO 审核"]


def test_quick_update_saves_work_item_and_progress_log_together(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    item = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "PMO 审核", "operator": "PMO"}).json()
    updated = client.post(
        f"/api/v1/projects/{project['id']}/work-items/{item['id']}/quick-update",
        json={"operator": "PMO", "status": "in_progress", "progress_content": "已通知学院补齐材料"},
    )
    assert updated.status_code == 200
    assert updated.json()["work_item"]["status"] == "in_progress"
    logs = client.get(f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs").json()
    assert [log["content"] for log in logs] == ["已通知学院补齐材料"]


def test_batch_work_item_action_preflight_and_execution_write_total_and_project_audits(client, create_project_payload):
    first = client.post("/api/v1/projects", json=create_project_payload(name="批量事项甲")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="批量事项乙")).json()
    first_item = client.post(f"/api/v1/projects/{first['id']}/work-items", json={"name": "统一材料准备", "operator": "PMO"}).json()
    second_item = client.post(f"/api/v1/projects/{second['id']}/work-items", json={"name": "统一材料准备", "operator": "PMO"}).json()
    targets = [{"project_id": first["id"], "work_item_id": first_item["id"]}, {"project_id": second["id"], "work_item_id": second_item["id"]}]

    preview = client.post("/api/v1/projects/batch-work-item-actions/preflight", json={"targets": targets, "action": "progress", "operator": "PMO"})
    assert preview.status_code == 200
    assert len(preview.json()["eligible"]) == 2

    executed = client.post("/api/v1/projects/batch-work-item-actions", json={"targets": targets, "action": "progress", "operator": "PMO", "defaults": {"progress_content": "已统一发送材料清单"}})
    assert executed.status_code == 200
    assert executed.json()["processed_count"] == 2
    assert [log["content"] for log in client.get(f"/api/v1/projects/{first['id']}/work-items/{first_item['id']}/progress-logs").json()] == ["已统一发送材料清单"]
    assert any(event["event_type"] == "WORK_ITEM_PROGRESS_RECORDED" for event in client.get(f"/api/v1/projects/{second['id']}/audit-events").json())


def test_batch_work_item_status_update_returns_and_projects_every_target(client, create_project_payload):
    first = client.post("/api/v1/projects", json=create_project_payload(name="批量状态甲")).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="批量状态乙")).json()
    first_item = client.post(f"/api/v1/projects/{first['id']}/work-items", json={"name": "同列事项", "operator": "PMO"}).json()
    second_item = client.post(f"/api/v1/projects/{second['id']}/work-items", json={"name": "同列事项", "operator": "PMO"}).json()
    targets = [{"project_id": first["id"], "work_item_id": first_item["id"]}, {"project_id": second["id"], "work_item_id": second_item["id"]}]

    preview = client.post("/api/v1/projects/batch-work-item-actions/preflight", json={"targets": targets, "action": "update", "operator": "PMO", "defaults": {"status": "in_progress"}})
    assert [item["work_item_id"] for item in preview.json()["eligible"]] == [first_item["id"], second_item["id"]]

    result = client.post("/api/v1/projects/batch-work-item-actions", json={"targets": targets, "action": "update", "operator": "PMO", "defaults": {"status": "in_progress"}})
    assert result.status_code == 200
    assert result.json()["processed_targets"] == targets

    projections = {item["id"]: item for item in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"]}
    assert projections[first["id"]]["work_item_column_states"][0]["status"] == "in_progress"
    assert projections[second["id"]]["work_item_column_states"][0]["status"] == "in_progress"
    assert any(event["event_type"] == "WORK_ITEM_UPDATED" for event in client.get(f"/api/v1/projects/{first['id']}/audit-events").json())
    assert any(event["event_type"] == "WORK_ITEM_UPDATED" for event in client.get(f"/api/v1/projects/{second['id']}/audit-events").json())


def test_batch_work_item_action_rejects_invalid_target_without_partial_write(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    item = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "待处理事项", "operator": "PMO"}).json()
    bad = client.post("/api/v1/projects/batch-work-item-actions", json={"targets": [{"project_id": project["id"], "work_item_id": item["id"]}, {"project_id": project["id"] + 999, "work_item_id": item["id"]}], "action": "update", "operator": "PMO", "defaults": {"status": "in_progress"}})
    assert bad.status_code == 422
    assert client.get(f"/api/v1/projects/{project['id']}/work-items").json()[0]["status"] == "not_started"


def test_progress_summary_prioritizes_overdue_items_before_waiting_external(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    response = client.post(
        "/api/v1/projects/batch-work-items",
        json={"project_ids": [project["id"]], "operator": "PMO", "items": [
            {"name": "逾期事项", "planned_date": "2025-01-01", "status": "not_started"},
            {"name": "等待外部事项", "planned_date": "2027-01-01", "status": "waiting_external"},
        ]},
    )
    assert response.status_code == 200
    item = next(value for value in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"] if value["id"] == project["id"])
    assert item["work_item_summary"][0]["name"] == "逾期事项"


def test_work_item_content_effects_and_progress_logs_are_kept_separate_from_management_timeline(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    item = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={
            "name": "采购需求书修改",
            "content": "等待学院补充数据接口范围",
            "status": "waiting_external",
            "operator": "PMO",
            "completion_effects": {"create_milestone": True, "require_result": True, "result_type": "pass_fail", "milestone_name": "需求书确认", "require_business_record": True},
        },
    )
    assert item.status_code == 200
    assert item.json()["content"] == "等待学院补充数据接口范围"
    assert item.json()["completion_rule_snapshot"]["effects"]["create_milestone"] is True

    ordinary = client.post(
        f"/api/v1/projects/{project['id']}/work-items/{item.json()['id']}/progress-logs",
        json={"operator": "PMO", "content": "学院已返回修改稿，仍需补充接口范围"},
    )
    highlighted = client.post(
        f"/api/v1/projects/{project['id']}/work-items/{item.json()['id']}/progress-logs",
        json={"operator": "PMO", "content": "专家确认修改方向", "is_timeline_highlight": True},
    )
    assert ordinary.status_code == 200
    assert highlighted.status_code == 200
    logs = client.get(f"/api/v1/projects/{project['id']}/work-items/{item.json()['id']}/progress-logs")
    assert [log["content"] for log in logs.json()] == ["专家确认修改方向", "学院已返回修改稿，仍需补充接口范围"]

    timeline = client.get(f"/api/v1/projects/{project['id']}/management-timeline")
    assert timeline.status_code == 200
    assert [event["summary"] for event in timeline.json()] == ["专家确认修改方向", "新增跟踪事项"]


def test_project_detail_exposes_fixed_stage_projection(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    detail = client.get(f"/api/v1/projects/{project['id']}")
    assert detail.status_code == 200
    assert detail.json()["stage"] == "未立项"


def test_main_flow_order_skips_cancelled_and_paused_item_blocks_key_node(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    first = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "专家评审", "operator": "PMO", "flow_group": "main", "sequence_rank": 300, "status": "paused"}).json()
    client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "党委会", "operator": "PMO", "flow_group": "main", "sequence_rank": 600}).json()
    cancelled = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "校长办公会", "operator": "PMO", "flow_group": "main", "sequence_rank": 500}).json()
    assert client.post(f"/api/v1/projects/{project['id']}/work-items/{cancelled['id']}/cancel", json={"operator": "PMO", "reason": "本项目无需上会"}).status_code == 200
    listed = client.get(f"/api/v1/projects/{project['id']}/work-items").json()
    assert [item["name"] for item in listed] == ["专家评审", "校长办公会", "党委会"]
    projection = next(item for item in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"] if item["id"] == project["id"])
    assert projection["next_key_node"]["name"] == "专家评审"
    assert first["flow_group"] == "main"


def test_project_main_flow_can_be_reordered_without_exposing_ranks(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    first = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "PMO 审核", "operator": "PMO", "flow_group": "main"}).json()
    second = client.post(f"/api/v1/projects/{project['id']}/work-items", json={"name": "党委会", "operator": "PMO", "flow_group": "main"}).json()
    reordered = client.post(
        f"/api/v1/projects/{project['id']}/work-items/reorder",
        json={"operator": "PMO", "item_ids": [second["id"], first["id"]]},
    )
    assert reordered.status_code == 200
    assert [item["name"] for item in reordered.json()] == ["党委会", "PMO 审核"]
    assert [item["sequence_rank"] for item in reordered.json()] == [100, 200]


def test_advancement_cycle_can_be_deferred_and_restarted(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={"operator": "PMO", "comment": "测试立项", "to_status": "established"})
    assert client.post(f"/api/v1/projects/{project['id']}/include-in-advancement", json={"operator": "PMO", "reason": "年度安排", "advancement_year": 2026}).status_code == 200
    deferred = client.post(f"/api/v1/projects/{project['id']}/defer-advancement", json={"operator": "PMO", "reason": "年度预算不足"})
    assert deferred.status_code == 200
    assert deferred.json()["library_implementation_view"] == "unimplemented"
    assert client.post(f"/api/v1/projects/{project['id']}/include-in-advancement", json={"operator": "PMO", "reason": "次年恢复", "advancement_year": 2027}).status_code == 200
    cycles = client.get(f"/api/v1/projects/{project['id']}/advancement-cycles").json()
    assert [cycle["status"] for cycle in cycles] == ["deferred", "active"]


def test_active_advancement_cycle_can_be_completed_without_closing_project(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={"operator": "PMO", "comment": "测试立项", "to_status": "established"})
    client.post(f"/api/v1/projects/{project['id']}/include-in-advancement", json={"operator": "PMO", "reason": "年度安排", "advancement_year": 2026})
    result = client.post(f"/api/v1/projects/{project['id']}/complete-advancement-cycle", json={"operator": "PMO", "reason": "年度工作完成"})
    assert result.status_code == 200
    assert client.get(f"/api/v1/projects/{project['id']}/advancement-cycles").json()[0]["status"] == "completed"
