from __future__ import annotations

import asyncio

import pytest

from trade.mcp.alpaca_mcp_executor import (
    PLACE_OPTION_ORDER,
    AlpacaMcpExecutor,
    McpCallTimeout,
    call_mcp_tool,
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


def test_mcp_place_option_order_cannot_submit_live_without_certificate() -> None:
    client = FakeMcpClient()
    executor = AlpacaMcpExecutor(client=client, dry_run=False)
    with pytest.raises(ExecutionRejected, match="Risk Certificate"):
        executor.place_option_order_sync(_put())
    assert client.calls == []


def test_mcp_uncertified_multileg_cannot_submit_live() -> None:
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
    with pytest.raises(ExecutionRejected, match="Risk Certificate"):
        AlpacaMcpExecutor(client=client, dry_run=False).place_option_order_sync(request)
    assert client.calls == []


def test_mcp_rejects_equity_symbol() -> None:
    request = OptionOrderRequest(qty=1, symbol="SPY", side="buy")
    with pytest.raises(ExecutionRejected):
        AlpacaMcpExecutor(dry_run=True).place_option_order_sync(request)


def test_mcp_stdio_params_pin_uvx_server() -> None:
    from trade.mcp.alpaca_mcp_executor import MCP_SERVER_SPEC, _stdio_params

    params = _stdio_params(MCP_SERVER_SPEC, {"ALPACA_PAPER_TRADE": "true"})
    assert params.command == "uvx"
    assert params.args == ["--with", "fastmcp>=3.1.0,<4", "alpaca-mcp-server==2.3.0"]


def test_parse_mcp_error_result() -> None:
    with pytest.raises(RuntimeError):
        parse_mcp_result({"is_error": True, "message": "rejected"})


class SlowMcpClient:
    async def call_tool(self, name: str, arguments: dict) -> dict:
        await asyncio.sleep(1)
        return {"id": "too-late"}


def test_call_mcp_tool_times_out_without_a_broker_result() -> None:
    with pytest.raises(McpCallTimeout, match="GET-by-client_order_id"):
        asyncio.run(call_mcp_tool(SlowMcpClient(), PLACE_OPTION_ORDER, {"order_class": "mleg"}, timeout=0.05))
