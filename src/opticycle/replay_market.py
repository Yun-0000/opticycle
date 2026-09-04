"""Keyless replay market. It is test data, never live quote or fill evidence."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from opticycle.plans import occ_symbol
from opticycle.verticals import MarketContext


def _friday_after(days: int = 3) -> date:
    target = date.today() + timedelta(days=days)
    while target.weekday() != 4:
        target += timedelta(days=1)
    return target


def _uptrend_closes(spot: float, rows: int = 60) -> pd.DataFrame:
    start = spot * 0.86
    step = (spot - start) / max(rows - 1, 1)
    closes = [start + step * index for index in range(rows)]
    closes[-1] = spot
    return pd.DataFrame(
        {
            "close": closes,
            "high": [value * 1.004 for value in closes],
            "low": [value * 0.996 for value in closes],
            "open": closes,
            "volume": [1_000_000] * rows,
        }
    )


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _bs_price(
    *,
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,
) -> float:
    years = max(time_to_expiry, 1 / 365)
    sigma = max(volatility, 0.01)
    root_t = math.sqrt(years)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * sigma * sigma) * years
    ) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    discount = math.exp(-risk_free_rate * years)
    if option_type == "call":
        return spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
    if option_type == "put":
        return strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    raise ValueError("option_type must be call or put")


def _synthetic_chain(underlying: str, spot: float, expiration: date) -> pd.DataFrame:
    years = max((expiration - date.today()).days, 1) / 365.0
    rate = 0.04
    volatility = 0.70
    rows: list[dict[str, Any]] = []
    center = int(round(spot / 5.0) * 5)
    strikes = list(range(center - 50, center + 55, 5))
    now = datetime.now(timezone.utc)
    for strike in strikes:
        for kind, option_type in (("P", "put"), ("C", "call")):
            mid = max(
                _bs_price(
                    spot=spot,
                    strike=strike,
                    time_to_expiry=years,
                    risk_free_rate=rate,
                    volatility=volatility,
                    option_type=option_type,
                ),
                0.15,
            )
            delta = 0.22
            rows.append(
                {
                    "symbol": occ_symbol(underlying, expiration, kind == "P", strike),
                    "underlying_symbol": underlying,
                    "option_type": kind,
                    "strike_price": float(strike),
                    "expiration_date": pd.Timestamp(expiration),
                    "bid_price": round(mid * 0.97, 2),
                    "ask_price": round(mid * 1.03, 2),
                    "last_price": round(mid, 2),
                    "bid": round(mid * 0.97, 2),
                    "ask": round(mid * 1.03, 2),
                    "delta": -delta if kind == "P" else delta,
                    "gamma": 0.01,
                    "theta": -0.04,
                    "vega": 0.08,
                    "implied_volatility": volatility,
                    "quote_timestamp": now,
                    "volume": 500,
                    "open_interest": 2_000,
                }
            )
    return pd.DataFrame(rows)


def replay_market(
    *,
    underlying: str = "SPY",
    spot: float = 500.0,
    equity: float = 100_000.0,
) -> MarketContext:
    expiration = _friday_after(days=3)
    return MarketContext(
        spot=spot,
        bars=_uptrend_closes(spot),
        chain=_synthetic_chain(underlying, spot, expiration),
        equity=equity,
        cash=equity,
    )
