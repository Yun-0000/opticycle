"""Select and size SPY credit verticals from observed option-chain data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from opticycle.plans import CyclePlan, occ_symbol
from opticycle.protocol import ThesisStance, parse_occ_symbol
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected, OptionOrderRequest

ALLOWED_CREDIT_SPREADS = frozenset({"bull_put", "bear_call"})
FORBIDDEN_DEBIT_SPREADS = frozenset({"bull_call", "bear_put"})
STANCE_TO_CREDIT = {
    ThesisStance.BULLISH: "bull_put",
    ThesisStance.BEARISH: "bear_call",
}


@dataclass(slots=True)
class MarketContext:
    """Market and account values supplied by observation or a test replay."""

    spot: float
    bars: pd.DataFrame
    chain: pd.DataFrame
    equity: float
    cash: float


def _parse_expiration(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or pd.isna(value):
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return None


def _occ_from_leg(underlying: str, leg: dict[str, Any]) -> str:
    option_type = str(leg.get("option_type") or "").lower()
    strike = float(leg.get("strike") or 0)
    expiration = _parse_expiration(leg.get("expiration"))
    if expiration is None:
        raise ExecutionRejected("NO_TRADE: vertical leg expiration is invalid")
    return occ_symbol(underlying, expiration, option_type.startswith("p"), strike)


def _spread_request(candidate: Any, underlying: str) -> OptionOrderRequest:
    metadata = dict(candidate.metadata or {})
    spread_type = str(metadata.get("spread_type") or "")
    if spread_type in FORBIDDEN_DEBIT_SPREADS:
        raise ExecutionRejected(f"NO_TRADE: {spread_type} debit verticals are disabled")
    if spread_type not in ALLOWED_CREDIT_SPREADS:
        raise ExecutionRejected(
            f"NO_TRADE: {spread_type or 'unknown'} is not an allowed credit vertical"
        )
    raw_legs = list(metadata.get("legs") or [])
    if len(raw_legs) != 2:
        raise ExecutionRejected("NO_TRADE: selected vertical must have exactly two legs")
    legs = [
        {
            "symbol": _occ_from_leg(underlying, leg),
            "ratio_qty": str(leg.get("ratio") or 1),
            "side": str(leg.get("side") or "").lower(),
            "position_intent": str(leg.get("position_intent") or "").lower(),
        }
        for leg in raw_legs
    ]
    if candidate.limit_price is None:
        raise ExecutionRejected("NO_TRADE: missing market-derived limit price")
    signed_limit = float(candidate.limit_price)
    if signed_limit >= 0:
        raise ExecutionRejected(
            "NO_TRADE: credit MLEG limit_price must be negative "
            "(Alpaca: positive=debit, negative=credit)"
        )
    return OptionOrderRequest(
        qty=1,
        order_type="limit",
        limit_price=signed_limit,
        order_class="mleg",
        legs=legs,
        reason=str(candidate.reason or "vertical_spread"),
        metadata={
            **metadata,
            "strategy": "vertical_spread",
            "selector": "observed_delta_exact_width",
            "underlying": underlying,
        },
    )


def vertical_max_loss_per_contract(request: OptionOrderRequest) -> Decimal:
    """Return exact credit-vertical max loss from the broker-bound limit."""
    if not request.is_multileg or not request.legs or len(request.legs) != 2:
        raise ExecutionRejected("NO_TRADE: sizing requires a two-leg vertical")
    if request.limit_price is None or Decimal(str(request.limit_price)) >= 0:
        raise ExecutionRejected("NO_TRADE: sizing requires a signed credit limit")
    strikes = [parse_occ_symbol(str(leg.get("symbol") or ""))[3] for leg in request.legs]
    width = abs(strikes[0] - strikes[1])
    credit = -Decimal(str(request.limit_price))
    max_loss = (width - credit) * Decimal("100")
    if width <= 0 or credit <= 0 or max_loss <= 0:
        raise ExecutionRejected("NO_TRADE: invalid vertical economics for sizing")
    return max_loss.quantize(Decimal("0.01"))


def apply_risk_budget_qty(
    request: OptionOrderRequest,
    portfolio: Any,
    settings: HackathonSettings,
) -> int:
    """Size one vertical from equity risk; structure limits never consume quantity."""
    equity = Decimal(str(getattr(portfolio, "equity", 0) or 0))
    existing_risk = Decimal(str(getattr(portfolio, "open_risk", 0) or 0))
    opened_today = int(getattr(portfolio, "verticals_opened_today", 0) or 0)
    open_verticals = int(getattr(portfolio, "open_verticals", 0) or 0)
    if equity <= 0:
        raise ExecutionRejected("NO_TRADE: account equity missing for risk sizing")
    per_contract = vertical_max_loss_per_contract(request)
    trade_budget = equity * Decimal(str(settings.risk_per_trade_pct))
    position_hard_cap = equity * Decimal(str(settings.max_position_pct))
    aggregate_remaining = (
        equity * Decimal(str(settings.max_total_risk_pct)) - existing_risk
    )
    risk_budget = min(trade_budget, position_hard_cap, aggregate_remaining)
    risk_qty = int((risk_budget / per_contract).to_integral_value(rounding=ROUND_FLOOR))
    if opened_today >= settings.max_new_verticals_per_day:
        raise ExecutionRejected("NO_TRADE: daily new-vertical capacity is exhausted")
    if open_verticals >= settings.max_open_verticals:
        raise ExecutionRejected("NO_TRADE: open-vertical capacity is exhausted")
    qty = min(risk_qty, settings.max_contracts_per_vertical)
    if qty <= 0:
        raise ExecutionRejected(
            "NO_TRADE: risk budget or daily/open vertical capacity is exhausted"
        )
    request.qty = qty
    request.metadata.update(
        {
            "sizing": "equity_risk_budget",
            "risk_per_trade_pct": str(settings.risk_per_trade_pct),
            "max_total_risk_pct": str(settings.max_total_risk_pct),
            "per_contract_max_loss": str(per_contract),
            "risk_budget": str(risk_budget.quantize(Decimal("0.01"))),
            "verticals_opened_today_before": opened_today,
            "open_verticals_before": open_verticals,
            "max_contracts_per_vertical": settings.max_contracts_per_vertical,
        }
    )
    return qty


def _normalize_stance(stance: ThesisStance | str | None) -> ThesisStance | None:
    if stance is None:
        return None
    if isinstance(stance, ThesisStance):
        return stance
    try:
        return ThesisStance(str(stance).strip().upper())
    except ValueError:
        return None


def _select_credit_candidate(
    settings: HackathonSettings,
    market: MarketContext,
    underlying: str,
    spread_type: str,
) -> Any:
    """Select the best exact-width credit vertical from observed quotes."""
    if spread_type in FORBIDDEN_DEBIT_SPREADS:
        raise ExecutionRejected(f"NO_TRADE: {spread_type} debit verticals are disabled")
    if spread_type not in ALLOWED_CREDIT_SPREADS:
        raise ExecutionRejected(f"NO_TRADE: {spread_type} is not an allowed credit vertical")

    chain = market.chain.copy()
    if chain.empty:
        raise ExecutionRejected("NO_TRADE: option chain missing")
    required = {"expiration_date", "strike_price", "option_type"}
    if not required.issubset(chain.columns):
        raise ExecutionRejected("NO_TRADE: option chain missing required columns")

    chain["expiration"] = chain["expiration_date"].apply(_parse_expiration)
    chain = chain[chain["expiration"].notna()]
    if chain.empty:
        raise ExecutionRejected("NO_TRADE: no usable expirations")
    today = datetime.now(ZoneInfo("America/New_York")).date()
    chain["dte"] = chain["expiration"].apply(lambda expiration: (expiration - today).days)
    chain = chain[
        (chain["dte"] >= int(settings.min_dte))
        & (chain["dte"] <= int(settings.max_dte))
    ]
    if chain.empty:
        raise ExecutionRejected("NO_TRADE: no contracts in DTE window")

    chain["option_type"] = chain["option_type"].astype(str).str.upper().str[0]
    kind = "P" if spread_type == "bull_put" else "C"
    chain = chain[chain["option_type"] == kind]
    if chain.empty:
        raise ExecutionRejected(f"NO_TRADE: no {spread_type} contracts in DTE window")

    width = Decimal(str(settings.spread_width))
    delta_min = Decimal(str(settings.short_delta_min))
    delta_max = Decimal(str(settings.short_delta_max))
    candidates: list[tuple[Decimal, dict[str, Any]]] = []
    for _, short in chain.iterrows():
        try:
            short_delta = abs(Decimal(str(short.get("delta"))))
            short_strike = Decimal(str(short.get("strike_price")))
            short_bid = Decimal(str(short.get("bid_price") or short.get("bid") or 0))
            short_ask = Decimal(str(short.get("ask_price") or short.get("ask") or 0))
        except Exception:
            continue
        if not (delta_min <= short_delta <= delta_max) or short_bid <= 0 or short_ask <= 0:
            continue

        long_strike = short_strike - width if kind == "P" else short_strike + width
        matches = chain[
            (chain["expiration"] == short["expiration"])
            & ((chain["strike_price"].astype(float) - float(long_strike)).abs() < 1e-6)
        ]
        if matches.empty:
            continue
        long = matches.iloc[0]
        try:
            long_bid = Decimal(str(long.get("bid_price") or long.get("bid") or 0))
            long_ask = Decimal(str(long.get("ask_price") or long.get("ask") or 0))
        except Exception:
            continue
        if long_bid <= 0 or long_ask <= 0:
            continue

        mid_credit = ((short_bid + short_ask) - (long_bid + long_ask)) / Decimal("2")
        credit = mid_credit.quantize(Decimal("0.01"))
        if credit <= 0 or credit >= width:
            continue
        max_loss = (width - credit) * Decimal("100")
        dte = int(short["dte"])
        score = (credit / max_loss) - (
            abs(short_delta - Decimal("0.25")) / Decimal("100")
        )
        expiration = short["expiration"]
        metadata = {
            "order_class": "mleg",
            "spread_type": spread_type,
            "underlying_symbol": underlying,
            "legs": [
                {
                    "option_type": "put" if kind == "P" else "call",
                    "strike": float(short_strike),
                    "expiration": expiration.isoformat(),
                    "side": "sell",
                    "position_intent": "sell_to_open",
                    "ratio": 1,
                },
                {
                    "option_type": "put" if kind == "P" else "call",
                    "strike": float(long_strike),
                    "expiration": expiration.isoformat(),
                    "side": "buy",
                    "position_intent": "buy_to_open",
                    "ratio": 1,
                },
            ],
            "net_price": float(credit),
            "width": float(width),
            "max_loss": float(max_loss),
            "delta_short": float(short_delta),
            "dte": dte,
            "selection": "observed_delta_exact_width",
        }
        candidates.append(
            (
                score,
                {
                    "metadata": metadata,
                    "limit_price": -float(credit),
                    "reason": (
                        f"{spread_type} ${width:g} wide, short delta {short_delta:.2f}, "
                        f"{dte} DTE, credit {credit:.2f}"
                    ),
                },
            )
        )
    if not candidates:
        raise ExecutionRejected(f"NO_TRADE: no {spread_type} credit vertical available")
    return SimpleNamespace(**max(candidates, key=lambda item: item[0])[1])


def build_vertical_cycle_plan(
    settings: HackathonSettings,
    *,
    market: MarketContext | None = None,
    dry_run: bool = True,
    underlying_price: float | None = None,
    stance: ThesisStance | str | None = None,
) -> CyclePlan:
    """Build the exact credit vertical authorized by a directional thesis."""
    if settings.strategy != "vertical_spread":
        raise ExecutionRejected("only SPY defined-risk vertical is enabled")
    if market is None:
        raise ExecutionRejected("market observation required; live path cannot synthesize fixtures")
    if not dry_run and underlying_price is not None:
        raise ExecutionRejected("live path cannot use a hardcoded underlying price")

    resolved = _normalize_stance(stance)
    if resolved is None or resolved == ThesisStance.NO_TRADE:
        raise ExecutionRejected("NO_TRADE: thesis stance is missing or not directional")
    spread_type = STANCE_TO_CREDIT.get(resolved)
    if spread_type is None:
        raise ExecutionRejected("NO_TRADE: thesis stance does not map to a credit vertical")

    underlying = settings.symbols[0]
    candidate = _select_credit_candidate(settings, market, underlying, spread_type)
    request = _spread_request(candidate, underlying)
    return CyclePlan(
        strategy="vertical_spread",
        request=request,
        underlying=underlying,
        notes=str(candidate.reason or spread_type),
        metadata={
            "selector": "observed_delta_exact_width",
            "spread_type": spread_type,
            "stance": resolved.value,
        },
    )
