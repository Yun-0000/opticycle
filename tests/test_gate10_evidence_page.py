"""Gate 10: public evidence page, claim manifest, keyless replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from opticycle.evidence_public import (
    BROKER_LOOKUP_PATH,
    EPISODE_FIELDS,
    GENUINE_STALE_QUOTE_CAVEAT,
    MANIFEST_PATH,
    NO_TRADE_CAVEAT,
    NO_TRADE_JSONL,
    PAGE_PATH,
    PUBLIC_JSONL,
    UPSTREAM_NAME_TOKENS,
    is_injected_no_trade,
    load_jsonl,
    load_public_records,
    replay_sanitized_records,
    scan_public_text,
)
from opticycle.ledger import COMMIT_SHA_RE, parse_claim

ROOT = Path(__file__).resolve().parents[1]


def test_evidence_page_renders_from_sanitized_export_only() -> None:
    assert PAGE_PATH.is_file()
    html = PAGE_PATH.read_text(encoding="utf-8")
    records = load_public_records()
    assert records
    for row in records:
        assert row.get("ledger_class") == "public_sanitized"
        assert row["record_id"] in html
        assert row["claim"] in html
        assert row["commit_sha"] in html
    for label in (
        "thesis",
        "NO_TRADE / veto",
        "real candidate",
        "Risk Certificate",
        "authorized payload hash",
        "MCP call",
        "broker receipt",
        "reconciliation",
        "P&amp;L / equity",
        "failure episode",
        "commit / build ID",
    ):
        assert label in html
    assert "sanitized-ledger" in html
    assert "private_raw" not in html
    assert "ALPACA_API_KEY" not in html
    assert "ALPACA_SECRET_KEY" not in html
    hits = scan_public_text(html, source="index.html")
    assert hits == []


def test_every_public_claim_maps_to_exact_record_and_commit() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = {row["record_id"]: row for row in load_public_records()}
    assert manifest["live_fill_claimed"] is True
    assert manifest["matched_claimed"] is False
    assert not manifest.get("incomplete_live")
    assert manifest["claims"]
    for claim, mapped in manifest["claims"].items():
        parsed = parse_claim(claim)
        assert COMMIT_SHA_RE.fullmatch(parsed["commit_sha"])
        assert parsed["record_id"] == mapped["record_id"]
        assert parsed["commit_sha"] == mapped["commit_sha"]
        row = records[mapped["record_id"]]
        assert row["commit_sha"] == mapped["commit_sha"]
        assert row["claim"] == claim
        if mapped["live_fill"]:
            assert mapped["live_mleg_submit"] is True
            assert mapped["channel"] == "live_paper"
            assert mapped["outcome"] == "FILLED"
            assert not mapped["incomplete"]
        else:
            assert mapped["live_fill"] is False
            assert mapped["live_mleg_submit"] is False
            assert not mapped.get("incomplete")


def test_keyless_replay_reproduces_non_live_claims() -> None:
    records = load_public_records()
    verified = replay_sanitized_records(records)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert {item["claim"] for item in verified} == set(manifest["claims"])
    assert all(
        (item["live_fill"] is True)
        == (item["channel"] == "live_paper" and item["outcome"] in {"FILLED", "MATCHED"})
        for item in verified
    )
    channels = {item["channel"] for item in verified}
    assert "replay" in channels
    assert "fault_injection" in channels
    assert "live_paper" in channels
    outcomes = {item["outcome"] for item in verified}
    assert "NO_TRADE" in outcomes
    assert "VETO" in outcomes
    assert "ERROR" in outcomes
    assert "MATCHED" in outcomes
    replayed = next(item for item in verified if item["channel"] == "replay" and item["payload_hash"])
    assert COMMIT_SHA_RE.fullmatch(replayed["commit_sha"])
    assert len(replayed["payload_hash"]) == 64


def test_no_trade_public_jsonl_is_not_fill_evidence() -> None:
    rows = load_jsonl(NO_TRADE_JSONL)
    assert rows
    row = rows[0]
    assert row["outcome"] == "NO_TRADE"
    assert is_injected_no_trade(row) is True
    assert row["episode"]["reconciliation"]["present"] is False
    assert row["episode"]["mcp_attempt"]["present"] is False
    blob = json.dumps(row).lower()
    assert "matched" not in blob
    html = PAGE_PATH.read_text(encoding="utf-8")
    assert NO_TRADE_CAVEAT in html
    assert GENUINE_STALE_QUOTE_CAVEAT in html or "SPY quote is stale" in html
    assert "NOT fill evidence" in html
    assert "blocked until Yun" not in html
    assert "Yun confirms" not in html
    assert "TODO:" not in html
    assert "absent on this injected-quote NO_TRADE episode (not fill evidence)" in html
    assert "does not mean live fills are missing" in html
    for field in EPISODE_FIELDS:
        assert field in row["episode"]


def test_live_mleg_fill_claims_record_authorized_matched() -> None:
    from opticycle.evidence_public import is_live_matched_fill

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["live_fill_claimed"] is True
    html = PAGE_PATH.read_text(encoding="utf-8")
    assert "oc-204a8dfccffd40c9" in html
    assert "oc-715ad36a630d408e" in html
    live_count = 0
    for row in load_public_records():
        if is_live_matched_fill(row):
            live_count += 1
            for field in ("mcp_attempt", "broker_receipt", "reconciliation"):
                assert row["episode"][field]["present"] is True
            continue
        if row.get("channel") == "live_paper":
            for blocked in ("mcp_attempt", "broker_receipt", "reconciliation", "realized_pnl", "unrealized_pnl"):
                assert row["episode"][blocked]["present"] is False
    assert live_count == 2


def test_foundation_md_discloses_pinned_upstream() -> None:
    path = ROOT / "FOUNDATION.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Gauss World Trader" in text
    assert "https://github.com/Magica-Chen/GaussWorldTrader" in text
    assert "31374551bae6fd34a0fe56fe11d208f4ff04fbb4" in text
    assert "vendor/pin-31374551/" in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "FOUNDATION.md" in readme
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 Zexun Chen" in license_text
    assert "MIT License" in license_text


def test_upstream_names_stay_out_of_evidence_page() -> None:
    paths = [
        PAGE_PATH,
        PUBLIC_JSONL,
        NO_TRADE_JSONL,
        MANIFEST_PATH,
        BROKER_LOOKUP_PATH,
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        for token in UPSTREAM_NAME_TOKENS:
            assert token.lower() not in lower, f"{path} contains {token!r}"
        assert "PA3V84C40PJQ" not in text


def test_ci_runs_tests_and_public_evidence_checks() -> None:
    workflow = (ROOT / ".github" / "workflows" / "hackathon-tests.yml").read_text(encoding="utf-8")
    assert "python3 -m pytest tests/" in workflow
    assert "scripts/scan-public-evidence.py" in workflow
    assert "scripts/replay-public-evidence.py" in workflow
    assert "scripts/record-live-fill-episode.py" in workflow
    assert "scripts/ingest-paper-fill.py" in workflow
    assert "pull_request" in workflow


def test_plan_md_bytes_unchanged() -> None:
    digest = hashlib.sha256((ROOT / "PLAN.md").read_bytes()).hexdigest()
    assert digest == "aabf9a2813ce393c46931607cbb26f4762e0472dc3787f186995b9358f3e3396"


def test_gate9_no_trade_export_is_byte_stable() -> None:
    digest = hashlib.sha256(NO_TRADE_JSONL.read_bytes()).hexdigest()
    assert digest == "1ca34e086e20246c9025da8ebcfa3633642b523185c7041e71d45622857aecf9"
    claims = json.loads((ROOT / "artifacts" / "evidence" / "claims.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(
        (ROOT / "artifacts" / "evidence" / "claims.json").read_bytes()
    ).hexdigest() == "0a437dc1c294727a19f7c264ed45f8b48e4e4752ff5e921384582a051c5970a1"
    assert "el-6b67a01c2bdd448388e813633f90e890" in json.dumps(claims)
