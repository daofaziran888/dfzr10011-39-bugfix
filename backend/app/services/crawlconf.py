"""采集配置模板业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "crawlconf"
REQUIRED_FIELDS = ["模板编号", "模板名称", "目标类型"]
STATUS_ORDER = ["草稿", "已发布", "已停用", "已废弃"]
ACTION_RULES = {"发布模板": "草稿", "停用模板": "已发布", "废弃模板": "已停用"}
NEGATIVE_ACTIONS = ["停用模板"]


class CrawlconfService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "配置模板"
    keyword_field = "模板编号"
