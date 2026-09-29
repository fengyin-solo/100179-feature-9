"""起重机械业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.config import settings
from app.store import store

MODULE = "crane"
REQUIRED_FIELDS = ["机械编号", "机械名称", "额定起重量"]
STATUS_ORDER = ["待投用", "在用运行", "停机检修", "已报废"]
ACTION_RULES = {"办理投用": "在用运行", "安排检修": "停机检修", "报废机械": "已报废"}
NEGATIVE_ACTIONS = []

# 到期提醒判定类别：缺失 = 没有下次检验日；超期 = 检验日已过；临近 = 距检验日不超过阈值
REMIND_MISSING = "缺失"
REMIND_OVERDUE = "超期"
REMIND_UPCOMING = "临近"
REMIND_NORMAL = "正常"
REMIND_PENDING_VERDICTS = (REMIND_UPCOMING, REMIND_OVERDUE)
REMIND_CONFIG_KEY = "crane.remind_threshold_days"
REMIND_THRESHOLD_MAX = 365


def _parse_inspection_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


class CraneReminderService:
    """起重机械到期提醒：按额定起重量与跨度规格口径评估下次检验日。

    评估结果固化成一份快照，列表标记、运营概览待处理量与台账统计都读这同一份，
    刷新不会各算各的；每次重算把当时阈值下的判断追加到历史，历史不回改。
    评估只读起重机械台账，判定结果写在快照里，不回改台账记录。
    """

    def threshold(self) -> int:
        return int(store.get_config(REMIND_CONFIG_KEY, settings.crane_remind_threshold_days))

    def update_threshold(self, value: Any) -> tuple[int | None, str]:
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            return None, f"提醒阈值「{value}」不是有效数字"
        if not number.is_integer():
            return None, f"提醒阈值「{value}」需为整数天数"
        days = int(number)
        if days < 0 or days > REMIND_THRESHOLD_MAX:
            return None, f"提醒阈值需在 0~{REMIND_THRESHOLD_MAX} 天之间"
        store.set_config(REMIND_CONFIG_KEY, days)
        self.recalculate()
        return days, f"提醒阈值已调整为 {days} 天，列表标记、运营概览与台账已按新口径重算"

    def recalculate(self) -> dict[str, Any]:
        today = date.today()
        threshold = self.threshold()
        items = [self._judge(row, today, threshold) for row in store.rows(MODULE)]
        summary = self._summarize(items)
        snapshot = {
            "module": MODULE,
            "threshold_days": threshold,
            "evaluated_on": today.isoformat(),
            "evaluated_at": datetime.now().isoformat(timespec="seconds"),
            "items": items,
            "summary": summary,
            "groups": self._group_by_spec(items),
        }
        store.set_snapshot(MODULE, snapshot)
        store.append_history(MODULE, {
            "evaluated_at": snapshot["evaluated_at"],
            "evaluated_on": snapshot["evaluated_on"],
            "threshold_days": threshold,
            "summary": summary,
        })
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        snapshot = store.get_snapshot(MODULE)
        if snapshot is None or snapshot.get("evaluated_on") != date.today().isoformat():
            snapshot = self.recalculate()
        return snapshot

    def pending_count(self) -> int:
        return int(self.snapshot()["summary"]["待处理"])

    def history(self) -> list[dict[str, Any]]:
        return store.history(MODULE)

    def apply_to_overview(self, data: dict[str, Any]) -> dict[str, Any]:
        """运营概览里起重机械的待处理量按到期提醒快照计，与其余模块并列汇总。"""
        pending = self.pending_count()
        modules = data.get("modules", [])
        for module in modules:
            if isinstance(module, dict) and module.get("name") == MODULE:
                module["pending"] = pending
        for card in data.get("cards", []):
            if isinstance(card, dict) and card.get("label") == "待处理":
                card["value"] = sum(
                    int(module.get("pending", 0)) for module in modules if isinstance(module, dict)
                )
        return data

    def decorate_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """给列表行合并检验提醒标记；拷贝后再加字段，不动台账原始记录。"""
        marks = {int(item["id"]): item for item in self.snapshot()["items"]}
        decorated = []
        for row in rows:
            merged = dict(row)
            mark = marks.get(int(row.get("id", 0)))
            if mark is None:
                merged["reminder_status"] = REMIND_MISSING
                merged["reminder_days"] = None
                merged["检验提醒"] = "未评估"
            else:
                merged["reminder_status"] = mark["判定"]
                merged["reminder_days"] = mark["剩余天数"]
                merged["检验提醒"] = mark["提醒文本"]
            decorated.append(merged)
        return decorated

    def _judge(self, row: dict[str, Any], today: date, threshold: int) -> dict[str, Any]:
        due = _parse_inspection_date(row.get("下次检验日"))
        days: int | None = None
        if due is None:
            # 没有下次检验日按缺失处理，不当作已到期
            verdict = REMIND_MISSING
            text = "检验日缺失"
        else:
            days = (due - today).days
            # 超期优先：同一台机械同时落在临近与超期条件里时按超期处理
            if days < 0:
                verdict = REMIND_OVERDUE
                text = f"超期 · 超 {-days} 天"
            elif days <= threshold:
                verdict = REMIND_UPCOMING
                text = f"临近 · 剩 {days} 天"
            else:
                verdict = REMIND_NORMAL
                text = "正常"
        return {
            "id": int(row.get("id", 0)),
            "机械编号": row.get("机械编号", ""),
            "机械名称": row.get("机械名称", ""),
            "额定起重量": str(row.get("额定起重量") or ""),
            "跨度规格": str(row.get("跨度规格") or ""),
            "下次检验日": str(row.get("下次检验日") or ""),
            "机械状态": row.get("status", ""),
            "剩余天数": days,
            "判定": verdict,
            "提醒文本": text,
        }

    def _summarize(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, Any] = {
            REMIND_UPCOMING: 0,
            REMIND_OVERDUE: 0,
            REMIND_MISSING: 0,
            REMIND_NORMAL: 0,
        }
        status_counter: dict[str, int] = {}
        for item in items:
            summary[item["判定"]] += 1
            status = str(item["机械状态"] or "未标记")
            status_counter[status] = status_counter.get(status, 0) + 1
        summary["待处理"] = summary[REMIND_UPCOMING] + summary[REMIND_OVERDUE]
        summary["状态统计"] = status_counter
        return summary

    def _group_by_spec(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按额定起重量 × 跨度规格区分口径，分别汇总各组的到期情况。"""
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for item in items:
            key = (item["额定起重量"], item["跨度规格"])
            group = groups.setdefault(key, {
                "额定起重量": key[0],
                "跨度规格": key[1],
                "总数": 0,
                REMIND_UPCOMING: 0,
                REMIND_OVERDUE: 0,
                REMIND_MISSING: 0,
                REMIND_NORMAL: 0,
                "待处理": 0,
            })
            group["总数"] += 1
            group[item["判定"]] += 1
            if item["判定"] in REMIND_PENDING_VERDICTS:
                group["待处理"] += 1
        return sorted(groups.values(), key=lambda group: (group["额定起重量"], group["跨度规格"]))


reminder_service = CraneReminderService()


class CraneService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("机械编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return reminder_service.decorate_rows(rows[start:start + size]), total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        reminder_service.recalculate()
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"起重机械 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于起重机械可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        reminder_service.recalculate()
        return entry, f"起重机械已{action}"
