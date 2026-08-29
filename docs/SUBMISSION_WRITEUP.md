# Opticycle — submission write-up

Opticycle is an autonomous paper options trader. Each cycle observes the market, asks ThesisAgent for a stance, runs risk gates sized for a $100,000 paper book, and — only after a payload-bound certificate — sends a defined-risk SPY vertical through official Alpaca MCP Server 2.3.0 (`place_option_order`, `order_class=mleg`). Equity-only orders are disabled. There is no CLI execution channel. ThesisAgent is an LLM call and is fail-closed without a key.

## AI decision logic

Live ThesisAgent is an LLM call. The model chooses `BULLISH`, `BEARISH`, or `NO_TRADE` from pre-validated snapshot evidence in the prompt (quotes, freshness, bar return/trend, chain presence). Determined signals such as implied stance may appear as evidence; they are not the answer. The model may disagree. Missing or stale evidence stays fail-closed. Without an LLM key the live path is fail-closed `NO_TRADE` / `HALT` — not a silent deterministic direction labeled as AI.

Stance binds credit type later: BULLISH → bull put credit, BEARISH → bear call credit. Debit verticals are disabled. The model never selects OCC symbols, quantity, or limit price.

## Risk gates

Before any MCP call, the agent checks:

- options-mandatory profile and paper-only flags
- official MCP as the only execution backend (`alpaca-mcp-server==2.3.0`)
- equity near $100,000 (configurable tolerance)
- max position percent, daily trade count, open position count, and buying power
- portfolio greeks from live marks or real IV when present; missing inputs are omitted, not invented as zero

A failed gate is journaled and no order is submitted.

## Alpaca infrastructure

Orders do not use alpaca-py `submit_order` on the hackathon path. Live execution spawns `uvx alpaca-mcp-server==2.3.0` over stdio and calls `place_option_order` (`order_class=mleg`) only. Keyless CI dry-run is `python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run` (fixture market, no live submit) plus `scripts/verify-paper-mcp-order.py --dry-run`. Live paper verify omits `--dry-run` and reads `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` from the environment only. Structured JSONL at `data/journal.jsonl` records decision, gate, and order id.
