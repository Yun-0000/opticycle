"""Keyless dry-run / replay market. Not a live quote path and not a fill."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from opticycle.pin_option import ObservedBook, ObservedChainAdapter, ObservedFred, PinMarket, PIN_SRC
from opticycle.plans import occ_symbol


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


def _synthetic_chain(underlying: str, spot: float, expiration: date, bs_price: Any) -> pd.DataFrame:
    t_years = max((expiration - date.today()).days, 1) / 365.0
    rate = 0.04
    vol = 0.70
    rows: list[dict[str, Any]] = []
    center = int(round(spot / 5.0) * 5)
    strikes = list(range(center - 50, center + 55, 5))
    now = datetime.now(timezone.utc)
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
                    "quote_timestamp": now,
                    "volume": 500,
                    "open_interest": 2_000,
                }
            )
    return pd.DataFrame(rows)


def _bs_price() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_replay_bs_price", PIN_SRC / "analysis" / "option_greeks.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("pin option_greeks is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bs_price


def replay_pin_market(
    *,
    underlying: str = "SPY",
    spot: float = 500.0,
    equity: float = 100_000.0,
) -> PinMarket:
    expiration = _friday_after(days=3)
    chain = _synthetic_chain(underlying, spot, expiration, _bs_price())
    return PinMarket(
        spot=spot,
        bars=_uptrend_closes(spot),
        chain=chain,
        equity=equity,
        cash=equity,
        book=ObservedBook(equity=equity, cash=equity),
        provider=ObservedChainAdapter(chain),
        fred=ObservedFred(),
    )
