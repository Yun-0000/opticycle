"""Fail-closed paper/options flags and no MATCHED without broker P&L/equity."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from opticycle.cycle import CycleState, CycleStore
from opticycle.journal import TradeJournal
from opticycle.observe import observe_live
from opticycle.protocol import ObservationOutcome
from opticycle.reconcile import HaltLedger
from opticycle.risk import PortfolioSnapshot, RiskGate
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from trade.orders import OptionOrderRequest
from tests.test_a4_matched_fill import _fill_broker
from tests.test_gate8_halt_engine import RecordingMcp, _advance
from tests.test_live_observation import _PartialClient, _account


def _live_ok_client(*, account) -> _PartialClient:
    now = datetime.now(timezone.utc)
    quote = SimpleNamespace(bid_price=500.0, ask_price=500.2, timestamp=now)
    bar = SimpleNamespace(open=499, high=501, low=498, close=500, volume=1_000_000, timestamp=now)
    chain_quote = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=1.2, ask_price=1.4),
        latest_trade=SimpleNamespace(price=1.3),
        greeks=SimpleNamespace(delta=-0.2, gamma=0.01, theta=-0.05, vega=0.1),
    )
    return _PartialClient(
        account=account,
        quote={"SPY": quote},
        bars={"SPY": [bar]},
        chain={"SPY260918P00500000": chain_quote},
    )


def test_missing_options_approved_does_not_silently_approve() -> None:
    account = SimpleNamespace(
        id="PA3V84C40PJQ",
        account_number="PA3V84C40PJQ",
        equity="100000",
        buying_power="100000",
        cash="100000",
        daytrade_count=0,
    )
    result = observe_live(HackathonSettings(), client=_live_ok_client(account=account))
    assert result.outcome == ObservationOutcome.HALT
    assert result.evidence is None
    assert "options" in result.reason.lower()
    snap = PortfolioSnapshot(equity=100000, buying_power=100000, cash=100000)
    assert snap.options_approved is False
    assert snap.paper is False
    gate = RiskGate(HackathonSettings()).evaluate(
        OptionOrderRequest(qty=1, symbol="SPY250919P00475000", side="sell"),
        snap,
    )
    assert gate.approved is False
    assert any("options" in reason.lower() or "paper" in reason.lower() for reason in gate.reasons)


def test_missing_paper_flag_does_not_default_true() -> None:
    account = _account(id="LIVEACCOUNT1", account_number="LIVEACCOUNT1")
    result = observe_live(HackathonSettings(), client=_live_ok_client(account=account))
    assert result.outcome == ObservationOutcome.HALT
    assert "paper" in result.reason.lower()
    confirmed = observe_live(HackathonSettings(), client=_live_ok_client(account=_account()))
    assert confirmed.outcome == ObservationOutcome.OK
    assert confirmed.portfolio is not None
    assert confirmed.portfolio.paper is True
    assert confirmed.portfolio.options_approved is True


def test_pnl_unreadable_does_not_write_matched(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.ACKNOWLEDGED)
    broker = _fill_broker(payload)
    original_account = broker.fetch_account
    seen = {"n": 0}

    def fetch_account():
        seen["n"] += 1
        if seen["n"] > 1:
            raise ConnectionError("pnl snapshot failed")
        return original_account()

    broker.fetch_account = fetch_account  # type: ignore[method-assign]
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=RecordingMcp(), dry_run=False),
        broker=broker,
        observer=broker,
    )
    row = TradeJournal(tmp_path / "journal.jsonl").evidence.read_all()[-1]
    assert result["outcome"] != "MATCHED"
    assert result["complete"] is False
    assert row["outcome"] != "MATCHED"
    assert "P&L" in result["reason"] or "equity" in result["reason"].lower() or "unreadable" in result["reason"]
    assert store.load(rec.cycle_id).state is not CycleState.COMPLETED


def test_pnl_missing_equity_does_not_write_matched(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.ACKNOWLEDGED)
    broker = _fill_broker(payload)
    broker.account = SimpleNamespace(
        id="PA3V84C40PJQ",
        account_number="PA3V84C40PJQ",
        cash="100120.00",
    )
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=RecordingMcp(), dry_run=False),
        broker=broker,
        observer=broker,
    )
    row = TradeJournal(tmp_path / "journal.jsonl").evidence.read_all()[-1]
    assert result["outcome"] != "MATCHED"
    assert result["complete"] is False
    assert row["outcome"] != "MATCHED"
    assert store.load(rec.cycle_id).state is not CycleState.COMPLETED
