"""Two real Monday paper MATCHED fills (live_paper). Do not invent extras.

Record broker facts only. Omit Alpaca account id. No keys. Replay MATCHED
stays a fixture; these two episodes are the live_paper completion.
"""

from __future__ import annotations

import hashlib
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

LIVE_CHANNEL = "live_paper"
WEEKEND_CLIENT_ORDER_ID = "oc-204a8dfccffd40c9"
MONDAY_CLIENT_ORDER_ID = "oc-715ad36a630d408e"
LIVE_MATCHED_CLIENT_IDS = frozenset({WEEKEND_CLIENT_ORDER_ID, MONDAY_CLIENT_ORDER_ID})
PUBLIC_ACCOUNT_ID = "omitted"

EXP_WEEKEND = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
EXP_MONDAY = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
FILLED_WEEKEND_AT = "2026-08-31T13:30:03Z"
RECON_WEEKEND_AT = "2026-08-31T13:55:00Z"
FILLED_MONDAY_AT = "2026-08-31T14:05:49Z"


class LiveFillError(AssertionError):
    """A live_paper MATCHED episode is missing required broker facts."""


def _leg(
    *,
    symbol: str,
    side: OrderSide,
    intent: PositionIntent,
    strike: str,
    expiration: datetime,
) -> OptionLegSpec:
    return OptionLegSpec(
        symbol=symbol,
        ratio_qty=1,
        side=side,
        position_intent=intent,
        option_type=OptionType.CALL,
        strike_price=Decimal(strike),
        expiration=expiration,
    )


def weekend_payload() -> CanonicalOrderPayload:
    short = _leg(
        symbol="SPY261009C00793000",
        side=OrderSide.SELL,
        intent=PositionIntent.SELL_TO_OPEN,
        strike="793.00",
        expiration=EXP_WEEKEND,
    )
    long = _leg(
        symbol="SPY261009C00809000",
        side=OrderSide.BUY,
        intent=PositionIntent.BUY_TO_OPEN,
        strike="809.00",
        expiration=EXP_WEEKEND,
    )
    return CanonicalOrderPayload(
        client_order_id=WEEKEND_CLIENT_ORDER_ID,
        account_id=PUBLIC_ACCOUNT_ID,
        underlying="SPY",
        order_class="mleg",
        order_type="limit",
        time_in_force="day",
        qty=1,
        limit_price=Decimal("2.54"),
        legs=(short, long),
    )


def monday_payload() -> CanonicalOrderPayload:
    short = _leg(
        symbol="SPY260925C00768000",
        side=OrderSide.SELL,
        intent=PositionIntent.SELL_TO_OPEN,
        strike="768.00",
        expiration=EXP_MONDAY,
    )
    long = _leg(
        symbol="SPY260925C00769000",
        side=OrderSide.BUY,
        intent=PositionIntent.BUY_TO_OPEN,
        strike="769.00",
        expiration=EXP_MONDAY,
    )
    return CanonicalOrderPayload(
        client_order_id=MONDAY_CLIENT_ORDER_ID,
        account_id=PUBLIC_ACCOUNT_ID,
        underlying="SPY",
        order_class="mleg",
        order_type="limit",
        time_in_force="day",
        qty=1,
        limit_price=Decimal("0.70"),
        legs=(short, long),
    )


def live_record_id(client_order_id: str) -> str:
    digest = hashlib.sha256(f"opticycle-live-matched:{client_order_id}".encode("utf-8")).hexdigest()[:32]
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


def _mcp_attempt(payload: CanonicalOrderPayload, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    attempt = {
        "tool": PLACE_OPTION_ORDER,
        "arguments_hash": digest_canonical(payload.to_mcp_arguments()),
        "submitted": True,
        "dry_run": False,
        "order_class": "mleg",
        "server_spec": "alpaca-mcp-server==2.3.0",
        "channel_label": "live_paper",
    }
    if extra:
        attempt.update(dict(extra))
    return attempt


def weekend_fields(*, commit_sha: str) -> dict[str, Any]:
    payload = weekend_payload()
    return {
        "thesis": {
            "stance": "BEARISH",
            "bound_credit_type": "bear_call",
            "model_called": False,
            "accepted": True,
            "detail": "weekend paper MLEG recon; BEARISH bear-call credit",
        },
        "candidate_set": _candidate(payload, spread="bear_call"),
        "certificate": {
            "approval": True,
            "veto": False,
            "payload_hash": payload.payload_hash,
        },
        "mcp_attempt": _mcp_attempt(payload),
        "broker_receipt": {
            "client_order_id": WEEKEND_CLIENT_ORDER_ID,
            "raw_status": "filled",
            "submitted": True,
            "readback": True,
            "filled_at": FILLED_WEEKEND_AT,
            "filled_qty": 1,
            "filled_avg_price": "-2.11",
            "credit_fill": "2.11",
            "limit": "2.54",
            "legs": [
                {
                    "symbol": "SPY261009C00793000",
                    "side": "sell",
                    "ratio_qty": "1",
                    "filled_avg_price": "2.95",
                },
                {
                    "symbol": "SPY261009C00809000",
                    "side": "buy",
                    "ratio_qty": "1",
                    "filled_avg_price": "0.84",
                },
            ],
        },
        "reconciliation": {
            "status": "matched",
            "broker_status": "filled",
            "filled_qty": 1,
            "filled_avg_price": "-2.11",
            "credit_fill": "2.11",
            "limit": "2.54",
            "credit_better_bound": True,
            "complete": True,
            "halt_triggered": False,
            "payload_hash": payload.payload_hash,
            "client_order_id": WEEKEND_CLIENT_ORDER_ID,
            "reconciled_at": RECON_WEEKEND_AT,
        },
        "end_of_cycle_equity": "100007.95",
        "code_build_id": commit_sha,
    }


def monday_fields(*, commit_sha: str) -> dict[str, Any]:
    payload = monday_payload()
    return {
        "thesis": {
            "stance": "BEARISH",
            "bound_credit_type": "bear_call",
            "stance_source": "bars_heuristic_no_llm_key",
            "model_called": False,
            "reason_code": "LLM_DISABLED",
            "accepted": True,
            "detail": "no LLM key on the box; not a live ThesisAgent LLM pick",
        },
        "candidate_set": _candidate(payload, spread="bear_call"),
        "certificate": {
            "approval": True,
            "veto": False,
            "payload_hash": payload.payload_hash,
            "max_loss": "30",
        },
        "mcp_attempt": _mcp_attempt(
            payload,
            extra={
                "mcp_submit_count": 1,
                "stdio_hung_after_broker_had_order": True,
                "second_submit": False,
            },
        ),
        "broker_receipt": {
            "client_order_id": MONDAY_CLIENT_ORDER_ID,
            "raw_status": "filled",
            "submitted": True,
            "readback": True,
            "filled_at": FILLED_MONDAY_AT,
            "filled_qty": 1,
            "filled_avg_price": "-0.51",
            "credit_fill": "0.51",
            "limit": "0.70",
            "legs": [
                {
                    "symbol": "SPY260925C00768000",
                    "side": "sell",
                    "ratio_qty": "1",
                    "filled_avg_price": "8.68",
                },
                {
                    "symbol": "SPY260925C00769000",
                    "side": "buy",
                    "ratio_qty": "1",
                    "filled_avg_price": "8.17",
                },
            ],
        },
        "reconciliation": {
            "status": "matched",
            "broker_status": "filled",
            "filled_qty": 1,
            "filled_avg_price": "-0.51",
            "credit_fill": "0.51",
            "limit": "0.70",
            "complete": True,
            "halt_triggered": False,
            "payload_hash": payload.payload_hash,
            "client_order_id": MONDAY_CLIENT_ORDER_ID,
        },
        "code_build_id": commit_sha,
    }


def _extra(client_order_id: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    body = {
        "live_fill_claimed": True,
        "matched_claimed": True,
        "channel_label": "live_paper",
        "operational_complete": True,
        "operational_verdict": "matched",
        "account_id_omitted": True,
        "client_order_id": client_order_id,
    }
    if extra:
        body.update(dict(extra))
    return body


def append_weekend_matched_episode(
    ledger: EvidenceLedger,
    *,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    sha = commit_sha or current_commit_sha()
    row = ledger.append_episode(
        channel=LIVE_CHANNEL,
        outcome="MATCHED",
        reason="weekend paper MLEG recon MATCHED; credit 2.11 vs limit 2.54; equity 100007.95",
        commit_sha=sha,
        client_order_id=WEEKEND_CLIENT_ORDER_ID,
        fields=weekend_fields(commit_sha=sha),
        extra=_extra(
            WEEKEND_CLIENT_ORDER_ID,
            {
                "filled_qty": 1,
                "filled_avg_price": "-2.11",
                "credit_fill": "2.11",
                "cash": "100210.95",
                "end_of_cycle_equity": "100007.95",
            },
        ),
    )
    require_live_matched_fill(row)
    return row


def append_monday_matched_episode(
    ledger: EvidenceLedger,
    *,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    sha = commit_sha or current_commit_sha()
    row = ledger.append_episode(
        channel=LIVE_CHANNEL,
        outcome="MATCHED",
        reason="Monday live MCP MLEG MATCHED; heuristic stance (no LLM key); no second submit",
        commit_sha=sha,
        client_order_id=MONDAY_CLIENT_ORDER_ID,
        fields=monday_fields(commit_sha=sha),
        extra=_extra(
            MONDAY_CLIENT_ORDER_ID,
            {
                "filled_qty": 1,
                "filled_avg_price": "-0.51",
                "credit_fill": "0.51",
                "mcp_submit_count": 1,
                "stance_source": "bars_heuristic_no_llm_key",
                "certificate_approval": True,
            },
        ),
    )
    require_live_matched_fill(row)
    return row


def append_live_matched_episodes(
    ledger: EvidenceLedger,
    *,
    commit_sha: str | None = None,
) -> list[dict[str, Any]]:
    sha = commit_sha or current_commit_sha()
    return [
        append_weekend_matched_episode(ledger, commit_sha=sha),
        append_monday_matched_episode(ledger, commit_sha=sha),
    ]


def _slot(row: Mapping[str, Any], field: str) -> Any:
    episode = row.get("episode") or {}
    slot = episode.get(field) or {}
    if isinstance(slot, Mapping) and slot.get("present"):
        return slot.get("value")
    return None


def is_authorized_live_matched(row: Mapping[str, Any]) -> bool:
    extra = row.get("extra") or {}
    return (
        str(row.get("channel") or "") == LIVE_CHANNEL
        and str(row.get("outcome") or "") == "MATCHED"
        and str(row.get("client_order_id") or "") in LIVE_MATCHED_CLIENT_IDS
        and extra.get("live_fill_claimed") is True
    )


def require_live_matched_fill(row: Mapping[str, Any]) -> None:
    missing: list[str] = []
    if not is_authorized_live_matched(row):
        raise LiveFillError("not one of the two authorized live_paper MATCHED fills")
    client_id = str(row.get("client_order_id") or "")
    extra = row.get("extra") or {}
    if extra.get("account_id") or extra.get("account_number"):
        missing.append("account_id_leaked")

    mcp = _slot(row, "mcp_attempt")
    if not isinstance(mcp, Mapping) or mcp.get("tool") != PLACE_OPTION_ORDER:
        missing.append("mcp_attempt.tool")
    elif mcp.get("submitted") is not True:
        missing.append("mcp_attempt.submitted")

    receipt = _slot(row, "broker_receipt")
    if not isinstance(receipt, Mapping):
        missing.append("broker_receipt")
    else:
        if receipt.get("client_order_id") != client_id:
            missing.append("broker_receipt.client_order_id")
        if str(receipt.get("raw_status") or "").lower() != "filled":
            missing.append("broker_receipt.filled")
        legs = receipt.get("legs")
        if not isinstance(legs, list) or len(legs) < 2:
            missing.append("broker_receipt.legs")

    recon = _slot(row, "reconciliation")
    if not isinstance(recon, Mapping) or str(recon.get("status") or "").lower() != "matched":
        missing.append("reconciliation.MATCHED")
    else:
        if recon.get("filled_qty") not in {1, "1"}:
            missing.append("filled_qty")
        if recon.get("filled_avg_price") in (None, ""):
            missing.append("filled_avg_price")

    candidate = _slot(row, "candidate_set")
    if not isinstance(candidate, Mapping) or not candidate.get("payload_hash"):
        missing.append("payload_hash")
    cert = _slot(row, "certificate")
    if not isinstance(cert, Mapping) or cert.get("approval") is not True:
        missing.append("certificate.approval")

    if client_id == WEEKEND_CLIENT_ORDER_ID and _slot(row, "end_of_cycle_equity") in (None, ""):
        missing.append("end_of_cycle_equity")
    if client_id == MONDAY_CLIENT_ORDER_ID:
        thesis = _slot(row, "thesis")
        if not isinstance(thesis, Mapping) or thesis.get("stance_source") != "bars_heuristic_no_llm_key":
            missing.append("stance_source")
        if isinstance(thesis, Mapping) and thesis.get("model_called") is True:
            missing.append("llm_claimed")
        if not isinstance(mcp, Mapping) or mcp.get("mcp_submit_count") != 1:
            missing.append("mcp_submit_count")
        if isinstance(mcp, Mapping) and mcp.get("second_submit") is True:
            missing.append("second_submit")

    commit_sha = str(row.get("commit_sha") or "")
    claim = str(row.get("claim") or "")
    if not commit_sha or (claim and commit_sha not in claim):
        missing.append("claim_commit_sha")
    if missing:
        raise LiveFillError("missing live fill facts: " + ", ".join(missing))
