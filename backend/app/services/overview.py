"""运营概览汇总：通用模块走 store 统计，起重机械待处理量改用到期提醒的同一份判定。"""
from __future__ import annotations

from app.services.crane_reminder import MODULE as CRANE_MODULE
from app.services.crane_reminder import crane_reminder_service
from app.store import store


def build_overview() -> dict[str, object]:
    """组装运营概览；起重机械的待处理量与列表标记、台账共用一次判定结果。"""
    data = store.overview()
    modules = data["modules"]
    for module in modules:
        if module["name"] == CRANE_MODULE:
            module["pending"] = crane_reminder_service.pending_count()
    for card in data["cards"]:
        if card["label"] == "待处理":
            card["value"] = sum(int(item["pending"]) for item in modules)
    return data
