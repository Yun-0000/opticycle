"""Load wheel / vertical_spread from vendor/pin-31374551 and turn ActionPlans into orders."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from opticycle.plans import CyclePlan, occ_symbol
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected, OptionOrderRequest

PIN_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "pin-31374551"
PIN_SRC = PIN_ROOT / "src"
PIN_COMMIT = "31374551"


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


def _has_alpaca_keys() -> bool:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    return bool(key and secret)


class _PaperBook:
    """Minimal book the pin wheel sizer expects."""

    positions: dict[str, Any] = {}
    option_positions: dict[str, Any] = {}

    def __init__(self, equity: float = 100_000.0) -> None:
        self.equity = equity

    def get_portfolio_value(self, _prices: Any = None) -> float:
        return float(self.equity)

    def get_available_cash(self) -> float:
        return float(self.equity)


class _FixtureAlpaca:
    def __init__(self, chain: pd.DataFrame) -> None:
        self._chain = chain

    def get_options_chain(self, _symbol: str) -> pd.DataFrame:
        return self._chain.copy()


class _FixtureFred:
    def get_treasury_yield(self, _maturity: str = "3M") -> pd.DataFrame:
        return pd.DataFrame({"value": [4.0]})


def _demo_expiration(days: int = 21) -> date:
    target = date.today() + timedelta(days=days)
    while target.weekday() != 4:
        target += timedelta(days=1)
    return target


def _historical_bars(spot: float, rows: int = 60) -> pd.DataFrame:
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


def _chain_frame(
    underlying: str,
    spot: float,
    expiration: date,
    bs_price: Any,
) -> pd.DataFrame:
    t_years = max((expiration - date.today()).days, 1) / 365.0
    rate = 0.04
    vol = 0.70
    rows: list[dict[str, Any]] = []
    strikes = [round(spot * factor, 0) for factor in (
        0.90, 0.93, 0.95, 0.97, 0.99, 1.00, 1.01, 1.03, 1.05, 1.07, 1.10
    )]
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
            delta = 0.22 if kind == "P" else 0.22
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
                    "volume": 500,
                    "open_interest": 2_000,
                }
            )
    return pd.DataFrame(rows)


def _install_pin_modules(*, live_data: bool, chain: pd.DataFrame) -> dict[str, Any]:
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

    fixture = _FixtureAlpaca(chain)
    fred = _FixtureFred()
    if live_data:
        alpaca_mod = _load_file(
            "src.data.alpaca_provider", PIN_SRC / "data" / "alpaca_provider.py"
        )
        provider_cls = alpaca_mod.AlpacaDataProvider
    else:
        alpaca_mod = types.ModuleType("src.data.alpaca_provider")
        alpaca_mod.AlpacaDataProvider = lambda: fixture
        sys.modules["src.data.alpaca_provider"] = alpaca_mod
        provider_cls = alpaca_mod.AlpacaDataProvider

    fred_mod = types.ModuleType("src.data.fred_provider")
    fred_mod.FREDProvider = lambda: fred
    sys.modules["src.data.fred_provider"] = fred_mod

    data_pkg = sys.modules["src.data"]
    data_pkg.AlpacaDataProvider = provider_cls

    wheel_mod = _load_file("src.strategy.option.wheel", PIN_SRC / "strategy" / "option" / "wheel.py")
    spread_mod = _load_file(
        "src.strategy.option.vertical_spread",
        PIN_SRC / "strategy" / "option" / "vertical_spread.py",
    )
    return {
        "WheelStrategy": wheel_mod.WheelStrategy,
        "VerticalSpreadStrategy": spread_mod.VerticalSpreadStrategy,
        "fixture_provider": fixture,
        "bs_price": sys.modules["src.analysis.option_greeks"].bs_price,
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
    underlying_price: float = 500.0,
    dry_run: bool = True,
) -> CyclePlan:
    """Call the pin vertical_spread path and map the ActionPlan to an option order."""
    if settings.strategy != "vertical_spread":
        raise ExecutionRejected("only SPY defined-risk vertical is enabled")
    wheel_path = PIN_SRC / "strategy" / "option" / "wheel.py"
    spread_path = PIN_SRC / "strategy" / "option" / "vertical_spread.py"
    if not wheel_path.is_file() or not spread_path.is_file():
        raise RuntimeError("pin option strategies are missing under vendor/pin-31374551")

    underlying = settings.symbols[0]
    expiration = _demo_expiration(days=14)
    live_data = (not dry_run) and _has_alpaca_keys()
    greeks_spec = importlib.util.spec_from_file_location(
        "_pin_bs_bootstrap", PIN_SRC / "analysis" / "option_greeks.py"
    )
    if greeks_spec is None or greeks_spec.loader is None:
        raise RuntimeError("pin option_greeks is missing")
    bootstrap = importlib.util.module_from_spec(greeks_spec)
    greeks_spec.loader.exec_module(bootstrap)
    chain = _chain_frame(underlying, underlying_price, expiration, bootstrap.bs_price)
    loaded = _install_pin_modules(live_data=live_data, chain=chain)

    book = _PaperBook(settings.starting_capital)
    now = datetime.now()
    bars = _historical_bars(underlying_price)
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
        if not live_data:
            strategy.provider = loaded["fixture_provider"]
            strategy.fred = _FixtureFred()
        snapshot = strategy.get_signal(
            symbol=underlying,
            current_date=now,
            current_price=underlying_price,
            current_data={},
            historical_data=bars,
            portfolio=book,
        )
        if snapshot is None:
            raise ExecutionRejected("vertical_spread returned no signal")
        action_plan = strategy.get_action_plan(snapshot, underlying_price, now)
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

    strategy = loaded["WheelStrategy"](params)
    strategy.symbol_list = [underlying]
    snapshot = strategy.get_signal(
        symbol=underlying,
        current_date=now,
        current_price=underlying_price,
        current_data={},
        historical_data=bars,
        portfolio=book,
    )
    if snapshot is None:
        raise ExecutionRejected("wheel returned no signal")
    action_plan = strategy.get_action_plan(snapshot, underlying_price, now)
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
