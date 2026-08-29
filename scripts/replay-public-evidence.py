#!/usr/bin/env python3
"""Keyless replay of non-live public claims from the sanitized ledger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.evidence_public import (  # noqa: E402
    MANIFEST_PATH,
    load_public_records,
    replay_sanitized_records,
)


def main() -> int:
    records = load_public_records()
    verified = replay_sanitized_records(records)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    claims = manifest["claims"]
    if set(claims) != {item["claim"] for item in verified}:
        print("manifest claims do not match replayed claims", file=sys.stderr)
        return 1
    for item in verified:
        mapped = claims[item["claim"]]
        if mapped["record_id"] != item["record_id"] or mapped["commit_sha"] != item["commit_sha"]:
            print(f"claim mapping mismatch: {item['claim']}", file=sys.stderr)
            return 1
        if mapped.get("live_fill"):
            print("manifest must not claim a live fill", file=sys.stderr)
            return 1
    print(f"replayed {len(verified)} non-live claims keylessly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
