from __future__ import annotations

from backend.app.db.connection import get_connection
from backend.app.repositories import workflow as workflow_repo


def get_statuses() -> list[dict]:
    with get_connection() as conn:
        return workflow_repo.fetch_all_statuses(conn)


def get_transition_rules() -> list[dict]:
    with get_connection() as conn:
        return workflow_repo.fetch_all_transition_rules(conn)


def get_allowed_transitions(from_status: str) -> list[dict]:
    with get_connection() as conn:
        return workflow_repo.fetch_allowed_transitions(conn, from_status)


def get_status_stats() -> list[dict]:
    with get_connection() as conn:
        return workflow_repo.fetch_status_stats(conn)


def generate_mermaid_diagram() -> str:
    statuses = get_statuses()
    transitions = get_transition_rules()
    lines = ["stateDiagram-v2", "    direction LR"]
    for status in statuses:
        if status["is_terminal"]:
            lines.append(f'    state "{status["status_name"]}" as {status["status_code"]} <<terminal>>')
        else:
            lines.append(f'    state "{status["status_name"]}" as {status["status_code"]}')
    for rule in transitions:
        tag = " [需审批]" if rule["requires_approval"] else ""
        lines.append(f'    {rule["from_status"]} --> {rule["to_status"]} : {rule["action_name"]}{tag}')
    return "\n".join(lines)

