#!/usr/bin/env python3
"""Read-only Alpaca GET of every registered paper fill. Never submits."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")

from opticycle.broker_lookup import public_broker_lookup
from opticycle.observe import AlpacaReadClient

FILL_REGISTRY = ROOT / "artifacts" / "evidence" / "paper_fill_ingest.json"


def expected_fills() -> dict[str, str]:
    payload = json.loads(FILL_REGISTRY.read_text(encoding="utf-8"))
    client_ids = payload.get("authorized_live_client_order_ids") or []
    broker_ids = payload.get("broker_order_ids") or {}
    expected = {
        str(client_id): str(broker_ids.get(client_id) or "")
        for client_id in client_ids
    }
    if not expected or any(not broker_id for broker_id in expected.values()):
        raise ValueError("paper fill registry is incomplete")
    return expected


def main() -> int:
    expected = expected_fills()
    if not (os.environ.get("ALPACA_API_KEY") or "").strip():
        snapshot = public_broker_lookup()
        recorded = {
            str(fill.get("client_order_id") or ""): str(fill.get("order_id") or "")
            for fill in snapshot.get("fills", [])
        }
        if any(recorded.get(client_id) != order_id for client_id, order_id in expected.items()):
            print("committed broker lookup does not cover the fill registry", file=sys.stderr)
            return 2
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        return 0
    client = AlpacaReadClient.from_env()
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
