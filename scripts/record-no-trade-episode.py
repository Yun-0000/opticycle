#!/usr/bin/env python3
"""Record a real NO_TRADE Evidence Ledger episode from the live observation path.

Does not place an order. Quotes may be live; this recorder uses the live
observation path with a missing SPY quote so the outcome is NO_TRADE.
Live MLEG submit / broker receipt / fill / P&L remain incomplete until Yun
confirms the exact paper order.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.journal import TradeJournal
from opticycle.ledger import current_commit_sha
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings


class MissingQuoteObserver:
    def fetch_account(self):
        return SimpleNamespace(
            id="PA3V84C40PJQ",
            account_number="PA3V84C40PJQ",
            equity="100000",
            buying_power="100000",
            cash="100000",
            daytrade_count=0,
            options_approved_level="2",
        )

    def fetch_positions(self):
        return []

    def fetch_open_orders(self):
        return []

    def fetch_fills(self):
        return []

    def fetch_clock(self):
        return SimpleNamespace(is_open=True, timestamp=datetime.now(timezone.utc))

    def fetch_quote(self, symbol: str):
        return None

    def fetch_bars(self, symbol: str):
        return {"SPY": []}

    def fetch_option_chain(self, symbol: str):
        return {}

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None):
        return None

    def fetch_orders_by_client_id(self, client_order_id: str):
        return []


def main() -> int:
    dest_dir = ROOT / "artifacts" / "evidence"
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="opticycle-evidence-"))
    journal = TradeJournal(tmp / "journal.jsonl")
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=MissingQuoteObserver(),
        journal=journal,
        provenance="live_paper",
    )
    if result.get("outcome") != "NO_TRADE" or result.get("order") is not None:
        print(result, file=sys.stderr)
        return 1
    public_path = dest_dir / "no_trade.public.jsonl"
    claims_path = dest_dir / "claims.json"
    public = journal.evidence.export_public(public_path)
    claims_path.write_text(json.dumps(journal.evidence.claims_index(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    row = public[-1]
    print(f"commit_sha={row['commit_sha']}")
    print(f"record_id={row['record_id']}")
    print(f"claim={row['claim']}")
    print(f"outcome={row['outcome']}")
    print(f"channel={row['channel']}")
    print(f"HEAD={current_commit_sha()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
