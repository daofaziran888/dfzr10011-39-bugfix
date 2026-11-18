"""采集数据源池业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "datasource"
REQUIRED_FIELDS = ["条目编号", "数据源名称", "源类型"]
STATUS_ORDER = ["草稿", "已接入", "已暂停", "已移除"]
ACTION_RULES = {"接入源": "草稿", "暂停源": "已接入", "移除源": "已暂停"}
NEGATIVE_ACTIONS = []


class DatasourceService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "数据源条目"
    keyword_field = "条目编号"
