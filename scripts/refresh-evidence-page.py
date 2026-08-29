#!/usr/bin/env python3
"""Refresh the public evidence page from existing sanitized exports + Gate 11 status."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.evidence_public import (  # noqa: E402
    MANIFEST_PATH,
    PAGE_PATH,
    build_manifest,
    load_gate11_status,
    load_public_records,
    render_evidence_page,
)


def main() -> int:
    records = load_public_records()
    if not records:
        print("no sanitized public records", file=sys.stderr)
        return 1
    manifest = build_manifest(records)
    status = load_gate11_status()
    manifest["genuine_no_trade_recorded"] = bool(status.get("genuine_no_trade_recorded"))
    manifest["live_quotes_available"] = bool(status.get("live_quotes_available"))
    manifest["injected_no_trade_promoted"] = False
    manifest["demo_mp4"] = status.get("demo_mp4") or "NOT submission footage"
    manifest["live_fill_claimed"] = False
    manifest["matched_claimed"] = False
    manifest["yun_authorized_one_paper_mleg"] = True
    manifest["sanitized_json_provided"] = bool(status.get("sanitized_json_provided"))
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PAGE_PATH.write_text(render_evidence_page(records, manifest, status=status), encoding="utf-8")
    print(f"page={PAGE_PATH} claims={len(manifest['claims'])} live_fill={manifest['live_fill_claimed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
