"""Read-only Markdown governance checks; not a natural-language consistency proof."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


REQ = r"REQ-[A-Z][A-Z0-9]*-\d{3}"
REF = re.compile(rf"({REQ})@v([1-9]\d*)\Z")
HEADING = re.compile(rf"### ({REQ}) \| v([1-9]\d*) \| (\S.*)\Z")
FILES = {
    "requirements": "docs/requirements/pmo-lifecycle-requirements.md",
    "acceptance": "docs/requirements/acceptance-checklist.md",
    "decisions": "docs/requirements/decision-log.md",
}


def prose(text: str):
    """Keep source line numbers, skipping fenced and inline code."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, re.sub(r"(`+).*?\1", "", line)


def table_rows(lines, expected, fail):
    header = None
    for number, line in lines:
        if not line.lstrip().startswith("|"):
            header = None
            continue
        cells = [part.strip() for part in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if expected[0] in cells:
            header = cells
            if any(field not in header for field in expected):
                fail(number, "表头缺少必填元数据：" + ",".join(expected))
            continue
        if not cells or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if header is None:
            if any(re.match(r"(?:AC-\d|DEC-\d)", cell) for cell in cells):
                fail(number, "记录缺少有效表头")
            continue
        if len(cells) != len(header):
            fail(number, "表格列数与表头不符")
        row = dict(zip(header, cells))
        if any(not row.get(field) or (row[field] == "—" and field not in {"旧引用", "新引用"}) for field in expected):
            fail(number, "记录缺少必填元数据")
            continue
        yield number, row


def check(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []

    def error(path, line, message):
        errors.append(f"{path}:{line}: {message}")

    texts = {}
    for key, relative in FILES.items():
        path = root / relative
        try:
            texts[key] = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            error(relative, 1, f"无法读取必需文档：{exc}")
    if len(texts) != len(FILES):
        return errors

    current = {}
    for line, content in prose(texts["requirements"]):
        if not re.match(r"^\s*#+\s+REQ-", content):
            continue
        match = HEADING.fullmatch(content)
        if not match:
            error(FILES["requirements"], line, "需求标题、版本或标题元数据格式错误")
            continue
        rid, version, _ = match.groups()
        if rid in current:
            error(FILES["requirements"], line, f"重复需求ID {rid}")
        current[rid] = (int(version), line)
    if not current:
        error(FILES["requirements"], 1, "当前需求集合为空")

    def references(value, path, line, allow_empty=False):
        if value == "—" and allow_empty:
            return []
        refs = []
        for token in value.split(","):
            match = REF.fullmatch(token.strip())
            if not match:
                error(path, line, f"需求引用或版本格式错误：{token}")
                continue
            ref = (match[1], int(match[2]))
            if ref in refs:
                error(path, line, f"同一记录重复引用：{token}")
            refs.append(ref)
        return refs

    ac_path = FILES["acceptance"]
    covered, seen = set(), set()
    fields = ("验收 ID", "需求引用", "步骤", "预期", "验证层级")
    for line, row in table_rows(prose(texts["acceptance"]), fields, lambda n, m: error(ac_path, n, m)):
        aid = row["验收 ID"]
        if not re.fullmatch(r"AC-\d{3}", aid):
            error(ac_path, line, f"验收ID格式错误：{aid}")
        if aid in seen:
            error(ac_path, line, f"重复验收ID {aid}")
        seen.add(aid)
        if any(layer.strip() not in {"API", "Browser", "Document"} for layer in row["验证层级"].split(",")):
            error(ac_path, line, "验证层级仅允许API,Browser,Document")
        for rid, version in references(row["需求引用"], ac_path, line):
            if rid not in current:
                error(ac_path, line, f"引用不存在的当前需求 {rid}")
            elif version != current[rid][0]:
                error(ac_path, line, f"引用过期或非当前版本 {rid}@v{version}")
            else:
                covered.add(rid)
    for rid, (_, line) in current.items():
        if rid not in covered:
            error(FILES["requirements"], line, f"有效需求缺少验收映射 {rid}")

    dec_path = FILES["decisions"]
    states, retired, seen = {}, set(), set()
    fields = ("决策 ID", "变更类型", "旧引用", "新引用", "理由及依据")
    for line, row in table_rows(prose(texts["decisions"]), fields, lambda n, m: error(dec_path, n, m)):
        did, kind = row["决策 ID"], row["变更类型"]
        if not re.fullmatch(r"DEC-\d{8}-\d{2,}", did):
            error(dec_path, line, f"决策ID格式错误：{did}")
        else:
            try:
                datetime.strptime(did.split("-")[1], "%Y%m%d")
            except ValueError:
                error(dec_path, line, f"决策日期格式错误：{did}")
        if did in seen:
            error(dec_path, line, f"重复决策ID {did}")
        seen.add(did)
        old = references(row["旧引用"], dec_path, line, True)
        new = references(row["新引用"], dec_path, line, True)
        if kind in {"基线整理", "新增"}:
            if old or not new:
                error(dec_path, line, "引入决策须无旧引用且有新引用")
            for rid, version in new:
                if rid in retired:
                    error(dec_path, line, f"退出编号被复用 {rid}")
                if rid in states or version != 1:
                    error(dec_path, line, f"版本链引入错误 {rid}@v{version}，必须首次v1")
                states[rid] = version
        elif kind == "变更":
            if not old or len(old) != len(new) or {r for r, _ in old} != {r for r, _ in new}:
                error(dec_path, line, "变更旧新引用必须对应；拆分合并使用退出及新增记录")
            for rid, version in old:
                if rid in retired or states.get(rid) != version or (rid, version + 1) not in new:
                    error(dec_path, line, f"版本链断裂或退出编号被复用 {rid}@v{version}")
            for rid, version in new:
                states[rid] = version
        elif kind == "退出":
            if not old or new:
                error(dec_path, line, "退出决策须有旧引用且无新引用")
            for rid, version in old:
                if rid in retired or states.get(rid) != version:
                    error(dec_path, line, f"退出版本链错误 {rid}@v{version}")
                retired.add(rid)
        else:
            error(dec_path, line, f"未知变更类型 {kind}")
    for rid, (version, line) in current.items():
        if rid in retired:
            error(FILES["requirements"], line, f"已退出规则仍在当前集合 {rid}")
        if states.get(rid) != version:
            error(FILES["requirements"], line, f"当前版本缺少引入/变更决策 {rid}@v{version}")
    for rid in states.keys() - retired - current.keys():
        error(dec_path, 1, f"决策有效规则不在当前集合且缺少退出决策 {rid}")

    # Scope is repository root Markdown and docs/, not dependency or test trees.
    paths = sorted(set(root.glob("*.md")) | set((root / "docs").rglob("*.md")))
    for path in paths:
        relative = path.relative_to(root)
        try:
            lines = list(prose(path.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeError) as exc:
            error(relative, 1, f"无法读取Markdown：{exc}")
            continue
        definitions = {}
        for line, content in lines:
            match = re.match(r'^\s*\[([^]]+)\]:\s*(<[^>]+>|\S+)', content)
            if match:
                definitions[match[1].casefold()] = match[2]
        for line, content in lines:
            targets = re.findall(r'!?\[[^]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\s*\)', content)
            definition = re.match(r'^\s*\[[^]]+\]:\s*(<[^>]+>|\S+)', content)
            if definition:
                targets.append(definition[1])
            for label, identifier in re.findall(r'!?\[([^]\n]+)\]\[([^]\n]*)\]', content):
                ref = (identifier or label).casefold()
                if ref not in definitions:
                    error(relative, line, f"Markdown引用链接未定义：{ref}")
                else:
                    targets.append(definitions[ref])
            for target in targets:
                target = target.strip("<>")
                if target.startswith("//") or urlsplit(target).scheme:
                    continue
                parts = urlsplit(target)
                destination = (path.parent / unquote(parts.path)).resolve() if parts.path else path
                if not destination.exists():
                    error(relative, line, f"本地Markdown链接失效：{target}")
                elif parts.fragment and destination.suffix.lower() == ".md":
                    anchors, counts = set(), {}
                    for _, heading in prose(destination.read_text(encoding="utf-8-sig")):
                        if not re.match(r"^#{1,6} ", heading):
                            continue
                        slug = re.sub(r"[^\w\- ]", "", re.sub(r"^#+\s+", "", heading).lower()).replace(" ", "-")
                        count = counts.get(slug, 0)
                        counts[slug] = count + 1
                        anchors.add(slug + (f"-{count}" if count else ""))
                    if unquote(parts.fragment) not in anchors:
                        error(relative, line, f"本地Markdown锚点失效：{target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    errors = check(parser.parse_args().root)
    if errors:
        print("\n".join(errors))
        return 1
    print("PASS: 文档结构与引用检查通过；未验证自然语言语义或产品行为。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
