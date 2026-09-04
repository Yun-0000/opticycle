#!/usr/bin/env python3
"""Regular-session automation entry. Paper only. At most one new MLEG with --submit.

Does not close existing positions. Cloud CI should omit --submit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if os.environ.get("OPTICYCLE_IGNORE_DOTENV", "").strip() != "1":
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

from opticycle.open_session import run_open_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Observe live; optionally submit one paper MLEG")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Allow at most one certified paper MLEG if ThesisAgent accepts",
    )
    args = parser.parse_args(argv)
    os.environ["ALPACA_PAPER_TRADE"] = "true"
    os.environ.setdefault("ALPACA_LIVE_TRADE", "false")
    os.environ.setdefault("HACKATHON_LLM_MODEL", "gpt-5.6-luna")
    report = run_open_session(submit=args.submit)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    if str(report.get("blocked") or "").startswith("missing"):
        return 0
    if report.get("blocked") == "regular session is closed":
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
