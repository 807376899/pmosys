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
    assert items[0]["label"] == "未立项"
    assert items[0]["count"] == 1
    assert items[0]["total_budget"] == 100.0
    assert items[0]["total_approved_budget"] == 0.0


def test_not_found_error_uses_uniform_shape(client):
    response = client.get("/api/v1/unknown-path")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert "message" in body
