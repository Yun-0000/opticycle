"""Alpaca MLEG limit_price is signed: positive debit, negative credit."""

from __future__ import annotations

from decimal import Decimal

from opticycle.protocol import alpaca_signed_mleg_limit, fill_within_signed_mleg_limit
from opticycle.reconcile import evaluate_recorded_mleg_fill, reconcile
from opticycle.risk import RiskEngine, independent_vertical_risk
from tests.test_gate7_reconciliation import FakeBroker, _order, _receipt
from tests.test_risk_certificate import (
    _bear_call_legs,
    _bull_put_legs,
    _bull_put_quotes,
    _evidence,
    _payload,
    _portfolio,
    _settings,
)
from opticycle.protocol import ReconciliationStatus
from opticycle.live_matched_fills import monday_payload, weekend_payload
from opticycle.pin_option import build_pin_cycle_plan
from opticycle.protocol import ThesisStance
from opticycle.settings import HackathonSettings


def test_alpaca_credit_limit_is_negative() -> None:
    assert alpaca_signed_mleg_limit(is_credit=True, premium=Decimal("2.54")) == Decimal("-2.54")
    assert alpaca_signed_mleg_limit(is_credit=False, premium=Decimal("1.50")) == Decimal("1.50")


def test_signed_fill_bound_credit_improvement() -> None:
    assert fill_within_signed_mleg_limit(Decimal("-2.54"), Decimal("-2.80")) is True
    assert fill_within_signed_mleg_limit(Decimal("-2.54"), Decimal("-2.54")) is True
    assert fill_within_signed_mleg_limit(Decimal("-2.54"), Decimal("-2.11")) is False


def test_reconciler_matches_better_credit_fill() -> None:
    payload = _payload(_bull_put_legs(), limit_price=Decimal("-1.20"))
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order(limit_price="-1.20", filled_avg_price="-1.31")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MATCHED
    assert report.filled_avg_price == Decimal("-1.31")


def test_reconciler_mismatches_worse_credit_fill() -> None:
    payload = _payload(_bull_put_legs(), limit_price=Decimal("-1.20"))
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order(limit_price="-1.20", filled_avg_price="-1.00")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MISMATCH
    assert report.complete is False


def test_positive_credit_limit_is_certificate_veto() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bull_put_legs(), limit_price=Decimal("1.20")),
        _portfolio(),
        _evidence(_bull_put_quotes()),
    )
    assert cert.approval is False
    assert cert.veto is True
    assert any("negative" in reason for reason in cert.reasons)


def test_historical_weekend_fill_is_not_price_bound_matched() -> None:
    payload = weekend_payload()
    assert payload.limit_price == Decimal("2.54")
    evaluated = evaluate_recorded_mleg_fill(payload, Decimal("-2.11"))
    assert evaluated["limit_sign_error"] is True
    assert evaluated["credit_better_bound"] is False
    assert evaluated["price_bound_matched"] is False
    assert evaluated["status"] == "mismatch"
    assert evaluated["within_intended_credit_limit"] is False


def test_historical_monday_fill_raises_max_loss_vs_certificate() -> None:
    payload = monday_payload()
    evaluated = evaluate_recorded_mleg_fill(payload, Decimal("-0.51"))
    assert evaluated["limit_sign_error"] is True
    assert evaluated["price_bound_matched"] is False
    width = Decimal("1.00")
    cert_loss, _ = independent_vertical_risk(
        width=width,
        net_credit=Decimal("0.70"),
        net_debit=Decimal("0"),
        qty=1,
        is_credit=True,
    )
    fill_loss, _ = independent_vertical_risk(
        width=width,
        net_credit=Decimal("0.51"),
        net_debit=Decimal("0"),
        qty=1,
        is_credit=True,
    )
    assert cert_loss == Decimal("30.00")
    assert fill_loss == Decimal("49.00")


def test_pin_credit_plan_keeps_negative_limit() -> None:
    from tests.fixtures.market import make_pin_market

    plan = build_pin_cycle_plan(
        HackathonSettings(),
        market=make_pin_market(),
        stance=ThesisStance.BEARISH,
    )
    assert plan.request.limit_price is not None
    assert float(plan.request.limit_price) < 0


def test_mcp_arguments_keep_credit_sign() -> None:
    payload = _payload(_bear_call_legs(), limit_price=Decimal("-1.00"))
    assert payload.to_mcp_arguments()["limit_price"] == "-1.00"
    assert payload.is_credit_vertical() is True
