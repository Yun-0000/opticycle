"""Pre-trade risk gates for the $100k paper book."""

from __future__ import annotations

from typing import Mapping

from src.gaussoptions.profile import HackathonProfile


def check_order(profile: HackathonProfile, order: Mapping[str, object], book: Mapping[str, object]) -> None:
    if profile.require_options and order.get("asset_class") != "option":
        raise ValueError("stock-only orders are disabled")
    notional = float(order.get("notional") or 0)
    equity = float(book.get("equity") or profile.starting_capital)
    if equity <= 0:
        raise ValueError("paper equity must be positive")
    if notional > equity * profile.max_position_pct:
        raise ValueError("order exceeds max_position_pct")
    trades_today = int(book.get("trades_today") or 0)
    if trades_today >= profile.max_daily_trades:
        raise ValueError("max_daily_trades reached")
