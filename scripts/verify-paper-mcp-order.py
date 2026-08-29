#!/usr/bin/env python3
"""Prove the paper option order path: decision → risk gate → MCP/CLI.

CI / default: --dry-run (no live Alpaca keys, no submit).

Without --dry-run the script places a real paper option order through Alpaca MCP
(primary) or official Alpaca CLI (fallback). Keys stay in the environment only:

  ALPACA_API_KEY
  ALPACA_SECRET_KEY
  ALPACA_PAPER_TRADE=true
  ALPACA_LIVE_TRADE=false   (must not be true)
  HACKATHON_EXECUTION_BACKEND=mcp|cli   (optional; --backend wins)

Never commit API keys.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VENDOR = ROOT / "vendor" / "pin-31374551"
for path in (str(VENDOR), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from opticycle.runner import run_once
from opticycle.settings import HackathonSettings


def _require_paper_env() -> None:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        print(
            "live paper verify needs env ALPACA_API_KEY and ALPACA_SECRET_KEY "
            "(never commit keys); use --dry-run without credentials",
            file=sys.stderr,
        )
        raise SystemExit(2)
    live = (os.environ.get("ALPACA_LIVE_TRADE") or "").strip().lower()
    if live == "true":
        print("ALPACA_LIVE_TRADE must not be true; paper only", file=sys.stderr)
        raise SystemExit(2)
    os.environ["ALPACA_PAPER_TRADE"] = "true"
    os.environ["ALPACA_LIVE_TRADE"] = "false"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify MCP/CLI paper option order path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not spawn MCP/CLI or submit; no live keys required",
    )
    parser.add_argument("--backend", choices=["mcp", "cli"], default="mcp")
    parser.add_argument("--strategy", choices=["wheel", "vertical_spread"], default="wheel")
    args = parser.parse_args(argv)
    if not args.dry_run:
        _require_paper_env()
    settings = HackathonSettings(
        execution_backend=args.backend,
        strategy=args.strategy,
    )
    result = run_once(settings, dry_run=args.dry_run)
    if not result.get("ok"):
        print(json.dumps(result, default=str), file=sys.stderr)
        return 1
    backend = result["order"].get("backend")
    tool = result["order"].get("tool")
    argv_sent = result["order"].get("argv")
    if args.backend == "mcp" and args.dry_run and tool != "place_option_order":
        print("expected MCP place_option_order", file=sys.stderr)
        return 1
    if args.backend == "cli" and args.dry_run and not argv_sent:
        print("expected CLI argv", file=sys.stderr)
        return 1
    if args.backend == "mcp" and not args.dry_run and not (
        result["order"].get("ok") or result["order"].get("id") or result["order"].get("order_id")
    ):
        print("expected a paper MCP order id", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "backend": backend,
                "strategy": result["strategy"],
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
