"""Option order request model for official Alpaca MCP."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

OCC_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
POSITION_INTENTS = {
    "BUY_TO_OPEN": "buy_to_open",
    "BUY_TO_CLOSE": "buy_to_close",
    "SELL_TO_OPEN": "sell_to_open",
    "SELL_TO_CLOSE": "sell_to_close",
    "BUY": "buy_to_open",
    "SELL": "sell_to_close",
}


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

    def to_cli_argv(self, binary: str = "alpaca") -> list[str]:
        self.assert_options_instrument()
        argv = [
            binary,
            "order",
            "submit",
            "--qty",
            str(int(self.qty)),
            "--type",
            "limit" if self.limit_price is not None else self.order_type,
            "--time-in-force",
            "day",
            "--output",
            "json",
        ]
        if self.is_multileg:
            import json

            argv.extend(["--order-class", "mleg", "--legs", json.dumps(self.legs)])
            if self.limit_price is not None:
                argv.extend(["--limit-price", str(self.limit_price)])
            return argv
        argv.extend(["--symbol", str(self.symbol), "--side", str(self.side)])
        if self.position_intent:
            argv.extend(["--position-intent", self.position_intent])
        if self.limit_price is not None:
            argv.extend(["--limit-price", str(self.limit_price)])
        if self.client_order_id:
            argv.extend(["--client-order-id", self.client_order_id])
        return argv


def decision_to_option_order(decision: Any) -> OptionOrderRequest:
    """Convert an ExecutionDecision-like object into an option order request."""
    metadata = dict(getattr(decision, "metadata", None) or {})
    action = str(getattr(decision, "action", "") or "").upper()
    side = str(getattr(decision, "side", "") or "").lower() or None
    quantity = int(getattr(decision, "quantity", 0) or 0)
    if quantity <= 0:
        raise ExecutionRejected("option quantity must be a positive whole number")
    symbol = str(getattr(decision, "symbol", "") or "").upper() or None
    order_type = str(getattr(decision, "order_type", "market") or "market").lower()
    limit_price = getattr(decision, "limit_price", None)
    legs = metadata.get("legs")
    order_class = metadata.get("order_class")
    intent = metadata.get("position_intent") or POSITION_INTENTS.get(action)
    if order_class == "mleg" or legs:
        normalized_legs = [_normalize_leg(leg) for leg in (legs or [])]
        return OptionOrderRequest(
            qty=quantity,
            order_type="limit" if limit_price is not None else order_type,
            limit_price=float(limit_price) if limit_price is not None else None,
            order_class="mleg",
            legs=normalized_legs,
            client_order_id=metadata.get("client_order_id"),
            reason=str(getattr(decision, "reason", "") or ""),
            metadata=metadata,
        )
    return OptionOrderRequest(
        qty=quantity,
        symbol=symbol,
        side=side,
        order_type=order_type,
        position_intent=intent,
        limit_price=float(limit_price) if limit_price is not None else None,
        client_order_id=metadata.get("client_order_id"),
        reason=str(getattr(decision, "reason", "") or ""),
        metadata=metadata,
    )


def _normalize_leg(leg: dict[str, Any]) -> dict[str, Any]:
    symbol = str(leg.get("symbol") or "").upper()
    ratio = str(leg.get("ratio_qty") or leg.get("ratio") or "1")
    payload: dict[str, Any] = {"symbol": symbol, "ratio_qty": ratio}
    if leg.get("side"):
        payload["side"] = str(leg["side"]).lower()
    if leg.get("position_intent"):
        payload["position_intent"] = str(leg["position_intent"]).lower()
    return payload
