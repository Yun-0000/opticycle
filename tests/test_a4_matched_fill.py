"""A4: terminal successful fill is MATCHED + fill + P&L, never HALT."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from opticycle.cycle import CycleState, CycleStore
from opticycle.journal import TradeJournal
from opticycle.protocol import ReconciliationStatus
from opticycle.reconcile import HaltLedger, reconcile
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from tests.test_gate7_reconciliation import FakeBroker, _account, _order, _receipt
from tests.test_gate8_halt_engine import RecordingMcp, _advance
from tests.test_risk_certificate import _bull_put_legs, _payload, _settings


def _fill_broker(payload, *, filled_avg_price: str = "-1.20") -> FakeBroker:
    order = _order(client_order_id=payload.client_order_id, filled_avg_price=filled_avg_price)
    fills = [
        SimpleNamespace(
            symbol="SPY260918P00550000",
            qty="1",
            filled_qty="1",
            filled_avg_price=filled_avg_price,
            realized_pl="120.00",
            status="filled",
        )
    ]
    positions = [
        SimpleNamespace(
            symbol="SPY260918P00550000",
            qty="-1",
            market_value="0",
            unrealized_pl="40.00",
        )
    ]
    account = SimpleNamespace(
        id="PA3V84C40PJQ",
        account_number="PA3V84C40PJQ",
        equity="100120.00",
        cash="100120.00",
        long_market_value="0",
        short_market_value="0",
    )
    return FakeBroker(account=account, orders=[order], fills=fills, positions=positions)


def test_filled_terminal_matching_legs_is_matched_with_fill_and_pnl() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=_fill_broker(payload),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MATCHED
    assert report.complete is True
    assert report.halt_triggered is False
    assert report.filled_qty == 1
    assert report.filled_avg_price == Decimal("-1.20")
    assert all(
        item.matched
        for item in report.comparisons
        if item.field.startswith("leg[")
    )


def test_improved_fill_vs_limit_is_matched() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=_fill_broker(payload, filled_avg_price="-1.35"),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MATCHED
    assert report.complete is True
    assert report.halt_triggered is False
    assert report.filled_avg_price == Decimal("-1.35")
    fill = next(item for item in report.comparisons if item.field == "filled_avg_price")
    assert fill.matched is True


def test_runner_complete_path_does_not_write_halt_for_matched(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.ACKNOWLEDGED)
    mcp = RecordingMcp()
    broker = _fill_broker(payload)
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=broker,
        observer=broker,
    )
    rows = TradeJournal(tmp_path / "journal.jsonl").evidence.read_all()
    row = rows[-1]
    assert result["complete"] is True
    assert result["outcome"] == "MATCHED"
    assert result["outcome"] != "HALT"
    assert result["filled_qty"] == 1
    assert Decimal(str(result["filled_avg_price"])) == Decimal("-1.20")
    assert result["realized_pnl"] is not None
    assert result["unrealized_pnl"] is not None
    assert result["end_of_cycle_equity"] is not None
    assert row["outcome"] == "MATCHED"
    assert row["outcome"] != "HALT"
    assert row["claim"].split(":")[2] == "MATCHED"
    episode = row["episode"]
    assert episode["reconciliation"]["present"] is True
    assert str(episode["reconciliation"]["value"]["status"]).lower() == "matched"
    assert episode["realized_pnl"]["present"] is True
    assert episode["unrealized_pnl"]["present"] is True
    assert episode["end_of_cycle_equity"]["present"] is True
    assert store.load(rec.cycle_id).state is CycleState.COMPLETED
    assert mcp.calls == []


def test_halt_outcome_assertion_on_successful_fill_must_fail(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    _rec, payload, _cert = _advance(store, CycleState.ACKNOWLEDGED)
    mcp = RecordingMcp()
    broker = _fill_broker(payload)
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=broker,
        observer=broker,
    )
    row = TradeJournal(tmp_path / "journal.jsonl").evidence.read_all()[-1]
    with pytest.raises(AssertionError):
        assert result["outcome"] == "HALT"
    with pytest.raises(AssertionError):
        assert row["outcome"] == "HALT"


def test_partial_fill_is_still_containment_halt_not_matched() -> None:
    payload = _payload(_bull_put_legs(), qty=2)
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(
            account=_account(),
            orders=[
                _order(
                    qty="2",
                    filled_qty="1",
                    status="partially_filled",
                    filled_avg_price="-1.20",
                )
            ],
        ),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.PARTIAL_FILL
    assert report.complete is False
    assert report.halt_triggered is True
    assert report.status != ReconciliationStatus.MATCHED
