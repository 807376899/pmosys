from __future__ import annotations


def _project_item(client, payload_factory, name: str, item_name: str = "专家评审"):
    project = client.post("/api/v1/projects", json=payload_factory(name=name)).json()
    item = client.post(
        f"/api/v1/projects/{project['id']}/work-items",
        json={"name": item_name, "operator": "PMO", "status": "not_started"},
    ).json()
    return project, item


def test_activity_records_member_outcomes_without_completing_work_items_and_ends_when_all_recorded(client, create_project_payload):
    first, first_item = _project_item(client, create_project_payload, "活动项目甲")
    second, second_item = _project_item(client, create_project_payload, "活动项目乙")

    created = client.post("/api/v1/work-item-activities", json={
        "name": "9 月专家评审活动",
        "work_item_name": "专家评审",
        "scheduled_on": "2026-09-25",
        "operator": "PMO",
        "targets": [
            {"project_id": first["id"], "work_item_id": first_item["id"]},
            {"project_id": second["id"], "work_item_id": second_item["id"]},
        ],
    })

    assert created.status_code == 200
    activity = created.json()
    assert activity["status"] == "not_started"
    assert [member["outcome_status"] for member in activity["members"]] == ["unrecorded", "unrecorded"]

    first_member = activity["members"][0]
    first_result = client.post(f"/api/v1/work-item-activities/{activity['id']}/results", json={
        "operator": "PMO", "member_ids": [first_member["id"]],
        "result_on": "2026-09-25", "result": "通过", "note": "材料齐全",
    })
    assert first_result.status_code == 200
    assert first_result.json()["status"] == "in_progress"
    assert first_result.json()["members"][0]["outcome_status"] == "recorded"
    assert client.get(f"/api/v1/projects/{first['id']}/work-items").json()[0]["status"] == "not_started"

    second_member = next(member for member in first_result.json()["members"] if member["project_id"] == second["id"])
    finished = client.post(f"/api/v1/work-item-activities/{activity['id']}/results", json={
        "operator": "PMO", "member_ids": [second_member["id"]],
        "result_on": "2026-09-25", "result": "待修改", "note": "补充预算说明",
    })
    assert finished.status_code == 200
    assert finished.json()["status"] == "ended"
    assert {member["outcome_status"] for member in finished.json()["members"]} == {"recorded"}
    assert client.get(f"/api/v1/projects/{second['id']}/work-items").json()[0]["status"] == "not_started"


def test_activity_shared_progress_is_visible_without_creating_project_progress_logs(client, create_project_payload):
    project, item = _project_item(client, create_project_payload, "活动进展项目")
    activity = client.post("/api/v1/work-item-activities", json={
        "name": "集中审核活动", "work_item_name": item["name"], "operator": "PMO",
        "targets": [{"project_id": project["id"], "work_item_id": item["id"]}],
    }).json()

    progress = client.post(f"/api/v1/work-item-activities/{activity['id']}/progress-logs", json={
        "operator": "PMO", "content": "已完成集中材料核验",
    })

    assert progress.status_code == 200
    details = client.get(f"/api/v1/work-item-activities/{activity['id']}").json()
    assert details["status"] == "in_progress"
    assert [entry["content"] for entry in details["progress_logs"]] == ["已完成集中材料核验"]
    assert client.get(f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs").json() == []


def test_activity_progress_can_be_corrected_or_soft_deleted_without_touching_work_item_logs(client, create_project_payload):
    project, item = _project_item(client, create_project_payload, "活动进展维护项目")
    activity = client.post("/api/v1/work-item-activities", json={
        "name": "活动进展维护", "work_item_name": item["name"], "operator": "PMO",
        "targets": [{"project_id": project["id"], "work_item_id": item["id"]}],
    }).json()
    created = client.post(f"/api/v1/work-item-activities/{activity['id']}/progress-logs", json={
        "operator": "PMO", "content": "材料初核完成",
    }).json()
    log_id = created["progress_logs"][0]["id"]

    changed = client.patch(f"/api/v1/work-item-activities/{activity['id']}/progress-logs/{log_id}", json={
        "operator": "PMO", "content": "材料复核完成",
    })
    assert changed.status_code == 200
    assert changed.json()["progress_logs"][0]["content"] == "材料复核完成"

    removed = client.request("DELETE", f"/api/v1/work-item-activities/{activity['id']}/progress-logs/{log_id}", json={
        "operator": "PMO", "reason": "误录",
    })
    assert removed.status_code == 200
    assert removed.json()["progress_logs"] == []
    assert client.get(f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs").json() == []


def test_activity_can_add_and_remove_members_without_creating_or_changing_work_items(client, create_project_payload):
    first, first_item = _project_item(client, create_project_payload, "活动成员甲")
    second, second_item = _project_item(client, create_project_payload, "活动成员乙")
    activity = client.post("/api/v1/work-item-activities", json={
        "name": "成员管理活动", "work_item_name": "专家评审", "operator": "PMO",
        "targets": [{"project_id": first["id"], "work_item_id": first_item["id"]}],
    }).json()

    joined = client.post(f"/api/v1/work-item-activities/{activity['id']}/members", json={
        "operator": "PMO", "targets": [{"project_id": second["id"], "work_item_id": second_item["id"]}],
    })
    assert joined.status_code == 200
    second_member = next(member for member in joined.json()["members"] if member["project_id"] == second["id"])
    assert client.get(f"/api/v1/projects/{second['id']}/work-items").json()[0]["status"] == "not_started"
    removed = client.post(f"/api/v1/work-item-activities/{activity['id']}/members/remove", json={
        "operator": "PMO", "member_ids": [second_member["id"]], "reason": "本次不参加",
    })
    assert removed.status_code == 200
    assert next(member for member in removed.json()["members"] if member["id"] == second_member["id"])["member_status"] == "removed"
    assert client.get(f"/api/v1/projects/{second['id']}/work-items").json()[0]["status"] == "not_started"


def test_activity_follow_up_groups_next_items_without_auto_advancing(client, create_project_payload):
    project, review = _project_item(client, create_project_payload, "活动后续项目")
    next_item = client.post(f"/api/v1/projects/{project['id']}/work-items", json={
        "name": "委员会会议", "operator": "PMO", "status": "not_started", "insert_mode": "append",
    }).json()
    activity = client.post("/api/v1/work-item-activities", json={
        "name": "评审活动", "work_item_name": review["name"], "operator": "PMO",
        "targets": [{"project_id": project["id"], "work_item_id": review["id"]}],
    }).json()
    client.post(f"/api/v1/projects/{project['id']}/work-items/{review['id']}/complete", json={"operator": "PMO", "completed_on": "2026-09-24"})

    groups = client.post(f"/api/v1/work-item-activities/{activity['id']}/next-groups", json={
        "operator": "PMO", "member_ids": [activity["members"][0]["id"]],
    })
    assert groups.status_code == 200
    assert groups.json()["groups"] == [{"name": next_item["name"], "count": 1, "project_ids": [project["id"]]}]
    hold = client.post(f"/api/v1/work-item-activities/{activity['id']}/follow-up", json={
        "operator": "PMO", "member_ids": [activity["members"][0]["id"]], "action": "hold",
    })
    assert hold.status_code == 200
    assert hold.json()["members"][0]["follow_up_action"] == "hold"
    assert next(item for item in client.get(f"/api/v1/projects/{project['id']}/work-items").json() if item["id"] == next_item["id"])["status"] == "not_started"

def test_legacy_batch_route_is_not_exposed(client):
    assert client.get("/api/v1/work-item-batches").status_code == 404
