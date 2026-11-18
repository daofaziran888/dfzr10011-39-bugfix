"""示例数据的运行期整理：运行期表格的空表定义与状态字段对齐。

示例数据里同一行既有内部状态 ``status``，又有一列给人看的「模板状态 / 规则状态」。
两边在种子数据里各写各的（列表读一列、详情读另一列就对不上），这里在装载时统一成同源。
"""
from __future__ import annotations

from typing import Any

# 运行期表格：不属于 16 个业务模块，不参与运营概览的模块统计。
AUX_TABLES = (
    "logparse_versions",
    "logparse_callbacks",
    "logparse_actions",
    "logparse_exceptions",
    "verify_checklist",
)

# 采集结果校验规则与日志模板的绑定关系：核对清单靠它回查解析字段所属模板版本。
VERIFY_TEMPLATE_BINDINGS: dict[str, dict[str, Any]] = {
    "VERI-0001": {"template_code": "LOGP-0001", "template_id": 1},
    "VERI-0002": {"template_code": "LOGP-0002", "template_id": 2},
    "VERI-0003": {"template_code": "LOGP-0003", "template_id": 3},
}


def build_aux_rows(tables: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """每次装载示例数据时新建运行期表格，并写入每个日志模板的初始版本快照。"""
    aux: dict[str, list[dict[str, Any]]] = {name: [] for name in AUX_TABLES}
    for index, row in enumerate(tables.get("logparse", []), start=1):
        aux["logparse_versions"].append(
            {
                "id": index,
                "template_id": row.get("id"),
                "template_code": row.get("模板编号"),
                "version": row.get("version"),
                "rule": row.get("解析规则"),
                "fields": row.get("字段提取"),
                "exception": row.get("异常匹配"),
                "status": row.get("status"),
                "reason": "初始版本",
                "recorded_at": "",
            }
        )
    return aux


def normalize_seed_rows(tables: dict[str, list[dict[str, Any]]]) -> None:
    """对齐日志模板与校验规则的可见状态字段，并补齐版本/关闭时间等字段。"""
    for row in tables.get("logparse", []):
        row["status"] = row.get("status") or "草稿"
        row["模板状态"] = row["status"]
        row.setdefault("version", "v1")
        row["结构化输出版本"] = row["version"]
        # 正常模板不能在异常口径里挂着：异常只来自解析回调的失败与拒绝。
        row["abnormal"] = False
        if row["status"] == "已关闭":
            row.setdefault("closed_at", row.get("updated_at") or "")

    templates = {row.get("模板编号"): row for row in tables.get("logparse", [])}
    for row in tables.get("verify", []):
        row["status"] = row.get("status") or "草稿"
        row["规则状态"] = row["status"]
        binding = VERIFY_TEMPLATE_BINDINGS.get(str(row.get("规则编号")))
        if binding is None:
            continue
        template = templates.get(binding["template_code"])
        row["绑定模板编号"] = binding["template_code"]
        row["绑定模板ID"] = template.get("id") if template else binding["template_id"]
