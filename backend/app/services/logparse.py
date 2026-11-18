"""采集日志解析业务规则：模板状态、解析规则与解析回调。

关键约束：

* 模板状态与解析规则必须来自同一版本：一个版本一行快照（``logparse_versions``），
  状态流转记在该版本的状态序列里；关闭后的模板不再产生新的结构化输出。
* 解析回调幂等：同一个 ``callback_id`` 重复提交只确认一次，第二次直接返回既有结果。
* 关闭模板与解析回调的冲突（两种处理都能继续，不互相阻塞）：
  - 关闭先行并拒绝回调：模板状态显示已关闭，异常日志清单出现一条「回调拒绝」记录；
  - 回调先行后再关闭：异常日志清单包含本次结果，模板关闭时间记录在回调之后。
* 解析失败保留原始字段（``raw``）并进入异常日志清单；正常解析结果不进入异常清单。
* 异常日志清单写入校验模块（``verify``）的「修复日志模板动作核对清单」，
  采集校验据此核对解析字段所属模板版本。
"""
from __future__ import annotations

import threading
from typing import Any

from app.services.base import ModuleService
from app.services.template_actions import (
    build_snapshot,
    extract_fields,
    now_text,
    template_version_of,
)
from app.services.verify import refresh_from_logparse
from app.store import store

MODULE = "logparse"
EXCEPTION_LIST = "logparse_exceptions"
CALLBACK_LOG = "logparse_callbacks"
REQUIRED_FIELDS = ["模板编号", "日志类型", "解析规则"]
STATUS_ORDER = ["草稿", "已启用", "已暂停", "已关闭"]
ACTION_RULES = {"启用模板": "草稿", "暂停模板": "已启用", "关闭模板": "已暂停"}
NEGATIVE_ACTIONS: list[str] = []

# 关闭模板与解析回调会同时提交：一把锁保护「读模板状态 → 判定 → 落库」整段，
# 谁先拿到锁谁先落库，另一方基于最新状态继续处理，不会出现两个结构化输出版本。
LOCK = threading.RLock()


class LogparseService(ModuleService):
    module = MODULE
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    label = "日志模板"
    keyword_field = "模板编号"
    status_field = "模板状态"
    entry_defaults = {"version": "v1", "结构化输出版本": "v1"}

    # ------------------------------------------------------------------ 模板
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        with LOCK:
            entry, missing = super().create_entry(values)
            if entry is not None:
                entry["version"] = str(values.get("版本号") or "v1")
                entry["结构化输出版本"] = entry["version"]
                entry["template_snapshot"] = build_snapshot(entry)
                self._append_version(entry, "登记")
            return entry, missing

    def get_detail(self, entry_id: int) -> dict[str, Any] | None:
        """详情与列表同源：状态、解析规则、版本都取自同一条记录。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None
        detail = dict(entry)
        # 列表读的是「模板状态」，详情再算一遍容易和它分叉，这里显式同源。
        detail["模板状态"] = entry.get("status")
        detail["当前版本"] = template_version_of(entry)
        detail["版本快照"] = self._versions(entry_id)
        detail["最近回调"] = [
            item for item in store.aux(CALLBACK_LOG) if item.get("template_id") == entry_id
        ][-10:]
        return detail

    @staticmethod
    def _versions(entry_id: int) -> list[dict[str, Any]]:
        return [row for row in store.aux("logparse_versions") if row.get("template_id") == entry_id]

    def _append_version(self, entry: dict[str, Any], reason: str) -> None:
        """版本快照：一个版本一行，解析规则与它经历过的状态记在同一行里。

        版本号只随解析规则变化而前进；状态流转追加进 ``statuses`` 列表，
        这样「状态」与「解析规则」永远挂在同一个版本下，回查不会串。
        """
        rows = store.aux("logparse_versions")
        current = template_version_of(entry)
        status = str(entry.get("status") or "")
        stamp = now_text()
        for row in rows:
            if row.get("template_id") == entry.get("id") and row.get("version") == current:
                history = row.setdefault("statuses", [])
                if not history:
                    history.append({"status": row.get("status") or "", "at": row.get("recorded_at") or ""})
                if history[-1].get("status") != status:
                    history.append({"status": status, "at": stamp})
                row["status"] = status
                # reason 只记录产生这个版本的原因；同版本内的状态流转不覆盖它。
                row.setdefault("reason", reason)
                return
        rows.append(
            {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "template_id": entry.get("id"),
                "template_code": entry.get("模板编号"),
                "version": current,
                "rule": entry.get("解析规则"),
                "fields": entry.get("字段提取"),
                "exception": entry.get("异常匹配"),
                "status": status,
                "statuses": [{"status": status, "at": stamp}],
                "reason": reason,
                "recorded_at": stamp,
            }
        )

    def _record_action(self, entry, action, before_status, decision) -> None:
        # 版本号标识「解析规则」这一版定义；状态与规则一起写进快照，
        # 保证两者来自同一版本，历史回调也能按版本回查。
        entry["结构化输出版本"] = template_version_of(entry)
        entry["template_snapshot"] = build_snapshot(entry)
        self._append_version(entry, action)
        stream = store.aux("logparse_actions")
        stream.append(
            {
                "id": max((int(row.get("id", 0)) for row in stream), default=0) + 1,
                "template_id": entry.get("id"),
                "template_code": entry.get("模板编号"),
                "action": action,
                "from_status": before_status,
                "to_status": entry.get("status"),
                "version": template_version_of(entry),
                "acted_at": now_text(),
            }
        )
        # 日志模板动作落库后重算校验模块的核对清单与异常日志口径。
        refresh_from_logparse()

    @staticmethod
    def _next_version(version: str) -> str:
        prefix = "v"
        if version.startswith(prefix) and version[len(prefix):].isdigit():
            return f"{prefix}{int(version[len(prefix):]) + 1}"
        return f"{version}.1"

    def update_rule(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """修改解析规则会推进版本：旧版本的回调结果仍按旧版本保留，可回查。"""
        with LOCK:
            entry = self.get_entry(entry_id)
            if entry is None:
                return None, f"日志模板 {entry_id} 不存在或已归档"
            if entry.get("status") == STATUS_ORDER[-1]:
                return None, "日志模板已关闭，不能再修改解析规则"
            rule = str(values.get("解析规则") or "").strip()
            if not rule:
                return None, "解析规则不能为空"
            if rule == entry.get("解析规则"):
                return entry, "解析规则未变化，版本保持不变"
            entry["解析规则"] = rule
            entry["version"] = self._next_version(template_version_of(entry))
            entry["结构化输出版本"] = entry["version"]
            entry["template_snapshot"] = build_snapshot(entry)
            entry["updated_at"] = now_text()
            self._append_version(entry, "修改解析规则")
            refresh_from_logparse()
            return entry, f"解析规则已更新，当前版本 {entry['version']}"

    # ------------------------------------------------------------------ 回调
    def run_parse_callback(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """解析回调：与关闭模板竞争同一把锁，结果写入异常日志清单 / 核对清单。

        幂等键 ``callback_id``：重复回调只确认一次，返回第一次的既有结果。
        """
        callback_id = str(values.get("callback_id") or values.get("callbackId") or "").strip()
        raw_log = str(values.get("raw") if values.get("raw") is not None else values.get("log") or "")

        with LOCK:
            entry = self.get_entry(entry_id)
            if entry is None:
                return None, f"日志模板 {entry_id} 不存在或已归档"

            if callback_id:
                for record in store.aux(CALLBACK_LOG):
                    if record.get("callback_id") == callback_id and record.get("template_id") == entry_id:
                        return record, f"重复回调已确认，返回既有结果（{record.get('result')}）"

            snapshot = build_snapshot(entry)
            received_at = now_text()
            status = str(entry.get("status") or "")

            # 关闭先行：模板已关闭，拒绝回调，异常清单留一条拒绝记录。
            if status == STATUS_ORDER[-1] or status not in STATUS_ORDER:
                record = self._callback_record(
                    entry,
                    callback_id,
                    raw_log,
                    snapshot,
                    result="回调拒绝",
                    accepted=False,
                    parsed=None,
                    error=f"模板已关闭，拒绝解析回调（关闭时间 {entry.get('closed_at') or '未知'}）",
                    received_at=received_at,
                )
                self._write_exception(record, raw_log, fields={}, reason="回调拒绝")
                return record, "模板已关闭，解析回调已拒绝并记入异常日志清单"

            parsed = extract_fields(snapshot["rule"], raw_log)
            if not parsed.ok:
                # 解析失败：保留原始字段，进入异常日志清单，不产生结构化输出。
                record = self._callback_record(
                    entry,
                    callback_id,
                    raw_log,
                    snapshot,
                    result="解析失败",
                    accepted=True,
                    parsed=parsed,
                    error=parsed.error,
                    received_at=received_at,
                )
                self._write_exception(record, raw_log, fields={}, reason="解析失败")
                return record, f"解析失败，已保留原始字段并记入异常日志清单：{parsed.error}"

            # 回调先行：记录本次结构化输出；随后再关闭模板时，关闭时间自然晚于本次回调。
            entry["last_callback_at"] = received_at
            record = self._callback_record(
                entry,
                callback_id,
                raw_log,
                snapshot,
                result="解析成功",
                accepted=True,
                parsed=parsed,
                error="",
                received_at=received_at,
            )
            # 结构化输出落库：核对清单随之更新，正常日志不进异常清单。
            refresh_from_logparse()
            return record, "解析回调已确认，结构化输出已生成"

    def _callback_record(
        self,
        entry: dict[str, Any],
        callback_id: str,
        raw_log: str,
        snapshot: dict[str, Any],
        *,
        result: str,
        accepted: bool,
        parsed,
        error: str,
        received_at: str,
    ) -> dict[str, Any]:
        rows = store.aux(CALLBACK_LOG)
        record = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "callback_id": callback_id or f"CB-{now_text()}-{len(rows) + 1}",
            "template_id": entry.get("id"),
            "template_code": entry.get("模板编号"),
            "template_version": snapshot["version"],
            "template_status": snapshot["status"],
            "rule": snapshot["rule"],
            "result": result,
            "accepted": accepted,
            "error": error,
            "raw": raw_log,
            "fields": dict(parsed.fields) if parsed is not None and parsed.ok else {},
            "received_at": received_at,
            "closed_at_at_callback": entry.get("closed_at"),
        }
        rows.append(record)
        return record

    def _write_exception(
        self,
        record: dict[str, Any],
        raw_log: str,
        *,
        fields: dict[str, Any],
        reason: str,
    ) -> None:
        """异常日志清单：只收解析失败与被拒绝的回调，正常日志不进清单。"""
        rows = store.aux(EXCEPTION_LIST)
        item = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": "待处理",
            "pending": True,
            "abnormal": True,
            "callback_id": record["callback_id"],
            "template_id": record["template_id"],
            "模板编号": record["template_code"],
            "模板版本": record["template_version"],
            "模板状态": record["template_status"],
            "解析规则": record["rule"],
            "异常原因": reason,
            "异常说明": record["error"],
            "原始日志": raw_log,
            # 解析失败保留原始字段：结构化字段为空，原始字段原样可回查。
            "原始字段": raw_log,
            "解析字段": fields,
            "记录时间": record["received_at"],
            "模板关闭时间": record.get("closed_at_at_callback"),
        }
        rows.append(item)
        # 异常清单变化后同步核对清单，采集校验读到的是同一批依据。
        refresh_from_logparse()

    # ------------------------------------------------------------------ 关闭
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """关闭模板也走同一把锁：与解析回调互斥，先到的落库、后到的基于最新状态处理。"""
        with LOCK:
            entry, message = super().run_action(entry_id, action)
            if entry is not None and str(action).startswith("关闭") and entry.get("status") == STATUS_ORDER[-1]:
                # 关闭时间只在首次关闭时记录；回调先行时它自然晚于本次回调。
                entry["closed_at"] = entry.get("closed_at") or now_text()
                entry["结构化输出版本"] = entry["version"]
                refresh_from_logparse()
            return entry, message
