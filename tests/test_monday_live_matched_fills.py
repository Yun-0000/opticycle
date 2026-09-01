"""Two authorized live_paper broker fills; not price-bound MATCHED."""

from __future__ import annotations

import json
from decimal import Decimal
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
from opticycle.broker_lookup import MONDAY_BROKER_ORDER_ID, WEEKEND_BROKER_ORDER_ID
from opticycle.live_matched_fills import (
    FILL_COMMIT_SHA,
    LIVE_MATCHED_CLIENT_IDS,
    MONDAY_CLIENT_ORDER_ID,
    WEEKEND_CLIENT_ORDER_ID,
    LiveFillError,
    append_live_matched_episodes,
    is_authorized_live_matched,
    live_record_id,
    require_live_matched_fill,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_RECORD_IDS = {
    live_record_id(WEEKEND_CLIENT_ORDER_ID): WEEKEND_CLIENT_ORDER_ID,
    live_record_id(MONDAY_CLIENT_ORDER_ID): MONDAY_CLIENT_ORDER_ID,
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
        assert row["outcome"] == "FILLED"
        assert row["extra"]["live_fill_claimed"] is True
        assert row["extra"]["matched_claimed"] is False
        assert row["episode"]["reconciliation"]["value"]["price_bound_matched"] is False
        assert row["episode"]["reconciliation"]["value"]["credit_better_bound"] is False
        assert row["episode"]["reconciliation"]["value"]["limit_sign_error"] is True
        assert row["episode"]["broker_receipt"]["value"]["broker_order_id"] in {
            WEEKEND_BROKER_ORDER_ID,
            MONDAY_BROKER_ORDER_ID,
        }
        assert row["extra"]["broker_order_id_present"] is True
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
    assert row["episode"]["reconciliation"]["value"]["fill_credit"] == "2.11"
    recon = row["episode"]["reconciliation"]["value"]
    assert recon["price_bound_matched"] is False
    monday = append_live_matched_episodes(EvidenceLedger(tmp_path / "other.jsonl"))[1]
    assert monday["episode"]["end_of_cycle_equity"]["present"] is False
    assert monday["extra"]["fill_max_loss"] == "49"
    assert Decimal(str(monday["episode"]["reconciliation"]["value"]["fill_max_loss"])) == Decimal("49.00")


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
    assert "not price-bound MATCHED" in html
    for row in live:
        require_live_matched_fill(row)
        parsed = parse_claim(row["claim"])
        assert parsed["commit_sha"] == row["commit_sha"]
        assert parsed["outcome"] == "FILLED"
        assert COMMIT_SHA_RE.fullmatch(row["commit_sha"])
        assert row["commit_sha"] == FILL_COMMIT_SHA
        assert row["outcome"] == "FILLED"
        assert row["client_order_id"] in html
        assert row["commit_sha"] in html
        assert row["client_order_id"] in public
        mapped = manifest["claims"][row["claim"]]
        assert mapped["live_fill"] is True
        assert mapped["channel"] == "live_paper"
        assert mapped["outcome"] == "FILLED"
        assert mapped["commit_sha"] == FILL_COMMIT_SHA
    assert "bars_heuristic_no_llm_key" in html
    assert WEEKEND_BROKER_ORDER_ID in html
    assert MONDAY_BROKER_ORDER_ID in html
    assert "PA3V84C40PJQ" not in html
    assert "PA3V84C40PJQ" not in public
    replayed = replay_sanitized_records(records)
    assert {item["client_order_id"] for item in live} == set(LIVE_MATCHED_CLIENT_IDS)
    live_verified = [item for item in replayed if item["live_fill"] and item["outcome"] == "FILLED"]
    assert len(live_verified) == 2
    signed_verified = [item for item in replayed if item["live_fill"] and item["outcome"] == "MATCHED"]
    assert len(signed_verified) == 1
    replay_matched = [
        row for row in records if row.get("outcome") == "MATCHED" and row.get("channel") == "replay"
    ]
    assert replay_matched
    assert all(not is_authorized_live_matched(row) for row in replay_matched)
    assert all(row["commit_sha"] != FILL_COMMIT_SHA for row in replay_matched)
