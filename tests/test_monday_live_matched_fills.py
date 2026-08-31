"""Two authorized live_paper MATCHED fills; no extras; heuristic stance honest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opticycle.evidence_public import (
    MANIFEST_PATH,
    PAGE_PATH,
    PUBLIC_JSONL,
    is_live_matched_fill,
    load_public_records,
    replay_sanitized_records,
)
from opticycle.ledger import COMMIT_SHA_RE, EvidenceLedger, current_commit_sha, parse_claim
from opticycle.live_matched_fills import (
    LIVE_MATCHED_CLIENT_IDS,
    MONDAY_CLIENT_ORDER_ID,
    WEEKEND_CLIENT_ORDER_ID,
    LiveFillError,
    append_live_matched_episodes,
    is_authorized_live_matched,
    require_live_matched_fill,
)

ROOT = Path(__file__).resolve().parents[1]
FILL_COMMIT_SHA = "c163d63a8a34f679d5a7ad4bc47535cd6ee7cc66"
LIVE_RECORD_IDS = {
    "el-ac177b1c1b344c7587fac4851939f3c2": WEEKEND_CLIENT_ORDER_ID,
    "el-c40cea16e4f2477d89f451de8e1901b4": MONDAY_CLIENT_ORDER_ID,
}


def test_ledger_records_both_authorized_fills_only(tmp_path: Path) -> None:
    sha = current_commit_sha()
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    rows = append_live_matched_episodes(ledger, commit_sha=sha)
    assert [row["client_order_id"] for row in rows] == [
        WEEKEND_CLIENT_ORDER_ID,
        MONDAY_CLIENT_ORDER_ID,
    ]
    blob = json.dumps(rows)
    assert "PA3V84C40PJQ" not in blob
    assert "account_number" not in blob
    for row in rows:
        require_live_matched_fill(row)
        assert row["channel"] == "live_paper"
        assert row["outcome"] == "MATCHED"
        assert row["extra"]["live_fill_claimed"] is True
        assert row["commit_sha"] == sha
        assert COMMIT_SHA_RE.fullmatch(sha)


def test_monday_fill_is_honest_heuristic_not_llm(tmp_path: Path) -> None:
    row = append_live_matched_episodes(EvidenceLedger(tmp_path / "ledger.raw.jsonl"))[1]
    thesis = row["episode"]["thesis"]["value"]
    assert thesis["stance_source"] == "bars_heuristic_no_llm_key"
    assert thesis["model_called"] is False
    assert row["episode"]["mcp_attempt"]["value"]["mcp_submit_count"] == 1
    assert row["episode"]["mcp_attempt"]["value"]["second_submit"] is False
    assert row["episode"]["certificate"]["value"]["approval"] is True


def test_weekend_fill_has_equity_not_invented_pnl(tmp_path: Path) -> None:
    row = append_live_matched_episodes(EvidenceLedger(tmp_path / "ledger.raw.jsonl"))[0]
    assert row["episode"]["end_of_cycle_equity"]["value"] == "100007.95"
    assert row["extra"]["cash"] == "100210.95"
    assert row["episode"]["realized_pnl"]["present"] is False
    assert row["episode"]["reconciliation"]["value"]["credit_fill"] == "2.11"
    monday = append_live_matched_episodes(EvidenceLedger(tmp_path / "other.jsonl"))[1]
    assert monday["episode"]["end_of_cycle_equity"]["present"] is False


def test_unauthorized_live_matched_is_rejected() -> None:
    with pytest.raises(LiveFillError):
        require_live_matched_fill(
            {
                "channel": "live_paper",
                "outcome": "MATCHED",
                "client_order_id": "oc-invented",
                "extra": {"live_fill_claimed": True},
                "episode": {},
            }
        )


def test_committed_public_export_has_both_live_fills() -> None:
    records = load_public_records()
    live = [row for row in records if is_live_matched_fill(row)]
    assert {row["client_order_id"] for row in live} == set(LIVE_MATCHED_CLIENT_IDS)
    assert {row["record_id"] for row in live} == set(LIVE_RECORD_IDS)
    assert len(live) == 2
    html = PAGE_PATH.read_text(encoding="utf-8")
    public = PUBLIC_JSONL.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["live_fill_claimed"] is True
    assert manifest["matched_claimed"] is True
    for row in live:
        require_live_matched_fill(row)
        parsed = parse_claim(row["claim"])
        assert parsed["commit_sha"] == row["commit_sha"]
        assert COMMIT_SHA_RE.fullmatch(row["commit_sha"])
        assert row["commit_sha"] == FILL_COMMIT_SHA
        assert row["client_order_id"] in html
        assert row["commit_sha"] in html
        assert row["client_order_id"] in public
        mapped = manifest["claims"][row["claim"]]
        assert mapped["live_fill"] is True
        assert mapped["channel"] == "live_paper"
        assert mapped["commit_sha"] == FILL_COMMIT_SHA
    assert "bars_heuristic_no_llm_key" in html
    assert "PA3V84C40PJQ" not in html
    assert "PA3V84C40PJQ" not in public
    replayed = replay_sanitized_records(records)
    assert {item["client_order_id"] for item in live} == set(LIVE_MATCHED_CLIENT_IDS)
    live_verified = [item for item in replayed if item["live_fill"]]
    assert len(live_verified) == 2
    replay_matched = [
        row for row in records if row.get("outcome") == "MATCHED" and row.get("channel") == "replay"
    ]
    assert replay_matched
    assert all(not is_authorized_live_matched(row) for row in replay_matched)
    assert all(row["commit_sha"] != FILL_COMMIT_SHA for row in replay_matched)
