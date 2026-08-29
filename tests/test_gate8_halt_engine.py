"""Gate 8: durable fail-closed cycle state machine.

Kill/restart recovers the same cycle, payload, and client_order_id.
No second order. Unknown broker state forbids a new cycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from opticycle.cycle import (
    CycleHalted,
    CycleState,
    CycleStore,
    DuplicateTransition,
    IllegalTransition,
    StaleCertificate,
)
from opticycle.journal import TradeJournal
from opticycle.protocol import ObservationOutcome, ReconciliationStatus
from opticycle.reconcile import HaltLedger, reconcile
from opticycle.risk import RiskEngine
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from tests.test_gate7_reconciliation import FakeBroker, _order, _receipt
from tests.test_risk_certificate import (
    _bull_put_legs,
    _bull_put_quotes,
    _evidence,
    _payload,
    _portfolio,
    _settings,
)
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor, PLACE_OPTION_ORDER

ROOT = Path(__file__).resolve().parents[1]


class RecordingMcp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"id": "should-not-submit", "status": "accepted"}


def _advance(
    store: CycleStore,
    target: CycleState,
    *,
    client_order_id: str = "oc-gate8-001",
) -> tuple:
    payload = _payload(_bull_put_legs(), client_order_id=client_order_id)
    evidence = _evidence(_bull_put_quotes())
    portfolio = _portfolio()
    rec = store.begin_cycle(client_order_id=client_order_id)
    rec = store.transition(rec.cycle_id, CycleState.THESIS_READY, snapshot_hash="snap-1")
    rec = store.transition(rec.cycle_id, CycleState.CANDIDATES_READY, payload=payload)
    cert = RiskEngine(_settings()).issue(payload, portfolio, evidence, cycle_id=rec.cycle_id)
    rec = store.authorize(rec.cycle_id, payload, cert)
    if target is CycleState.AUTHORIZED:
        return rec, payload, cert
    rec = store.transition(rec.cycle_id, CycleState.SUBMITTING, reason="persist before mcp")
    if target is CycleState.SUBMITTING:
        return rec, payload, cert
    rec = store.record_attempt(
        rec.cycle_id,
        mcp_tool=PLACE_OPTION_ORDER,
        arguments_hash="args-1",
        broker_order_id="alp-ord-1",
        raw_status="accepted",
        raw_hash="raw-1",
    )
    rec = store.transition(
        rec.cycle_id,
        CycleState.ACKNOWLEDGED,
        broker_order_id="alp-ord-1",
        broker_status="accepted",
    )
    if target is CycleState.ACKNOWLEDGED:
        return rec, payload, cert
    rec = store.transition(rec.cycle_id, CycleState.RECONCILING, reason="reconcile")
    if target is CycleState.RECONCILING:
        return rec, payload, cert
    rec = store.transition(rec.cycle_id, CycleState.RECONCILED, reason="matched")
    rec = store.transition(rec.cycle_id, CycleState.COMPLETED, reason="complete")
    return rec, payload, cert


def _restart_run(tmp_path: Path, store: CycleStore, payload, mcp: RecordingMcp):
    recovered = CycleStore(store.path)
    return run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=recovered,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=FakeBroker(orders=[_order(client_order_id=payload.client_order_id)]),
        observer=FakeBroker(orders=[_order(client_order_id=payload.client_order_id)]),
    ), recovered


def test_restart_submitting_recovers_same_cycle_without_second_order(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.SUBMITTING)
    mcp = RecordingMcp()
    result, recovered = _restart_run(tmp_path, store, payload, mcp)
    loaded = recovered.load(rec.cycle_id)
    assert loaded.cycle_id == rec.cycle_id
    assert loaded.client_order_id == rec.client_order_id == payload.client_order_id
    assert loaded.payload_hash == rec.payload_hash == payload.payload_hash
    assert loaded.payload() is not None
    assert loaded.payload().payload_hash == payload.payload_hash
    assert mcp.calls == []
    assert result["cycle_id"] == rec.cycle_id
    assert result["client_order_id"] == payload.client_order_id
    assert result["payload_hash"] == payload.payload_hash
    assert result["order"] is None
    assert loaded.state in {CycleState.COMPLETED, CycleState.HALTED, CycleState.RECONCILED}


def test_restart_acknowledged_recovers_same_cycle_without_second_order(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.ACKNOWLEDGED)
    mcp = RecordingMcp()
    result, recovered = _restart_run(tmp_path, store, payload, mcp)
    loaded = recovered.load(rec.cycle_id)
    assert loaded.cycle_id == rec.cycle_id
    assert loaded.client_order_id == payload.client_order_id
    assert loaded.payload_hash == payload.payload_hash
    assert mcp.calls == []
    assert result["client_order_id"] == payload.client_order_id
    assert result["cycle_id"] == rec.cycle_id


def test_restart_reconciling_recovers_same_cycle_without_second_order(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.RECONCILING)
    mcp = RecordingMcp()
    result, recovered = _restart_run(tmp_path, store, payload, mcp)
    loaded = recovered.load(rec.cycle_id)
    assert loaded.cycle_id == rec.cycle_id
    assert loaded.client_order_id == payload.client_order_id
    assert loaded.payload_hash == payload.payload_hash
    assert mcp.calls == []
    assert result["client_order_id"] == payload.client_order_id
    assert recovered.attempt(rec.cycle_id)["attempt_no"] == 1


def test_illegal_state_jump_is_rejected(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec = store.begin_cycle(client_order_id="oc-illegal")
    with pytest.raises(IllegalTransition, match="OBSERVED → SUBMITTING"):
        store.transition(rec.cycle_id, CycleState.SUBMITTING)
    with pytest.raises(IllegalTransition, match="OBSERVED → COMPLETED"):
        store.transition(rec.cycle_id, CycleState.COMPLETED)
    assert store.load(rec.cycle_id).state is CycleState.OBSERVED


def test_duplicate_transition_is_rejected(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec = store.begin_cycle(client_order_id="oc-dup")
    rec = store.transition(rec.cycle_id, CycleState.THESIS_READY)
    with pytest.raises(DuplicateTransition):
        store.transition(rec.cycle_id, CycleState.THESIS_READY)
    assert store.load(rec.cycle_id).version == 1


def test_stale_certificate_reuse_is_blocked(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    payload = _payload(_bull_put_legs(), client_order_id="oc-stale")
    other = _payload(_bull_put_legs(), client_order_id="oc-stale", qty=2)
    rec = store.begin_cycle(client_order_id="oc-stale")
    rec = store.transition(rec.cycle_id, CycleState.THESIS_READY)
    rec = store.transition(rec.cycle_id, CycleState.CANDIDATES_READY, payload=payload)
    cert = RiskEngine(_settings()).issue(payload, _portfolio(), _evidence(_bull_put_quotes()), cycle_id=rec.cycle_id)
    with pytest.raises(StaleCertificate, match="one certificate"):
        store.authorize(rec.cycle_id, other, cert)
    expired = RiskEngine(_settings()).issue(
        payload,
        _portfolio(),
        _evidence(_bull_put_quotes()),
        cycle_id=rec.cycle_id,
        now=datetime.now(timezone.utc) - timedelta(seconds=120),
    )
    with pytest.raises(StaleCertificate, match="expired"):
        store.authorize(rec.cycle_id, payload, expired)
    rec = store.authorize(rec.cycle_id, payload, cert)
    with pytest.raises(DuplicateTransition):
        store.authorize(rec.cycle_id, payload, cert)


def test_client_order_id_is_unique_and_immutable(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec = store.begin_cycle(client_order_id="oc-unique")
    store.veto(rec.cycle_id, "done")
    with pytest.raises(Exception):
        store.begin_cycle(client_order_id="oc-unique")
    with pytest.raises(Exception, match="immutable"):
        store._conn.execute(
            "UPDATE cycles SET client_order_id = ? WHERE cycle_id = ?",
            ("oc-changed", rec.cycle_id),
        )
        store._conn.commit()
    assert store.load(rec.cycle_id).client_order_id == "oc-unique"


def test_unknown_broker_forbids_a_new_cycle(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.SUBMITTING, client_order_id="oc-unknown")
    mcp = RecordingMcp()
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=FakeBroker(fail=True),
        observer=FakeBroker(fail=True),
    )
    assert result["outcome"] == ObservationOutcome.HALT.value
    assert mcp.calls == []
    assert store.forbids_new_cycle() is True
    with pytest.raises(CycleHalted, match="unknown broker"):
        store.begin_cycle()
    second = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal2.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=FakeBroker(orders=[_order(client_order_id=payload.client_order_id)]),
    )
    assert second["outcome"] == ObservationOutcome.HALT.value
    assert second["order"] is None
    assert mcp.calls == []
    assert store.load(rec.cycle_id).client_order_id == "oc-unknown"


def test_full_cycle_is_replayable_from_durable_records(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, cert = _advance(store, CycleState.COMPLETED, client_order_id="oc-replay")
    events = store.replay(rec.cycle_id)
    states = [item["to_state"] for item in events]
    assert states == [
        "OBSERVED",
        "THESIS_READY",
        "CANDIDATES_READY",
        "AUTHORIZED",
        "SUBMITTING",
        "ACKNOWLEDGED",
        "RECONCILING",
        "RECONCILED",
        "COMPLETED",
    ]
    assert events[-1]["payload_hash"] == payload.payload_hash
    assert events[3]["certificate_hash"] == cert.binding_hash
    loaded = store.load(rec.cycle_id)
    assert loaded.payload().to_canonical_dict() == payload.to_canonical_dict()
    assert loaded.client_order_id == "oc-replay"
    assert store.attempt(rec.cycle_id)["attempt_no"] == 1


def test_second_execution_attempt_is_rejected(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, _payload, _cert = _advance(store, CycleState.SUBMITTING, client_order_id="oc-once")
    store.record_attempt(
        rec.cycle_id,
        mcp_tool=PLACE_OPTION_ORDER,
        arguments_hash="a",
        broker_order_id="ord-1",
        raw_status="accepted",
        raw_hash="h",
    )
    with pytest.raises(DuplicateTransition, match="one cycle"):
        store.record_attempt(
            rec.cycle_id,
            mcp_tool=PLACE_OPTION_ORDER,
            arguments_hash="b",
            broker_order_id="ord-2",
            raw_status="accepted",
            raw_hash="h2",
        )


def test_credit_price_improvement_is_matched_not_halt() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order(filled_avg_price="1.35")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MATCHED
    assert report.complete is True
    assert report.halt_triggered is False
    assert report.filled_avg_price == Decimal("1.35")
    fill = next(item for item in report.comparisons if item.field == "filled_avg_price")
    assert fill.matched is True


def test_fill_worse_than_limit_still_halts() -> None:
    payload = _payload(_bull_put_legs())
    report = reconcile(
        payload=payload,
        receipt=_receipt(payload),
        broker=FakeBroker(orders=[_order(filled_avg_price="1.00")]),
        settings=_settings(),
    )
    assert report.status == ReconciliationStatus.MISMATCH
    assert report.complete is False
    assert report.halt_triggered is True


def test_cycle_engine_has_no_cli_and_no_channel_switch() -> None:
    text = (ROOT / "src" / "opticycle" / "cycle.py").read_text(encoding="utf-8")
    assert "trade.cli" not in text
    assert "alpaca_cli" not in text
    assert "cancel_order" not in text
    assert "submit_order" not in text
    runner = (ROOT / "src" / "opticycle" / "runner.py").read_text(encoding="utf-8")
    assert "place_certified_order_sync" in runner
    assert "cycles.sqlite" in runner
