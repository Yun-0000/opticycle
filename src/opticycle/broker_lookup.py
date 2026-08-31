"""Sanitized Alpaca GET-by-client_order_id facts. No account id. No keys."""

from __future__ import annotations

from opticycle.ledger import sha256_json

WEEKEND_CLIENT_ORDER_ID = "oc-204a8dfccffd40c9"
MONDAY_CLIENT_ORDER_ID = "oc-715ad36a630d408e"

WEEKEND_BROKER_ORDER_ID = "abcb5385-0aa3-42cc-9b58-ef4200235c27"
MONDAY_BROKER_ORDER_ID = "2a6d6b7c-caad-4c24-959a-8d93455a36fe"
BROKER_LOOKUP_AT = "2026-08-31T21:02:23Z"
BROKER_LOOKUP_SOURCE = "alpaca.trading.get_order_by_client_id"

# Clock at lookup: US equities closed. Next regular open 2026-09-01 09:30 ET.
MARK_EQUITY = "100010.9"
MARK_CASH = "100261.9"
MARK_LONG_MARKET_VALUE = "904"
MARK_SHORT_MARKET_VALUE = "-1155"
MARK_UNREALIZED_PNL = "11"
MARK_LAST_EQUITY = "100000"


def sanitized_weekend_fill() -> dict[str, str | list[dict[str, str]]]:
    return {
        "order_id": WEEKEND_BROKER_ORDER_ID,
        "client_order_id": WEEKEND_CLIENT_ORDER_ID,
        "limit": "2.54",
        "status": "filled",
        "filled_avg_price": "-2.11",
        "legs": [
            {"symbol": "SPY261009C00793000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "SPY261009C00809000", "side": "buy", "ratio_qty": "1"},
        ],
    }


def sanitized_monday_fill() -> dict[str, str | list[dict[str, str]]]:
    return {
        "order_id": MONDAY_BROKER_ORDER_ID,
        "client_order_id": MONDAY_CLIENT_ORDER_ID,
        "limit": "0.70",
        "status": "filled",
        "filled_avg_price": "-0.51",
        "legs": [
            {"symbol": "SPY260925C00768000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "SPY260925C00769000", "side": "buy", "ratio_qty": "1"},
        ],
    }


def broker_readback_hash(payload: dict) -> str:
    return sha256_json(payload)


def mark_snapshot() -> dict[str, object]:
    return {
        "looked_up_at": BROKER_LOOKUP_AT,
        "clock_open": False,
        "next_open": "2026-09-01T09:30:00-04:00",
        "equity": MARK_EQUITY,
        "cash": MARK_CASH,
        "long_market_value": MARK_LONG_MARKET_VALUE,
        "short_market_value": MARK_SHORT_MARKET_VALUE,
        "unrealized_pnl": MARK_UNREALIZED_PNL,
        "last_equity": MARK_LAST_EQUITY,
        "realized_pnl_present": False,
        "positions_still_open": True,
        "exit_recorded": False,
        "identity": "cash + long_market_value + short_market_value (Alpaca signed shorts)",
        "positions": [
            {
                "symbol": "SPY260925C00768000",
                "qty": "-1",
                "side": "short",
                "market_value": "-892",
                "avg_entry_price": "8.68",
                "unrealized_pl": "-24",
            },
            {
                "symbol": "SPY260925C00769000",
                "qty": "1",
                "side": "long",
                "market_value": "834",
                "avg_entry_price": "8.17",
                "unrealized_pl": "17",
            },
            {
                "symbol": "SPY261009C00793000",
                "qty": "-1",
                "side": "short",
                "market_value": "-263",
                "avg_entry_price": "2.95",
                "unrealized_pl": "32",
            },
            {
                "symbol": "SPY261009C00809000",
                "qty": "1",
                "side": "long",
                "market_value": "70",
                "avg_entry_price": "0.84",
                "unrealized_pl": "-14",
            },
        ],
    }


def public_broker_lookup() -> dict[str, object]:
    weekend = sanitized_weekend_fill()
    monday = sanitized_monday_fill()
    return {
        "schema": "opticycle.broker-lookup.v1",
        "source": BROKER_LOOKUP_SOURCE,
        "looked_up_at": BROKER_LOOKUP_AT,
        "account_id_omitted": True,
        "mcp_result_hash_present": False,
        "mcp_result_hash_gap": (
            "raw place_option_order MCP result was not retained at submit time; "
            "Alpaca GET-by-client_order_id is the independent broker readback"
        ),
        "fills": [
            {
                **weekend,
                "broker_readback_hash": broker_readback_hash(weekend),
            },
            {
                **monday,
                "broker_readback_hash": broker_readback_hash(monday),
            },
        ],
        "mark_snapshot": mark_snapshot(),
    }
