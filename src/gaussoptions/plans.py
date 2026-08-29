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
) -> CyclePlan:
    """Return a wheel or vertical-spread option order for the watchlist symbol."""
    underlying = settings.symbols[0]
    expiration = demo_expiration()
    if settings.strategy == "vertical_spread":
        short_strike = round(underlying_price * 0.97, 0)
        long_strike = round(underlying_price * 0.95, 0)
        short_sym = occ_symbol(underlying, expiration, True, short_strike)
        long_sym = occ_symbol(underlying, expiration, True, long_strike)
        request = OptionOrderRequest(
            qty=1,
            order_type="limit",
            limit_price=0.85,
            order_class="mleg",
            legs=[
                {
                    "symbol": short_sym,
                    "ratio_qty": "1",
                    "side": "sell",
                    "position_intent": "sell_to_open",
                },
                {
                    "symbol": long_sym,
                    "ratio_qty": "1",
                    "side": "buy",
                    "position_intent": "buy_to_open",
                },
            ],
            reason="bull put credit spread",
            metadata={"strategy": "vertical_spread", "underlying": underlying},
        )
        return CyclePlan(
            strategy="vertical_spread",
            request=request,
            underlying=underlying,
            notes="vertical put credit spread",
        )
    strike = round(underlying_price * 0.95, 0)
    symbol = occ_symbol(underlying, expiration, True, strike)
    request = OptionOrderRequest(
        qty=1,
        symbol=symbol,
        side="sell",
        order_type="limit",
        limit_price=1.25,
        position_intent="sell_to_open",
        reason="cash-secured put",
        metadata={"strategy": "wheel", "stage": "cash_secured_put", "underlying": underlying},
    )
    return CyclePlan(
        strategy="wheel",
        request=request,
        underlying=underlying,
        notes="wheel cash-secured put",
    )
