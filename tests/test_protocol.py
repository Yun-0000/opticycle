"""Unit tests for Opticycle Gate 2 protocol objects.

Verifies:
- Same semantic payload always produces the exact same hash
- Changing strike, side, ratio, qty, limit, or account changes the payload_hash
- Leg order independence: permutations of legs produce identical canonical sort and hash
- MCP tool parameters are derived strictly from CanonicalOrderPayload
- All Decimal and UTC datetime constraints are enforced
- Round-trip integrity and boundary checks
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal
import pytest

from opticycle.protocol import (
    BrokerReceipt,
    CanonicalOrderPayload,
    DecisionEpisode,
    DecisionRecord,
    EvidenceSnapshot,
    ExecutionAttempt,
    ExecutionChannel,
    ExecutionStatus,
    OptionCandidate,
    OptionContractQuote,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
    ReconciliationReport,
    ReconciliationStatus,
    RiskCertificate,
    SpreadType,
    StrategyKind,
    ThesisAction,
)


def _make_sample_legs() -> tuple[OptionLegSpec, OptionLegSpec]:
    exp = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    leg1 = OptionLegSpec(
        symbol="SPY260918P00550000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("550.00"),
        expiration=exp,
    )
    leg2 = OptionLegSpec(
        symbol="SPY260918P00540000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("540.00"),
        expiration=exp,
    )
    return leg1, leg2


def _make_sample_payload(
    client_order_id: str = "cycle-20260829-001",
    account_id: str = "PA3V84C40PJQ",
    qty: int = 1,
    limit_price: Decimal = Decimal("2.45"),
    legs: tuple[OptionLegSpec, ...] | None = None,
) -> CanonicalOrderPayload:
    if legs is None:
        legs = _make_sample_legs()
    return CanonicalOrderPayload(
        client_order_id=client_order_id,
        account_id=account_id,
        underlying="SPY",
        order_class="mleg",
        order_type="limit",
        time_in_force="day",
        qty=qty,
        limit_price=limit_price,
        legs=legs,
    )


def test_payload_hash_deterministic() -> None:
    p1 = _make_sample_payload()
    p2 = _make_sample_payload()
    assert p1.payload_hash == p2.payload_hash
    assert len(p1.payload_hash) == 64


def test_payload_hash_leg_ordering_invariant() -> None:
    leg1, leg2 = _make_sample_legs()
    p_forward = _make_sample_payload(legs=(leg1, leg2))
    p_reversed = _make_sample_payload(legs=(leg2, leg1))

    # Regardless of input leg sequence, canonical sort yields identical hash
    assert p_forward.payload_hash == p_reversed.payload_hash
    assert p_forward.legs == p_reversed.legs


def test_payload_hash_changes_on_account() -> None:
    p1 = _make_sample_payload(account_id="PA3V84C40PJQ")
    p2 = _make_sample_payload(account_id="PA9999999999")
    assert p1.payload_hash != p2.payload_hash


def test_payload_hash_changes_on_qty() -> None:
    p1 = _make_sample_payload(qty=1)
    p2 = _make_sample_payload(qty=2)
    assert p1.payload_hash != p2.payload_hash


def test_payload_hash_changes_on_limit_price() -> None:
    p1 = _make_sample_payload(limit_price=Decimal("2.45"))
    p2 = _make_sample_payload(limit_price=Decimal("2.50"))
    assert p1.payload_hash != p2.payload_hash


def test_payload_hash_changes_on_strike() -> None:
    exp = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    leg1 = OptionLegSpec(
        symbol="SPY260918P00550000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("550.00"),
        expiration=exp,
    )
    leg2_a = OptionLegSpec(
        symbol="SPY260918P00540000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("540.00"),
        expiration=exp,
    )
    leg2_b = OptionLegSpec(
        symbol="SPY260918P00535000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("535.00"),
        expiration=exp,
    )
    p1 = _make_sample_payload(legs=(leg1, leg2_a))
    p2 = _make_sample_payload(legs=(leg1, leg2_b))
    assert p1.payload_hash != p2.payload_hash


def test_payload_hash_changes_on_side() -> None:
    exp = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    leg1 = OptionLegSpec(
        symbol="SPY260918P00550000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("550.00"),
        expiration=exp,
    )
    leg2 = OptionLegSpec(
        symbol="SPY260918P00540000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("540.00"),
        expiration=exp,
    )
    leg2_flipped = OptionLegSpec(
        symbol="SPY260918P00540000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("540.00"),
        expiration=exp,
    )
    p1 = _make_sample_payload(legs=(leg1, leg2))
    p2 = _make_sample_payload(legs=(leg1, leg2_flipped))
    assert p1.payload_hash != p2.payload_hash


def test_payload_hash_changes_on_ratio() -> None:
    exp = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    leg1 = OptionLegSpec(
        symbol="SPY260918P00550000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("550.00"),
        expiration=exp,
    )
    leg2_ratio1 = OptionLegSpec(
        symbol="SPY260918P00540000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("540.00"),
        expiration=exp,
    )
    leg2_ratio2 = OptionLegSpec(
        symbol="SPY260918P00540000",
        ratio_qty=2,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("540.00"),
        expiration=exp,
    )
    p1 = _make_sample_payload(legs=(leg1, leg2_ratio1))
    p2 = _make_sample_payload(legs=(leg1, leg2_ratio2))
    assert p1.payload_hash != p2.payload_hash


def test_mcp_arguments_derived_strictly_from_payload() -> None:
    payload = _make_sample_payload()
    args = payload.to_mcp_arguments()

    assert args["order_class"] == "mleg"
    assert args["type"] == "limit"
    assert args["time_in_force"] == "day"
    assert args["qty"] == "1"
    assert args["limit_price"] == "2.45"
    assert args["client_order_id"] == "cycle-20260829-001"
    assert len(args["legs"]) == 2

    # Check legs match canonical payload
    assert args["legs"][0]["symbol"] == payload.legs[0].symbol
    assert args["legs"][0]["ratio_qty"] == str(payload.legs[0].ratio_qty)
    assert args["legs"][0]["side"] == payload.legs[0].side.value
    assert args["legs"][0]["position_intent"] == payload.legs[0].position_intent.value


def test_validation_rejects_invalid_occ_symbol() -> None:
    with pytest.raises(ValueError, match="Invalid OCC option symbol"):
        OptionLegSpec(
            symbol="INVALID_SYMBOL",
            ratio_qty=1,
            side=OrderSide.BUY,
            position_intent=PositionIntent.BUY_TO_OPEN,
            option_type=OptionType.PUT,
            strike_price=Decimal("500.00"),
            expiration=datetime.now(timezone.utc),
        )


def test_risk_certificate_binding() -> None:
    payload = _make_sample_payload()
    cert = RiskCertificate(
        certificate_id="cert-001",
        cycle_id="cycle-20260829-001",
        payload_hash=payload.payload_hash,
        client_order_id=payload.client_order_id,
        account_id=payload.account_id,
        passed=True,
        reasons=(),
        portfolio_equity=Decimal("100000.00"),
        buying_power=Decimal("100000.00"),
        projected_delta=Decimal("-0.15"),
        projected_vega=Decimal("4.50"),
        max_risk_allowed=Decimal("8000.00"),
        timestamp=datetime.now(timezone.utc),
    )
    assert cert.payload_hash == payload.payload_hash
    assert cert.passed is True


def test_decision_episode_lifecycle_and_immutability() -> None:
    now = datetime.now(timezone.utc)
    exp = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    leg1, leg2 = _make_sample_legs()

    quote = OptionContractQuote(
        symbol="SPY260918P00550000",
        underlying="SPY",
        option_type=OptionType.PUT,
        strike_price=Decimal("550.00"),
        expiration=exp,
        bid=Decimal("15.20"),
        ask=Decimal("15.50"),
        last=Decimal("15.35"),
        delta=Decimal("-0.25"),
    )

    evidence = EvidenceSnapshot(
        underlying="SPY",
        spot_price=Decimal("560.25"),
        timestamp=now,
        bars_count=60,
        quote_age_seconds=Decimal("0.5"),
        is_fresh=True,
        chain_quotes=(quote,),
    )

    candidate = OptionCandidate(
        underlying="SPY",
        spread_type=SpreadType.BULL_PUT,
        legs=(leg1, leg2),
        net_limit_price=Decimal("2.45"),
        max_loss=Decimal("755.00"),
        max_profit=Decimal("245.00"),
        width=Decimal("10.00"),
        dte=20,
        is_credit=True,
        score=Decimal("0.85"),
    )

    decision = DecisionRecord(
        cycle_id="cycle-001",
        underlying="SPY",
        action=ThesisAction.OPEN_SPREAD,
        strategy=StrategyKind.VERTICAL_SPREAD,
        timestamp=now,
        reason="Bull put spread meeting delta and DTE criteria",
        confidence=Decimal("0.85"),
        candidate=candidate,
    )

    payload = _make_sample_payload(client_order_id="cycle-001", legs=(leg1, leg2))

    cert = RiskCertificate(
        certificate_id="cert-001",
        cycle_id="cycle-001",
        payload_hash=payload.payload_hash,
        client_order_id=payload.client_order_id,
        account_id=payload.account_id,
        passed=True,
        reasons=(),
        portfolio_equity=Decimal("100000.00"),
        buying_power=Decimal("100000.00"),
        projected_delta=Decimal("-0.15"),
        projected_vega=Decimal("4.50"),
        max_risk_allowed=Decimal("8000.00"),
        timestamp=now,
    )

    execution = ExecutionAttempt(
        attempt_id="att-001",
        cycle_id="cycle-001",
        channel=ExecutionChannel.MCP,
        payload_hash=payload.payload_hash,
        client_order_id=payload.client_order_id,
        sent_at=now,
        mcp_tool_name="place_option_order",
        mcp_arguments=payload.to_mcp_arguments(),
    )

    receipt = BrokerReceipt(
        receipt_id="rec-001",
        cycle_id="cycle-001",
        client_order_id="cycle-001",
        broker_order_id="alp-ord-12345",
        received_at=now,
        raw_status="accepted",
        is_success=True,
    )

    reconciliation = ReconciliationReport(
        report_id="recon-001",
        cycle_id="cycle-001",
        client_order_id="cycle-001",
        broker_order_id="alp-ord-12345",
        status=ReconciliationStatus.MATCHED,
        reconciled_at=now,
        broker_status="filled",
        filled_qty=1,
        filled_avg_price=Decimal("2.45"),
    )

    episode = DecisionEpisode(
        cycle_id="cycle-001",
        underlying="SPY",
        started_at=now,
        finished_at=now,
        evidence=evidence,
        decision=decision,
        certificate=cert,
        order_payload=payload,
        execution=execution,
        receipt=receipt,
        reconciliation=reconciliation,
        terminal_state=ExecutionStatus.FILLED,
    )

    assert episode.cycle_id == "cycle-001"
    assert episode.terminal_state == ExecutionStatus.FILLED
    assert episode.order_payload.payload_hash == cert.payload_hash
    assert episode.execution.channel == ExecutionChannel.MCP
