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

## Monday paper MATCHED fills

Two real Opticycle MCP MLEG paper fills, channel `live_paper`, outcome `MATCHED`. Not replay-as-done. No extra fills. Account id omitted.

1. `oc-204a8dfccffd40c9` — BEARISH bear-call credit, SPY 2026-10-09 793C/809C, qty 1, limit 2.54. Legs: sell `SPY261009C00793000` fill 2.95; buy `SPY261009C00809000` fill 0.84. Broker filled 2026-08-31 13:30:03Z, `filled_qty=1`, `filled_avg_price=-2.11` (2.11 credit vs 2.54 limit). Recon equity 100007.95, cash 100210.95.
2. `oc-715ad36a630d408e` — BEARISH bear-call, SPY 2026-09-25 768C/769C, qty 1, limit 0.70, max_loss 30. Legs: sell `SPY260925C00768000` fill 8.68; buy `SPY260925C00769000` fill 8.17. Filled 2026-08-31 14:05:49Z, `filled_qty=1`, `filled_avg_price=-0.51`. MCP `place_option_order`, `mcp_submit_count=1` (stdio hung after the broker had the order; no second submit). **`stance_source=bars_heuristic_no_llm_key`**: no LLM key on the box — not a live ThesisAgent LLM pick. Certificate approval true.

No demo video is committed in this packet. Remotion demo is Gate 12.

Paper account ID is recorded in `docs/ALPACA_ACCOUNT.md` (ID only).

## Public evidence

Judge packet (sanitized ledger only): `artifacts/evidence/index.html`. Public completion is the two real live_paper MATCHED fills (`oc-204a8dfccffd40c9`, `oc-715ad36a630d408e`).

## License

MIT. See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
