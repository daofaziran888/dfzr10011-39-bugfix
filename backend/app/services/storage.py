"""采集存储分层业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "storage"
REQUIRED_FIELDS = ["策略编号", "存储层级", "文件格式"]
STATUS_ORDER = ["草稿", "已生效", "已暂停", "已关闭"]
ACTION_RULES = {"启用策略": "草稿", "暂停策略": "已生效", "关闭策略": "已暂停"}
NEGATIVE_ACTIONS = []


class StorageService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "存储策略"
    keyword_field = "策略编号"
