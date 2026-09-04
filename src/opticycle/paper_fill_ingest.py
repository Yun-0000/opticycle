"""Ingest a sanitized broker receipt/fill JSON into the Evidence Ledger.

Yun authorized one Alpaca paper MLEG. Cloud VMs have no keys and must not
place the order. When a later sanitized JSON arrives (order_id, legs, limit,
status, filled_avg_price, client_order_id), this hook records the receipt.
It never invents missing fields and never stamps a fake MATCHED episode.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from opticycle.ledger import EvidenceLedger, public_contains_secrets
from opticycle.protocol import format_decimal

REQUIRED_FILL_FIELDS = (
    "order_id",
    "legs",
    "limit",
    "status",
    "filled_avg_price",
    "client_order_id",
)

ACCOUNT_ID_RE = re.compile(r"\bPA[A-Z0-9]{8,}\b")
WAITING_HOOK = "python3 scripts/ingest-paper-fill.py --from-json <sanitized.json>"


class FillIngestError(Exception):
    """Sanitized fill JSON is missing, secret-bearing, or incomplete."""


def waiting_status() -> dict[str, Any]:
    return {
        "schema": "opticycle.paper-fill-ingest.v1",
        "yun_authorized_one_paper_mleg": True,
        "cloud_submit": False,
        "sanitized_json_provided": False,
        "live_fill_claimed": False,
        "matched_claimed": False,
        "waiting_for": list(REQUIRED_FILL_FIELDS),
        "hook": WAITING_HOOK,
        "detail": (
            "Yun authorized one Alpaca paper MLEG. Cloud VM cannot submit. "
            "Provide sanitized broker JSON later; do not invent MATCHED, receipt, or P&L."
        ),
    }


def _reject_secrets(payload: Mapping[str, Any]) -> None:
    blob = json.dumps(payload, default=str)
    if ACCOUNT_ID_RE.search(blob):
        raise FillIngestError("sanitized fill JSON must not contain an Alpaca account id")
    if "ALPACA_API_KEY=" in blob or "ALPACA_SECRET_KEY=" in blob:
        raise FillIngestError("sanitized fill JSON must not contain credentials")
    hits = public_contains_secrets(payload)
    if hits:
        raise FillIngestError(f"sanitized fill JSON failed secret scan: {hits}")


def validate_sanitized_fill(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Require every field from the broker JSON. Never invent defaults."""
    if payload is None:
        raise FillIngestError("no sanitized broker JSON provided")
    if not isinstance(payload, Mapping):
        raise FillIngestError("sanitized broker JSON must be an object")
    _reject_secrets(payload)
    missing = [name for name in REQUIRED_FILL_FIELDS if payload.get(name) in (None, "", [])]
    if missing:
        raise FillIngestError(
            f"missing fields {missing}; refusing to invent order_id/legs/limit/status/"
            "filled_avg_price/client_order_id"
        )
    legs = payload.get("legs")
    if not isinstance(legs, list) or len(legs) < 2:
        raise FillIngestError("mleg fill JSON requires at least two legs")
    cleaned_legs: list[dict[str, str]] = []
    for item in legs:
        if not isinstance(item, Mapping):
            raise FillIngestError("each leg must be an object")
        symbol = str(item.get("symbol") or "").strip()
        side = str(item.get("side") or "").strip().lower()
        ratio = str(item.get("ratio_qty") or item.get("qty") or "").strip()
        if not symbol or not side or not ratio:
            raise FillIngestError("each leg needs symbol, side, and ratio_qty")
        cleaned_legs.append({"symbol": symbol, "side": side, "ratio_qty": ratio})
    try:
        limit = format_decimal(Decimal(str(payload["limit"])), 4)
        filled_avg = format_decimal(Decimal(str(payload["filled_avg_price"])), 4)
    except (InvalidOperation, ValueError, TypeError, ArithmeticError) as exc:
        raise FillIngestError("limit and filled_avg_price must be numeric") from exc
    status = str(payload["status"]).strip().lower()
    if not status:
        raise FillIngestError("status is required")
    return {
        "order_id": str(payload["order_id"]).strip(),
        "client_order_id": str(payload["client_order_id"]).strip(),
        "limit": limit,
        "status": status,
        "filled_avg_price": filled_avg,
        "legs": cleaned_legs,
        "order_class": "mleg",
        "source": "sanitized_broker_json",
        "live_fill_claimed": False,
        "matched_claimed": False,
    }


def load_sanitized_fill(path: Path | str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.is_file():
        raise FillIngestError(f"sanitized broker JSON not found: {file_path}")
    try:
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FillIngestError("sanitized broker JSON is not valid JSON") from exc
    return validate_sanitized_fill(loaded)


def ingest_sanitized_fill(
    *,
    ledger: EvidenceLedger,
    payload: Mapping[str, Any],
    commit_sha: str | None = None,
) -> dict[str, Any]:
    """Record the receipt/fill facts. Never stamp MATCHED or live P&L."""
    cleaned = validate_sanitized_fill(payload)
    row = ledger.append_episode(
        channel="live_paper",
        outcome="HALT",
        reason="sanitized broker JSON ingested; MATCHED / live P&L not claimed",
        commit_sha=commit_sha,
        client_order_id=cleaned["client_order_id"],
        extra={
            "ingest_sanitized_broker_json": True,
            "yun_authorized_one_paper_mleg": True,
            "live_fill_claimed": False,
            "matched_claimed": False,
            "cloud_submit": False,
        },
        fields={"broker_receipt": cleaned},
    )
    recon = row["episode"]["reconciliation"]
    if recon.get("present") is True:
        raise FillIngestError("ingest must not record a reconciliation slot")
    value = recon.get("value") if isinstance(recon, dict) else None
    status = ""
    if isinstance(value, Mapping):
        status = str(value.get("status") or "").lower()
    if status in {"matched", "fill", "filled"}:
        raise FillIngestError("ingest must not stamp MATCHED")
    if row["episode"]["realized_pnl"]["present"] or row["episode"]["unrealized_pnl"]["present"]:
        raise FillIngestError("ingest must not stamp live P&L")
    if row["extra"].get("live_fill_claimed"):
        raise FillIngestError("ingest must not claim a live fill")
    return row
