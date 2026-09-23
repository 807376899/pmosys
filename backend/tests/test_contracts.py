from __future__ import annotations


def _advancing_project(client, create_project_payload, *, name: str):
    project = client.post("/api/v1/projects", json=create_project_payload(name=name, budget=100)).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/pmo-override",
        json={"to_status": "established", "operator": "PMO", "comment": "测试立项"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project['id']}/include-in-advancement",
        json={"advancement_year": 2027, "reason": "年度安排", "operator": "PMO"},
    ).status_code == 200
    return project


def test_shared_contract_requires_facts_before_fulfillment_and_updates_project_summaries(client, create_project_payload):
    first = _advancing_project(client, create_project_payload, name="合同项目一")
    second = _advancing_project(client, create_project_payload, name="合同项目二")

    created = client.post("/api/v1/contracts", json={
        "name": "设备采购合同", "contract_no": "HT-2027-000", "project_ids": [first["id"], second["id"]], "operator": "PMO",
    })
    assert created.status_code == 200
    contract = created.json()
    assert contract["status"] == "not_started"
    assert {project["id"] for project in contract["projects"]} == {first["id"], second["id"]}

    blocked = client.patch(f"/api/v1/contracts/{contract['id']}", json={"status": "performing", "operator": "PMO"})
    assert blocked.status_code == 422

    updated = client.patch(f"/api/v1/contracts/{contract['id']}", json={
        "contract_no": "HT-2027-001", "supplier": "示例公司", "total_amount": 100,
        "signed_on": "2027-03-01", "status": "performing", "operator": "PMO",
    })
    assert updated.status_code == 200
    assert updated.json()["status"] == "performing"

    duplicate = client.post("/api/v1/contracts", json={
        "name": "重复编号合同", "contract_no": "HT-2027-001", "project_ids": [first["id"]], "operator": "PMO",
    })
    assert duplicate.status_code == 409

    listed = client.get("/api/v1/projects", params={"page_size": 20}).json()["items"]
    for project_id in (first["id"], second["id"]):
        summary = next(item for item in listed if item["id"] == project_id)["contract_summary"]
        assert summary["count"] == 1
        assert summary["label"] == "1份 · 1履约中"


def test_contract_number_is_required_even_before_performance(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="编号必填项目")

    response = client.post("/api/v1/contracts", json={
        "name": "缺少编号合同", "project_ids": [project["id"]], "operator": "PMO",
    })

    assert response.status_code == 422
    assert "合同编号" in response.json()["message"]


def test_contract_summary_exposes_compact_contract_entries(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="合同摘要项目")
    response = client.post("/api/v1/contracts", json={
        "name": "摘要合同", "contract_no": "HT-2027-004", "project_ids": [project["id"]], "operator": "PMO",
    })
    assert response.status_code == 200

    project_row = next(item for item in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"] if item["id"] == project["id"])
    assert project_row["contract_summary"]["contracts"] == [{"id": response.json()["id"], "contract_no": "HT-2027-004", "name": "摘要合同", "status": "not_started"}]


def test_contract_acceptance_history_and_project_link_correction(client, create_project_payload):
    active = _advancing_project(client, create_project_payload, name="履约项目")
    completed = client.post("/api/v1/projects", json=create_project_payload(name="完成项目", budget=100)).json()
    assert client.post(
        f"/api/v1/projects/{completed['id']}/pmo-override",
        json={"to_status": "closed", "operator": "PMO", "comment": "历史完成"},
    ).status_code == 200
    created = client.post("/api/v1/contracts", json={
        "name": "验收合同", "contract_no": "HT-2027-002", "supplier": "示例公司", "total_amount": 100,
        "signed_on": "2027-03-01", "status": "performing", "project_ids": [active["id"]], "operator": "PMO",
    })
    assert created.status_code == 200
    contract_id = created.json()["id"]

    blocked_link = client.put(f"/api/v1/contracts/{contract_id}/projects", json={
        "project_ids": [active["id"], completed["id"]], "operator": "PMO",
    })
    assert blocked_link.status_code == 422
    corrected_link = client.put(f"/api/v1/contracts/{contract_id}/projects", json={
        "project_ids": [active["id"], completed["id"]], "history_correction": True,
        "reason": "补录历史合同关联", "operator": "PMO",
    })
    assert corrected_link.status_code == 200

    first = client.post(f"/api/v1/contracts/{contract_id}/acceptance-records", json={
        "acceptance_status": "needs_rectification", "acceptance_date": "2027-06-01", "result": "需整改", "note": "补齐材料", "operator": "PMO",
    })
    assert first.status_code == 200
    progress = client.post(f"/api/v1/contracts/{contract_id}/progress-logs", json={"content": "已补齐材料", "operator": "PMO"})
    assert progress.status_code == 200
    second = client.post(f"/api/v1/contracts/{contract_id}/acceptance-records", json={
        "acceptance_status": "accepted", "acceptance_date": "2027-06-10", "result": "验收通过", "note": "", "operator": "PMO",
    })
    assert second.status_code == 200

    assert client.patch(f"/api/v1/contracts/{contract_id}", json={"status": "completed", "operator": "PMO"}).status_code == 200

    detail = client.get(f"/api/v1/contracts/{contract_id}").json()
    assert detail["acceptance_status"] == "accepted"
    assert [row["acceptance_status"] for row in detail["acceptance_records"]] == ["accepted", "needs_rectification"]
    assert detail["latest_progress"]["content"] == "已补齐材料"

    last_link = client.put(f"/api/v1/contracts/{contract_id}/projects", json={
        "project_ids": [], "reason": "错误", "operator": "PMO",
    })
    assert last_link.status_code == 422


def test_contract_allocations_acceptance_and_completion_gate(client, create_project_payload):
    first = _advancing_project(client, create_project_payload, name="分摊项目一")
    second = _advancing_project(client, create_project_payload, name="分摊项目二")
    created = client.post("/api/v1/contracts", json={
        "name": "分摊合同", "contract_no": "HT-2027-003", "supplier": "示例公司", "total_amount": 100,
        "signed_on": "2027-03-01", "status": "performing",
        "project_links": [{"project_id": first["id"], "allocated_amount": 60}, {"project_id": second["id"], "allocated_amount": 30}],
        "operator": "PMO",
    })
    assert created.status_code == 200
    contract = created.json()
    assert {item["allocated_amount"] for item in contract["projects"]} == {"60", "30"}
    assert contract["allocation_complete"] is True
    assert contract["allocation_difference"] == "10"

    blocked = client.patch(f"/api/v1/contracts/{contract['id']}", json={"status": "completed", "operator": "PMO"})
    assert blocked.status_code == 422
    accepted = client.post(f"/api/v1/contracts/{contract['id']}/acceptance-records", json={
        "acceptance_status": "accepted", "acceptance_date": "2027-06-10", "result": "验收通过", "operator": "PMO",
    })
    assert accepted.status_code == 200
    completed = client.patch(f"/api/v1/contracts/{contract['id']}", json={"status": "completed", "operator": "PMO"})
    assert completed.status_code == 200
    assert completed.json()["acceptance_status"] == "accepted"


def test_completed_project_can_create_explicit_historical_contract(client, create_project_payload):
    completed = client.post("/api/v1/projects", json=create_project_payload(name="历史合同项目", budget=100)).json()
    assert client.post(f"/api/v1/projects/{completed['id']}/pmo-override", json={"to_status": "closed", "operator": "PMO", "comment": "历史完成"}).status_code == 200

    rejected = client.post("/api/v1/contracts", json={"name": "历史合同", "project_ids": [completed["id"]], "operator": "PMO"})
    assert rejected.status_code == 422
    created = client.post("/api/v1/contracts", json={
        "name": "历史合同", "contract_no": "HT-2027-005", "project_links": [{"project_id": completed["id"], "allocated_amount": None}],
        "history_correction": True, "reason": "补录历史合同", "operator": "PMO",
    })
    assert created.status_code == 200
    assert created.json()["projects"][0]["id"] == completed["id"]


def test_historical_contract_can_link_multiple_completed_projects(client, create_project_payload):
    first = client.post("/api/v1/projects", json=create_project_payload(name="历史合同项目一", budget=100)).json()
    second = client.post("/api/v1/projects", json=create_project_payload(name="历史合同项目二", budget=100)).json()
    for project in (first, second):
        assert client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={"to_status": "closed", "operator": "PMO", "comment": "历史完成"}).status_code == 200

    response = client.post("/api/v1/contracts", json={
        "name": "多项目历史合同", "contract_no": "HT-2027-006",
        "project_ids": [first["id"], second["id"]], "history_correction": True,
        "reason": "集中补录历史合同", "operator": "PMO",
    })

    assert response.status_code == 200
    assert {project["id"] for project in response.json()["projects"]} == {first["id"], second["id"]}
