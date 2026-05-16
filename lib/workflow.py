"""
PMO项目管理系统 - 工作流状态流转配置

核心设计原则：
1. 所有状态和流转规则存储在数据库中，支持动态自定义
2. 本文件仅定义初始种子数据（seed data），系统启动时写入数据库
3. 运行时一切以数据库为准，此处定义不再生效

项目生命周期：
  草稿 → 评审中 → 已立项 → [送审] → 采购 → 实施 → 试用 → 验收 → 关闭
  + 暂停 / 终止（随时可触发）

注意：
  - 评审驳回回到草稿，重新提交时再次走 draft → under_review 流程
  - 本轮不开发评审模块（不记录评审轮次、评审意见、评审委员等）
"""

# ============================================================
# 1. 状态定义（初始种子数据）
# 11个状态：9个主线 + 2个特殊状态（暂停/终止）
# ============================================================
DEFAULT_STATUSES = [
    {
        "status_code": "draft",
        "status_name": "草稿",
        "description": "项目负责人编制项目申报材料，尚未提交评审",
        "entry_condition": "无限制，任何授权用户均可创建",
        "exit_condition": "申报材料提交评审或撤回/终止",
        "responsible_role": "项目负责人",
        "key_deliverable": "项目申报书",
        "is_terminal": False,
        "sort_order": 1,
        "color": "#94A3B8",
    },
    {
        "status_code": "under_review",
        "status_name": "评审中",
        "description": "评审委员会对项目可行性、必要性、预算合理性进行评审",
        "entry_condition": "申报材料完整提交，进入评审流程",
        "exit_condition": "作出通过或驳回决议",
        "responsible_role": "评审委员会",
        "key_deliverable": "评审意见书、评审决议",
        "is_terminal": False,
        "sort_order": 2,
        "color": "#F59E0B",
    },
    {
        "status_code": "established",
        "status_name": "已立项",
        "description": "评审通过，正式立项，分配项目编号与预算额度",
        "entry_condition": "评审通过决议 / 送审完成",
        "exit_condition": "进入送审或采购流程",
        "responsible_role": "PMO",
        "key_deliverable": "立项批复",
        "is_terminal": False,
        "sort_order": 3,
        "color": "#10B981",
    },
    {
        "status_code": "submission_review",
        "status_name": "送审中",
        "description": "部分项目需送上级主管部门或财政部门审批（预算超阈值、特殊类别等）",
        "entry_condition": "根据项目性质判断是否需要送审",
        "exit_condition": "送审通过或驳回",
        "responsible_role": "PMO/主管部门",
        "key_deliverable": "送审材料、审批批复",
        "is_terminal": False,
        "sort_order": 4,
        "color": "#8B5CF6",
    },
    {
        "status_code": "procuring",
        "status_name": "采购中",
        "description": "根据资金安排进行采购，包括招标、谈判、单一来源等方式",
        "entry_condition": "立项/送审完成，资金安排已确认",
        "exit_condition": "采购完成，合同签订",
        "responsible_role": "项目负责人/采购部门",
        "key_deliverable": "采购文件、中标通知书、合同",
        "is_terminal": False,
        "sort_order": 5,
        "color": "#3B82F6",
    },
    {
        "status_code": "implementing",
        "status_name": "实施中",
        "description": "项目进入实施阶段，按计划推进建设/开发/部署工作",
        "entry_condition": "采购完成或无需采购直接进入实施",
        "exit_condition": "实施完成，成果具备试用条件",
        "responsible_role": "项目负责人",
        "key_deliverable": "实施过程文档、阶段成果",
        "is_terminal": False,
        "sort_order": 6,
        "color": "#06B6D4",
    },
    {
        "status_code": "trial",
        "status_name": "试用中",
        "description": "项目成果进入试用阶段，验证功能与性能是否满足需求",
        "entry_condition": "实施完成，成果具备试用条件",
        "exit_condition": "试用期满，提交验收申请",
        "responsible_role": "项目负责人/业务部门",
        "key_deliverable": "试用报告、问题清单",
        "is_terminal": False,
        "sort_order": 7,
        "color": "#0EA5E9",
    },
    {
        "status_code": "accepting",
        "status_name": "验收中",
        "description": "组织验收评审，对项目成果进行正式验收",
        "entry_condition": "试用通过，提交验收申请及材料",
        "exit_condition": "验收通过或不通过",
        "responsible_role": "验收委员会/PMO",
        "key_deliverable": "验收报告",
        "is_terminal": False,
        "sort_order": 8,
        "color": "#EC4899",
    },
    {
        "status_code": "closed",
        "status_name": "已关闭",
        "description": "项目验收通过，正式关闭归档，资源释放",
        "entry_condition": "验收通过",
        "exit_condition": "无（终态）",
        "responsible_role": "PMO",
        "key_deliverable": "归档包、结项总结",
        "is_terminal": True,
        "sort_order": 9,
        "color": "#6B7280",
    },
    # ---- 特殊状态 ----
    {
        "status_code": "suspended",
        "status_name": "已暂停",
        "description": "项目因外部原因（资金调整、政策变化等）暂时搁置，或立项后长期未执行",
        "entry_condition": "暂停审批通过",
        "exit_condition": "恢复到之前阶段或终止项目",
        "responsible_role": "PMO/项目负责人",
        "key_deliverable": "暂停说明",
        "is_terminal": False,
        "sort_order": 10,
        "color": "#92400E",
    },
    {
        "status_code": "terminated",
        "status_name": "已终止",
        "description": "需求变更/长期未执行等原因提前终止",
        "entry_condition": "终止审批通过",
        "exit_condition": "无（终态）",
        "responsible_role": "PMO/项目负责人",
        "key_deliverable": "终止报告",
        "is_terminal": True,
        "sort_order": 11,
        "color": "#7F1D1D",
    },
]

# ============================================================
# 2. 流转规则（初始种子数据）
# ============================================================
# 严格按照用户定义的规则：
#   主线流程 8条 + 后半段 4条 + 送审驳回 1条
#   暂停分支 7条 + 暂停恢复 6条
#   终止分支 8条 + 暂停→终止 1条
#   合计 34条（29条需审批 + 5条直接操作）

DEFAULT_TRANSITIONS = [
    # ==================== 主线流程（8条）====================
    # 草稿 → 评审中（需审批：PMO）
    {
        "from_status": "draft",
        "to_status": "under_review",
        "action_name": "提交评审",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "项目申报书",
        "is_active": True,
    },
    # 评审中 → 已立项（需审批：评审委员会）
    {
        "from_status": "under_review",
        "to_status": "established",
        "action_name": "评审通过",
        "requires_approval": True,
        "approver_role": "评审委员会",
        "required_deliverable": "评审通过决议",
        "is_active": True,
    },
    # 评审中 → 草稿（驳回，需审批）
    {
        "from_status": "under_review",
        "to_status": "draft",
        "action_name": "评审驳回",
        "requires_approval": True,
        "approver_role": "评审委员会",
        "required_deliverable": "评审意见",
        "is_active": True,
    },
    # 已立项 → 送审中（直接，部分项目需要）
    {
        "from_status": "established",
        "to_status": "submission_review",
        "action_name": "提交送审",
        "requires_approval": False,
        "approver_role": None,
        "required_deliverable": "送审材料",
        "is_active": True,
    },
    # 已立项 → 采购中（直接，无需送审的项目）
    {
        "from_status": "established",
        "to_status": "procuring",
        "action_name": "直接进入采购",
        "requires_approval": False,
        "approver_role": None,
        "required_deliverable": "资金安排确认",
        "is_active": True,
    },
    # 送审中 → 采购中（需审批：PMO/主管部门）
    {
        "from_status": "submission_review",
        "to_status": "procuring",
        "action_name": "送审通过",
        "requires_approval": True,
        "approver_role": "PMO/主管部门",
        "required_deliverable": "审批批复",
        "is_active": True,
    },
    # 采购中 → 实施中（直接）
    {
        "from_status": "procuring",
        "to_status": "implementing",
        "action_name": "采购完成，进入实施",
        "requires_approval": False,
        "approver_role": None,
        "required_deliverable": "合同/采购确认书",
        "is_active": True,
    },
    # 实施中 → 试用中（直接）
    {
        "from_status": "implementing",
        "to_status": "trial",
        "action_name": "实施完成，进入试用",
        "requires_approval": False,
        "approver_role": None,
        "required_deliverable": "实施完成报告",
        "is_active": True,
    },

    # ==================== 后半段流程（4条）====================
    # 试用中 → 验收中（直接）
    {
        "from_status": "trial",
        "to_status": "accepting",
        "action_name": "申请验收",
        "requires_approval": False,
        "approver_role": None,
        "required_deliverable": "试用报告、验收申请",
        "is_active": True,
    },
    # 验收中 → 已关闭（需审批：验收委员会/PMO）
    {
        "from_status": "accepting",
        "to_status": "closed",
        "action_name": "验收通过",
        "requires_approval": True,
        "approver_role": "验收委员会/PMO",
        "required_deliverable": "验收报告",
        "is_active": True,
    },
    # 验收中 → 试用中（不通过，需审批）
    {
        "from_status": "accepting",
        "to_status": "trial",
        "action_name": "验收不通过，返回试用",
        "requires_approval": True,
        "approver_role": "验收委员会/PMO",
        "required_deliverable": "整改意见",
        "is_active": True,
    },
    # 送审驳回 → 已立项（需审批，送审未通过退回）
    {
        "from_status": "submission_review",
        "to_status": "established",
        "action_name": "送审驳回",
        "requires_approval": True,
        "approver_role": "PMO/主管部门",
        "required_deliverable": "驳回意见",
        "is_active": True,
    },

    # ==================== 暂停分支（7条，均需审批）====================
    {
        "from_status": "under_review",
        "to_status": "suspended",
        "action_name": "暂停项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "暂停申请",
        "is_active": True,
    },
    {
        "from_status": "established",
        "to_status": "suspended",
        "action_name": "暂停项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "暂停说明",
        "is_active": True,
    },
    {
        "from_status": "submission_review",
        "to_status": "suspended",
        "action_name": "暂停项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "暂停申请",
        "is_active": True,
    },
    {
        "from_status": "procuring",
        "to_status": "suspended",
        "action_name": "暂停项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "暂停申请",
        "is_active": True,
    },
    {
        "from_status": "implementing",
        "to_status": "suspended",
        "action_name": "暂停项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "暂停申请",
        "is_active": True,
    },
    {
        "from_status": "trial",
        "to_status": "suspended",
        "action_name": "暂停项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "暂停申请",
        "is_active": True,
    },
    {
        "from_status": "accepting",
        "to_status": "suspended",
        "action_name": "暂停项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "暂停申请",
        "is_active": True,
    },

    # ==================== 暂停恢复（6条，均需审批）====================
    {
        "from_status": "suspended",
        "to_status": "under_review",
        "action_name": "恢复项目（回到评审中）",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "恢复确认",
        "is_active": True,
    },
    {
        "from_status": "suspended",
        "to_status": "established",
        "action_name": "恢复项目（回到已立项）",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "恢复确认",
        "is_active": True,
    },
    {
        "from_status": "suspended",
        "to_status": "submission_review",
        "action_name": "恢复项目（回到送审中）",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "恢复确认",
        "is_active": True,
    },
    {
        "from_status": "suspended",
        "to_status": "procuring",
        "action_name": "恢复项目（回到采购中）",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "恢复确认",
        "is_active": True,
    },
    {
        "from_status": "suspended",
        "to_status": "implementing",
        "action_name": "恢复项目（回到实施中）",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "恢复确认",
        "is_active": True,
    },
    {
        "from_status": "suspended",
        "to_status": "trial",
        "action_name": "恢复项目（回到试用中）",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "恢复确认",
        "is_active": True,
    },

    # ==================== 终止分支（8+1条，均需审批）====================
    # 草稿 → 终止
    {
        "from_status": "draft",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止申请",
        "is_active": True,
    },
    # 评审中 → 终止
    {
        "from_status": "under_review",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止申请",
        "is_active": True,
    },
    # 已立项 → 终止
    {
        "from_status": "established",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止报告",
        "is_active": True,
    },
    # 送审中 → 终止
    {
        "from_status": "submission_review",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止申请",
        "is_active": True,
    },
    # 采购中 → 终止
    {
        "from_status": "procuring",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止申请",
        "is_active": True,
    },
    # 实施中 → 终止
    {
        "from_status": "implementing",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止报告",
        "is_active": True,
    },
    # 试用中 → 终止
    {
        "from_status": "trial",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止报告",
        "is_active": True,
    },
    # 验收中 → 终止
    {
        "from_status": "accepting",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止报告",
        "is_active": True,
    },
    # 已暂停 → 已终止
    {
        "from_status": "suspended",
        "to_status": "terminated",
        "action_name": "终止项目",
        "requires_approval": True,
        "approver_role": "PMO",
        "required_deliverable": "终止报告",
        "is_active": True,
    },
]
