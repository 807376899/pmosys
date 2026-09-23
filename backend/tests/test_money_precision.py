from __future__ import annotations


def test_project_budget_uses_decimal_text_without_rounding(client, create_project_payload):
    created = client.post("/api/v1/projects", json=create_project_payload(budget="12.5896")).json()
    assert created["budget"] == "12.5896"
    assert created["effective_budget"] == "12.5896"

    refreshed = client.get(f"/api/v1/projects/{created['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["budget"] == "12.5896"


def test_decimal_amounts_normalize_without_losing_precision(client):
    created = client.post("/api/v1/funding/arrangements", json={
        "planning_year": 2027,
        "name": "精度测试资金安排",
        "estimated_amount": "12.5000",
        "operator": "PMO",
    })
    assert created.status_code == 200
    assert created.json()["estimated_amount"] == "12.5"
    assert client.get("/api/v1/funding/overview", params={"year": 2027}).json()["estimated_total"] == "12.5"


def test_money_rejects_scientific_notation_and_negative_values(client, create_project_payload):
    scientific = client.post("/api/v1/projects", json=create_project_payload(budget="1e2"))
    assert scientific.status_code == 422
    negative = client.post("/api/v1/projects", json=create_project_payload(budget="-0.01"))
    assert negative.status_code == 422
