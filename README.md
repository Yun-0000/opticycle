# Opticycle

Autonomous options trader for the Alpaca AI Trading Agents Hackathon.

Opticycle runs an unattended paper cycle: it selects a wheel cash-secured put or a vertical put credit spread, applies $100k book risk gates (position size, daily trades, buying power, portfolio delta/vega), and places **option** orders through **Alpaca MCP Server 2.3.0** (primary) or the official **Alpaca CLI** (fallback). Stock-only orders are rejected.

## Quick start (dry-run, no keys)

```bash
python3 -m pip install -r requirements-hackathon.txt
PYTHONPATH=vendor/pin-31374551:src python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run
PYTHONPATH=vendor/pin-31374551:src python3 scripts/verify-paper-mcp-order.py --dry-run
PYTHONPATH=vendor/pin-31374551:src python3 -m pytest tests/ -q
```

Live paper orders use local environment variables only (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`). Never commit secrets. Paper mode stays on (`ALPACA_PAPER_TRADE=true`, `ALPACA_LIVE_TRADE` must not be `true`). `scripts/verify-paper-mcp-order.py` is `--dry-run` in CI; omit `--dry-run` only when those env vars are set locally.

## Product behavior

1. Load the hackathon profile (`starting_capital=100000`, `require_options=true`, `execution_backend=mcp`).
2. Build an options structure (`wheel` or `vertical_spread`) from `vendor/pin-31374551/src/strategy/option/` on the watchlist underlying (default SPY).
3. Evaluate risk gates, including vollib Black-Scholes greeks.
4. Submit via MCP tool `place_option_order`, or `alpaca order submit` if `--backend cli`.
5. Append decision, gate, and order records to `data/journal.jsonl`.

Official demo video (Remotion, not a screen recording): `artifacts/demo.mp4`. Shot list: `docs/DEMO_SHOTLIST.md`.

Paper account ID is recorded in `docs/ALPACA_ACCOUNT.md` (ID only).

## License

MIT. See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
