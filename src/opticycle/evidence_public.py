"""Public evidence page: sanitized records, claim manifest, keyless replay.

Reads sanitized ledger exports only. Three authorized live_paper broker fills
are recorded: the first two remain FILLED because their credit limit sign was
wrong, while the signed-credit third fill is price-bound MATCHED. Replay
MATCHED stays channel=replay (not live_paper). The committed injected-quote
NO_TRADE is not fill evidence.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from opticycle.broker_lookup import SIGNED_CLIENT_ORDER_ID
from opticycle.ledger import (
    COMMIT_SHA_RE,
    EPISODE_FIELDS,
    canonical_dumps,
    parse_claim,
    public_contains_secrets,
    sanitize,
)
from opticycle.live_matched_fills import (
    LIVE_MATCHED_CLIENT_IDS,
    is_authorized_live_matched,
)
from opticycle.signed_credit_fill import (
    is_price_bound_matched_fill,
)

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "artifacts" / "evidence"
PUBLIC_JSONL = EVIDENCE_DIR / "public.jsonl"
NO_TRADE_JSONL = EVIDENCE_DIR / "no_trade.public.jsonl"
GENUINE_NO_TRADE_JSONL = EVIDENCE_DIR / "genuine_no_trade.public.jsonl"
BROKER_LOOKUP_PATH = EVIDENCE_DIR / "broker_lookup.json"
MANIFEST_PATH = EVIDENCE_DIR / "manifest.json"
PAGE_PATH = EVIDENCE_DIR / "index.html"
GATE11_STATUS_PATH = EVIDENCE_DIR / "gate11_status.json"
PAPER_FILL_INGEST_PATH = EVIDENCE_DIR / "paper_fill_ingest.json"
WALK_FORWARD_JSON_PATH = EVIDENCE_DIR / "walk-forward-backtest.json"

NO_TRADE_CAVEAT = (
    "live-path + injected missing quote; NOT an Alpaca true quote-miss; "
    "NOT fill evidence; NOT a live MATCHED / MLEG / fill claim"
)

INJECTED_NO_TRADE_SLOT_ABSENT = (
    "absent on this injected-quote NO_TRADE episode (not fill evidence)"
)

GENUINE_STALE_QUOTE_CAVEAT = (
    "live Alpaca observation; SPY quote stale after the regular session; "
    "genuine NO_TRADE; ThesisAgent not called (freshness fail-closed); not fill evidence"
)

DEMO_VIDEO_STATUS = "rendered at artifacts/demo.mp4"

FORBIDDEN_PUBLIC_TOKENS = (
    "ALPACA_API_KEY=",
    "ALPACA_SECRET_KEY=",
    "sk-live",
    "sk-proj",
    "BEGIN PRIVATE",
)

DESIGNATED_ACCOUNT_ID = "PA3V84C40PJQ"

PUBLIC_MODEL_RE = re.compile(r"\bgpt-[A-Za-z0-9._-]+\b", re.IGNORECASE)

RELEASE_ARTIFACTS = (
    "artifacts/demo.mp4",
    "artifacts/demo-poster.png",
    "artifacts/opticycle-one-page.pdf",
    "artifacts/opticycle-slides.pdf",
    "artifacts/opticycle-slides.pptx",
    "artifacts/readme-hero.svg",
    "artifacts/team-cover.png",
    "artifacts/evidence/alpaca_cli_snapshot.json",
    "artifacts/evidence/broker_lookup.json",
    "artifacts/evidence/claims.json",
    "artifacts/evidence/equity-curve.png",
    "artifacts/evidence/equity-vs-spy.json",
    "artifacts/evidence/equity-vs-spy.png",
    "artifacts/evidence/gate11_status.json",
    "artifacts/evidence/genuine_no_trade.public.jsonl",
    "artifacts/evidence/no_trade.public.jsonl",
    "artifacts/evidence/paper_fill_ingest.json",
    "artifacts/evidence/portfolio_history.json",
    "artifacts/evidence/public.jsonl",
    "artifacts/evidence/sanitized_fills/oc-204a8dfccffd40c9.json",
    "artifacts/evidence/sanitized_fills/oc-63db2a85298b4ecabefab59076a6397e.json",
    "artifacts/evidence/sanitized_fills/oc-715ad36a630d408e.json",
    "artifacts/evidence/walk-forward-backtest.html",
    "artifacts/evidence/walk-forward-backtest.json",
    "artifacts/evidence/walk-forward-backtest.png",
    "artifacts/evidence/walk-forward-iex-bars.json",
)


def redact_public_model_metadata(value: Any) -> Any:
    """Keep public evidence model-agnostic while preserving whether a model was called."""
    if isinstance(value, Mapping):
        return {
            key: (
                "configurable"
                if str(key).lower() == "model"
                else redact_public_model_metadata(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_public_model_metadata(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_public_model_metadata(item) for item in value)
    if isinstance(value, str):
        return PUBLIC_MODEL_RE.sub("configured model", value)
    return value


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
        "sanitized_json_provided": False,
    }
    if not GATE11_STATUS_PATH.is_file():
        return default
    loaded = json.loads(GATE11_STATUS_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return default
    merged = dict(default)
    merged.update(loaded)
    merged["injected_no_trade_promoted"] = False
    merged["live_fill_claimed"] = bool(merged.get("live_fill_claimed"))
    return redact_public_model_metadata(merged)


def load_public_records() -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in (NO_TRADE_JSONL, GENUINE_NO_TRADE_JSONL, PUBLIC_JSONL):
        for row in load_jsonl(path):
            record_id = str(row.get("record_id") or "")
            if record_id and record_id in seen:
                continue
            if record_id:
                seen.add(record_id)
            combined.append(row)
    return combined


def modeled_walk_forward_section() -> str:
    """Render the modeled research result when available."""
    if not WALK_FORWARD_JSON_PATH.is_file():
        return ""
    loaded = json.loads(WALK_FORWARD_JSON_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        return ""
    metrics = loaded.get("metrics") or {}
    date_range = loaded.get("date_range") or {}
    return f"""
  <details class="research">
    <summary><span>Modeled research</span><strong>{float(metrics.get('total_return_pct') or 0):+.2f}% modeled · not broker P&amp;L</strong></summary>
    <div class="research-body">
      <div>
        <div class="eyebrow">ALPACA IEX DAILY / BLACK-SCHOLES</div>
        <h3>{int(metrics.get('trades') or 0)} sequential trades · {float(metrics.get('max_drawdown_pct') or 0):.2f}% max drawdown</h3>
        <p class="muted">Rolling-origin research using prior observations only, the live exit rules, and a disclosed 1.20× IV/RV assumption. Range {html.escape(str(date_range.get('start') or ''))} to {html.escape(str(date_range.get('end') or ''))}.</p>
        <a class="text-link" href="walk-forward-backtest.html">Method and limitations ↗</a>
      </div>
      <img src="walk-forward-backtest.png" alt="Modeled SPY vertical walk-forward compared with SPY close benchmark"/>
    </div>
  </details>
"""


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
    """Identify the historical injected-quote probe; it is never live fill evidence."""
    if record.get("outcome") != "NO_TRADE":
        return False
    extra = record.get("extra") or {}
    if extra.get("injected_missing_quote") is True:
        return True
    if record.get("record_id") == "el-6b67a01c2bdd448388e813633f90e890":
        return True
    reason = str(record.get("reason") or "")
    return "SPY quote missing" in reason


def is_genuine_no_trade(record: Mapping[str, Any]) -> bool:
    extra = record.get("extra") or {}
    if extra.get("genuine_no_trade") is True:
        return True
    reason = str(record.get("reason") or "")
    return (
        record.get("outcome") == "NO_TRADE"
        and record.get("channel") == "live_paper"
        and "SPY quote is stale" in reason
        and extra.get("injected_missing_quote") is not True
    )


REPLAY_MATCHED_CAVEAT = None

LIVE_MATCHED_NOTE = (
    "live_paper broker fill; submitted credit limit had debit sign; "
    "not price-bound MATCHED; account id omitted"
)

SIGNED_MATCHED_NOTE = (
    "live_paper price-bound MATCHED; Alpaca-negative credit limit; "
    "filled <= submitted; ThesisAgent model_called=true; account id omitted"
)


def is_live_matched_fill(record: Mapping[str, Any]) -> bool:
    return is_authorized_live_matched(record)


def is_live_fill_row(record: Mapping[str, Any]) -> bool:
    return is_live_matched_fill(record) or is_price_bound_matched_fill(record)


def claim_caveat(record: Mapping[str, Any]) -> str | None:
    if is_injected_no_trade(record) and record.get("channel") == "live_paper":
        return NO_TRADE_CAVEAT
    if is_genuine_no_trade(record):
        return GENUINE_STALE_QUOTE_CAVEAT
    if record.get("channel") == "replay" and str(record.get("outcome") or "") == "MATCHED":
        return REPLAY_MATCHED_CAVEAT
    if is_price_bound_matched_fill(record):
        return SIGNED_MATCHED_NOTE
    if is_live_matched_fill(record):
        extra = record.get("extra") or {}
        if extra.get("stance_source") == "bars_heuristic_no_llm_key":
            return LIVE_MATCHED_NOTE + "; stance_source=bars_heuristic_no_llm_key (no LLM key)"
        return LIVE_MATCHED_NOTE
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
        live_fill = is_live_fill_row(row)
        claims[claim] = {
            "record_id": parsed["record_id"],
            "commit_sha": parsed["commit_sha"],
            "outcome": parsed["outcome"],
            "channel": row.get("channel"),
            "live_fill": live_fill,
            "live_mleg_submit": live_fill,
            "incomplete": [],
            "caveat": claim_caveat(row),
        }
    any_live = any(item["live_fill"] for item in claims.values())
    artifact_hashes = {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in RELEASE_ARTIFACTS
        if (ROOT / relative).is_file()
    }
    deployed_commit = os.environ.get("GITHUB_SHA") or None
    return {
        "schema": "opticycle.claim-evidence.v1",
        "source": "sanitized_public_ledger",
        "release": {
            "branch": "main",
            "deployed_commit": deployed_commit,
            "stamp_source": "GITHUB_SHA during GitHub Pages publish",
            "historical_build_ids": (
                "pre-release provenance retained after the release squash; "
                "not checkout targets in the one-commit release repository"
            ),
        },
        "artifact_sha256": artifact_hashes,
        "live_fill_claimed": any_live,
        "injected_no_trade_promoted": False,
        "matched_claimed": any(is_price_bound_matched_fill(row) for row in records),
        "incomplete_live": {},
        "no_trade_injected_quote_caveat": NO_TRADE_CAVEAT,
        "authorized_live_client_order_ids": sorted(set(LIVE_MATCHED_CLIENT_IDS) | {SIGNED_CLIENT_ORDER_ID}),
        "claims": claims,
    }


def scan_public_text(text: str, *, source: str) -> list[str]:
    hits: list[str] = []
    lowered = text.lower()
    for token in FORBIDDEN_PUBLIC_TOKENS:
        if token.lower() in lowered:
            hits.append(f"{source}: {token}")
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
            if not is_live_fill_row(row):
                raise ValueError("live_paper MATCHED/fill is not a verifiable public claim")
        if is_injected_no_trade(row):
            if status in {"matched", "filled", "fill"}:
                raise ValueError("injected NO_TRADE must not be used as fill evidence")
        live_fill = is_live_fill_row(row)
        verified.append(
            {
                "claim": claim,
                "record_id": parsed["record_id"],
                "commit_sha": parsed["commit_sha"],
                "outcome": parsed["outcome"],
                "channel": row.get("channel"),
                "payload_hash": payload_hash_of(row),
                "live_fill": live_fill,
                "caveat": claim_caveat(row),
            }
        )
    return verified


def _present_label(record: Mapping[str, Any], field: str) -> str:
    episode = record.get("episode") or {}
    slot = episode.get(field) or {}
    if isinstance(slot, Mapping) and slot.get("present"):
        return "present"
    if is_injected_no_trade(record):
        return f"not present — {INJECTED_NO_TRADE_SLOT_ABSENT}"
    reason = ""
    if isinstance(slot, Mapping):
        reason = str(slot.get("reason") or "")
    return f"not present{(' — ' + reason) if reason else ''}"


def _page_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy records for the page and label pre-release provenance accurately."""
    out: list[dict[str, Any]] = []
    for row in records:
        copied = json.loads(json.dumps(row))
        episode = copied.get("episode") or {}
        build_slot = episode.get("code_build_id") or {}
        if isinstance(build_slot, dict) and build_slot.get("present"):
            build_slot["reason"] = (
                "historical pre-release build ID retained after the release squash"
            )
            episode["code_build_id"] = build_slot
        copied["episode"] = episode
        if is_injected_no_trade(row):
            copied.pop("live_paper_incomplete", None)
            extra = dict(copied.get("extra") or {})
            extra.pop("live_paper_incomplete", None)
            copied["extra"] = extra
            for field, slot in list(episode.items()):
                if not isinstance(slot, dict) or slot.get("present"):
                    continue
                slot["reason"] = INJECTED_NO_TRADE_SLOT_ABSENT
                episode[field] = slot
            copied["episode"] = episode
            out.append(copied)
            continue
        if is_genuine_no_trade(row):
            copied.pop("live_paper_incomplete", None)
            extra = dict(copied.get("extra") or {})
            extra.pop("live_paper_incomplete", None)
            copied["extra"] = extra
            for field, slot in list(episode.items()):
                if not isinstance(slot, dict) or slot.get("present"):
                    continue
                slot["reason"] = (
                    "absent on this genuine stale-quote NO_TRADE episode (not fill evidence)"
                )
                episode[field] = slot
            copied["episode"] = episode
            out.append(copied)
            continue
        out.append(copied)
    return out


def _pre(value: Any) -> str:
    if value is None:
        return "<p class='empty'>not present</p>"
    dumped = json.dumps(value, indent=2, sort_keys=True, default=str)
    return f"<pre>{html.escape(dumped)}</pre>"


def _golden_trace(records: Iterable[Mapping[str, Any]]) -> str:
    golden = next(
        (row for row in records if str(row.get("client_order_id") or "") == SIGNED_CLIENT_ORDER_ID),
        None,
    )
    if golden is None or not is_price_bound_matched_fill(golden):
        raise ValueError("missing price-bound golden trace")
    snapshot = slot_value(golden, "snapshot") or {}
    thesis = slot_value(golden, "thesis") or {}
    candidate = slot_value(golden, "candidate_set") or {}
    certificate = slot_value(golden, "certificate") or {}
    mcp = slot_value(golden, "mcp_attempt") or {}
    receipt = slot_value(golden, "broker_receipt") or {}
    steps = [
        (
            "SNAPSHOT",
            f"Fresh {snapshot.get('underlying', 'SPY')} state",
        ),
        (
            "LLM STANCE",
            f"{thesis.get('stance')} · model_called=true",
        ),
        (
            "PAYLOAD",
            f"2 legs · qty {candidate.get('qty')}",
        ),
        (
            "CERT",
            f"SHA-256 {str(certificate.get('payload_hash') or '')[:8]}…",
        ),
        (
            "MCP",
            f"Official server · submit {mcp.get('mcp_submit_count')}",
        ),
        (
            "GET",
            f"Same ID · fill {receipt.get('filled_avg_price')}",
        ),
        (
            "MATCHED",
            "Limit = fill · no retry",
        ),
    ]
    return "<div class='trace'>" + "".join(
        (
            "<div class='trace-step'>"
            f"<strong>{html.escape(title)}</strong>"
            f"<span>{html.escape(detail)}</span>"
            "</div>"
            + ("<div class='arrow'>→</div>" if index < len(steps) - 1 else "")
        )
        for index, (title, detail) in enumerate(steps)
    ) + "</div>"


def render_evidence_page(
    records: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    *,
    status: Mapping[str, Any] | None = None,
) -> str:
    claim_rows: list[str] = []
    for claim, mapped in (manifest.get("claims") or {}).items():
        claim_status = "incomplete live slots" if mapped.get("incomplete") else "non-live / keyless replay"
        if mapped.get("caveat") == NO_TRADE_CAVEAT:
            claim_status = "injected-quote NO_TRADE — not fill evidence"
        elif mapped.get("live_fill"):
            if mapped.get("outcome") == "MATCHED":
                claim_status = "live_paper price-bound MATCHED"
            else:
                claim_status = "live_paper broker fill — not price-bound MATCHED"
        elif mapped.get("caveat") == GENUINE_STALE_QUOTE_CAVEAT:
            claim_status = "genuine live NO_TRADE — stale quote; not fill evidence"
        elif mapped.get("channel") == "replay" and mapped.get("outcome") == "MATCHED":
            claim_status = "replay MATCHED"
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
    <dt>historical build ID</dt><dd><code>{html.escape(str(row.get('commit_sha') or row.get('code_build_id') or ''))}</code></dd>
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
    gate11 = dict(status or load_gate11_status())
    page_records = _page_records(records)
    golden_trace = _golden_trace(page_records)
    run_timeline = (
        ("AUG 28", "TEST ONLY", "Injected missing-quote NO_TRADE; explicitly not live evidence."),
        ("AUG 29", "NOT RUN", "No recorded autonomous paper episode."),
        ("AUG 30", "NOT RUN", "No recorded autonomous paper episode."),
        ("AUG 31", "RAN", "Two paper fills plus a genuine stale-quote NO_TRADE."),
        ("SEP 01", "RAN", "Two MCP closes; one signed-credit, price-bound MATCHED fill."),
        ("SEP 02", "NOT RUN", "No recorded autonomous paper episode."),
        ("SEP 03", "RAN", "Broker truth refreshed; closed-session safety paths made zero submits."),
        ("SEP 04", "NO EPISODE", "No Sep 4 episode is claimed in this release."),
    )
    timeline_html = "".join(
        "<div class='timeline-day'>"
        f"<small>{html.escape(day)}</small>"
        f"<strong>{html.escape(state)}</strong>"
        f"<span>{html.escape(detail)}</span>"
        "</div>"
        for day, state, detail in run_timeline
    )
    walk_forward = modeled_walk_forward_section()
    embedded = html.escape(canonical_dumps({"records": page_records, "manifest": manifest, "gate11": gate11}))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="description" content="Opticycle public paper-trading evidence: one certified MLEG, one broker readback, zero resubmits."/>
  <title>Opticycle · Public evidence</title>
  <style>
    :root {{ color-scheme: light; --bg: #fafaf7; --panel: #ffffff; --soft: #f1f2ed; --line: #dedfd8; --ink: #151815; --muted: #646a64; --accent: #167448; --accent-soft: #e5f4eb; --dark: #141816; --dark-line: #303631; --amber: #946c24; --amber-soft: #f7efd9; --red: #a14343; --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; overflow-x: hidden; color: var(--ink); background: var(--bg); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; -webkit-font-smoothing: antialiased; }}
    a {{ color: inherit; text-underline-offset: .18em; }}
    a:focus-visible, summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 4px; }}
    code, pre {{ font-family: var(--mono); }}
    .site-header, main, footer {{ width: min(1232px, calc(100% - 48px)); margin-inline: auto; }}
    .site-header {{ position: sticky; top: 0; z-index: 20; height: 68px; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; border-bottom: 1px solid rgba(21,24,21,.12); background: rgba(250,250,247,.91); backdrop-filter: blur(16px); }}
    .brand {{ font-size: .78rem; font-weight: 750; letter-spacing: .18em; text-decoration: none; }}
    .nav {{ display: flex; gap: 1.5rem; font-size: .82rem; color: var(--muted); }}
    .nav a, .header-action {{ text-decoration: none; }}
    .header-action {{ justify-self: end; font-size: .78rem; font-weight: 650; }}
    main {{ padding-bottom: 80px; }}
    .hero {{ min-height: 540px; display: flex; flex-direction: column; justify-content: center; padding: 72px 0 62px; border-bottom: 1px solid var(--line); }}
    .eyebrow {{ color: var(--accent); font: 650 .69rem/1.4 var(--mono); letter-spacing: .16em; text-transform: uppercase; }}
    h1 {{ max-width: 930px; margin: 22px 0 30px; font-size: clamp(4.6rem, 10.8vw, 8.8rem); font-weight: 620; line-height: .82; letter-spacing: -.075em; text-wrap: balance; }}
    h2 {{ max-width: 760px; margin: 12px 0 0; font-size: clamp(2.35rem, 4.2vw, 4rem); font-weight: 590; line-height: 1; letter-spacing: -.052em; text-wrap: balance; }}
    h3 {{ margin: 0; font-size: 1.15rem; letter-spacing: -.02em; }}
    .hero-copy {{ max-width: 700px; margin: 0; color: var(--muted); font-size: 1.13rem; line-height: 1.65; text-wrap: pretty; }}
    .hero-meta {{ display: flex; flex-wrap: wrap; gap: 9px; margin-top: 34px; }}
    .pill {{ border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,.62); padding: .48rem .72rem; font: 650 .67rem var(--mono); letter-spacing: .06em; text-transform: uppercase; }}
    .pill.good {{ color: var(--accent); border-color: #b9d9c7; background: var(--accent-soft); }}
    .scoreboard {{ display: grid; grid-template-columns: repeat(4, 1fr); border-block: 1px solid var(--line); background: transparent; margin-top: -24px; }}
    .score {{ min-height: 124px; padding: 22px 24px; border-right: 1px solid var(--line); display: flex; flex-direction: column; justify-content: space-between; }}
    .score:last-child {{ border-right: 0; }}
    .score small, .label {{ color: var(--muted); font: 600 .67rem var(--mono); letter-spacing: .1em; text-transform: uppercase; }}
    .score strong {{ font-size: clamp(1.65rem, 2.6vw, 2.5rem); font-weight: 570; letter-spacing: -.05em; }}
    .score strong.good, .positive {{ color: var(--accent); }}
    .negative {{ color: var(--red); }}
    .section {{ padding: 92px 0; border-bottom: 1px solid var(--line); }}
    .section-head {{ display: grid; grid-template-columns: 180px 1fr; gap: 24px; align-items: start; margin-bottom: 48px; }}
    .section-head p {{ max-width: 600px; margin: 18px 0 0; color: var(--muted); line-height: 1.6; }}
    .trace {{ display: grid; grid-template-columns: repeat(13, minmax(0, auto)); align-items: center; gap: 8px; overflow-x: auto; padding: 6px 0 16px; }}
    .trace-step {{ min-width: 128px; min-height: 108px; padding: 16px; border-top: 1px solid var(--line); background: transparent; }}
    .trace-step:last-child {{ color: var(--accent); border-color: var(--accent); background: linear-gradient(180deg, var(--accent-soft), transparent); }}
    .trace-step strong {{ display: block; font: 650 .68rem var(--mono); letter-spacing: .1em; }}
    .trace-step span {{ display: block; margin-top: 26px; color: var(--muted); font-size: .78rem; line-height: 1.35; }}
    .arrow {{ color: #a4aaa4; font-size: .9rem; }}
    .proof-layout {{ display: grid; grid-template-columns: 1.25fr .75fr; margin-top: 28px; }}
    .receipt {{ min-height: 340px; padding: 30px; color: #edf2ee; background: var(--dark); }}
    .receipt-head {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 24px; border-bottom: 1px solid var(--dark-line); }}
    .receipt-head .label {{ color: #89928b; }}
    .receipt-status {{ color: #7ce0aa; font: 650 .72rem var(--mono); letter-spacing: .08em; }}
    .receipt-title {{ margin: 28px 0 36px; font-size: clamp(2rem, 4vw, 3.8rem); line-height: 1; letter-spacing: -.05em; }}
    .receipt-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }}
    .receipt-grid div {{ padding-top: 16px; border-top: 1px solid var(--dark-line); }}
    .receipt-grid small {{ display: block; color: #89928b; font: .66rem var(--mono); letter-spacing: .1em; }}
    .receipt-grid strong {{ display: block; margin-top: 8px; font-size: 1.05rem; font-weight: 520; }}
    .receipt-id {{ margin-top: 28px; padding: 14px 16px; border: 1px solid var(--dark-line); border-radius: 8px; color: #a8b0aa; font: .72rem/1.5 var(--mono); overflow-wrap: anywhere; }}
    .invariants {{ border: 1px solid var(--line); border-left: 0; background: transparent; }}
    .invariant {{ min-height: 170px; padding: 26px; }}
    .invariant + .invariant {{ border-top: 1px solid var(--line); }}
    .invariant strong {{ display: block; margin-bottom: 15px; font-size: 1.02rem; }}
    .invariant strong span {{ color: var(--accent); margin-right: 10px; font-family: var(--mono); }}
    .invariant p {{ margin: 0; color: var(--muted); font-size: .9rem; line-height: 1.55; }}
    .policy-note {{ margin: 18px 0 0; color: var(--muted); font-size: .78rem; }}
    .broker-summary {{ display: grid; grid-template-columns: 1.3fr .7fr; gap: 24px; padding: 28px; border: 1px solid #bfdccb; border-radius: 4px; background: var(--accent-soft); }}
    .broker-summary .identity {{ font-size: clamp(1.5rem, 3vw, 2.5rem); line-height: 1.2; letter-spacing: -.04em; }}
    .broker-summary .identity strong {{ color: var(--accent); }}
    .broker-summary p {{ margin: 0; color: #4d6255; line-height: 1.55; }}
    .text-link {{ display: inline-block; margin-top: 14px; color: var(--accent); font-size: .82rem; font-weight: 650; text-decoration: none; }}
    .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }}
    .chart-card {{ margin: 0; padding: 10px; border: 1px solid var(--line); border-radius: 4px; background: var(--panel); }}
    .chart-card figcaption {{ display: flex; justify-content: space-between; align-items: baseline; padding: 10px 8px 16px; }}
    .chart-card figcaption strong {{ font-size: 1rem; }}
    .chart-card figcaption span {{ color: var(--muted); font: .66rem var(--mono); }}
    .chart-card img {{ display: block; width: 100%; height: auto; background: var(--dark); }}
    .subhead {{ margin: 58px 0 18px; font-size: 1.35rem; }}
    .table-wrap {{ width: 100%; overflow-x: auto; border-top: 1px solid var(--ink); }}
    table {{ width: 100%; border-collapse: collapse; font-size: .86rem; }}
    th, td {{ padding: 15px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font: 600 .66rem var(--mono); letter-spacing: .08em; text-transform: uppercase; }}
    td:last-child, th:last-child {{ text-align: right; }}
    .timeline {{ display: grid; grid-template-columns: repeat(4, 1fr); border-top: 1px solid var(--line); border-left: 1px solid var(--line); }}
    .timeline-day {{ min-height: 128px; padding: 20px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); background: rgba(255,255,255,.4); }}
    .timeline-day small, .timeline-day strong, .timeline-day span {{ display: block; }}
    .timeline-day small {{ color: var(--muted); font: .66rem var(--mono); letter-spacing: .08em; }}
    .timeline-day strong {{ margin: 15px 0 10px; color: var(--accent); font: 650 .76rem var(--mono); }}
    .timeline-day span {{ color: var(--muted); font-size: .78rem; line-height: 1.42; }}
    .probe-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-top: 42px; }}
    .probe {{ padding: 24px; border-top: 1px solid var(--ink); }}
    .probe strong {{ display: block; margin: 10px 0 20px; font-size: 1.05rem; }}
    .probe span {{ color: var(--accent); font: 650 .72rem var(--mono); }}
    .disclosures {{ display: grid; grid-template-columns: repeat(3, 1fr); border-block: 1px solid var(--line); }}
    .disclosure {{ min-height: 156px; padding: 24px; border-right: 1px solid var(--line); }}
    .disclosure:last-child {{ border-right: 0; }}
    .disclosure strong {{ display: block; margin-bottom: 18px; }}
    .disclosure p {{ margin: 0; color: var(--muted); font-size: .88rem; line-height: 1.55; }}
    details {{ border-block: 1px solid var(--line); background: transparent; }}
    summary {{ display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 16px; cursor: pointer; list-style: none; }}
    summary::-webkit-details-marker {{ display: none; }}
    summary::after {{ content: ""; width: 7px; height: 7px; margin: -4px 3px 0 8px; border-right: 1.5px solid var(--muted); border-bottom: 1.5px solid var(--muted); transform: rotate(45deg); transition: transform .18s ease; }}
    details[open] summary::after {{ margin-top: 4px; transform: rotate(225deg); }}
    .research {{ margin-top: 20px; border-top: 0; }}
    .research > summary {{ padding: 22px 24px; }}
    .research > summary {{ grid-template-columns: 1fr auto auto; }}
    .research > summary span {{ font-weight: 650; }}
    .research > summary strong {{ color: var(--amber); font-size: .82rem; font-weight: 650; }}
    .research-body {{ display: grid; grid-template-columns: .65fr 1.35fr; gap: 28px; align-items: center; padding: 0 24px 24px; border-top: 1px solid var(--line); }}
    .research-body > div {{ padding-top: 24px; }}
    .research-body img {{ display: block; width: 100%; margin-top: 24px; border-radius: 8px; }}
    .resources {{ display: flex; justify-content: space-between; align-items: center; gap: 24px; padding: 42px 0; border-bottom: 1px solid var(--line); }}
    .resources p {{ max-width: 520px; margin: 0; color: var(--muted); }}
    .actions {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 9px; }}
    .button {{ padding: .72rem .9rem; border: 1px solid var(--ink); border-radius: 7px; background: var(--ink); color: white; font-size: .75rem; font-weight: 650; text-decoration: none; }}
    .button.secondary {{ padding-inline: .35rem; border: 0; border-radius: 0; background: transparent; color: var(--ink); text-decoration: underline; text-decoration-color: #b7bbb6; }}
    .ledger {{ margin-top: 48px; }}
    .ledger > summary {{ padding: 20px 4px; font-weight: 650; }}
    .ledger-content {{ padding: 0 24px 24px; border-top: 1px solid var(--line); overflow: hidden; }}
    article.episode {{ margin: 18px 0; padding: 22px; border: 1px solid var(--line); border-radius: 10px; background: var(--soft); }}
    article.episode h2 {{ font-size: 1.4rem; margin-top: 0; }}
    article.episode h3 {{ margin-top: 28px; }}
    .caveat {{ padding: 12px 14px; border-left: 3px solid var(--amber); background: var(--amber-soft); color: #5f4c27; }}
    dt {{ margin-top: 10px; font-weight: 650; }}
    dd {{ margin: 5px 0 0; color: var(--muted); }}
    pre {{ max-height: 360px; padding: 14px; overflow: auto; border-radius: 8px; color: #dbe4dd; background: var(--dark); font-size: .78rem; }}
    code {{ font-size: .9em; overflow-wrap: anywhere; }}
    .empty, .muted {{ color: var(--muted); }}
    footer {{ display: flex; justify-content: space-between; padding: 28px 0 54px; color: var(--muted); font-size: .74rem; }}
    @media (max-width: 900px) {{
      .site-header {{ grid-template-columns: 1fr auto; }} .nav {{ display: none; }}
      .scoreboard, .timeline {{ grid-template-columns: repeat(2, 1fr); }} .score:nth-child(2) {{ border-right: 0; }} .score:nth-child(-n+2) {{ border-bottom: 1px solid var(--line); }}
      .section-head, .proof-layout, .broker-summary, .chart-grid, .research-body {{ grid-template-columns: 1fr; }}
      .probe-grid, .disclosures {{ grid-template-columns: 1fr; }}
      .invariants {{ border-top: 0; border-left: 1px solid var(--line); }}
      .disclosure {{ min-height: 0; border-right: 0; border-bottom: 1px solid var(--line); }} .disclosure:last-child {{ border-bottom: 0; }}
      .section {{ padding: 82px 0; }} .section-head {{ gap: 14px; }}
      .resources {{ align-items: flex-start; flex-direction: column; }} .actions {{ justify-content: flex-start; }}
    }}
    @media (max-width: 560px) {{
      .site-header, main, footer {{ width: min(calc(100% - 28px), 1232px); }} .header-action {{ display: none; }}
      .eyebrow {{ overflow-wrap: anywhere; }}
      .hero {{ min-height: 520px; padding-top: 60px; }} h1 {{ font-size: clamp(4rem, 22vw, 6rem); }}
      .scoreboard {{ grid-template-columns: 1fr; margin-top: -18px; }} .score {{ min-height: 112px; border-right: 0; border-bottom: 1px solid var(--line); }} .score:last-child {{ border-bottom: 0; }}
      .receipt-grid {{ grid-template-columns: 1fr; }} .timeline {{ grid-template-columns: 1fr 1fr; }}
      .research > summary {{ grid-template-columns: 1fr auto; }} .research > summary strong {{ grid-column: 1; grid-row: 2; justify-self: start; margin-top: 6px; }} .research > summary::after {{ grid-column: 2; grid-row: 1 / span 2; }}
      footer {{ display: block; }} footer span {{ display: block; margin-top: 8px; }}
    }}
  </style>
</head>
<body>
  <header class="site-header">
    <a class="brand" href="#top">OPTICYCLE</a>
    <nav class="nav" aria-label="Evidence sections"><a href="#proof">Proof</a><a href="#results">Results</a><a href="#operations">Operations</a></nav>
    <a class="header-action" href="../demo.mp4">Watch demo ↗</a>
  </header>
  <main id="top">
    <section class="hero">
      <div class="eyebrow">SANITIZED ALPACA PAPER EVIDENCE · SEP 3 SNAPSHOT</div>
      <h1>Proof,<br/>before capital.</h1>
      <p class="hero-copy">One SPY options agent. The model proposes a direction; deterministic risk authorizes the exact order; Alpaca broker state decides what is true.</p>
      <div class="hero-meta"><span class="pill">Paper only</span><span class="pill">Official Alpaca MCP</span><span class="pill good">Broker reconciled</span></div>
    </section>

    <section class="scoreboard" aria-label="Key evidence">
      <div class="score"><small>Price-bound match</small><strong class="good">1 exact</strong></div>
      <div class="score"><small>Submit → resubmit</small><strong>1 → 0</strong></div>
      <div class="score"><small>Closed realized P&amp;L</small><strong class="good">+$55.67</strong></div>
      <div class="score"><small>Sep 3 paper equity</small><strong>$100,132.45</strong></div>
    </section>

    <section class="section" id="proof">
      <div class="section-head">
        <div class="eyebrow">01 / GOLDEN TRACE</div>
        <div><h2>One order. Seven verifiable steps.</h2><p>The only price-bound live match, reduced to the decisions a judge needs to verify.</p></div>
      </div>
      {golden_trace}
      <div class="proof-layout">
        <article class="receipt">
          <div class="receipt-head"><span class="label">ALPACA PAPER RECEIPT</span><span class="receipt-status">✓ EXACT MATCH</span></div>
          <div class="receipt-title">SPY 740P / 724P<br/>bull put</div>
          <div class="receipt-grid">
            <div><small>LIMIT / FILL</small><strong>−2.26 / −2.26</strong></div>
            <div><small>QUANTITY</small><strong>1× MLEG</strong></div>
            <div><small>TRANSPORT</small><strong>Alpaca MCP 2.3.0</strong></div>
          </div>
          <div class="receipt-id">client_order_id · {SIGNED_CLIENT_ORDER_ID}</div>
        </article>
        <aside class="invariants">
          <div class="invariant"><strong><span>01</span>Byte-bound authorization</strong><p>Change any symbol, side, ratio, intent, quantity, or price and the certificate no longer matches.</p></div>
          <div class="invariant"><strong><span>02</span>Zero-resubmit recovery</strong><p>An uncertain response triggers GET by the same client ID—never a second order.</p></div>
        </aside>
      </div>
      <p class="policy-note">Historical receipt. Current selector policy: 3–10 DTE, exact $5 width, 0.20–0.30 short-leg delta.</p>
    </section>

    <section class="section" id="results">
      <div class="section-head">
        <div class="eyebrow">02 / BROKER RESULTS</div>
        <div><h2>Account truth, at explicit timestamps.</h2><p>Broker observations stay separate from modeled research and from values captured at different times.</p></div>
      </div>
      <div class="broker-summary">
        <div class="identity">$100,281.45 cash + $283 long − $432 short = <strong>$100,132.45 equity</strong></div>
        <div><p>Sep 3, 19:43 PDT. The separate P&amp;L bridge differs by $0.22; the residual is disclosed, not force-fit.</p><a class="text-link" href="alpaca_cli_snapshot.json">Open broker snapshot ↗</a></div>
      </div>
      <div class="chart-grid">
        <figure class="chart-card"><figcaption><strong>Paper equity observations</strong><span>ALPACA PORTFOLIO HISTORY</span></figcaption><img src="equity-curve.png" alt="Paper account equity curve generated from Alpaca portfolio history"/></figure>
        <figure class="chart-card"><figcaption><strong>Observed return vs SPY</strong><span>EXACT SHARED DATES</span></figcaption><img src="equity-vs-spy.png" alt="Observed Opticycle account return compared with SPY over exact shared dates"/></figure>
      </div>
      <h3 class="subhead">Executed positions</h3>
      <div class="table-wrap"><table class="result">
        <thead><tr><th>Spread</th><th>Broker entry</th><th>Exit / state</th><th>P&amp;L at record</th></tr></thead>
        <tbody>
          <tr><td><a href="sanitized_fills/oc-204a8dfccffd40c9.json">SPY 793C/809C bear call</a></td><td>2.11 credit</td><td>1.53 debit · MCP</td><td class="positive">+$58</td></tr>
          <tr><td><a href="sanitized_fills/oc-715ad36a630d408e.json">SPY 768C/769C bear call</a></td><td>0.51 credit</td><td>0.53 debit · MCP</td><td class="negative">−$2</td></tr>
          <tr><td><a href="sanitized_fills/oc-63db2a85298b4ecabefab59076a6397e.json">SPY 740P/724P bull put</a></td><td>2.26 credit</td><td>Open at snapshot</td><td class="positive">+$77 unrealized</td></tr>
          <tr><td><strong>Closed total</strong></td><td colspan="2">Alpaca flatten equity $100,055.67</td><td class="positive"><strong>+$55.67</strong></td></tr>
        </tbody>
      </table></div>
    </section>

    <section class="section" id="operations">
      <div class="section-head">
        <div class="eyebrow">03 / OPERATIONS</div>
        <div><h2>Missing days stay missing.</h2><p>Recorded runs from August 28 through the September 4 deadline. Nothing is backfilled.</p></div>
      </div>
      <div class="timeline">{timeline_html}</div>
      <div class="probe-grid">
        <div class="probe"><div class="label">STALE QUOTE</div><strong>Stop before the model</strong><span>NO_TRADE</span></div>
        <div class="probe"><div class="label">MUTATED PAYLOAD</div><strong>Invalidate authorization</strong><span>VETO</span></div>
        <div class="probe"><div class="label">UNKNOWN RESPONSE</div><strong>GET the same client ID</strong><span>MATCHED · 0 RESUBMITS</span></div>
      </div>
    </section>

    <section class="section" id="disclosure">
      <div class="section-head">
        <div class="eyebrow">04 / BOUNDARIES</div>
        <div><h2>What this evidence does not claim.</h2><p>Concise disclosures keep the live result legible without hiding its limits.</p></div>
      </div>
      <div class="disclosures">
        <article class="disclosure"><strong>Earlier fills are not exact matches</strong><p>The first two historical credits used the wrong limit sign. They remain FILLED. Only the third entry is price-bound MATCHED.</p></article>
        <article class="disclosure"><strong>Observations are time-bound</strong><p>$100,132.45 is the Sep 3 account snapshot. $100,086.45 is a historical daily endpoint, not current equity.</p></article>
        <article class="disclosure"><strong>Research is not broker P&amp;L</strong><p>The walk-forward result is modeled from prior-only IEX bars and disclosed assumptions.</p></article>
      </div>
{walk_forward.lstrip()}
    </section>

    <section class="resources">
      <p><strong>Verify the claim, not the presentation.</strong><br/>The raw broker artifacts and release hashes remain directly accessible.</p>
      <div class="actions">
        <a class="button" href="../demo.mp4">Watch demo</a>
        <a class="button secondary" href="broker_lookup.json">Broker receipts</a>
        <a class="button secondary" href="manifest.json">Release hashes</a>
      </div>
    </section>

    <details class="ledger" id="records">
      <summary>Full sanitized ledger and claim map</summary>
      <div class="ledger-content">
        <h3 class="subhead">Claim → record → historical build</h3>
        <p class="muted">Build IDs are pre-release provenance retained after the release squash; they are not checkout targets in this one-commit repository.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Claim</th><th>Record ID</th><th>Historical build</th><th>Status</th></tr></thead>
          <tbody>{''.join(claim_rows)}</tbody>
        </table></div>
{''.join(cards)}
      </div>
    </details>
    <script type="application/json" id="sanitized-ledger">{embedded}</script>
  </main>
  <footer><strong>OPTICYCLE · PAPER ONLY</strong><span>Public evidence · account {DESIGNATED_ACCOUNT_ID}</span></footer>
</body>
</html>
"""


def write_evidence_artifacts(
    records: list[dict[str, Any]],
    *,
    dest_dir: Path | None = None,
    write_public_ledger: bool = True,
) -> dict[str, Path]:
    dest = dest_dir or EVIDENCE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    public_path = dest / "public.jsonl"
    manifest_path = dest / "manifest.json"
    page_path = dest / "index.html"
    sanitized = [redact_public_model_metadata(sanitize(row)) for row in records]
    for row in sanitized:
        row["ledger_class"] = "public_sanitized"
    if write_public_ledger:
        public_path.write_text(
            "".join(canonical_dumps(row) + "\n" for row in sanitized),
            encoding="utf-8",
        )
    manifest = build_manifest(sanitized)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    page_path.write_text(render_evidence_page(sanitized, manifest), encoding="utf-8")
    return {"public": public_path, "manifest": manifest_path, "page": page_path}
