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


def test_shared_contract_uses_facts_not_a_manual_fulfillment_status(client, create_project_payload):
    first = _advancing_project(client, create_project_payload, name="合同项目一")
    second = _advancing_project(client, create_project_payload, name="合同项目二")

    created = client.post("/api/v1/contracts", json={
        "name": "设备采购合同", "contract_no": "HT-2027-000", "project_ids": [first["id"], second["id"]], "operator": "PMO",
    })
    assert created.status_code == 200
    contract = created.json()
    assert contract["status"] == "active"
    assert {project["id"] for project in contract["projects"]} == {first["id"], second["id"]}

    blocked = client.patch(f"/api/v1/contracts/{contract['id']}", json={"status": "performing", "operator": "PMO"})
    assert blocked.status_code == 422

    updated = client.patch(f"/api/v1/contracts/{contract['id']}", json={
        "contract_no": "HT-2027-001", "supplier": "示例公司", "total_amount": 100,
        "signed_on": "2027-03-01", "operator": "PMO",
    })
    assert updated.status_code == 200
    assert updated.json()["status"] == "active"

    duplicate = client.post("/api/v1/contracts", json={
        "name": "重复编号合同", "contract_no": "HT-2027-001", "project_ids": [first["id"]], "operator": "PMO",
    })
    assert duplicate.status_code == 409

    listed = client.get("/api/v1/projects", params={"page_size": 20}).json()["items"]
    for project_id in (first["id"], second["id"]):
        summary = next(item for item in listed if item["id"] == project_id)["contract_summary"]
        assert summary["count"] == 1
        assert summary["label"] == "1份"


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
    summary_contract = project_row["contract_summary"]["contracts"][0]
    assert summary_contract["id"] == response.json()["id"]
    assert summary_contract["payment_status"] == "unpaid"
    assert summary_contract["project_count"] == 1


def test_contract_summary_lists_every_contract_in_contract_number_order(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="合同排序项目")
    for number in ("HT-2027-020", "HT-2027-002", "HT-2027-011"):
        response = client.post("/api/v1/contracts", json={
            "name": f"{number} 合同", "contract_no": number, "project_ids": [project["id"]], "operator": "PMO",
        })
        assert response.status_code == 200

    project_row = next(item for item in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"] if item["id"] == project["id"])
    assert [item["contract_no"] for item in project_row["contract_summary"]["contracts"]] == [
        "HT-2027-002", "HT-2027-011", "HT-2027-020",
    ]


def test_contract_acceptance_history_and_project_link_correction(client, create_project_payload):
    active = _advancing_project(client, create_project_payload, name="履约项目")
    completed = client.post("/api/v1/projects", json=create_project_payload(name="完成项目", budget=100)).json()
    assert client.post(
        f"/api/v1/projects/{completed['id']}/pmo-override",
        json={"to_status": "closed", "operator": "PMO", "comment": "历史完成"},
    ).status_code == 200
    created = client.post("/api/v1/contracts", json={
        "name": "验收合同", "contract_no": "HT-2027-002", "supplier": "示例公司", "total_amount": 100,
        "signed_on": "2027-03-01", "project_ids": [active["id"]], "operator": "PMO",
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

    paid = client.post(f"/api/v1/contracts/{contract_id}/payment-records", json={"amount": 100, "paid_on": "2027-06-20"})
    assert paid.status_code == 200
    assert paid.json()["status"] == "active"

    detail = client.get(f"/api/v1/contracts/{contract_id}").json()
    assert detail["acceptance_status"] == "accepted"
    assert [row["acceptance_status"] for row in detail["acceptance_records"]] == ["accepted", "needs_rectification"]
    assert detail["latest_progress"]["content"] == "已补齐材料"

    last_link = client.put(f"/api/v1/contracts/{contract_id}/projects", json={
        "project_ids": [], "reason": "错误", "operator": "PMO",
    })
    assert last_link.status_code == 422


def test_contract_allocations_and_acceptance_do_not_change_contract_state(client, create_project_payload):
    first = _advancing_project(client, create_project_payload, name="分摊项目一")
    second = _advancing_project(client, create_project_payload, name="分摊项目二")
    created = client.post("/api/v1/contracts", json={
        "name": "分摊合同", "contract_no": "HT-2027-003", "supplier": "示例公司", "total_amount": 100,
        "signed_on": "2027-03-01",
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
    paid = client.post(f"/api/v1/contracts/{contract['id']}/payment-records", json={"amount": 100, "paid_on": "2027-06-20"})
    assert paid.status_code == 200
    assert paid.json()["acceptance_status"] == "accepted"
    assert paid.json()["status"] == "active"


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


def test_contract_payments_drive_payment_projection_without_automatic_completion(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="付款合同项目")
    created = client.post("/api/v1/contracts", json={
        "name": "付款合同", "contract_no": "HT-2027-007", "supplier": "示例公司",
        "total_amount": "12.5896", "signed_on": "2027-03-01",
        "project_ids": [project["id"]], "operator": "PMO",
    })
    assert created.status_code == 200
    contract_id = created.json()["id"]
    assert created.json()["payment_status"] == "unpaid"

    partial = client.post(f"/api/v1/contracts/{contract_id}/payment-records", json={
        "amount": "2.5896", "paid_on": "2027-04-01", "note": "首付款",
    })
    assert partial.status_code == 200
    assert partial.json()["payment_status"] == "partial"
    assert partial.json()["paid_total"] == "2.5896"
    assert partial.json()["status"] == "active"

    accepted = client.post(f"/api/v1/contracts/{contract_id}/acceptance-records", json={
        "acceptance_status": "accepted", "acceptance_date": "2027-06-10", "result": "验收通过", "operator": "PMO",
    })
    assert accepted.status_code == 200
    assert client.get(f"/api/v1/contracts/{contract_id}").json()["status"] == "active"

    settled = client.post(f"/api/v1/contracts/{contract_id}/payment-records", json={
        "amount": "10", "paid_on": "2027-06-20",
    })
    assert settled.status_code == 200
    assert settled.json()["payment_status"] == "paid"
    assert settled.json()["paid_total"] == "12.5896"
    assert settled.json()["remaining_amount"] == "0"
    assert settled.json()["status"] == "active"

    blocked = client.post(f"/api/v1/contracts/{contract_id}/payment-records", json={
        "amount": "0.0001", "paid_on": "2027-06-21",
    })
    assert blocked.status_code == 422

    corrected = client.patch(f"/api/v1/contracts/{contract_id}/payment-records/{settled.json()['payment_records'][-1]['id']}", json={
        "amount": "9", "paid_on": "2027-06-20",
    })
    assert corrected.status_code == 200
    assert corrected.json()["payment_status"] == "partial"
    assert corrected.json()["status"] == "active"

    deleted = client.delete(f"/api/v1/contracts/{contract_id}/payment-records/{partial.json()['payment_records'][0]['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["payment_status"] == "partial"
    assert deleted.json()["paid_total"] == "9"


def test_contract_delivery_schedule_is_derived_from_signed_date_and_period(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="交付周期合同项目")

    response = client.post("/api/v1/contracts", json={
        "name": "交付周期合同", "contract_no": "HT-2027-008", "supplier": "示例公司",
        "total_amount": "10", "signed_on": "2027-01-31",
        "delivery_period_value": 1, "delivery_period_unit": "months",
        "project_ids": [project["id"]], "operator": "PMO",
    })

    assert response.status_code == 200
    contract = response.json()
    assert contract["calculated_delivery_on"] == "2027-02-28"
    assert contract["planned_delivery_on"] == "2027-02-28"
    assert contract["delivery_schedule"]["kind"] == "upcoming"
    assert contract["status"] == "active"


def test_manual_delivery_date_overrides_calculation_and_pause_blocks_new_facts(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="交付覆盖合同项目")
    created = client.post("/api/v1/contracts", json={
        "name": "覆盖合同", "contract_no": "HT-2027-009", "supplier": "示例公司",
        "total_amount": "10", "signed_on": "2027-01-31", "delivery_period_value": 1,
        "delivery_period_unit": "months", "planned_completion_on": "2027-03-05",
        "project_ids": [project["id"]], "operator": "PMO",
    })
    assert created.status_code == 200
    contract = created.json()
    assert contract["planned_delivery_on"] == "2027-03-05"
    assert contract["delivery_plan_conflict"] is True

    paused = client.post(f"/api/v1/contracts/{contract['id']}/pause", json={"reason": "等待变更", "operator": "PMO"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert client.post(f"/api/v1/contracts/{contract['id']}/payment-records", json={"amount": "1", "paid_on": "2027-02-01"}).status_code == 422
    assert client.post(f"/api/v1/contracts/{contract['id']}/acceptance-records", json={
        "acceptance_status": "accepting", "acceptance_date": "2027-02-01", "operator": "PMO",
    }).status_code == 422
    assert client.post(f"/api/v1/contracts/{contract['id']}/resume", json={"operator": "PMO"}).json()["status"] == "active"
    assert client.post(f"/api/v1/contracts/{contract['id']}/terminate", json={"reason": "合同解除", "operator": "PMO"}).json()["status"] == "terminated"
    assert client.post(f"/api/v1/contracts/{contract['id']}/progress-logs", json={"content": "不可登记", "operator": "PMO"}).status_code == 422
    summary = next(item for item in client.get("/api/v1/projects", params={"page_size": 20}).json()["items"] if item["id"] == project["id"])["contract_summary"]
    assert summary["contracts"][0]["status"] == "terminated"


def test_workday_delivery_uses_configured_holiday_calendar(client, create_project_payload, tmp_path, monkeypatch):
    calendar = tmp_path / "holidays.json"
    calendar.write_text('{"holidays":["2027-01-04"],"workdays":["2027-01-09"]}', encoding="utf-8")
    monkeypatch.setenv("PMO_HOLIDAY_CALENDAR_PATH", str(calendar))
    project = _advancing_project(client, create_project_payload, name="工作日合同项目")

    response = client.post("/api/v1/contracts", json={
        "name": "工作日合同", "contract_no": "HT-2027-010", "signed_on": "2027-01-01",
        "delivery_period_value": 2, "delivery_period_unit": "working_days",
        "project_ids": [project["id"]], "operator": "PMO",
    })

    assert response.status_code == 200
    contract = response.json()
    assert contract["calculated_delivery_on"] == "2027-01-06"
    assert contract["delivery_schedule"]["calendar_source"] == "holiday_calendar"


def test_delivery_period_uses_calendar_units_and_rejects_impossible_actual_date(client, create_project_payload):
    project = _advancing_project(client, create_project_payload, name="日历周期合同项目")
    cases = [
        ("HT-2028-001", "2028-02-28", 1, "calendar_days", "2028-02-29"),
        ("HT-2028-002", "2028-02-28", 2, "weeks", "2028-03-13"),
        ("HT-2028-003", "2024-02-29", 1, "years", "2025-02-28"),
    ]
    for number, signed_on, value, unit, expected in cases:
        response = client.post("/api/v1/contracts", json={
            "name": f"{number} 合同", "contract_no": number, "signed_on": signed_on,
            "delivery_period_value": value, "delivery_period_unit": unit,
            "project_ids": [project["id"]], "operator": "PMO",
        })
        assert response.status_code == 200
        assert response.json()["calculated_delivery_on"] == expected

    impossible = client.post("/api/v1/contracts", json={
        "name": "提前交付合同", "contract_no": "HT-2028-004", "signed_on": "2028-02-28",
        "actual_delivered_on": "2028-02-27", "project_ids": [project["id"]], "operator": "PMO",
    })
    assert impossible.status_code == 422
    assert "实际交付日期" in impossible.json()["message"]
