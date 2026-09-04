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
PUBLIC_LLM_MODEL = "gpt-5.6-luna"

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
    "artifacts/opticycle-one-page.pdf",
    "artifacts/opticycle-slides.pdf",
    "artifacts/opticycle-slides.pptx",
    "artifacts/evidence/alpaca_cli_snapshot.json",
    "artifacts/evidence/broker_lookup.json",
    "artifacts/evidence/paper_fill_ingest.json",
    "artifacts/evidence/portfolio_history.json",
)


def redact_public_model_metadata(value: Any) -> Any:
    """Publish the declared competition model while redacting any other model metadata."""
    if isinstance(value, Mapping):
        return {
            key: (
                item
                if str(key).lower() == "model" and item == PUBLIC_LLM_MODEL
                else "[REDACTED]"
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
        return PUBLIC_MODEL_RE.sub(
            lambda match: match.group(0)
            if match.group(0).lower() == PUBLIC_LLM_MODEL
            else "[REDACTED]",
            value,
        )
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
  <section class="equity modeled">
    <div class="eyebrow">RESEARCH CONTEXT / ALPACA IEX DAILY / BLACK-SCHOLES</div>
    <h2>Modeled walk-forward</h2>
    <div class="facts">
      <div class="fact"><small>Modeled return</small><strong>{float(metrics.get('total_return_pct') or 0):+.2f}%</strong></div>
      <div class="fact"><small>Sequential trades</small><strong>{int(metrics.get('trades') or 0)}</strong></div>
      <div class="fact"><small>Max drawdown</small><strong>{float(metrics.get('max_drawdown_pct') or 0):.2f}%</strong></div>
    </div>
    <img src="walk-forward-backtest.png" alt="Modeled SPY vertical walk-forward compared with SPY close benchmark"/>
    <p class="muted">Rolling-origin, prior observations only; 3–10 DTE with a fixed 5-day target, exact $5 width, 0.25 absolute short delta, 50% credit-capture take-profit, 2×-credit stop, ≤1 DTE force-close, and Black-Scholes prices using a disclosed 1.20× IV/RV premium assumption. Range {html.escape(str(date_range.get('start') or ''))} to {html.escape(str(date_range.get('end') or ''))}. <a href="walk-forward-backtest.html">Open the method, sensitivity, and limitations</a>.</p>
  </section>
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
    """Copy records for the public evidence page. Injected NO_TRADE empty slots are not fill TODOs."""
    out: list[dict[str, Any]] = []
    for row in records:
        if is_injected_no_trade(row):
            copied = json.loads(json.dumps(row))
            copied.pop("live_paper_incomplete", None)
            extra = dict(copied.get("extra") or {})
            extra.pop("live_paper_incomplete", None)
            copied["extra"] = extra
            episode = copied.get("episode") or {}
            for field, slot in list(episode.items()):
                if not isinstance(slot, dict) or slot.get("present"):
                    continue
                slot["reason"] = INJECTED_NO_TRADE_SLOT_ABSENT
                episode[field] = slot
            copied["episode"] = episode
            out.append(copied)
            continue
        if is_genuine_no_trade(row):
            copied = json.loads(json.dumps(row))
            copied.pop("live_paper_incomplete", None)
            extra = dict(copied.get("extra") or {})
            extra.pop("live_paper_incomplete", None)
            copied["extra"] = extra
            episode = copied.get("episode") or {}
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
        out.append(row)
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
    recon = slot_value(golden, "reconciliation") or {}
    steps = [
        (
            "SNAPSHOT",
            f"{snapshot.get('underlying', 'SPY')} · {snapshot.get('session', 'regular')} · sanitized",
        ),
        (
            "LLM STANCE",
            f"{thesis.get('stance')} · {thesis.get('model') or PUBLIC_LLM_MODEL} · model_called=true",
        ),
        (
            "PAYLOAD",
            f"bull put · qty {candidate.get('qty')} · limit {candidate.get('limit_price')}",
        ),
        (
            "CERT",
            f"approved · payload {str(certificate.get('payload_hash') or '')[:12]}…",
        ),
        (
            "MCP",
            f"place_option_order · mleg · submit {mcp.get('mcp_submit_count')}",
        ),
        (
            "GET",
            f"order {str(receipt.get('broker_order_id') or '')[:8]}… · fill {receipt.get('filled_avg_price')}",
        ),
        (
            "MATCHED",
            f"price_bound={str(recon.get('price_bound_matched')).lower()} · second_submit={str(mcp.get('second_submit')).lower()}",
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
    live_ids = "".join(
        f"<li><code>{html.escape(cid)}</code></li>"
        for cid in sorted(set(LIVE_MATCHED_CLIENT_IDS) | {SIGNED_CLIENT_ORDER_ID})
    )
    gate11 = dict(status or load_gate11_status())
    quote_gap = html.escape(str(gate11.get("live_quote_gap") or ""))
    genuine = (
        "yes — live Alpaca stale-quote NO_TRADE (does not mean live fills are missing)"
        if gate11.get("genuine_no_trade_recorded")
        else "no — gap recorded honestly (does not mean live fills are missing)"
    )
    ingest_note = (
        "Two historical live_paper broker fills "
        f"({', '.join(sorted(LIVE_MATCHED_CLIENT_IDS))}) remain unsigned-limit FILLED, "
        "not price-bound MATCHED. In-session signed-credit fill "
        f"{SIGNED_CLIENT_ORDER_ID} is price-bound MATCHED "
        "(limit -2.26, fill -2.26, ThesisAgent model_called=true). "
        "Prior verticals were closed via MCP place_option_order mleg; those close "
        "orders retained raw_result_hash. The open credit MLEG's MCP envelope was "
        "not returned after broker accept; Alpaca GET is the fill source. "
        f"Paper account {DESIGNATED_ACCOUNT_ID}. The committed Sep 1 CLI snapshot reports "
        "equity 100036.62 and open unrealized P&L -19.00. The older portfolio-history "
        "endpoint ends at 100026.77 and is shown only as a historical chart point."
    )
    page_records = _page_records(records)
    golden_trace = _golden_trace(page_records)
    strategy_premise = (
        "Trade risk-budgeted SPY defined-risk credit verticals only when fresh evidence, "
        "an LLM stance, and an exact-payload deterministic certificate all agree; "
        "otherwise record NO_TRADE or HALT."
    )
    run_timeline = (
        ("AUG 28", "TEST ONLY", "Injected missing-quote NO_TRADE; explicitly not live evidence."),
        ("AUG 29", "NOT RUN", "No recorded autonomous paper episode."),
        ("AUG 30", "NOT RUN", "No recorded autonomous paper episode."),
        ("AUG 31", "RAN", "Two paper fills plus a genuine stale-quote NO_TRADE."),
        ("SEP 01", "RAN", "Two MCP closes; one signed-credit, price-bound MATCHED fill."),
        ("SEP 02", "NOT RUN", "No recorded autonomous paper episode."),
        ("SEP 03", "NOT RUN", "No recorded autonomous paper episode as of publication."),
        ("SEP 04", "PENDING", "Submission deadline 08:00 PDT; no episode claimed."),
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
  <title>Opticycle public evidence</title>
  <style>
    :root {{ color-scheme: dark; --bg: #0b0e12; --panel: #1f2124; --line: #303235; --ink: #dedede; --muted: #818284; --accent: #00d892; --accent-dark: #002923; --amber: #cab16a; --red: #ff6285; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; margin: 0 auto; padding: 3.5rem 1.5rem 7rem; max-width: 1320px; color: var(--ink); background-color: var(--bg); background-image: linear-gradient(#1f2124 1px, transparent 1px), linear-gradient(90deg, #1f2124 1px, transparent 1px); background-size: 32px 32px; }}
    h1 {{ font-size: clamp(2.8rem, 7vw, 5.5rem); font-weight: 400; line-height: .94; letter-spacing: -.055em; margin: .55rem 0 1.3rem; max-width: 880px; text-wrap: balance; }}
    h2 {{ margin-top: 2rem; }}
    a {{ color: var(--ink); }}
    .eyebrow {{ color: var(--accent); font: 600 .74rem ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .16em; text-transform: uppercase; }}
    .lede {{ color: var(--muted); max-width: 780px; font-size: 1.1rem; line-height: 1.6; }}
    .trace {{ display: grid; grid-template-columns: repeat(13, minmax(0, auto)); align-items: stretch; gap: .55rem; margin: 2.5rem 0 1.1rem; overflow-x: auto; padding-bottom: .5rem; }}
    .trace-step {{ min-width: 145px; padding: 1rem; border: 1px solid var(--line); border-radius: 1px; background: var(--panel); }}
    .trace-step:last-child {{ border-color: var(--accent); box-shadow: inset 0 -3px var(--accent); }}
    .trace-step strong {{ display: block; color: var(--accent); font: 600 .76rem ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .1em; }}
    .trace-step span {{ display: block; margin-top: .65rem; color: var(--muted); font-size: .82rem; line-height: 1.35; }}
    .arrow {{ display: grid; place-items: center; color: #647080; }}
    .facts {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 1px; margin: 1rem 0 2.5rem; }}
    .fact {{ background: var(--panel); padding: 1.15rem; }}
    .fact small {{ display: block; color: var(--muted); font: .7rem ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; letter-spacing: .1em; }}
    .fact strong {{ display: block; margin-top: .45rem; font-size: 1.2rem; font-weight: 400; }}
    .equity {{ border: 1px solid var(--line); border-radius: 1px; background: var(--panel); padding: 1rem; margin: 2rem 0; }}
    .equity.modeled {{ border-color: #554b32; }}
    .equity.modeled .eyebrow {{ color: var(--amber); }}
    .equity img {{ display: block; width: 100%; height: auto; background: var(--bg); }}
    .invariants {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; border: 1px solid var(--line); background: var(--line); margin: 2.5rem 0; }}
    .invariant {{ background: var(--panel); padding: 1.35rem; }}
    .invariant strong {{ display: block; color: var(--accent); font-size: 1.1rem; margin-bottom: .55rem; }}
    .invariant p {{ color: var(--muted); line-height: 1.55; margin: 0; }}
    .timeline {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); margin: 1rem 0 2rem; }}
    .timeline-day {{ background: var(--panel); padding: 1rem; min-height: 132px; }}
    .timeline-day small, .timeline-day strong, .timeline-day span {{ display: block; }}
    .timeline-day small {{ color: var(--muted); font: .7rem ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .1em; }}
    .timeline-day strong {{ color: var(--accent); margin: .55rem 0; }}
    .timeline-day span {{ color: var(--muted); font-size: .82rem; line-height: 1.4; }}
    .result {{ font-size: 1rem; }}
    .positive {{ color: var(--accent); font-weight: 600; }}
    .negative {{ color: var(--red); font-weight: 600; }}
    .banner, .caveat {{ background: #181712; border: 1px solid #554b32; padding: 1rem 1.2rem; }}
    .premise {{ border-left: 3px solid var(--accent); padding: .1rem 0 .1rem 1.2rem; margin: 2.5rem 0; font-size: 1.3rem; line-height: 1.5; max-width: 1050px; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: .75rem; margin: 1.5rem 0 2.5rem; }}
    .button {{ color: var(--accent); background: var(--accent-dark); border: 1px solid #005441; border-radius: 1px; padding: .8rem 1rem; font: 600 .78rem ui-monospace, SFMono-Regular, Menlo, monospace; text-decoration: none; text-transform: uppercase; letter-spacing: .06em; }}
    .button.secondary {{ color: var(--ink); background: transparent; border: 1px solid var(--line); }}
    details {{ border: 1px solid var(--line); border-radius: 1px; background: var(--bg); padding: 1rem 1.2rem; margin-top: 2rem; }}
    summary {{ cursor: pointer; font-size: 1.15rem; font-weight: 800; }}
    article.episode {{ border: 1px solid var(--line); border-radius: 1px; padding: 1rem; margin: 1.25rem 0; background: var(--panel); }}
    dt {{ font-weight: 600; margin-top: 0.4rem; }}
    pre {{ background: var(--bg); padding: 0.75rem; overflow: auto; border: 1px solid var(--line); }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; word-break: break-all; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.85rem; }}
    th, td {{ border: 1px solid var(--line); padding: .65rem .7rem; text-align: left; vertical-align: top; }}
    th {{ color: var(--accent); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 400; }}
    .empty, .muted {{ color: var(--muted); }}
    @media (max-width: 780px) {{ .facts, .invariants, .timeline {{ grid-template-columns: 1fr; }} body {{ padding-top: 2rem; }} }}
  </style>
</head>
<body>
  <div class="eyebrow">OPTICYCLE / HISTORICAL GOLDEN TRACE / SANITIZED PAPER EVIDENCE</div>
  <h1>Two invariants.<br/>One broker truth.</h1>
  <p class="lede">Paper account <strong>{DESIGNATED_ACCOUNT_ID}</strong>. Opticycle binds authorization to the exact canonical MLEG payload bytes, then reconciles the same <code>client_order_id</code> without resubmitting when the transport result is uncertain.</p>
  <section class="invariants">
    <div class="invariant"><strong>01 / Byte-bound authorization</strong><p>Any symbol, side, ratio, quantity, price, or intent mutation changes the payload hash and invalidates the short-lived risk certificate.</p></div>
    <div class="invariant"><strong>02 / Zero-resubmit reconciliation</strong><p>One MCP submit. An uncertain response triggers Alpaca GET by the same client ID, never a second order. Reproduce without credentials: <code>python3 scripts/assert-zero-resubmit.py</code>.</p></div>
  </section>
  {golden_trace}
  <div class="facts">
    <div class="fact"><small>Golden client order</small><strong>{SIGNED_CLIENT_ORDER_ID}</strong></div>
    <div class="fact"><small>Historical execution proof · expiry 2026-10-16</small><strong>Sell SPY 740P / Buy SPY 724P · qty 1</strong></div>
    <div class="fact"><small>Price integrity</small><strong>Limit -2.26 / Fill -2.26</strong></div>
    <div class="fact"><small>Official transport</small><strong>Alpaca MCP 2.3.0 · MLEG only</strong></div>
    <div class="fact"><small>Timeout invariant</small><strong>mcp_submit_count=1 · second_submit=false</strong></div>
    <div class="fact"><small>Closed-spread realized P&amp;L</small><strong>+$55.67</strong></div>
    <div class="fact"><small>Sep 1 CLI account equity</small><strong>$100,036.62</strong></div>
    <div class="fact"><small>Sep 1 open unrealized P&amp;L</small><strong>−$19.00</strong></div>
    <div class="fact"><small>Historical portfolio endpoint</small><strong>$100,026.77 · not current</strong></div>
  </div>
  <p class="muted">This receipt predates the tightened selector policy. Current entries require 3–10 DTE, exact $5 width, and 0.20–0.30 short-leg delta.</p>
  <section class="equity">
    <div class="eyebrow">BROKER PAPER TRUTH / COMMITTED SEP 1 SNAPSHOT</div>
    <h2>One accounting identity, explicit timestamps</h2>
    <p class="lede"><strong>$100,000 starting equity + $55.67 closed-spread realized P&amp;L − $19.00 open unrealized P&amp;L = $100,036.67.</strong> The broker snapshot is $100,036.62; the $0.05 difference is the rounding precision of the public leg marks. The $100,026.77 portfolio-history point below is older and is not presented as current equity.</p>
    <p class="muted">Machine-readable snapshot: <a href="alpaca_cli_snapshot.json">alpaca_cli_snapshot.json</a></p>
  </section>
  <section class="equity">
    <div class="eyebrow">ALPACA / GET /V2/ACCOUNT/PORTFOLIO/HISTORY</div>
    <h2>Paper equity curve</h2>
    <img src="equity-curve.png" alt="Paper account equity curve generated from Alpaca portfolio history"/>
    <p class="muted">Machine-readable source: <a href="portfolio_history.json">portfolio_history.json</a></p>
  </section>
  <section class="equity">
    <div class="eyebrow">SAME-PERIOD BENCHMARK / EXACT SHARED DATES</div>
    <h2>Opticycle vs SPY</h2>
    <img src="equity-vs-spy.png" alt="Observed Opticycle account return compared with SPY over exact shared dates"/>
    <p class="muted">Two-endpoint comparison, not an interpolated curve. Sources: Alpaca portfolio history and Alpaca IEX daily bars. <a href="equity-vs-spy.json">Open the values</a>.</p>
  </section>
{walk_forward}
  <h2>Closed-trade results</h2>
  <table class="result">
    <thead><tr><th>Spread</th><th>Broker entry</th><th>MCP exit</th><th>Approx. realized P&amp;L</th></tr></thead>
    <tbody>
      <tr><td><a href="sanitized_fills/oc-204a8dfccffd40c9.json">SPY 793C/809C bear call</a></td><td>2.11 credit</td><td>1.53 debit</td><td class="positive">+$58</td></tr>
      <tr><td><a href="sanitized_fills/oc-715ad36a630d408e.json">SPY 768C/769C bear call</a></td><td>0.51 credit</td><td>0.53 debit</td><td class="negative">−$2</td></tr>
      <tr><td><a href="sanitized_fills/oc-63db2a85298b4ecabefab59076a6397e.json">SPY 740P/724P bull put</a></td><td>2.26 credit</td><td>open at Sep 1 snapshot</td><td>−$19 unrealized at snapshot</td></tr>
      <tr><td><strong>Closed total</strong></td><td colspan="2">Alpaca flatten equity 100055.67</td><td class="positive"><strong>+$55.67</strong></td></tr>
    </tbody>
  </table>
  <h2>Daily run record · PDT</h2>
  <p class="muted">August 28 through the September 4 deadline. Missing days are shown, not backfilled.</p>
  <div class="timeline">{timeline_html}</div>
  <div class="actions">
    <a class="button" href="../demo.mp4">Watch the rendered demo</a>
    <a class="button" href="../opticycle-one-page.pdf">Open the one-page</a>
    <a class="button" href="../opticycle-slides.pdf">Open the slides</a>
    <a class="button secondary" href="broker_lookup.json">Open broker GET receipts</a>
    <a class="button secondary" href="paper_fill_ingest.json">Open fill ingest summary</a>
    <a class="button secondary" href="manifest.json">Verify release hashes</a>
  </div>
  <p class="premise"><strong>Strategy premise.</strong> {html.escape(strategy_premise)}</p>
  <h2>Held-out and failure probes</h2>
  <table>
    <thead><tr><th>Probe</th><th>Evidence type</th><th>Expected behavior</th><th>Recorded result</th></tr></thead>
    <tbody>
      <tr><td>Stale SPY quote</td><td>Live Alpaca observation</td><td>Do not call ThesisAgent; do not submit</td><td>NO_TRADE</td></tr>
      <tr><td>Mutated or unsafe payload</td><td>Credential-free risk replay</td><td>Certificate veto</td><td>VETO</td></tr>
      <tr><td>MCP response unknown after accept</td><td>Golden live episode</td><td>Zero resubmit; GET same client ID</td><td>MATCHED</td></tr>
      <tr><td>Existing position without TP/SL/DTE trigger</td><td>Credential-free exits-only replay</td><td>No entry path; zero submits</td><td>NO_TRADE / no_exit_triggered</td></tr>
    </tbody>
  </table>
  <div class="banner">
    <p><strong>Public defect disclosure:</strong> the first two historical entries used a positive limit for intended credits. They remain <code>FILLED</code>, never price-bound <code>MATCHED</code>. Production now requires a negative credit limit; only the third entry proves it end to end.</p>
    <p><strong>One in-session live_paper fill is price-bound MATCHED</strong> (negative credit limit, filled &lt;= limit, ThesisAgent called). Two earlier live_paper fills remain unsigned-limit FILLED, not MATCHED. Replay channel MATCHED is not live_paper. Injected NO_TRADE is not fill evidence.</p>
    <p>{html.escape(NO_TRADE_CAVEAT)}</p>
    <p>Genuine live NO_TRADE this gate: {html.escape(genuine)}. {quote_gap}</p>
    <p>{html.escape(ingest_note)}</p>
    <p>Demo status: {html.escape(str(gate11.get('demo_mp4') or DEMO_VIDEO_STATUS))}.</p>
    <p>Authorized live_paper client_order_id values:</p>
    <ul>{live_ids}</ul>
  </div>
  <details>
    <summary>Full sanitized ledger and claim map</summary>
    <h2>Claim → record → commit</h2>
    <table>
      <thead><tr><th>claim</th><th>record id</th><th>commit (40-char)</th><th>status</th></tr></thead>
      <tbody>{''.join(claim_rows)}</tbody>
    </table>
{''.join(cards)}
  </details>
  <script type="application/json" id="sanitized-ledger">{embedded}</script>
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
