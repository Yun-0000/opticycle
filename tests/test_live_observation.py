"""Gate 3: live observation is fail-closed and never uses fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from opticycle.observe import observe_live
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
