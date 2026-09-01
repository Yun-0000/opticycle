#!/usr/bin/env python3
"""Check that every golden video fact is present on the judge evidence page."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "remotion" / "src" / "golden.ts"
PAGE = ROOT / "artifacts" / "evidence" / "index.html"
VALUE_RE = re.compile(r'^\s+[A-Za-z][A-Za-z0-9]*:\s*"([^"]+)"', re.MULTILINE)


def main() -> int:
    values = VALUE_RE.findall(GOLDEN.read_text(encoding="utf-8"))
    if not values:
        raise AssertionError("no golden video facts found")
    page = PAGE.read_text(encoding="utf-8").lower()
    missing = [value for value in values if value.lower() not in page]
    if missing:
        raise AssertionError(f"golden video facts missing from evidence page: {missing}")
    print(f"verified {len(values)} golden video facts against artifacts/evidence/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
