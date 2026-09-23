from __future__ import annotations

import pytest


def test_project_crud_and_patch_whitelist(client, create_project_payload):
    created = client.post("/api/v1/projects", json=create_project_payload()).json()
    detail = client.get(f"/api/v1/projects/{created['id']}")
    assert detail.status_code == 200
    patch = client.patch(
        f"/api/v1/projects/{created['id']}",
        json={"name": "更新后的项目", "budget": 123.5, "operator": "PMO", "reason": "修正导入信息"},
    )
    assert patch.status_code == 200
    assert patch.json()["name"] == "更新后的项目"
    invalid_patch = client.patch(
        f"/api/v1/projects/{created['id']}",
        json={"current_status": "closed", "operator": "PMO", "reason": "错误测试"},
    )
    assert invalid_patch.status_code == 422
    assert invalid_patch.json()["code"] == "VALIDATION_ERROR"
    missing_audit = client.request("DELETE", f"/api/v1/projects/{created['id']}", json={})
    assert missing_audit.status_code == 422

    delete = client.request(
        "DELETE",
        f"/api/v1/projects/{created['id']}",
        json={"operator": "PMO", "reason": "重复导入，改由正确项目保留"},
    )
    assert delete.status_code == 200
    assert delete.json()["soft_deleted"] is True
    remaining = client.get("/api/v1/projects").json()["items"]
    assert created["id"] not in [project["id"] for project in remaining]


def test_software_procurement_nature_is_structured_project_data(client, create_project_payload):
    created = client.post(
        "/api/v1/projects",
        json=create_project_payload(project_type="software", procurement_nature="service"),
    )
    assert created.status_code == 200
    assert created.json()["procurement_nature"] == "service"

    updated = client.patch(
        f"/api/v1/projects/{created.json()['id']}",
        json={"procurement_nature": "mixed", "operator": "PMO", "reason": "补充采购属性"},
    )
    assert updated.status_code == 200
    assert updated.json()["procurement_nature"] == "mixed"


def test_project_edit_persists_name_and_procurement_nature_with_audit(client, create_project_payload):
    project = client.post(
        "/api/v1/projects",
        json=create_project_payload(name="原项目名称", project_type="software", procurement_nature="goods"),
    ).json()

    updated = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "name": "更新后的项目名称",
            "procurement_nature": "service",
            "operator": "PMO办公室",
            "reason": "修正导入分类属性",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["name"] == "更新后的项目名称"
    assert updated.json()["procurement_nature"] == "service"
    assert updated.json()["project_summary_display"] == "专业教学软件项目 · 服务"
    assert client.get(f"/api/v1/projects/{project['id']}").json()["name"] == "更新后的项目名称"
    audit = client.get(f"/api/v1/projects/{project['id']}/audit-events").json()
    assert audit[0]["event_type"] == "PROJECT_UPDATED"
    assert audit[0]["reason"] == "修正导入分类属性"


def test_project_edit_can_clear_unrecorded_budget_and_keep_completion_date(client, create_project_payload):
    project = client.post(
        "/api/v1/projects",
        json=create_project_payload(budget=0, actual_end_date="2026-01-15"),
    ).json()

    updated = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"budget": None, "actual_end_date": "2026-02", "operator": "PMO", "reason": "纠正历史导入空预算和完成时间"},
    )

    assert updated.status_code == 200
    assert updated.json()["budget"] is None
    assert updated.json()["actual_end_date"] == "2026-02"


@pytest.mark.parametrize("keyword", ["检索项目", "SW20260001", "检索说明", "检索发起人", "检索备注"])
def test_project_keyword_search_supports_all_project_fields_after_join(client, create_project_payload, keyword):
    project = client.post(
        "/api/v1/projects",
        json=create_project_payload(
            name="检索项目",
            project_code="SW20260001",
            description="检索说明",
            sponsor="检索发起人",
            special_note="检索备注",
        ),
    ).json()

    response = client.get("/api/v1/projects", params={"keyword": keyword})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [project["id"]]


def test_soft_deleted_project_can_be_listed_and_restored(client, create_project_payload):
    created = client.post("/api/v1/projects", json=create_project_payload()).json()
    assert client.request(
        "DELETE", f"/api/v1/projects/{created['id']}", json={"operator": "PMO", "reason": "误导入"}
    ).status_code == 200

    removed = client.get("/api/v1/projects", params={"include_deleted": True}).json()["items"]
    assert [project["id"] for project in removed] == [created["id"]]

    restored = client.post(
        f"/api/v1/projects/{created['id']}/restore", json={"operator": "PMO", "reason": "确认应保留"}
    )
    assert restored.status_code == 200
    assert restored.json()["id"] == created["id"]
    assert client.get("/api/v1/projects").json()["items"][0]["id"] == created["id"]


def test_project_list_supports_project_type_filter(client, create_project_payload):
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="软件项目", project_type="teaching_software"),
    )
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="场所项目", project_type="practical_teaching_site"),
    )
    response = client.get("/api/v1/projects", params={"project_type": "teaching_software"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["project_type"] == "software"


def test_legacy_project_type_aliases_are_normalized_for_filtering(client, create_project_payload):
    client.post("/api/v1/projects", json=create_project_payload(name="旧软件项目", project_type="teaching_software"))
    client.post("/api/v1/projects", json=create_project_payload(name="旧场所项目", project_type="practical_teaching_site"))

    software = client.get("/api/v1/projects", params={"project_type": "software"}).json()["items"]
    laboratory = client.get("/api/v1/projects", params={"project_type": "laboratory"}).json()["items"]

    assert [item["name"] for item in software] == ["旧软件项目"]
    assert [item["name"] for item in laboratory] == ["旧场所项目"]
    assert software[0]["project_type"] == "software"


def test_project_types_are_the_single_configurable_project_classification(client, create_project_payload):
    initial = client.get("/api/v1/project-types")
    assert initial.status_code == 200
    assert [item["name"] for item in initial.json()] == ["专业教学软件项目", "实践教学场所项目"]

    created_type = client.post(
        "/api/v1/project-types",
        json={"code": "equipment", "name": "教学设备项目", "code_prefix": "EQ", "sort_order": 3, "operator": "PMO"},
    )
    assert created_type.status_code == 200

    project = client.post(
        "/api/v1/projects",
        json=create_project_payload(name="设备项目", project_type="equipment", category=""),
    )
    assert project.status_code == 200
    assert project.json()["project_type"] == "equipment"
    assert project.json()["category"] in {"", None}


def test_project_type_creation_generates_internal_code(client):
    created = client.post(
        "/api/v1/project-types",
        json={"name": "教学设备项目", "code_prefix": "EQ", "sort_order": 3, "operator": "PMO"},
    )
    assert created.status_code == 200
    assert created.json()["code"].startswith("custom_")


def test_project_list_sorting_and_department_order(client, create_project_payload, monkeypatch):
    monkeypatch.setenv("PMO_DEPARTMENT_ORDER", "财务部,信息中心,教务处")
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="信息项目", department="信息中心"),
    )
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="财务项目", department="财务部"),
    )
    client.post(
        "/api/v1/projects",
        json=create_project_payload(name="其他项目", department="后勤处"),
    )
    from backend.app.db.connection import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE projects SET advancement_year=2025 WHERE name='信息项目'")
        conn.execute("UPDATE projects SET advancement_year=2024 WHERE name='财务项目'")
        conn.execute("UPDATE projects SET advancement_year=2026 WHERE name='其他项目'")

    response = client.get("/api/v1/projects", params={"sort_by": "department", "sort_dir": "asc"})
    assert response.status_code == 200
    assert [item["department"] for item in response.json()["items"]] == ["财务部", "信息中心", "后勤处"]

    response = client.get("/api/v1/projects", params={"sort_by": "implementation_year", "sort_dir": "desc"})
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["其他项目", "信息项目", "财务项目"]

    response = client.get("/api/v1/meta/departments")
    assert response.status_code == 200
    assert response.json() == ["财务部", "信息中心", "后勤处"]


def test_project_list_department_and_year_sorts_use_stable_secondary_keys(client, create_project_payload, monkeypatch):
    monkeypatch.setenv("PMO_DEPARTMENT_ORDER", "财务部,信息中心")
    projects = [
        ("财务较晚项目", "财务部", "SW20260003"),
        ("财务较早项目", "财务部", "SW20260001"),
        ("信息项目", "信息中心", "SW20260002"),
        ("财务同年项目", "财务部", "SW20260004"),
    ]
    for name, department, code in projects:
        assert client.post("/api/v1/projects", json=create_project_payload(
            name=name, department=department, project_code=code,
        )).status_code == 200

    from backend.app.db.connection import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE projects SET advancement_year=2025, actual_end_date='2025-11', updated_at='2026-01-01' WHERE name='财务较晚项目'")
        conn.execute("UPDATE projects SET advancement_year=2024, actual_end_date='2024-12', updated_at='2026-01-01' WHERE name='财务较早项目'")
        conn.execute("UPDATE projects SET advancement_year=2025, actual_end_date='2025-01', updated_at='2026-12-01' WHERE name='信息项目'")
        conn.execute("UPDATE projects SET advancement_year=2025, actual_end_date='2025-07', updated_at='2026-01-01' WHERE name='财务同年项目'")

    department = client.get("/api/v1/projects", params={"sort_by": "department", "sort_dir": "asc"}).json()["items"]
    assert [item["name"] for item in department] == ["财务较早项目", "财务较晚项目", "财务同年项目", "信息项目"]

    implementation_year = client.get("/api/v1/projects", params={"sort_by": "implementation_year", "sort_dir": "desc"}).json()["items"]
    assert [item["name"] for item in implementation_year] == ["财务较晚项目", "财务同年项目", "信息项目", "财务较早项目"]

    completion_year = client.get("/api/v1/projects", params={"sort_by": "completion_year", "sort_dir": "desc"}).json()["items"]
    assert [item["name"] for item in completion_year] == ["财务较晚项目", "财务同年项目", "信息项目", "财务较早项目"]


def test_default_list_sort_and_year_facet_do_not_depend_on_current_result(client, create_project_payload, monkeypatch):
    monkeypatch.setenv("PMO_DEPARTMENT_ORDER", "财务部")
    for name, code in [("无年份项目", "SW20260003"), ("较早项目", "SW20260001"), ("较晚项目", "SW20260002")]:
        assert client.post("/api/v1/projects", json=create_project_payload(name=name, department="财务部", project_code=code)).status_code == 200

    from backend.app.db.connection import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE projects SET advancement_year=2024 WHERE name='较早项目'")
        conn.execute("UPDATE projects SET advancement_year=2025 WHERE name='较晚项目'")

    default_items = client.get("/api/v1/projects").json()["items"]
    assert [item["name"] for item in default_items] == ["较早项目", "较晚项目", "无年份项目"]

    filtered = client.get("/api/v1/projects", params={"implementation_year": "2025"})
    assert filtered.status_code == 200
    assert [item["name"] for item in filtered.json()["items"]] == ["较晚项目"]
    assert set(filtered.json()["filter_options"]["implementation_years"]) == {"2024", "2025"}


def test_default_list_sort_uses_project_type_between_year_and_project_code(client, create_project_payload):
    first_type = client.post(
        "/api/v1/project-types",
        json={"name": "前序分类", "code_prefix": "ZZ", "sort_order": 10, "operator": "PMO"},
    ).json()
    second_type = client.post(
        "/api/v1/project-types",
        json={"name": "后序分类", "code_prefix": "AA", "sort_order": 20, "operator": "PMO"},
    ).json()
    projects = [
        ("同年后序", second_type["code"], "AA20260001"),
        ("同年前序", first_type["code"], "ZZ20260099"),
        ("无年份前序", first_type["code"], "ZZ20260001"),
    ]
    for name, project_type, project_code in projects:
        assert client.post(
            "/api/v1/projects",
            json=create_project_payload(
                name=name,
                department="教务处",
                project_type=project_type,
                project_code=project_code,
            ),
        ).status_code == 200

    from backend.app.db.connection import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE projects SET advancement_year=2026 WHERE name IN ('同年后序', '同年前序')")

    listed = client.get("/api/v1/projects").json()["items"]
    assert [item["name"] for item in listed] == ["同年前序", "同年后序", "无年份前序"]


def test_progress_log_updates_latest_activity_but_basic_project_edit_does_not(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    item = client.post(
        f"/api/v1/projects/{project['id']}/work-items", json={"name": "材料准备", "operator": "PMO"}
    ).json()

    before = next(value for value in client.get("/api/v1/projects").json()["items"] if value["id"] == project["id"])
    assert before.get("latest_activity_at") is None
    assert client.post(
        f"/api/v1/projects/{project['id']}/work-items/{item['id']}/progress-logs",
        json={"operator": "PMO", "content": "已联系负责人"},
    ).status_code == 200
    after_progress = next(value for value in client.get("/api/v1/projects").json()["items"] if value["id"] == project["id"])
    assert after_progress["latest_activity_at"]

    assert client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "仅修改基本信息", "operator": "PMO", "reason": "更正名称"},
    ).status_code == 200
    after_edit = next(value for value in client.get("/api/v1/projects").json()["items"] if value["id"] == project["id"])
    assert after_edit["latest_activity_at"] == after_progress["latest_activity_at"]


def test_project_detail_projects_only_lifecycle_stage_events(client, create_project_payload):
    project = client.post("/api/v1/projects", json=create_project_payload()).json()
    assert client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={
        "to_status": "established", "operator": "PMO", "comment": "登记立项",
    }).status_code == 200
    assert client.post(f"/api/v1/projects/{project['id']}/pmo-override", json={
        "to_status": "closed", "operator": "PMO", "comment": "项目完成",
    }).status_code == 200

    detail = client.get(f"/api/v1/projects/{project['id']}").json()
    assert [event["kind"] for event in detail["stage_events"]] == ["established", "completed"]
    assert [event["label"] for event in detail["stage_events"]] == ["立项入项目库", "项目完成"]
