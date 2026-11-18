"""RPA执行记录业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "robot"
REQUIRED_FIELDS = ["记录编号", "流程模板", "执行节点"]
STATUS_ORDER = ["待执行", "执行中", "执行成功", "执行失败"]
ACTION_RULES = {"启动执行": "待执行", "重试执行": "执行中", "归档记录": "执行失败"}
NEGATIVE_ACTIONS = []


class RobotService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "执行记录"
    keyword_field = "记录编号"
