from __future__ import annotations

import io

import pandas as pd


def test_export_projects(client, create_project_payload):
    client.post("/api/v1/projects", json=create_project_payload(contract_amount=88))
    response = client.get("/api/v1/exports/projects")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(response.content) > 0
    exported = pd.read_excel(io.BytesIO(response.content))
    assert exported.loc[0, "合同金额"] == 88


def test_export_uses_advancing_management_view_and_structured_attributes(client, create_project_payload):
    project = client.post(
        "/api/v1/projects",
        json=create_project_payload(name="特批软件项目", project_type="software", procurement_nature="mixed"),
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/special-include-in-advancement",
        json={"operator": "PMO", "reason": "窗口紧张", "approval_basis": "PMO 特批", "advancement_year": 2026},
    ).status_code == 200

    response = client.get("/api/v1/exports/projects", params={"group": "pool_active"})
    exported = pd.read_excel(io.BytesIO(response.content))

    assert exported["项目名称"].tolist() == ["特批软件项目"]
    assert exported.loc[0, "采购属性"] == "混合"
