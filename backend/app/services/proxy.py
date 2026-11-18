"""采集代理路由业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "proxy"
REQUIRED_FIELDS = ["配置编号", "代理地址", "代理协议"]
STATUS_ORDER = ["草稿", "已启用", "已降级", "已关闭"]
ACTION_RULES = {"启用代理": "草稿", "降级代理": "已启用", "关闭代理": "已降级"}
NEGATIVE_ACTIONS = []


class ProxyService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "代理配置"
    keyword_field = "配置编号"
