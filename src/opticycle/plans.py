"""Build options-only action plans for the autonomous cycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from opticycle.protocol import ThesisStance
from opticycle.settings import HackathonSettings
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


def build_cycle_plan(
    settings: HackathonSettings,
    *,
    market: Any | None = None,
    dry_run: bool = True,
    underlying_price: float | None = None,
    stance: ThesisStance | str | None = None,
) -> CyclePlan:
    """Build a SPY defined-risk credit vertical bound to the thesis stance."""
    from opticycle.verticals import build_vertical_cycle_plan

    return build_vertical_cycle_plan(
        settings,
        market=market,
        dry_run=dry_run,
        underlying_price=underlying_price,
        stance=stance,
    )
