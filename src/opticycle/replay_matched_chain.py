"""Replay/fixture Decision Episode: MCP MLEG → broker readback → MATCHED fill + P&L.

This is a keyless public chain, labeled replay (not a live_paper fill).
Do not bind oc-204a8dfccffd40c9 on the replay channel. live_fill_claimed stays false here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from opticycle.ledger import EvidenceLedger, current_commit_sha
from opticycle.protocol import (
    CanonicalOrderPayload,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
)
from trade.mcp.alpaca_mcp_executor import PLACE_OPTION_ORDER, digest_canonical

REPLAY_CHANNEL = "replay"
REPLAY_CLIENT_ORDER_ID = "oc-replay-a5-mleg-001"
REPLAY_CYCLE_ID = "cycle-replay-a5-mleg-001"
REPLAY_BROKER_ORDER_ID = "replay-ord-a5-001"
FORBIDDEN_LIVE_CLIENT_ORDER_ID = "oc-204a8dfccffd40c9"
EXP = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)

CHAIN_HOPS = (
    "mcp_attempt",
    "broker_receipt",
    "reconciliation",
    "filled_qty",
    "filled_avg_price",
    "pnl_equity",
)


class ChainIncomplete(AssertionError):
    """A required MCP → readback → fill/P&L hop is missing."""


def replay_payload() -> CanonicalOrderPayload:
    short = OptionLegSpec(
        symbol="SPY260918P00550000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("550.00"),
        expiration=EXP,
    )
    long = OptionLegSpec(
        symbol="SPY260918P00540000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("540.00"),
        expiration=EXP,
    )
    return CanonicalOrderPayload(
        client_order_id=REPLAY_CLIENT_ORDER_ID,
        account_id="replay",
        underlying="SPY",
        order_class="mleg",
        order_type="limit",
        time_in_force="day",
        qty=1,
        limit_price=Decimal("1.20"),
        legs=(short, long),
    )


def matched_chain_fields(*, commit_sha: str, payload: CanonicalOrderPayload | None = None) -> dict[str, Any]:
    order = payload or replay_payload()
    if order.client_order_id == FORBIDDEN_LIVE_CLIENT_ORDER_ID:
        raise ChainIncomplete("oc-204a8dfccffd40c9 must not be written as MATCHED")
    arguments = order.to_mcp_arguments()
    arguments_hash = digest_canonical(arguments)
    return {
        "candidate_set": {
            "strategy": "vertical_spread",
            "underlying": "SPY",
            "spread": "bull_put",
            "order_class": "mleg",
            "qty": order.qty,
            "limit_price": str(order.limit_price),
            "payload_hash": order.payload_hash,
            "client_order_id": order.client_order_id,
            "legs": [
                {"symbol": leg.symbol, "side": leg.side.value, "ratio_qty": str(leg.ratio_qty)}
                for leg in order.legs
            ],
        },
        "certificate": {
            "approval": True,
            "veto": False,
            "payload_hash": order.payload_hash,
        },
        "mcp_attempt": {
            "tool": PLACE_OPTION_ORDER,
            "arguments_hash": arguments_hash,
            "submitted": True,
            "dry_run": False,
            "order_class": "mleg",
            "server_spec": "alpaca-mcp-server==2.3.0",
            "channel_label": "replay_fixture",
        },
        "broker_receipt": {
            "client_order_id": order.client_order_id,
            "broker_order_id": REPLAY_BROKER_ORDER_ID,
            "raw_status": "filled",
            "submitted": True,
            "readback": True,
        },
        "reconciliation": {
            "status": "matched",
            "broker_status": "filled",
            "filled_qty": 1,
            "filled_avg_price": "1.20",
            "complete": True,
            "halt_triggered": False,
            "payload_hash": order.payload_hash,
            "client_order_id": order.client_order_id,
            "cycle_id": REPLAY_CYCLE_ID,
        },
        "realized_pnl": "120.00",
        "unrealized_pnl": "40.00",
        "end_of_cycle_equity": "100120.00",
        "code_build_id": commit_sha,
    }


def append_replay_matched_episode(
    ledger: EvidenceLedger,
    *,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    sha = commit_sha or current_commit_sha()
    payload = replay_payload()
    row = ledger.append_episode(
        channel=REPLAY_CHANNEL,
        outcome="MATCHED",
        reason="replay/fixture MCP MLEG → broker readback → fill + P&L; not a live_paper fill",
        commit_sha=sha,
        cycle_id=REPLAY_CYCLE_ID,
        client_order_id=REPLAY_CLIENT_ORDER_ID,
        fields=matched_chain_fields(commit_sha=sha, payload=payload),
        extra={
            "live_fill_claimed": False,
            "channel_label": "replay_fixture",
            "filled_qty": 1,
            "filled_avg_price": "1.20",
            "operational_complete": True,
            "operational_verdict": "matched",
        },
    )
    require_matched_chain(row)
    return row


def _slot(row: Mapping[str, Any], field: str) -> Any:
    episode = row.get("episode") or {}
    slot = episode.get(field) or {}
    if isinstance(slot, Mapping) and slot.get("present"):
        return slot.get("value")
    return None


def require_matched_chain(row: Mapping[str, Any]) -> None:
    """Fail if any hop of MCP → readback → MATCHED fill/P&L is missing."""
    missing: list[str] = []
    client_id = str(row.get("client_order_id") or "")
    if client_id == FORBIDDEN_LIVE_CLIENT_ORDER_ID:
        raise ChainIncomplete("oc-204a8dfccffd40c9 must not appear as MATCHED on the replay channel")
    if str(row.get("channel") or "") == "live_paper":
        raise ChainIncomplete("chain must be labeled replay/fixture, not live_paper fill")
    if str(row.get("outcome") or "") != "MATCHED":
        missing.append("outcome=MATCHED")
    extra = row.get("extra") or {}
    if extra.get("live_fill_claimed") is True:
        raise ChainIncomplete("live_fill_claimed must stay false")

    mcp = _slot(row, "mcp_attempt")
    if not isinstance(mcp, Mapping):
        missing.append("mcp_attempt")
    else:
        if not mcp.get("tool"):
            missing.append("mcp_attempt.tool")
        if not mcp.get("arguments_hash"):
            missing.append("mcp_attempt.arguments_hash")
        if mcp.get("submitted") is not True:
            missing.append("mcp_attempt.submitted")

    receipt = _slot(row, "broker_receipt")
    if not isinstance(receipt, Mapping) or not (receipt.get("broker_order_id") or receipt.get("readback")):
        missing.append("broker_receipt")

    recon = _slot(row, "reconciliation")
    if not isinstance(recon, Mapping) or str(recon.get("status") or "").lower() != "matched":
        missing.append("reconciliation.MATCHED")
    else:
        filled_qty = recon.get("filled_qty")
        filled_px = recon.get("filled_avg_price")
        if filled_qty in (None, ""):
            missing.append("filled_qty")
        if filled_px in (None, ""):
            missing.append("filled_avg_price")

    if _slot(row, "realized_pnl") in (None, "") and _slot(row, "unrealized_pnl") in (None, ""):
        missing.append("pnl")
    if _slot(row, "end_of_cycle_equity") in (None, ""):
        missing.append("end_of_cycle_equity")

    cycle_id = str(row.get("cycle_id") or "")
    payload_hash = None
    candidate = _slot(row, "candidate_set")
    if isinstance(candidate, Mapping):
        payload_hash = candidate.get("payload_hash")
    if isinstance(recon, Mapping) and recon.get("payload_hash"):
        if payload_hash and recon.get("payload_hash") != payload_hash:
            missing.append("payload_hash_mismatch")
        payload_hash = payload_hash or recon.get("payload_hash")
    commit_sha = str(row.get("commit_sha") or "")
    if not cycle_id or not client_id or not payload_hash or not commit_sha:
        missing.append("identity")
    if isinstance(recon, Mapping):
        if recon.get("client_order_id") and recon.get("client_order_id") != client_id:
            missing.append("client_order_id_mismatch")
        if recon.get("cycle_id") and recon.get("cycle_id") != cycle_id:
            missing.append("cycle_id_mismatch")
    if isinstance(candidate, Mapping) and candidate.get("client_order_id") not in {None, client_id}:
        missing.append("candidate_client_order_id_mismatch")
    claim = str(row.get("claim") or "")
    if commit_sha and claim and commit_sha not in claim:
        missing.append("claim_commit_sha")

    if missing:
        raise ChainIncomplete("missing hops: " + ", ".join(missing))
