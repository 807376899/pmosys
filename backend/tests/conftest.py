from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_pmo.db"
    monkeypatch.setenv("PMO_DB_PATH", str(db_path))

    import backend.app.main as main_module

    importlib.reload(main_module)
    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as test_client:
        yield test_client


@pytest.fixture()
def create_project_payload():
    def _build(**overrides):
        payload = {
            "project_code": "",
            "name": "示例项目",
            "description": "描述",
            "department": "信息中心",
            "sponsor": "张主任",
            "project_manager": "李工",
            "category": "信息化建设",
            "project_type": "teaching_software",
            "budget": 100,
            "approved_budget": None,
            "special_note": "",
            "actual_start_date": "",
            "actual_end_date": "",
            "operator": "PMO办公室",
        }
        payload.update(overrides)
        return payload

    return _build
