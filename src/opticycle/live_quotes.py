"""Probe whether live Alpaca quotes can be observed. Never injects a miss."""

from __future__ import annotations

import os
from typing import Any


def probe_live_quotes() -> dict[str, Any]:
    """Alpaca market data requires keys. Do not fake a genuine NO_TRADE without them."""
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        return {
            "available": False,
            "genuine_no_trade_recorded": False,
            "injected_no_trade_promoted": False,
            "reason": (
                "missing local Alpaca credentials; quotes cannot be observed keylessly; "
                "no genuine NO_TRADE recorded"
            ),
        }
    return {
        "available": True,
        "genuine_no_trade_recorded": False,
        "injected_no_trade_promoted": False,
        "reason": "credentials present; genuine NO_TRADE is recorded only by scripts/record-genuine-no-trade.py",
    }
