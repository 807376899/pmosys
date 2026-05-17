from __future__ import annotations


def test_teaching_software_code_generation(client, create_project_payload):
    response = client.post("/api/v1/projects", json=create_project_payload())
    assert response.status_code == 200
    assert response.json()["project_code"].startswith("SW")


def test_practical_site_code_generation(client, create_project_payload):
    response = client.post(
        "/api/v1/projects",
        json=create_project_payload(name="实践场所项目", project_type="practical_teaching_site"),
    )
    assert response.status_code == 200
    assert response.json()["project_code"].startswith("SY")

