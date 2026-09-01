"""In-session signed-credit MATCHED fill facts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from opticycle.broker_lookup import SIGNED_BROKER_ORDER_ID, SIGNED_CLIENT_ORDER_ID, sanitized_signed_fill
from opticycle.ledger import EvidenceLedger
from opticycle.reconcile import evaluate_recorded_mleg_fill
from opticycle.signed_credit_fill import (
    SIGNED_FILL,
    append_signed_credit_matched_episode,
    assert_zero_resubmit_record,
    is_price_bound_matched_fill,
    signed_payload,
)


def test_signed_credit_fill_is_price_bound_matched(tmp_path: Path) -> None:
    payload = signed_payload()
    assert payload.limit_price == Decimal("-2.26")
    evaluated = evaluate_recorded_mleg_fill(payload, SIGNED_FILL)
    assert evaluated["price_bound_matched"] is True
    assert evaluated["limit_sign_error"] is False
    assert evaluated["status"] == "matched"
    row = append_signed_credit_matched_episode(
        EvidenceLedger(tmp_path / "ledger.raw.jsonl"),
        commit_sha="a" * 40,
    )
    assert is_price_bound_matched_fill(row) is True
    assert row["outcome"] == "MATCHED"
    assert row["client_order_id"] == SIGNED_CLIENT_ORDER_ID
    assert row["extra"]["matched_claimed"] is True
    assert row["extra"]["mcp_submit_count"] == 1
    assert row["extra"]["second_submit"] is False
    assert row["episode"]["snapshot"]["value"]["prevalidated"] is True
    assert row["episode"]["thesis"]["value"]["model_called"] is True
    proof = assert_zero_resubmit_record(row)
    assert proof["credential_free"] is True
    assert proof["mcp_submit_count"] == 1
    assert proof["second_submit"] is False
    receipt = row["episode"]["broker_receipt"]["value"]
    assert receipt["broker_order_id"] == SIGNED_BROKER_ORDER_ID
    assert receipt["limit"] == "-2.26"
    assert receipt["filled_avg_price"] == "-2.26"
    fill = sanitized_signed_fill()
    assert fill["order_id"] == SIGNED_BROKER_ORDER_ID
    assert fill["filled_avg_price"] == "-2.26"
