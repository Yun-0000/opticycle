"""Regular-session automation: manage positions, then consider one paper MLEG.

Never submits unless --submit. Paper only. The runner owns entry and exit gates.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from opticycle.ledger import canonical_dumps, sanitize
from opticycle.observe import AlpacaReadClient, ObservationClosed, observe_live
from opticycle.protocol import ObservationOutcome
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from opticycle.thesis import ThesisAgent, persist_thesis_episode, require_live_llm

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
LOCK_PATH = DATA_DIR / "open_session_lock.json"
LAST_PATH = DATA_DIR / "open_session_last.json"
ACCOUNT_ID_RE = re.compile(r"\bPA[A-Z0-9]{8,}\b")


class OpenSessionError(RuntimeError):
    """Open-session automation cannot run safely."""


def paper_keys_present() -> bool:
    return bool((os.environ.get("ALPACA_API_KEY") or "").strip()) and bool(
        (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    )


def llm_key_present() -> bool:
    return bool(
        (os.environ.get("OPENAI_API_KEY") or os.environ.get("HACKATHON_LLM_API_KEY") or "").strip()
    )


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def skip_reason(
    *,
    submit: bool,
    today: date | None = None,
    lock: Mapping[str, Any] | None = None,
) -> str | None:
    """Why this run must not place a new order. Observation-only may still proceed."""
    if not paper_keys_present():
        return "missing ALPACA_API_KEY or ALPACA_SECRET_KEY"
    if str(os.environ.get("ALPACA_LIVE_TRADE") or "").strip().lower() == "true":
        return "ALPACA_LIVE_TRADE must not be true"
    if not llm_key_present():
        return "missing OPENAI_API_KEY"
    if not submit:
        return "submit not enabled (pass --submit to enable MCP lifecycle management)"
    return None


def broker_fault_reason(exc: BaseException) -> str:
    """Fail-closed broker reason. Never includes HTML, account ids, or raw dumps."""
    blob = str(exc)
    lowered = blob.lower()
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    html = "<html" in lowered or "<!doctype html" in lowered
    if (
        status == 401
        or "unauthorized" in lowered
        or (html and "401" in lowered)
        or "401 authorization required" in lowered
    ):
        return "paper broker unauthorized"
    if status == 403 or "forbidden" in lowered:
        return "paper broker forbidden"
    return "paper broker unreachable"


def _clock_open(client: Any) -> tuple[bool, dict[str, Any]]:
    clock = client.fetch_clock()
    is_open = bool(getattr(clock, "is_open", False))
    payload = {
        "is_open": is_open,
        "timestamp": str(getattr(clock, "timestamp", "") or ""),
        "next_open": str(getattr(clock, "next_open", "") or ""),
        "next_close": str(getattr(clock, "next_close", "") or ""),
    }
    return is_open, payload


def _strip_secrets(value: Any) -> Any:
    cleaned = sanitize(value)
    blob = canonical_dumps(cleaned)
    if ACCOUNT_ID_RE.search(blob):
        cleaned = json.loads(ACCOUNT_ID_RE.sub("omitted", blob))
    return cleaned


def write_last(payload: Mapping[str, Any], *, path: Path = LAST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_strip_secrets(dict(payload)), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_lock(payload: Mapping[str, Any], *, path: Path = LOCK_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_strip_secrets(dict(payload)), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_open_session(
    *,
    submit: bool = False,
    settings: HackathonSettings | None = None,
    client: Any | None = None,
    today: date | None = None,
    last_path: Path = LAST_PATH,
    lock_path: Path = LOCK_PATH,
) -> dict[str, Any]:
    """Observe live. Optionally run one certified entry/exit lifecycle cycle."""
    settings = settings or HackathonSettings()
    os.environ["ALPACA_PAPER_TRADE"] = "true"
    os.environ["ALPACA_LIVE_TRADE"] = "false"
    blocked = skip_reason(submit=submit, today=today, lock=load_lock(lock_path))
    report: dict[str, Any] = {
        "schema": "opticycle.open-session.v2",
        "submit_requested": submit,
        "submitted": False,
        "model": (os.environ.get("HACKATHON_LLM_MODEL") or "gpt-5.6-luna").strip(),
        "blocked": blocked,
        "closes_positions": bool(submit),
    }
    if blocked and blocked.startswith("missing"):
        write_last(report, path=last_path)
        return report
    if blocked == "ALPACA_LIVE_TRADE must not be true":
        write_last(report, path=last_path)
        return report

    reader = client
    if reader is None:
        try:
            reader = AlpacaReadClient.from_env()
        except ObservationClosed as exc:
            report["blocked"] = exc.reason
            write_last(report, path=last_path)
            return report

    try:
        is_open, clock = _clock_open(reader)
    except Exception as exc:
        report["blocked"] = broker_fault_reason(exc)
        write_last(report, path=last_path)
        return report
    report["clock"] = clock
    if not is_open:
        report["blocked"] = "regular session is closed"
        write_last(report, path=last_path)
        return report

    if not submit or (blocked and str(blocked).startswith("submit not enabled")):
        try:
            observation = observe_live(settings, client=reader)
        except ObservationClosed as exc:
            report["blocked"] = exc.reason
            write_last(report, path=last_path)
            return report
        except Exception as exc:
            report["blocked"] = broker_fault_reason(exc)
            write_last(report, path=last_path)
            return report
        report["observation_outcome"] = observation.outcome.value
        report["observation_reason"] = observation.reason
        if observation.outcome != ObservationOutcome.OK or observation.evidence is None:
            write_last(report, path=last_path)
            return report
        from opticycle.journal import TradeJournal

        journal = TradeJournal(DATA_DIR / "open-session-journal.jsonl")
        thesis = ThesisAgent(require_live_llm(None)).evaluate(observation.evidence)
        persist_thesis_episode(journal, observation.evidence, thesis)
        report["thesis"] = {
            "stance": thesis.stance.value,
            "accepted": thesis.accepted,
            "model_called": thesis.model_called,
            "reason_code": thesis.reason_code,
        }
        write_last(report, path=last_path)
        return report

    if blocked:
        write_last(report, path=last_path)
        return report

    try:
        result = run_once(settings, dry_run=False, observer=reader, provenance="live_paper")
    except Exception as exc:
        report["blocked"] = broker_fault_reason(exc)
        write_last(report, path=last_path)
        return report
    report["outcome"] = result.get("outcome")
    report["reason"] = result.get("reason")
    report["submitted"] = bool(result.get("submitted"))
    report["client_order_id"] = result.get("client_order_id") or ""
    report["record_id"] = result.get("record_id") or ""
    report["claim"] = result.get("claim") or ""
    order = result.get("order") or {}
    if isinstance(order, Mapping):
        report["mcp"] = {
            "tool": order.get("tool"),
            "submitted": order.get("submitted"),
            "arguments_hash": order.get("arguments_hash"),
            "raw_result_hash": order.get("raw_result_hash"),
            "dry_run": order.get("dry_run"),
        }
    if report["submitted"]:
        previous = load_lock(lock_path)
        day = (today or datetime.now(timezone.utc).date()).isoformat()
        same_day = previous.get("submit_date") == day
        arguments = order.get("arguments") if isinstance(order, Mapping) else {}
        try:
            submitted_qty = int((arguments or {}).get("qty") or result.get("filled_qty") or 1)
        except (TypeError, ValueError):
            submitted_qty = 1
        write_lock(
            {
                "submit_date": day,
                "client_order_id": report["client_order_id"],
                "raw_result_hash": (report.get("mcp") or {}).get("raw_result_hash"),
                "submit_count": (int(previous.get("submit_count") or 0) if same_day else 0) + 1,
                "contracts_opened": (
                    int(previous.get("contracts_opened") or 0) if same_day else 0
                )
                + submitted_qty,
            },
            path=lock_path,
        )
    write_last(report, path=last_path)
    return report
