"""Load wheel / vertical_spread from vendor/pin-31374551 and turn ActionPlans into orders."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from opticycle.plans import CyclePlan, occ_symbol
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected, OptionOrderRequest

PIN_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "pin-31374551"
PIN_SRC = PIN_ROOT / "src"
PIN_COMMIT = "31374551"


@dataclass(slots=True)
class ObservedBook:
    """Account book adapter over already-observed equity. Not a fixture generator."""

    equity: float
    cash: float
    positions: dict[str, Any] = field(default_factory=dict)
    option_positions: dict[str, Any] = field(default_factory=dict)

    def get_portfolio_value(self, _prices: Any = None) -> float:
        return float(self.equity)

    def get_available_cash(self) -> float:
        return float(self.cash)


class ObservedChainAdapter:
    """Wrap an already-fetched option chain. Does not synthesize contracts."""

    def __init__(self, chain: pd.DataFrame) -> None:
        self._chain = chain

    def get_options_chain(self, _symbol: str) -> pd.DataFrame:
        return self._chain.copy()


class ObservedFred:
    """Risk-free rate adapter. Live callers pass an observed rate; default is unused on live path."""

    def __init__(self, percent: float = 4.0) -> None:
        self._percent = percent

    def get_treasury_yield(self, _maturity: str = "3M") -> pd.DataFrame:
        return pd.DataFrame({"value": [self._percent]})


@dataclass(slots=True)
class PinMarket:
    """Caller-supplied market context. Live path must pass observed data, never fixtures."""

    spot: float
    bars: pd.DataFrame
    chain: pd.DataFrame
    equity: float
    cash: float
    book: ObservedBook
    provider: ObservedChainAdapter
    fred: ObservedFred


def _pin_on_path() -> None:
    root = str(PIN_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _pkg(name: str, path: Path) -> None:
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__path__", None):
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__file__ = str(path / "__init__.py")
    sys.modules[name] = module


def _load_file(fullname: str, path: Path) -> types.ModuleType:
    loaded = sys.modules.get(fullname)
    if loaded is not None and getattr(loaded, "__file__", None) == str(path):
        return loaded
    spec = importlib.util.spec_from_file_location(fullname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


def _install_pin_modules(market: PinMarket) -> dict[str, Any]:
    """Import pin option classes without executing src.strategy package __init__."""
    _pin_on_path()
    _pkg("src", PIN_SRC)
    _pkg("src.strategy", PIN_SRC / "strategy")
    _pkg("src.strategy.option", PIN_SRC / "strategy" / "option")
    _pkg("src.analysis", PIN_SRC / "analysis")
    _pkg("src.data", PIN_SRC / "data")
    _pkg("src.utils", PIN_SRC / "utils")
    _pkg("src.watchlist", PIN_SRC / "watchlist")

    _load_file("src.strategy.base", PIN_SRC / "strategy" / "base.py")
    _load_file("src.strategy.utils", PIN_SRC / "strategy" / "utils.py")
    _load_file("src.analysis.option_greeks", PIN_SRC / "analysis" / "option_greeks.py")
    _load_file("src.analysis.technical_analysis", PIN_SRC / "analysis" / "technical_analysis.py")
    _load_file("src.utils.timezone_utils", PIN_SRC / "utils" / "timezone_utils.py")
    _load_file("src.utils.asset_utils", PIN_SRC / "utils" / "asset_utils.py")
    _load_file("src.watchlist.watchlist_manager", PIN_SRC / "watchlist" / "watchlist_manager.py")

    if "src.watchlist" in sys.modules:
        watchlist_pkg = sys.modules["src.watchlist"]
        manager_mod = sys.modules["src.watchlist.watchlist_manager"]
        watchlist_pkg.WatchlistManager = manager_mod.WatchlistManager

    alpaca_mod = types.ModuleType("src.data.alpaca_provider")
    alpaca_mod.AlpacaDataProvider = lambda: market.provider
    sys.modules["src.data.alpaca_provider"] = alpaca_mod

    fred_mod = types.ModuleType("src.data.fred_provider")
    fred_mod.FREDProvider = lambda: market.fred
    sys.modules["src.data.fred_provider"] = fred_mod

    data_pkg = sys.modules["src.data"]
    data_pkg.AlpacaDataProvider = alpaca_mod.AlpacaDataProvider

    wheel_mod = _load_file("src.strategy.option.wheel", PIN_SRC / "strategy" / "option" / "wheel.py")
    spread_mod = _load_file(
        "src.strategy.option.vertical_spread",
        PIN_SRC / "strategy" / "option" / "vertical_spread.py",
    )
    return {
        "WheelStrategy": wheel_mod.WheelStrategy,
        "VerticalSpreadStrategy": spread_mod.VerticalSpreadStrategy,
    }


def _occ_from_leg(underlying: str, leg: dict[str, Any]) -> str:
    option_type = str(leg.get("option_type") or "").lower()
    is_put = option_type.startswith("p")
    strike = float(leg.get("strike") or 0)
    raw_exp = leg.get("expiration")
    if isinstance(raw_exp, datetime):
        exp = raw_exp.date()
    elif isinstance(raw_exp, date):
        exp = raw_exp
    else:
        exp = datetime.fromisoformat(str(raw_exp)).date()
    return occ_symbol(underlying, exp, is_put, strike)


def _wheel_request(legacy: dict[str, Any], qty: int) -> OptionOrderRequest:
    symbol = str(legacy.get("symbol") or "").upper()
    action = str(legacy.get("action") or "").upper()
    side = "sell" if "SELL" in action else "buy"
    intent = "sell_to_open" if side == "sell" else "buy_to_open"
    premium = legacy.get("premium") or legacy.get("price")
    return OptionOrderRequest(
        qty=max(int(qty), 1),
        symbol=symbol,
        side=side,
        order_type="limit",
        limit_price=float(premium) if premium is not None else 1.25,
        position_intent=intent,
        reason=str(legacy.get("reason") or "wheel"),
        metadata={
            "strategy": "wheel",
            "stage": legacy.get("strategy_stage"),
            "pin": PIN_COMMIT,
            "strategy_class": "WheelStrategy",
        },
    )


def _spread_request(plan: Any, underlying: str) -> OptionOrderRequest:
    metadata = dict(plan.metadata or {})
    raw_legs = list(metadata.get("legs") or [])
    if not raw_legs:
        raise ExecutionRejected("vertical_spread ActionPlan is missing legs")
    legs = []
    for leg in raw_legs:
        payload = {
            "symbol": _occ_from_leg(underlying, leg),
            "ratio_qty": str(leg.get("ratio") or 1),
            "side": str(leg.get("side") or "").lower(),
            "position_intent": str(leg.get("position_intent") or "").lower(),
        }
        legs.append(payload)
    limit = plan.target_price
    return OptionOrderRequest(
        qty=1,
        order_type="limit",
        limit_price=abs(float(limit)) if limit is not None else 0.85,
        order_class="mleg",
        legs=legs,
        reason=str(plan.reason or "vertical_spread"),
        metadata={
            "strategy": "vertical_spread",
            "spread_type": metadata.get("spread_type"),
            "pin": PIN_COMMIT,
            "strategy_class": "VerticalSpreadStrategy",
            "underlying": underlying,
        },
    )


def build_pin_cycle_plan(
    settings: HackathonSettings,
    *,
    market: PinMarket | None = None,
    dry_run: bool = True,
    underlying_price: float | None = None,
) -> CyclePlan:
    """Call the pin vertical_spread path and map the ActionPlan to an option order."""
    if settings.strategy != "vertical_spread":
        raise ExecutionRejected("only SPY defined-risk vertical is enabled")
    if market is None:
        raise ExecutionRejected("market observation required; live path cannot synthesize fixtures")
    if not dry_run and underlying_price is not None:
        raise ExecutionRejected("live path cannot use a hardcoded underlying price")

    wheel_path = PIN_SRC / "strategy" / "option" / "wheel.py"
    spread_path = PIN_SRC / "strategy" / "option" / "vertical_spread.py"
    if not wheel_path.is_file() or not spread_path.is_file():
        raise RuntimeError("pin option strategies are missing under vendor/pin-31374551")

    underlying = settings.symbols[0]
    loaded = _install_pin_modules(market)
    book = market.book
    now = datetime.now()
    bars = market.bars
    spot = float(market.spot)
    params = {
        "max_stock_price": 10_000.0,
        "min_stock_price": 1.0,
        "position_size_pct": 0.55,
        "dte_min": 7,
        "dte_max": 45,
    }

    if settings.strategy == "vertical_spread":
        strategy = loaded["VerticalSpreadStrategy"](params)
        strategy.symbol_list = [underlying]
        strategy.provider = market.provider
        strategy.fred = market.fred
        snapshot = strategy.get_signal(
            symbol=underlying,
            current_date=now,
            current_price=spot,
            current_data={},
            historical_data=bars,
            portfolio=book,
        )
        if snapshot is None:
            raise ExecutionRejected("vertical_spread returned no signal")
        action_plan = strategy.get_action_plan(snapshot, spot, now)
        if action_plan is None or action_plan.action == "HOLD":
            raise ExecutionRejected(
                f"vertical_spread did not produce an order: {getattr(snapshot, 'reason', '')}"
            )
        request = _spread_request(action_plan, underlying)
        return CyclePlan(
            strategy="vertical_spread",
            request=request,
            underlying=underlying,
            notes=str(action_plan.reason or "vertical_spread"),
            metadata={"pin": PIN_COMMIT, "strategy_class": "VerticalSpreadStrategy"},
        )

    # Dead WheelStrategy branch retained for Gate 4 deletion. Not an execution path.
    strategy = loaded["WheelStrategy"](params)
    strategy.symbol_list = [underlying]
    snapshot = strategy.get_signal(
        symbol=underlying,
        current_date=now,
        current_price=spot,
        current_data={},
        historical_data=bars,
        portfolio=book,
    )
    if snapshot is None:
        raise ExecutionRejected("wheel returned no signal")
    action_plan = strategy.get_action_plan(snapshot, spot, now)
    if action_plan is None or action_plan.action == "HOLD":
        raise ExecutionRejected(
            f"wheel did not produce an order: {getattr(snapshot, 'reason', '')}"
        )
    legacy = (action_plan.metadata or {}).get("legacy_signal") or {}
    qty = max(int(legacy.get("quantity") or 1), 1)
    request = _wheel_request(legacy, min(qty, 1))
    return CyclePlan(
        strategy="wheel",
        request=request,
        underlying=underlying,
        notes=str(action_plan.reason or "wheel"),
        metadata={"pin": PIN_COMMIT, "strategy_class": "WheelStrategy"},
    )
