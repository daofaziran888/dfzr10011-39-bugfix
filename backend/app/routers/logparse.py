"""采集日志解析接口：维护日志模板与解析回调。

固定路径（``/export``、``/exceptions``、``/callbacks``）必须声明在 ``/{entry_id}`` 之前，
否则会被参数路由抢先匹配成 422。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.logparse import EXCEPTION_LIST, LogparseService
from app.store import store

router = APIRouter(prefix="/api/logparse", tags=["采集日志解析"])

service = LogparseService()

LIST_FIELDS = ["模板编号", "日志类型", "解析规则", "字段提取", "格式化输出", "异常匹配", "应用范围", "模板状态"]
STATUSES = ["草稿", "已启用", "已暂停", "已关闭"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集日志解析清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "logparse", "total": total, "items": items}


@router.get("/exceptions")
def list_exceptions(
    template_id: int | None = Query(default=None, description="按模板 ID 过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """异常日志清单：只含解析失败与被拒绝的回调，正常日志不在此列。"""
    rows = [dict(row) for row in store.aux(EXCEPTION_LIST)]
    if template_id is not None:
        rows = [row for row in rows if row.get("template_id") == template_id]
    total = len(rows)
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("/callbacks")
def list_callbacks(template_id: int | None = None, page: int = 1, size: int = 20) -> PageResult[dict]:
    """解析回调流水：重复回调只留一条，据此确认幂等。"""
    rows = [dict(row) for row in store.aux("logparse_callbacks")]
    if template_id is not None:
        rows = [row for row in rows if row.get("template_id") == template_id]
    total = len(rows)
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按模板编号检索"),
    status: str | None = Query(default=None, description="草稿、已启用、已暂停、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按模板编号与状态过滤采集日志解析列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条日志模板，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="日志模板已登记", entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条日志模板明细；状态与版本与列表同源。"""
    entry = service.get_detail(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"日志模板 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条日志模板执行启用模板、暂停模板、关闭模板；关闭后拒绝新的解析回调。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/rule", response_model=ActionResult)
def update_rule(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改解析规则：推进模板版本，旧版本的结构化结果按原版本保留。"""
    entry, message = service.update_rule(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/callbacks", response_model=ActionResult)
def run_callback(entry_id: int, payload: EntryPayload) -> ActionResult:
    """解析回调：按当前模板版本输出结构化字段；同一 ``callback_id`` 重复提交只确认一次。"""
    record, message = service.run_parse_callback(entry_id, payload.values)
    if record is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=record)
