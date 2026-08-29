# GaussOptions Agent — submission write-up

GaussOptions Agent is an autonomous paper options trader. Each cycle produces one options decision, runs risk gates sized for a $100,000 paper book, and sends the order through Alpaca MCP (primary) or the official Alpaca CLI (fallback). Equity-only orders are disabled.

## AI decision logic

The hackathon profile defaults to `fast` committee mode (no LLM billing). The live strategy set is **wheel** (cash-secured put, then covered-call stage when shares are assigned) and **vertical_spread** (defined-risk put or call verticals) from `vendor/pin-31374551/src/strategy/option/`. The default demo underlying is SPY. A cycle asks those modules for an `ActionPlan` and maps it to an OCC option symbol or a two-leg mleg payload, never a cash-equity market order. Operators may set `HACKATHON_STRATEGY=vertical_spread` without turning stocks on.

## Risk gates

Before any MCP or CLI call, the agent checks:

- options-mandatory profile and paper-only flags
- dedicated paper account id `PA3V84C40PJQ` when the live account snapshot is present
- equity near $100,000 (configurable tolerance)
- max position percent, daily trade count, open position count, and buying power
- portfolio delta and vega caps, with per-contract greeks from vollib Black-Scholes, scaled by the 100-share multiplier

A failed gate is journaled and no order is submitted.

## Alpaca infrastructure

Orders do not use alpaca-py `submit_order` on the hackathon path. `EXECUTION_BACKEND=mcp` spawns `uvx alpaca-mcp-server==2.3.0` over stdio and calls the `place_option_order` tool (single-leg or `order_class=mleg`). `EXECUTION_BACKEND=cli` runs `alpaca order submit` with paper forced (`ALPACA_LIVE_TRADE` must not be true). CI runs `scripts/verify-paper-mcp-order.py --dry-run`. Live paper verify omits `--dry-run` and reads `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` from the environment only. Structured JSONL at `data/journal.jsonl` records decision, gate, and order id.
