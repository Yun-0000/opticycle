"""Pre-trade risk gates sized for a $100k paper options book."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opticycle.settings import HackathonSettings
from trade.orders import OCC_SYMBOL_RE, ExecutionRejected, OptionOrderRequest

OPTION_MULTIPLIER = 100


@dataclass(slots=True)
class PortfolioSnapshot:
    equity: float
    buying_power: float
    cash: float
    account_id: str | None = None
    paper: bool = True
    options_approved: bool = True
    trades_today: int = 0
    open_positions: int = 0
    net_delta: float = 0.0
    net_vega: float = 0.0
    positions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class GateResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)

    def raise_if_rejected(self) -> None:
        if not self.approved:
            raise ExecutionRejected("; ".join(self.reasons) or "risk gate rejected the order")


class RiskGate:
    def __init__(self, settings: HackathonSettings) -> None:
        self.settings = settings

    def evaluate(
        self,
        request: OptionOrderRequest,
        portfolio: PortfolioSnapshot,
        *,
        underlying_price: float | None = None,
        option_price: float | None = None,
        proposed_delta: float = 0.0,
        proposed_vega: float = 0.0,
    ) -> GateResult:
        reasons: list[str] = []
        request.assert_options_instrument()

        if not self.settings.require_options:
            reasons.append("options-mandatory profile is off")
        if not portfolio.paper or not self.settings.paper_only:
            reasons.append("paper account required")
        if not portfolio.options_approved:
            reasons.append("options trading is not approved on this account")

        expected_id = self.settings.paper_account_id
        if expected_id and portfolio.account_id and portfolio.account_id != expected_id:
            reasons.append("account id does not match the dedicated paper account")

        target = self.settings.starting_capital
        if portfolio.equity <= 0:
            reasons.append("equity is missing")
        else:
            drift = abs(portfolio.equity - target) / target
            if drift > self.settings.equity_tolerance:
                reasons.append(
                    f"equity {portfolio.equity:.0f} is outside the ${target:.0f} paper book window"
                )

        if portfolio.trades_today >= self.settings.max_daily_trades:
            reasons.append("daily trade limit reached")
        if portfolio.open_positions >= self.settings.max_open_positions:
            reasons.append("open position limit reached")

        notional = _order_notional(request, underlying_price, option_price)
        if portfolio.equity > 0 and notional / portfolio.equity > self.settings.max_position_pct:
            reasons.append("order exceeds max position percent")
        if notional > portfolio.buying_power:
            reasons.append("insufficient buying power")

        new_delta = abs(portfolio.net_delta + proposed_delta)
        new_vega = abs(portfolio.net_vega + proposed_vega)
        if new_delta > self.settings.max_abs_delta:
            reasons.append("portfolio delta limit exceeded")
        if new_vega > self.settings.max_abs_vega:
            reasons.append("portfolio vega limit exceeded")

        return GateResult(approved=not reasons, reasons=reasons)


def contract_greeks(
    flag: str,
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    sigma: float,
) -> dict[str, float]:
    """Black-Scholes greeks via vollib (delta/vega per 1.00, scaled by multiplier in callers)."""
    from vollib.black_scholes.greeks.analytical import delta, vega, gamma, theta

    kind = "c" if flag.lower().startswith("c") else "p"
    return {
        "delta": float(delta(kind, spot, strike, time_to_expiry, rate, sigma)),
        "vega": float(vega(kind, spot, strike, time_to_expiry, rate, sigma)),
        "gamma": float(gamma(kind, spot, strike, time_to_expiry, rate, sigma)),
        "theta": float(theta(kind, spot, strike, time_to_expiry, rate, sigma)),
    }


def scale_greeks(greeks: dict[str, float], qty: int, side: str) -> dict[str, float]:
    sign = -1.0 if side.lower() == "sell" else 1.0
    factor = sign * abs(qty) * OPTION_MULTIPLIER
    return {key: value * factor for key, value in greeks.items()}


def _order_notional(
    request: OptionOrderRequest,
    underlying_price: float | None,
    option_price: float | None,
) -> float:
    if request.limit_price is not None:
        premium = abs(float(request.limit_price))
    elif option_price is not None:
        premium = abs(float(option_price))
    elif underlying_price is not None:
        premium = abs(float(underlying_price)) * 0.02
    else:
        premium = 1.0
    qty = abs(int(request.qty))
    if request.is_multileg:
        return premium * qty * OPTION_MULTIPLIER
    return premium * qty * OPTION_MULTIPLIER
