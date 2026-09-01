"""Load vertical_spread from vendor/pin-31374551 and turn ActionPlans into orders."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from decimal import Decimal, ROUND_FLOOR
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
    if limit is None:
        raise ExecutionRejected("NO_TRADE: missing market-derived limit price")
    signed_limit = float(limit)
    if spread_type in ALLOWED_CREDIT_SPREADS and signed_limit >= 0:
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
        reason=str(plan.reason or "vertical_spread"),
        metadata={
            "strategy": "vertical_spread",
            "spread_type": spread_type,
            "pin": PIN_COMMIT,
            "strategy_class": "VerticalSpreadStrategy",
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
    """Size one vertical from equity risk, aggregate-risk, and contract caps."""
    equity = Decimal(str(getattr(portfolio, "equity", 0) or 0))
    existing_risk = Decimal(str(getattr(portfolio, "open_risk", 0) or 0))
    opened_today = int(getattr(portfolio, "contracts_opened_today", 0) or 0)
    open_contracts = int(getattr(portfolio, "open_contracts", 0) or 0)
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
    daily_capacity = max(settings.max_new_contracts_per_day - opened_today, 0)
    open_capacity = max(settings.max_open_contracts - open_contracts, 0)
    qty = min(risk_qty, daily_capacity, open_capacity)
    if qty <= 0:
        raise ExecutionRejected(
            "NO_TRADE: risk budget or daily/open contract capacity is exhausted"
        )
    request.qty = qty
    request.metadata.update(
        {
            "sizing": "equity_risk_budget",
            "risk_per_trade_pct": str(settings.risk_per_trade_pct),
            "max_total_risk_pct": str(settings.max_total_risk_pct),
            "per_contract_max_loss": str(per_contract),
            "risk_budget": str(risk_budget.quantize(Decimal("0.01"))),
            "opened_today_before": opened_today,
            "open_contracts_before": open_contracts,
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


def _credit_candidate_for_type(strategy: Any, market: PinMarket, underlying: str, spread_type: str) -> Any:
    """Select one exact-width credit vertical from observed quotes and delta."""
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
    today = datetime.now(ZoneInfo("America/New_York")).date()
    chain["dte"] = chain["expiration"].apply(lambda exp: (exp - today).days)
    chain = chain[(chain["dte"] >= dte_min) & (chain["dte"] <= dte_max)]
    if chain.empty:
        raise ExecutionRejected("NO_TRADE: no contracts in DTE window")
    chain["option_type"] = chain["option_type"].astype(str).str.upper().str[0]
    kind = "P" if spread_type == "bull_put" else "C"
    chain = chain[chain["option_type"] == kind]
    if chain.empty:
        raise ExecutionRejected(f"NO_TRADE: no {spread_type} contracts in DTE window")

    width = Decimal(str(strategy.params["spread_width"]))
    delta_min = Decimal(str(strategy.params["short_delta_min"]))
    delta_max = Decimal(str(strategy.params["short_delta_max"]))
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
        long_strike = short_strike - width if spread_type == "bull_put" else short_strike + width
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
        score = (credit / max_loss) - (abs(short_delta - Decimal("0.25")) / Decimal("100"))
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
                    "max_loss": float(max_loss),
                    "reason": (
                        f"{spread_type} ${width:g} wide, short delta {short_delta:.2f}, "
                        f"{dte} DTE, credit {credit:.2f}"
                    ),
                },
            )
        )
    if not candidates:
        raise ExecutionRejected(f"NO_TRADE: no {spread_type} credit vertical available")
    selected = max(candidates, key=lambda item: item[0])[1]
    return types.SimpleNamespace(
        spread_type=spread_type,
        action="SELL_TO_OPEN",
        **selected,
    )


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
        "dte_min": settings.min_dte,
        "dte_max": settings.max_dte,
        "iv_min_credit": 0.10,
        "short_delta_min": settings.short_delta_min,
        "short_delta_max": settings.short_delta_max,
        "spread_width": settings.spread_width,
        "credit_min_pct": 0.05,
        "credit_max_pct": 0.90,
        "width_pct": settings.spread_width / market.spot,
        "otm_pct": 0.03,
    }

    strategy = loaded["VerticalSpreadStrategy"](params)
    strategy.symbol_list = [underlying]
    strategy.provider = market.provider
    strategy.fred = market.fred
    candidate = _credit_candidate_for_type(strategy, market, underlying, spread_type)
    raw_legs = list((candidate.metadata or {}).get("legs") or [])
    if len(raw_legs) != 2:
        raise ExecutionRejected("NO_TRADE: selected vertical is missing legs")
    selected_width = abs(
        Decimal(str(raw_legs[0].get("strike"))) - Decimal(str(raw_legs[1].get("strike")))
    )
    if selected_width != Decimal(str(settings.spread_width)):
        raise ExecutionRejected(
            f"NO_TRADE: no exact ${settings.spread_width:g}-wide vertical available"
        )
    action_plan = types.SimpleNamespace(
        metadata=candidate.metadata,
        target_price=float(candidate.limit_price),
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
