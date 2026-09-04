#!/usr/bin/env python3
"""Capture sanitized account/positions/orders from official Alpaca CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from opticycle.alpaca_cli_readonly import AlpacaCliReadError, write_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts" / "evidence" / "alpaca_cli_snapshot.json",
    )
    args = parser.parse_args(argv)
    try:
        payload = write_snapshot(args.out)
    except AlpacaCliReadError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 1
    print(json.dumps({"ok": True, "path": str(args.out), "snapshot_hash": payload["snapshot_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
