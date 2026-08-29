"""Public judge evidence: sanitized page, claim manifest, keyless replay.

Reads sanitized ledger exports only. Never claims a live MLEG fill, broker
receipt, or P&L snapshot. The committed NO_TRADE record is live-path plus an
injected missing quote — not an Alpaca true quote-miss and not fill evidence.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from opticycle.ledger import (
    COMMIT_SHA_RE,
    EPISODE_FIELDS,
    LIVE_PAPER_INCOMPLETE,
    canonical_dumps,
    parse_claim,
    public_contains_secrets,
    sanitize,
)

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "artifacts" / "evidence"
PUBLIC_JSONL = EVIDENCE_DIR / "public.jsonl"
NO_TRADE_JSONL = EVIDENCE_DIR / "no_trade.public.jsonl"
MANIFEST_PATH = EVIDENCE_DIR / "manifest.json"
PAGE_PATH = EVIDENCE_DIR / "index.html"
GATE11_STATUS_PATH = EVIDENCE_DIR / "gate11_status.json"
PAPER_FILL_INGEST_PATH = EVIDENCE_DIR / "paper_fill_ingest.json"

NO_TRADE_CAVEAT = (
    "live-path + injected missing quote; NOT an Alpaca true quote-miss; "
    "NOT fill evidence; NOT a live MATCHED / MLEG / fill claim"
)

DEMO_VIDEO_STATUS = "deleted; Remotion demo is Gate 12"

INCOMPLETE_LIVE_CLAIMS = {
    "live_mleg_submit": LIVE_PAPER_INCOMPLETE["detail"],
    "live_broker_receipt": LIVE_PAPER_INCOMPLETE["detail"],
    "live_fill": LIVE_PAPER_INCOMPLETE["detail"],
    "live_pnl_snapshot": LIVE_PAPER_INCOMPLETE["detail"],
}

FORBIDDEN_PUBLIC_TOKENS = (
    "PA3V84C40PJQ",
    "ALPACA_API_KEY=",
    "ALPACA_SECRET_KEY=",
    "sk-live",
    "BEGIN PRIVATE",
    "GaussWorldTrader",
    "Gauss World Trader",
    "gauss-world-trader",
    "GaussOptions",
    "Magica-Chen",
    "Magica Chen",
    "github.com/Magica",
)

UPSTREAM_NAME_TOKENS = (
    "GaussWorldTrader",
    "Gauss World Trader",
    "gauss-world-trader",
    "GaussOptions",
    "gaussoptions",
    "Magica-Chen",
    "github.com/Magica",
)

ACCOUNT_ID_RE = re.compile(r"\bPA[A-Z0-9]{8,}\b")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError(f"non-object row in {path}")
        rows.append(loaded)
    return rows


def load_gate11_status() -> dict[str, Any]:
    default = {
        "live_fill_claimed": False,
        "live_quotes_available": False,
        "genuine_no_trade_recorded": False,
        "injected_no_trade_promoted": False,
        "demo_mp4": DEMO_VIDEO_STATUS,
        "live_quote_gap": "live Alpaca quotes were not available without keys",
        "pnl_reconcile": "fixture-tested; not stamped as live",
        "yun_authorized_one_paper_mleg": True,
        "sanitized_json_provided": False,
    }
    if not GATE11_STATUS_PATH.is_file():
        return default
    loaded = json.loads(GATE11_STATUS_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return default
    merged = dict(default)
    merged.update(loaded)
    merged["live_fill_claimed"] = False
    merged["injected_no_trade_promoted"] = False
    return merged


def load_public_records() -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in (NO_TRADE_JSONL, PUBLIC_JSONL):
        for row in load_jsonl(path):
            record_id = str(row.get("record_id") or "")
            if record_id and record_id in seen:
                continue
            if record_id:
                seen.add(record_id)
            combined.append(row)
    return combined


def slot_value(record: Mapping[str, Any], field: str) -> Any:
    episode = record.get("episode") or {}
    slot = episode.get(field) or {}
    if isinstance(slot, Mapping) and slot.get("present"):
        return slot.get("value")
    return None


def payload_hash_of(record: Mapping[str, Any]) -> str | None:
    candidate = slot_value(record, "candidate_set")
    if isinstance(candidate, Mapping):
        digest = candidate.get("payload_hash")
        if digest:
            return str(digest)
    certificate = slot_value(record, "certificate")
    if isinstance(certificate, Mapping) and certificate.get("payload_hash"):
        return str(certificate["payload_hash"])
    return None


def is_injected_no_trade(record: Mapping[str, Any]) -> bool:
    """Gate 9 leftover: live-path + injected missing quote, not an Alpaca true miss."""
    if record.get("outcome") != "NO_TRADE":
        return False
    extra = record.get("extra") or {}
    if extra.get("injected_missing_quote") is True:
        return True
    if record.get("record_id") == "el-6b67a01c2bdd448388e813633f90e890":
        return True
    reason = str(record.get("reason") or "")
    return "SPY quote missing" in reason


def claim_caveat(record: Mapping[str, Any]) -> str | None:
    if is_injected_no_trade(record) and record.get("channel") == "live_paper":
        return NO_TRADE_CAVEAT
    return None


def build_manifest(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    claims: dict[str, dict[str, Any]] = {}
    for row in records:
        claim = str(row.get("claim") or "")
        if not claim:
            continue
        parsed = parse_claim(claim)
        if parsed["record_id"] != row.get("record_id"):
            raise ValueError("claim record_id does not match ledger record")
        if parsed["commit_sha"] != row.get("commit_sha"):
            raise ValueError("claim commit SHA does not match ledger record")
        if not COMMIT_SHA_RE.fullmatch(str(row.get("commit_sha") or "")):
            raise ValueError("commit SHA must be an exact 40-char hex digest")
        claims[claim] = {
            "record_id": parsed["record_id"],
            "commit_sha": parsed["commit_sha"],
            "outcome": parsed["outcome"],
            "channel": row.get("channel"),
            "live_fill": False,
            "live_mleg_submit": False,
            "incomplete": list(INCOMPLETE_LIVE_CLAIMS.keys())
            if row.get("channel") == "live_paper"
            else [],
            "caveat": claim_caveat(row),
        }
    return {
        "schema": "opticycle.claim-evidence.v1",
        "source": "sanitized_public_ledger",
        "live_fill_claimed": False,
        "injected_no_trade_promoted": False,
        "matched_claimed": False,
        "incomplete_live": dict(INCOMPLETE_LIVE_CLAIMS),
        "no_trade_injected_quote_caveat": NO_TRADE_CAVEAT,
        "claims": claims,
    }


def scan_public_text(text: str, *, source: str) -> list[str]:
    hits: list[str] = []
    lowered = text.lower()
    for token in FORBIDDEN_PUBLIC_TOKENS:
        if token.lower() in lowered:
            hits.append(f"{source}: {token}")
    if ACCOUNT_ID_RE.search(text):
        hits.append(f"{source}: alpaca paper account id")
    if "ALPACA_API_KEY=" in text or "ALPACA_SECRET_KEY=" in text:
        hits.append(f"{source}: credential assignment")
    return hits


def scan_public_blob(value: Any, *, source: str) -> list[str]:
    blob = value if isinstance(value, str) else canonical_dumps(value)
    hits = scan_public_text(blob, source=source)
    hits.extend(f"{source}: {item}" for item in public_contains_secrets(value if not isinstance(value, str) else {"blob": value}))
    return hits


def replay_sanitized_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keyless replay of non-live claims from sanitized records only."""
    verified: list[dict[str, Any]] = []
    for row in records:
        if row.get("ledger_class") not in {"public_sanitized", None}:
            if row.get("ledger_class") == "private_raw":
                raise ValueError("keyless replay refuses private raw ledger rows")
        claim = str(row["claim"])
        parsed = parse_claim(claim)
        if parsed["record_id"] != row["record_id"] or parsed["commit_sha"] != row["commit_sha"]:
            raise ValueError(f"claim does not map to record {row.get('record_id')}")
        episode = row.get("episode") or {}
        for field in EPISODE_FIELDS:
            if field not in episode:
                raise ValueError(f"episode missing {field}")
        recon = slot_value(row, "reconciliation")
        status = ""
        if isinstance(recon, Mapping):
            status = str(recon.get("status") or "").lower()
        if row.get("channel") == "live_paper" and status in {"matched", "filled", "fill"}:
            raise ValueError("live_paper MATCHED/fill is not a verifiable public claim")
        if is_injected_no_trade(row):
            if status in {"matched", "filled", "fill"}:
                raise ValueError("injected NO_TRADE must not be used as fill evidence")
        verified.append(
            {
                "claim": claim,
                "record_id": parsed["record_id"],
                "commit_sha": parsed["commit_sha"],
                "outcome": parsed["outcome"],
                "channel": row.get("channel"),
                "payload_hash": payload_hash_of(row),
                "live_fill": False,
                "caveat": claim_caveat(row),
            }
        )
    return verified


def _present_label(record: Mapping[str, Any], field: str) -> str:
    episode = record.get("episode") or {}
    slot = episode.get(field) or {}
    if isinstance(slot, Mapping) and slot.get("present"):
        return "present"
    reason = ""
    if isinstance(slot, Mapping):
        reason = str(slot.get("reason") or "")
    return f"not present{(' — ' + reason) if reason else ''}"


def _pre(value: Any) -> str:
    if value is None:
        return "<p class='empty'>not present</p>"
    dumped = json.dumps(value, indent=2, sort_keys=True, default=str)
    return f"<pre>{html.escape(dumped)}</pre>"


def render_evidence_page(
    records: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    *,
    status: Mapping[str, Any] | None = None,
) -> str:
    claim_rows: list[str] = []
    for claim, mapped in (manifest.get("claims") or {}).items():
        claim_status = "incomplete live slots" if mapped.get("incomplete") else "non-live / keyless replay"
        if mapped.get("caveat"):
            claim_status = "injected-quote NO_TRADE — not fill evidence"
        claim_rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(claim))}</code></td>"
            f"<td><code>{html.escape(str(mapped.get('record_id', '')))}</code></td>"
            f"<td><code>{html.escape(str(mapped.get('commit_sha', '')))}</code></td>"
            f"<td>{html.escape(claim_status)}</td>"
            "</tr>"
        )
    cards: list[str] = []
    for row in records:
        caveat = claim_caveat(row)
        caveat_html = f"<p class='caveat'>{html.escape(caveat)}</p>" if caveat else ""
        payload_hash = payload_hash_of(row) or "not present"
        failure = str(row.get("outcome")) in {"HALT", "ERROR", "VETO"}
        failure_label = (
            "yes — " + str(row.get("outcome"))
            if failure
            else "no — outcome " + str(row.get("outcome"))
        )
        cards.append(
            f"""
<article class="episode" id="{html.escape(str(row.get('record_id', '')))}">
  <h2>{html.escape(str(row.get('outcome', '')))} · {html.escape(str(row.get('channel', '')))}</h2>
  {caveat_html}
  <dl>
    <dt>record id</dt><dd><code>{html.escape(str(row.get('record_id', '')))}</code></dd>
    <dt>claim</dt><dd><code>{html.escape(str(row.get('claim', '')))}</code></dd>
    <dt>commit / build ID</dt><dd><code>{html.escape(str(row.get('commit_sha') or row.get('code_build_id') or ''))}</code></dd>
    <dt>authorized payload hash</dt><dd><code>{html.escape(str(payload_hash))}</code></dd>
  </dl>
  <h3>thesis</h3>{_pre(slot_value(row, 'thesis'))}
  <p class="slot">NO_TRADE / veto: <strong>{html.escape(str(row.get('outcome', '')))}</strong> — {html.escape(str(row.get('reason', '')))}</p>
  <h3>real candidate (if present)</h3>
  <p class="slot">{html.escape(_present_label(row, 'candidate_set'))}</p>
  {_pre(slot_value(row, 'candidate_set'))}
  <h3>Risk Certificate</h3>
  <p class="slot">{html.escape(_present_label(row, 'certificate'))}</p>
  {_pre(slot_value(row, 'certificate'))}
  <h3>MCP call (if present)</h3>
  <p class="slot">{html.escape(_present_label(row, 'mcp_attempt'))}</p>
  {_pre(slot_value(row, 'mcp_attempt'))}
  <h3>broker receipt (if present)</h3>
  <p class="slot">{html.escape(_present_label(row, 'broker_receipt'))}</p>
  {_pre(slot_value(row, 'broker_receipt'))}
  <h3>reconciliation (if present)</h3>
  <p class="slot">{html.escape(_present_label(row, 'reconciliation'))}</p>
  {_pre(slot_value(row, 'reconciliation'))}
  <h3>P&amp;L / equity (if present)</h3>
  <p class="slot">realized {_present_label(row, 'realized_pnl')}; unrealized {_present_label(row, 'unrealized_pnl')}; equity {_present_label(row, 'end_of_cycle_equity')}</p>
  {_pre({
                "realized_pnl": slot_value(row, "realized_pnl"),
                "unrealized_pnl": slot_value(row, "unrealized_pnl"),
                "end_of_cycle_equity": slot_value(row, "end_of_cycle_equity"),
            })}
  <h3>failure episode</h3>
  <p class="slot">{html.escape(failure_label)}</p>
  {_pre({"reason": row.get("reason"), "snapshot": slot_value(row, "snapshot")} if failure else None)}
</article>
"""
        )
    incomplete = "".join(
        f"<li><strong>{html.escape(name)}</strong>: {html.escape(detail)}</li>"
        for name, detail in INCOMPLETE_LIVE_CLAIMS.items()
    )
    gate11 = dict(status or load_gate11_status())
    quote_gap = html.escape(str(gate11.get("live_quote_gap") or ""))
    genuine = "yes" if gate11.get("genuine_no_trade_recorded") else "no — gap recorded honestly"
    ingest_note = (
        "Yun authorized one paper MLEG. Cloud VM cannot submit. "
        "Waiting for sanitized broker JSON (order_id, legs, limit, status, filled_avg_price, client_order_id). "
        "MATCHED is not claimed."
    )
    embedded = html.escape(canonical_dumps({"records": records, "manifest": manifest, "gate11": gate11}))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Opticycle public evidence</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; max-width: 960px; color: #111; }}
    h1 {{ font-size: 1.6rem; }}
    .banner, .caveat {{ background: #fff3cd; border: 1px solid #e6c200; padding: 0.75rem 1rem; }}
    article.episode {{ border: 1px solid #ddd; padding: 1rem; margin: 1.25rem 0; }}
    dt {{ font-weight: 600; margin-top: 0.4rem; }}
    pre {{ background: #f6f8fa; padding: 0.75rem; overflow: auto; }}
    code {{ font-size: 0.9em; word-break: break-all; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.85rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }}
    .empty {{ color: #666; }}
  </style>
</head>
<body>
  <h1>Opticycle public evidence</h1>
  <p>Rendered from sanitized ledger records only. No secrets, keys, or account credentials.</p>
  <div class="banner">
    <p><strong>Live MLEG / fill / broker receipt / P&amp;L are incomplete.</strong> Do not treat any card as a live MATCHED fill. Yun has not confirmed the exact paper order.</p>
    <p>{html.escape(NO_TRADE_CAVEAT)}</p>
    <p>Genuine live NO_TRADE this gate: {html.escape(genuine)}. {quote_gap}</p>
    <p>{html.escape(ingest_note)}</p>
    <p>No demo video is committed in this packet. Remotion demo is Gate 12.</p>
    <ul>{incomplete}</ul>
  </div>
  <h2>Claim → record → commit</h2>
  <table>
    <thead><tr><th>claim</th><th>record id</th><th>commit (40-char)</th><th>status</th></tr></thead>
    <tbody>{''.join(claim_rows)}</tbody>
  </table>
  {''.join(cards)}
  <script type="application/json" id="sanitized-ledger">{embedded}</script>
</body>
</html>
"""


def write_evidence_artifacts(records: list[dict[str, Any]], *, dest_dir: Path | None = None) -> dict[str, Path]:
    dest = dest_dir or EVIDENCE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    public_path = dest / "public.jsonl"
    manifest_path = dest / "manifest.json"
    page_path = dest / "index.html"
    sanitized = [sanitize(row) for row in records]
    for row in sanitized:
        row["ledger_class"] = "public_sanitized"
    public_path.write_text("".join(canonical_dumps(row) + "\n" for row in sanitized), encoding="utf-8")
    manifest = build_manifest(sanitized)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    page_path.write_text(render_evidence_page(sanitized, manifest), encoding="utf-8")
    return {"public": public_path, "manifest": manifest_path, "page": page_path}
