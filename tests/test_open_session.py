"""Open-session automation: skip without keys; never submit when the clock is closed."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from opticycle.open_session import run_open_session, skip_reason


def test_skip_reason_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert skip_reason(submit=True) == "missing ALPACA_API_KEY or ALPACA_SECRET_KEY"


def test_skip_reason_refuses_live_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "true")
    assert skip_reason(submit=True) == "ALPACA_LIVE_TRADE must not be true"


def test_skip_reason_one_submit_per_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "false")
    reason = skip_reason(submit=True, today=date(2026, 9, 1), lock={"submit_date": "2026-09-01"})
    assert reason is not None
    assert "already submitted" in reason


def test_unauthorized_clock_does_not_submit_or_leak_html(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "false")

    class UnauthorizedClock:
        def fetch_clock(self):
            raise RuntimeError(
                "<html>\n<head><title>401 Authorization Required</title></head>\n"
                "<body><center><h1>401 Authorization Required</h1></center></body></html>"
            )

    last = tmp_path / "last.json"
    report = run_open_session(
        submit=True,
        client=UnauthorizedClock(),
        last_path=last,
        lock_path=tmp_path / "lock.json",
    )
    assert report["submitted"] is False
    assert report["closes_positions"] is False
    assert report["blocked"] == "paper broker unauthorized"
    dumped = last.read_text(encoding="utf-8")
    assert "<html" not in dumped
    assert "401 Authorization Required" not in dumped


def test_closed_clock_does_not_submit(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "false")

    class ClosedClock:
        def fetch_clock(self):
            return SimpleNamespace(
                is_open=False,
                timestamp="2026-08-31T21:00:00Z",
                next_open="2026-09-01T09:30:00-04:00",
                next_close="2026-09-01T16:00:00-04:00",
            )

    last = tmp_path / "last.json"
    report = run_open_session(
        submit=True,
        client=ClosedClock(),
        last_path=last,
        lock_path=tmp_path / "lock.json",
    )
    assert report["submitted"] is False
    assert report["closes_positions"] is False
    assert report["blocked"] == "regular session is closed"
    assert last.is_file()


def test_script_without_keys_is_zero() -> None:
    import subprocess
    import sys
    from pathlib import Path

    env = {k: v for k, v in __import__("os").environ.items() if k not in {
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "OPENAI_API_KEY",
        "HACKATHON_LLM_API_KEY",
    }}
    env["OPTICYCLE_IGNORE_DOTENV"] = "1"
    root = Path(__file__).resolve().parents[1]
    ran = subprocess.run(
        [sys.executable, str(root / "scripts" / "run-open-session.py")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(root),
    )
    assert ran.returncode == 0
    assert "missing ALPACA" in ran.stdout
