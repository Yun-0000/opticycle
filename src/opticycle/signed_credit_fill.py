"""In-session signed-credit MATCHED fill. Do not invent extras.

Submitted 2026-09-01 during regular hours through official MCP
`place_option_order` `order_class=mleg` with Alpaca-negative credit limit.
Broker filled at the same signed price (`filled <= limit`). Account id omitted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

from opticycle.broker_lookup import (
    SIGNED_BROKER_ORDER_ID,
    SIGNED_CLIENT_ORDER_ID,
    broker_readback_hash,
    sanitized_signed_fill,
)
from opticycle.ledger import EvidenceLedger
from opticycle.live_matched_fills import _candidate, _credit_max_loss, _width, live_record_id
from opticycle.protocol import (
    CanonicalOrderPayload,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
)
from opticycle.reconcile import evaluate_recorded_mleg_fill
from trade.mcp.alpaca_mcp_executor import PLACE_OPTION_ORDER, digest_canonical

LIVE_CHANNEL = "live_paper"
EXP_SIGNED = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)
FILLED_SIGNED_AT = "2026-09-01T16:20:42Z"
SUBMITTED_SIGNED_AT = "2026-09-01T16:15:45Z"
SIGNED_LIMIT = Decimal("-2.26")
SIGNED_FILL = Decimal("-2.26")


def signed_payload() -> CanonicalOrderPayload:
    long = OptionLegSpec(
        symbol="SPY261016P00724000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("724.00"),
        expiration=EXP_SIGNED,
    )
    short = OptionLegSpec(
        symbol="SPY261016P00740000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("740.00"),
        expiration=EXP_SIGNED,
    )
    return CanonicalOrderPayload(
        client_order_id=SIGNED_CLIENT_ORDER_ID,
        account_id="omitted",
        underlying="SPY",
        order_class="mleg",
        order_type="limit",
        time_in_force="day",
        qty=1,
        limit_price=SIGNED_LIMIT,
        legs=(short, long),
    )


def is_price_bound_matched_fill(row: Mapping[str, Any]) -> bool:
    extra = row.get("extra") or {}
    return (
        str(row.get("channel") or "") == LIVE_CHANNEL
        and str(row.get("outcome") or "") == "MATCHED"
        and str(row.get("client_order_id") or "") == SIGNED_CLIENT_ORDER_ID
        and extra.get("matched_claimed") is True
        and extra.get("price_bound_matched") is True
        and extra.get("live_fill_claimed") is True
    )


def _recon(payload: CanonicalOrderPayload) -> dict[str, Any]:
    evaluated = evaluate_recorded_mleg_fill(payload, SIGNED_FILL)
    width = _width(payload)
    fill_credit = Decimal(str(evaluated["fill_credit"] or "0"))
    intended_credit = Decimal(str(evaluated["intended_credit"] or "0"))
    return {
        **evaluated,
        "broker_status": "filled",
        "filled_qty": 1,
        "complete": True,
        "halt_triggered": False,
        "payload_hash": payload.payload_hash,
        "client_order_id": payload.client_order_id,
        "broker_order_id_present": True,
        "certificate_max_loss": str(_credit_max_loss(width, intended_credit, payload.qty)),
        "fill_max_loss": str(_credit_max_loss(width, fill_credit, payload.qty)),
        "provenance": (
            "recorded broker fill facts; production signed-limit evaluator; "
            "Alpaca GET-by-client_order_id; filled <= submitted negative credit limit"
        ),
        "reconciled_at": FILLED_SIGNED_AT,
    }


def signed_fields(*, commit_sha: str) -> dict[str, Any]:
    payload = signed_payload()
    arguments_hash = digest_canonical(payload.to_mcp_arguments())
    return {
        "thesis": {
            "stance": "BULLISH",
            "bound_credit_type": "bull_put",
            "model_called": True,
            "accepted": True,
            "reason_code": "TREND_ALIGNED",
            "model": "gpt-5.6-luna",
            "detail": "in-session ThesisAgent LLM pick; credit type bound after stance",
        },
        "candidate_set": _candidate(payload, spread="bull_put"),
        "certificate": {
            "approval": True,
            "veto": False,
            "payload_hash": payload.payload_hash,
            "note": "production signed-credit certificate; Alpaca-negative MLEG limit",
        },
        "mcp_attempt": {
            "tool": PLACE_OPTION_ORDER,
            "arguments_hash": arguments_hash,
            "submitted": True,
            "dry_run": False,
            "order_class": "mleg",
            "server_spec": "alpaca-mcp-server==2.3.0",
            "channel_label": "live_paper",
            "raw_result_hash_retained": False,
            "raw_result_hash_gap": (
                "MCP stdio client did not return the tool envelope after the broker "
                "accepted this working MLEG; Alpaca GET-by-client_order_id is the fill "
                "source. Same-session close MLEGs retained raw_result_hash."
            ),
        },
        "broker_receipt": {
            "client_order_id": SIGNED_CLIENT_ORDER_ID,
            "broker_order_id": SIGNED_BROKER_ORDER_ID,
            "broker_readback_hash": broker_readback_hash(sanitized_signed_fill()),
            "broker_lookup_source": "alpaca.trading.get_orders",
            "raw_status": "filled",
            "submitted": True,
            "readback": True,
            "submitted_at": SUBMITTED_SIGNED_AT,
            "filled_at": FILLED_SIGNED_AT,
            "filled_qty": 1,
            "filled_avg_price": "-2.26",
            "credit_fill": "2.26",
            "limit": "-2.26",
            "submitted_limit_sign": "credit_negative",
            "legs": [
                {
                    "symbol": "SPY261016P00740000",
                    "side": "sell",
                    "ratio_qty": "1",
                    "filled_avg_price": "6.80",
                    "position_intent": "sell_to_open",
                },
                {
                    "symbol": "SPY261016P00724000",
                    "side": "buy",
                    "ratio_qty": "1",
                    "filled_avg_price": "4.54",
                    "position_intent": "buy_to_open",
                },
            ],
        },
        "reconciliation": _recon(payload),
        "end_of_cycle_equity": "100049.62",
        "code_build_id": commit_sha,
    }


def append_signed_credit_matched_episode(
    ledger: EvidenceLedger,
    *,
    commit_sha: str,
) -> dict[str, Any]:
    payload = signed_payload()
    evaluated = evaluate_recorded_mleg_fill(payload, SIGNED_FILL)
    if evaluated.get("price_bound_matched") is not True:
        raise AssertionError("signed credit fill must be price-bound MATCHED")
    row = ledger.append_episode(
        channel=LIVE_CHANNEL,
        outcome="MATCHED",
        reason=(
            "in-session ThesisAgent BULLISH bull-put; MCP place_option_order mleg; "
            "submitted limit -2.26; broker filled_avg_price -2.26; filled <= limit"
        ),
        commit_sha=commit_sha,
        client_order_id=SIGNED_CLIENT_ORDER_ID,
        record_id=live_record_id(SIGNED_CLIENT_ORDER_ID),
        ts=FILLED_SIGNED_AT,
        fields=signed_fields(commit_sha=commit_sha),
        extra={
            "live_fill_claimed": True,
            "matched_claimed": True,
            "price_bound_matched": True,
            "limit_sign_error": False,
            "channel_label": "live_paper",
            "operational_complete": True,
            "operational_verdict": "matched",
            "account_id_omitted": True,
            "client_order_id": SIGNED_CLIENT_ORDER_ID,
            "broker_order_id_present": True,
            "filled_qty": 1,
            "filled_avg_price": "-2.26",
            "credit_fill": "2.26",
            "model_called": True,
            "model": "gpt-5.6-luna",
            "prior_verticals_closed": True,
            "end_of_cycle_equity": "100049.62",
            "cash": "100281.62",
        },
    )
    if not is_price_bound_matched_fill(row):
        raise AssertionError("signed credit episode is not a price-bound MATCHED fill")
    return row
