"""采集频率控制业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "ratelimit"
REQUIRED_FIELDS = ["规则编号", "目标站点", "请求间隔"]
STATUS_ORDER = ["草稿", "已生效", "已暂停", "已关闭"]
ACTION_RULES = {"启用规则": "草稿", "暂停规则": "已生效", "关闭规则": "已暂停"}
NEGATIVE_ACTIONS = []


class RatelimitService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "频率规则"
    keyword_field = "规则编号"
