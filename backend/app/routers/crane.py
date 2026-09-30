"""起重机械接口：维护起重机械，覆盖办理投用、安排检修、报废机械等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, ReminderRulePayload
from app.services.crane import CraneService
from app.services.crane_reminder import crane_reminder_service

router = APIRouter(prefix="/api/crane", tags=["起重机械"])

service = CraneService()

LIST_FIELDS = ["机械编号", "机械名称", "额定起重量", "跨度规格", "使用场所", "投用日期", "下次检验日", "机械状态"]
STATUSES = ["待投用", "在用运行", "停机检修", "已报废"]


@router.get("/ledger")
def crane_ledger() -> dict[str, Any]:
    """起重机械台账：按额定起重量与跨度规格分档的全量到期判定。"""
    return crane_reminder_service.ledger()


@router.get("/reminder-rule")
def get_reminder_rule() -> dict[str, Any]:
    """读取当前到期判定口径；列表、概览与台账都按这份口径出结果。"""
    return crane_reminder_service.current_rule()


@router.put("/reminder-rule")
def update_reminder_rule(payload: ReminderRulePayload) -> dict[str, Any]:
    """调整到期判定阈值：旧口径下的判定先留档，三处展示随即按新口径重算。"""
    rule, error = crane_reminder_service.update_rule([tier.model_dump() for tier in payload.tiers])
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True, "message": f"到期判定口径已更新到第 {rule['version']} 版", "rule": rule}


@router.get("/reminder-history")
def reminder_history() -> dict[str, Any]:
    """历史判定留档：每次调整口径前的判断结果，仍按当时的阈值保留。"""
    history = crane_reminder_service.history()
    return {"total": len(history), "items": history}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按机械编号检索"),
    status: str | None = Query(default=None, description="待投用、在用运行、停机检修、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按机械编号与状态过滤起重机械列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条起重机械明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"起重机械 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条起重机械，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="起重机械已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条起重机械执行办理投用、安排检修、报废机械；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出起重机械清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "crane", "total": total, "items": items}
