"""起重机械到期提醒：按额定起重量与跨度规格区分口径，统一算出临近/超期/缺失判定。

列表标记、运营概览待处理量与起重机械台账都从 evaluate_all 取同一份结果；
调整阈值时先把旧口径下的判定存入历史，历史判定不随新阈值回改。
判定只读台账记录，绝不回写，保证刷新前后已有起重机械记录不被改动。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.config import settings
from app.store import store

MODULE = "crane"

# 判定类别：正常、临近、超期、缺失
NORMAL = "正常"
NEAR = "临近"
OVERDUE = "超期"
MISSING = "缺失"

# 列为待处理的判定：临近或已超期；缺失单独成类，不算待处理也不算已到期
PENDING_LABELS = (NEAR, OVERDUE)

LEDGER_FIELDS = ["机械编号", "机械名称", "额定起重量", "跨度规格", "使用场所", "下次检验日"]

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def parse_measure(raw: Any) -> float | None:
    """从「10t」「22.5米」这类规格文本里取出数值；取不到按 None 处理。"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = _NUMBER_RE.search(str(raw))
    return float(match.group()) if match else None


def parse_day(raw: Any) -> date | None:
    """解析下次检验日；空值或无法解析都按缺失处理，而不是当作已到期。"""
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class CraneReminderService:
    """起重机械到期提醒的判定与口径管理。"""

    # ---- 口径（阈值规则） ----

    def current_rule(self) -> dict[str, Any]:
        """读取当前口径；第一次访问时用配置里的默认口径初始化。"""
        rule = store.reminder_rule(MODULE)
        if rule is None:
            rule = {
                "version": 1,
                "updated_at": None,
                "tiers": [dict(tier) for tier in settings.crane_reminder_tiers],
            }
            store.save_reminder_rule(MODULE, rule)
        return rule

    def update_rule(self, tiers: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
        """调整到期判定阈值：先把旧口径下的判定留档，再启用新口径。"""
        cleaned, error = self._validate_tiers(tiers)
        if error:
            return None, error
        old_rule = self.current_rule()
        today = date.today()
        # 历史判定按当时的阈值保留：归档旧口径下每台机械的判断结果。
        store.append_reminder_history(MODULE, {
            "version": old_rule["version"],
            "tiers": [dict(tier) for tier in old_rule["tiers"]],
            "archived_at": today.isoformat(),
            "judgments": self.evaluate_all(rule=old_rule, today=today),
        })
        new_rule = {
            "version": int(old_rule.get("version", 0)) + 1,
            "updated_at": today.isoformat(),
            "tiers": cleaned,
        }
        store.save_reminder_rule(MODULE, new_rule)
        return new_rule, ""

    def history(self) -> list[dict[str, Any]]:
        return store.reminder_history(MODULE)

    @staticmethod
    def _validate_tiers(tiers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        if not tiers:
            return [], "口径档位不能为空，至少保留一档"
        cleaned: list[dict[str, Any]] = []
        for tier in tiers:
            name = str(tier.get("name") or "").strip()
            if not name:
                return [], "口径档位缺少名称"
            try:
                min_capacity = float(tier.get("min_capacity_t", 0) or 0)
                min_span = float(tier.get("min_span_m", 0) or 0)
                threshold = int(tier.get("threshold_days", 0) or 0)
            except (TypeError, ValueError):
                return [], f"口径「{name}」的阈值不是有效数字"
            if min_capacity < 0 or min_span < 0 or threshold < 0:
                return [], f"口径「{name}」的下限与阈值不能为负数"
            cleaned.append({
                "name": name,
                "min_capacity_t": min_capacity,
                "min_span_m": min_span,
                "threshold_days": threshold,
            })
        if not any(t["min_capacity_t"] == 0 and t["min_span_m"] == 0 for t in cleaned):
            return [], "需要一档下限为 0 的兜底口径，否则小吨位机械无法归档"
        return cleaned, ""

    # ---- 判定 ----

    @staticmethod
    def _ordered_tiers(rule: dict[str, Any]) -> list[dict[str, Any]]:
        """档位从大到小排序，命中即停；兜底档（下限 0）一定排在最后。"""
        return sorted(
            rule.get("tiers", []),
            key=lambda tier: (tier["min_capacity_t"], tier["min_span_m"]),
            reverse=True,
        )

    def classify_tier(self, entry: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
        """按额定起重量与跨度规格归档：任一项达到档位下限即落入该档。"""
        capacity = parse_measure(entry.get("额定起重量")) or 0.0
        span = parse_measure(entry.get("跨度规格")) or 0.0
        for tier in self._ordered_tiers(rule):
            if capacity >= tier["min_capacity_t"] or span >= tier["min_span_m"]:
                return tier
        return {"name": "未分档", "min_capacity_t": 0.0, "min_span_m": 0.0, "threshold_days": 0}

    def evaluate_entry(
        self,
        entry: dict[str, Any],
        rule: dict[str, Any],
        today: date,
    ) -> dict[str, Any]:
        """对单台机械给出判定；同时命中临近与超期时按超期优先。"""
        tier = self.classify_tier(entry, rule)
        threshold = int(tier["threshold_days"])
        due = parse_day(entry.get("下次检验日"))
        if due is None:
            label, remaining = MISSING, None
        else:
            remaining = (due - today).days
            if remaining < 0:
                label = OVERDUE  # 已过期优先于临近
            elif remaining <= threshold:
                label = NEAR
            else:
                label = NORMAL
        return {
            "id": entry.get("id"),
            "机械编号": entry.get("机械编号"),
            "机械名称": entry.get("机械名称"),
            "额定起重量": entry.get("额定起重量"),
            "跨度规格": entry.get("跨度规格"),
            "下次检验日": entry.get("下次检验日"),
            "检验口径": tier["name"],
            "提醒阈值": threshold,
            "剩余天数": remaining,
            "到期提醒": label,
            "待处理": label in PENDING_LABELS,
        }

    def evaluate_all(
        self,
        rule: dict[str, Any] | None = None,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        """对全量起重机械出一次判定，三处展示共用这一份结果。"""
        rule = rule or self.current_rule()
        today = today or date.today()
        return [self.evaluate_entry(row, rule, today) for row in store.rows(MODULE)]

    def pending_count(self) -> int:
        """运营概览用的待处理量：临近与超期的台数。"""
        return sum(1 for item in self.evaluate_all() if item["待处理"])

    def summary(self, judgments: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "总数": len(judgments),
            NEAR: sum(1 for item in judgments if item["到期提醒"] == NEAR),
            OVERDUE: sum(1 for item in judgments if item["到期提醒"] == OVERDUE),
            MISSING: sum(1 for item in judgments if item["到期提醒"] == MISSING),
            NORMAL: sum(1 for item in judgments if item["到期提醒"] == NORMAL),
            "待处理": sum(1 for item in judgments if item["待处理"]),
        }

    def ledger(self) -> dict[str, Any]:
        """起重机台账：按口径分组的全量判定，与列表标记、概览待处理量同一份结果。"""
        rule = self.current_rule()
        judgments = self.evaluate_all(rule=rule)
        groups: list[dict[str, Any]] = []
        for tier in self._ordered_tiers(rule):
            items = [item for item in judgments if item["检验口径"] == tier["name"]]
            groups.append({
                "口径": tier["name"],
                "提醒阈值": tier["threshold_days"],
                "机械": items,
                **self.summary(items),
            })
        known = {group["口径"] for group in groups}
        stray = [item for item in judgments if item["检验口径"] not in known]
        if stray:
            groups.append({"口径": "未分档", "提醒阈值": 0, "机械": stray, **self.summary(stray)})
        return {
            "module": MODULE,
            "generated_at": date.today().isoformat(),
            "rule": rule,
            "summary": self.summary(judgments),
            "groups": groups,
        }

    # ---- 列表标记 ----

    def annotate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """给列表行附上到期提醒标记；返回副本，不改动台账里的原始记录。"""
        rule = self.current_rule()
        today = date.today()
        annotated: list[dict[str, Any]] = []
        for row in rows:
            judgment = self.evaluate_entry(row, rule, today)
            marked = dict(row)
            marked["检验口径"] = judgment["检验口径"]
            marked["剩余天数"] = judgment["剩余天数"]
            marked["到期提醒"] = judgment["到期提醒"]
            annotated.append(marked)
        return annotated


crane_reminder_service = CraneReminderService()
