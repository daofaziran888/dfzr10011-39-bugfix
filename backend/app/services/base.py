"""各业务模块共用的列表、登记与动作流程。

动作判定和字段输出原先每个模块各写一遍，改一处漏一处；这里把通用流程收拢成一份，
模块只声明自己的字段与状态序列。``run_action`` 走 ``template_actions.decide_action``，
保证「启用 / 暂停 / 关闭」落到正确的下一个状态，而不是被打回原状态。
"""
from __future__ import annotations

from typing import Any

from app.services.template_actions import ActionDecision, apply_decision, decide_action
from app.store import store


class ModuleService:
    module: str = ""
    required_fields: list[str] = []
    status_order: list[str] = []
    action_rules: dict[str, str] = {}
    negative_actions: list[str] = []
    label: str = ""
    keyword_field: str = ""
    status_field: str | None = None
    entry_defaults: dict[str, Any] = {}

    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(self.module)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(self.keyword_field, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(self.module, entry_id)

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field_name
            for field_name in self.required_fields
            if not str(values.get(field_name) or "").strip()
        ]
        if missing:
            return None, missing
        rows = store.rows(self.module)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field_name: values.get(field_name) for field_name in self.required_fields})
        entry["status"] = self.status_order[0]
        entry["pending"] = True
        entry["abnormal"] = False
        for extra_key, extra_value in self.entry_defaults.items():
            entry.setdefault(extra_key, extra_value)
        if self.status_field:
            entry[self.status_field] = entry["status"]
        rows.append(entry)
        return entry, []

    # ------------------------------------------------------------------ 动作
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.module, entry_id)
        if entry is None:
            return None, f"{self.label} {entry_id} 不存在或已归档"

        before = str(entry.get("status") or "")
        decision = decide_action(
            entry,
            action,
            status_order=self.status_order,
            action_rules=self.action_rules,
            label=self.label,
            entity=self.label,
        )
        if not decision.ok:
            return None, decision.message

        if decision.changed:
            apply_decision(
                entry,
                decision,
                status_order=self.status_order,
                negative_actions=self.negative_actions,
                action=action,
            )
            if self.status_field:
                entry[self.status_field] = entry["status"]
            self._record_action(entry, action, before, decision)
        return entry, decision.message

    # 动作落库后的扩展点：日志模板用它记录版本快照、动作流水并重算校验核对清单。
    def _record_action(
        self,
        entry: dict[str, Any],
        action: str,
        before_status: str,
        decision: ActionDecision,
    ) -> None:
        return None
