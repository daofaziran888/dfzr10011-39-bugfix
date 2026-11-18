"""断点续采恢复业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "resume"
REQUIRED_FIELDS = ["断点编号", "采集计划", "断点位置"]
STATUS_ORDER = ["已记录", "恢复中", "已恢复", "已放弃"]
ACTION_RULES = {"启动恢复": "已记录", "放弃恢复": "恢复中", "归档记录": "已恢复"}
NEGATIVE_ACTIONS = []


class ResumeService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "断点记录"
    keyword_field = "断点编号"
