#!/usr/bin/env python3
"""Build sanitized public.jsonl, claim manifest, and evidence page."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.evidence_public import (  # noqa: E402
    MANIFEST_PATH,
    NO_TRADE_JSONL,
    PAGE_PATH,
    PUBLIC_JSONL,
    build_manifest,
    load_jsonl,
    render_evidence_page,
)
from opticycle.ledger import EvidenceLedger, canonical_dumps, current_commit_sha  # noqa: E402
from opticycle.live_matched_fills import FILL_COMMIT_SHA, append_live_matched_episodes  # noqa: E402
from opticycle.replay_matched_chain import append_replay_matched_episode  # noqa: E402


def _sha(payload: dict) -> str:
    return hashlib.sha256(canonical_dumps(payload).encode("utf-8")).hexdigest()


def _replay_records(sha: str) -> list[dict]:
    tmp = Path(tempfile.mkdtemp(prefix="opticycle-public-")) / "ledger.raw.jsonl"
    ledger = EvidenceLedger(tmp)
    candidate = {
        "strategy": "vertical_spread",
        "underlying": "SPY",
        "spread": "bull_put",
        "legs": [
            {"symbol": "SPY260918P00550000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "SPY260918P00540000", "side": "buy", "ratio_qty": "1"},
        ],
        "qty": 1,
        "limit_price": "-1.20",
        "order_class": "mleg",
    }
    candidate["payload_hash"] = _sha(candidate)
    ledger.append_episode(
        channel="replay",
        outcome="NO_TRADE",
        reason="keyless replay dry-run preview; not a live order",
        commit_sha=sha,
        fields={
            "thesis": {
                "stance": "BULLISH",
                "reason_code": "TREND_ALIGNED",
                "accepted": True,
                "confidence": "0.70",
            },
            "candidate_set": candidate,
            "certificate": {
                "approval": True,
                "veto": False,
                "payload_hash": candidate["payload_hash"],
                "binding_hash": _sha({"payload_hash": candidate["payload_hash"], "approval": True}),
                "reasons": [],
            },
            "mcp_attempt": {
                "dry_run": True,
                "submitted": False,
                "tool": "place_option_order",
                "order_class": "mleg",
            },
            "code_build_id": sha,
        },
        extra={"live_fill_claimed": False},
    )
    ledger.append_episode(
        channel="replay",
        outcome="VETO",
        reason="risk certificate veto (replay)",
        commit_sha=sha,
        fields={
            "thesis": {"stance": "BEARISH", "reason_code": "LOW_CONFIDENCE", "accepted": False},
            "candidate_set": {"payload_hash": candidate["payload_hash"], "rejected": True},
            "certificate": {
                "approval": False,
                "veto": True,
                "payload_hash": candidate["payload_hash"],
                "reasons": ["stale quote"],
            },
            "code_build_id": sha,
        },
    )
    ledger.append_episode(
        channel="fault_injection",
        outcome="ERROR",
        reason="injected observation failure",
        commit_sha=sha,
        fields={
            "snapshot": {"outcome": "HALT", "reason": "fault injection", "has_evidence": False},
            "code_build_id": sha,
        },
        extra={"fault_injection": True},
    )
    append_replay_matched_episode(ledger, commit_sha=sha)
    append_live_matched_episodes(ledger, commit_sha=FILL_COMMIT_SHA)
    return ledger.export_public()


def main() -> int:
    sha = current_commit_sha()
    no_trade = load_jsonl(NO_TRADE_JSONL)
    if not no_trade:
        print("missing Gate 9 artifacts/evidence/no_trade.public.jsonl", file=sys.stderr)
        return 1
    extras = _replay_records(sha)
    combined: list[dict] = []
    seen: set[str] = set()
    for row in no_trade + extras:
        record_id = str(row.get("record_id") or "")
        if record_id in seen:
            continue
        seen.add(record_id)
        combined.append(row)
    PUBLIC_JSONL.parent.mkdir(parents=True, exist_ok=True)
    # Keep Gate 9 no_trade.public.jsonl byte-stable; public.jsonl holds extras only.
    PUBLIC_JSONL.write_text("".join(canonical_dumps(row) + "\n" for row in extras), encoding="utf-8")
    manifest = build_manifest(combined)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    claims_path = PUBLIC_JSONL.parent / "claims.json"
    claims_path.write_text(json.dumps(manifest["claims"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PAGE_PATH.write_text(render_evidence_page(combined, manifest), encoding="utf-8")
    print(f"records={len(combined)} claims={len(manifest['claims'])} sha={sha}")
    print(f"page={PAGE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
