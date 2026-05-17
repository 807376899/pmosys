from __future__ import annotations


def test_dashboard_groups(client, create_project_payload):
    client.post("/api/v1/projects", json=create_project_payload())
    response = client.get("/api/v1/dashboard/groups")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 5
    assert [item["key"] for item in items] == [
        "pre_establish",
        "pool_pending",
        "pool_active",
        "completed",
        "abandoned",
    ]

