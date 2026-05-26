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
