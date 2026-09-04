#!/usr/bin/env python3
"""Read-only Alpaca GET of every registered paper fill. Never submits."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")

from opticycle.broker_lookup import broker_readback_hash, public_broker_lookup
from opticycle.observe import AlpacaReadClient

FILL_REGISTRY = ROOT / "artifacts" / "evidence" / "paper_fill_ingest.json"
BROKER_LOOKUP = ROOT / "artifacts" / "evidence" / "broker_lookup.json"


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


def _public_order(order: Any) -> dict[str, Any]:
    legs = []
    for leg in list(_get(order, "legs", []) or []):
        legs.append(
            {
                "symbol": _text(_get(leg, "symbol")).upper(),
                "side": _text(_get(leg, "side")).lower(),
                "ratio_qty": _text(_get(leg, "ratio_qty") or _get(leg, "qty") or "1"),
                "position_intent": _text(_get(leg, "position_intent")).lower(),
                "filled_avg_price": _text(_get(leg, "filled_avg_price")),
            }
        )
    return {
        "order_id": _text(_get(order, "id") or _get(order, "order_id")),
        "client_order_id": _text(_get(order, "client_order_id")),
        "order_class": _text(_get(order, "order_class")).lower(),
        "status": _text(_get(order, "status")).lower(),
        "qty": _text(_get(order, "qty")),
        "filled_qty": _text(_get(order, "filled_qty")),
        "limit": _text(_get(order, "limit_price") or _get(order, "limit")),
        "filled_avg_price": _text(_get(order, "filled_avg_price")),
        "submitted_at": _text(_get(order, "submitted_at")),
        "filled_at": _text(_get(order, "filled_at")),
        "legs": legs,
    }


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


def live_broker_lookup(client: AlpacaReadClient, expected: dict[str, str]) -> dict[str, Any]:
    snapshot = public_broker_lookup()
    prior_fills = {
        str(fill.get("client_order_id") or ""): dict(fill)
        for fill in snapshot.get("fills", [])
    }
    fills: list[dict[str, Any]] = []
    found: dict[str, str] = {}
    for client_id, order_id in expected.items():
        order = client.fetch_order(client_order_id=client_id)
        public = _public_order(order)
        oid = str(public.get("order_id") or "")
        found[client_id] = oid
        if oid != order_id:
            raise ValueError(f"mismatch {client_id}: expected {order_id} got {oid}")
        if public.get("client_order_id") != client_id:
            raise ValueError(f"broker returned the wrong client_order_id for {client_id}")
        merged = {**prior_fills.get(client_id, {}), **public}
        merged["broker_readback_hash"] = broker_readback_hash(public)
        fills.append(merged)
    refreshed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    snapshot.update(
        {
            "verified": True,
            "refreshed_at": refreshed_at,
            "looked_up_at": refreshed_at,
            "order_ids": found,
            "fills": fills,
        }
    )
    return snapshot


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=BROKER_LOOKUP,
        help="Write the sanitized live GET snapshot here when credentials are present",
    )
    args = parser.parse_args(argv)
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
    try:
        snapshot = live_broker_lookup(client, expected)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    _write_json_atomic(args.out, snapshot)
    print(
        json.dumps(
            {
                "verified": True,
                "fills": len(snapshot["fills"]),
                "refreshed_at": snapshot["refreshed_at"],
                "path": str(args.out),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
