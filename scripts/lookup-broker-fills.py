#!/usr/bin/env python3
"""Read-only Alpaca GET of the two authorized paper fills. Never submits."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from opticycle.broker_lookup import (  # noqa: E402
    MONDAY_BROKER_ORDER_ID,
    MONDAY_CLIENT_ORDER_ID,
    WEEKEND_BROKER_ORDER_ID,
    WEEKEND_CLIENT_ORDER_ID,
    public_broker_lookup,
)
from opticycle.observe import AlpacaReadClient  # noqa: E402


def main() -> int:
    if not (os.environ.get("ALPACA_API_KEY") or "").strip():
        print(json.dumps(public_broker_lookup(), indent=2, sort_keys=True))
        return 0
    client = AlpacaReadClient.from_env()
    expected = {
        WEEKEND_CLIENT_ORDER_ID: WEEKEND_BROKER_ORDER_ID,
        MONDAY_CLIENT_ORDER_ID: MONDAY_BROKER_ORDER_ID,
    }
    found: dict[str, str] = {}
    for client_id, order_id in expected.items():
        order = client.fetch_order(client_order_id=client_id)
        oid = str(getattr(order, "id", None) or "")
        found[client_id] = oid
        if oid != order_id:
            print(f"mismatch {client_id}: expected {order_id} got {oid}", file=sys.stderr)
            return 2
    print(json.dumps({"verified": True, "order_ids": found, **public_broker_lookup()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
