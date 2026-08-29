#!/usr/bin/env python3
"""Prove the paper option order path: decision → risk gate → MCP/CLI.

Default and CI: --dry-run (no live Alpaca keys).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VENDOR = ROOT / "vendor" / "pin-31374551"
for path in (str(VENDOR), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from gaussoptions.runner import run_once
from gaussoptions.settings import HackathonSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify MCP/CLI paper option order path")
    parser.add_argument("--dry-run", action="store_true", help="Do not spawn MCP/CLI or use live keys")
    parser.add_argument("--backend", choices=["mcp", "cli"], default="mcp")
    parser.add_argument("--strategy", choices=["wheel", "vertical_spread"], default="wheel")
    args = parser.parse_args(argv)
    if not args.dry_run:
        print("refusing live verify without --dry-run (CI must not use Alpaca keys)", file=sys.stderr)
        return 2
    settings = HackathonSettings(
        execution_backend=args.backend,
        strategy=args.strategy,
    )
    result = run_once(settings, dry_run=True)
    if not result.get("ok"):
        print(json.dumps(result, default=str), file=sys.stderr)
        return 1
    backend = result["order"].get("backend")
    tool = result["order"].get("tool")
    argv_sent = result["order"].get("argv")
    if args.backend == "mcp" and tool != "place_option_order":
        print("expected MCP place_option_order", file=sys.stderr)
        return 1
    if args.backend == "cli" and not argv_sent:
        print("expected CLI argv", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "backend": backend, "strategy": result["strategy"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
