"""采集节点集群业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import ModuleService

MODULE = "cluster"
REQUIRED_FIELDS = ["节点编号", "节点地址", "节点角色"]
STATUS_ORDER = ["待加入", "运行中", "已离线", "已移除"]
ACTION_RULES = {"加入集群": "待加入", "下线节点": "运行中", "移除节点": "已离线"}
NEGATIVE_ACTIONS = ["下线节点"]


class ClusterService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "集群节点"
    keyword_field = "节点编号"
