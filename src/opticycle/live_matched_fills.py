"""Shared identifiers and helpers for recorded live paper fills."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Mapping

from opticycle.protocol import CanonicalOrderPayload
from opticycle.risk import independent_vertical_risk

LIVE_CHANNEL = "live_paper"
WEEKEND_CLIENT_ORDER_ID = "oc-204a8dfccffd40c9"
MONDAY_CLIENT_ORDER_ID = "oc-715ad36a630d408e"
LIVE_MATCHED_CLIENT_IDS = frozenset({WEEKEND_CLIENT_ORDER_ID, MONDAY_CLIENT_ORDER_ID})


def live_record_id(client_order_id: str) -> str:
    known = {
        WEEKEND_CLIENT_ORDER_ID: "el-ac177b1c1b344c7587fac4851939f3c2",
        MONDAY_CLIENT_ORDER_ID: "el-c40cea16e4f2477d89f451de8e1901b4",
    }
    if client_order_id in known:
        return known[client_order_id]
    digest = hashlib.sha256(
        f"opticycle-live-matched:{client_order_id}".encode()
    ).hexdigest()[:32]
    return f"el-{digest}"


def _candidate(payload: CanonicalOrderPayload, *, spread: str) -> dict[str, Any]:
    return {
        "strategy": "vertical_spread",
        "underlying": "SPY",
        "spread": spread,
        "order_class": "mleg",
        "qty": payload.qty,
        "limit_price": str(payload.limit_price),
        "payload_hash": payload.payload_hash,
        "client_order_id": payload.client_order_id,
        "legs": [
            {"symbol": leg.symbol, "side": leg.side.value, "ratio_qty": str(leg.ratio_qty)}
            for leg in payload.legs
        ],
    }


def _width(payload: CanonicalOrderPayload) -> Decimal:
    strikes = [leg.strike_price for leg in payload.legs]
    return abs(strikes[0] - strikes[1])


def _credit_max_loss(width: Decimal, credit: Decimal, qty: int = 1) -> Decimal:
    loss, _profit = independent_vertical_risk(
        width=width,
        net_credit=credit,
        net_debit=Decimal("0"),
        qty=qty,
        is_credit=True,
    )
    return loss


def is_authorized_live_matched(row: Mapping[str, Any]) -> bool:
    extra = row.get("extra") or {}
    return (
        str(row.get("channel") or "") == LIVE_CHANNEL
        and str(row.get("outcome") or "") in {"FILLED", "MATCHED"}
        and str(row.get("client_order_id") or "") in LIVE_MATCHED_CLIENT_IDS
        and extra.get("live_fill_claimed") is True
    )
