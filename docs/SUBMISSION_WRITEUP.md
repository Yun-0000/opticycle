# Opticycle — proof-carrying SPY options agent

Opticycle is an autonomous paper trader that makes one narrow promise: it trades only when fresh evidence survives deterministic risk checks, binds authorization to the exact multi-leg payload, and refuses to trust execution until Alpaca broker state reconciles. The result is an auditable agent that can say `NO_TRADE`, manage its positions, and stop safely when execution is uncertain.

## AI decision logic

ThesisAgent receives only validated market features: quote freshness, 20-day realized volatility, current-chain IV rank, 25-delta put/call skew, five-day range, trend, and the NFP event clock. It may output only `BULLISH`, `BEARISH`, or `NO_TRADE`; it never chooses OCC symbols, quantity, or price. A deterministic selector then builds a 3–10 DTE, $5-wide SPY credit vertical with 0.20–0.30 short-leg delta. BULLISH binds to a bull put; BEARISH binds to a bear call. Missing evidence stays `NO_TRADE`.

## Risk gates

The exact payload receives a short-lived hash-bound certificate. Quantity is `floor(2% × live equity / per-contract max loss)`, capped at four contracts per vertical, then checked against 8% aggregate open risk, the independent 8% position hard cap, two new verticals per day, four verticals open, buying power, and portfolio delta/vega/gamma/theta limits. Contract quantity does not consume extra structure slots. The lifecycle manager exits through another hash-bound MLEG at 50% credit captured, 2× credit loss, ≤1 DTE, or the pre-NFP ≤2 DTE flatten window. A timeout never creates a second submit.

## Alpaca infrastructure

All order mutations use official `alpaca-mcp-server==2.3.0` → `place_option_order` → `order_class=mleg`. Alpaca GET and the official Alpaca CLI (`account get`, `position list`, `order list`) provide independent read-only reconciliation and public evidence; CLI is never an execution fallback. Every accepted order keeps one `client_order_id`, payload hash, certificate binding, MCP attempt count, broker receipt, reconciliation verdict, and equity/P&L snapshot.

| Verified result | Broker evidence | Outcome |
| --- | --- | --- |
| SPY 793C/809C bear call | entry credit 2.11; MCP close debit 1.53 | approx. **+$58** realized |
| SPY 768C/769C bear call | entry credit 0.51; MCP close debit 0.53 | approx. **−$2** realized |
| SPY 740P/724P bull put | limit `-2.26`; fill `-2.26`; broker `24b16fe6…` | live price-bound **MATCHED** |
| Account after closing first two spreads | Alpaca equity `100055.67` | authoritative broker snapshot |
| Modeled walk-forward | Alpaca IEX daily bars + Black-Scholes option pricing | research context only; not broker P&L |

Public proof: Judge packet, broker receipts, portfolio-history curve, source, and rendered demo all resolve from the same repository HEAD.

<small>Honesty: the first two entries were real fills but used the wrong positive sign for intended credit limits, so they remain `FILLED`, not price-bound `MATCHED`. The third entry is the only live price-bound match. Keyless replay and the IEX/Black-Scholes walk-forward are labeled and never promoted to live evidence. Foundation reuse is disclosed in `FOUNDATION.md`.</small>
