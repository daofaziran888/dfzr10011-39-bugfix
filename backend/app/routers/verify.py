"""采集结果校验接口：校验规则 + 修复日志模板动作核对清单。

``/exception-logs`` / ``/checklist`` / ``/repair-queue`` 是固定路径，必须声明在
``/{entry_id}`` 之前，否则会被参数路由当成 entry_id 解析成 422。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.verify import VerifyService

router = APIRouter(prefix="/api/verify", tags=["采集结果校验"])

service = VerifyService()

LIST_FIELDS = ["规则编号", "采集计划", "校验类型", "校验字段", "阈值配置", "不通过动作", "最近校验", "规则状态"]
STATUSES = ["草稿", "已启用", "已暂停", "已关闭"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集结果校验清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "verify", "total": total, "items": items}


@router.get("/exception-logs", response_model=PageResult[dict])
def list_exception_logs(
    rule_id: int | None = Query(default=None, description="按校验规则过滤，取其绑定的模板"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """读取异常日志清单：解析字段所属模板版本逐条可见，供校验核对。"""
    rows = [dict(row) for row in service.exception_list(entry_id=rule_id)]
    total = len(rows)
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("/checklist", response_model=PageResult[dict])
def list_checklist(
    rule_id: int | None = Query(default=None, description="按校验规则过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """修复日志模板动作核对清单：动作队列 + 异常依据，逐条核对模板版本。"""
    rows = service.checklist(entry_id=rule_id)
    total = len(rows)
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("/repair-queue", response_model=PageResult[dict])
def list_repair_queue(page: int = 1, size: int = 20) -> PageResult[dict]:
    """修复日志模板动作队列：待处理的模板动作与回调异常。"""
    rows = service.repair_queue()
    total = len(rows)
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.post("/refresh", response_model=ActionResult)
def refresh_checklist() -> ActionResult:
    """重算核对清单与异常日志口径：别的业务入口改动日志模板后走这里。"""
    rows = service.refresh_checklist()
    return ActionResult(ok=True, message=f"核对清单已重算，共 {len(rows)} 条依据", entry=None)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、已启用、已暂停、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号与状态过滤采集结果校验列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条校验规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="校验规则已登记", entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条校验规则明细；附核对清单、异常日志清单与结构化结果批次。"""
    entry = service.get_detail(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"校验规则 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条校验规则执行启用校验、暂停校验、关闭校验；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
