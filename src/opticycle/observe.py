"""Live SPY market observation via Alpaca read APIs.

alpaca-py is used for read/verify only. This module never submits orders.
Missing or stale data yields NO_TRADE or HALT. Fixtures are never used.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

import pandas as pd

from opticycle.protocol import (
    EvidenceSnapshot,
    ObservationOutcome,
    ObservedDatum,
    OptionContractQuote,
    OptionType,
    OCC_SYMBOL_RE,
    ensure_utc,
)
from opticycle.risk import PortfolioSnapshot
from opticycle.settings import HackathonSettings

MAX_QUOTE_AGE_SECONDS = Decimal("120")
BARS_LIMIT = 60
DEFAULT_EQUITY_FEED = "iex"
ALLOWED_EQUITY_FEEDS = frozenset({"iex", "sip", "delayed_sip"})


class ObservationClosed(Exception):
    """Live observation cannot produce a usable snapshot."""

    def __init__(self, outcome: ObservationOutcome, reason: str) -> None:
        super().__init__(reason)
        self.outcome = outcome
        self.reason = reason


def equity_data_feed() -> str:
    """Paper accounts are entitled to IEX, not SIP. Never default to SIP."""
    raw = (
        os.environ.get("ALPACA_DATA_FEED")
        or os.environ.get("HACKATHON_DATA_FEED")
        or DEFAULT_EQUITY_FEED
    ).strip().lower()
    if raw not in ALLOWED_EQUITY_FEEDS:
        return DEFAULT_EQUITY_FEED
    return raw


def feed_denial_reason(exc: BaseException) -> str | None:
    """SIP/IEX subscription denial is a data error, not a fake or missing quote."""
    text = str(exc).lower()
    if "subscription does not permit" in text or "does not permit querying" in text or "not entitled" in text:
        if "sip" in text:
            return "SIP feed not permitted (data error, not a quote)"
        if "iex" in text:
            return "IEX feed not permitted"
        if "opra" in text:
            return "OPRA feed not permitted"
        return "market data feed not permitted"
    return None


class MarketReadClient(Protocol):
    """Read-only market/account client. Implementations must not submit orders."""

    def fetch_account(self) -> Any: ...
    def fetch_positions(self) -> Any: ...
    def fetch_open_orders(self) -> Any: ...
    def fetch_fills(self) -> Any: ...
    def fetch_clock(self) -> Any: ...
    def fetch_quote(self, symbol: str) -> Any: ...
    def fetch_bars(self, symbol: str) -> Any: ...
    def fetch_option_chain(self, symbol: str) -> Any: ...
    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None) -> Any: ...
    def fetch_orders_by_client_id(self, client_order_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class ObservationResult:
    outcome: ObservationOutcome
    reason: str
    correlation_id: str
    datums: tuple[ObservedDatum, ...]
    evidence: EvidenceSnapshot | None = None
    portfolio: PortfolioSnapshot | None = None
    bars: pd.DataFrame | None = None
    chain: pd.DataFrame | None = None


class AlpacaReadClient:
    """alpaca-py Trading + market-data clients, read/verify only."""

    def __init__(
        self,
        trading: Any,
        stock_data: Any,
        option_data: Any,
        *,
        equity_feed: str | None = None,
    ) -> None:
        self._trading = trading
        self._stock_data = stock_data
        self._option_data = option_data
        self._equity_feed = (equity_feed or equity_data_feed()).strip().lower()
        if self._equity_feed not in ALLOWED_EQUITY_FEEDS:
            self._equity_feed = DEFAULT_EQUITY_FEED

    @classmethod
    def from_env(cls) -> "AlpacaReadClient":
        key = (os.environ.get("ALPACA_API_KEY") or "").strip()
        secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
        if not key or not secret:
            raise ObservationClosed(
                ObservationOutcome.HALT,
                "missing ALPACA_API_KEY or ALPACA_SECRET_KEY",
            )
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        return cls(
            trading=TradingClient(key, secret, paper=True),
            stock_data=StockHistoricalDataClient(key, secret),
            option_data=OptionHistoricalDataClient(key, secret),
            equity_feed=equity_data_feed(),
        )

    def fetch_account(self) -> Any:
        return self._trading.get_account()

    def fetch_positions(self) -> Any:
        return self._trading.get_all_positions()

    def fetch_open_orders(self) -> Any:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        return self._trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True))

    def fetch_fills(self) -> Any:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        return self._trading.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.CLOSED, nested=True, limit=50)
        )

    def fetch_clock(self) -> Any:
        return self._trading.get_clock()

    def fetch_quote(self, symbol: str) -> Any:
        from alpaca.data.enums import DataFeed

        preferred = DataFeed(self._equity_feed)
        try:
            return self._get_stock_latest_quote(symbol, preferred)
        except ObservationClosed:
            raise
        except Exception as exc:
            denial = feed_denial_reason(exc)
            if denial and preferred != DataFeed.IEX:
                try:
                    return self._get_stock_latest_quote(symbol, DataFeed.IEX)
                except Exception as iex_exc:
                    iex_denial = feed_denial_reason(iex_exc)
                    raise ObservationClosed(
                        ObservationOutcome.HALT,
                        iex_denial or "IEX feed not permitted",
                    ) from iex_exc
            if denial:
                raise ObservationClosed(ObservationOutcome.HALT, denial) from exc
            raise

    def _get_stock_latest_quote(self, symbol: str, feed: Any) -> Any:
        from alpaca.data.requests import StockLatestQuoteRequest

        return self._stock_data.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=feed)
        )

    def fetch_bars(self, symbol: str) -> Any:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=120)
        feed = DataFeed(self._equity_feed)
        try:
            return self._stock_data.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TimeFrame.Day,
                    start=start,
                    end=end,
                    limit=BARS_LIMIT,
                    feed=feed,
                )
            )
        except Exception as exc:
            denial = feed_denial_reason(exc)
            if denial and feed != DataFeed.IEX:
                try:
                    return self._stock_data.get_stock_bars(
                        StockBarsRequest(
                            symbol_or_symbols=symbol,
                            timeframe=TimeFrame.Day,
                            start=start,
                            end=end,
                            limit=BARS_LIMIT,
                            feed=DataFeed.IEX,
                        )
                    )
                except Exception as iex_exc:
                    iex_denial = feed_denial_reason(iex_exc)
                    raise ObservationClosed(
                        ObservationOutcome.HALT,
                        iex_denial or "IEX feed not permitted",
                    ) from iex_exc
            if denial:
                raise ObservationClosed(ObservationOutcome.HALT, denial) from exc
            raise

    def fetch_option_chain(self, symbol: str) -> Any:
        from alpaca.data.enums import OptionsFeed
        from alpaca.data.requests import OptionChainRequest

        return self._option_data.get_option_chain(
            OptionChainRequest(underlying_symbol=symbol, feed=OptionsFeed.INDICATIVE)
        )

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None) -> Any:
        if order_id:
            getter = getattr(self._trading, "get_order_by_id", None) or getattr(
                self._trading, "get_order", None
            )
            if getter is None:
                return None
            return getter(order_id)
        if client_order_id:
            getter = getattr(self._trading, "get_order_by_client_id", None) or getattr(
                self._trading, "get_order_by_client_order_id", None
            )
            if getter is None:
                return None
            return getter(client_order_id)
        return None

    def fetch_orders_by_client_id(self, client_order_id: str) -> list[Any]:
        wanted = str(client_order_id or "")
        found: list[Any] = []
        seen: set[str] = set()
        for bucket in (self.fetch_open_orders(), self.fetch_fills()):
            for item in list(bucket or []):
                cid = str(
                    getattr(item, "client_order_id", None)
                    or (item.get("client_order_id") if isinstance(item, dict) else "")
                    or ""
                )
                oid = str(
                    getattr(item, "id", None)
                    or (item.get("id") if isinstance(item, dict) else "")
                    or ""
                )
                if cid != wanted:
                    continue
                key = oid or cid
                if key in seen:
                    continue
                seen.add(key)
                found.append(item)
        return found


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _portfolio_greeks(positions: list[Any]) -> tuple[float | None, float | None, float | None, float | None]:
    """Sum broker position greeks. Empty book is 0. Missing inputs are omitted, not 0."""
    if not positions:
        return 0.0, 0.0, 0.0, 0.0
    totals = {"delta": Decimal("0"), "gamma": Decimal("0"), "theta": Decimal("0"), "vega": Decimal("0")}
    for item in positions:
        getter = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        nested = getter("greeks", None)
        parsed = {
            "delta": _first_decimal(
                getter("delta", None),
                getattr(nested, "delta", None) if nested is not None else None,
                nested.get("delta") if isinstance(nested, dict) else None,
            ),
            "gamma": _first_decimal(
                getter("gamma", None),
                getattr(nested, "gamma", None) if nested is not None else None,
                nested.get("gamma") if isinstance(nested, dict) else None,
            ),
            "theta": _first_decimal(
                getter("theta", None),
                getattr(nested, "theta", None) if nested is not None else None,
                nested.get("theta") if isinstance(nested, dict) else None,
            ),
            "vega": _first_decimal(
                getter("vega", None),
                getattr(nested, "vega", None) if nested is not None else None,
                nested.get("vega") if isinstance(nested, dict) else None,
            ),
        }
        if any(value is None for value in parsed.values()):
            return None, None, None, None
        if all(value == Decimal("0") for value in parsed.values()):
            return None, None, None, None
        for key, value in parsed.items():
            totals[key] += value
    return (
        float(totals["delta"]),
        float(totals["gamma"]),
        float(totals["theta"]),
        float(totals["vega"]),
    )


def _confirmed_paper(account: Any) -> bool | None:
    """True only when the account is confirmed paper. Missing → None (fail-closed)."""
    explicit = getattr(account, "paper", None)
    if explicit is True or explicit is False:
        return explicit
    if explicit is not None:
        text = str(explicit).strip().lower()
        if text in {"true", "1", "paper", "yes"}:
            return True
        if text in {"false", "0", "live", "no"}:
            return False
        return None
    number = str(getattr(account, "account_number", None) or getattr(account, "id", "") or "").strip()
    if not number:
        return None
    return number.startswith("PA")


def _confirmed_options_approved(account: Any) -> bool | None:
    """True only when an options approval level is present and >= 1. Missing → None."""
    raw = getattr(account, "options_approved_level", None)
    if raw is None or str(raw).strip() == "":
        raw = getattr(account, "options_trading_level", None)
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip().lower()
    if text in {"0", "none", "false", "no"}:
        return False
    try:
        return int(float(text)) >= 1
    except (TypeError, ValueError):
        return False


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    if number.is_nan():
        return None
    return number


def _first_decimal(*values: Any) -> Decimal | None:
    for value in values:
        parsed = _as_decimal(value)
        if parsed is not None:
            return parsed
    return None


def _freshness(ts: datetime, now: datetime) -> Decimal:
    delta = ensure_utc(now) - ensure_utc(ts)
    return Decimal(str(max(delta.total_seconds(), 0.0)))


def _quote_from_payload(payload: Any, symbol: str) -> Any:
    if payload is None:
        return None
    if hasattr(payload, "get"):
        return payload.get(symbol) or payload.get(symbol.upper())
    data = getattr(payload, "data", None)
    if isinstance(data, dict):
        return data.get(symbol) or data.get(symbol.upper())
    return payload


def _bars_frame(payload: Any, symbol: str) -> pd.DataFrame:
    rows = []
    data = payload
    if hasattr(payload, "data"):
        data = payload.data
    series = None
    if isinstance(data, dict):
        series = data.get(symbol) or data.get(symbol.upper())
    elif isinstance(data, list):
        series = data
    if series is None:
        return pd.DataFrame()
    for bar in series:
        rows.append(
            {
                "open": float(getattr(bar, "open", None) or 0),
                "high": float(getattr(bar, "high", None) or 0),
                "low": float(getattr(bar, "low", None) or 0),
                "close": float(getattr(bar, "close", None) or 0),
                "volume": float(getattr(bar, "volume", None) or 0),
                "timestamp": getattr(bar, "timestamp", None),
            }
        )
    return pd.DataFrame(rows)


def _parse_occ(symbol: str) -> tuple[str, datetime, str, Decimal] | None:
    if not OCC_SYMBOL_RE.fullmatch(symbol):
        return None
    root = symbol[:-15]
    yymmdd = symbol[-15:-9]
    kind = symbol[-9]
    strike_raw = symbol[-8:]
    expiration = datetime.strptime(yymmdd, "%y%m%d").replace(tzinfo=timezone.utc)
    strike = Decimal(strike_raw) / Decimal("1000")
    return root, expiration, kind, strike


def _chain_from_payload(payload: Any, underlying: str) -> tuple[pd.DataFrame, tuple[OptionContractQuote, ...]]:
    items: list[tuple[str, Any]] = []
    data = getattr(payload, "data", payload)
    if isinstance(data, dict):
        items = list(data.items())
    elif isinstance(data, list):
        items = [(getattr(item, "symbol", ""), item) for item in data]
    rows: list[dict[str, Any]] = []
    quotes: list[OptionContractQuote] = []
    for symbol, snap in items:
        occ = _parse_occ(str(symbol).upper())
        if occ is None:
            continue
        root, expiration, kind, strike = occ
        latest = getattr(snap, "latest_quote", None) or snap
        trade = getattr(snap, "latest_trade", None)
        greeks = getattr(snap, "greeks", None)
        bid = _as_decimal(getattr(latest, "bid_price", None) or getattr(snap, "bid_price", None)) or Decimal("0")
        ask = _as_decimal(getattr(latest, "ask_price", None) or getattr(snap, "ask_price", None)) or Decimal("0")
        last = _as_decimal(getattr(trade, "price", None) or getattr(snap, "last_price", None)) or Decimal("0")
        quote_ts = getattr(latest, "timestamp", None) or getattr(snap, "timestamp", None)
        if not isinstance(quote_ts, datetime):
            quote_ts = None
        delta = _first_decimal(
            getattr(greeks, "delta", None) if greeks is not None else None,
            getattr(snap, "delta", None),
        )
        gamma = _first_decimal(
            getattr(greeks, "gamma", None) if greeks is not None else None,
            getattr(snap, "gamma", None),
        )
        theta = _first_decimal(
            getattr(greeks, "theta", None) if greeks is not None else None,
            getattr(snap, "theta", None),
        )
        vega = _first_decimal(
            getattr(greeks, "vega", None) if greeks is not None else None,
            getattr(snap, "vega", None),
        )
        iv = _first_decimal(
            getattr(snap, "implied_volatility", None),
            getattr(greeks, "implied_volatility", None) if greeks is not None else None,
        )
        option_type = OptionType.PUT if kind == "P" else OptionType.CALL
        rows.append(
            {
                "symbol": str(symbol).upper(),
                "underlying_symbol": underlying,
                "option_type": kind,
                "strike_price": float(strike),
                "expiration_date": pd.Timestamp(expiration.date()),
                "bid_price": float(bid),
                "ask_price": float(ask),
                "last_price": float(last),
                "bid": float(bid),
                "ask": float(ask),
                "delta": float(delta) if delta is not None else None,
                "gamma": float(gamma) if gamma is not None else None,
                "theta": float(theta) if theta is not None else None,
                "vega": float(vega) if vega is not None else None,
                "implied_volatility": float(iv) if iv is not None else None,
                "quote_timestamp": quote_ts,
                "volume": int(getattr(snap, "volume", 0) or 0),
                "open_interest": int(getattr(snap, "open_interest", 0) or 0),
            }
        )
        try:
            quotes.append(
                OptionContractQuote(
                    symbol=str(symbol).upper(),
                    underlying=root or underlying,
                    option_type=option_type,
                    strike_price=strike,
                    expiration=expiration,
                    bid=bid,
                    ask=ask,
                    last=last,
                    delta=delta,
                    gamma=gamma,
                    theta=theta,
                    vega=vega,
                    quote_timestamp=quote_ts,
                    implied_volatility=iv,
                )
            )
        except ValueError:
            continue
    return pd.DataFrame(rows), tuple(quotes)


def _datum(
    kind: str,
    source: str,
    correlation_id: str,
    *,
    ok: bool,
    timestamp: datetime | None = None,
    freshness_seconds: Decimal = Decimal("0"),
    detail: str = "",
) -> ObservedDatum:
    return ObservedDatum(
        kind=kind,
        source=source,
        timestamp=timestamp or _now(),
        freshness_seconds=freshness_seconds,
        correlation_id=correlation_id,
        ok=ok,
        detail=detail,
    )


def _closed(
    outcome: ObservationOutcome,
    reason: str,
    correlation_id: str,
    datums: list[ObservedDatum],
) -> ObservationResult:
    return ObservationResult(
        outcome=outcome,
        reason=reason,
        correlation_id=correlation_id,
        datums=tuple(datums),
    )


def observe_live(
    settings: HackathonSettings,
    client: MarketReadClient | None = None,
    *,
    now: datetime | None = None,
) -> ObservationResult:
    """Fetch a live evidence snapshot. Never falls back to fixtures."""

    correlation_id = uuid.uuid4().hex
    clock_now = ensure_utc(now or _now())
    datums: list[ObservedDatum] = []
    underlying = settings.symbols[0] if settings.symbols else "SPY"

    if client is None:
        try:
            client = AlpacaReadClient.from_env()
        except ObservationClosed as exc:
            datums.append(
                _datum(
                    "credentials",
                    "env",
                    correlation_id,
                    ok=False,
                    timestamp=clock_now,
                    detail=exc.reason,
                )
            )
            return _closed(exc.outcome, exc.reason, correlation_id, datums)

    def _call(kind: str, source: str, fn: Any) -> Any:
        try:
            value = fn()
        except ObservationClosed:
            raise
        except Exception as exc:
            denial = feed_denial_reason(exc)
            if denial:
                datums.append(
                    _datum(kind, source, correlation_id, ok=False, timestamp=clock_now, detail=denial)
                )
                raise ObservationClosed(ObservationOutcome.HALT, denial) from exc
            datums.append(
                _datum(kind, source, correlation_id, ok=False, timestamp=clock_now, detail=type(exc).__name__)
            )
            raise ObservationClosed(ObservationOutcome.HALT, f"offline or {kind} read failed") from exc
        datums.append(_datum(kind, source, correlation_id, ok=True, timestamp=clock_now))
        return value

    try:
        account = _call("account", "alpaca.trading.get_account", client.fetch_account)
        positions = _call("positions", "alpaca.trading.get_all_positions", client.fetch_positions)
        open_orders = _call("open_orders", "alpaca.trading.get_orders", client.fetch_open_orders)
        fills = _call("fills", "alpaca.trading.get_orders", client.fetch_fills)
        clock = _call("clock", "alpaca.trading.get_clock", client.fetch_clock)
        quote_payload = _call(
            "quote",
            "alpaca.data.get_stock_latest_quote",
            lambda: client.fetch_quote(underlying),
        )
        bars_payload = _call(
            "bars",
            "alpaca.data.get_stock_bars",
            lambda: client.fetch_bars(underlying),
        )
        chain_payload = _call(
            "option_chain",
            "alpaca.data.get_option_chain",
            lambda: client.fetch_option_chain(underlying),
        )
    except ObservationClosed as exc:
        return _closed(exc.outcome, exc.reason, correlation_id, datums)

    if account is None:
        datums.append(_datum("account", "alpaca.trading.get_account", correlation_id, ok=False, detail="missing"))
        return _closed(ObservationOutcome.HALT, "account snapshot missing", correlation_id, datums)

    equity = _as_decimal(getattr(account, "equity", None))
    buying_power = _as_decimal(getattr(account, "buying_power", None))
    cash = _as_decimal(getattr(account, "cash", None))
    account_id = str(getattr(account, "id", None) or getattr(account, "account_number", "") or "")
    if equity is None or buying_power is None or cash is None or not account_id:
        datums.append(_datum("account", "alpaca.trading.get_account", correlation_id, ok=False, detail="incomplete"))
        return _closed(ObservationOutcome.HALT, "account equity or buying power missing", correlation_id, datums)

    quote = _quote_from_payload(quote_payload, underlying)
    if quote is None:
        datums.append(_datum("quote", "alpaca.data.get_stock_latest_quote", correlation_id, ok=False, detail="missing"))
        return _closed(ObservationOutcome.NO_TRADE, "SPY quote missing", correlation_id, datums)

    bid = _as_decimal(getattr(quote, "bid_price", None))
    ask = _as_decimal(getattr(quote, "ask_price", None))
    trade_price = _as_decimal(getattr(quote, "last", None) or getattr(quote, "price", None))
    if bid and ask and bid > 0 and ask > 0:
        spot = (bid + ask) / Decimal("2")
    elif trade_price and trade_price > 0:
        spot = trade_price
    elif ask and ask > 0:
        spot = ask
    elif bid and bid > 0:
        spot = bid
    else:
        datums.append(_datum("quote", "alpaca.data.get_stock_latest_quote", correlation_id, ok=False, detail="no price"))
        return _closed(ObservationOutcome.NO_TRADE, "SPY quote missing", correlation_id, datums)

    quote_ts = getattr(quote, "timestamp", None)
    if not isinstance(quote_ts, datetime):
        datums.append(
            _datum(
                "quote",
                "alpaca.data.get_stock_latest_quote",
                correlation_id,
                ok=False,
                timestamp=clock_now,
                detail="timestamp missing",
            )
        )
        return _closed(ObservationOutcome.NO_TRADE, "SPY quote timestamp missing", correlation_id, datums)
    quote_age = _freshness(quote_ts, clock_now)
    datums.append(
        _datum(
            "quote",
            "alpaca.data.get_stock_latest_quote",
            correlation_id,
            ok=True,
            timestamp=quote_ts,
            freshness_seconds=quote_age,
        )
    )
    if quote_age > MAX_QUOTE_AGE_SECONDS:
        return _closed(ObservationOutcome.NO_TRADE, "SPY quote is stale", correlation_id, datums)

    bars = _bars_frame(bars_payload, underlying)
    if bars.empty:
        datums.append(_datum("bars", "alpaca.data.get_stock_bars", correlation_id, ok=False, detail="empty"))
        return _closed(ObservationOutcome.NO_TRADE, "SPY bars missing", correlation_id, datums)

    chain, chain_quotes = _chain_from_payload(chain_payload, underlying)
    if chain.empty or not chain_quotes:
        datums.append(_datum("option_chain", "alpaca.data.get_option_chain", correlation_id, ok=False, detail="empty"))
        return _closed(ObservationOutcome.NO_TRADE, "SPY option chain missing", correlation_id, datums)

    position_list = list(positions or [])
    open_list = list(open_orders or [])
    fill_list = list(fills or [])
    _ = fill_list  # recorded as datum; fills used by later gates
    paper_flag = _confirmed_paper(account)
    options_flag = _confirmed_options_approved(account)
    if paper_flag is not True:
        datums.append(_datum("account", "alpaca.trading.get_account", correlation_id, ok=False, detail="paper not confirmed"))
        return _closed(ObservationOutcome.HALT, "paper account not confirmed", correlation_id, datums)
    if options_flag is not True:
        datums.append(_datum("account", "alpaca.trading.get_account", correlation_id, ok=False, detail="options approval missing"))
        return _closed(ObservationOutcome.HALT, "options approval missing or not confirmed", correlation_id, datums)

    net_delta, net_gamma, net_theta, net_vega = _portfolio_greeks(position_list)
    portfolio = PortfolioSnapshot(
        equity=float(equity),
        buying_power=float(buying_power),
        cash=float(cash),
        account_id=account_id,
        paper=True,
        options_approved=True,
        trades_today=int(getattr(account, "daytrade_count", 0) or 0),
        open_positions=len(position_list),
        net_delta=net_delta,
        net_vega=net_vega,
        net_gamma=net_gamma,
        net_theta=net_theta,
        positions=[{"symbol": getattr(item, "symbol", "")} for item in position_list],
    )
    if open_list:
        portfolio.trades_today = max(portfolio.trades_today, len(open_list))

    clock_open = bool(getattr(clock, "is_open", False))
    bar_closes: list[Decimal] = []
    if not bars.empty and "close" in bars.columns:
        for value in bars["close"].tolist():
            parsed = _as_decimal(value)
            if parsed is not None and parsed > 0:
                bar_closes.append(parsed)
    last_price = trade_price if trade_price and trade_price > 0 else spot
    evidence = EvidenceSnapshot(
        underlying=underlying,
        spot_price=spot,
        timestamp=clock_now,
        bars_count=int(len(bars)),
        quote_age_seconds=quote_age,
        is_fresh=True,
        chain_quotes=chain_quotes,
        indicators=(("clock_open", Decimal("1") if clock_open else Decimal("0")),),
        datums=tuple(datums),
        correlation_id=correlation_id,
        account_id=account_id,
        bid=bid if bid and bid > 0 else None,
        ask=ask if ask and ask > 0 else None,
        last=last_price if last_price and last_price > 0 else None,
        quote_timestamp=quote_ts,
        bar_closes=tuple(bar_closes),
    )
    return ObservationResult(
        outcome=ObservationOutcome.OK,
        reason="live observation complete",
        correlation_id=correlation_id,
        datums=tuple(datums),
        evidence=evidence,
        portfolio=portfolio,
        bars=bars,
        chain=chain,
    )
