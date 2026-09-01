"""Gate 11: live-paper evidence path, fixture P&L reconcile, honest quote gap."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from opticycle.evidence_public import GATE11_STATUS_PATH, MANIFEST_PATH, NO_TRADE_JSONL, PAGE_PATH, load_public_records
from opticycle.ledger import EvidenceLedger, current_commit_sha
from opticycle.live_quotes import probe_live_quotes
from opticycle.paper_fill_ingest import (
    FillIngestError,
    REQUIRED_FILL_FIELDS,
    ingest_sanitized_fill,
    validate_sanitized_fill,
    waiting_status,
)
from opticycle.pnl import (
    PnlError,
    SOURCE_FIXTURE,
    SOURCE_LIVE_BROKER,
    may_claim_live_pnl,
    pnl_from_snapshot,
    refuse_live_stamp,
    snapshot_from_objects,
    would_record_live_fill_episode,
)

ROOT = Path(__file__).resolve().parents[1]
PLAN_SHA = "aabf9a2813ce393c46931607cbb26f4762e0472dc3787f186995b9358f3e3396"
NO_TRADE_SHA = "1ca34e086e20246c9025da8ebcfa3633642b523185c7041e71d45622857aecf9"


def _fixture_matched():
    return snapshot_from_objects(
        account={"equity": "100150.00", "cash": "99000.00", "long_market_value": "1150.00"},
        positions=[
            {
                "symbol": "SPY260918P00550000",
                "qty": "1",
                "market_value": "1150.00",
                "unrealized_pl": "50.00",
            }
        ],
        fills=[{"symbol": "SPY260918P00550000", "qty": "1", "realized_pl": "100.00", "status": "filled"}],
        source=SOURCE_FIXTURE,
    )


def test_pnl_reconciles_to_fixture_broker_snapshot() -> None:
    snapshot = _fixture_matched()
    report = pnl_from_snapshot(snapshot)
    assert report.matched is True
    assert report.source == SOURCE_FIXTURE
    assert report.live_claimed is False
    assert report.end_of_cycle_equity == Decimal("100150.00")
    assert report.unrealized_pnl is not None
    assert report.realized_present is True
    assert report.realized_pnl is not None
    identity = next(item for item in report.comparisons if item.field == "equity_identity")
    assert identity.matched is True


def test_pnl_mismatch_does_not_invent_equity() -> None:
    snapshot = snapshot_from_objects(
        account={"equity": "100000.00", "cash": "50000.00", "long_market_value": "40000.00"},
        positions=[{"market_value": "40000.00", "unrealized_pl": "0"}],
        fills=[],
        source=SOURCE_FIXTURE,
    )
    report = pnl_from_snapshot(snapshot)
    assert report.matched is False
    assert "equity_identity" in report.discrepancies
    assert report.live_claimed is False


def test_fixture_numbers_cannot_be_stamped_live() -> None:
    snapshot = _fixture_matched()
    assert may_claim_live_pnl(snapshot, real_fill=True) is False
    assert may_claim_live_pnl(snapshot, real_fill=False) is False
    with pytest.raises(PnlError, match="fixture"):
        refuse_live_stamp(snapshot, real_fill=True)
    live_shaped = snapshot_from_objects(
        account={"equity": "100150.00", "cash": "99000.00", "long_market_value": "1150.00"},
        positions=[],
        fills=[],
        source=SOURCE_LIVE_BROKER,
    )
    assert may_claim_live_pnl(live_shaped, real_fill=False) is False
    with pytest.raises(PnlError, match="incomplete"):
        refuse_live_stamp(live_shaped, real_fill=False)


def test_would_record_live_fill_is_dry_run_and_unclaimed() -> None:
    preview = would_record_live_fill_episode(
        snapshot=_fixture_matched(),
        mcp_attempt={"dry_run": True, "submitted": False, "tool": "place_option_order"},
        broker_receipt={"present": False},
        reconciliation={"present": False},
    )
    assert preview["submitted"] is False
    assert preview["live_fill_claimed"] is False
    assert preview["live_mleg_submit"] is False
    assert preview["snapshot_source"] == SOURCE_FIXTURE
    assert "Yun" in preview["blocked"]


def test_record_live_fill_script_cannot_submit() -> None:
    denied = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "record-live-fill-episode.py"), "--submit"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 2
    assert "cannot submit" in denied.stderr or "Yun" in denied.stderr
    preview = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "record-live-fill-episode.py"), "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert preview.returncode == 0
    payload = json.loads(preview.stdout)
    assert payload["live_fill_claimed"] is False
    assert payload["submitted"] is False


def test_old_demo_artifacts_are_deleted() -> None:
    assert not (ROOT / "docs" / "DEMO_SHOTLIST.md").exists()
    assert not (ROOT / "artifacts" / "demo.mp4").exists()
    assert not (ROOT / "artifacts" / "DEMO_NOT_SUBMISSION.md").exists()
    assert not (ROOT / "artifacts" / "demo.mp4.NOT_SUBMISSION").exists()
    assert not (ROOT / "artifacts" / "opticycle-demo.mp4").exists()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    html = PAGE_PATH.read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "hackathon-tests.yml").read_text(encoding="utf-8")
    for blob in (readme, html, workflow):
        assert "DEMO_SHOTLIST.md" not in blob
        assert "artifacts/demo.mp4" not in blob
        assert "DEMO_NOT_SUBMISSION" not in blob
        assert "opticycle-demo.mp4" not in blob


def test_injected_no_trade_not_promoted_and_fill_incomplete() -> None:
    digest = hashlib.sha256(NO_TRADE_JSONL.read_bytes()).hexdigest()
    assert digest == NO_TRADE_SHA
    status = json.loads(GATE11_STATUS_PATH.read_text(encoding="utf-8"))
    assert status["live_fill_claimed"] is True
    assert status["genuine_no_trade_recorded"] is True
    assert status["injected_no_trade_promoted"] is False
    assert status["live_quotes_available"] is True
    assert status["observation_reason"] == "SPY quote is stale"
    assert status["yun_authorized_one_paper_mleg"] is True
    assert status["matched_claimed"] is True
    assert status["llm_episode_recorded"] is True
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["live_fill_claimed"] is True
    assert manifest.get("injected_no_trade_promoted") is False
    html = PAGE_PATH.read_text(encoding="utf-8")
    assert "NOT fill evidence" in html
    assert "injected missing quote" in html
    from opticycle.evidence_public import is_live_fill_row

    for row in load_public_records():
        if is_live_fill_row(row):
            continue
        if row.get("channel") == "live_paper":
            for blocked in ("mcp_attempt", "broker_receipt", "reconciliation", "realized_pnl", "unrealized_pnl"):
                assert row["episode"][blocked]["present"] is False


def test_probe_live_quotes_is_honest_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    probe = probe_live_quotes()
    assert probe["available"] is False
    assert probe["genuine_no_trade_recorded"] is False
    assert "credentials" in probe["reason"]


def test_plan_md_unchanged() -> None:
    digest = hashlib.sha256((ROOT / "PLAN.md").read_bytes()).hexdigest()
    assert digest == PLAN_SHA


def test_snapshot_from_namespace_objects() -> None:
    account = SimpleNamespace(equity="100000", cash="100000", long_market_value="0")
    snapshot = snapshot_from_objects(account=account, positions=[], fills=[], source=SOURCE_FIXTURE)
    report = pnl_from_snapshot(snapshot)
    assert report.matched is True
    assert report.live_claimed is False
    assert report.realized_present is False


def test_equity_identity_uses_alpaca_signed_short_market_value() -> None:
    snapshot = snapshot_from_objects(
        account={
            "equity": "100010.9",
            "cash": "100261.9",
            "long_market_value": "904",
            "short_market_value": "-1155",
        },
        positions=[
            {"symbol": "SPY260925C00768000", "qty": "-1", "market_value": "-892", "unrealized_pl": "-24"},
            {"symbol": "SPY260925C00769000", "qty": "1", "market_value": "834", "unrealized_pl": "17"},
            {"symbol": "SPY261009C00793000", "qty": "-1", "market_value": "-263", "unrealized_pl": "32"},
            {"symbol": "SPY261009C00809000", "qty": "1", "market_value": "70", "unrealized_pl": "-14"},
        ],
        fills=[],
        source=SOURCE_LIVE_BROKER,
    )
    report = pnl_from_snapshot(snapshot)
    assert report.matched is True
    assert report.live_claimed is False
    assert report.end_of_cycle_equity == Decimal("100010.9")
    assert report.unrealized_pnl == Decimal("11")
    assert report.realized_present is False


def _sample_fill_json() -> dict:
    return {
        "order_id": "test-ord-not-live",
        "client_order_id": "oc-test-not-live",
        "limit": "1.20",
        "status": "filled",
        "filled_avg_price": "1.21",
        "legs": [
            {"symbol": "SPY260918P00550000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "SPY260918P00540000", "side": "buy", "ratio_qty": "1"},
        ],
    }


def test_waiting_hook_does_not_invent_matched() -> None:
    status = waiting_status()
    assert status["yun_authorized_one_paper_mleg"] is True
    assert status["cloud_submit"] is False
    assert status["sanitized_json_provided"] is False
    assert status["live_fill_claimed"] is False
    assert status["matched_claimed"] is False
    assert list(status["waiting_for"]) == list(REQUIRED_FILL_FIELDS)
    waiting = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ingest-paper-fill.py")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert waiting.returncode == 0
    payload = json.loads(waiting.stdout)
    assert payload["live_fill_claimed"] is False
    assert payload["matched_claimed"] is False


def test_incomplete_fill_json_is_rejected() -> None:
    with pytest.raises(FillIngestError, match="missing fields"):
        validate_sanitized_fill({"order_id": "test-ord-not-live"})
    with pytest.raises(FillIngestError, match="account id"):
        validate_sanitized_fill({**_sample_fill_json(), "note": "PA3V84C40PJQ"})


def test_ingested_sanitized_json_records_receipt_but_not_matched(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.raw.jsonl")
    row = ingest_sanitized_fill(
        ledger=ledger,
        payload=_sample_fill_json(),
        commit_sha=current_commit_sha(),
    )
    assert row["channel"] == "live_paper"
    assert row["extra"]["live_fill_claimed"] is False
    assert row["extra"]["matched_claimed"] is False
    assert row["episode"]["broker_receipt"]["present"] is True
    receipt = row["episode"]["broker_receipt"]["value"]
    assert receipt["order_id"] == "test-ord-not-live"
    assert receipt["client_order_id"] == "oc-test-not-live"
    assert receipt["status"] == "filled"
    assert len(receipt["legs"]) == 2
    assert row["episode"]["reconciliation"]["present"] is False
    assert row["episode"]["realized_pnl"]["present"] is False
    assert row["episode"]["unrealized_pnl"]["present"] is False
    blob = json.dumps(row).lower()
    assert '"status":"matched"' not in blob
    assert row["outcome"] != "PROFIT"


def test_ingest_script_submit_is_refused() -> None:
    denied = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ingest-paper-fill.py"), "--submit"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 2
    missing = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ingest-paper-fill.py"), "--from-json", "/no/such/fill.json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 3
