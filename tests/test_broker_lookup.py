"""Independent Alpaca GET-by-client_order_id evidence. No account id."""

from __future__ import annotations

import json
from pathlib import Path

from opticycle.broker_lookup import (
    BROKER_LOOKUP_AT,
    MONDAY_BROKER_ORDER_ID,
    MONDAY_CLIENT_ORDER_ID,
    WEEKEND_BROKER_ORDER_ID,
    WEEKEND_CLIENT_ORDER_ID,
    broker_readback_hash,
    public_broker_lookup,
    sanitized_monday_fill,
    sanitized_weekend_fill,
)
from opticycle.evidence_public import (
    BROKER_LOOKUP_PATH,
    GENUINE_NO_TRADE_JSONL,
    PAGE_PATH,
    is_genuine_no_trade,
    load_jsonl,
    load_public_records,
)

ROOT = Path(__file__).resolve().parents[1]


def test_sanitized_fills_match_broker_lookup() -> None:
    weekend = sanitized_weekend_fill()
    monday = sanitized_monday_fill()
    assert weekend["order_id"] == WEEKEND_BROKER_ORDER_ID
    assert monday["order_id"] == MONDAY_BROKER_ORDER_ID
    lookup = public_broker_lookup()
    assert lookup["looked_up_at"] == BROKER_LOOKUP_AT
    assert lookup["mcp_result_hash_present"] is False
    ids = {item["client_order_id"]: item["order_id"] for item in lookup["fills"]}
    assert ids[WEEKEND_CLIENT_ORDER_ID] == WEEKEND_BROKER_ORDER_ID
    assert ids[MONDAY_CLIENT_ORDER_ID] == MONDAY_BROKER_ORDER_ID
    assert lookup["fills"][0]["broker_readback_hash"] == broker_readback_hash(weekend)
    committed = json.loads(BROKER_LOOKUP_PATH.read_text(encoding="utf-8"))
    assert committed["fills"][0]["order_id"] == WEEKEND_BROKER_ORDER_ID
    blob = json.dumps(committed)
    assert "PA3V84C40PJQ" not in blob
    assert "sk-proj" not in blob


def test_committed_sanitized_fill_jsons() -> None:
    dest = ROOT / "artifacts" / "evidence" / "sanitized_fills"
    weekend = json.loads((dest / f"{WEEKEND_CLIENT_ORDER_ID}.json").read_text(encoding="utf-8"))
    monday = json.loads((dest / f"{MONDAY_CLIENT_ORDER_ID}.json").read_text(encoding="utf-8"))
    assert weekend == sanitized_weekend_fill()
    assert monday == sanitized_monday_fill()


def test_genuine_stale_quote_no_trade_is_exported() -> None:
    rows = load_jsonl(GENUINE_NO_TRADE_JSONL)
    assert len(rows) == 1
    row = rows[0]
    assert is_genuine_no_trade(row) is True
    assert row["outcome"] == "NO_TRADE"
    assert row["reason"] == "SPY quote is stale"
    assert row["extra"]["model_called"] is False
    assert row["extra"]["llm_key_present"] is True
    assert row["episode"]["mcp_attempt"]["present"] is False
    assert "TODO:" not in json.dumps(row)
    public = [item for item in load_public_records() if is_genuine_no_trade(item)]
    assert len(public) == 1
    html = PAGE_PATH.read_text(encoding="utf-8")
    assert row["record_id"] in html
    assert "SPY quote is stale" in html
    assert "TODO:" not in html
