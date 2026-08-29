"""Place paper option orders through Alpaca MCP Server tools."""

from __future__ import annotations

from typing import Any, Callable, Mapping


class AlpacaMcpExecutor:
    """Primary executor. `call_tool` is injected so tests can mock MCP."""

    def __init__(self, call_tool: Callable[[str, Mapping[str, Any]], Any]):
        self._call_tool = call_tool

    def place_option_order(self, order: Mapping[str, Any]) -> dict[str, Any]:
        if order.get("asset_class") != "option":
            raise ValueError("hackathon profile requires option orders")
        payload = {
            "symbol": order["symbol"],
            "qty": order["qty"],
            "side": order["side"],
            "type": order.get("type", "market"),
            "time_in_force": order.get("time_in_force", "day"),
            "asset_class": "option",
        }
        result = self._call_tool("place_order", payload)
        return {"backend": "mcp", "order": payload, "result": result}
