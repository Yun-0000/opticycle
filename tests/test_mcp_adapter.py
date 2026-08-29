from __future__ import annotations

import pytest

from trade.mcp.alpaca_mcp_executor import (
    PLACE_OPTION_ORDER,
    AlpacaMcpExecutor,
    parse_mcp_result,
)
from trade.orders import ExecutionRejected, OptionOrderRequest


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"id": "mcp-order-1", "status": "accepted", "ok": True}


def _put() -> OptionOrderRequest:
    return OptionOrderRequest(
        qty=1,
        symbol="SPY250919P00475000",
        side="sell",
        order_type="limit",
        limit_price=1.25,
        position_intent="sell_to_open",
        client_order_id="csp-1",
    )


def test_mcp_dry_run_does_not_call_client() -> None:
    client = FakeMcpClient()
    executor = AlpacaMcpExecutor(client=client, dry_run=True)
    result = executor.place_option_order_sync(_put())
    assert result["dry_run"] is True
    assert result["backend"] == "mcp"
    assert result["tool"] == PLACE_OPTION_ORDER
    assert result["arguments"]["symbol"] == "SPY250919P00475000"
    assert result["arguments"]["position_intent"] == "sell_to_open"
    assert client.calls == []


def test_mcp_place_option_order_uses_tool_not_sdk() -> None:
    client = FakeMcpClient()
    executor = AlpacaMcpExecutor(client=client, dry_run=False)
    result = executor.place_option_order_sync(_put())
    assert result["id"] == "mcp-order-1"
    assert client.calls == [
        (
            PLACE_OPTION_ORDER,
            {
                "qty": "1",
                "type": "limit",
                "time_in_force": "day",
                "client_order_id": "csp-1",
                "symbol": "SPY250919P00475000",
                "side": "sell",
                "position_intent": "sell_to_open",
                "limit_price": "1.25",
            },
        )
    ]


def test_mcp_multileg_vertical_spread_payload() -> None:
    client = FakeMcpClient()
    request = OptionOrderRequest(
        qty=1,
        order_class="mleg",
        limit_price=0.85,
        legs=[
            {
                "symbol": "SPY250919P00485000",
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "SPY250919P00475000",
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
        ],
    )
    AlpacaMcpExecutor(client=client, dry_run=False).place_option_order_sync(request)
    name, arguments = client.calls[0]
    assert name == PLACE_OPTION_ORDER
    assert arguments["order_class"] == "mleg"
    assert len(arguments["legs"]) == 2


def test_mcp_rejects_equity_symbol() -> None:
    request = OptionOrderRequest(qty=1, symbol="SPY", side="buy")
    with pytest.raises(ExecutionRejected):
        AlpacaMcpExecutor(dry_run=True).place_option_order_sync(request)


def test_mcp_stdio_params_pin_uvx_server() -> None:
    from trade.mcp.alpaca_mcp_executor import MCP_SERVER_SPEC, _stdio_params

    params = _stdio_params(MCP_SERVER_SPEC, {"ALPACA_PAPER_TRADE": "true"})
    assert params.command == "uvx"
    assert params.args == ["alpaca-mcp-server==2.3.0"]


def test_parse_mcp_error_result() -> None:
    with pytest.raises(RuntimeError):
        parse_mcp_result({"is_error": True, "message": "rejected"})
