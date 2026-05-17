from __future__ import annotations


def _create_project(client, payload):
    return client.post("/api/v1/projects", json=payload).json()


def test_single_transition_and_budget_rules(client, create_project_payload):
    project = _create_project(client, create_project_payload())
    invalid = client.post(
        f"/api/v1/projects/{project['id']}/transitions",
        json={
            "to_status": "closed",
            "operator": "王敏",
            "operator_role": "PMO",
            "comment": "直接关闭",
            "deliverable": "",
            "force": False,
            "approved_budget": None,
        },
    )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "INVALID_TRANSITION"

    review = client.post(
        f"/api/v1/projects/{project['id']}/transitions",
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
    assert review.status_code == 200

    forbidden_budget = client.post(
        f"/api/v1/projects/{project['id']}/transitions",
        json={
            "to_status": "established",
            "operator": "王敏",
            "operator_role": "PMO",
            "approver": "评审委员会",
            "comment": "评审通过",
            "deliverable": "评审通过决议",
            "force": False,
            "approved_budget": 88.0,
        },
    )
    assert forbidden_budget.status_code == 422
    assert forbidden_budget.json()["code"] == "APPROVED_BUDGET_NOT_ALLOWED"


def test_force_transition_requires_pmo_role(client, create_project_payload):
    project = _create_project(client, create_project_payload())
    response = client.post(
        f"/api/v1/projects/{project['id']}/transitions",
        json={
            "to_status": "terminated",
            "operator": "普通用户",
            "operator_role": "USER",
            "approver": "普通用户",
            "comment": "强制终止",
            "deliverable": "",
            "force": True,
            "approved_budget": None,
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "PMO_ROLE_REQUIRED"

