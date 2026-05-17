from __future__ import annotations


def test_export_projects(client, create_project_payload):
    client.post("/api/v1/projects", json=create_project_payload())
    response = client.get("/api/v1/exports/projects")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(response.content) > 0
