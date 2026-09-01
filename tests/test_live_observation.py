"""Gate 3: live observation is fail-closed and never uses fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from opticycle.observe import (
    MAX_QUOTE_AGE_SECONDS,
    AlpacaReadClient,
    ObservationClosed,
    equity_data_feed,
    feed_denial_reason,
    observe_live,
)
from opticycle.protocol import ObservationOutcome
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings


class _OfflineClient:
    def fetch_account(self):
        raise ConnectionError("simulated offline")

    def fetch_positions(self):
        raise ConnectionError("simulated offline")

    def fetch_open_orders(self):
        raise ConnectionError("simulated offline")

    def fetch_fills(self):
        raise ConnectionError("simulated offline")

    def fetch_clock(self):
        raise ConnectionError("simulated offline")

    def fetch_quote(self, symbol: str):
        raise ConnectionError("simulated offline")

    def fetch_bars(self, symbol: str):
        raise ConnectionError("simulated offline")

    def fetch_option_chain(self, symbol: str):
        raise ConnectionError("simulated offline")

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None):
        raise ConnectionError("simulated offline")

    def fetch_orders_by_client_id(self, client_order_id: str):
        raise ConnectionError("simulated offline")


class _PartialClient:
    def __init__(self, *, account=None, quote=None, bars=None, chain=None) -> None:
        self.account = account
        self.quote = quote
        self.bars = bars
        self.chain = chain

    def fetch_account(self):
        return self.account

    def fetch_positions(self):
        return []

    def fetch_open_orders(self):
        return []

    def fetch_fills(self):
        return []

    def fetch_clock(self):
        return SimpleNamespace(is_open=True, timestamp=datetime.now(timezone.utc))

    def fetch_quote(self, symbol: str):
        return self.quote

    def fetch_bars(self, symbol: str):
        return self.bars if self.bars is not None else {"SPY": []}

    def fetch_option_chain(self, symbol: str):
        return self.chain if self.chain is not None else {}

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None):
        return None

    def fetch_orders_by_client_id(self, client_order_id: str):
        return []


def _account(**kwargs):
    payload = dict(
        id="PA3V84C40PJQ",
        account_number="PA3V84C40PJQ",
        equity="100000",
        buying_power="100000",
        cash="100000",
        daytrade_count=0,
        options_approved_level="2",
    )
    payload.update(kwargs)
    return SimpleNamespace(**payload)


def test_paper_account_id_prefers_pa_account_number_over_uuid() -> None:
    from opticycle.observe import paper_account_id

    account = _account(id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", account_number="PA3V84C40PJQ")
    assert paper_account_id(account) == "PA3V84C40PJQ"
    now = datetime.now(timezone.utc)
    bars = [
        SimpleNamespace(open=499, high=501, low=498, close=500, volume=1_000_000, timestamp=now)
        for _ in range(20)
    ]
    chain_quote = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=1.2, ask_price=1.4, timestamp=now),
        latest_trade=SimpleNamespace(price=1.3),
        greeks=SimpleNamespace(delta=-0.20, gamma=0.01, theta=-0.04, vega=0.08),
    )
    result = observe_live(
        HackathonSettings(),
        client=_PartialClient(
            account=account,
            quote={"SPY": SimpleNamespace(bid_price=500.0, ask_price=500.2, timestamp=now)},
            bars={"SPY": bars},
            chain={"SPY260918P00500000": chain_quote, "SPY260918P00490000": chain_quote},
        ),
    )
    assert result.outcome == ObservationOutcome.OK
    assert result.portfolio is not None
    assert result.portfolio.account_id == "PA3V84C40PJQ"


def test_live_observe_missing_account_is_halt() -> None:
    result = observe_live(HackathonSettings(), client=_PartialClient(account=None, quote={"SPY": object()}))
    assert result.outcome == ObservationOutcome.HALT
    assert result.evidence is None
    assert "account" in result.reason


def test_live_observe_missing_quote_is_no_trade() -> None:
    result = observe_live(
        HackathonSettings(),
        client=_PartialClient(account=_account(), quote=None),
    )
    assert result.outcome == ObservationOutcome.NO_TRADE
    assert result.evidence is None
    assert "quote" in result.reason


def test_live_observe_offline_is_halt() -> None:
    result = observe_live(HackathonSettings(), client=_OfflineClient())
    assert result.outcome == ObservationOutcome.HALT
    assert result.evidence is None
    assert "offline" in result.reason


def test_live_run_once_missing_quote_does_not_submit() -> None:
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=_PartialClient(account=_account(), quote=None),
    )
    assert result["ok"] is False
    assert result["outcome"] == "NO_TRADE"
    assert result["order"] is None


def test_live_run_once_missing_account_does_not_submit() -> None:
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=_PartialClient(account=None),
    )
    assert result["ok"] is False
    assert result["outcome"] == "HALT"
    assert result["order"] is None


def test_live_run_once_offline_does_not_submit() -> None:
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=_OfflineClient(),
    )
    assert result["ok"] is False
    assert result["outcome"] == "HALT"
    assert result["order"] is None


def test_live_run_once_rejects_fixture_market() -> None:
    from tests.fixtures.market import make_pin_market

    with pytest.raises(Exception, match="fixture market"):
        run_once(HackathonSettings(), dry_run=False, market=make_pin_market())


def test_live_run_once_rejects_hardcoded_price() -> None:
    with pytest.raises(Exception, match="hardcoded"):
        run_once(HackathonSettings(), dry_run=False, underlying_price=500.0)


def test_observe_live_without_keys_does_not_invent_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    result = observe_live(HackathonSettings(), client=None)
    assert result.outcome == ObservationOutcome.HALT
    assert result.evidence is None


def test_datums_carry_provenance() -> None:
    quote = SimpleNamespace(
        bid_price=500.0,
        ask_price=500.2,
        timestamp=datetime.now(timezone.utc),
    )
    bar = SimpleNamespace(open=499, high=501, low=498, close=500, volume=1_000_000, timestamp=datetime.now(timezone.utc))
    chain_quote = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=1.2, ask_price=1.4),
        latest_trade=SimpleNamespace(price=1.3),
        greeks=SimpleNamespace(delta=-0.2, gamma=0.01, theta=-0.05, vega=0.1),
    )
    client = _PartialClient(
        account=_account(),
        quote={"SPY": quote},
        bars={"SPY": [bar]},
        chain={"SPY260918P00500000": chain_quote},
    )
    result = observe_live(HackathonSettings(), client=client)
    assert result.outcome == ObservationOutcome.OK
    assert result.evidence is not None
    assert result.evidence.correlation_id
    kinds = {datum.kind for datum in result.datums}
    assert {"account", "quote", "bars", "option_chain", "clock"}.issubset(kinds)
    for datum in result.datums:
        assert datum.source
        assert datum.correlation_id == result.correlation_id
        assert datum.timestamp.tzinfo is not None


class _FeedDeniedClient(_PartialClient):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def fetch_quote(self, symbol: str):
        raise RuntimeError(self.message)


def _feed_value(request) -> str:
    feed = getattr(request, "feed", None)
    return str(getattr(feed, "value", feed) or "")


def test_equity_data_feed_defaults_to_iex_not_sip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_DATA_FEED", raising=False)
    monkeypatch.delenv("HACKATHON_DATA_FEED", raising=False)
    assert equity_data_feed() == "iex"


def test_equity_data_feed_honors_explicit_permitted_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_DATA_FEED", "delayed_sip")
    assert equity_data_feed() == "delayed_sip"


def test_feed_denial_reason_labels_sip_as_data_error() -> None:
    reason = feed_denial_reason(RuntimeError("subscription does not permit querying recent SIP data"))
    assert reason is not None
    assert "SIP" in reason
    assert "quote missing" not in reason.lower()


def test_sip_denied_quote_is_halt_not_fake_or_missing_quote() -> None:
    result = observe_live(
        HackathonSettings(),
        client=_FeedDeniedClient(
            "subscription does not permit querying recent SIP data",
            account=_account(),
        ),
    )
    assert result.outcome == ObservationOutcome.HALT
    assert result.evidence is None
    assert "SIP" in result.reason
    assert result.reason != "SPY quote missing"
    assert "quote missing" not in result.reason.lower()


def test_iex_denied_quote_is_halt_honestly() -> None:
    result = observe_live(
        HackathonSettings(),
        client=_FeedDeniedClient(
            "subscription does not permit querying recent IEX data",
            account=_account(),
        ),
    )
    assert result.outcome == ObservationOutcome.HALT
    assert result.evidence is None
    assert "IEX" in result.reason
    assert result.reason != "SPY quote missing"


def test_fresh_iex_quote_is_ok() -> None:
    quote = SimpleNamespace(
        bid_price=668.10,
        ask_price=668.12,
        timestamp=datetime.now(timezone.utc),
    )
    bar = SimpleNamespace(
        open=667, high=669, low=666, close=668, volume=1_000_000, timestamp=datetime.now(timezone.utc)
    )
    chain_quote = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=1.2, ask_price=1.4),
        latest_trade=SimpleNamespace(price=1.3),
        greeks=SimpleNamespace(delta=-0.2, gamma=0.01, theta=-0.05, vega=0.1),
    )
    result = observe_live(
        HackathonSettings(),
        client=_PartialClient(
            account=_account(),
            quote={"SPY": quote},
            bars={"SPY": [bar]},
            chain={"SPY260918P00500000": chain_quote},
        ),
    )
    assert result.outcome == ObservationOutcome.OK
    assert result.evidence is not None


def test_stale_iex_quote_is_no_trade_without_loosening_freshness() -> None:
    assert MAX_QUOTE_AGE_SECONDS == Decimal("120")
    quote = SimpleNamespace(
        bid_price=668.10,
        ask_price=668.12,
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=121),
    )
    result = observe_live(
        HackathonSettings(),
        client=_PartialClient(account=_account(), quote={"SPY": quote}),
    )
    assert result.outcome == ObservationOutcome.NO_TRADE
    assert result.evidence is None
    assert result.reason == "SPY quote is stale"


def test_alpaca_read_client_requests_iex_feed_by_default() -> None:
    captured: list[str] = []

    class Stock:
        def get_stock_latest_quote(self, request):
            captured.append(_feed_value(request))
            return {
                "SPY": SimpleNamespace(
                    bid_price=668.10,
                    ask_price=668.12,
                    timestamp=datetime.now(timezone.utc),
                )
            }

        def get_stock_bars(self, request):
            captured.append("bars:" + _feed_value(request))
            return {"SPY": []}

    client = AlpacaReadClient(trading=object(), stock_data=Stock(), option_data=object(), equity_feed="iex")
    client.fetch_quote("SPY")
    client.fetch_bars("SPY")
    assert captured[0] == "iex"
    assert captured[1] == "bars:iex"


def test_alpaca_read_client_retries_iex_when_sip_denied() -> None:
    feeds: list[str] = []

    class Stock:
        def get_stock_latest_quote(self, request):
            feed = _feed_value(request)
            feeds.append(feed)
            if feed == "sip":
                raise RuntimeError("subscription does not permit querying recent SIP data")
            return {
                "SPY": SimpleNamespace(
                    bid_price=668.10,
                    ask_price=668.12,
                    timestamp=datetime.now(timezone.utc),
                )
            }

    client = AlpacaReadClient(trading=object(), stock_data=Stock(), option_data=object(), equity_feed="sip")
    payload = client.fetch_quote("SPY")
    assert feeds == ["sip", "iex"]
    assert payload["SPY"].bid_price == 668.10


def test_alpaca_read_client_halts_when_iex_also_denied() -> None:
    class Stock:
        def get_stock_latest_quote(self, request):
            feed = _feed_value(request)
            raise RuntimeError(f"subscription does not permit querying recent {feed.upper()} data")

    client = AlpacaReadClient(trading=object(), stock_data=Stock(), option_data=object(), equity_feed="sip")
    with pytest.raises(ObservationClosed) as raised:
        client.fetch_quote("SPY")
    assert raised.value.outcome == ObservationOutcome.HALT
    assert "IEX" in raised.value.reason


def test_live_run_once_sip_denied_does_not_submit() -> None:
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=_FeedDeniedClient(
            "subscription does not permit querying recent SIP data",
            account=_account(),
        ),
    )
    assert result["ok"] is False
    assert result["outcome"] == "HALT"
    assert result["order"] is None
    assert "SIP" in result["reason"]


def test_alpaca_read_client_requests_indicative_option_feed() -> None:
    captured: dict[str, str] = {}

    class Options:
        def get_option_chain(self, request):
            captured["feed"] = _feed_value(request)
            return {}

    client = AlpacaReadClient(
        trading=object(),
        stock_data=object(),
        option_data=Options(),
        equity_feed="iex",
    )
    client.fetch_option_chain("SPY")
    assert captured["feed"] == "indicative"
