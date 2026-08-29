"""Fallback paper option orders through the official Alpaca CLI."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence


class AlpacaCliExecutor:
    """Fallback executor. `run` is injected so tests can mock the CLI."""

    def __init__(self, run: Callable[[Sequence[str]], Any]):
        self._run = run

    def place_option_order(self, order: Mapping[str, Any]) -> dict[str, Any]:
        if order.get("asset_class") != "option":
            raise ValueError("hackathon profile requires option orders")
        args = [
            "alpaca",
            "order",
            "submit",
            "--symbol",
            str(order["symbol"]),
            "--qty",
            str(order["qty"]),
            "--side",
            str(order["side"]),
            "--type",
            str(order.get("type", "market")),
            "--asset-class",
            "option",
        ]
        result = self._run(args)
        return {"backend": "cli", "args": args, "result": result}
