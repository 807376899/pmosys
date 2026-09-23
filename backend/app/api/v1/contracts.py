from __future__ import annotations

from fastapi import APIRouter, Body, Query

from backend.app.services.contracts import (
    create_contract,
    create_contract_progress_log,
    delete_contract_progress_log,
    get_contract,
    get_contract_progress_logs,
    list_project_contracts,
    record_contract_acceptance,
    search_contracts,
    supplier_suggestions,
    update_contract,
    update_contract_progress_log,
    update_contract_projects,
)


router = APIRouter(prefix="/contracts", tags=["contracts"])
project_router = APIRouter(prefix="/projects", tags=["contracts"])


@router.post("")
def create(payload: dict = Body(...)):
    return create_contract(payload)


@router.get("")
def search(query: str = Query("")):
    return search_contracts(query)


@router.get("/supplier-suggestions")
def suppliers(query: str = Query("")):
    return supplier_suggestions(query)


@router.get("/{contract_id}")
def read(contract_id: int):
    return get_contract(contract_id)


@router.patch("/{contract_id}")
def patch(contract_id: int, payload: dict = Body(...)):
    return update_contract(contract_id, payload)


@router.put("/{contract_id}/projects")
def replace_projects(contract_id: int, payload: dict = Body(...)):
    return update_contract_projects(contract_id, payload)


@router.get("/{contract_id}/progress-logs")
def list_progress(contract_id: int):
    return get_contract_progress_logs(contract_id)


@router.post("/{contract_id}/progress-logs")
def add_progress(contract_id: int, payload: dict = Body(...)):
    return create_contract_progress_log(contract_id, payload)


@router.patch("/{contract_id}/progress-logs/{log_id}")
def patch_progress(contract_id: int, log_id: int, payload: dict = Body(...)):
    return update_contract_progress_log(contract_id, log_id, payload)


@router.delete("/{contract_id}/progress-logs/{log_id}")
def remove_progress(contract_id: int, log_id: int, payload: dict = Body(...)):
    delete_contract_progress_log(contract_id, log_id, payload)
    return {"success": True}


@router.post("/{contract_id}/acceptance-records")
def add_acceptance(contract_id: int, payload: dict = Body(...)):
    return record_contract_acceptance(contract_id, payload)


@project_router.get("/{project_id}/contracts")
def list_for_project(project_id: int):
    return list_project_contracts(project_id)
