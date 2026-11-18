"""模板动作判定与字段输出的共用实现。

采集日志解析和采集结果校验原先各写了一遍「动作 → 目标状态」的判定和「解析规则 → 结构化字段」
的提取，两边口径不一致：动作对应的状态被打回了上一个状态（启用模板反而落回草稿），
字段输出也各挑各的。这里把两件事收拢成一份实现：

* ``decide_action``：动作合法性、目标状态与时间戳，只此一份。
* ``apply_decision``：把判定结果写回记录，pending/abnormal 口径统一。
* ``extract_fields``：按当前模板的解析规则输出结构化字段；解析失败保留原始字段。
* ``build_snapshot``：模板版本快照，保证状态与解析规则来自同一次读取。

各模块的 ``run_action`` 只把本模块的配置传进来，不再自己判断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# STATUS_ORDER 与 ACTION_RULES 的对应关系：ACTION_RULES 里写的是动作对应的「源状态」，
# 动作成功后落到状态序列里的下一个状态，例如日志模板：
#   草稿 --启用模板--> 已启用 --暂停模板--> 已暂停 --关闭模板--> 已关闭
# 修复前各模块直接 entry["status"] = ACTION_RULES[action]，等于把状态打回源状态
# （启用模板反而落回草稿），判定和字段输出还各写了一遍，这里收拢成同一份实现。


def now_text() -> str:
    """统一的状态时间戳口径：精确到微秒，保证关闭与回调的先后可以稳定比较。"""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")


@dataclass
class ActionDecision:
    """动作判定的结果：调用方只管把要写的字段落回记录。"""

    ok: bool
    message: str
    target: str | None = None
    changed: bool = False
    timestamps: dict[str, str] = field(default_factory=dict)


def decide_action(
    entry: dict[str, Any],
    action: str,
    *,
    status_order: list[str],
    action_rules: dict[str, str],
    label: str = "",
    entity: str = "",
) -> ActionDecision:
    """统一的动作判定：动作是否可执行、落到哪个状态、要不要记时间戳。

    只做判定、不改 ``entry``。关闭模板与解析回调可以在同一把锁里先判定再落库，
    避免两边都基于旧状态各写各的。

    * 动作必须在本模块的动作表里；
    * 目标状态 = 前置状态在状态序列中的下一项，已在末位时保持末位；
    * 重复提交同一动作是幂等的，不覆盖已有时间戳；
    * 记录已到末位（关闭/移除/归档）后不再接受其它动作。
    """
    entity = entity or label or "记录"
    action = str(action or "").strip()
    if action not in action_rules:
        return ActionDecision(
            ok=False,
            message=f"动作「{action}」不属于{label or entity}可执行范围",
        )

    source = action_rules[action]
    if source not in status_order:
        return ActionDecision(
            ok=False,
            message=f"目标状态「{source}」不在允许的状态序列里",
        )

    # 动作表里写的是动作的源状态，成功后的目标状态是序列里的下一项。
    target = status_order[min(status_order.index(source) + 1, len(status_order) - 1)]
    current = str(entry.get("status") or status_order[0])
    if current not in status_order:
        return ActionDecision(
            ok=False,
            message=f"当前状态「{current}」不在允许的状态序列里",
        )

    # 重复提交同一动作：幂等，只回报既有结果，不重复推进也不覆盖时间戳。
    if current == target:
        return ActionDecision(
            ok=True,
            message=f"{entity}已{action}，返回既有结果",
            target=target,
            changed=False,
        )

    if current == status_order[-1]:
        return ActionDecision(
            ok=False,
            message=f"{entity}已到终态「{current}」，不能执行「{action}」",
        )

    # 只允许向前推进：已经走过的状态不能倒回去（例如已暂停的不能再次「启用」）。
    if status_order.index(current) > status_order.index(target):
        return ActionDecision(
            ok=False,
            message=f"当前状态「{current}」已经越过「{target}」，不能执行「{action}」",
        )

    verb = next((item for item in ("关闭", "暂停", "启用") if action.startswith(item)), "")
    timestamps: dict[str, str] = {}
    if verb == "关闭":
        timestamps["closed_at"] = now_text()
    elif verb == "暂停":
        timestamps["paused_at"] = now_text()
    elif verb == "启用":
        timestamps["enabled_at"] = now_text()

    return ActionDecision(
        ok=True,
        message=f"{entity}已{action}",
        target=target,
        changed=True,
        timestamps=timestamps,
    )


def apply_decision(
    entry: dict[str, Any],
    decision: ActionDecision,
    *,
    status_order: list[str],
    negative_actions: list[str] | tuple[str, ...] = (),
    action: str = "",
) -> None:
    """把动作判定结果写回记录，保持 pending/abnormal 的既有口径。"""
    entry["status"] = decision.target
    entry["pending"] = decision.target != status_order[-1]
    entry["abnormal"] = action in negative_actions
    for key, value in decision.timestamps.items():
        entry[key] = value
    entry["updated_at"] = now_text()


# ---------------------------------------------------------------------------
# 字段输出：解析规则 → 结构化字段
# ---------------------------------------------------------------------------

FIELD_PATTERN = re.compile(r"%(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<type>[a-z]+))?%")
# 解析规则里没有占位符时，按「键=值」逐段拆，拆不出来就视为解析失败。
PAIR_SEPARATOR = re.compile(r"[\s,;|]+")


@dataclass
class ParseResult:
    """一次解析回调的产出，正常与异常共用一份结构。

    解析失败时 ``fields`` 为空、``raw`` 保留原始日志，调用方据此把记录写进异常日志清单。
    """

    ok: bool
    fields: dict[str, str] = field(default_factory=dict)
    raw: str = ""
    error: str = ""


def extract_fields(rule: str, raw_log: str) -> ParseResult:
    """按模板的解析规则从原始日志里提字段。

    * 规则里有 ``%name%`` 占位符：按占位符与字面量依次切分，字面量对不上就算解析失败。
    * 规则里没有占位符：按 ``键=值`` 拆分，至少要能拆出一组。
    * 解析失败保留原始字段（``raw``），不产生结构化输出。
    """
    rule = str(rule or "")
    raw = str(raw_log or "")
    if not raw.strip():
        return ParseResult(ok=False, raw=raw, error="原始日志为空")

    names = [match.group("name") for match in FIELD_PATTERN.finditer(rule)]
    if names:
        matches = list(FIELD_PATTERN.finditer(rule))
        fields: dict[str, str] = {}
        cursor = 0
        # 规则第一段字段前的字面量也要在原始日志里定位。
        prefix = rule[:matches[0].start()]
        if prefix:
            position = raw.find(prefix, cursor)
            if position < 0:
                return ParseResult(ok=False, raw=raw, error=f"解析规则字面量「{prefix}」未匹配")
            cursor = position + len(prefix)
        for index, match in enumerate(matches):
            following = matches[index + 1].start() if index + 1 < len(matches) else len(rule)
            trailing = rule[match.end():following]
            if trailing:
                position = raw.find(trailing, cursor)
                if position < 0:
                    return ParseResult(ok=False, raw=raw, error=f"解析规则字面量「{trailing}」未匹配")
                fields[match.group("name")] = raw[cursor:position].strip()
                cursor = position + len(trailing)
            else:
                fields[match.group("name")] = raw[cursor:].strip()
                cursor = len(raw)
        return ParseResult(ok=True, fields=fields, raw=raw)

    fields = {}
    for chunk in PAIR_SEPARATOR.split(raw.strip()):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        if key.strip():
            fields[key.strip()] = value.strip()
    if not fields:
        return ParseResult(ok=False, raw=raw, error="解析规则与原始日志格式不匹配")
    return ParseResult(ok=True, fields=fields, raw=raw)


def build_snapshot(template: dict[str, Any]) -> dict[str, Any]:
    """模板版本快照：状态与解析规则必须取自同一次读取。"""
    return {
        "template_id": template.get("id"),
        "template_code": template.get("模板编号"),
        "version": template_version_of(template),
        "status": template.get("status"),
        "rule": template.get("解析规则"),
        "fields": template.get("字段提取"),
        "exception": template.get("异常匹配"),
    }


def template_version_of(template: dict[str, Any]) -> str:
    return str(template.get("version") or template.get("版本号") or "v1")
