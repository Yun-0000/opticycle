# Opticycle

Autonomous options trader for the Alpaca AI Trading Agents Hackathon.

Opticycle runs an unattended paper cycle: ThesisAgent (LLM) chooses `BULLISH` / `BEARISH` / `NO_TRADE` from live snapshot evidence when a key is present, binds a SPY defined-risk credit vertical, applies $100k book risk gates, and places **option** orders through **official Alpaca MCP Server 2.3.0** (`place_option_order`, `order_class=mleg`) only. Stock-only orders are rejected. There is no CLI execution channel. Without an LLM key the live path is fail-closed unless an explicit heuristic stance is recorded as such.

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
3. ThesisAgent chooses stance from that evidence when an LLM key is present. Fail-closed without a key unless a heuristic stance is recorded honestly. Credit type binds later (BULLISH=bull put, BEARISH=bear call).
4. Evaluate risk gates, including greeks when real inputs exist.
5. Submit via MCP tool `place_option_order` (`order_class=mleg`) only.
6. Append decision, gate, and order records to `data/journal.jsonl`.

## Monday paper broker fills

Two real Opticycle MCP MLEG paper fills, channel `live_paper`. Broker filled both. They are **not** price-bound `MATCHED`. Account id omitted.

Alpaca MLEG `limit_price` is signed: **positive = debit, negative = credit**. These two orders were submitted with a **positive** (debit) limit. Production now requires a negative credit limit and the reconciler uses `filled <= limit`. Under that rule a 2.11 credit fill is worse than a 2.54 credit bound, and a 0.51 credit fill is worse than a 0.70 credit bound (certificate max_loss $30 vs fill max_loss $49).

1. `oc-204a8dfccffd40c9` — BEARISH bear-call credit, SPY 2026-10-09 793C/809C, qty 1, submitted limit `+2.54`. Legs: sell `SPY261009C00793000` fill 2.95; buy `SPY261009C00809000` fill 0.84. Broker filled 2026-08-31 13:30:03Z, `filled_qty=1`, `filled_avg_price=-2.11`, Alpaca `order_id=abcb5385-0aa3-42cc-9b58-ef4200235c27`. Recon equity 100007.95, cash 100210.95. Outcome `FILLED`, not price-bound MATCHED.
2. `oc-715ad36a630d408e` — BEARISH bear-call, SPY 2026-09-25 768C/769C, qty 1, submitted limit `+0.70`, certificate max_loss 30. Legs: sell `SPY260925C00768000` fill 8.68; buy `SPY260925C00769000` fill 8.17. Filled 2026-08-31 14:05:49Z, `filled_qty=1`, `filled_avg_price=-0.51`, Alpaca `order_id=2a6d6b7c-caad-4c24-959a-8d93455a36fe`. MCP `place_option_order`, `mcp_submit_count=1`. **`stance_source=bars_heuristic_no_llm_key`**: no LLM key on the box — not a live ThesisAgent LLM pick. Fill max_loss $49.

After-hours 2026-08-31 Alpaca GET (account id omitted): both verticals still open; equity `100010.9`, cash `100261.9`, unrealized `+11`; identity `cash + long_mv + short_mv`. No exit / realized P&L. A live observation the same evening was genuine `NO_TRADE` (`SPY quote is stale`). ThesisAgent was not called on that stale quote even though an LLM key is now present.

No demo video is committed in this packet. Remotion demo is Gate 12.

Paper account ID is recorded in `docs/ALPACA_ACCOUNT.md` (ID only).

## Public evidence

Judge packet (sanitized ledger only): `artifacts/evidence/index.html`. The two live_paper fills are recorded as broker fills, not as price-bound MATCHED. Independent Alpaca GET-by-client_order_id receipts are in `artifacts/evidence/broker_lookup.json`.

## Foundation

Pinned MIT foundation: Gauss World Trader, https://github.com/Magica-Chen/GaussWorldTrader @ `31374551bae6fd34a0fe56fe11d208f4ff04fbb4`, snapshot `vendor/pin-31374551/`. See `FOUNDATION.md` and `THIRD_PARTY_NOTICES.md` for reuse scope.

## License

MIT. See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
