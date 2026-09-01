from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from opticycle.pin_option import apply_risk_budget_qty, vertical_max_loss_per_contract
from opticycle.position_manager import (
    ExitAuthorization,
    OpenVertical,
    _exit_reason,
    manage_open_positions,
    open_contracts_and_risk,
    open_verticals_and_risk,
)
from opticycle.protocol import EvidenceSnapshot, OptionContractQuote, OptionType
from opticycle.risk import PortfolioSnapshot, payload_from_request
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected, OptionOrderRequest

ACCOUNT = "PA3V84C40PJQ"
SHORT = "SPY260904P00500000"
LONG = "SPY260904P00495000"


def _request() -> OptionOrderRequest:
    return OptionOrderRequest(
        qty=1,
        order_type="limit",
        limit_price=-1.0,
        order_class="mleg",
        legs=[
            {"symbol": SHORT, "ratio_qty": "1", "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": LONG, "ratio_qty": "1", "side": "buy", "position_intent": "buy_to_open"},
        ],
    )


def _portfolio(**kwargs) -> PortfolioSnapshot:
    values = dict(
        equity=100_000,
        buying_power=100_000,
        cash=100_000,
        account_id=ACCOUNT,
        paper=True,
        options_approved=True,
        net_delta=0,
        net_vega=0,
        net_gamma=0,
        net_theta=0,
    )
    values.update(kwargs)
    return PortfolioSnapshot(**values)


def test_equity_risk_budget_sizes_and_caps_contracts() -> None:
    request = _request()
    assert vertical_max_loss_per_contract(request) == Decimal("400.00")
    qty = apply_risk_budget_qty(request, _portfolio(), HackathonSettings())
    assert qty == 4
    assert request.qty == 4
    assert request.metadata["risk_budget"] == "2000.00"


def test_sizing_respects_open_and_aggregate_capacity() -> None:
    request = _request()
    assert apply_risk_budget_qty(
        request,
        _portfolio(open_verticals=3),
        HackathonSettings(),
    ) == 4
    with pytest.raises(ExecutionRejected, match="exhausted"):
        apply_risk_budget_qty(
            _request(),
            _portfolio(open_risk=7800),
            HackathonSettings(),
        )
    with pytest.raises(ExecutionRejected, match="exhausted"):
        apply_risk_budget_qty(
            _request(),
            _portfolio(verticals_opened_today=2),
            HackathonSettings(),
        )
    with pytest.raises(ExecutionRejected, match="exhausted"):
        apply_risk_budget_qty(
            _request(),
            _portfolio(open_verticals=4),
            HackathonSettings(),
        )


def _positions() -> list[dict[str, str]]:
    return [
        {"symbol": SHORT, "qty": "-1", "side": "short", "avg_entry_price": "2.00"},
        {"symbol": LONG, "qty": "1", "side": "long", "avg_entry_price": "1.00"},
    ]


def test_four_contracts_are_one_open_vertical() -> None:
    positions = [dict(item) for item in _positions()]
    positions[0]["qty"] = "-4"
    positions[1]["qty"] = "4"
    contracts, contract_risk = open_contracts_and_risk(positions)
    verticals, vertical_risk = open_verticals_and_risk(positions)
    assert contracts == 4
    assert verticals == 1
    assert vertical_risk == contract_risk == Decimal("1600.00")


def _evidence(now: datetime) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        underlying="SPY",
        spot_price=Decimal("505"),
        timestamp=now,
        bars_count=30,
        quote_age_seconds=Decimal("1"),
        is_fresh=True,
        account_id=ACCOUNT,
        quote_timestamp=now,
        chain_quotes=(
            OptionContractQuote(
                symbol=SHORT,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=Decimal("500"),
                expiration=datetime(2026, 9, 4, tzinfo=timezone.utc),
                bid=Decimal("0.35"),
                ask=Decimal("0.45"),
                last=Decimal("0.40"),
                delta=Decimal("-0.25"),
                gamma=Decimal("0.01"),
                theta=Decimal("-0.05"),
                vega=Decimal("0.08"),
                quote_timestamp=now,
            ),
            OptionContractQuote(
                symbol=LONG,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=Decimal("495"),
                expiration=datetime(2026, 9, 4, tzinfo=timezone.utc),
                bid=Decimal("0.05"),
                ask=Decimal("0.10"),
                last=Decimal("0.07"),
                delta=Decimal("-0.10"),
                gamma=Decimal("0.006"),
                theta=Decimal("-0.02"),
                vega=Decimal("0.04"),
                quote_timestamp=now,
            ),
        ),
    )


class _ExitExecutor:
    def place_authorized_exit_sync(self, payload, authorization, **kwargs):
        authorization.verify(
            payload,
            position_snapshot_hash=kwargs["position_snapshot_hash"],
            settings=kwargs["settings"],
            now=kwargs["now"],
        )
        return {
            "tool": "place_option_order",
            "arguments": payload.to_mcp_arguments(),
            "arguments_hash": "a" * 64,
            "raw_result_hash": "b" * 64,
            "raw": {"id": "exit-order", "status": "filled"},
            "submitted": True,
            "dry_run": False,
        }


class _Broker:
    def __init__(self) -> None:
        self.cid = ""

    def fetch_account(self):
        return SimpleNamespace(account_number=ACCOUNT)

    def fetch_orders_by_client_id(self, client_order_id: str):
        return [
            {
                "id": "exit-order",
                "client_order_id": client_order_id,
                "order_class": "mleg",
                "qty": "1",
                "limit_price": "0.60",
                "status": "filled",
                "filled_qty": "1",
                "filled_avg_price": "0.35",
                "legs": [
                    {"symbol": SHORT, "ratio_qty": "1", "side": "buy", "position_intent": "buy_to_close"},
                    {"symbol": LONG, "ratio_qty": "1", "side": "sell", "position_intent": "sell_to_close"},
                ],
            }
        ]


def test_autonomous_exit_is_mcp_mleg_and_reconciled(tmp_path) -> None:
    now = datetime(2026, 9, 3, 19, 40, tzinfo=timezone.utc)
    contracts, risk = open_contracts_and_risk(_positions())
    assert contracts == 1
    assert risk == Decimal("400.00")
    verticals, vertical_risk = open_verticals_and_risk(_positions())
    assert verticals == 1
    assert vertical_risk == risk
    result = manage_open_positions(
        settings=HackathonSettings(),
        positions=_positions(),
        evidence=_evidence(now),
        broker=_Broker(),
        executor=_ExitExecutor(),  # type: ignore[arg-type]
        state_dir=tmp_path,
        now=now,
    )
    assert result["acted"] is True
    assert result["reason"] == "EVENT_RISK_FLATTEN"
    assert result["mcp_submit_count"] == 1
    assert result["second_submit"] is False
    assert result["reconciliation"]["status"] == "matched"


@pytest.mark.parametrize(
    ("expiration", "current_debit", "expected"),
    [
        (datetime(2026, 9, 10, tzinfo=timezone.utc).date(), Decimal("0.50"), "TAKE_PROFIT_50_PERCENT"),
        (datetime(2026, 9, 10, tzinfo=timezone.utc).date(), Decimal("2.00"), "STOP_LOSS_2X_CREDIT"),
        (datetime(2026, 9, 2, tzinfo=timezone.utc).date(), Decimal("1.00"), "DTE_FORCE_CLOSE"),
    ],
)
def test_each_autonomous_exit_trigger_is_deterministic(expiration, current_debit, expected) -> None:
    vertical = OpenVertical(
        short_symbol=SHORT,
        long_symbol=LONG,
        qty=1,
        expiration=expiration,
        width=Decimal("5"),
        entry_credit=Decimal("1.00"),
    )
    now = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    assert _exit_reason(vertical, current_debit, HackathonSettings(), now) == expected


def test_exit_authorization_rejects_payload_mutation() -> None:
    request = _request()
    request.legs[0]["position_intent"] = "buy_to_close"
    request.legs[0]["side"] = "buy"
    request.legs[1]["position_intent"] = "sell_to_close"
    request.legs[1]["side"] = "sell"
    request.limit_price = 0.50
    request.client_order_id = "oc-exit-test"
    payload = payload_from_request(request, account_id=ACCOUNT, client_order_id="oc-exit-test")
    now = datetime.now(timezone.utc)
    auth = ExitAuthorization(
        authorization_id="auth",
        payload_hash=payload.payload_hash,
        position_snapshot_hash="c" * 64,
        client_order_id=payload.client_order_id,
        account_id=ACCOUNT,
        reason="TAKE_PROFIT_50_PERCENT",
        issued_at=now,
        expires_at=now.replace(year=now.year + 1),
    )
    mutated = payload_from_request(
        OptionOrderRequest(
            qty=2,
            order_type="limit",
            limit_price=0.50,
            order_class="mleg",
            legs=request.legs,
        ),
        account_id=ACCOUNT,
        client_order_id="oc-exit-test",
    )
    with pytest.raises(ExecutionRejected, match="payload changed"):
        auth.verify(
            mutated,
            position_snapshot_hash="c" * 64,
            settings=HackathonSettings(),
            now=now,
        )
