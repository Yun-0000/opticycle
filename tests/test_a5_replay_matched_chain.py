"""A5: one replay/fixture Decision Episode chains MCP → readback → fill/P&L."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opticycle.cycle import CycleState, CycleStore
from opticycle.evidence_public import (
    MANIFEST_PATH,
    PUBLIC_JSONL,
    load_jsonl,
    load_public_records,
    replay_sanitized_records,
)
from opticycle.journal import TradeJournal
from opticycle.ledger import EvidenceLedger, current_commit_sha, parse_claim
from opticycle.reconcile import HaltLedger
from opticycle.replay_matched_chain import (
    FORBIDDEN_LIVE_CLIENT_ORDER_ID,
    REPLAY_CHANNEL,
    REPLAY_CLIENT_ORDER_ID,
    ChainIncomplete,
    append_replay_matched_episode,
    require_matched_chain,
)
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from tests.test_a4_matched_fill import _fill_broker
from tests.test_gate8_halt_engine import RecordingMcp, _advance


def test_single_episode_contains_mcp_readback_fill_pnl_chain(tmp_path: Path) -> None:
    sha = current_commit_sha()
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    row = append_replay_matched_episode(ledger, commit_sha=sha)
    require_matched_chain(row)
    assert row["channel"] == REPLAY_CHANNEL
    assert row["outcome"] == "MATCHED"
    assert row["commit_sha"] == sha
    assert row["client_order_id"] == REPLAY_CLIENT_ORDER_ID
    assert row["client_order_id"] != FORBIDDEN_LIVE_CLIENT_ORDER_ID
    episode = row["episode"]
    mcp = episode["mcp_attempt"]["value"]
    assert mcp["tool"] == "place_option_order"
    assert mcp["arguments_hash"]
    assert mcp["submitted"] is True
    recon = episode["reconciliation"]["value"]
    assert recon["status"] == "matched"
    assert recon["filled_qty"] == 1
    assert recon["filled_avg_price"]
    assert episode["broker_receipt"]["present"] is True
    assert episode["realized_pnl"]["present"] is True
    assert episode["end_of_cycle_equity"]["present"] is True
    assert row["extra"]["live_fill_claimed"] is False


def test_public_claim_maps_to_that_record_and_this_commit(tmp_path: Path) -> None:
    sha = current_commit_sha()
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    row = append_replay_matched_episode(ledger, commit_sha=sha)
    public = ledger.export_public(tmp_path / "public.jsonl")
    matched = next(item for item in public if item["outcome"] == "MATCHED")
    parsed = parse_claim(matched["claim"])
    assert parsed["record_id"] == matched["record_id"] == row["record_id"]
    assert parsed["commit_sha"] == matched["commit_sha"] == sha == current_commit_sha()
    assert parsed["outcome"] == "MATCHED"
    verified = replay_sanitized_records(public)
    hit = next(item for item in verified if item["record_id"] == row["record_id"])
    assert hit["commit_sha"] == sha
    assert hit["live_fill"] is False
    assert hit["channel"] == REPLAY_CHANNEL


def test_missing_any_hop_fails_the_chain() -> None:
    sha = current_commit_sha()
    broken = {
        "channel": "replay",
        "outcome": "MATCHED",
        "cycle_id": "cycle-x",
        "client_order_id": "oc-replay-missing",
        "commit_sha": sha,
        "claim": f"opticycle:v1:MATCHED:el-x:{sha}",
        "extra": {"live_fill_claimed": False},
        "episode": {
            "mcp_attempt": {"present": False, "value": None, "reason": "missing"},
            "broker_receipt": {"present": True, "value": {"broker_order_id": "x"}, "reason": None},
            "reconciliation": {
                "present": True,
                "value": {"status": "matched", "filled_qty": 1, "filled_avg_price": "1.20"},
                "reason": None,
            },
            "realized_pnl": {"present": True, "value": "1", "reason": None},
            "unrealized_pnl": {"present": True, "value": "1", "reason": None},
            "end_of_cycle_equity": {"present": True, "value": "100000", "reason": None},
            "candidate_set": {"present": True, "value": {"payload_hash": "ab" * 32}, "reason": None},
        },
    }
    with pytest.raises(ChainIncomplete, match="mcp_attempt"):
        require_matched_chain(broken)


def test_live_fill_claimed_stays_false_on_replay_chain(tmp_path: Path) -> None:
    row = append_replay_matched_episode(EvidenceLedger(tmp_path / "ledger.raw.jsonl"))
    assert row["extra"]["live_fill_claimed"] is False
    assert row["outcome"] != "HALT"


def test_forbidden_live_client_id_is_not_matched() -> None:
    with pytest.raises(ChainIncomplete, match="oc-204a8dfccffd40c9"):
        require_matched_chain(
            {
                "channel": "replay",
                "outcome": "MATCHED",
                "client_order_id": FORBIDDEN_LIVE_CLIENT_ORDER_ID,
                "cycle_id": "x",
                "commit_sha": current_commit_sha(),
                "extra": {"live_fill_claimed": False},
                "episode": {},
            }
        )


def test_runner_matched_path_records_mcp_readback_fill_pnl(tmp_path: Path) -> None:
    store = CycleStore(tmp_path / "cycles.sqlite")
    rec, payload, _cert = _advance(store, CycleState.ACKNOWLEDGED)
    mcp = RecordingMcp()
    broker = _fill_broker(payload)
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        provenance="replay",
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        halt_ledger=HaltLedger(tmp_path / "halt.json"),
        cycle_store=store,
        mcp_executor=AlpacaMcpExecutor(client=mcp, dry_run=False),
        broker=broker,
        observer=broker,
    )
    row = TradeJournal(tmp_path / "journal.jsonl").evidence.read_all()[-1]
    assert result["outcome"] == "MATCHED"
    assert row["channel"] == "replay"
    assert row["client_order_id"] != FORBIDDEN_LIVE_CLIENT_ORDER_ID
    require_matched_chain(row)
    assert row["extra"]["live_fill_claimed"] is False
    assert rec.cycle_id == row["cycle_id"]
    assert payload.client_order_id == row["client_order_id"]
    assert payload.payload_hash == row["episode"]["candidate_set"]["value"]["payload_hash"]
    assert mcp.calls == []


def test_committed_public_export_has_replay_matched_chain() -> None:
    records = load_public_records()
    matched = [row for row in records if row.get("outcome") == "MATCHED" and row.get("channel") == "replay"]
    assert matched, "public evidence must include one replay MATCHED chain"
    row = matched[0]
    require_matched_chain(row)
    assert row["client_order_id"] != FORBIDDEN_LIVE_CLIENT_ORDER_ID
    parsed = parse_claim(row["claim"])
    assert parsed["record_id"] == row["record_id"]
    assert parsed["commit_sha"] == row["commit_sha"]
    from opticycle.ledger import COMMIT_SHA_RE
    assert COMMIT_SHA_RE.fullmatch(parsed["commit_sha"])
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["claims"][row["claim"]]["live_fill"] is False
    verified = replay_sanitized_records(load_jsonl(PUBLIC_JSONL))
    assert any(item["claim"] == row["claim"] for item in verified)
