#!/usr/bin/env python3
"""Fetch Alpaca portfolio history and render an honest, annotated equity chart."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_URL = "https://paper-api.alpaca.markets/v2/account"
HISTORY_URL = "https://paper-api.alpaca.markets/v2/account/portfolio/history"
DESIGNATED_ACCOUNT = "PA3V84C40PJQ"
IEX_BARS_PATH = ROOT / "artifacts" / "evidence" / "walk-forward-iex-bars.json"


def _request(url: str) -> tuple[int, dict]:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        raise RuntimeError("paper credentials missing")
    request = urllib.request.Request(
        url,
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def normalize_history_points(history: dict) -> list[dict[str, float | int]]:
    """Pair timestamps/equity and remove Alpaca's leading zero placeholders."""
    raw = zip(history.get("timestamp") or [], history.get("equity") or [])
    points: list[dict[str, float | int]] = []
    for timestamp, equity in raw:
        if timestamp is None or equity is None:
            continue
        parsed = float(equity)
        if parsed <= 0:
            continue
        points.append({"timestamp": int(timestamp), "equity": parsed})
    return points


def render_equity_png(points: list[dict[str, float | int]], path: Path) -> None:
    """Render the observed broker points; never interpolate missing account days."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    dates = [datetime.fromtimestamp(int(row["timestamp"]), timezone.utc) for row in points]
    values = [float(row["equity"]) for row in points]
    start, end = values[0], values[-1]
    change = end - start

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(12, 5.4), dpi=160)
    fig.patch.set_facecolor("#0b0e12")
    ax.set_facecolor("#0b0e12")
    ax.scatter(dates, values, color="#00d892", s=58, zorder=3)
    ax.axhline(start, color="#434547", linewidth=1.2, linestyle=(0, (4, 4)), zorder=1)
    ax.text(dates[0], start, f"  Start ${start:,.2f}", color="#a3a4a5", va="bottom")
    ax.annotate(
        f"End ${end:,.2f}\nNet {change:+,.2f}",
        xy=(dates[-1], end),
        xytext=(-12, 26 if change >= 0 else -42),
        textcoords="offset points",
        ha="right",
        va="bottom" if change >= 0 else "top",
        color="#dedede",
        fontweight="normal",
        bbox={"boxstyle": "square,pad=0.42", "facecolor": "#002923", "edgecolor": "#00d892"},
        arrowprops={"arrowstyle": "-", "color": "#00d892"},
    )
    ax.set_title("Alpaca paper equity observations", loc="left", fontsize=20, fontweight="normal", color="#dedede", pad=24)
    ax.text(
        0,
        1.02,
        f"{len(points)} observed broker points • {dates[0]:%b %d}–{dates[-1]:%b %d, %Y} • no fabricated values between dates",
        transform=ax.transAxes,
        color="#818284",
        fontsize=10,
    )
    ax.set_ylabel("Account equity (USD)", color="#a3a4a5")
    ax.set_xlabel("Broker date (UTC)", color="#a3a4a5", labelpad=10)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"${value:,.0f}"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.grid(axis="y", color="#303235", linewidth=0.9)
    ax.grid(axis="x", visible=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#303235")
    ax.tick_params(colors="#818284")
    spread = max(values) - min(values)
    padding = max(spread * 0.8, 15)
    ax.set_ylim(min(values) - padding, max(values) + padding)
    fig.text(
        0.99,
        0.015,
        "Source: Alpaca GET /v2/account/portfolio/history • Paper account PA3V84C40PJQ",
        ha="right",
        color="#5d5e61",
        fontsize=8.5,
    )
    fig.subplots_adjust(left=0.11, right=0.97, top=0.82, bottom=0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def build_same_period_comparison(
    points: list[dict[str, float | int]], bars_payload: dict
) -> dict[str, object]:
    """Compare account equity and SPY only across dates observed by both sources."""
    equity_by_date = {
        datetime.fromtimestamp(int(row["timestamp"]), timezone.utc).date().isoformat(): float(row["equity"])
        for row in points
    }
    spy_by_date = {
        str(row["t"])[:10]: float(row["c"])
        for row in (bars_payload.get("bars") or [])
        if row.get("t") and row.get("c") is not None
    }
    common_dates = sorted(set(equity_by_date) & set(spy_by_date))
    if len(common_dates) < 2:
        raise ValueError("fewer than two shared Opticycle/SPY observation dates")
    start_date, end_date = common_dates[0], common_dates[-1]
    account_start, account_end = equity_by_date[start_date], equity_by_date[end_date]
    spy_start, spy_end = spy_by_date[start_date], spy_by_date[end_date]
    return {
        "schema": "opticycle.same-period-benchmark.v1",
        "period": {"start": start_date, "end": end_date},
        "shared_observation_dates": common_dates,
        "opticycle": {
            "source": "Alpaca GET /v2/account/portfolio/history",
            "start": account_start,
            "end": account_end,
            "return_pct": round((account_end / account_start - 1) * 100, 4),
        },
        "spy": {
            "source": "Alpaca IEX daily bars",
            "start": spy_start,
            "end": spy_end,
            "return_pct": round((spy_end / spy_start - 1) * 100, 4),
        },
        "note": "Exact shared dates only; no interpolation across missing account days.",
    }


def render_same_period_comparison(comparison: dict[str, object], path: Path) -> None:
    """Render a compact return comparison; two endpoints do not imply a time-series curve."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    opticycle = dict(comparison["opticycle"])
    spy = dict(comparison["spy"])
    values = [float(opticycle["return_pct"]), float(spy["return_pct"])]
    colors = ["#00d892", "#818284"]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(10.5, 4.7), dpi=160)
    fig.patch.set_facecolor("#0b0e12")
    ax.set_facecolor("#0b0e12")
    bars = ax.barh(["Opticycle", "SPY"], values, color=colors, height=0.5)
    ax.axvline(0, color="#dedede", linewidth=1)
    for bar, value in zip(bars, values):
        ax.text(
            value + (0.025 if value >= 0 else -0.025),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.3f}%",
            va="center",
            ha="left" if value >= 0 else "right",
            color="#dedede",
            fontsize=13,
        )
    period = dict(comparison["period"])
    ax.set_title("Observed account return vs SPY", loc="left", fontsize=20, color="#dedede", pad=23)
    ax.text(
        0,
        1.02,
        f"Exact shared dates {period['start']} to {period['end']} • no interpolation",
        transform=ax.transAxes,
        color="#818284",
        fontsize=10,
    )
    ax.set_xlabel("Return over shared observation window", color="#a3a4a5", labelpad=10)
    ax.grid(axis="x", color="#303235", linewidth=0.9)
    ax.grid(axis="y", visible=False)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#303235")
    ax.tick_params(colors="#a3a4a5")
    low, high = min(values + [0.0]), max(values + [0.0])
    pad = max((high - low) * 0.28, 0.12)
    ax.set_xlim(low - pad, high + pad)
    fig.text(
        0.99,
        0.015,
        "Sources: Alpaca portfolio history + Alpaca IEX daily bars • Paper account PA3V84C40PJQ",
        ha="right",
        color="#5d5e61",
        fontsize=8.5,
    )
    fig.subplots_adjust(left=0.16, right=0.94, top=0.8, bottom=0.2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="1M")
    parser.add_argument("--timeframe", default="1D")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "artifacts" / "evidence")
    args = parser.parse_args(argv)
    query = urllib.parse.urlencode(
        {"period": args.period, "timeframe": args.timeframe, "extended_hours": "false"}
    )
    try:
        account_status, account = _request(ACCOUNT_URL)
        history_status, history = _request(f"{HISTORY_URL}?{query}")
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        reason = type(exc).__name__ if not isinstance(exc, RuntimeError) else str(exc)
        print(json.dumps({"ok": False, "reason": reason}))
        return 1
    account_id = str(account.get("account_number") or account.get("id") or "")
    points = normalize_history_points(history)
    if account_status != 200 or history_status != 200 or account_id != DESIGNATED_ACCOUNT or len(points) < 2:
        print(json.dumps({"ok": False, "reason": "account/history verification failed"}))
        return 1
    equities = [float(row["equity"]) for row in points]
    payload = {
        "schema": "opticycle.portfolio-history.v2",
        "source": "GET /v2/account/portfolio/history",
        "http_status": history_status,
        "account_id": account_id,
        "period": args.period,
        "timeframe": args.timeframe,
        "points": points,
        "observed_points": len(points),
        "zero_placeholders_removed": len(history.get("equity") or []) - len(points),
        "start_equity": equities[0],
        "end_equity": equities[-1],
        "net_change": round(equities[-1] - equities[0], 2),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "portfolio_history.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    render_equity_png(points, args.out_dir / "equity-curve.png")
    comparison_written = False
    if IEX_BARS_PATH.is_file():
        comparison = build_same_period_comparison(
            points, json.loads(IEX_BARS_PATH.read_text(encoding="utf-8"))
        )
        (args.out_dir / "equity-vs-spy.json").write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        render_same_period_comparison(comparison, args.out_dir / "equity-vs-spy.png")
        comparison_written = True
    print(json.dumps({"ok": True, "http_status": history_status, "points": len(points), "net_change": payload["net_change"], "benchmark": comparison_written}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
