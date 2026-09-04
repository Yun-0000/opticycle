"""Append-only Evidence Ledger (Gate 9).

Private raw JSONL is the source of truth. A sanitized public export is derived
from it and contains no secrets, keys, or account credentials. Replay,
live_paper, and fault_injection episodes are labeled and distinguishable.

The public evidence contains three authorized live paper fills, including one
price-bound MATCHED episode. Missing fields on any new episode remain explicitly
incomplete until a sanitized broker receipt is ingested; evidence is never
inferred or invented.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

EPISODE_FIELDS = (
    "snapshot",
    "thesis",
    "candidate_set",
    "certificate",
    "mcp_attempt",
    "broker_receipt",
    "reconciliation",
    "positions",
    "realized_pnl",
    "unrealized_pnl",
    "end_of_cycle_equity",
    "code_build_id",
)

CHANNELS = ("replay", "live_paper", "fault_injection")
OUTCOMES = ("NO_TRADE", "HALT", "VETO", "ERROR", "PROFIT", "LOSS", "MATCHED", "FILLED")
LEDGER_CLASS_PRIVATE = "private_raw"
LEDGER_CLASS_PUBLIC = "public_sanitized"
GENESIS_HASH = "0" * 64
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

LIVE_PAPER_INCOMPLETE = {
    "code": "LIVE_PAPER_INCOMPLETE",
    "detail": (
        "This episode's live receipt/fill/P&L remain incomplete until sanitized broker JSON is ingested "
        "(order_id, legs, limit, status, filled_avg_price, client_order_id). "
        "Do not invent MATCHED."
    ),
    "live_mleg_submit": False,
    "live_broker_receipt": False,
    "live_fill": False,
    "live_pnl_snapshot": False,
}

_SECRET_KEY_PARTS = (
    "secret",
    "password",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "alpaca_api_key",
    "alpaca_secret",
)
_ACCOUNT_CREDENTIAL_KEYS = (
    "account_id",
    "account_number",
    "account",
    "alpaca_api_key",
    "alpaca_secret_key",
)


class AppendOnlyError(Exception):
    """The Evidence Ledger does not delete, truncate, or rewrite history."""


class LedgerError(Exception):
    """Invalid ledger operation."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_commit_sha(*, repo: Path | None = None) -> str:
    """Exact git commit SHA for code/build ID. Overridable via OPTICYCLE_BUILD_ID."""
    override = (os.environ.get("OPTICYCLE_BUILD_ID") or os.environ.get("GIT_COMMIT") or "").strip()
    if COMMIT_SHA_RE.fullmatch(override):
        return override
    root = repo or Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LedgerError("commit SHA is required for the Evidence Ledger") from exc
    if not COMMIT_SHA_RE.fullmatch(sha):
        raise LedgerError(f"invalid commit SHA {sha!r}")
    return sha


def canonical_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def _is_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in _ACCOUNT_CREDENTIAL_KEYS:
        return True
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def _redact_scalar(key: str, value: Any) -> Any:
    if isinstance(value, str) and value.startswith("redacted:"):
        return value
    if isinstance(value, str) and COMMIT_SHA_RE.fullmatch(value):
        return value
    digest = hashlib.sha256(f"{key}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"redacted:{digest}"


def sanitize(value: Any, *, key: str = "") -> Any:
    """Deterministic public sanitizer. No secrets, keys, or account credentials."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for child_key, child in value.items():
            name = str(child_key)
            if _is_secret_key(name):
                out[name] = _redact_scalar(name, child)
            else:
                out[name] = sanitize(child, key=name)
        return out
    if isinstance(value, list):
        return [sanitize(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item, key=key) for item in value]
    if key and _is_secret_key(key):
        return _redact_scalar(key, value)
    if isinstance(value, str):
        if "sk-" in value or "AKIA" in value:
            return _redact_scalar(key or "token", value)
        if re.search(r"(api[_-]?key|secret[_-]?key)\s*[=:]", value, re.I):
            return _redact_scalar(key or "blob", value)
    return value


def slot(value: Any = None, *, present: bool | None = None, reason: str | None = None) -> dict[str, Any]:
    if present is None:
        present = value is not None
    return {"present": bool(present), "value": value if present else None, "reason": reason}


def live_incomplete_slot(field: str) -> dict[str, Any]:
    return slot(
        None,
        present=False,
        reason=f"{LIVE_PAPER_INCOMPLETE['detail']} ({field})",
    )


def make_claim(*, record_id: str, commit_sha: str, outcome: str) -> str:
    if not COMMIT_SHA_RE.fullmatch(commit_sha):
        raise LedgerError("claim requires an exact 40-char commit SHA")
    if not record_id:
        raise LedgerError("claim requires a record id")
    return f"opticycle:v1:{outcome}:{record_id}:{commit_sha}"


def parse_claim(claim: str) -> dict[str, str]:
    parts = str(claim).split(":")
    if len(parts) != 5 or parts[0] != "opticycle" or parts[1] != "v1":
        raise LedgerError(f"unrecognized claim string: {claim!r}")
    outcome, record_id, commit_sha = parts[2], parts[3], parts[4]
    if not COMMIT_SHA_RE.fullmatch(commit_sha):
        raise LedgerError("claim commit SHA is not an exact 40-char hex digest")
    return {"outcome": outcome, "record_id": record_id, "commit_sha": commit_sha}


def complete_episode(fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(fields or {})
    episode: dict[str, Any] = {}
    for name in EPISODE_FIELDS:
        raw = payload.get(name)
        if isinstance(raw, Mapping) and "present" in raw:
            episode[name] = {
                "present": bool(raw["present"]),
                "value": raw.get("value"),
                "reason": raw.get("reason"),
            }
        else:
            episode[name] = slot(raw)
    missing = [name for name in EPISODE_FIELDS if name not in episode]
    if missing:
        raise LedgerError(f"episode incomplete: {missing}")
    return episode


def _apply_live_paper_block(
    episode: dict[str, Any],
    channel: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Block invented live MATCHED/P&L. A broker-terminal MATCHED complete is kept."""
    if channel != "live_paper":
        return episode
    extra = extra or {}
    verdict = str(extra.get("operational_verdict") or "").lower()
    if bool(extra.get("operational_complete")) and verdict in {"matched", "filled"}:
        return episode
    ingest = bool(extra.get("ingest_sanitized_broker_json"))
    blocked = dict(episode)
    keep = {"broker_receipt"} if ingest else set()
    for field in ("mcp_attempt", "broker_receipt", "reconciliation", "realized_pnl", "unrealized_pnl"):
        if field in keep:
            continue
        blocked[field] = live_incomplete_slot(field)
    recon = blocked.get("reconciliation") or {}
    value = recon.get("value") if isinstance(recon, Mapping) else recon
    status = ""
    if isinstance(value, Mapping):
        status = str(value.get("status") or "").lower()
    if status in {"matched", "fill", "filled"}:
        blocked["reconciliation"] = live_incomplete_slot("reconciliation")
    return blocked


class EvidenceLedger:
    """Append-only private raw ledger. Public export is a derived sanitization."""

    def __init__(self, path: Path | str = Path("data/ledger.raw.jsonl")) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self.path.is_file():
            raise LedgerError("ledger path must be a file")

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise AppendOnlyError("evidence ledger is append-only; no selective delete")

    def clear(self) -> None:
        raise AppendOnlyError("evidence ledger is append-only; profit/loss/veto/error/NO_TRADE/HALT are retained")

    def purge(self) -> None:
        raise AppendOnlyError("evidence ledger is append-only; no selective delete")

    def overwrite(self, *args: Any, **kwargs: Any) -> None:
        raise AppendOnlyError("evidence ledger is append-only; rewrite is forbidden")

    def truncate(self) -> None:
        raise AppendOnlyError("evidence ledger is append-only; truncate is forbidden")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                loaded = json.loads(text)
                if not isinstance(loaded, dict):
                    raise LedgerError("corrupt ledger: non-object row")
                records.append(loaded)
        return records

    def _last(self) -> dict[str, Any] | None:
        rows = self.read_all()
        return rows[-1] if rows else None

    def append_episode(
        self,
        *,
        channel: str,
        outcome: str,
        reason: str,
        commit_sha: str | None = None,
        cycle_id: str = "",
        client_order_id: str = "",
        fields: Mapping[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
        record_id: str | None = None,
        ts: str | None = None,
    ) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise LedgerError(f"channel must be one of {CHANNELS}")
        if outcome not in OUTCOMES:
            raise LedgerError(f"outcome must be one of {OUTCOMES}")
        sha = commit_sha or current_commit_sha()
        if not COMMIT_SHA_RE.fullmatch(sha):
            raise LedgerError("code/build ID must be an exact commit SHA")
        episode = _apply_live_paper_block(complete_episode(fields), channel, extra)
        if not episode["code_build_id"]["present"]:
            episode["code_build_id"] = slot(sha, present=True, reason="recorded build ID")
        elif episode["code_build_id"]["value"] != sha:
            raise LedgerError("episode code_build_id must equal the exact commit SHA")
        previous = self._last()
        seq = int(previous["seq"]) + 1 if previous else 1
        assigned_id = record_id or f"el-{uuid.uuid4().hex}"
        if not str(assigned_id).startswith("el-"):
            raise LedgerError("record_id must start with el-")
        claim = make_claim(record_id=assigned_id, commit_sha=sha, outcome=outcome)
        extra_dict = dict(extra or {})
        verdict = str(extra_dict.get("operational_verdict") or "").lower()
        matched_complete = bool(extra_dict.get("operational_complete")) and verdict in {
            "matched",
            "filled",
        }
        body = {
            "record_id": assigned_id,
            "seq": seq,
            "ledger_class": LEDGER_CLASS_PRIVATE,
            "channel": channel,
            "outcome": outcome,
            "reason": reason,
            "cycle_id": cycle_id,
            "client_order_id": client_order_id,
            "commit_sha": sha,
            "code_build_id": sha,
            "claim": claim,
            "ts": ts or _now(),
            "episode": episode,
            "live_paper_incomplete": (
                None
                if matched_complete
                else (dict(LIVE_PAPER_INCOMPLETE) if channel == "live_paper" else None)
            ),
            "extra": extra_dict,
        }
        prev_hash = str(previous["record_hash"]) if previous else GENESIS_HASH
        record_hash = sha256_json({"prev_hash": prev_hash, "body": body})
        record = {**body, "prev_hash": prev_hash, "record_hash": record_hash}
        line = canonical_dumps(record) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def export_public(self, dest: Path | str | None = None) -> list[dict[str, Any]]:
        """Reproducible sanitized export. Never writes fake live fills."""
        exported: list[dict[str, Any]] = []
        for row in self.read_all():
            public = sanitize(row)
            public["ledger_class"] = LEDGER_CLASS_PUBLIC
            public["derived_from"] = {
                "record_id": row["record_id"],
                "record_hash": row["record_hash"],
                "commit_sha": row["commit_sha"],
            }
            exported.append(public)
        if dest is not None:
            path = Path(dest)
            path.parent.mkdir(parents=True, exist_ok=True)
            blob = "".join(canonical_dumps(item) + "\n" for item in exported)
            path.write_text(blob, encoding="utf-8")
        return exported

    def resolve_claim(self, claim: str) -> dict[str, Any]:
        parsed = parse_claim(claim)
        for row in self.read_all():
            if row.get("record_id") == parsed["record_id"]:
                if row.get("commit_sha") != parsed["commit_sha"]:
                    raise LedgerError("claim commit SHA does not match ledger record")
                if row.get("outcome") != parsed["outcome"]:
                    raise LedgerError("claim outcome does not match ledger record")
                if row.get("claim") != claim:
                    raise LedgerError("claim string does not match stored claim")
                return row
        raise LedgerError(f"no ledger record for claim {claim}")

    def claims_index(self) -> dict[str, dict[str, str]]:
        index: dict[str, dict[str, str]] = {}
        for row in self.read_all():
            index[row["claim"]] = {
                "record_id": row["record_id"],
                "commit_sha": row["commit_sha"],
                "outcome": row["outcome"],
                "channel": row["channel"],
            }
        return index


class EpisodeBuilder:
    """Accumulate one Decision Episode, then append it. Live fills stay incomplete."""

    def __init__(
        self,
        ledger: EvidenceLedger,
        *,
        channel: str,
        commit_sha: str | None = None,
    ) -> None:
        self.ledger = ledger
        self.channel = channel
        self.commit_sha = commit_sha or current_commit_sha()
        self._fields: dict[str, Any] = {
            name: slot(None, present=False, reason="not observed in this episode")
            for name in EPISODE_FIELDS
        }
        self._fields["code_build_id"] = slot(self.commit_sha, present=True, reason="recorded build ID")
        self._fields["candidate_set"] = slot([], present=True, reason="empty set")
        self._fields["positions"] = slot([], present=True, reason="no positions observed")
        self._committed: dict[str, Any] | None = None

    def set(self, field: str, value: Any, *, reason: str | None = None) -> None:
        if field not in EPISODE_FIELDS:
            raise LedgerError(f"unknown episode field {field}")
        self._fields[field] = slot(value, present=True, reason=reason)

    def missing(self, field: str, reason: str) -> None:
        if field not in EPISODE_FIELDS:
            raise LedgerError(f"unknown episode field {field}")
        self._fields[field] = slot(None, present=False, reason=reason)

    def commit(
        self,
        *,
        outcome: str,
        reason: str,
        cycle_id: str = "",
        client_order_id: str = "",
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._committed is not None:
            return self._committed
        self._committed = self.ledger.append_episode(
            channel=self.channel,
            outcome=outcome,
            reason=reason,
            commit_sha=self.commit_sha,
            cycle_id=cycle_id,
            client_order_id=client_order_id,
            fields=self._fields,
            extra=extra,
        )
        return self._committed


def snapshot_from_observation(observation: Any) -> dict[str, Any]:
    datums = []
    for datum in getattr(observation, "datums", ()) or ():
        datums.append(
            {
                "kind": datum.kind,
                "source": datum.source,
                "timestamp": datum.timestamp.isoformat(),
                "freshness_seconds": str(datum.freshness_seconds),
                "correlation_id": datum.correlation_id,
                "ok": datum.ok,
                "detail": datum.detail,
            }
        )
    evidence = getattr(observation, "evidence", None)
    return {
        "outcome": getattr(getattr(observation, "outcome", None), "value", None),
        "reason": getattr(observation, "reason", ""),
        "correlation_id": getattr(observation, "correlation_id", ""),
        "datums": datums,
        "has_evidence": evidence is not None,
        "spot_price": str(getattr(evidence, "spot_price", "")) if evidence is not None else None,
        "quote_age_seconds": str(getattr(evidence, "quote_age_seconds", "")) if evidence is not None else None,
    }


def public_contains_secrets(public: Any) -> list[str]:
    hits: list[str] = []
    blob = canonical_dumps(public)
    for token in ("sk-live", "BEGIN PRIVATE", "super-secret-value"):
        if token in blob:
            hits.append(token)
    if "ALPACA_API_KEY=" in blob or "ALPACA_SECRET_KEY=" in blob:
        hits.append("credential assignment")
    return hits
