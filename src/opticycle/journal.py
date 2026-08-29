"""Append-only JSONL event journal plus Evidence Ledger handle."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opticycle.ledger import AppendOnlyError, EvidenceLedger


class TradeJournal:
    def __init__(
        self,
        path: Path | str = Path("data/journal.jsonl"),
        *,
        evidence: EvidenceLedger | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence = evidence or EvidenceLedger(self.path.with_name("ledger.raw.jsonl"))

    def record(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "event": event,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        return entry

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise AppendOnlyError("trade journal is append-only; no selective delete")

    def clear(self) -> None:
        raise AppendOnlyError("trade journal is append-only; no selective delete")

    def purge(self) -> None:
        raise AppendOnlyError("trade journal is append-only; no selective delete")

    def overwrite(self, *args: Any, **kwargs: Any) -> None:
        raise AppendOnlyError("trade journal is append-only; rewrite is forbidden")
