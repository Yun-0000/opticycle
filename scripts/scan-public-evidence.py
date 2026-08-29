#!/usr/bin/env python3
"""Refuse secrets, account IDs, and upstream names on public evidence artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticycle.evidence_public import (  # noqa: E402
    GATE11_STATUS_PATH,
    MANIFEST_PATH,
    NO_TRADE_JSONL,
    PAGE_PATH,
    PAPER_FILL_INGEST_PATH,
    PUBLIC_JSONL,
    load_jsonl,
    scan_public_blob,
    scan_public_text,
)


def main() -> int:
    hits: list[str] = []
    for path in (NO_TRADE_JSONL, PUBLIC_JSONL, MANIFEST_PATH, PAGE_PATH, GATE11_STATUS_PATH, PAPER_FILL_INGEST_PATH):
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            return 1
        text = path.read_text(encoding="utf-8")
        hits.extend(scan_public_text(text, source=str(path.relative_to(ROOT))))
        if path.suffix in {".json", ".jsonl"}:
            if path.suffix == ".jsonl":
                for row in load_jsonl(path):
                    hits.extend(scan_public_blob(row, source=str(path.relative_to(ROOT))))
            else:
                import json

                hits.extend(scan_public_blob(json.loads(text), source=str(path.relative_to(ROOT))))
    if hits:
        print("secret scan failed:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 1
    print("public evidence scan clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
