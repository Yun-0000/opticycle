#!/usr/bin/env python3
"""Preview the live-fill ledger path. Cloud VM must not submit.

Yun authorized one paper MLEG. Ingest sanitized broker JSON via
scripts/ingest-paper-fill.py --from-json. Do not invent MATCHED.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.pnl import (  # noqa: E402
    SOURCE_FIXTURE,
    refuse_live_stamp,
    snapshot_from_objects,
    would_record_live_fill_episode,
)

SUBMIT_BLOCKED = "Yun authorized one paper MLEG; cloud VM has no keys and must not place it"


def _fixture_snapshot():
    return snapshot_from_objects(
        account={"equity": "100150.00", "cash": "99000.00", "long_market_value": "1150.00"},
        positions=[{"symbol": "SPY260918P00550000", "qty": "1", "market_value": "1150.00", "unrealized_pl": "50.00"}],
        fills=[{"symbol": "SPY260918P00550000", "qty": "1", "realized_pl": "100.00", "status": "filled"}],
        source=SOURCE_FIXTURE,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run live-fill ledger path (no submit)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Refused: this environment cannot place the paper MLEG",
    )
    args = parser.parse_args(argv)
    if args.submit:
        print(SUBMIT_BLOCKED, file=sys.stderr)
        return 2
    snapshot = _fixture_snapshot()
    try:
        refuse_live_stamp(snapshot, real_fill=False)
    except Exception as exc:
        blocked = str(exc)
    else:
        blocked = SUBMIT_BLOCKED
    preview = would_record_live_fill_episode(
        snapshot=snapshot,
        mcp_attempt={"dry_run": True, "submitted": False, "tool": "place_option_order", "order_class": "mleg"},
        broker_receipt={"present": False, "reason": blocked},
        reconciliation={"present": False, "status": "not claimed"},
    )
    preview["blocked"] = blocked
    print(json.dumps(preview, indent=2, sort_keys=True))
    if preview.get("live_fill_claimed"):
        print("preview must not claim a live fill", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
