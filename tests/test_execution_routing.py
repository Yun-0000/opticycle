from __future__ import annotations

from types import SimpleNamespace

import pytest

from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor, PLACE_OPTION_ORDER
from trade.orders import ExecutionRejected
from trade.routing import execute_via_backend, dry_run_option_order
from trade.orders import OptionOrderRequest


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"id": "routed-mcp", "ok": True}


def _option_decision(**kwargs) -> SimpleNamespace:
    payload = dict(
        symbol="SPY250919P00475000",
        side="sell",
        quantity=1,
        order_type="limit",
        limit_price=1.25,
        action="SELL_TO_OPEN",
        reason="defined-risk vertical",
        metadata={},
    )
    payload.update(kwargs)
    return SimpleNamespace(**payload)


def test_routing_mcp_sends_option_order() -> None:
    client = FakeMcpClient()
    engine = SimpleNamespace(execute=True, logger=None, mcp_client=client)
    ok = execute_via_backend(
        engine,
        _option_decision(),
        "mcp",
        mcp_executor=AlpacaMcpExecutor(client=client, dry_run=False),
    )
    assert ok is True
    assert client.calls[0][0] == PLACE_OPTION_ORDER


def test_routing_rejects_stock_only_decision() -> None:
    engine = SimpleNamespace(execute=True, logger=None)
    with pytest.raises(ExecutionRejected, match="OCC option symbol"):
        execute_via_backend(engine, _option_decision(symbol="AAPL"), "mcp")


def test_routing_rejects_cli_backend() -> None:
    engine = SimpleNamespace(execute=True, logger=None)
    with pytest.raises(ExecutionRejected, match="official MCP"):
        execute_via_backend(engine, _option_decision(), "cli")


def test_dry_run_option_order_rejects_cli() -> None:
    request = OptionOrderRequest(
        qty=1,
        symbol="SPY250919P00475000",
        side="sell",
        order_type="limit",
        limit_price=1.25,
        position_intent="sell_to_open",
    )
    with pytest.raises(ExecutionRejected, match="official MCP"):
        dry_run_option_order(request, "cli")


def test_routing_dry_run_returns_true_without_live_call() -> None:
    client = FakeMcpClient()
    engine = SimpleNamespace(execute=False, logger=None)
    ok = execute_via_backend(
        engine,
        _option_decision(),
        "mcp",
        mcp_executor=AlpacaMcpExecutor(client=client, dry_run=True),
    )
    assert ok is True
    assert client.calls == []
