from __future__ import annotations


def test_project_crud_and_patch_whitelist(client, create_project_payload):
    created = client.post("/api/v1/projects", json=create_project_payload()).json()
    detail = client.get(f"/api/v1/projects/{created['id']}")
    assert detail.status_code == 200
    patch = client.patch(
        f"/api/v1/projects/{created['id']}",
        json={"name": "更新后的项目", "budget": 123.5},
    )
    assert patch.status_code == 200
    assert patch.json()["name"] == "更新后的项目"
    invalid_patch = client.patch(
        f"/api/v1/projects/{created['id']}",
        json={"current_status": "closed"},
    )
    assert invalid_patch.status_code == 422
    assert invalid_patch.json()["code"] == "VALIDATION_ERROR"
    delete = client.delete(f"/api/v1/projects/{created['id']}")
    assert delete.status_code == 200


def test_project_list_supports_project_type_filter(client, create_project_payload):
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="软件项目", project_type="teaching_software"),
    )
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="场所项目", project_type="practical_teaching_site"),
    )
    response = client.get("/api/v1/projects", params={"project_type": "teaching_software"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["project_type"] == "teaching_software"


def test_project_list_sorting_and_department_order(client, create_project_payload, monkeypatch):
    monkeypatch.setenv("PMO_DEPARTMENT_ORDER", "财务部,信息中心,教务处")
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="信息项目", department="信息中心", actual_start_date="2025-01-01"),
    )
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="财务项目", department="财务部", actual_start_date="2024-01-01"),
    )
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="其他项目", department="后勤处", actual_start_date="2026-01-01"),
    )

    response = client.get("/api/v1/projects", params={"sort_by": "department", "sort_dir": "asc"})
    assert response.status_code == 200
    assert [item["department"] for item in response.json()["items"]] == ["财务部", "信息中心", "后勤处"]

    response = client.get("/api/v1/projects", params={"sort_by": "implementation_year", "sort_dir": "desc"})
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["其他项目", "信息项目", "财务项目"]

    response = client.get("/api/v1/meta/departments")
    assert response.status_code == 200
    assert response.json() == ["财务部", "信息中心", "后勤处"]
