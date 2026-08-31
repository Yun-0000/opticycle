# Opticycle — submission write-up

Opticycle is an autonomous paper options trader. Each cycle observes the market, asks ThesisAgent for a stance when an LLM key is present, runs risk gates sized for a $100,000 paper book, and — only after a payload-bound certificate — sends a defined-risk SPY vertical through official Alpaca MCP Server 2.3.0 (`place_option_order`, `order_class=mleg`). Equity-only orders are disabled. There is no CLI execution channel. ThesisAgent is an LLM call and is fail-closed without a key; a heuristic stance is labeled as such and is not a live ThesisAgent pick.

## AI decision logic

Live ThesisAgent is an LLM call. The model chooses `BULLISH`, `BEARISH`, or `NO_TRADE` from pre-validated snapshot evidence in the prompt (quotes, freshness, bar return/trend, chain presence). Determined signals such as implied stance may appear as evidence; they are not the answer. The model may disagree. Missing or stale evidence stays fail-closed. Without an LLM key the live path is fail-closed `NO_TRADE` / `HALT` — not a silent deterministic direction labeled as AI.

The Monday live MCP MLEG (`oc-715ad36a630d408e`) used `stance_source=bars_heuristic_no_llm_key`: there was no LLM key on the box. That is not a live ThesisAgent LLM pick.

Stance binds credit type later: BULLISH → bull put credit, BEARISH → bear call credit. Debit verticals are disabled. The model never selects OCC symbols, quantity, or limit price.

## Risk gates

Before any MCP call, the agent checks:

- options-mandatory profile and paper-only flags
- official MCP as the only execution backend (`alpaca-mcp-server==2.3.0`)
- equity near $100,000 (configurable tolerance)
- max position percent, daily trade count, open position count, and buying power
- portfolio greeks from live marks or real IV when present; missing inputs are omitted, not invented as zero

A failed gate is journaled and no order is submitted. The Monday fill carried `certificate_approval=true` and `max_loss=30`.

## Alpaca infrastructure

Orders do not use alpaca-py `submit_order` on the hackathon path. Live execution spawns `uvx alpaca-mcp-server==2.3.0` over stdio and calls `place_option_order` (`order_class=mleg`) only. Keyless CI dry-run is `python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run` (fixture market, no live submit) plus `scripts/verify-paper-mcp-order.py --dry-run`. Live paper verify omits `--dry-run` and reads `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` from the environment only. Structured JSONL at `data/journal.jsonl` records decision, gate, and order id.

## Monday paper MATCHED fills

Two real MCP MLEG paper fills are recorded as `live_paper` `MATCHED` (not replay-as-done). No extra fills. Account id omitted.

| client_order_id | structure | limit | fill | notes |
| --- | --- | --- | --- | --- |
| `oc-204a8dfccffd40c9` | BEARISH bear-call SPY 2026-10-09 793C/809C qty 1 | 2.54 credit | 2.11 credit (`filled_avg_price=-2.11`) at 2026-08-31 13:30:03Z | recon equity 100007.95, cash 100210.95 |
| `oc-715ad36a630d408e` | BEARISH bear-call SPY 2026-09-25 768C/769C qty 1 | 0.70 credit | 0.51 credit (`filled_avg_price=-0.51`) at 2026-08-31 14:05:49Z | `place_option_order`, `mcp_submit_count=1`; stdio hung after the broker had the order; no second submit; heuristic stance |

Public evidence: `artifacts/evidence/index.html`. Public completion is the two real `live_paper` MATCHED fills.
