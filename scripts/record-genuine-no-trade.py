#!/usr/bin/env python3
"""Record a genuine live NO_TRADE only if Alpaca quotes are actually available.

Does not inject a missing quote. Does not place an order. Without keys, writes
the gap honestly and leaves the Gate 9 injected episode unlabeled as genuine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.live_quotes import probe_live_quotes  # noqa: E402
from opticycle.observe import observe_live  # noqa: E402
from opticycle.protocol import ObservationOutcome  # noqa: E402
from opticycle.settings import HackathonSettings  # noqa: E402

STATUS_PATH = ROOT / "artifacts" / "evidence" / "gate11_status.json"


def _status_payload(probe: dict, *, extra: dict | None = None) -> dict:
    payload = {
        "schema": "opticycle.gate11-status.v1",
        "live_fill_claimed": False,
        "live_quotes_available": bool(probe.get("available")),
        "genuine_no_trade_recorded": False,
        "injected_no_trade_promoted": False,
        "injected_no_trade_caveat": (
            "live-path + injected missing quote; NOT an Alpaca true quote-miss; "
            "NOT fill evidence; NOT a live MATCHED / MLEG / fill claim"
        ),
        "live_quote_gap": probe.get("reason"),
        "demo_mp4": "NOT submission footage",
        "pnl_reconcile": "fixture-tested; not stamped as live",
    }
    if extra:
        payload.update(extra)
    return payload


def main() -> int:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    probe = probe_live_quotes()
    if not probe["available"]:
        STATUS_PATH.write_text(json.dumps(_status_payload(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(_status_payload(probe), indent=2, sort_keys=True))
        return 0
    observation = observe_live(HackathonSettings())
    extra = {
        "observation_outcome": observation.outcome.value,
        "observation_reason": observation.reason,
    }
    genuine = (
        observation.outcome == ObservationOutcome.NO_TRADE
        and "injected" not in observation.reason.lower()
        and observation.reason != "SPY quote missing"
    )
    extra["genuine_no_trade_recorded"] = bool(genuine)
    if genuine:
        extra["note"] = (
            "A genuine NO_TRADE was observed. Export it with the runner ledger path; "
            "do not overwrite artifacts/evidence/no_trade.public.jsonl."
        )
        print("genuine NO_TRADE observed; not overwriting injected Gate 9 export", file=sys.stderr)
        print(observation.reason)
        STATUS_PATH.write_text(json.dumps(_status_payload(probe, extra=extra), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    extra["genuine_no_trade_recorded"] = False
    extra["live_quote_gap"] = (
        f"live quotes reachable but outcome={observation.outcome.value}: {observation.reason}; "
        "no genuine NO_TRADE recorded; injected Gate 9 episode stays labeled injected"
    )
    STATUS_PATH.write_text(json.dumps(_status_payload(probe, extra=extra), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(_status_payload(probe, extra=extra), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
