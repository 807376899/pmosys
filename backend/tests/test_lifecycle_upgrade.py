from __future__ import annotations


def test_type_catalog_and_database_generated_code(client, create_project_payload):
    types = client.get("/api/v1/project-types")
    assert types.status_code == 200
    assert {item["code"] for item in types.json()} == {"software", "laboratory"}

    project = client.post(
        "/api/v1/projects",
        json=create_project_payload(project_type="software", major="人工智能", location="主校区"),
    )
    assert project.status_code == 200
    body = project.json()
    assert body["project_code"].startswith("SW")
    assert body["major"] == "人工智能"
    assert body["location"] == "主校区"


def test_pmo_override_and_submission_budget_return_to_library(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    override = client.post(
        f"/api/v1/projects/{project['id']}/pmo-override",
        json={"to_status": "submission_review", "operator": "PMO", "comment": "补录送审状态"},
    )
    assert override.status_code == 200
    assert override.json()["library_implementation_view"] == "unimplemented"

    returned = client.post(
        f"/api/v1/projects/{project['id']}/submission-review-complete",
        json={"operator": "PMO", "approved_budget": 88.0},
    )
    assert returned.status_code == 200
    assert returned.json()["current_status"] == "established"
    assert returned.json()["approved_budget"] == 88.0


def test_dashboard_has_five_pmo_views(client):
    response = client.get("/api/v1/dashboard/groups")
    assert response.status_code == 200
    assert [item["key"] for item in response.json()] == [
        "pre_establish",
        "pool_pending",
        "pool_active",
        "completed",
        "abandoned",
    ]
    assert response.json()[2]["label"] == "推进中"
