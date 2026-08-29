# Opticycle

Autonomous options trader for the Alpaca AI Trading Agents Hackathon.

Opticycle runs an unattended paper cycle: ThesisAgent (LLM) chooses `BULLISH` / `BEARISH` / `NO_TRADE` from live snapshot evidence, binds a SPY defined-risk credit vertical, applies $100k book risk gates (position size, daily trades, buying power, portfolio greeks), and places **option** orders through **official Alpaca MCP Server 2.3.0** (`place_option_order`, `order_class=mleg`) only. Stock-only orders are rejected. There is no CLI execution channel. Without an LLM key the live path is fail-closed.

## Quick start (dry-run, no keys)

```bash
python3 -m pip install -r requirements-hackathon.txt
PYTHONPATH=vendor/pin-31374551:src python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run
PYTHONPATH=vendor/pin-31374551:src python3 scripts/verify-paper-mcp-order.py --dry-run
PYTHONPATH=vendor/pin-31374551:src python3 -m pytest tests/ -q
```

Keyless dry-run uses a fixture SPY vertical and does not spawn MCP or submit. It is not a live ThesisAgent call and not a fill.

Live paper orders use local environment variables only (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, and an LLM key such as `OPENAI_API_KEY`). Never commit secrets. Paper mode stays on (`ALPACA_PAPER_TRADE=true`, `ALPACA_LIVE_TRADE` must not be `true`). `scripts/verify-paper-mcp-order.py` is `--dry-run` in CI; omit `--dry-run` only when those env vars are set locally.

## Product behavior

1. Load the hackathon profile (`starting_capital=100000`, `require_options=true`, `execution_backend=mcp`, `agent_mode=llm`).
2. Observe the underlying and option chain (live IEX on the live path; fixture market on keyless dry-run).
3. ThesisAgent chooses stance from that evidence. Fail-closed without an LLM key. Credit type binds later (BULLISH=bull put, BEARISH=bear call).
4. Evaluate risk gates, including greeks when real inputs exist.
5. Submit via MCP tool `place_option_order` (`order_class=mleg`) only.
6. Append decision, gate, and order records to `data/journal.jsonl`.

No demo video is committed in this packet. Remotion demo is Gate 12.

Paper account ID is recorded in `docs/ALPACA_ACCOUNT.md` (ID only).

## Public evidence

Judge packet (sanitized ledger only): `artifacts/evidence/index.html`. Live MLEG/fill claims are incomplete.

## License

MIT. See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
