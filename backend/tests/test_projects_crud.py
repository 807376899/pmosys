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

