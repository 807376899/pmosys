"""Isolated document fixtures only; no application imports or business database."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_docs_governance.py"
spec = importlib.util.spec_from_file_location("docs_governance", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def tree(tmp_path):
    folder = tmp_path / "docs" / "requirements"
    folder.mkdir(parents=True)
    (folder / "pmo-lifecycle-requirements.md").write_text("# 当前需求\n\n### REQ-UI-001 | v1 | 示例\n\n可观察行为。\n", encoding="utf-8")
    (folder / "acceptance-checklist.md").write_text(
        "| 验收 ID | 需求引用 | 步骤 | 预期 | 验证层级 |\n| --- | --- | --- | --- | --- |\n"
        "| AC-001 | REQ-UI-001@v1 | 点击保存 | 显示结果 | Browser |\n", encoding="utf-8")
    (folder / "decision-log.md").write_text(
        "| 决策 ID | 变更类型 | 旧引用 | 新引用 | 理由及依据 |\n| --- | --- | --- | --- | --- |\n"
        "| DEC-20260911-01 | 基线整理 | — | REQ-UI-001@v1 | 用户授权首次整理 |\n", encoding="utf-8")
    return tmp_path


def change(tree, name, old, new):
    path = tree / "docs" / "requirements" / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def snapshot(tree):
    return {str(p.relative_to(tree)): (p.read_bytes(), p.stat().st_mtime_ns) for p in tree.rglob("*") if p.is_file()}


def test_valid_baseline_and_success_does_not_write(tree):
    before = snapshot(tree)
    assert module.check(tree) == []
    result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tree)], capture_output=True)
    assert result.returncode == 0
    assert snapshot(tree) == before


@pytest.mark.parametrize("name,old,new,expected", [
    ("pmo-lifecycle-requirements.md", "可观察行为。", "### REQ-UI-001 | v1 | 重复", "重复需求ID"),
    ("acceptance-checklist.md", "| AC-001", "| AC-001", "重复验收ID"),
    ("decision-log.md", "| DEC-20260911-01", "| DEC-20260911-01", "重复决策ID"),
    ("acceptance-checklist.md", "REQ-UI-001@v1", "REQ-UI-999@v1", "引用不存在"),
    ("acceptance-checklist.md", "REQ-UI-001@v1", "REQ-UI-001@v2", "引用过期"),
    ("acceptance-checklist.md", "点击保存", "", "缺少必填元数据"),
    ("pmo-lifecycle-requirements.md", "| v1 |", "| v0 |", "格式错误"),
    ("pmo-lifecycle-requirements.md", "| v1 | 示例", "| v1 | ", "格式错误"),
    ("acceptance-checklist.md", "REQ-UI-001@v1", "REQ-UI-001@version1", "版本格式错误"),
    ("acceptance-checklist.md", "| AC-001 | REQ-UI-001@v1 | 点击保存 | 显示结果 | Browser |", "", "缺少验收"),
    ("decision-log.md", "| DEC-20260911-01 | 基线整理 | — | REQ-UI-001@v1 | 用户授权首次整理 |", "", "缺少引入"),
    ("decision-log.md", "用户授权首次整理", "", "缺少必填元数据"),
    ("decision-log.md", "用户授权首次整理", "—", "缺少必填元数据"),
    ("decision-log.md", "DEC-20260911-01", "DEC-20261340-01", "决策日期格式错误"),
    ("decision-log.md", "REQ-UI-001@v1", "REQ-UI-001@v3", "版本链引入错误"),
    ("pmo-lifecycle-requirements.md", "可观察行为。", "[失效](missing.md)", "链接失效"),
    ("pmo-lifecycle-requirements.md", "可观察行为。", "[失效](#missing)", "锚点失效"),
    ("pmo-lifecycle-requirements.md", "可观察行为。", "[失效][missing]", "未定义"),
])
def test_invalid_documents_fail_without_writing(tree, name, old, new, expected):
    if old == new:
        path = tree / "docs" / "requirements" / name
        content = path.read_text(encoding="utf-8")
        path.write_text(content + content.splitlines()[-1] + "\n", encoding="utf-8")
    else:
        change(tree, name, old, new)
    before = snapshot(tree)
    errors = module.check(tree)
    assert any(expected in error for error in errors), errors
    assert all(":" in error for error in errors)
    result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tree)], capture_output=True)
    assert result.returncode == 1
    assert snapshot(tree) == before


def append_decision(tree, row):
    path = tree / "docs" / "requirements" / "decision-log.md"
    path.write_text(path.read_text(encoding="utf-8") + row + "\n", encoding="utf-8")


def test_version_chain_valid_then_broken(tree):
    change(tree, "pmo-lifecycle-requirements.md", "| v1 |", "| v2 |")
    change(tree, "acceptance-checklist.md", "@v1", "@v2")
    append_decision(tree, "| DEC-20260911-02 | 变更 | REQ-UI-001@v1 | REQ-UI-001@v2 | 用户确认行为改变 |")
    assert not module.check(tree)
    change(tree, "decision-log.md", "| 变更 | REQ-UI-001@v1 |", "| 变更 | REQ-UI-001@v0 |")
    assert module.check(tree)


def test_retirement_and_reuse_are_rejected(tree):
    append_decision(tree, "| DEC-20260911-02 | 退出 | REQ-UI-001@v1 | — | 用户退出 |")
    assert any("已退出规则仍在" in e for e in module.check(tree))
    append_decision(tree, "| DEC-20260911-03 | 新增 | — | REQ-UI-001@v1 | 错误复用 |")
    assert any("退出编号被复用" in e for e in module.check(tree))


def test_skipped_version_is_rejected(tree):
    change(tree, "pmo-lifecycle-requirements.md", "| v1 |", "| v3 |")
    change(tree, "acceptance-checklist.md", "@v1", "@v3")
    append_decision(tree, "| DEC-20260911-02 | 变更 | REQ-UI-001@v1 | REQ-UI-001@v3 | 不可跳版 |")
    assert any("版本链断裂" in e for e in module.check(tree))


def test_valid_retirement_retains_history_and_does_not_require_old_acceptance(tree):
    change(tree, "pmo-lifecycle-requirements.md", "REQ-UI-001", "REQ-UI-002")
    change(tree, "acceptance-checklist.md", "REQ-UI-001", "REQ-UI-002")
    append_decision(tree, "| DEC-20260911-02 | 退出 | REQ-UI-001@v1 | — | 用户退出旧要求 |")
    append_decision(tree, "| DEC-20260911-03 | 新增 | — | REQ-UI-002@v1 | 用户新增替代要求 |")
    assert not module.check(tree)


def test_missing_retirement_is_rejected(tree):
    append_decision(tree, "| DEC-20260911-02 | 新增 | — | REQ-UI-002@v1 | 后续从正文消失 |")
    assert any("缺少退出决策" in e for e in module.check(tree))


def test_history_is_not_current_but_its_local_links_are_checked(tree):
    history = tree / "docs" / "requirements" / "history"
    history.mkdir()
    file = history / "old.md"
    file.write_text("### REQ-UI-001 | v9 | 历史重复\n### REQ-OLD-999 | v1 | 历史\n", encoding="utf-8")
    assert not module.check(tree)
    file.write_text(file.read_text(encoding="utf-8") + "[坏链接](missing.md)\n", encoding="utf-8")
    assert any("链接失效" in e for e in module.check(tree))


def test_links_valid_reference_unicode_space_and_code_examples(tree):
    folder = tree / "docs" / "requirements"
    (folder / "有 空格.md").write_text("# 中文标题\n", encoding="utf-8")
    change(tree, "pmo-lifecycle-requirements.md", "可观察行为。", "\n".join([
        "[有效](<有 空格.md#中文标题>)", "[引用][文档]", "[文档]: <有 空格.md>",
        "[外部](https://example.com/missing)", "```markdown", "[示例](missing.md)", "```",
    ]))
    assert not module.check(tree)
