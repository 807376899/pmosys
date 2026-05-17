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

