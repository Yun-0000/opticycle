"""Append-only JSON trade journal. No secrets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def append(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[Any] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    existing.append(dict(record))
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
