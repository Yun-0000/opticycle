from __future__ import annotations

from types import SimpleNamespace

import pytest

from opticycle.risk import GateResult, PortfolioSnapshot, RiskGate, contract_greeks, scale_greeks
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected, OptionOrderRequest


def _settings(**kwargs) -> HackathonSettings:
    return HackathonSettings(**kwargs)


def _portfolio(**kwargs) -> PortfolioSnapshot:
    base = dict(
        equity=100_000,
        buying_power=100_000,
        cash=100_000,
        paper=True,
        options_approved=True,
        trades_today=0,
        open_positions=0,
        net_delta=0.0,
        net_vega=0.0,
    )
    base.update(kwargs)
    return PortfolioSnapshot(**base)


def _put() -> OptionOrderRequest:
    return OptionOrderRequest(
        qty=1,
        symbol="SPY250919P00475000",
        side="sell",
        order_type="limit",
        limit_price=1.25,
        position_intent="sell_to_open",
    )


def test_risk_gate_approves_option_order_within_100k_limits() -> None:
    gate = RiskGate(_settings())
    result = gate.evaluate(_put(), _portfolio(), option_price=1.25, proposed_delta=-12.0, proposed_vega=8.0)
    assert result.approved is True
    assert result.reasons == []


def test_risk_gate_rejects_stock_symbol() -> None:
    request = OptionOrderRequest(qty=1, symbol="AAPL", side="buy", order_type="market")
    with pytest.raises(ExecutionRejected, match="OCC option symbol"):
        RiskGate(_settings()).evaluate(request, _portfolio())


def test_risk_gate_rejects_daily_trade_limit() -> None:
    result = RiskGate(_settings(max_daily_trades=1)).evaluate(
        _put(),
        _portfolio(trades_today=1),
        option_price=1.25,
    )
    assert result.approved is False
    assert any("daily trade" in reason for reason in result.reasons)


def test_risk_gate_rejects_missing_options_approval() -> None:
    result = RiskGate(_settings()).evaluate(
        _put(),
        _portfolio(options_approved=False),
        option_price=1.25,
    )
    assert result.approved is False
    assert any("options" in reason for reason in result.reasons)


def test_risk_gate_rejects_delta_limit() -> None:
    result = RiskGate(_settings(max_abs_delta=10.0)).evaluate(
        _put(),
        _portfolio(net_delta=-9.0),
        option_price=1.25,
        proposed_delta=-5.0,
    )
    assert result.approved is False
    assert any("delta" in reason for reason in result.reasons)


def test_vollib_greeks_and_scale_sign_for_short_put() -> None:
    greeks = contract_greeks("p", 100.0, 95.0, 21 / 365, 0.04, 0.20)
    assert greeks["delta"] < 0
    scaled = scale_greeks(greeks, 1, "sell")
    assert scaled["delta"] > 0


def test_gate_result_raise_if_rejected() -> None:
    with pytest.raises(ExecutionRejected):
        GateResult(approved=False, reasons=["veto"]).raise_if_rejected()
