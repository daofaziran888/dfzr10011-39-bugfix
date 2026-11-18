"""采集结果校验业务规则：校验规则状态流转 + 修复日志模板动作核对清单。

核对清单（``verify_checklist``）由本模块维护，数据来源是采集日志解析写入的运行期表格：

* 日志模板动作流水（``logparse_actions``）：每次启用 / 暂停 / 关闭都记一条；
* 解析回调流水（``logparse_callbacks``）：每次结构化输出、解析失败或回调拒绝；
* 异常日志清单（``logparse_exceptions``）：解析失败与被拒绝的回调。

采集校验读取异常日志清单，逐条核对「解析字段所属模板版本」与当前模板版本是否一致，
把结果落到核对清单里，供校验清单一页核对。模板关闭后不再产生新的结构化输出，
VERI 只能看到关闭前那一批完整结果。

别的业务入口（日志模板动作、解析回调）落库后调用 ``refresh_checklist`` 重算
「修复日志模板动作队列」和「异常日志清单」，保证两边口径随时一致。
"""
from __future__ import annotations

from typing import Any

from app.services.base import ModuleService
from app.services.template_actions import now_text
from app.store import store

MODULE = "verify"
CHECKLIST = "verify_checklist"
REQUIRED_FIELDS = ["规则编号", "采集计划", "校验类型"]
STATUS_ORDER = ["草稿", "已启用", "已暂停", "已关闭"]
ACTION_RULES = {"启用校验": "草稿", "暂停校验": "已启用", "关闭校验": "已暂停"}
NEGATIVE_ACTIONS: list[str] = []


class VerifyService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "校验规则"
    keyword_field = "规则编号"
    status_field = "规则状态"

    def get_detail(self, entry_id: int) -> dict[str, Any] | None:
        """详情与列表同源，并附上绑定的日志模板与本次可核对的结构化结果。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None
        detail = dict(entry)
        detail["核对清单"] = self.checklist(entry_id=entry_id)
        detail["异常日志清单"] = self.exception_list(entry_id=entry_id)
        detail["结构化结果批次"] = self.result_batches(entry_id=entry_id)
        return detail

    # ------------------------------------------------------------------ 核对清单
    def checklist(self, entry_id: int | None = None) -> list[dict[str, Any]]:
        # 读之前先重算：不管动作从哪个业务入口进来，清单都与最新模板动作、
        # 异常日志清单保持一致，不会读到上一次的残影。
        self.refresh_checklist()
        rows = store.aux(CHECKLIST)
        if entry_id is not None:
            rule = store.find(MODULE, entry_id)
            if rule is None:
                return []
            template_id = rule.get("绑定模板ID")
            rows = [row for row in rows if row.get("template_id") == template_id]
        return list(rows)

    def exception_list(self, entry_id: int | None = None) -> list[dict[str, Any]]:
        """读取异常日志清单；按校验规则绑定的模板过滤。

        异常清单由日志模板服务写入，这里只读；写入口径在 ``logparse._write_exception``，
        正常解析结果不会进来。视图里再补一层结果校验，避免历史脏数据里混入正常日志。
        """
        rows = [
            dict(row)
            for row in store.aux("logparse_exceptions")
            if row.get("异常原因") in ("解析失败", "回调拒绝")
        ]
        if entry_id is not None:
            rule = store.find(MODULE, entry_id)
            if rule is None:
                return []
            rows = [row for row in rows if row.get("template_id") == rule.get("绑定模板ID")]
        return rows

    def result_batches(self, entry_id: int) -> list[dict[str, Any]]:
        """按模板版本聚合结构化输出，关闭后的模板只回放最后一批完整结果。"""
        rule = store.find(MODULE, entry_id)
        if rule is None:
            return []
        template_id = rule.get("绑定模板ID")
        template = store.find("logparse", int(template_id)) if template_id is not None else None
        callbacks = [
            row
            for row in store.aux("logparse_callbacks")
            if row.get("template_id") == template_id and row.get("result") == "解析成功"
        ]
        batches: dict[str, dict[str, Any]] = {}
        for row in callbacks:
            version = str(row.get("template_version"))
            batch = batches.setdefault(
                version,
                {
                    "template_version": version,
                    "template_code": row.get("template_code"),
                    "items": [],
                    "closed": bool(template and template.get("status") == STATUS_ORDER[-1]),
                },
            )
            batch["items"].append(
                {
                    "callback_id": row.get("callback_id"),
                    "fields": row.get("fields"),
                    "received_at": row.get("received_at"),
                }
            )
        ordered = sorted(batches.values(), key=lambda item: item["items"][-1]["received_at"])
        if template and template.get("status") == STATUS_ORDER[-1]:
            # 关闭后不再产生新输出：只保留最后一批完整结果。
            return ordered[-1:]
        return ordered

    def refresh_checklist(self) -> list[dict[str, Any]]:
        """重算修复日志模板动作核对清单：动作队列 + 异常日志清单逐条核对版本。

        由日志模板动作与解析回调在落库后调用；其它业务入口改动日志模板时同样走这里，
        清单因此始终反映最新一批模板动作与异常依据。
        """
        templates = {row.get("id"): row for row in store.rows("logparse")}
        actions = store.aux("logparse_actions")
        callbacks = store.aux("logparse_callbacks")
        exceptions = store.aux("logparse_exceptions")
        rows = store.aux(CHECKLIST)

        existing = {(row.get("kind"), row.get("source_id")): row for row in rows}
        next_id = max((int(row.get("id", 0)) for row in rows), default=0)

        def upsert(kind: str, source_id: int, payload: dict[str, Any]) -> None:
            nonlocal next_id
            key = (kind, source_id)
            row = existing.get(key)
            if row is None:
                next_id += 1
                row = {"id": next_id, "kind": kind, "source_id": source_id}
                rows.append(row)
                existing[key] = row
            row.update(payload)
            row["refreshed_at"] = now_text()

        for action in actions:
            template = templates.get(action.get("template_id"), {})
            version = str(action.get("version") or "")
            current = str(template.get("version") or "")
            # 关闭动作需要核对关闭后的结构化输出版本；其余动作落库即视为已核对。
            needs_review = action.get("action") == "关闭模板"
            upsert(
                "模板动作",
                int(action.get("id", 0)),
                {
                    "status": "待处理" if needs_review else "已核对",
                    "pending": needs_review,
                    "abnormal": False,
                    "template_id": action.get("template_id"),
                    "模板编号": action.get("template_code"),
                    "模板版本": version,
                    "当前模板版本": current,
                    "版本一致": bool(version) and version == current,
                    "动作": action.get("action"),
                    "动作来源状态": action.get("from_status"),
                    "动作目标状态": action.get("to_status"),
                    "记录时间": action.get("acted_at"),
                    "依据": f"模板动作#{action.get('id')}",
                },
            )

        for callback in callbacks:
            # 解析成功的回调只登记结构化输出，供校验核对字段与版本；
            # 解析失败 / 回调拒绝已由异常日志清单逐条写入，这里不重复登记。
            if callback.get("result") != "解析成功":
                continue
            template = templates.get(callback.get("template_id"), {})
            current_version = str(template.get("version") or "")
            callback_version = str(callback.get("template_version") or "")
            upsert(
                "结构化输出",
                int(callback.get("id", 0)),
                {
                    "status": "已核对",
                    "pending": False,
                    "abnormal": False,
                    "template_id": callback.get("template_id"),
                    "模板编号": callback.get("template_code"),
                    "模板版本": callback_version,
                    "当前模板版本": current_version,
                    # 解析字段所属版本与当前版本是否一致，供校验核对
                    "版本一致": bool(callback_version) and callback_version == current_version,
                    "回调结果": callback.get("result"),
                    "异常原因": "",
                    "解析字段": callback.get("fields") or {},
                    "原始字段": callback.get("raw"),
                    "记录时间": callback.get("received_at"),
                    "依据": f"解析回调#{callback.get('id')}",
                },
            )

        for exception in exceptions:
            upsert(
                "异常日志",
                int(exception.get("id", 0)),
                {
                    "status": "待处理",
                    "pending": True,
                    "abnormal": True,
                    "template_id": exception.get("template_id"),
                    "模板编号": exception.get("模板编号"),
                    "模板版本": exception.get("模板版本"),
                    "当前模板版本": str(
                        templates.get(exception.get("template_id"), {}).get("version") or ""
                    ),
                    "版本一致": str(exception.get("模板版本"))
                    == str(templates.get(exception.get("template_id"), {}).get("version") or ""),
                    "异常原因": exception.get("异常原因"),
                    "解析字段": exception.get("解析字段") or {},
                    "原始字段": exception.get("原始字段"),
                    "记录时间": exception.get("记录时间"),
                    "依据": f"异常日志#{exception.get('id')}",
                },
            )
        return list(rows)

    def repair_queue(self) -> list[dict[str, Any]]:
        """修复日志模板动作队列：关闭带来的版本核对 + 异常日志清单，按记录时间排序。"""
        rows = [
            row
            for row in self.checklist()
            if row.get("pending") and row.get("kind") in ("模板动作", "异常日志")
        ]
        return sorted(rows, key=lambda item: str(item.get("记录时间") or ""))


def refresh_from_logparse() -> list[dict[str, Any]]:
    """给日志模板动作 / 解析回调用的重算入口，避免调用方重复构造服务。"""
    return VerifyService().refresh_checklist()
