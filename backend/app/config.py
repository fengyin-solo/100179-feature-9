"""运行配置：端口、跨域、运行环境与起重机械到期提醒的默认口径。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Settings:
    app_name: str = "特种设备点检运维平台"
    env: str = "local"
    port: int = 8000
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200
    # 起重机械到期提醒的默认口径：按额定起重量（吨）与跨度（米）分档，
    # 任一项达到下限即落入该档；threshold_days 是临近检验的提醒阈值，可在台账页调整。
    crane_reminder_tiers: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"name": "大型机械", "min_capacity_t": 50.0, "min_span_m": 30.0, "threshold_days": 90},
            {"name": "中型机械", "min_capacity_t": 10.0, "min_span_m": 15.0, "threshold_days": 60},
            {"name": "小型机械", "min_capacity_t": 0.0, "min_span_m": 0.0, "threshold_days": 30},
        ]
    )


settings = Settings()
