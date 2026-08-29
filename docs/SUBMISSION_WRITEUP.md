# GaussOptions Agent — submission write-up

## Product
An autonomous paper-trading agent that only trades equity options on a dedicated $100k Alpaca paper book. One cycle: pick a wheel-style cash-secured put, pass risk gates, then submit the order through Alpaca MCP (primary) or the official Alpaca CLI (fallback).

## AI logic
The MVP cycle is deterministic and options-only. It selects the event symbol (default SPY), sizes a single-leg put, and tags the plan as `wheel`. Stock-only plans are rejected before any broker call. A later cycle can swap in a vertical spread without changing the execution contract.

## Risk gates
Pre-trade checks, all fail-closed:

- `asset_class` must be `option`
- order notional cannot exceed 15% of paper equity
- daily trade count cannot exceed 8
- paper equity must stay positive on the $100k book

Failed gates never reach MCP or CLI.

## Alpaca infrastructure
- **MCP (primary):** `place_order` with `asset_class=option`
- **CLI (fallback):** `alpaca order submit --asset-class option`
- Paper API keys stay in local environment variables and are never written to the repository
- Account ID for the already-created dedicated paper account is recorded in `docs/ALPACA_ACCOUNT.md` (ID only)

## How to verify
`python -m src.gaussoptions --once --backend mcp --dry-run`
