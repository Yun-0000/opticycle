"""Gate 7: broker reconciliation decides completion.

submitted=True is not a fill and not completion. Only MATCHED completes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from opticycle.journal import TradeJournal
from opticycle.protocol import BrokerReceipt, ObservationOutcome, ReconciliationStatus, ThesisStance
from opticycle.reconcile import (
    PARTIAL_FILL_CONTAINMENT,
    HaltLedger,
    receipt_from_mcp,
    reconcile,
    report_as_dict,
)
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from tests.test_risk_certificate import _bull_put_legs, _payload, _settings

ROOT = Path(__file__).resolve().parents[1]


def _account(account_id: str = "PA3V84C40PJQ") -> SimpleNamespace:
    return SimpleNamespace(
        id=account_id,
        account_number=account_id,
        equity="100000.00",
        cash="100000.00",
        long_market_value="0",
        short_market_value="0",
    )


def _legs():
    short, long = _bull_put_legs()
    return [
        SimpleNamespace(
            symbol=short.symbol,
            ratio_qty="1",
            side="sell",
            position_intent="sell_to_open",
        ),
        SimpleNamespace(
            symbol=long.symbol,
            ratio_qty="1",
            side="buy",
            position_intent="buy_to_open",
        ),
    ]


def _order(**kwargs) -> SimpleNamespace:
    payload = dict(
        id="alp-ord-1",
        client_order_id="cycle-gate5-001",
        order_class="mleg",
        qty="1",
        limit_price="-1.20",
        status="filled",
        filled_qty="1",
        filled_avg_price="-1.20",
        legs=_legs(),
    )
    payload.update(kwargs)
    return SimpleNamespace(**payload)


class FakeBroker:
    def __init__(
        self,
        account=None,
        orders=None,
        *,
        fail: bool = False,
        positions=None,
        fills=None,
    ) -> None:
        self.account = account if account is not None else _account()
        self.orders = list(orders or [])
        self.positions = list(positions or [])
        self.fills = list(fills) if fills is not None else []
        self.fail = fail

    def fetch_account(self):
        if self.fail:
            raise ConnectionError("broker offline")
        return self.account

    def fetch_positions(self):
        if self.fail:
            raise ConnectionError("broker offline")
        return list(self.positions)

    def fetch_fills(self):
        if self.fail:
            raise ConnectionError("broker offline")
        return list(self.fills)

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None):
        if self.fail:
            raise ConnectionError("broker offline")
        if not self.orders:
            return None
        if order_id:
            for item in self.orders:
                if str(getattr(item, "id", "")) == str(order_id):
                    return item
        if client_order_id:
            for item in self.orders:
                if str(getattr(item, "client_order_id", "")) == str(client_order_id):
                    return item
        return self.orders[0]

    def fetch_orders_by_client_id(self, client_order_id: str):
        if self.fail:
            raise ConnectionError("broker offline")
        wanted = str(client_order_id)
        return [item for item in self.orders if str(getattr(item, "client_order_id", "")) == wanted]


def _receipt(payload, *, order_id: str = "alp-ord-1", submitted: bool = True) -> BrokerReceipt:
    return BrokerReceipt(
        receipt_id="receipt-1",
        cycle_id=payload.client_order_id,
        client_order_id=payload.client_order_id,
        broker_order_id=order_id,
        received_at=datetime.now(timezone.utc),
        raw_status="accepted",
        is_success=submitted,
        submitted=submitted,
        response_payload={"id": order_id, "status": "accepted"},
    )


def test_price_improvement_is_matched() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order(filled_avg_price="-1.31")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MATCHED
    assert report.complete is True
    assert report.halt_triggered is False
    assert report.filled_avg_price == Decimal("-1.31")


def test_matched_fill_is_the_only_completion() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order()]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MATCHED
    assert report.complete is True
    assert report.halt_triggered is False
    assert report.filled_qty == 1
    assert report.filled_avg_price == Decimal("-1.20")
    fields = {item.field for item in report.comparisons}
    for required in (
        "account",
        "order_id",
        "client_order_id",
        "order_class",
        "qty",
        "limit",
        "status",
        "filled_qty",
        "filled_avg_price",
        "legs",
    ):
        assert required in fields
    assert any(item.field.startswith("leg[0].") for item in report.comparisons)
    assert all(item.matched for item in report.comparisons)


def test_submitted_true_alone_cannot_complete() -> None:
    payload = _payload(_bull_put_legs())
    mcp_result = {
        "submitted": True,
        "dry_run": False,
        "raw": {"id": "alp-ord-1", "status": "accepted"},
        "ok": True,
    }
    receipt = receipt_from_mcp(cycle_id=payload.client_order_id, payload=payload, mcp_result=mcp_result)
    assert receipt.submitted is True
    assert receipt.is_success is True
    report = reconcile(
        payload=payload,
        receipt=receipt,
        broker=FakeBroker(orders=[]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.UNKNOWN
    assert report.complete is False
    assert report.halt_triggered is True


def test_mismatch_halts() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order(qty="9", filled_qty="9")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MISMATCH
    assert report.complete is False
    assert report.halt_triggered is True
    assert any(item.field == "qty" and not item.matched for item in report.comparisons)


def test_unknown_broker_state_halts() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(fail=True),
        settings=_settings(),
    )
    assert report.status in {ReconciliationStatus.UNKNOWN, ReconciliationStatus.UNKNOWN_BROKER_STATE}
    assert report.complete is False
    assert report.halt_triggered is True


def test_duplicate_client_order_is_explicit() -> None:
    payload = _payload(_bull_put_legs())
    first = _order(id="alp-ord-1")
    second = _order(id="alp-ord-2")
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[first, second]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.DUPLICATE
    assert report.complete is False
    assert report.halt_triggered is True


def test_partial_fill_uses_deterministic_containment() -> None:
    payload = _payload(_bull_put_legs(), qty=2)
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(
            orders=[
                _order(
                    qty="2",
                    filled_qty="1",
                    status="partially_filled",
                    filled_avg_price="-1.20",
                )
            ]
        ),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.PARTIAL_FILL
    assert report.complete is False
    assert report.halt_triggered is True
    assert report.filled_qty == 1
    assert report.containment == PARTIAL_FILL_CONTAINMENT
    assert "do_not_resubmit" in report.containment
    assert "do_not_switch_channel" in report.containment
    src = (ROOT / "src" / "opticycle" / "reconcile.py").read_text(encoding="utf-8")
    assert "openai" not in src.lower()
    assert "ThesisAgent" not in src
    assert "trade.cli" not in src


def test_account_mismatch_is_mismatch() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(account=_account("PA9999999999"), orders=[_order()]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MISMATCH
    assert report.halt_triggered is True
    assert any(item.field == "account" and not item.matched for item in report.comparisons)


def test_halt_ledger_blocks_new_live_trades(tmp_path: Path) -> None:
    ledger = HaltLedger(tmp_path / "halt.json")
    ledger.trip(status="mismatch", reason="qty mismatch", report_id="r1")
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        halt_ledger=ledger,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
    )
    assert result["ok"] is False
    assert result["complete"] is False
    assert result["submitted"] is False
    assert result["outcome"] == ObservationOutcome.HALT.value
    assert result["order"] is None


def test_dry_run_ok_is_not_cycle_completion(tmp_path: Path) -> None:
    from tests.fixtures.market import make_pin_market

    result = run_once(
        HackathonSettings(),
        dry_run=True,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        market=make_pin_market(),
        stance=ThesisStance.BULLISH,
    )
    assert result["ok"] is True
    assert result["complete"] is False
    assert result["submitted"] is False
    assert result["order"]["submitted"] is False


def test_mismatch_trips_halt_ledger(tmp_path: Path) -> None:
    payload = _payload(_bull_put_legs())
    ledger = HaltLedger(tmp_path / "halt.json")
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order(qty="9")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MISMATCH
    ledger.trip(status=report.status.value, reason="qty", report_id=report.report_id)
    assert ledger.is_halted() is True
    dumped = report_as_dict(report)
    assert dumped["complete"] is False
    assert dumped["comparisons"]
    assert dumped["status"] == "mismatch"
