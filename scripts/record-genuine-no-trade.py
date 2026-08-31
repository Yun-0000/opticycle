#!/usr/bin/env python3
"""Record a genuine live NO_TRADE only if Alpaca quotes are actually available.

Does not inject a missing quote. Does not place an order. Merges Gate 11 status
so live fill claims are not wiped. Without keys, writes the gap honestly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.evidence_public import DEMO_VIDEO_STATUS, GATE11_STATUS_PATH  # noqa: E402
from opticycle.live_matched_fills import LIVE_MATCHED_CLIENT_IDS  # noqa: E402
from opticycle.live_quotes import probe_live_quotes  # noqa: E402
from opticycle.observe import observe_live  # noqa: E402
from opticycle.protocol import ObservationOutcome  # noqa: E402
from opticycle.settings import HackathonSettings  # noqa: E402


def _load_existing() -> dict:
    if not GATE11_STATUS_PATH.is_file():
        return {}
    loaded = json.loads(GATE11_STATUS_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _status_payload(probe: dict, *, extra: dict | None = None) -> dict:
    existing = _load_existing()
    payload = {
        "schema": "opticycle.gate11-status.v1",
        "live_fill_claimed": bool(existing.get("live_fill_claimed")),
        "matched_claimed": bool(existing.get("matched_claimed")),
        "live_quotes_available": bool(probe.get("available")),
        "genuine_no_trade_recorded": False,
        "injected_no_trade_promoted": False,
        "injected_no_trade_caveat": (
            "live-path + injected missing quote; NOT an Alpaca true quote-miss; "
            "NOT fill evidence; NOT a live MATCHED / MLEG / fill claim"
        ),
        "live_quote_gap": probe.get("reason"),
        "demo_mp4": existing.get("demo_mp4") or DEMO_VIDEO_STATUS,
        "pnl_reconcile": existing.get("pnl_reconcile") or "fixture-tested; not stamped as live",
        "yun_authorized_one_paper_mleg": True,
        "sanitized_json_provided": bool(existing.get("sanitized_json_provided")),
        "authorized_live_client_order_ids": sorted(LIVE_MATCHED_CLIENT_IDS),
    }
    if extra:
        payload.update(extra)
    return payload


def main() -> int:
    GATE11_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    probe = probe_live_quotes()
    if not probe["available"]:
        existing = _load_existing()
        if existing.get("genuine_no_trade_recorded") or existing.get("live_fill_claimed"):
            print(json.dumps({**existing, "probe_without_keys": probe}, indent=2, sort_keys=True))
            return 0
        GATE11_STATUS_PATH.write_text(
            json.dumps(_status_payload(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(_status_payload(probe), indent=2, sort_keys=True))
        return 0
    observation = observe_live(HackathonSettings())
    extra = {
        "observation_outcome": observation.outcome.value,
        "observation_reason": observation.reason,
        "live_quotes_reachable": True,
    }
    genuine = (
        observation.outcome == ObservationOutcome.NO_TRADE
        and "injected" not in observation.reason.lower()
        and observation.reason != "SPY quote missing"
    )
    extra["genuine_no_trade_recorded"] = bool(genuine)
    if genuine:
        extra["note"] = (
            "A genuine NO_TRADE was observed on the live Alpaca path. "
            "Export it as artifacts/evidence/genuine_no_trade.public.jsonl; "
            "do not overwrite artifacts/evidence/no_trade.public.jsonl."
        )
        extra["live_quote_gap"] = observation.reason
        print("genuine NO_TRADE observed; not overwriting injected Gate 9 export", file=sys.stderr)
        print(observation.reason)
        GATE11_STATUS_PATH.write_text(
            json.dumps(_status_payload(probe, extra=extra), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    extra["genuine_no_trade_recorded"] = False
    extra["live_quote_gap"] = (
        f"live quotes reachable but outcome={observation.outcome.value}: {observation.reason}; "
        "no genuine NO_TRADE recorded; injected Gate 9 episode stays labeled injected"
    )
    GATE11_STATUS_PATH.write_text(
        json.dumps(_status_payload(probe, extra=extra), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(_status_payload(probe, extra=extra), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
