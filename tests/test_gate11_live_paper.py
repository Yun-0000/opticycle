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
from opticycle.live_quotes import probe_live_quotes
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


def test_shotlist_matches_locked_product() -> None:
    text = (ROOT / "docs" / "DEMO_SHOTLIST.md").read_text(encoding="utf-8").lower()
    assert "wheel" not in text
    assert "cli fallback" not in text
    assert "alpaca order submit" not in text
    assert "channel switch" not in text or "no channel switch" in text
    assert "defined-risk" in text
    assert "alpaca-mcp-server==2.3.0" in text
    assert "mleg" in text
    assert "certificate" in text
    assert "reconcile" in text
    assert "ledger" in text
    assert "not submission footage" in text


def test_demo_mp4_labeled_not_for_submit() -> None:
    assert (ROOT / "artifacts" / "demo.mp4").is_file()
    label = (ROOT / "artifacts" / "DEMO_NOT_SUBMISSION.md").read_text(encoding="utf-8").lower()
    sidecar = (ROOT / "artifacts" / "demo.mp4.NOT_SUBMISSION").read_text(encoding="utf-8").lower()
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    html = PAGE_PATH.read_text(encoding="utf-8").lower()
    for blob in (label, sidecar, readme, html):
        assert "not submission" in blob or "not submission footage" in blob
    assert "gate 12" in label


def test_injected_no_trade_not_promoted_and_fill_incomplete() -> None:
    digest = hashlib.sha256(NO_TRADE_JSONL.read_bytes()).hexdigest()
    assert digest == NO_TRADE_SHA
    status = json.loads(GATE11_STATUS_PATH.read_text(encoding="utf-8"))
    assert status["live_fill_claimed"] is False
    assert status["genuine_no_trade_recorded"] is False
    assert status["injected_no_trade_promoted"] is False
    assert status["live_quotes_available"] is False
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["live_fill_claimed"] is False
    assert manifest.get("injected_no_trade_promoted") is False
    html = PAGE_PATH.read_text(encoding="utf-8")
    assert "NOT fill evidence" in html
    assert "injected missing quote" in html
    for row in load_public_records():
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
