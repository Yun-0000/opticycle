"""A2: candidate leg timestamps and portfolio greeks are real, not age=0 / fake 0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from opticycle.observe import observe_live
from opticycle.protocol import freshness_seconds
from opticycle.risk import RiskEngine, observed_greeks
from opticycle.settings import HackathonSettings
from tests.test_live_observation import _PartialClient, _account
from tests.test_risk_certificate import (
    _bull_put_legs,
    _bull_put_quotes,
    _evidence,
    _payload,
    _portfolio,
    _quote,
    _settings,
)


def test_missing_leg_timestamp_is_fail_closed_not_age_zero() -> None:
    now = datetime.now(timezone.utc)
    quotes = _bull_put_quotes()
    missing = _quote(
        "SPY260918P00550000",
        option_type=quotes[0].option_type,
        strike="550.00",
        bid="2.10",
        ask="2.20",
        delta="-0.20",
        vega="0.08",
        gamma="0.01",
        theta="-0.04",
        quote_timestamp=None,
    )
    evidence = _evidence((missing, quotes[1]), now=now)
    cert = RiskEngine(_settings()).issue(_payload(_bull_put_legs()), _portfolio(), evidence, now=now)
    assert cert.veto is True
    assert any("missing quote timestamp" in reason for reason in cert.reasons)
    assert freshness_seconds(missing.quote_timestamp, now) is None
    assert all(leg.quote_timestamp is not None for leg in cert.calculated_risk.legs) or not cert.calculated_risk.legs


def test_stale_leg_quote_is_fail_closed() -> None:
    now = datetime.now(timezone.utc)
    quotes = _bull_put_quotes()
    stale = _quote(
        "SPY260918P00540000",
        option_type=quotes[1].option_type,
        strike="540.00",
        bid="0.80",
        ask="0.90",
        delta="-0.10",
        vega="0.05",
        gamma="0.008",
        theta="-0.02",
        quote_timestamp=now - timedelta(seconds=121),
    )
    fresh_short = _quote(
        "SPY260918P00550000",
        option_type=quotes[0].option_type,
        strike="550.00",
        bid="2.10",
        ask="2.20",
        delta="-0.20",
        vega="0.08",
        gamma="0.01",
        theta="-0.04",
        quote_timestamp=now,
    )
    evidence = _evidence((fresh_short, stale), now=now, age=Decimal("1"), fresh=True)
    cert = RiskEngine(_settings()).issue(_payload(_bull_put_legs()), _portfolio(), evidence, now=now)
    assert cert.veto is True
    assert any("stale quote" in reason for reason in cert.reasons)


def test_missing_greek_inputs_are_not_numeric_zero_on_live_snapshot() -> None:
    now = datetime.now(timezone.utc)
    bars = [
        SimpleNamespace(open=499, high=501, low=498, close=500, volume=1_000_000, timestamp=now)
        for _ in range(20)
    ]
    chain_snap = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=1.2, ask_price=1.4, timestamp=now),
        latest_trade=SimpleNamespace(price=1.3),
        greeks=None,
    )
    result = observe_live(
        HackathonSettings(),
        client=_PartialClient(
            account=_account(),
            quote={"SPY": SimpleNamespace(bid_price=500.0, ask_price=500.2, timestamp=now)},
            bars={"SPY": bars},
            chain={"SPY260918P00500000": chain_snap, "SPY260918P00490000": chain_snap},
        ),
    )
    assert result.outcome.value == "OK"
    assert result.evidence is not None
    for quote in result.evidence.chain_quotes:
        assert quote.delta is None
        assert quote.gamma is None
        assert quote.theta is None
        assert quote.vega is None
        assert quote.implied_volatility is None
        assert observed_greeks(quote) is False
    assert result.portfolio is not None
    assert result.portfolio.net_delta == 0.0
    assert result.portfolio.open_positions == 0


def test_fixture_only_zeros_are_not_real_greeks() -> None:
    zeros = _quote(
        "SPY260918P00550000",
        option_type=_bull_put_quotes()[0].option_type,
        strike="550.00",
        bid="2.10",
        ask="2.20",
        delta="0",
        vega="0",
        gamma="0",
        theta="0",
        implied_volatility=None,
    )
    assert observed_greeks(zeros) is False
    real = _bull_put_quotes()[0]
    assert observed_greeks(real) is True


def test_live_positions_use_chain_greeks_when_broker_omits_them() -> None:
    now = datetime.now(timezone.utc)
    bars = [
        SimpleNamespace(open=499, high=501, low=498, close=500, volume=1_000_000, timestamp=now)
        for _ in range(20)
    ]
    chain_snap = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=1.2, ask_price=1.4, timestamp=now),
        latest_trade=SimpleNamespace(price=1.3),
        greeks=SimpleNamespace(delta=-0.2, gamma=0.01, theta=-0.05, vega=0.1),
    )

    class Client(_PartialClient):
        def fetch_positions(self):
            return [SimpleNamespace(symbol="SPY260918P00500000", qty="1")]

    result = observe_live(
        HackathonSettings(),
        client=Client(
            account=_account(),
            quote={"SPY": SimpleNamespace(bid_price=500.0, ask_price=500.2, timestamp=now)},
            bars={"SPY": bars},
            chain={"SPY260918P00500000": chain_snap, "SPY260918P00490000": chain_snap},
        ),
    )
    assert result.outcome.value == "OK"
    assert result.portfolio is not None
    assert result.portfolio.open_positions == 1
    assert result.portfolio.net_delta == pytest.approx(-0.2)
    assert result.portfolio.net_vega == pytest.approx(0.1)
    assert result.portfolio.net_gamma == pytest.approx(0.01)
    assert result.portfolio.net_theta == pytest.approx(-0.05)


def test_live_positions_without_chain_greeks_still_omit_portfolio_greeks() -> None:
    now = datetime.now(timezone.utc)
    bars = [
        SimpleNamespace(open=499, high=501, low=498, close=500, volume=1_000_000, timestamp=now)
        for _ in range(20)
    ]
    chain_snap = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=1.2, ask_price=1.4, timestamp=now),
        latest_trade=SimpleNamespace(price=1.3),
        greeks=None,
    )

    class Client(_PartialClient):
        def fetch_positions(self):
            return [SimpleNamespace(symbol="SPY260918P00500000", qty="1")]

    result = observe_live(
        HackathonSettings(),
        client=Client(
            account=_account(),
            quote={"SPY": SimpleNamespace(bid_price=500.0, ask_price=500.2, timestamp=now)},
            bars={"SPY": bars},
            chain={"SPY260918P00500000": chain_snap, "SPY260918P00490000": chain_snap},
        ),
    )
    assert result.outcome.value == "OK"
    assert result.portfolio is not None
    assert result.portfolio.open_positions == 1
    assert result.portfolio.net_delta is None
    assert result.portfolio.net_vega is None
    assert result.portfolio.net_gamma is None
    assert result.portfolio.net_theta is None
