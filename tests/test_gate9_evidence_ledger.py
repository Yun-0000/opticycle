"""Gate 9: append-only publicly-verifiable Evidence Ledger.

No live MLEG submit, live broker receipt, or live fill is claimed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from opticycle.journal import TradeJournal
from opticycle.ledger import (
    EPISODE_FIELDS,
    LIVE_PAPER_INCOMPLETE,
    AppendOnlyError,
    EvidenceLedger,
    current_commit_sha,
    make_claim,
    parse_claim,
    public_contains_secrets,
    sanitize,
)
from opticycle.protocol import ObservationOutcome, ThesisStance
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_NO_TRADE = ROOT / "artifacts" / "evidence" / "no_trade.public.jsonl"
CLAIMS_PATH = ROOT / "artifacts" / "evidence" / "claims.json"


class _MissingQuoteObserver:
    """Live observation path with an account and no quote → real NO_TRADE. No order."""

    def fetch_account(self):
        return SimpleNamespace(
            id="PA3V84C40PJQ",
            account_number="PA3V84C40PJQ",
            equity="100000",
            buying_power="100000",
            cash="100000",
            daytrade_count=0,
            options_approved_level="2",
        )

    def fetch_positions(self):
        return []

    def fetch_open_orders(self):
        return []

    def fetch_fills(self):
        return []

    def fetch_clock(self):
        return SimpleNamespace(is_open=True, timestamp=datetime.now(timezone.utc))

    def fetch_quote(self, symbol: str):
        return None

    def fetch_bars(self, symbol: str):
        return {"SPY": []}

    def fetch_option_chain(self, symbol: str):
        return {}

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None):
        return None

    def fetch_orders_by_client_id(self, client_order_id: str):
        return []


def _record_live_no_trade(tmp_path: Path) -> dict:
    journal = TradeJournal(tmp_path / "journal.jsonl")
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=_MissingQuoteObserver(),
        journal=journal,
        provenance="live_paper",
    )
    rows = journal.evidence.read_all()
    assert rows, "live observation path must persist an evidence episode"
    row = rows[-1]
    assert result["outcome"] == ObservationOutcome.NO_TRADE.value
    assert result["order"] is None
    return {"result": result, "row": row, "ledger": journal.evidence}


def test_append_only_retains_profit_loss_veto_error_no_trade_halt(tmp_path: Path) -> None:
    sha = current_commit_sha()
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    outcomes = [
        ("NO_TRADE", "live observation missing quote"),
        ("HALT", "broker unknown"),
        ("VETO", "certificate veto"),
        ("ERROR", "fault injection"),
        ("PROFIT", "replay labeled pnl — not a live fill"),
        ("LOSS", "replay labeled pnl — not a live fill"),
    ]
    channels = {
        "NO_TRADE": "live_paper",
        "HALT": "live_paper",
        "VETO": "live_paper",
        "ERROR": "fault_injection",
        "PROFIT": "replay",
        "LOSS": "replay",
    }
    ids = []
    for outcome, reason in outcomes:
        row = ledger.append_episode(
            channel=channels[outcome],
            outcome=outcome,
            reason=reason,
            commit_sha=sha,
        )
        ids.append(row["record_id"])
    kept = ledger.read_all()
    assert [item["outcome"] for item in kept] == [item[0] for item in outcomes]
    assert [item["seq"] for item in kept] == list(range(1, 7))
    assert len({item["record_id"] for item in kept}) == 6
    replayed = [item["channel"] for item in kept]
    assert "replay" in replayed and "live_paper" in replayed and "fault_injection" in replayed
    assert ledger.read_all()[0]["record_id"] == ids[0]


def test_no_selective_delete(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    ledger.append_episode(
        channel="live_paper",
        outcome="NO_TRADE",
        reason="keep me",
        commit_sha=current_commit_sha(),
    )
    journal = TradeJournal(tmp_path / "journal.jsonl", evidence=ledger)
    for obj in (ledger, journal):
        with pytest.raises(AppendOnlyError, match="append-only"):
            obj.delete()
        with pytest.raises(AppendOnlyError, match="append-only"):
            obj.clear()
        with pytest.raises(AppendOnlyError, match="append-only"):
            obj.purge()
        with pytest.raises(AppendOnlyError, match="append-only"):
            obj.overwrite()
    src = (ROOT / "src" / "opticycle" / "ledger.py").read_text(encoding="utf-8")
    assert "open(\"w\"" not in src
    assert "open('w'" not in src
    assert "unlink(" not in src
    private = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(private) == 1


def test_episode_completeness_and_live_paper_does_not_claim_fill(tmp_path: Path) -> None:
    sha = current_commit_sha()
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    row = ledger.append_episode(
        channel="live_paper",
        outcome="NO_TRADE",
        reason="schema ready; no live fill",
        commit_sha=sha,
        fields={
            "mcp_attempt": {"id": "fake-live-order", "submitted": True},
            "broker_receipt": {"status": "filled"},
            "reconciliation": {"status": "matched"},
            "realized_pnl": "12.00",
            "unrealized_pnl": "3.00",
        },
    )
    episode = row["episode"]
    for name in EPISODE_FIELDS:
        assert name in episode
        assert "present" in episode[name]
        assert "value" in episode[name]
        assert "reason" in episode[name]
    assert episode["code_build_id"]["value"] == sha
    for blocked in ("mcp_attempt", "broker_receipt", "reconciliation", "realized_pnl", "unrealized_pnl"):
        assert episode[blocked]["present"] is False
        assert episode[blocked]["value"] is None
        assert "Yun confirms" in (episode[blocked]["reason"] or "")
    assert row["live_paper_incomplete"] == LIVE_PAPER_INCOMPLETE
    assert row["live_paper_incomplete"]["live_mleg_submit"] is False
    assert row["episode"]["reconciliation"]["value"] is None


def test_live_observation_no_trade_is_retained(tmp_path: Path) -> None:
    captured = _record_live_no_trade(tmp_path)
    row = captured["row"]
    result = captured["result"]
    assert result["outcome"] == "NO_TRADE"
    assert result["order"] is None
    assert result["submitted"] is False
    assert row["channel"] == "live_paper"
    assert row["outcome"] == "NO_TRADE"
    assert row["episode"]["snapshot"]["present"] is True
    datums = row["episode"]["snapshot"]["value"]["datums"]
    assert datums, "snapshot must retain live observation datums"
    assert any("quote" in str(item.get("detail", "")).lower() or item.get("kind") == "quote" for item in datums)
    assert row["episode"]["mcp_attempt"]["present"] is False
    assert row["episode"]["broker_receipt"]["present"] is False
    assert row["episode"]["reconciliation"]["present"] is False
    assert row["commit_sha"] == current_commit_sha()
    assert captured["ledger"].read_all()[-1]["record_id"] == row["record_id"]


def test_replay_and_fault_injection_are_distinguishable(tmp_path: Path) -> None:
    sha = current_commit_sha()
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    replay = ledger.append_episode(channel="replay", outcome="LOSS", reason="replay", commit_sha=sha)
    fault = ledger.append_episode(channel="fault_injection", outcome="ERROR", reason="injected", commit_sha=sha)
    live = ledger.append_episode(channel="live_paper", outcome="HALT", reason="halt", commit_sha=sha)
    assert replay["channel"] != fault["channel"] != live["channel"]
    assert replay["ledger_class"] == "private_raw"
    public = ledger.export_public()
    channels = {item["channel"] for item in public}
    assert channels == {"replay", "fault_injection", "live_paper"}
    journal = TradeJournal(tmp_path / "journal.jsonl")
    from tests.fixtures.market import make_pin_market

    dry = run_once(
        HackathonSettings(),
        dry_run=True,
        journal=journal,
        market=make_pin_market(),
        provenance="replay",
        stance=ThesisStance.BULLISH,
    )
    assert dry["channel"] == "replay"
    assert dry["submitted"] is False
    fault_run = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=_MissingQuoteObserver(),
        journal=TradeJournal(tmp_path / "fault-journal.jsonl"),
        provenance="fault_injection",
    )
    assert fault_run["channel"] == "fault_injection"
    assert fault_run["outcome"] == "NO_TRADE"


def test_claim_maps_to_exact_record_id_and_commit_sha(tmp_path: Path) -> None:
    sha = current_commit_sha()
    captured = _record_live_no_trade(tmp_path)
    row = captured["row"]
    claim = row["claim"]
    parsed = parse_claim(claim)
    assert parsed["record_id"] == row["record_id"]
    assert parsed["commit_sha"] == row["commit_sha"] == sha
    assert parsed["outcome"] == "NO_TRADE"
    resolved = captured["ledger"].resolve_claim(claim)
    assert resolved["record_id"] == row["record_id"]
    rebuilt = make_claim(record_id=row["record_id"], commit_sha=sha, outcome="NO_TRADE")
    assert rebuilt == claim
    with pytest.raises(Exception):
        captured["ledger"].resolve_claim(
            make_claim(record_id=row["record_id"], commit_sha="0" * 40, outcome="NO_TRADE")
        )


def test_sanitizer_is_reproducible_and_strips_secrets(tmp_path: Path) -> None:
    sha = current_commit_sha()
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    ledger.append_episode(
        channel="live_paper",
        outcome="NO_TRADE",
        reason="sanitize me",
        commit_sha=sha,
        fields={
            "snapshot": {
                "account_id": "PA3V84C40PJQ",
                "ALPACA_SECRET_KEY": "super-secret-value",
                "detail": "quote missing",
            }
        },
        extra={"ALPACA_API_KEY": "key-material", "note": "ok"},
    )
    first = ledger.export_public(tmp_path / "public-a.jsonl")
    second = ledger.export_public(tmp_path / "public-b.jsonl")
    assert first == second
    assert (tmp_path / "public-a.jsonl").read_text(encoding="utf-8") == (
        tmp_path / "public-b.jsonl"
    ).read_text(encoding="utf-8")
    public = first[0]
    blob = json.dumps(public)
    assert "super-secret-value" not in blob
    assert "key-material" not in blob
    assert "PA3V84C40PJQ" not in blob
    assert public["ledger_class"] == "public_sanitized"
    assert public["derived_from"]["record_id"] == ledger.read_all()[0]["record_id"]
    assert public["derived_from"]["commit_sha"] == sha
    assert public_contains_secrets(public) == []
    assert sanitize(public) == public


def test_committed_public_no_trade_episode_is_verifiable() -> None:
    assert PUBLIC_NO_TRADE.is_file(), "Gate 9 must record a real NO_TRADE public episode"
    rows = [
        json.loads(line)
        for line in PUBLIC_NO_TRADE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows, "public ledger export must be non-empty"
    no_trade = next(item for item in rows if item["outcome"] == "NO_TRADE")
    assert no_trade["channel"] == "live_paper"
    assert no_trade["ledger_class"] == "public_sanitized"
    for name in EPISODE_FIELDS:
        assert name in no_trade["episode"]
    assert no_trade["episode"]["mcp_attempt"]["present"] is False
    assert no_trade["episode"]["broker_receipt"]["present"] is False
    assert no_trade["episode"]["reconciliation"]["present"] is False
    assert no_trade["live_paper_incomplete"]["live_fill"] is False
    blob = json.dumps(no_trade)
    assert "super-secret" not in blob
    assert '"status":"matched"' not in blob.lower()
    claims = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    claim = no_trade["claim"]
    mapped = claims[claim]
    assert mapped["record_id"] == no_trade["record_id"]
    assert mapped["commit_sha"] == no_trade["commit_sha"]
    parsed = parse_claim(claim)
    assert parsed["record_id"] == no_trade["record_id"]
    assert parsed["commit_sha"] == no_trade["commit_sha"]
    assert len(parsed["commit_sha"]) == 40
