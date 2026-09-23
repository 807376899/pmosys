from __future__ import annotations

import io

import pandas as pd

from backend.app.db.connection import get_connection


def test_import_preview_and_commit(client):
    df = pd.DataFrame(
        [
            {
                "项目名称": "导入项目",
                "项目分类": "专业教学软件项目",
                "项目状态": "未立项",
                "初始预算": 50,
                "有效预算": 45,
            }
        ]
    )
    output = io.BytesIO()
    df.to_excel(output, index=False, sheet_name="项目数据")
    output.seek(0)
    preview = client.post(
        "/api/v1/imports/projects/preview",
        files={"file": ("import.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["valid_rows"] == 1
    assert body["records"][0]["approved_budget"] == 45.0
    commit = client.post(
        "/api/v1/imports/projects/commit",
        json={"records": body["records"], "operator": "批量导入"},
    )
    assert commit.status_code == 200
    assert commit.json()["success"] == 1
    project_id = client.get("/api/v1/projects").json()["items"][0]["id"]
    assert client.get(f"/api/v1/projects/{project_id}/work-items").json() == []
    assert client.get(f"/api/v1/projects/{project_id}/external-constraints").json() == []


def test_import_uses_active_project_type_dictionary(client):
    created = client.post(
        "/api/v1/project-types",
        json={"name": "教学设备项目", "code_prefix": "EQ", "sort_order": 3, "operator": "PMO"},
    )
    assert created.status_code == 200
    df = pd.DataFrame([{"项目名称": "设备导入项目", "项目分类": "教学设备项目", "项目状态": "未立项"}])
    output = io.BytesIO()
    df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post(
        "/api/v1/imports/projects/preview",
        files={"file": ("equipment.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview.status_code == 200
    assert preview.json()["records"][0]["project_type"] == created.json()["code"]


def test_completed_import_keeps_blank_budget_and_records_implementation_year(client):
    df = pd.DataFrame([{
        "项目名称": "已完成历史项目", "项目分类": "专业教学软件项目", "项目状态": "已完成",
        "完成日期": "2025-12", "推进年度": "2025",
    }])
    output = io.BytesIO()
    df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("completed.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert preview.status_code == 200
    record = preview.json()["records"][0]
    assert record["budget"] is None
    assert client.post("/api/v1/imports/projects/commit", json={"records": [record], "operator": "PMO"}).status_code == 200
    project = client.get("/api/v1/projects", params={"group": "completed"}).json()["items"][0]
    assert project["stage"] == "已完成"
    assert project["implementation_year"] == 2025
    assert project["actual_end_date"] == "2025-12"
    detail = client.get(f"/api/v1/projects/{project['id']}").json()
    assert detail["advancement"]["status"] == "completed"
    assert detail["implementation_year"] == 2025
    assert detail["has_completed_advancement_cycle"] is True


def test_import_preview_rejects_invalid_or_duplicate_project_codes(client):
    existing = client.post("/api/v1/projects", json={"name": "已有项目", "project_type": "software", "project_code": "SW20260001", "operator": "PMO"})
    assert existing.status_code == 200
    df = pd.DataFrame([
        {"项目名称": "格式错误", "项目分类": "专业教学软件项目", "项目状态": "未立项", "项目编号": "SW-2026-1"},
        {"项目名称": "数据库重复", "项目分类": "专业教学软件项目", "项目状态": "未立项", "项目编号": "SW20260001"},
        {"项目名称": "文件重复一", "项目分类": "专业教学软件项目", "项目状态": "未立项", "项目编号": "SW20260002"},
        {"项目名称": "文件重复二", "项目分类": "专业教学软件项目", "项目状态": "未立项", "项目编号": "SW20260002"},
    ])
    output = io.BytesIO(); df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("codes.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] == 0
    assert preview.json()["invalid_rows"] == 4


def test_history_import_accepts_matching_historical_code_but_rejects_future_code(client):
    df = pd.DataFrame([
        {"项目名称": "历史编号", "项目分类": "专业教学软件项目", "项目状态": "已完成", "项目编号": "SW20250001", "推进年度": "2025", "完成日期": "2026-01-15"},
        {"项目名称": "未来编号", "项目分类": "专业教学软件项目", "项目状态": "未立项", "项目编号": "SW20270001"},
    ])
    output = io.BytesIO(); df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("history-codes.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] == 1
    assert preview.json()["records"][0]["project_code"] == "SW20250001"
    assert "年份" in preview.json()["errors"][0]["message"]


def test_history_import_commit_keeps_manual_historical_code_and_generates_blank_codes(client):
    df = pd.DataFrame([
        {"项目名称": "历史场所项目", "项目分类": "实践教学场所项目", "项目状态": "已完成", "项目编号": "SY20200001", "推进年度": "2020", "完成日期": "2021-01-15"},
        {"项目名称": "自动编号项目一", "项目分类": "实践教学场所项目", "项目状态": "未立项"},
        {"项目名称": "自动编号项目二", "项目分类": "实践教学场所项目", "项目状态": "未立项"},
    ])
    output = io.BytesIO(); df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("mixed-history-codes.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    assert preview.status_code == 200
    records = preview.json()["records"]
    assert preview.json()["invalid_rows"] == 0
    assert records[0]["project_code"] == "SY20200001"
    assert len({record["project_code"] for record in records}) == 3
    assert all(record["project_code"].startswith("SY2026") for record in records[1:])

    commit = client.post("/api/v1/imports/projects/commit", json={"records": records, "operator": "PMO"})

    assert commit.status_code == 200
    assert commit.json()["success"] == 3
    imported = client.get("/api/v1/projects", params={"page_size": 20}).json()["items"]
    assert {project["project_code"] for project in imported} == {record["project_code"] for record in records}


def test_import_commit_revalidates_each_record_without_partial_write(client):
    df = pd.DataFrame([
        {"项目名称": "可导入项目", "项目分类": "实践教学场所项目", "项目状态": "未立项"},
        {"项目名称": "确认前失效项目", "项目分类": "实践教学场所项目", "项目状态": "未立项"},
    ])
    output = io.BytesIO(); df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("revalidate.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    records = preview.json()["records"]
    records[1]["project_type"] = "disabled-or-missing"

    commit = client.post("/api/v1/imports/projects/commit", json={"records": records, "operator": "PMO"})

    assert commit.status_code == 200
    assert commit.json()["success"] == 0
    assert commit.json()["failed"] == 1
    error = commit.json()["errors"][0]
    assert error["row_number"] == records[1]["row_number"]
    assert error["name"] == "确认前失效项目"
    assert error["code"] == "VALIDATION_ERROR"
    assert "不存在或已停用" in error["message"]
    assert client.get("/api/v1/projects", params={"page_size": 20}).json()["total"] == 0


def test_import_commit_rejects_project_code_added_after_preview(client):
    df = pd.DataFrame([{"项目名称": "历史场所项目", "项目分类": "实践教学场所项目", "项目状态": "未立项", "项目编号": "SY20200001"}])
    output = io.BytesIO(); df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("concurrent-code.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    record = preview.json()["records"][0]
    with get_connection() as conn:
        conn.execute("INSERT INTO projects (project_code, name, current_status, project_type) VALUES (?, ?, ?, ?)", (record["project_code"], "确认前已创建", "draft", "laboratory"))

    commit = client.post("/api/v1/imports/projects/commit", json={"records": [record], "operator": "PMO"})

    assert commit.status_code == 200
    assert commit.json()["success"] == 0
    assert commit.json()["errors"][0]["code"] == "DUPLICATE_PROJECT_CODE"
    assert client.get("/api/v1/projects", params={"page_size": 20}).json()["total"] == 1


def test_batch_backfill_completed_history_creates_cycle_and_can_clear_imported_zero_budget(client):
    df = pd.DataFrame([{
        "项目名称": "待补录历史项目", "项目分类": "专业教学软件项目", "项目状态": "已完成",
        "完成日期": "2026-01", "推进年度": "2025", "初始预算": 0,
    }])
    output = io.BytesIO(); df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("legacy.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    assert client.post("/api/v1/imports/projects/commit", json={"records": preview["records"], "operator": "PMO"}).status_code == 200
    project = client.get("/api/v1/projects", params={"group": "completed"}).json()["items"][0]
    with get_connection() as conn:
        conn.execute("DELETE FROM project_advancement_records WHERE project_id=?", (project["id"],))
        conn.execute("UPDATE projects SET advancement_year=NULL WHERE id=?", (project["id"],))

    missing_cycle = client.get(f"/api/v1/projects/{project['id']}").json()
    assert missing_cycle["has_completed_advancement_cycle"] is False

    response = client.post("/api/v1/projects/batch-backfill-completed-advancement", json={
        "project_ids": [project["id"]], "advancement_year": 2025, "operator": "PMO", "reason": "补录历史实施", "clear_zero_budget": True,
    })

    assert response.status_code == 200
    detail = client.get(f"/api/v1/projects/{project['id']}").json()
    assert detail["implementation_year"] == 2025
    assert detail["advancement"]["status"] == "completed"
    assert detail["has_completed_advancement_cycle"] is True
    assert detail["budget"] is None
    cycles = client.get(f"/api/v1/projects/{project['id']}/advancement-cycles").json()
    assert [(item["advancement_year"], item["status"]) for item in cycles] == [(2025, "completed")]


def test_batch_backfill_rejects_completed_project_with_existing_history(client):
    df = pd.DataFrame([{
        "项目名称": "已有历史项目", "项目分类": "专业教学软件项目", "项目状态": "已完成",
        "完成日期": "2026-01", "推进年度": "2025",
    }])
    output = io.BytesIO(); df.to_excel(output, index=False, sheet_name="项目数据")
    preview = client.post("/api/v1/imports/projects/preview", files={"file": ("completed-history.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    assert client.post("/api/v1/imports/projects/commit", json={"records": preview["records"], "operator": "PMO"}).status_code == 200
    project = client.get("/api/v1/projects", params={"group": "completed"}).json()["items"][0]

    response = client.post("/api/v1/projects/batch-backfill-completed-advancement", json={
        "project_ids": [project["id"]], "advancement_year": 2025, "operator": "PMO", "reason": "重复补录",
    })

    assert response.status_code == 422
