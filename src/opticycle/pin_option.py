"""Load vertical_spread from vendor/pin-31374551 and turn ActionPlans into orders."""

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
from opticycle.protocol import ThesisStance
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected, OptionOrderRequest

ALLOWED_CREDIT_SPREADS = frozenset({"bull_put", "bear_call"})
FORBIDDEN_DEBIT_SPREADS = frozenset({"bull_call", "bear_put"})
STANCE_TO_CREDIT = {
    ThesisStance.BULLISH: "bull_put",
    ThesisStance.BEARISH: "bear_call",
}

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

    spread_mod = _load_file(
        "src.strategy.option.vertical_spread",
        PIN_SRC / "strategy" / "option" / "vertical_spread.py",
    )
    return {"VerticalSpreadStrategy": spread_mod.VerticalSpreadStrategy}


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


def _spread_request(plan: Any, underlying: str) -> OptionOrderRequest:
    metadata = dict(plan.metadata or {})
    spread_type = str(metadata.get("spread_type") or "")
    if spread_type in FORBIDDEN_DEBIT_SPREADS:
        raise ExecutionRejected(f"NO_TRADE: {spread_type} debit verticals are disabled")
    if spread_type not in ALLOWED_CREDIT_SPREADS:
        raise ExecutionRejected(f"NO_TRADE: {spread_type or 'unknown'} is not an allowed credit vertical")
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
            "spread_type": spread_type,
            "pin": PIN_COMMIT,
            "strategy_class": "VerticalSpreadStrategy",
            "underlying": underlying,
        },
    )


def _normalize_stance(stance: ThesisStance | str | None) -> ThesisStance | None:
    if stance is None:
        return None
    if isinstance(stance, ThesisStance):
        return stance
    try:
        return ThesisStance(str(stance).strip().upper())
    except ValueError:
        return None


def _credit_candidate_for_type(strategy: Any, market: PinMarket, underlying: str, spread_type: str) -> Any:
    """Ask the pin constructor for one credit type only. Never uses RSI/trend get_signal."""
    if spread_type in FORBIDDEN_DEBIT_SPREADS:
        raise ExecutionRejected(f"NO_TRADE: {spread_type} debit verticals are disabled")
    if spread_type not in ALLOWED_CREDIT_SPREADS:
        raise ExecutionRejected(f"NO_TRADE: {spread_type} is not an allowed credit vertical")
    chain = strategy.provider.get_options_chain(underlying)
    if chain is None or getattr(chain, "empty", True):
        raise ExecutionRejected("NO_TRADE: option chain missing")
    required_cols = {"expiration_date", "strike_price", "option_type"}
    if not required_cols.issubset(chain.columns):
        raise ExecutionRejected("NO_TRADE: option chain missing required columns")
    chain = chain.copy()
    chain["expiration"] = chain["expiration_date"].apply(strategy._parse_expiration)
    chain = chain[chain["expiration"].notna()]
    if chain.empty:
        raise ExecutionRejected("NO_TRADE: no usable expirations")
    dte_min = int(strategy.params["dte_min"])
    dte_max = int(strategy.params["dte_max"])
    today = datetime.now().date()
    chain["dte"] = chain["expiration"].apply(lambda exp: (exp - today).days)
    chain = chain[(chain["dte"] >= dte_min) & (chain["dte"] <= dte_max)]
    if chain.empty:
        raise ExecutionRejected("NO_TRADE: no contracts in DTE window")
    chain["option_type"] = chain["option_type"].astype(str).str.upper()
    expirations = sorted(chain["expiration"].unique())
    candidate = strategy._best_candidate_for_type(
        chain,
        expirations,
        float(market.spot),
        underlying,
        spread_type,
    )
    if candidate is None:
        raise ExecutionRejected(f"NO_TRADE: no {spread_type} credit vertical available")
    if candidate.spread_type != spread_type or candidate.spread_type not in ALLOWED_CREDIT_SPREADS:
        raise ExecutionRejected("NO_TRADE: constructed spread does not match thesis stance")
    return candidate


def build_pin_cycle_plan(
    settings: HackathonSettings,
    *,
    market: PinMarket | None = None,
    dry_run: bool = True,
    underlying_price: float | None = None,
    stance: ThesisStance | str | None = None,
) -> CyclePlan:
    """Construct the credit vertical required by thesis stance. No RSI/trend selection."""
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

    spread_path = PIN_SRC / "strategy" / "option" / "vertical_spread.py"
    if not spread_path.is_file():
        raise RuntimeError("pin vertical_spread is missing under vendor/pin-31374551")

    underlying = settings.symbols[0]
    loaded = _install_pin_modules(market)
    params = {
        "max_stock_price": 10_000.0,
        "min_stock_price": 1.0,
        "position_size_pct": 0.55,
        "dte_min": 7,
        "dte_max": 45,
        "iv_min_credit": 0.10,
        "short_delta_min": 0.05,
        "short_delta_max": 0.80,
        "credit_min_pct": 0.05,
        "credit_max_pct": 0.90,
        "width_pct": 0.02,
        "otm_pct": 0.03,
    }

    strategy = loaded["VerticalSpreadStrategy"](params)
    strategy.symbol_list = [underlying]
    strategy.provider = market.provider
    strategy.fred = market.fred
    candidate = _credit_candidate_for_type(strategy, market, underlying, spread_type)
    action_plan = types.SimpleNamespace(
        metadata=candidate.metadata,
        target_price=abs(float(candidate.limit_price)),
        reason=candidate.reason,
        action=candidate.action,
    )
    request = _spread_request(action_plan, underlying)
    return CyclePlan(
        strategy="vertical_spread",
        request=request,
        underlying=underlying,
        notes=str(action_plan.reason or spread_type),
        metadata={
            "pin": PIN_COMMIT,
            "strategy_class": "VerticalSpreadStrategy",
            "spread_type": spread_type,
            "stance": resolved.value,
        },
    )
