"""Portfolio state — one position, cooldown, daily loss cap.

Small on purpose. v1's `trade_filter.py` carried four blackout windows, an escalating
cooldown, a momentum-gated breaker and an ATR band, and blocked 1,621 of 1,820 attempts.
Most of that was protecting P&L rather than win rate (streak 3+ actually won 44.8% vs
streak 0 at 35.7%), and none of it was ever isolated. v2 starts with the three rules
whose justification is structural, and earns anything else back with evidence.

ONE POSITION IS NOT A SIMPLIFICATION, IT IS THE MEASUREMENT CONVENTION.
Every honest number in this repo is computed under a one-position convention. The one
time an overlapping-events convention was used it produced a 10pp "chop filter" that
vanished and partly reversed when re-run correctly
(docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .config import Config


@dataclass
class Portfolio:
    """Mutable state that survives across bars."""

    cfg: Config
    open_count: int = 0
    bars_since_stop: Optional[int] = None  # None = not cooling down
    losses_today: int = 0
    current_day: Optional[datetime] = None
    refusals: Dict[str, int] = field(default_factory=dict)

    def refuse(self, reason: str) -> None:
        """Count a refusal by category, so a report can say where the setups went."""
        key = reason.split(";")[0].split("(")[0].strip()[:48]
        self.refusals[key] = self.refusals.get(key, 0) + 1

    def on_new_bar(self, ts: datetime) -> None:
        """Roll the daily counter and advance the cooldown clock."""
        day = datetime(ts.year, ts.month, ts.day)
        if self.current_day is None or day != self.current_day:
            self.current_day = day
            self.losses_today = 0
        if self.bars_since_stop is not None:
            self.bars_since_stop += 1
            if self.bars_since_stop >= self.cfg.cooldown_bars:
                self.bars_since_stop = None

    def can_enter(self, ts: datetime) -> Optional[str]:
        """Refusal reason if a new entry is not allowed right now, else None."""
        if self.open_count >= self.cfg.max_open:
            return "position already open"
        if self.bars_since_stop is not None:
            return f"cooldown ({self.bars_since_stop}/{self.cfg.cooldown_bars} bars)"
        if self.losses_today >= self.cfg.max_daily_losses:
            return f"daily loss cap ({self.losses_today}/{self.cfg.max_daily_losses})"
        return None

    def opened(self) -> None:
        self.open_count += 1

    def closed(self, stopped_out: bool) -> None:
        self.open_count = max(0, self.open_count - 1)
        if stopped_out:
            self.bars_since_stop = 0
            self.losses_today += 1
