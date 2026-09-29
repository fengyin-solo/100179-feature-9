"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._configs: dict[str, Any] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._histories: dict[str, list[dict[str, Any]]] = {}

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def get_config(self, key: str, default: Any = None) -> Any:
        """运行时可调口径（如提醒阈值）放这里，不动冻结的 Settings。"""
        return self._configs.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        self._configs[key] = value

    def get_snapshot(self, module: str) -> dict[str, Any] | None:
        """同一模块同一时刻只保留一份评估快照，各视图读同一份。"""
        return self._snapshots.get(module)

    def set_snapshot(self, module: str, snapshot: dict[str, Any]) -> None:
        self._snapshots[module] = snapshot

    def append_history(self, module: str, record: dict[str, Any], *, limit: int = 50) -> None:
        """评估历史只追加不回改，保留当时口径下的判断。"""
        history = self._histories.setdefault(module, [])
        history.append(record)
        del history[:-limit]

    def history(self, module: str) -> list[dict[str, Any]]:
        return list(self._histories.get(module, []))

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
