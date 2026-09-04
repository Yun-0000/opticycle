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
from datetime import date, datetime, timezone
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
TARGET_DTE = 5
RATE = 0.04
SIGNAL_THRESHOLD = 0.005
SLIPPAGE_PER_LEG = 0.02
IV_PREMIUM_MULTIPLIER = 1.20
TAKE_PROFIT_FRACTION = 0.50
STOP_LOSS_MULTIPLE = 2.0
FORCE_CLOSE_DTE = 1


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


def _realized_volatility(prior_closes: np.ndarray) -> float:
    log_returns = np.diff(np.log(prior_closes))
    realized = float(np.std(log_returns, ddof=1) * math.sqrt(252))
    return min(max(realized, 0.10), 0.60)


def _spread_value(
    kind: str,
    spot: float,
    short: float,
    long: float,
    years: float,
    volatility: float,
) -> float:
    short_price = _bs_price(kind, spot, short, years, volatility)
    long_price = _bs_price(kind, spot, long, years, volatility)
    return max(short_price - long_price, 0.0)


def _choose_expiry_index(dates: list[date], entry_index: int) -> int | None:
    candidates = [
        i
        for i in range(entry_index + 1, len(dates))
        if 3 <= (dates[i] - dates[entry_index]).days <= 10
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda i: (abs((dates[i] - dates[entry_index]).days - TARGET_DTE), i),
    )


def walk_forward(
    bars: list[dict[str, Any]],
    *,
    iv_premium_multiplier: float = IV_PREMIUM_MULTIPLIER,
) -> dict[str, Any]:
    ordered = sorted(bars, key=_bar_date)
    dates = [_bar_date(row) for row in ordered]
    closes = np.asarray([float(row["c"]) for row in ordered], dtype=float)
    equity = STARTING_EQUITY
    equity_points = [{"date": dates[59].isoformat(), "equity": equity}]
    trades: list[dict[str, Any]] = []
    cursor = 60
    while cursor < len(ordered) - 3:
        history = closes[cursor - 20 : cursor]
        realized_volatility = _realized_volatility(history)
        implied_volatility = min(realized_volatility * iv_premium_multiplier, 0.90)
        trailing_return = float(history[-1] / history[0] - 1)
        if trailing_return > SIGNAL_THRESHOLD:
            stance, kind = "BULLISH", "put"
        elif trailing_return < -SIGNAL_THRESHOLD:
            stance, kind = "BEARISH", "call"
        else:
            cursor += 1
            continue

        entry_date = dates[cursor]
        expiry_index = _choose_expiry_index(dates, cursor)
        if expiry_index is None:
            break
        expiry_date = dates[expiry_index]
        dte = (expiry_date - entry_date).days
        years = dte / 365
        spot = float(closes[cursor])
        short = _short_strike(kind, spot, years, implied_volatility)
        long = short - WIDTH if kind == "put" else short + WIDTH
        credit = max(
            _spread_value(kind, spot, short, long, years, implied_volatility)
            - 2 * SLIPPAGE_PER_LEG,
            0.01,
        )
        max_loss_per_contract = max((WIDTH - credit) * 100, 1.0)
        qty = min(MAX_CONTRACTS, int((equity * RISK_PER_VERTICAL) // max_loss_per_contract))
        if qty < 1:
            cursor += 1
            continue

        take_profit_debit = credit * (1 - TAKE_PROFIT_FRACTION)
        stop_loss_debit = min(credit * STOP_LOSS_MULTIPLE, WIDTH)
        exit_index = expiry_index
        exit_reason = "DTE_FORCE_CLOSE"
        exit_debit = WIDTH
        exit_iv = implied_volatility
        exit_spot = float(closes[expiry_index])
        for mark_index in range(cursor + 1, expiry_index + 1):
            remaining_dte = (expiry_date - dates[mark_index]).days
            mark_history = closes[max(0, mark_index - 20) : mark_index]
            if len(mark_history) < 20:
                continue
            mark_realized = _realized_volatility(mark_history)
            mark_iv = min(mark_realized * iv_premium_multiplier, 0.90)
            mark_years = max(remaining_dte, 1) / 365
            row = ordered[mark_index]
            adverse_spot = float(row["l"] if kind == "put" else row["h"])
            favorable_spot = float(row["h"] if kind == "put" else row["l"])
            adverse_debit = _spread_value(
                kind, adverse_spot, short, long, mark_years, mark_iv
            ) + 2 * SLIPPAGE_PER_LEG
            favorable_debit = _spread_value(
                kind, favorable_spot, short, long, mark_years, mark_iv
            ) + 2 * SLIPPAGE_PER_LEG
            stop_hit = adverse_debit >= stop_loss_debit
            take_profit_hit = favorable_debit <= take_profit_debit

            exit_index = mark_index
            exit_iv = mark_iv
            exit_spot = float(row["c"])
            if remaining_dte <= FORCE_CLOSE_DTE:
                exit_reason = "DTE_FORCE_CLOSE"
                exit_debit = min(
                    _spread_value(kind, exit_spot, short, long, mark_years, mark_iv)
                    + 2 * SLIPPAGE_PER_LEG,
                    WIDTH,
                )
                break
            if stop_hit:
                # Daily bars cannot reveal trigger order. When both thresholds are
                # touched, use the loss first so the model cannot benefit from ambiguity.
                exit_reason = "STOP_LOSS_2X_CREDIT"
                exit_debit = stop_loss_debit
                break
            if take_profit_hit:
                exit_reason = "TAKE_PROFIT_50_PERCENT"
                exit_debit = take_profit_debit
                break

        pnl = (credit - exit_debit) * 100 * qty
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
                "realized_volatility_20d": round(realized_volatility, 6),
                "entry_implied_volatility": round(implied_volatility, 6),
                "exit_implied_volatility": round(exit_iv, 6),
                "iv_premium_multiplier": iv_premium_multiplier,
                "trailing_return_20d": round(trailing_return, 6),
                "modeled_credit": round(credit, 4),
                "modeled_exit_debit": round(exit_debit, 4),
                "exit_reason": exit_reason,
                "holding_calendar_days": (dates[exit_index] - entry_date).days,
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
    benchmark_base_spot = float(closes[59])
    benchmark_points = [
        {
            "date": row["date"],
            "equity": round(STARTING_EQUITY * float(closes[dates.index(date.fromisoformat(row["date"]))]) / benchmark_base_spot, 2),
        }
        for row in equity_points
    ]
    return {
        "schema": "opticycle.modeled-walk-forward.v2",
        "label": "MODELED — NOT BROKER P&L",
        "source": "Alpaca Market Data API IEX daily bars",
        "feed": "iex",
        "method": {
            "walk_forward": "rolling-origin; every decision uses only the preceding 20 closes",
            "signal": "20-day close return above +0.5% bullish, below -0.5% bearish, otherwise abstain",
            "pricing": f"Black-Scholes European price with prior-only 20-day realized volatility multiplied by a fixed {iv_premium_multiplier:.2f} IV/RV premium assumption",
            "structure": "3-10 calendar DTE window with a fixed 5-day target, exact $5 width, 0.25 absolute short delta",
            "lifecycle": "daily OHLC trigger proxy; 50% credit-capture take-profit, 2x-credit stop, and <=1 DTE force-close; stop wins same-bar ambiguity",
            "sizing": "2% equity max-loss budget, maximum 4 contracts, one vertical at a time",
            "costs": "$0.02 modeled slippage per leg embedded in entry credit and exit trigger/debit marks; commissions and regulatory fees excluded",
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
        "trades": trades,
        "limitations": [
            "Modeled option prices are not historical option-chain quotes or fills.",
            f"The fixed {iv_premium_multiplier:.2f} IV/RV multiplier is a disclosed volatility-risk-premium assumption, not a fitted historical IV series.",
            "Daily OHLC cannot establish intraday trigger order; same-bar take-profit/stop ambiguity is resolved conservatively as a stop.",
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
    fig.patch.set_facecolor("#0b0e12")
    ax.set_facecolor("#0b0e12")
    ax.step(
        agent_dates,
        agent_values,
        where="post",
        color="#cab16a",
        linewidth=2.5,
        label="Modeled realized vertical equity",
    )
    ax.plot(agent_dates, benchmark_values, color="#818284", linewidth=1.8, linestyle="--", label="SPY close benchmark")
    ax.axhline(STARTING_EQUITY, color="#434547", linewidth=1, linestyle=":")
    ax.set_title("Modeled walk-forward equity", loc="left", fontsize=19, fontweight="normal", color="#dedede", pad=23)
    ax.text(
        0,
        1.02,
        "SPY IEX daily • 3–10 DTE • 0.25Δ • $5 width • TP/SL lifecycle • IV=1.20×RV",
        transform=ax.transAxes,
        color="#818284",
        fontsize=9.5,
    )
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"${value:,.0f}"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="y", color="#303235", linewidth=0.9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#303235")
    ax.tick_params(colors="#818284")
    legend = ax.legend(frameon=False, loc="upper left", ncol=2)
    for label in legend.get_texts():
        label.set_color("#bababb")
    fig.text(0.99, 0.015, "MODELED — NOT BROKER P&L", ha="right", color="#cab16a", fontsize=9, fontweight="bold")
    fig.subplots_adjust(left=0.10, right=0.97, top=0.80, bottom=0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def render_one_page(result: dict[str, Any], path: Path) -> None:
    metrics = result["metrics"]
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in result["limitations"])
    sensitivity = "".join(
        f"<tr><td>{float(row['iv_rv_multiplier']):.2f}×</td><td>{float(row['total_return_pct']):+.2f}%</td><td>{float(row['profit_factor']):.3f}</td><td>{float(row['max_drawdown_pct']):.2f}%</td></tr>"
        for row in result.get("sensitivity", [])
    )
    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>Opticycle modeled walk-forward</title><style>
:root{{--carbon:#0b0e12;--graphite:#1f2124;--slate:#303235;--ash:#818284;--platinum:#bababb;--snow:#dedede;--amber:#cab16a}}*{{box-sizing:border-box}}body{{font-family:Inter,ui-sans-serif,system-ui;max-width:1120px;margin:0 auto;padding:48px 32px 72px;color:var(--platinum);background:var(--carbon);background-image:linear-gradient(var(--graphite) 1px,transparent 1px),linear-gradient(90deg,var(--graphite) 1px,transparent 1px);background-size:32px 32px}}main{{background:var(--carbon);border:1px solid var(--slate);padding:32px}}h1{{font-size:44px;font-weight:400;letter-spacing:-.035em;line-height:1.05;margin:.5em 0}}h2{{color:var(--snow);font-size:20px;font-weight:400}}.flag{{display:inline-block;color:var(--carbon);background:var(--amber);padding:7px 10px;font:700 12px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.08em}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--slate);border:1px solid var(--slate);margin:24px 0}}.kpi{{background:var(--graphite);padding:16px}}.kpi small{{color:var(--ash);font:12px ui-monospace,SFMono-Regular,Menlo,monospace;text-transform:uppercase}}.kpi strong{{display:block;color:var(--snow);font-size:26px;font-weight:400;margin-top:8px}}img{{display:block;width:100%;height:auto;border:1px solid var(--slate)}}.two{{display:grid;grid-template-columns:1.4fr 1fr;gap:32px;margin-top:28px}}table{{border-collapse:collapse;width:100%;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}}td,th{{border-bottom:1px solid var(--slate);padding:9px;text-align:left}}th{{color:var(--amber);font-weight:400}}p,li{{line-height:1.55;color:var(--ash)}}b,code{{color:var(--platinum)}}code{{font-size:.9em}}@media(max-width:760px){{body{{padding:16px}}main{{padding:20px}}.grid,.two{{grid-template-columns:1fr 1fr}}}}@media print{{body{{padding:0;font-size:10px}}main{{border:0}}h1{{font-size:28px}}}}
</style></head><body><main><div class='flag'>MODELED — NOT BROKER P&amp;L</div><h1>SPY vertical walk-forward</h1><p>Rolling-origin test using Alpaca IEX daily stock bars. Every decision uses only prior observations; options are priced with Black-Scholes.</p>
<div class='grid'><div class='kpi'><small>Total return</small><strong>{metrics['total_return_pct']:+.2f}%</strong></div><div class='kpi'><small>Trades</small><strong>{metrics['trades']}</strong></div><div class='kpi'><small>Win rate</small><strong>{metrics['win_rate_pct']:.1f}%</strong></div><div class='kpi'><small>Max drawdown</small><strong>{metrics['max_drawdown_pct']:.2f}%</strong></div></div>
<img src='walk-forward-backtest.png' alt='Modeled walk-forward equity compared with SPY close benchmark'>
<div class='two'><section><h2>Method</h2><ul>{''.join(f'<li><b>{html.escape(k)}</b>: {html.escape(v)}</li>' for k,v in result['method'].items())}</ul></section><section><h2>VRP sensitivity</h2><table><thead><tr><th>IV/RV</th><th>Return</th><th>PF</th><th>Max DD</th></tr></thead><tbody>{sensitivity}</tbody></table></section></div>
<h2>Limitations</h2><ul>{limitations}</ul><p><small>Source: {html.escape(result['source'])}, feed={result['feed']}; range {result['date_range']['start']} to {result['date_range']['end']}. Reproduce with <code>scripts/build-walk-forward-backtest.py</code>. Dataset SHA-256: {result['bars_sha256']}</small></p></main></body></html>"""
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
    result["sensitivity"] = [
        {
            "iv_rv_multiplier": multiplier,
            "total_return_pct": sensitivity_result["metrics"]["total_return_pct"],
            "profit_factor": sensitivity_result["metrics"]["profit_factor"],
            "max_drawdown_pct": sensitivity_result["metrics"]["max_drawdown_pct"],
        }
        for multiplier in (1.10, 1.20, 1.30)
        for sensitivity_result in (walk_forward(bars, iv_premium_multiplier=multiplier),)
    ]
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
