from __future__ import annotations

import io

import pandas as pd


def test_import_preview_and_commit(client):
    df = pd.DataFrame(
        [
            {
                "项目名称": "导入项目",
                "项目类型": "教学软件",
                "当前状态": "draft",
                "预算(万元)": 50,
            }
        ]
    )
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    preview = client.post(
        "/api/v1/imports/projects/preview",
        files={"file": ("import.xlsx", output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["valid_rows"] == 1
    commit = client.post(
        "/api/v1/imports/projects/commit",
        json={"records": body["records"], "operator": "批量导入"},
    )
    assert commit.status_code == 200
    assert commit.json()["success"] == 1

