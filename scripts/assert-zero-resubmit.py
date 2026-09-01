#!/usr/bin/env python3
"""Credential-free proof that the golden timeout path did not resubmit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.broker_lookup import SIGNED_CLIENT_ORDER_ID  # noqa: E402
from opticycle.evidence_public import BROKER_LOOKUP_PATH, load_public_records  # noqa: E402
from opticycle.signed_credit_fill import assert_zero_resubmit_record  # noqa: E402


def main() -> int:
    rows = [
        row
        for row in load_public_records()
        if row.get("client_order_id") == SIGNED_CLIENT_ORDER_ID
    ]
    if len(rows) != 1:
        raise AssertionError("golden client_order_id must map to one public ledger record")
    result = assert_zero_resubmit_record(rows[0])
    lookup = json.loads(BROKER_LOOKUP_PATH.read_text(encoding="utf-8"))
    fills = [
        fill
        for fill in lookup.get("fills", [])
        if fill.get("client_order_id") == SIGNED_CLIENT_ORDER_ID
    ]
    if len(fills) != 1:
        raise AssertionError("golden client_order_id must map to one broker GET receipt")
    if fills[0].get("order_id") != result["broker_order_id"]:
        raise AssertionError("public ledger and broker lookup order_id disagree")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
