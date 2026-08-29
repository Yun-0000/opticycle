"""Autonomous cycle: decide an option structure, gate it, then MCP/CLI submit."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from src.gaussoptions.profile import HackathonProfile
from src.gaussoptions.risk import check_order
from src.gaussoptions.journal import append as journal_append
from pathlib import Path


class OptionExecutor(Protocol):
    def place_option_order(self, order: Mapping[str, Any]) -> dict[str, Any]: ...


def decide_option_order(profile: HackathonProfile, market: Mapping[str, Any]) -> dict[str, Any]:
    """MVP decision: sell a cash-secured put (wheel entry) on the profile symbol."""
    symbol = str(market.get("option_symbol") or f"{profile.symbol}P")
    qty = int(market.get("qty") or 1)
    notional = float(market.get("notional") or 5000)
    return {
        "symbol": symbol,
        "qty": qty,
        "side": "sell",
        "type": "market",
        "time_in_force": "day",
        "asset_class": "option",
        "strategy": "wheel",
        "notional": notional,
    }


def run_once(
    profile: HackathonProfile,
    executor: OptionExecutor,
    market: Mapping[str, Any],
    book: Mapping[str, Any],
) -> dict[str, Any]:
    backend = profile.validate_backend()
    order = decide_option_order(profile, market)
    check_order(profile, order, book)
    submitted = executor.place_option_order(order)
    record = {
        "backend": backend,
        "decision": order,
        "execution": submitted,
        "status": "filled_or_submitted",
    }
    journal_append(Path("artifacts/journal.json"), record)
    return {
        "backend": backend,
        "decision": order,
        "execution": submitted,
        "status": "filled_or_submitted",
    }
