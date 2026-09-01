"""A3: working broker states wait; terminal states complete; unknown still HALTs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from opticycle.cycle import CycleState, CycleStore
from opticycle.journal import TradeJournal
from opticycle.protocol import BrokerReceipt, ObservationOutcome, ReconciliationStatus
from opticycle.reconcile import HaltLedger, reconcile
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from tests.test_gate7_reconciliation import FakeBroker, _order, _receipt
from tests.test_gate8_halt_engine import RecordingMcp, _advance
from tests.test_risk_certificate import _bull_put_legs, _payload, _settings


def _working_order(*, status: str, client_order_id: str = "cycle-gate5-001"):
    return _order(
        client_order_id=client_order_id,
        status=status,
        filled_qty="0",
        filled_avg_price=None,
    )


def test_accepted_receipt_is_pending_not_halt() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_working_order(status="accepted")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.PENDING
    assert report.complete is False
    assert report.halt_triggered is False
    assert report.broker_status == "accepted"


def test_new_receipt_is_pending_not_halt() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_working_order(status="new")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.PENDING
    assert report.complete is False
    assert report.halt_triggered is False
    assert report.broker_status == "new"


def test_accepted_then_filled_is_matched() -> None:
    payload = _payload(_bull_put_legs())
    receipt = _receipt(payload)
    pending = reconcile(
        payload=payload,
        receipt=receipt,
        broker=FakeBroker(orders=[_working_order(status="accepted")]),
        settings=_settings(),
    )
    assert pending.status == ReconciliationStatus.PENDING
    assert pending.halt_triggered is False
    filled = reconcile(
        payload=payload,
        receipt=receipt,
        broker=FakeBroker(orders=[_order()]),
        settings=_settings(),
    )
    assert filled.status == ReconciliationStatus.MATCHED
    assert filled.complete is True
    assert filled.halt_triggered is False


def test_query_fail_still_halts() -> None:
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


def test_missing_order_with_no_ack_halts() -> None:
    payload = _payload(_bull_put_legs())
    receipt = BrokerReceipt(
        receipt_id="receipt-no-ack",
        cycle_id=payload.client_order_id,
        client_order_id=payload.client_order_id,
        broker_order_id=None,
        received_at=datetime.now(timezone.utc),
        raw_status="",
        is_success=False,
        submitted=False,
        response_payload={},
    )
    report = reconcile(
        payload=payload,
        receipt=receipt,
        broker=FakeBroker(orders=[]),
        settings=_settings(),
    )
    assert report.status in {ReconciliationStatus.UNKNOWN, ReconciliationStatus.UNKNOWN_BROKER_STATE}
    assert report.complete is False
    assert report.halt_triggered is True


def test_pending_restart_queries_same_client_id_without_resubmit(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.ACKNOWLEDGED)
    mcp = RecordingMcp()
    working = _working_order(status="accepted", client_order_id=payload.client_order_id)
    broker = FakeBroker(orders=[working])
    ledger = HaltLedger(tmp_path / "halt.json")
    first = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=ledger,
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=broker,
        observer=broker,
    )
    loaded = store.load(rec.cycle_id)
    assert first["outcome"] != ObservationOutcome.HALT.value
    assert first["outcome"] == "PENDING"
    assert first["complete"] is False
    assert first["reconciliation"]["status"] == "pending"
    assert first["client_order_id"] == payload.client_order_id == rec.client_order_id
    assert loaded.client_order_id == payload.client_order_id
    assert loaded.state in {CycleState.ACKNOWLEDGED, CycleState.RECONCILING}
    assert loaded.state is not CycleState.HALTED
    assert ledger.is_halted() is False
    assert store.forbids_new_cycle() is False
    assert mcp.calls == []

    second = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal2.jsonl"),
        halt_ledger=ledger,
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=broker,
        observer=broker,
    )
    again = store.load(rec.cycle_id)
    assert mcp.calls == []
    assert second["outcome"] == "PENDING"
    assert second["complete"] is False
    assert second["client_order_id"] == payload.client_order_id
    assert again.client_order_id == payload.client_order_id
    assert again.state in {CycleState.ACKNOWLEDGED, CycleState.RECONCILING}
    assert again.state is not CycleState.HALTED
    assert ledger.is_halted() is False

    working.status = "filled"
    working.filled_qty = "1"
    working.filled_avg_price = "-1.20"
    third = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal3.jsonl"),
        halt_ledger=ledger,
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=broker,
        observer=broker,
    )
    done = store.load(rec.cycle_id)
    assert mcp.calls == []
    assert third["complete"] is True
    assert third["reconciliation"]["status"] == "matched"
    assert third["client_order_id"] == payload.client_order_id
    assert done.state is CycleState.COMPLETED
    assert done.client_order_id == payload.client_order_id
