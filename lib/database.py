"""
PMO项目管理系统 - 数据库层

职责：
1. 数据库连接管理（SQLite），使用绝对路径，自动创建目录
2. 表结构初始化（projects + status_history + status_definitions + transition_rules）
3. 种子数据写入（状态定义 + 流转规则）
4. 项目CRUD操作（含自动编号生成）
5. 状态流转操作（含合规性校验、审批人必填校验）
6. 状态历史查询
7. 批量导入历史项目

注意事项：
- 数据库文件 pmo.db 与 app.py 放在同一目录
- 连接失败时给出清晰的错误提示
- 项目编号自动生成规则：PMO-年份-4位序号（如 PMO-2026-0001）
"""

import sqlite3
import os
import sys
from datetime import datetime
from contextlib import contextmanager
from typing import Optional

from lib.workflow import DEFAULT_STATUSES, DEFAULT_TRANSITIONS


# ============================================================
# 数据库路径管理
# ============================================================

def get_db_path() -> str:
    """
    获取数据库文件的绝对路径。

    策略：
    1. 优先使用环境变量 COZE_WORKSPACE_PATH（云端沙箱）
    2. 否则使用本文件所在目录的上级（即项目根目录，与 app.py 同级）
    3. 确保 pmo.db 始终与 app.py 在同一目录
    """
    workspace = os.environ.get("COZE_WORKSPACE_PATH")
    if workspace:
        # 云端沙箱环境
        db_dir = workspace
    else:
        # 本地运行：以 app.py 所在目录为基准
        # database.py 在 lib/ 下，所以往上一级就是项目根目录
        db_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    db_path = os.path.join(db_dir, "pmo.db")
    return db_path


def ensure_db_directory(db_path: str) -> None:
    """确保数据库文件所在目录存在，如果不存在则自动创建"""
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except OSError as e:
            print(f"[错误] 无法创建数据库目录 {db_dir}: {e}", file=sys.stderr)
            raise


@contextmanager
def get_connection():
    """
    获取数据库连接的上下文管理器。

    使用方式：
        with get_connection() as conn:
            conn.execute(...)

    错误处理：
    - 连接失败时给出清晰的中文错误提示
    - 自动 commit/rollback
    - 确保连接关闭
    """
    db_path = get_db_path()

    # 确保目录存在
    ensure_db_directory(db_path)

    # 尝试连接数据库
    try:
        conn = sqlite3.connect(db_path, timeout=10)
    except sqlite3.Error as e:
        error_msg = (
            "数据库连接失败！\n"
            "  数据库路径: " + db_path + "\n"
            "  错误信息: " + str(e) + "\n"
            "  请检查：\n"
            "    1. 目录是否存在且有写入权限\n"
            "    2. 磁盘空间是否充足\n"
            "    3. 是否有其他进程占用数据库文件"
        )
        print("[错误] " + error_msg, file=sys.stderr)
        raise RuntimeError(error_msg) from e

    conn.row_factory = sqlite3.Row
    # 开启WAL模式，提升并发性能
    conn.execute("PRAGMA journal_mode=WAL")
    # 开启外键约束
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# 数据库初始化
# ============================================================

def init_database():
    """
    初始化数据库：建表 + 写入种子数据。

    只在表为空时写入种子数据，重复调用不会覆盖。
    """
    with get_connection() as conn:
        # ---- 创建项目主表 ----
        # 字段已精简：移除 priority、planned_start_date、planned_end_date
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                project_code      TEXT UNIQUE NOT NULL,
                name              TEXT NOT NULL,
                description       TEXT,
                department        TEXT,
                sponsor           TEXT,
                project_manager   TEXT,
                current_status    TEXT NOT NULL DEFAULT 'draft',
                category          TEXT,
                budget            REAL DEFAULT 0,
                special_note      TEXT DEFAULT '',
                actual_start_date  TEXT,
                actual_end_date    TEXT,
                created_at        TEXT DEFAULT (datetime('now','localtime')),
                updated_at        TEXT DEFAULT (datetime('now','localtime')),
                status_updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # ---- 创建状态历史表 ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS status_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                from_status     TEXT,
                to_status       TEXT NOT NULL,
                action          TEXT NOT NULL,
                operator        TEXT NOT NULL,
                approver        TEXT,
                comment         TEXT,
                deliverable     TEXT,
                transition_date TEXT DEFAULT (datetime('now','localtime'))
            )
        """)

        # ---- 创建状态定义表（可自定义） ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS status_definitions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                status_code      TEXT UNIQUE NOT NULL,
                status_name      TEXT NOT NULL,
                description      TEXT,
                entry_condition  TEXT,
                exit_condition   TEXT,
                responsible_role TEXT,
                key_deliverable  TEXT,
                is_terminal      INTEGER DEFAULT 0,
                sort_order       INTEGER DEFAULT 0,
                color            TEXT DEFAULT '#6B7280',
                is_active        INTEGER DEFAULT 1
            )
        """)

        # ---- 创建流转规则表（可自定义） ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transition_rules (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                from_status          TEXT NOT NULL,
                to_status            TEXT NOT NULL,
                action_name          TEXT NOT NULL,
                requires_approval    INTEGER DEFAULT 0,
                approver_role        TEXT,
                required_deliverable TEXT,
                is_active            INTEGER DEFAULT 1
            )
        """)

        # ---- 历史版本字段补齐 ----
        _ensure_projects_schema(conn)

        # ---- 创建索引，提升查询性能 ----
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(current_status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_dept ON projects(department)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_status_updated ON projects(status_updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_project ON status_history(project_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_date ON status_history(transition_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transition_from ON transition_rules(from_status)"
        )

        # ---- 写入种子数据（仅在表为空时） ----
        _seed_statuses(conn)
        _seed_transitions(conn)


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    """检查表中是否已存在指定字段"""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r["name"] == column_name for r in rows)


def _ensure_projects_schema(conn: sqlite3.Connection) -> None:
    """为历史数据库补齐新增字段，避免升级失败"""
    if not _column_exists(conn, "projects", "special_note"):
        conn.execute("ALTER TABLE projects ADD COLUMN special_note TEXT DEFAULT ''")

    if not _column_exists(conn, "projects", "status_updated_at"):
        conn.execute("ALTER TABLE projects ADD COLUMN status_updated_at TEXT DEFAULT ''")
        conn.execute(
            """
            UPDATE projects
            SET status_updated_at = COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''), datetime('now','localtime'))
            WHERE status_updated_at IS NULL OR status_updated_at = ''
            """
        )


def _seed_statuses(conn: sqlite3.Connection):
    """写入状态定义种子数据（仅在表为空时执行）"""
    count = conn.execute("SELECT COUNT(*) FROM status_definitions").fetchone()[0]
    if count > 0:
        return
    for s in DEFAULT_STATUSES:
        conn.execute(
            """
            INSERT INTO status_definitions
                (status_code, status_name, description, entry_condition, exit_condition,
                 responsible_role, key_deliverable, is_terminal, sort_order, color, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                s["status_code"], s["status_name"], s["description"],
                s["entry_condition"], s["exit_condition"],
                s["responsible_role"], s["key_deliverable"],
                int(s["is_terminal"]), s["sort_order"], s["color"],
            ),
        )


def _seed_transitions(conn: sqlite3.Connection):
    """写入流转规则种子数据（仅在表为空时执行）"""
    count = conn.execute("SELECT COUNT(*) FROM transition_rules").fetchone()[0]
    if count > 0:
        return
    for t in DEFAULT_TRANSITIONS:
        conn.execute(
            """
            INSERT INTO transition_rules
                (from_status, to_status, action_name, requires_approval,
                 approver_role, required_deliverable, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                t["from_status"], t["to_status"], t["action_name"],
                int(t["requires_approval"]), t["approver_role"],
                t["required_deliverable"],
            ),
        )


# ============================================================
# 项目编号自动生成
# ============================================================

def generate_project_code() -> str:
    """
    自动生成项目编号，规则：PMO-年份-4位序号。

    示例：PMO-2026-0001、PMO-2026-0002

    逻辑：
    1. 查询当前年份下已有的最大编号
    2. 序号递增，确保唯一
    3. 如果编号冲突则继续递增
    """
    year = datetime.now().year
    prefix = "PMO-" + str(year) + "-"

    with get_connection() as conn:
        # 查询当前年份下最大编号
        max_code = conn.execute(
            "SELECT MAX(project_code) FROM projects WHERE project_code LIKE ?",
            (prefix + "%",),
        ).fetchone()[0]

        if max_code:
            try:
                # 提取序号部分并递增
                seq = int(max_code.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1

        # 尝试生成唯一编号（处理冲突情况）
        for _ in range(100):
            code = prefix + str(seq).zfill(4)
            exists = conn.execute(
                "SELECT 1 FROM projects WHERE project_code = ?", (code,)
            ).fetchone()
            if not exists:
                return code
            seq += 1

        # 极端情况：100次都冲突，使用时间戳后缀
        return prefix + str(int(datetime.now().timestamp()))[-6:]


# ============================================================
# 项目 CRUD
# ============================================================

def create_project(
    name: str,
    project_code: str = "",
    description: str = "",
    department: str = "",
    sponsor: str = "",
    project_manager: str = "",
    category: str = "",
    budget: float = 0,
    special_note: str = "",
    operator: str = "system",
) -> int:
    """
    创建项目，初始状态为 draft。

    参数：
        name: 项目名称（必填）
        project_code: 项目编号（可选，为空时自动生成 PMO-年份-序号）
        operator: 操作人，用于记录初始状态历史

    返回：新建项目的 ID
    """
    # 如果未提供编号，自动生成
    if not project_code or not project_code.strip():
        project_code = generate_project_code()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO projects
                (project_code, name, description, department, sponsor,
                 project_manager, category, budget, special_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_code.strip(), name, description, department, sponsor,
                project_manager, category, budget, special_note,
            ),
        )
        project_id = cursor.lastrowid

        # 记录初始状态到历史表
        conn.execute(
            """
            INSERT INTO status_history
                (project_id, from_status, to_status, action, operator, comment, deliverable)
            VALUES (?, NULL, 'draft', '创建项目', ?, '项目创建', '项目申报书')
            """,
            (project_id, operator),
        )

        return project_id


def get_projects(
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    department: Optional[str] = None,
    project_manager: Optional[str] = None,
    min_budget: Optional[float] = None,
    max_budget: Optional[float] = None,
    status_updated_from: Optional[str] = None,
    status_updated_to: Optional[str] = None,
) -> list[dict]:
    """
    查询项目列表，支持多条件筛选。

    默认按更新时间倒序排列（最近更新的排最前）。
    """
    conditions = []
    params: list = []

    if status:
        conditions.append("current_status = ?")
        params.append(status)
    if keyword:
        conditions.append(
            "(name LIKE ? OR project_code LIKE ? OR description LIKE ? "
            "OR sponsor LIKE ? OR special_note LIKE ?)"
        )
        params.extend(["%" + keyword + "%"] * 5)
    if department:
        conditions.append("department = ?")
        params.append(department)
    if project_manager:
        conditions.append("project_manager = ?")
        params.append(project_manager)
    if min_budget is not None:
        conditions.append("budget >= ?")
        params.append(min_budget)
    if max_budget is not None:
        conditions.append("budget <= ?")
        params.append(max_budget)
    if status_updated_from:
        conditions.append("status_updated_at >= ?")
        params.append(status_updated_from)
    if status_updated_to:
        conditions.append("status_updated_at <= ?")
        params.append(status_updated_to)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM projects" + where + " ORDER BY updated_at DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_project_by_id(project_id: int) -> Optional[dict]:
    """根据ID获取项目详情，不存在返回 None"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None


def update_project(project_id: int, **kwargs) -> bool:
    """
    更新项目基本信息（不含状态流转）。

    只允许更新白名单中的字段，防止注入。
    """
    # 白名单：已移除 priority、planned_start_date、planned_end_date
    allowed_fields = {
        "name", "description", "department", "sponsor", "project_manager",
        "category", "actual_start_date", "actual_end_date", "budget",
        "special_note",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return False

    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [project_id]

    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE projects SET " + set_clause + " WHERE id = ?", values
        )
        return cursor.rowcount > 0


def delete_project(project_id: int) -> bool:
    """删除项目（级联删除状态历史）"""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM projects WHERE id = ?", (project_id,)
        )
        return cursor.rowcount > 0


# ============================================================
# 状态流转
# ============================================================

def get_allowed_transitions(from_status: str) -> list[dict]:
    """
    查询从当前状态允许的所有流转规则。

    返回包含目标状态名称和颜色的完整信息，用于界面展示。
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT tr.*, sd.status_name AS to_status_name, sd.color AS to_status_color
            FROM transition_rules tr
            LEFT JOIN status_definitions sd ON tr.to_status = sd.status_code
            WHERE tr.from_status = ? AND tr.is_active = 1
            ORDER BY tr.id
            """,
            (from_status,),
        ).fetchall()
        return [dict(r) for r in rows]


def transition_project(
    project_id: int,
    to_status: str,
    operator: str,
    approver: Optional[str] = None,
    comment: str = "",
    deliverable: str = "",
    force: bool = False,
) -> dict:
    """
    执行项目状态流转。

    校验逻辑（按顺序）：
    1. 项目是否存在
    2. 流转规则是否合法（数据库中有对应规则）
    3. 需审批的流转是否已指定审批人
    4. 执行状态变更并记录历史

    参数：
        project_id: 项目ID
        to_status: 目标状态码
        operator: 操作人
        approver: 审批人（需审批流转时必填）
        comment: 变更理由（界面层强制必填）
        deliverable: 交付物

    返回: {"success": bool, "message": str}
    """
    with get_connection() as conn:
        project = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            return {"success": False, "message": "项目不存在: " + str(project_id)}

        from_status = project["current_status"]
        if from_status == to_status:
            return {"success": False, "message": "目标状态不能与当前状态相同"}

        rule = None
        action_name = ""
        approver_value = approver
        deliverable_value = deliverable
        comment_value = comment.strip()

        if force:
            status_exists = conn.execute(
                """
                SELECT 1 FROM status_definitions
                WHERE status_code = ? AND is_active = 1
                """,
                (to_status,),
            ).fetchone()
            if not status_exists:
                return {"success": False, "message": "目标状态不存在: " + to_status}

            action_name = "PMO特批强制变更"
            approver_value = approver_value or operator
            if comment_value:
                comment_value = "PMO特批: " + comment_value
            else:
                comment_value = "PMO特批"
        else:
            rule = conn.execute(
                """
                SELECT * FROM transition_rules
                WHERE from_status = ? AND to_status = ? AND is_active = 1
                """,
                (from_status, to_status),
            ).fetchone()

            if not rule:
                return {
                    "success": False,
                    "message": "不允许的流转: " + from_status + " → " + to_status + "，请检查流转规则",
                }

            if rule["requires_approval"] and not approver_value:
                return {
                    "success": False,
                    "message": (
                        "此流转需要审批，审批角色: "
                        + str(rule["approver_role"])
                        + "，请指定审批人"
                    ),
                }

            action_name = rule["action_name"]
            deliverable_value = deliverable_value or rule["required_deliverable"]

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            UPDATE projects
            SET current_status = ?, updated_at = ?, status_updated_at = ?
            WHERE id = ?
            """,
            (to_status, now, now, project_id),
        )

        conn.execute(
            """
            INSERT INTO status_history
                (project_id, from_status, to_status, action, operator, approver,
                 comment, deliverable)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, from_status, to_status, action_name,
                operator, approver_value, comment_value, deliverable_value,
            ),
        )

        if to_status == "implementing" and not project["actual_start_date"]:
            conn.execute(
                "UPDATE projects SET actual_start_date = ? WHERE id = ?",
                (now[:10], project_id),
            )
        if to_status in ("closed", "terminated") and not project["actual_end_date"]:
            conn.execute(
                "UPDATE projects SET actual_end_date = ? WHERE id = ?",
                (now[:10], project_id),
            )

        action_desc = "PMO特批" if force else action_name
        msg = "状态流转成功: " + from_status + " → " + to_status + " (" + action_desc + ")"
        return {"success": True, "message": msg}


def batch_transition_projects(
    project_ids: list[int],
    to_status: str,
    operator: str,
    approver: Optional[str] = None,
    comment: str = "",
    deliverable: str = "",
    force: bool = False,
) -> dict:
    """
    批量执行项目状态流转。

    返回:
    {
        "total": 总数,
        "success": 成功数,
        "failed": 失败数,
        "errors": [{"project_id": 1, "project_code": "...", "name": "...", "error": "..."}]
    }
    """
    unique_ids = []
    seen = set()
    for project_id in project_ids:
        if project_id not in seen:
            seen.add(project_id)
            unique_ids.append(project_id)

    result = {
        "total": len(unique_ids),
        "success": 0,
        "failed": 0,
        "errors": [],
    }

    for project_id in unique_ids:
        project = get_project_by_id(project_id)
        label = {
            "project_id": project_id,
            "project_code": project["project_code"] if project else "-",
            "name": project["name"] if project else "-",
        }

        item_result = transition_project(
            project_id=project_id,
            to_status=to_status,
            operator=operator,
            approver=approver,
            comment=comment,
            deliverable=deliverable,
            force=force,
        )
        if item_result["success"]:
            result["success"] += 1
        else:
            result["failed"] += 1
            result["errors"].append({
                **label,
                "error": item_result["message"],
            })

    return result


def get_status_history(project_id: int) -> list[dict]:
    """
    获取项目状态流转历史（按时间正序排列）。

    返回包含 from_status_name 和 to_status_name 的完整信息。
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT sh.*,
                   sd1.status_name AS from_status_name,
                   sd2.status_name AS to_status_name
            FROM status_history sh
            LEFT JOIN status_definitions sd1 ON sh.from_status = sd1.status_code
            LEFT JOIN status_definitions sd2 ON sh.to_status = sd2.status_code
            WHERE sh.project_id = ?
            ORDER BY sh.transition_date ASC
            """,
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# 状态定义 & 流转规则查询
# ============================================================

def get_all_statuses() -> list[dict]:
    """获取所有活跃状态定义（按排序号排列）"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM status_definitions WHERE is_active = 1 ORDER BY sort_order"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_transition_rules() -> list[dict]:
    """获取所有活跃流转规则"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transition_rules WHERE is_active = 1 ORDER BY from_status, id"
        ).fetchall()
        return [dict(r) for r in rows]


def get_status_stats() -> list[dict]:
    """
    获取各状态下的项目数量统计。

    用于仪表盘状态卡片展示。
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT sd.status_code, sd.status_name, sd.color, sd.is_terminal,
                   COUNT(p.id) AS project_count
            FROM status_definitions sd
            LEFT JOIN projects p ON sd.status_code = p.current_status
            WHERE sd.is_active = 1
            GROUP BY sd.status_code
            ORDER BY sd.sort_order
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_departments() -> list[str]:
    """获取所有已存在的部门列表（用于筛选下拉框）"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT department FROM projects WHERE department IS NOT NULL AND department != '' ORDER BY department"
        ).fetchall()
        return [r["department"] for r in rows]


def get_project_managers() -> list[str]:
    """获取所有已存在的项目负责人列表（用于筛选下拉框）"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT project_manager FROM projects WHERE project_manager IS NOT NULL AND project_manager != '' ORDER BY project_manager"
        ).fetchall()
        return [r["project_manager"] for r in rows]


# ============================================================
# 自定义状态和规则（扩展用）
# ============================================================

def add_status_definition(
    status_code: str,
    status_name: str,
    description: str = "",
    entry_condition: str = "",
    exit_condition: str = "",
    responsible_role: str = "",
    key_deliverable: str = "",
    is_terminal: bool = False,
    sort_order: int = 99,
    color: str = "#6B7280",
) -> bool:
    """新增自定义状态定义"""
    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO status_definitions
                    (status_code, status_name, description, entry_condition,
                     exit_condition, responsible_role, key_deliverable,
                     is_terminal, sort_order, color, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    status_code, status_name, description, entry_condition,
                    exit_condition, responsible_role, key_deliverable,
                    int(is_terminal), sort_order, color,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def add_transition_rule(
    from_status: str,
    to_status: str,
    action_name: str,
    requires_approval: bool = False,
    approver_role: str = "",
    required_deliverable: str = "",
) -> bool:
    """新增自定义流转规则"""
    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO transition_rules
                    (from_status, to_status, action_name, requires_approval,
                     approver_role, required_deliverable, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    from_status, to_status, action_name,
                    int(requires_approval), approver_role, required_deliverable,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def generate_mermaid_diagram() -> str:
    """
    生成状态流转的 Mermaid 图定义。

    终态状态标记 <<terminal>>，需审批的流转标记 [需审批]。
    """
    statuses = get_all_statuses()
    transitions = get_all_transition_rules()

    lines = ["stateDiagram-v2"]
    lines.append("    direction LR")

    # 定义每个状态节点
    for s in statuses:
        label = s["status_name"]
        if s["is_terminal"]:
            lines.append('    state "' + label + '" as ' + s["status_code"] + " <<terminal>>")
        else:
            lines.append('    state "' + label + '" as ' + s["status_code"])

    # 定义流转关系
    for t in transitions:
        action = t["action_name"]
        approval_tag = " [需审批]" if t["requires_approval"] else ""
        lines.append(
            "    " + t["from_status"] + " --> " + t["to_status"]
            + " : " + action + approval_tag
        )

    return "\n".join(lines)


# ============================================================
# 批量导入历史项目
# ============================================================

# 合法的状态码集合（用于导入时校验）
VALID_STATUS_CODES = {
    "draft", "under_review", "established", "submission_review",
    "procuring", "implementing", "trial", "accepting",
    "closed", "suspended", "terminated",
}

# 合法的状态码→中文名映射（支持导入时中文状态自动转换）
STATUS_CN_TO_EN = {
    "草稿": "draft", "评审中": "under_review", "已立项": "established",
    "送审中": "submission_review", "采购中": "procuring", "实施中": "implementing",
    "试用中": "trial", "验收中": "accepting", "已关闭": "closed",
    "已暂停": "suspended", "已终止": "terminated",
}


def batch_create_projects(
    records: list[dict],
    operator: str = "批量导入",
) -> dict:
    """
    批量创建历史项目（用于导入已有项目数据）。

    参数：
        records: 项目数据列表，每个dict包含项目字段
        operator: 操作人名称，默认"批量导入"

    返回: {
        "total": 总数,
        "success": 成功数,
        "failed": 失败数,
        "errors": [{"row": 行号, "name": 项目名, "error": 错误原因}],
    }
    """
    result = {"total": len(records), "success": 0, "failed": 0, "errors": []}

    for i, rec in enumerate(records):
        try:
            # ---- 字段处理与默认值 ----
            name = str(rec.get("name", "") or rec.get("项目名称", "")).strip()
            if not name:
                result["failed"] += 1
                result["errors"].append({
                    "row": i + 1, "name": "(无名)",
                    "error": "项目名称不能为空",
                })
                continue

            # 项目编号：为空时自动生成
            project_code = str(
                rec.get("project_code", "")
                or rec.get("项目编号", "")
            ).strip()
            if not project_code:
                project_code = generate_project_code()

            # 检查编号是否重复
            with get_connection() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM projects WHERE project_code = ?",
                    (project_code,),
                ).fetchone()
                if exists:
                    # 编号重复则自动重新生成
                    project_code = generate_project_code()

            # 状态处理：默认draft，支持中英文状态名
            status_raw = str(
                rec.get("current_status", "")
                or rec.get("状态", "")
                or rec.get("当前状态", "")
            ).strip()

            # 中文状态名转英文状态码
            if status_raw in STATUS_CN_TO_EN:
                status_raw = STATUS_CN_TO_EN[status_raw]
            else:
                status_raw = status_raw.lower()

            if not status_raw or status_raw not in VALID_STATUS_CODES:
                status_raw = "draft"

            # 数值字段
            budget = rec.get("budget", rec.get("预算", rec.get("预算(万元)", 0)))
            try:
                budget = float(budget) if budget else 0.0
            except (ValueError, TypeError):
                budget = 0.0

            # 其他文本字段（已移除 priority、planned_start_date、planned_end_date）
            description = str(rec.get("description", "") or rec.get("项目描述", "")).strip()
            department = str(rec.get("department", "") or rec.get("申报部门", "") or rec.get("部门", "")).strip()
            sponsor = str(rec.get("sponsor", "") or rec.get("发起人", "")).strip()
            project_manager = str(
                rec.get("project_manager", "")
                or rec.get("项目负责人", "")
                or rec.get("负责人", "")
            ).strip()
            category = str(rec.get("category", "") or rec.get("项目分类", "") or rec.get("分类", "")).strip()
            special_note = str(rec.get("special_note", "") or rec.get("特殊说明", "")).strip()
            actual_start = str(rec.get("actual_start_date", "") or rec.get("实际开始", "") or rec.get("实际开始日期", "")).strip()
            actual_end = str(rec.get("actual_end_date", "") or rec.get("实际结束", "") or rec.get("实际结束日期", "")).strip()

            # ---- 写入数据库 ----
            with get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO projects
                        (project_code, name, description, department, sponsor,
                         project_manager, current_status, category, special_note,
                         budget, actual_start_date, actual_end_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_code, name, description, department, sponsor,
                        project_manager, status_raw, category, special_note,
                        budget, actual_start, actual_end,
                    ),
                )
                new_id = cursor.lastrowid

                # 记录初始状态历史
                action_text = "批量导入" if status_raw == "draft" else "批量导入（历史状态: " + status_raw + "）"
                conn.execute(
                    """
                    INSERT INTO status_history
                        (project_id, from_status, to_status, action, operator, comment)
                    VALUES (?, NULL, ?, ?, ?, '历史项目批量导入')
                    """,
                    (new_id, status_raw, action_text, operator),
                )

            result["success"] += 1

        except Exception as e:
            result["failed"] += 1
            result["errors"].append({
                "row": i + 1,
                "name": name if name else "第" + str(i + 1) + "行",
                "error": str(e),
            })

    return result
