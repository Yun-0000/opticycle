#!/usr/bin/env python3
"""Ingest sanitized broker fill JSON, or wait. Cloud VM must not submit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.ledger import EvidenceLedger  # noqa: E402
from opticycle.paper_fill_ingest import (  # noqa: E402
    FillIngestError,
    ingest_sanitized_fill,
    load_sanitized_fill,
    waiting_status,
)

SUBMIT_BLOCKED = "Yun authorized one paper MLEG; cloud VM has no keys and must not place it"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest sanitized paper MLEG fill JSON (no submit)")
    parser.add_argument(
        "--from-json",
        dest="from_json",
        help="Path to sanitized broker JSON (order_id, legs, limit, status, filled_avg_price, client_order_id)",
    )
    parser.add_argument(
        "--ledger",
        help="Private ledger path (default: do not write committed artifacts)",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Refused: this environment cannot place the paper MLEG",
    )
    args = parser.parse_args(argv)
    if args.submit:
        print(SUBMIT_BLOCKED, file=sys.stderr)
        return 2
    if not args.from_json:
        print(json.dumps(waiting_status(), indent=2, sort_keys=True))
        return 0
    try:
        payload = load_sanitized_fill(args.from_json)
    except FillIngestError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    if not args.ledger:
        print(json.dumps({"validated": True, "live_fill_claimed": False, "matched_claimed": False, "receipt": payload}, indent=2, sort_keys=True))
        return 0
    ledger = EvidenceLedger(args.ledger)
    row = ingest_sanitized_fill(ledger=ledger, payload=payload)
    print(
        json.dumps(
            {
                "record_id": row["record_id"],
                "claim": row["claim"],
                "live_fill_claimed": False,
                "matched_claimed": False,
                "broker_receipt_present": row["episode"]["broker_receipt"]["present"],
                "reconciliation_present": row["episode"]["reconciliation"]["present"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
