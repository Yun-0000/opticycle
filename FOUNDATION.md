# Foundation disclosure

This is the only first-party file that names the upstream foundation. README, demo materials, and the public evidence page do not.

| Field | Value |
| --- | --- |
| Foundation ID | `pin-31374551` |
| Snapshot path | `vendor/pin-31374551/` |
| Pinned commit | `31374551bae6fd34a0fe56fe11d208f4ff04fbb4` |
| License | MIT (`vendor/pin-31374551/LICENSE`, also copied at repo root `LICENSE`) |
| Original author | Zexun Chen (`Copyright (c) 2026 Zexun Chen`) |
| Upstream project | Gauss World Trader |
| Original repository | https://github.com/Magica-Chen/GaussWorldTrader |
| Reuse scope | Pinned baseline algorithmic framework only |

## Original-vs-reused checklist

### Reused from the pinned snapshot

- Python 3.12 async project layout
- Alpaca market-data / account read client wrapper
- Analytical Black-Scholes greeks calculation utilities
- Defined-risk vertical spread construction helpers under `vendor/pin-31374551/src/strategy/option/`

### Original Opticycle work (this hackathon)

- Proof-carrying observe → thesis/`NO_TRADE` → certificate → MCP MLEG → reconcile loop
- Thesis agent with stance-only outputs (no OCC/qty/price selection)
- Payload-bound Risk Certificate
- Official `alpaca-mcp-server==2.3.0` as the sole live execution channel
- Post-trade broker reconciliation and fail-closed HALT cycle engine
- Append-only Evidence Ledger and this public evidence pack

### Not reused as a live product

- Stock-only / wheel strategies from the snapshot
- Snapshot CLI as an execution channel
- Snapshot dashboard / notification branding
