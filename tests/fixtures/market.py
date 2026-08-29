"""Synthetic bars, option chain, and book for dry-run tests only."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from opticycle.pin_option import ObservedBook, ObservedChainAdapter, ObservedFred, PinMarket
from opticycle.plans import occ_symbol


def demo_expiration(days: int = 14) -> date:
    target = date.today() + timedelta(days=days)
    while target.weekday() != 4:
        target += timedelta(days=1)
    return target


def historical_bars(spot: float, rows: int = 60) -> pd.DataFrame:
    """Uptrend bars so vertical_spread can emit a bullish signal."""
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


def chain_frame(
    underlying: str,
    spot: float,
    expiration: date,
    bs_price: Any,
) -> pd.DataFrame:
    t_years = max((expiration - date.today()).days, 1) / 365.0
    rate = 0.04
    vol = 0.70
    rows: list[dict[str, Any]] = []
    strikes = [
        round(spot * factor, 0)
        for factor in (0.90, 0.93, 0.95, 0.97, 0.99, 1.00, 1.01, 1.03, 1.05, 1.07, 1.10)
    ]
    for strike in strikes:
        for kind, flag in (("P", "put"), ("C", "call")):
            mid = float(
                bs_price(
                    spot=spot,
                    strike=strike,
                    time_to_expiry=t_years,
                    risk_free_rate=rate,
                    volatility=vol,
                    option_type=flag,
                )
            )
            mid = max(mid, 0.15)
            delta = 0.22
            symbol = occ_symbol(underlying, expiration, kind == "P", strike)
            rows.append(
                {
                    "symbol": symbol,
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
                    "implied_volatility": vol,
                    "quote_timestamp": datetime.now(timezone.utc),
                    "volume": 500,
                    "open_interest": 2_000,
                }
            )
    return pd.DataFrame(rows)


def _bs_price() -> Any:
    from opticycle.pin_option import PIN_SRC
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_fixture_bs_price", PIN_SRC / "analysis" / "option_greeks.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("pin option_greeks is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bs_price


def make_pin_market(
    *,
    underlying: str = "SPY",
    spot: float = 500.0,
    equity: float = 100_000.0,
) -> PinMarket:
    expiration = demo_expiration(days=14)
    chain = chain_frame(underlying, spot, expiration, _bs_price())
    return PinMarket(
        spot=spot,
        bars=historical_bars(spot),
        chain=chain,
        equity=equity,
        cash=equity,
        book=ObservedBook(equity=equity, cash=equity),
        provider=ObservedChainAdapter(chain),
        fred=ObservedFred(),
    )
