#!/usr/bin/env python3
"""Build a one-page modeled SPY vertical walk-forward from Alpaca IEX daily bars."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
DATA_URL = "https://data.alpaca.markets/v2/stocks/SPY/bars"
STARTING_EQUITY = 100_000.0
RISK_PER_VERTICAL = 0.02
MAX_CONTRACTS = 4
WIDTH = 5.0
TARGET_DELTA = 0.25
TARGET_DTE = 7
RATE = 0.04
SIGNAL_THRESHOLD = 0.005
SLIPPAGE_PER_LEG = 0.02


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def fetch_iex_bars(start: str, end: str) -> list[dict[str, Any]]:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        raise RuntimeError("paper credentials missing")
    rows: list[dict[str, Any]] = []
    token = ""
    while True:
        query = {
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "limit": "10000",
            "adjustment": "all",
            "feed": "iex",
            "sort": "asc",
        }
        if token:
            query["page_token"] = token
        request = urllib.request.Request(
            f"{DATA_URL}?{urllib.parse.urlencode(query)}",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        rows.extend(body.get("bars") or [])
        token = str(body.get("next_page_token") or "")
        if not token:
            break
    if len(rows) < 90:
        raise RuntimeError("insufficient IEX daily bars for walk-forward")
    return rows


def _bar_date(row: dict[str, Any]) -> date:
    return datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00")).date()


def _bs_price(kind: str, spot: float, strike: float, years: float, volatility: float) -> float:
    years = max(years, 1 / 365)
    volatility = max(volatility, 0.01)
    d1 = (math.log(spot / strike) + (RATE + 0.5 * volatility**2) * years) / (
        volatility * math.sqrt(years)
    )
    d2 = d1 - volatility * math.sqrt(years)
    discount = math.exp(-RATE * years)
    if kind == "call":
        return spot * norm.cdf(d1) - strike * discount * norm.cdf(d2)
    return strike * discount * norm.cdf(-d2) - spot * norm.cdf(-d1)


def _short_strike(kind: str, spot: float, years: float, volatility: float) -> float:
    target_d1 = norm.ppf(1 - TARGET_DELTA) if kind == "put" else norm.ppf(TARGET_DELTA)
    exponent = target_d1 * volatility * math.sqrt(years) - (RATE + 0.5 * volatility**2) * years
    return float(round(spot / math.exp(exponent)))


def _intrinsic(kind: str, spot: float, strike: float) -> float:
    return max(strike - spot, 0.0) if kind == "put" else max(spot - strike, 0.0)


def walk_forward(bars: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(bars, key=_bar_date)
    dates = [_bar_date(row) for row in ordered]
    closes = np.asarray([float(row["c"]) for row in ordered], dtype=float)
    equity = STARTING_EQUITY
    equity_points = [{"date": dates[59].isoformat(), "equity": equity}]
    trades: list[dict[str, Any]] = []
    cursor = 60
    while cursor < len(ordered) - 3:
        history = closes[cursor - 20 : cursor]
        log_returns = np.diff(np.log(history))
        volatility = float(np.std(log_returns, ddof=1) * math.sqrt(252))
        volatility = min(max(volatility, 0.10), 0.60)
        trailing_return = float(history[-1] / history[0] - 1)
        if trailing_return > SIGNAL_THRESHOLD:
            stance, kind = "BULLISH", "put"
        elif trailing_return < -SIGNAL_THRESHOLD:
            stance, kind = "BEARISH", "call"
        else:
            cursor += 1
            continue

        entry_date = dates[cursor]
        target_expiry = entry_date + timedelta(days=TARGET_DTE)
        exit_index = next((i for i in range(cursor + 1, len(dates)) if dates[i] >= target_expiry), None)
        if exit_index is None or (dates[exit_index] - entry_date).days > 10:
            break
        dte = (dates[exit_index] - entry_date).days
        years = dte / 365
        spot = float(closes[cursor])
        short = _short_strike(kind, spot, years, volatility)
        long = short - WIDTH if kind == "put" else short + WIDTH
        short_price = _bs_price(kind, spot, short, years, volatility)
        long_price = _bs_price(kind, spot, long, years, volatility)
        credit = max(short_price - long_price - 2 * SLIPPAGE_PER_LEG, 0.01)
        max_loss_per_contract = max((WIDTH - credit) * 100, 1.0)
        qty = min(MAX_CONTRACTS, int((equity * RISK_PER_VERTICAL) // max_loss_per_contract))
        if qty < 1:
            cursor = exit_index + 1
            continue
        exit_spot = float(closes[exit_index])
        settlement = _intrinsic(kind, exit_spot, short) - _intrinsic(kind, exit_spot, long)
        pnl = (credit - settlement) * 100 * qty
        before = equity
        equity += pnl
        trades.append(
            {
                "entry_date": entry_date.isoformat(),
                "exit_date": dates[exit_index].isoformat(),
                "signal_lookback_end": dates[cursor - 1].isoformat(),
                "stance": stance,
                "kind": kind,
                "dte": dte,
                "spot": round(spot, 4),
                "exit_spot": round(exit_spot, 4),
                "short_strike": short,
                "long_strike": long,
                "width": WIDTH,
                "target_short_delta": TARGET_DELTA,
                "realized_volatility_20d": round(volatility, 6),
                "trailing_return_20d": round(trailing_return, 6),
                "modeled_credit": round(credit, 4),
                "qty": qty,
                "max_loss": round(max_loss_per_contract * qty, 2),
                "equity_before": round(before, 2),
                "pnl": round(pnl, 2),
                "equity_after": round(equity, 2),
            }
        )
        equity_points.append({"date": dates[exit_index].isoformat(), "equity": round(equity, 2)})
        cursor = exit_index + 1

    if not trades:
        raise RuntimeError("walk-forward produced no trades")
    wins = [row for row in trades if row["pnl"] > 0]
    losses = [row for row in trades if row["pnl"] < 0]
    equity_values = [float(row["equity"]) for row in equity_points]
    peaks = np.maximum.accumulate(equity_values)
    drawdowns = [(value / peak) - 1 for value, peak in zip(equity_values, peaks)]
    gross_profit = sum(float(row["pnl"]) for row in wins)
    gross_loss = abs(sum(float(row["pnl"]) for row in losses))
    folds: dict[str, dict[str, float | int]] = {}
    for row in trades:
        year = str(row["exit_date"])[:4]
        fold = folds.setdefault(year, {"trades": 0, "pnl": 0.0})
        fold["trades"] = int(fold["trades"]) + 1
        fold["pnl"] = round(float(fold["pnl"]) + float(row["pnl"]), 2)
    benchmark_base_spot = float(closes[59])
    benchmark_points = [
        {
            "date": row["date"],
            "equity": round(STARTING_EQUITY * float(closes[dates.index(date.fromisoformat(row["date"]))]) / benchmark_base_spot, 2),
        }
        for row in equity_points
    ]
    return {
        "schema": "opticycle.modeled-walk-forward.v1",
        "label": "MODELED — NOT BROKER P&L",
        "source": "Alpaca Market Data API IEX daily bars",
        "feed": "iex",
        "method": {
            "walk_forward": "rolling-origin; every decision uses only the preceding 20 closes",
            "signal": "20-day close return above +0.5% bullish, below -0.5% bearish, otherwise abstain",
            "pricing": "Black-Scholes European price with rolling 20-day realized volatility",
            "structure": "7 calendar DTE target (actual 7-10), exact $5 width, 0.25 absolute short delta",
            "sizing": "2% equity max-loss budget, maximum 4 contracts, one vertical at a time",
            "costs": "$0.02 modeled slippage per leg; commissions and regulatory fees excluded",
        },
        "metrics": {
            "starting_equity": STARTING_EQUITY,
            "ending_equity": round(equity, 2),
            "total_return_pct": round((equity / STARTING_EQUITY - 1) * 100, 3),
            "trades": len(trades),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
            "max_drawdown_pct": round(min(drawdowns) * 100, 3),
            "profit_factor": None if gross_loss == 0 else round(gross_profit / gross_loss, 3),
            "average_pnl": round(sum(float(row["pnl"]) for row in trades) / len(trades), 2),
        },
        "date_range": {"start": dates[0].isoformat(), "end": dates[-1].isoformat()},
        "equity_points": equity_points,
        "benchmark_points": benchmark_points,
        "folds": folds,
        "trades": trades,
        "limitations": [
            "Modeled option prices are not historical option-chain quotes or fills.",
            "European Black-Scholes omits early assignment, discrete dividends, quote microstructure, and volatility skew.",
            "IEX daily bars are a stock-price source; this result is research context, not a performance claim.",
        ],
    }


def render_chart(result: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    agent_dates = [date.fromisoformat(row["date"]) for row in result["equity_points"]]
    agent_values = [float(row["equity"]) for row in result["equity_points"]]
    benchmark_values = [float(row["equity"]) for row in result["benchmark_points"]]
    fig, ax = plt.subplots(figsize=(12, 5.2), dpi=160)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")
    ax.step(
        agent_dates,
        agent_values,
        where="post",
        color="#2563eb",
        linewidth=2.5,
        label="Modeled realized vertical equity",
    )
    ax.plot(agent_dates, benchmark_values, color="#d97706", linewidth=1.8, linestyle="--", label="SPY close benchmark")
    ax.axhline(STARTING_EQUITY, color="#94a3b8", linewidth=1, linestyle=":")
    ax.set_title("Modeled walk-forward equity", loc="left", fontsize=19, fontweight="bold", color="#0f172a", pad=23)
    ax.text(
        0,
        1.02,
        "SPY IEX daily • prior-20d inputs • 7–10 DTE • 0.25Δ • $5 width • BS modeled prices",
        transform=ax.transAxes,
        color="#64748b",
        fontsize=9.5,
    )
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"${value:,.0f}"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#cbd5e1")
    ax.tick_params(colors="#64748b")
    ax.legend(frameon=False, loc="upper left", ncol=2)
    fig.text(0.99, 0.015, "MODELED — NOT BROKER P&L", ha="right", color="#b45309", fontsize=9, fontweight="bold")
    fig.subplots_adjust(left=0.10, right=0.97, top=0.80, bottom=0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def render_one_page(result: dict[str, Any], path: Path) -> None:
    metrics = result["metrics"]
    folds = "".join(
        f"<tr><td>{html.escape(year)}</td><td>{row['trades']}</td><td>${float(row['pnl']):+,.2f}</td></tr>"
        for year, row in result["folds"].items()
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in result["limitations"])
    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>Opticycle modeled walk-forward</title><style>
body{{font-family:Inter,ui-sans-serif,system-ui;max-width:1080px;margin:0 auto;padding:32px;color:#0f172a;background:#fff}}h1{{font-size:42px;letter-spacing:-.04em;margin:.2em 0}}.flag{{color:#92400e;background:#fffbeb;border:1px solid #fcd34d;padding:10px 14px;font-weight:800}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0}}.kpi{{border:1px solid #e2e8f0;padding:14px}}.kpi small{{color:#64748b}}.kpi strong{{display:block;font-size:24px;margin-top:5px}}img{{width:100%;height:auto}}.two{{display:grid;grid-template-columns:1.4fr 1fr;gap:24px}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left}}p,li{{line-height:1.45;color:#334155}}code{{font-size:.9em}}@media(max-width:760px){{.grid,.two{{grid-template-columns:1fr 1fr}}}}@media print{{body{{padding:0;font-size:10px}}h1{{font-size:28px}}}}
</style></head><body><div class='flag'>MODELED — NOT BROKER P&amp;L</div><h1>SPY vertical walk-forward</h1><p>Rolling-origin test using Alpaca IEX daily stock bars. Every decision uses only prior observations; options are priced with Black-Scholes.</p>
<div class='grid'><div class='kpi'><small>Total return</small><strong>{metrics['total_return_pct']:+.2f}%</strong></div><div class='kpi'><small>Trades</small><strong>{metrics['trades']}</strong></div><div class='kpi'><small>Win rate</small><strong>{metrics['win_rate_pct']:.1f}%</strong></div><div class='kpi'><small>Max drawdown</small><strong>{metrics['max_drawdown_pct']:.2f}%</strong></div></div>
<img src='walk-forward-backtest.png' alt='Modeled walk-forward equity compared with SPY close benchmark'>
<div class='two'><section><h2>Method</h2><ul>{''.join(f'<li><b>{html.escape(k)}</b>: {html.escape(v)}</li>' for k,v in result['method'].items())}</ul></section><section><h2>Calendar folds</h2><table><thead><tr><th>Exit year</th><th>Trades</th><th>Modeled P&amp;L</th></tr></thead><tbody>{folds}</tbody></table></section></div>
<h2>Limitations</h2><ul>{limitations}</ul><p><small>Source: {html.escape(result['source'])}, feed={result['feed']}; range {result['date_range']['start']} to {result['date_range']['end']}. Reproduce with <code>scripts/build-walk-forward-backtest.py</code>. Dataset SHA-256: {result['bars_sha256']}</small></p></body></html>"""
    path.write_text(page, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-01-01T00:00:00Z")
    parser.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    parser.add_argument("--bars-json", type=Path)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "artifacts" / "evidence")
    args = parser.parse_args(argv)
    bars = json.loads(args.bars_json.read_text(encoding="utf-8"))["bars"] if args.bars_json else fetch_iex_bars(args.start, args.end)
    result = walk_forward(bars)
    result["bars_sha256"] = hashlib.sha256(_canonical(bars).encode("utf-8")).hexdigest()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "walk-forward-iex-bars.json").write_text(
        json.dumps({"schema": "opticycle.iex-bars.v1", "source": result["source"], "feed": "iex", "bars": bars}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "walk-forward-backtest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    render_chart(result, args.out_dir / "walk-forward-backtest.png")
    render_one_page(result, args.out_dir / "walk-forward-backtest.html")
    print(json.dumps({"ok": True, **result["metrics"], "bars": len(bars), "label": result["label"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
