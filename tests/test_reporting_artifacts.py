from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


equity_script = _load("build_equity_curve", ROOT / "scripts" / "build-equity-curve.py")
backtest_script = _load(
    "build_walk_forward_backtest", ROOT / "scripts" / "build-walk-forward-backtest.py"
)


def test_equity_history_removes_zero_placeholders() -> None:
    points = equity_script.normalize_history_points(
        {"timestamp": [1, 2, 3, 4], "equity": [0, "0", "100000", "100026.77"]}
    )
    assert points == [
        {"timestamp": 3, "equity": 100000.0},
        {"timestamp": 4, "equity": 100026.77},
    ]


def _modeled_bars(count: int = 240) -> list[dict[str, object]]:
    start = datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    business_day = 0
    cursor = start
    while len(rows) < count:
        if cursor.weekday() < 5:
            close = 470 * math.exp(0.0007 * business_day + 0.025 * math.sin(business_day / 9))
            rows.append(
                {
                    "t": cursor.isoformat().replace("+00:00", "Z"),
                    "o": close * 0.998,
                    "h": close * 1.006,
                    "l": close * 0.994,
                    "c": close,
                    "v": 1_000_000,
                }
            )
            business_day += 1
        cursor += timedelta(days=1)
    return rows


def test_walk_forward_is_prior_only_exact_width_and_risk_bounded() -> None:
    result = backtest_script.walk_forward(_modeled_bars())
    assert result["label"] == "MODELED — NOT BROKER P&L"
    assert result["feed"] == "iex"
    assert result["metrics"]["trades"] > 5
    for trade in result["trades"]:
        assert trade["signal_lookback_end"] < trade["entry_date"]
        assert 7 <= trade["dte"] <= 10
        assert trade["width"] == 5.0
        assert trade["target_short_delta"] == 0.25
        assert 1 <= trade["qty"] <= 4
        assert trade["max_loss"] <= trade["equity_before"] * 0.020001
        assert abs(trade["short_strike"] - trade["long_strike"]) == 5.0


def test_walk_forward_section_separates_modeled_result_from_broker_pnl(
    tmp_path: Path, monkeypatch,
) -> None:
    from opticycle import evidence_public

    result = backtest_script.walk_forward(_modeled_bars())
    path = tmp_path / "walk-forward-backtest.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setattr(evidence_public, "WALK_FORWARD_JSON_PATH", path)
    rendered = evidence_public.modeled_walk_forward_section()
    assert "Modeled walk-forward — not broker P&amp;L" in rendered
    assert "research context, not historical option fills or broker performance" in rendered
    assert f"{result['metrics']['total_return_pct']:+.2f}%" in rendered
