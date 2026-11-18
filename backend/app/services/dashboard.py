"""全局采集看板业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "dashboard"
REQUIRED_FIELDS = ["面板编号", "面板名称", "显示指标"]
STATUS_ORDER = ["草稿", "已启用", "已暂停", "已归档"]
ACTION_RULES = {"启用面板": "草稿", "暂停面板": "已启用", "归档面板": "已暂停"}
NEGATIVE_ACTIONS = []


class DashboardService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "看板面板"
    keyword_field = "面板编号"
