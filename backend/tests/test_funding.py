from __future__ import annotations

import io

import pandas as pd


def _advancing_project(client, create_project_payload, *, name: str, budget: float, year: int):
    project = client.post("/api/v1/projects", json=create_project_payload(name=name, budget=budget)).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/pmo-override",
        json={"to_status": "established", "operator": "PMO", "comment": "测试立项"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project['id']}/include-in-advancement",
        json={"advancement_year": year, "reason": "年度安排", "operator": "PMO"},
    ).status_code == 200
    return project


def test_annual_funding_overview_uses_current_advancing_effective_budget(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="年度推进项目", budget=120, year=2027)
    created = client.post("/api/v1/funding/arrangements", json={
        "planning_year": 2027, "name": "2027 年实践教学建设经费", "estimated_amount": 100,
        "fund_code": "", "note": "财务初步安排", "operator": "PMO",
    })
    assert created.status_code == 200

    overview = client.get("/api/v1/funding/overview", params={"year": 2027})
    assert overview.status_code == 200
    body = overview.json()
    assert body["estimated_total"] == 100
    assert body["advancing_effective_budget_total"] == 120
    assert body["difference"] == -20
    assert body["over_expected"] is True
    assert body["advancing_project_count"] == 1
    assert body["advancing_projects"][0]["id"] == project["id"]
    arrangement_id = created.json()["id"]
    updated = client.patch(f"/api/v1/funding/arrangements/{arrangement_id}", json={
        "name": "调整后的年度安排", "estimated_amount": 140, "fund_code": "", "note": "调整", "operator": "PMO",
    })
    assert updated.status_code == 200
    assert client.get("/api/v1/funding/overview", params={"year": 2027}).json()["estimated_total"] == 140
    assert client.request("DELETE", f"/api/v1/funding/arrangements/{arrangement_id}", json={"operator": "PMO", "reason": "测试清理"}).status_code == 200
    assert client.get("/api/v1/funding/overview", params={"year": 2027}).json()["estimated_total"] == 0


def test_project_funding_allocations_are_many_to_many_and_warn_without_blocking(client, create_project_payload):
    first = _advancing_project(client, create_project_payload, name="项目一", budget=100, year=2027)
    second = _advancing_project(client, create_project_payload, name="项目二", budget=80, year=2027)
    source = client.post("/api/v1/funding/sources", json={
        "fund_code": "A001", "reference_amount": 120, "valid_from_year": 2027,
        "valid_until_year": 2027, "scope_note": "实践教学", "note": "", "operator": "PMO",
    })
    assert source.status_code == 200
    source_id = source.json()["id"]
    assert client.patch(f"/api/v1/funding/sources/{source_id}", json={
        "fund_code": "A001", "reference_amount": 125, "valid_from_year": 2027, "valid_until_year": 2028,
        "scope_note": "实践教学", "note": "调整有效期", "operator": "PMO",
    }).status_code == 200

    allocated = client.post(f"/api/v1/funding/sources/{source_id}/allocations", json={
        "operator": "PMO", "allocations": [
            {"project_id": first["id"], "allocated_amount": 130},
            {"project_id": second["id"], "allocated_amount": 30},
        ],
    })
    assert allocated.status_code == 200
    assert allocated.json()["warnings"]

    detail = client.get(f"/api/v1/projects/{first['id']}").json()
    assert detail["formal_allocation_total"] == 130
    assert detail["funding_allocations"][0]["fund_code"] == "A001"
    listed = client.get("/api/v1/projects", params={"page_size": 20}).json()["items"]
    assert next(item for item in listed if item["id"] == second["id"])["formal_allocation_total"] == 30


def test_funding_import_creates_cross_year_source_and_updates_existing_pair(client, create_project_payload):
    first = _advancing_project(client, create_project_payload, name="2027 项目", budget=100, year=2027)
    second = _advancing_project(client, create_project_payload, name="2028 项目", budget=100, year=2028)
    frame = pd.DataFrame([
        {"项目编号": first["project_code"], "项目名称": first["name"], "资金号": "A001", "资金参考金额": 300, "分配金额": 60},
        {"项目编号": second["project_code"], "项目名称": second["name"], "资金号": "A001", "资金参考金额": 300, "分配金额": 40},
    ])
    content = io.BytesIO(); frame.to_excel(content, index=False, sheet_name="正式资金分配")
    preview = client.post("/api/v1/funding/allocations/import/preview", files={
        "file": ("allocations.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    })
    assert preview.status_code == 200
    assert preview.json()["invalid_rows"] == 0
    committed = client.post("/api/v1/funding/allocations/import/commit", json={
        "records": preview.json()["records"], "operator": "PMO", "confirm_source_amount_updates": True,
    })
    assert committed.status_code == 200

    source = next(item for item in client.get("/api/v1/funding/sources", params={"year": 2027}).json() if item["fund_code"] == "A001")
    assert (source["valid_from_year"], source["valid_until_year"]) == (2027, 2028)
    assert client.post(f"/api/v1/projects/{first['id']}/funding-allocations", json={
        "funding_source_id": source["id"], "allocated_amount": 75, "operator": "PMO",
    }).status_code == 200
    assert client.get(f"/api/v1/projects/{first['id']}/funding-allocations").json()[0]["allocated_amount"] == 75


def test_funding_import_keeps_project_source_link_when_allocation_amount_is_blank(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload(name="计划项目", budget=100)).json()
    assert client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={"to_status": "established", "operator": "PMO", "comment": "测试立项"}).status_code == 200
    assert client.put("/api/v1/projects/annual-budget-plans/2027", json={"operator": "PMO", "members": [{"project_id": project["id"], "planned_new_amount": 100}]}).status_code == 200
    template = client.get("/api/v1/funding/allocations/import/template?year=2027")
    assert template.status_code == 200
    assert list(pd.read_excel(io.BytesIO(template.content), sheet_name="正式资金分配").columns) == [
        "项目编号", "项目名称", "项目分类", "学院", "预算（本年资金安排）", "资金代码", "资金名称", "资金负责人", "资金金额", "分配金额"
    ]
    frame = pd.DataFrame([{
        "项目编号": project["project_code"], "项目名称": project["name"], "项目分类": "专业教学软件项目", "学院": "测试学院",
        "预算（本年资金安排）": 100, "资金代码": "A001", "资金名称": "2027 年建设经费", "资金负责人": "财务老师", "资金金额": 300,
        "分配金额": "",
    }])
    content = io.BytesIO(); frame.to_excel(content, index=False, sheet_name="正式资金分配")

    preview = client.post("/api/v1/funding/allocations/import/preview?planning_year=2027", files={
        "file": ("allocations.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    })
    assert preview.status_code == 200
    assert preview.json()["invalid_rows"] == 0
    assert preview.json()["records"][0]["allocated_amount"] is None

    committed = client.post("/api/v1/funding/allocations/import/commit", json={
        "records": preview.json()["records"], "operator": "PMO", "planning_year": 2027, "confirm_source_amount_updates": True,
    })
    assert committed.status_code == 200
    source = next(item for item in client.get("/api/v1/funding/sources", params={"year": 2027}).json() if item["fund_code"] == "A001")
    assert source["fund_name"] == "2027 年建设经费"
    assert source["fund_manager"] == "财务老师"
    allocation = client.get(f"/api/v1/projects/{project['id']}/funding-allocations").json()[0]
    assert allocation["allocated_amount"] is None
    assert allocation["allocation_amount_recorded"] is False
