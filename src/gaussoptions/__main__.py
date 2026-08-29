"""CLI: python -m src.gaussoptions --once --backend mcp --dry-run"""

from __future__ import annotations

import argparse
import json

from src.gaussoptions.profile import HackathonProfile
from src.gaussoptions.runner import run_once
from src.trade.cli.alpaca_cli_executor import AlpacaCliExecutor
from src.trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor


def main() -> None:
    parser = argparse.ArgumentParser(description="GaussOptions Agent")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--backend", choices=("mcp", "cli"), default="mcp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profile = HackathonProfile(execution_backend=args.backend)

    def fake_mcp(tool: str, payload: dict) -> dict:
        return {"tool": tool, "dry_run": True, "payload": payload, "id": "sim-mcp-1"}

    def fake_cli(argv) -> dict:
        return {"argv": list(argv), "dry_run": True, "id": "sim-cli-1"}

    executor = (
        AlpacaMcpExecutor(fake_mcp)
        if args.backend == "mcp"
        else AlpacaCliExecutor(fake_cli)
    )
    if not args.once:
        raise SystemExit("only --once is supported in this build")
    result = run_once(
        profile,
        executor,
        {"option_symbol": "SPY250919P00580000", "qty": 1, "notional": 2500},
        {"equity": 100000, "trades_today": 0},
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
