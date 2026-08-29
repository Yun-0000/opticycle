"""CLI: python -m opticycle run --profile hackathon --backend mcp --once --dry-run"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from opticycle.runner import run_loop
from opticycle.settings import HackathonSettings, STOCK_STRATEGIES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opticycle", description="Opticycle")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the autonomous options cycle")
    run.add_argument("--profile", default="hackathon", choices=["hackathon"])
    run.add_argument("--backend", choices=["mcp"], default=None)
    run.add_argument("--strategy", choices=["vertical_spread"], default=None)
    run.add_argument("--once", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.error("unknown command")
    if args.profile != "hackathon":
        parser.error("only the hackathon profile is enabled")
    updates: dict[str, str] = {}
    if args.backend:
        if args.backend != "mcp":
            parser.error("official MCP is the only live execution channel")
        updates["execution_backend"] = "mcp"
    if args.strategy:
        if args.strategy in STOCK_STRATEGIES:
            parser.error("stock-only strategies are disabled")
        if args.strategy != "vertical_spread":
            parser.error("only SPY defined-risk vertical is enabled")
        updates["strategy"] = args.strategy
    settings = HackathonSettings(**updates)
    os.environ["EXECUTION_BACKEND"] = settings.execution_backend
    return run_loop(settings, dry_run=args.dry_run, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
