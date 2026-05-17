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
