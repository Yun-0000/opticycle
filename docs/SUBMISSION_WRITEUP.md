# Opticycle — submission write-up

Opticycle is an autonomous paper options trader. Each cycle observes the market, asks ThesisAgent for a stance when an LLM key is present, runs risk gates sized for a $100,000 paper book, and — only after a payload-bound certificate — sends a defined-risk SPY vertical through official Alpaca MCP Server 2.3.0 (`place_option_order`, `order_class=mleg`). Equity-only orders are disabled. There is no CLI execution channel. ThesisAgent is an LLM call and is fail-closed without a key; a heuristic stance is labeled as such and is not a live ThesisAgent pick.

## AI decision logic

Live ThesisAgent is an LLM call. The model chooses `BULLISH`, `BEARISH`, or `NO_TRADE` from pre-validated snapshot evidence in the prompt (quotes, freshness, bar return/trend, chain presence). Determined signals such as implied stance may appear as evidence; they are not the answer. The model may disagree. Missing or stale evidence stays fail-closed. Without an LLM key the live path is fail-closed `NO_TRADE` / `HALT` — not a silent deterministic direction labeled as AI.

The Monday live MCP MLEG (`oc-715ad36a630d408e`) used `stance_source=bars_heuristic_no_llm_key`: there was no LLM key on the box. That is not a live ThesisAgent LLM pick. An OpenAI key is now present; a live ThesisAgent episode still requires a fresh in-session SPY quote (after-hours 2026-08-31 observation was `NO_TRADE` / `SPY quote is stale`, `model_called=false`).

Stance binds credit type later: BULLISH → bull put credit, BEARISH → bear call credit. Debit verticals are disabled. The model never selects OCC symbols, quantity, or limit price. Credit MLEG `limit_price` is Alpaca-signed (negative).

## Risk gates

Before any MCP call, the agent checks:

- options-mandatory profile and paper-only flags
- official MCP as the only execution backend (`alpaca-mcp-server==2.3.0`)
- equity near $100,000 (configurable tolerance)
- max position percent, daily trade count, open position count, and buying power
- portfolio greeks from live marks or real IV when present; missing inputs are omitted, not invented as zero
- credit MLEG limit sign (positive debit / negative credit). A credit vertical with a non-negative limit is vetoed. Certified max-loss uses that signed limit.

The Monday fill's historical certificate claimed `max_loss=30` from an unsigned 0.70 credit. The broker fill was 0.51 credit, so realized max-loss at fill is $49. That episode is recorded as `FILLED`, not price-bound `MATCHED`. A failed gate is journaled and no order is submitted.

## Alpaca infrastructure

Orders do not use alpaca-py `submit_order` on the hackathon path. Live execution spawns `uvx alpaca-mcp-server==2.3.0` over stdio and calls `place_option_order` (`order_class=mleg`) only. Keyless CI dry-run is `python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run` (fixture market, no live submit) plus `scripts/verify-paper-mcp-order.py --dry-run`. Live paper verify omits `--dry-run` and reads `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` from the environment only. Structured JSONL at `data/journal.jsonl` records decision, gate, and order id.

## Monday paper broker fills

Two real MCP MLEG paper fills are recorded as `live_paper` `FILLED` (not price-bound `MATCHED`). Submitted limits were debit-positive. Account id omitted.

| client_order_id | structure | submitted limit | fill | notes |
| --- | --- | --- | --- | --- |
| `oc-204a8dfccffd40c9` | BEARISH bear-call SPY 2026-10-09 793C/809C qty 1 | `+2.54` (debit sign; intended credit bound `-2.54`) | 2.11 credit (`filled_avg_price=-2.11`) at 2026-08-31 13:30:03Z | broker `abcb5385-0aa3-42cc-9b58-ef4200235c27`; fill-time equity 100007.95; not credit-better |
| `oc-715ad36a630d408e` | BEARISH bear-call SPY 2026-09-25 768C/769C qty 1 | `+0.70` (debit sign) | 0.51 credit (`filled_avg_price=-0.51`) at 2026-08-31 14:05:49Z | broker `2a6d6b7c-caad-4c24-959a-8d93455a36fe`; certificate max_loss $30 vs fill max_loss $49; heuristic stance |

Public evidence: `artifacts/evidence/index.html`. These fills are broker facts, not price-bound MATCHED.
