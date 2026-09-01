#!/usr/bin/env python3
"""Close open paper SPY credit verticals via official MCP place_option_order.

Paper only. Uses uvx alpaca-mcp-server==2.3.0 tool place_option_order
(order_class=mleg) with buy_to_close / sell_to_close. Does not use alpaca-py
submit_order. Writes a sanitized report to data/close_last.json (gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if os.environ.get("OPTICYCLE_IGNORE_DOTENV", "").strip() != "1":
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

from opticycle.observe import AlpacaReadClient, ObservationClosed  # noqa: E402
from opticycle.protocol import OCC_SYMBOL_RE  # noqa: E402
from trade.mcp.alpaca_mcp_executor import (  # noqa: E402
    PLACE_OPTION_ORDER,
    default_mcp_client_factory,
    digest_canonical,
    mcp_env_from_os,
    parse_mcp_result,
    serialize_mcp_raw,
)

LAST_PATH = ROOT / "data" / "close_last.json"


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    if parsed.is_nan():
        return None
    return parsed


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _signed_qty(position: Any) -> Decimal:
    qty = _dec(getattr(position, "qty", None)) or Decimal("0")
    side = str(getattr(getattr(position, "side", None), "value", getattr(position, "side", "")) or "").lower()
    if "short" in side and qty > 0:
        return -qty
    return qty


def _pair_verticals(positions: list[Any]) -> list[dict[str, Any]]:
    by_expiry: dict[str, list[Any]] = defaultdict(list)
    for item in positions:
        symbol = str(getattr(item, "symbol", "") or "").upper()
        if not OCC_SYMBOL_RE.fullmatch(symbol):
            continue
        by_expiry[symbol[-15:-9]].append(item)
    pairs: list[dict[str, Any]] = []
    for expiry, group in sorted(by_expiry.items()):
        shorts = [item for item in group if _signed_qty(item) < 0]
        longs = [item for item in group if _signed_qty(item) > 0]
        for short, long in zip(shorts, longs):
            pairs.append(
                {
                    "expiry": expiry,
                    "short": str(getattr(short, "symbol", "")).upper(),
                    "long": str(getattr(long, "symbol", "")).upper(),
                    "qty": 1,
                }
            )
    return pairs


def _quote_map(chain_payload: Any) -> dict[str, Any]:
    data = getattr(chain_payload, "data", chain_payload)
    if isinstance(data, dict):
        return {str(key).upper(): value for key, value in data.items()}
    out: dict[str, Any] = {}
    if isinstance(data, list):
        for item in data:
            symbol = str(getattr(item, "symbol", "") or "").upper()
            if symbol:
                out[symbol] = item
    return out


def _bid_ask(snap: Any) -> tuple[Decimal | None, Decimal | None]:
    latest = getattr(snap, "latest_quote", None) or snap
    bid = _dec(getattr(latest, "bid_price", None) or getattr(snap, "bid_price", None))
    ask = _dec(getattr(latest, "ask_price", None) or getattr(snap, "ask_price", None))
    return bid, ask


def _close_limit(short_snap: Any, long_snap: Any, *, width: Decimal) -> Decimal | None:
    short_bid, short_ask = _bid_ask(short_snap)
    long_bid, long_ask = _bid_ask(long_snap)
    if short_ask is None or long_bid is None or short_ask <= 0 or long_bid <= 0:
        return None
    debit = short_ask - long_bid
    if debit <= 0:
        debit = Decimal("0.01")
    padded = debit + Decimal("0.20")
    if width > 0:
        padded = min(padded, width)
    return padded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _strike(symbol: str) -> Decimal:
    return Decimal(symbol[-8:]) / Decimal("1000")


async def _mcp_place(arguments: dict[str, Any]) -> dict[str, Any]:
    opened = default_mcp_client_factory(env=mcp_env_from_os())
    if hasattr(opened, "__aenter__"):
        session = await opened.__aenter__()
        try:
            raw = await session.call_tool(PLACE_OPTION_ORDER, arguments)
        finally:
            if hasattr(opened, "__aexit__"):
                await opened.__aexit__(None, None, None)
    else:
        raw = await opened.call_tool(PLACE_OPTION_ORDER, arguments)
    serialized = serialize_mcp_raw(raw)
    parsed = parse_mcp_result(raw)
    return {
        "tool": PLACE_OPTION_ORDER,
        "arguments": arguments,
        "arguments_hash": digest_canonical(arguments),
        "raw_result_hash": digest_canonical(serialized),
        "parsed": parsed,
        "submitted": True,
    }


def _sanitize(value: Any) -> Any:
    blob = json.dumps(value, default=str)
    blob = __import__("re").sub(r"\bPA[A-Z0-9]{8,}\b", "omitted", blob)
    return json.loads(blob)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Close paper SPY verticals via MCP MLEG")
    parser.add_argument("--confirm", action="store_true", help="Required to submit close orders")
    args = parser.parse_args(argv)
    os.environ["ALPACA_PAPER_TRADE"] = "true"
    os.environ["ALPACA_LIVE_TRADE"] = "false"
    if str(os.environ.get("ALPACA_LIVE_TRADE") or "").strip().lower() == "true":
        print("ALPACA_LIVE_TRADE must not be true", file=sys.stderr)
        return 2
    if not args.confirm:
        print("pass --confirm to submit close MLEGs", file=sys.stderr)
        return 2

    try:
        client = AlpacaReadClient.from_env()
        clock = client.fetch_clock()
        positions = list(client.fetch_positions() or [])
        chain = client.fetch_option_chain("SPY")
    except ObservationClosed as exc:
        print(json.dumps({"ok": False, "blocked": exc.reason}))
        return 1

    is_open = bool(getattr(clock, "is_open", False))
    report: dict[str, Any] = {
        "schema": "opticycle.close-vertical.v1",
        "clock_open": is_open,
        "submitted": [],
        "blocked": None,
    }
    if not is_open:
        report["blocked"] = "regular session is closed"
        LAST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_PATH.write_text(json.dumps(_sanitize(report), indent=2, sort_keys=True) + "\n")
        print(json.dumps(_sanitize(report), indent=2, sort_keys=True))
        return 0

    quotes = _quote_map(chain)
    pairs = _pair_verticals(positions)
    report["pairs"] = [{"expiry": row["expiry"], "short": row["short"], "long": row["long"]} for row in pairs]
    if not pairs:
        report["blocked"] = "no option verticals to close"
        LAST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_PATH.write_text(json.dumps(_sanitize(report), indent=2, sort_keys=True) + "\n")
        print(json.dumps(_sanitize(report), indent=2, sort_keys=True))
        return 0

    for row in pairs:
        short_sym = row["short"]
        long_sym = row["long"]
        width = abs(_strike(short_sym) - _strike(long_sym))
        limit = _close_limit(quotes.get(short_sym), quotes.get(long_sym), width=width)
        if limit is None:
            report["submitted"].append({"short": short_sym, "long": long_sym, "ok": False, "reason": "missing quotes"})
            continue
        arguments = {
            "order_class": "mleg",
            "type": "limit",
            "time_in_force": "day",
            "qty": "1",
            "limit_price": _money(limit),
            "client_order_id": f"oc-close-{uuid.uuid4().hex[:16]}",
            "legs": [
                {
                    "symbol": short_sym,
                    "ratio_qty": "1",
                    "side": "buy",
                    "position_intent": "buy_to_close",
                },
                {
                    "symbol": long_sym,
                    "ratio_qty": "1",
                    "side": "sell",
                    "position_intent": "sell_to_close",
                },
            ],
        }
        try:
            result = asyncio.run(_mcp_place(arguments))
        except Exception as exc:
            report["submitted"].append(
                {
                    "short": short_sym,
                    "long": long_sym,
                    "ok": False,
                    "reason": type(exc).__name__,
                    "limit_price": _money(limit),
                }
            )
            continue
        parsed = result.get("parsed") or {}
        report["submitted"].append(
            {
                "short": short_sym,
                "long": long_sym,
                "ok": True,
                "limit_price": _money(limit),
                "client_order_id": arguments["client_order_id"],
                "raw_result_hash": result.get("raw_result_hash"),
                "arguments_hash": result.get("arguments_hash"),
                "broker_order_id": parsed.get("id") or parsed.get("order_id") or (parsed.get("order") or {}).get("id"),
                "status": parsed.get("status") or (parsed.get("order") or {}).get("status"),
            }
        )

    LAST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_PATH.write_text(json.dumps(_sanitize(report), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_sanitize(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
