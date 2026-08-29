"""Build options-only action plans for the autonomous cycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from gaussoptions.settings import HackathonSettings
from trade.orders import OptionOrderRequest


@dataclass(slots=True)
class CyclePlan:
    strategy: str
    request: OptionOrderRequest
    underlying: str
    notes: str
    metadata: dict[str, Any] = field(default_factory=dict)


def occ_symbol(underlying: str, expiration: date, put: bool, strike: float) -> str:
    root = underlying.strip().upper()
    kind = "P" if put else "C"
    strike_int = int(round(strike * 1000))
    return f"{root}{expiration.strftime('%y%m%d')}{kind}{strike_int:08d}"


def demo_expiration(days: int = 21) -> date:
    today = date.today()
    target = today + timedelta(days=days)
    while target.weekday() != 4:
        target += timedelta(days=1)
    return target


def build_cycle_plan(
    settings: HackathonSettings,
    *,
    underlying_price: float = 500.0,
    dry_run: bool = True,
) -> CyclePlan:
    """Build an option order from the pin wheel / vertical_spread ActionPlan."""
    from gaussoptions.pin_option import build_pin_cycle_plan

    return build_pin_cycle_plan(
        settings,
        underlying_price=underlying_price,
        dry_run=dry_run,
    )
