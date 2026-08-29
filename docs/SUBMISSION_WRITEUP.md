# Opticycle — submission write-up

Opticycle is an autonomous paper options trader. Each cycle produces one options decision, runs risk gates sized for a $100,000 paper book, and sends the order through official Alpaca MCP Server 2.3.0 only. Equity-only orders are disabled. There is no CLI execution channel.

## AI decision logic

The hackathon profile defaults to `fast` mode (no LLM billing). The live strategy is a **SPY defined-risk vertical** from `vendor/pin-31374551/src/strategy/option/`. A cycle asks that module for an `ActionPlan` and maps it to a two-leg mleg payload, never a cash-equity market order.

## Risk gates

Before any MCP call, the agent checks:

- options-mandatory profile and paper-only flags
- dedicated paper account id `PA3V84C40PJQ` when the live account snapshot is present
- equity near $100,000 (configurable tolerance)
- max position percent, daily trade count, open position count, and buying power
- portfolio delta and vega caps, with per-contract greeks from vollib Black-Scholes, scaled by the 100-share multiplier

A failed gate is journaled and no order is submitted.

## Alpaca infrastructure

Orders do not use alpaca-py `submit_order` on the hackathon path. `EXECUTION_BACKEND=mcp` spawns `uvx alpaca-mcp-server==2.3.0` over stdio and calls the `place_option_order` tool (`order_class=mleg`). CI runs `scripts/verify-paper-mcp-order.py --dry-run`. Live paper verify omits `--dry-run` and reads `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` from the environment only. Structured JSONL at `data/journal.jsonl` records decision, gate, and order id.
