"""Option order request model for official Alpaca MCP."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

OCC_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


class ExecutionRejected(ValueError):
    """Raised when an order cannot be sent on the options-only path."""


@dataclass(slots=True)
class OptionOrderRequest:
    """Paper option order payload for official Alpaca MCP."""

    qty: int
    symbol: str | None = None
    side: str | None = None
    order_type: str = "market"
    time_in_force: str = "day"
    position_intent: str | None = None
    limit_price: float | None = None
    client_order_id: str | None = None
    order_class: str | None = None
    legs: list[dict[str, Any]] | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_multileg(self) -> bool:
        return bool(self.legs) or self.order_class == "mleg"

    def assert_options_instrument(self) -> None:
        if self.is_multileg:
            if not self.legs:
                raise ExecutionRejected("multi-leg order requires legs")
            for index, leg in enumerate(self.legs):
                symbol = str(leg.get("symbol") or "")
                if not OCC_SYMBOL_RE.fullmatch(symbol):
                    raise ExecutionRejected(
                        f"leg[{index}] is not an OCC option symbol: {symbol!r}"
                    )
            return
        if not self.symbol or not OCC_SYMBOL_RE.fullmatch(self.symbol):
            raise ExecutionRejected(
                f"stock-only orders are disabled; need OCC option symbol, got {self.symbol!r}"
            )
        if not self.side:
            raise ExecutionRejected("single-leg option order requires side")

    def to_mcp_args(self) -> dict[str, Any]:
        self.assert_options_instrument()
        args: dict[str, Any] = {
            "qty": str(int(self.qty)),
            "type": self.order_type,
            "time_in_force": "day",
        }
        if self.client_order_id:
            args["client_order_id"] = self.client_order_id
        if self.is_multileg:
            args["order_class"] = "mleg"
            args["legs"] = self.legs
            if self.limit_price is not None:
                args["limit_price"] = str(self.limit_price)
                args["type"] = "limit"
            return args
        args["symbol"] = self.symbol
        args["side"] = self.side
        if self.position_intent:
            args["position_intent"] = self.position_intent
        if self.limit_price is not None:
            args["limit_price"] = str(self.limit_price)
            args["type"] = "limit"
        return args
