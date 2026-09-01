"""Sanitized Alpaca GET-by-client_order_id facts. No account id. No keys."""

from __future__ import annotations

from opticycle.ledger import sha256_json

WEEKEND_CLIENT_ORDER_ID = "oc-204a8dfccffd40c9"
MONDAY_CLIENT_ORDER_ID = "oc-715ad36a630d408e"
SIGNED_CLIENT_ORDER_ID = "oc-63db2a85298b4ecabefab59076a6397e"
CLOSE_MONDAY_CLIENT_ORDER_ID = "oc-close-dd8c560e40524cd5"
CLOSE_WEEKEND_CLIENT_ORDER_ID = "oc-close-ff602cde9ba041ef"

WEEKEND_BROKER_ORDER_ID = "abcb5385-0aa3-42cc-9b58-ef4200235c27"
MONDAY_BROKER_ORDER_ID = "2a6d6b7c-caad-4c24-959a-8d93455a36fe"
SIGNED_BROKER_ORDER_ID = "24b16fe6-0d8d-4478-afa6-0f3781eb6b33"
CLOSE_MONDAY_BROKER_ORDER_ID = "104182d8-00c8-45fa-bfef-d5d80c421443"
CLOSE_WEEKEND_BROKER_ORDER_ID = "437de35d-7d1f-4a11-9b1a-c2c28b8998c5"
BROKER_LOOKUP_AT = "2026-08-31T21:02:23Z"
SIGNED_LOOKUP_AT = "2026-09-01T16:21:30Z"
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


def sanitized_signed_fill() -> dict[str, str | list[dict[str, str]]]:
    return {
        "order_id": SIGNED_BROKER_ORDER_ID,
        "client_order_id": SIGNED_CLIENT_ORDER_ID,
        "limit": "-2.26",
        "status": "filled",
        "filled_avg_price": "-2.26",
        "legs": [
            {"symbol": "SPY261016P00740000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "SPY261016P00724000", "side": "buy", "ratio_qty": "1"},
        ],
    }


def sanitized_close_fills() -> list[dict[str, str | list[dict[str, str]]]]:
    return [
        {
            "order_id": CLOSE_MONDAY_BROKER_ORDER_ID,
            "client_order_id": CLOSE_MONDAY_CLIENT_ORDER_ID,
            "limit": "0.65",
            "status": "filled",
            "filled_avg_price": "0.53",
            "raw_result_hash": "cbda23343257066815e42a22c72ff1e652d1e4805f2694c03b3ad07b62ce423e",
            "arguments_hash": "ad4ad51762c387f8e85c6f81a47b95a3764fe09ec661ea4848edf172fcf47a68",
            "legs": [
                {"symbol": "SPY260925C00768000", "side": "buy", "ratio_qty": "1"},
                {"symbol": "SPY260925C00769000", "side": "sell", "ratio_qty": "1"},
            ],
        },
        {
            "order_id": CLOSE_WEEKEND_BROKER_ORDER_ID,
            "client_order_id": CLOSE_WEEKEND_CLIENT_ORDER_ID,
            "limit": "1.75",
            "status": "filled",
            "filled_avg_price": "1.53",
            "raw_result_hash": "1c4ee69f6ec5285d2994ffefb8d3dc9aed8939d9846f0407520a1b994f26066e",
            "arguments_hash": "f1ec1a22b929a2ec69f9ee611a800ba69d71fd8bf18ddeae683668eb303e4dee",
            "legs": [
                {"symbol": "SPY261009C00793000", "side": "buy", "ratio_qty": "1"},
                {"symbol": "SPY261009C00809000", "side": "sell", "ratio_qty": "1"},
            ],
        },
    ]


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
    signed = sanitized_signed_fill()
    closes = sanitized_close_fills()
    return {
        "schema": "opticycle.broker-lookup.v1",
        "source": BROKER_LOOKUP_SOURCE,
        "looked_up_at": BROKER_LOOKUP_AT,
        "signed_lookup_at": SIGNED_LOOKUP_AT,
        "account_id_omitted": True,
        "mcp_result_hash_present": True,
        "mcp_result_hash_gap": (
            "open credit MLEG oc-63db2a85298b4ecabefab59076a6397e: MCP stdio client "
            "did not return the tool envelope after broker accept; Alpaca GET is the "
            "fill source. Same-session close MLEGs retained raw_result_hash."
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
            {
                **signed,
                "broker_readback_hash": broker_readback_hash(signed),
                "price_bound_matched": True,
            },
        ],
        "closes": [
            {**row, "broker_readback_hash": broker_readback_hash(row)} for row in closes
        ],
        "mark_snapshot": mark_snapshot(),
        "session_2026_09_01": {
            "flatten_equity": "100055.67",
            "flatten_cash": "100055.67",
            "after_signed_fill_equity": "100049.62",
            "after_signed_fill_cash": "100281.62",
            "after_signed_fill_long_market_value": "455",
            "after_signed_fill_short_market_value": "-687",
            "identity": "cash + long_market_value + short_market_value (Alpaca signed shorts)",
            "prior_verticals_closed": True,
            "positions": [
                {
                    "symbol": "SPY261016P00724000",
                    "qty": "1",
                    "side": "long",
                    "avg_entry_price": "4.54",
                },
                {
                    "symbol": "SPY261016P00740000",
                    "qty": "-1",
                    "side": "short",
                    "avg_entry_price": "6.80",
                },
            ],
        },
    }
