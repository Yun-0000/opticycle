"""Live/production modules must not import or describe CLI as an execution channel."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LIVE_MODULES = [
    ROOT / "src" / "opticycle" / "runner.py",
    ROOT / "src" / "opticycle" / "cli.py",
    ROOT / "src" / "opticycle" / "settings.py",
    ROOT / "src" / "opticycle" / "preflight.py",
    ROOT / "src" / "opticycle" / "__main__.py",
    ROOT / "src" / "opticycle" / "plans.py",
    ROOT / "src" / "opticycle" / "observe.py",
    ROOT / "src" / "opticycle" / "pin_option.py",
    ROOT / "src" / "trade" / "routing.py",
    ROOT / "src" / "trade" / "__init__.py",
]

FIXTURE_MARKERS = (
    "tests.fixtures",
    "tests/fixtures",
    "def _historical_bars",
    "def historical_bars",
    "def _chain_frame",
    "def chain_frame",
    "class _FixtureAlpaca",
    "class _PaperBook",
    "class _FixtureFred",
)

FORBIDDEN_IMPORTS = (
    "alpaca_cli_executor",
    "AlpacaCliExecutor",
    "trade.cli",
)

FORBIDDEN_TEXT = (
    "cli fallback",
    "cli (fallback)",
    "fallback execution",
    "or cli",
)


def test_live_modules_do_not_import_cli_executor() -> None:
    for path in LIVE_MODULES:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_IMPORTS:
            assert token not in text, f"{path} still references {token!r}"


def test_live_modules_do_not_call_cli_a_fallback() -> None:
    for path in LIVE_MODULES:
        lower = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_TEXT:
            assert token not in lower, f"{path} still contains {token!r}"


def test_cli_adapter_does_not_call_itself_fallback() -> None:
    path = ROOT / "src" / "trade" / "cli" / "alpaca_cli_executor.py"
    lower = path.read_text(encoding="utf-8").lower()
    assert "fallback" not in lower
    assert "not a live execution channel" in lower


def test_production_import_graph_cannot_reach_fixture_generators() -> None:
    production = list((ROOT / "src" / "opticycle").glob("*.py")) + list(
        (ROOT / "src" / "trade").rglob("*.py")
    )
    for path in production:
        text = path.read_text(encoding="utf-8")
        for token in FIXTURE_MARKERS:
            assert token not in text, f"{path} can reach fixture generator {token!r}"


def test_observe_never_submits_orders() -> None:
    text = (ROOT / "src" / "opticycle" / "observe.py").read_text(encoding="utf-8")
    assert "submit_order" not in text
    assert "close_position" not in text


def test_live_runner_does_not_call_dry_run_portfolio_on_live_branch() -> None:
    text = (ROOT / "src" / "opticycle" / "runner.py").read_text(encoding="utf-8")
    live_chunk = text.split("if not dry_run:", 1)[1].split("else:", 1)[0]
    assert "dry_run_portfolio" not in live_chunk
    assert "500.0" not in live_chunk
    assert "observe_live" in live_chunk
