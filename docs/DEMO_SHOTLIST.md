# Opticycle — demo shot list (locked product)

`artifacts/demo.mp4` is **NOT submission footage**. It is leftover from an earlier storyboard and must not be submitted. Remotion rewrite is Gate 12, not this commit.

Locked on-screen story: SPY defined-risk credit vertical only. Execution is official `alpaca-mcp-server==2.3.0` MLEG (`place_option_order`, `order_class=mleg`) only. Loop: Risk Certificate → MCP → broker reconcile → Evidence Ledger. No channel switch.

| # | Duration | On-screen story |
| --- | --- | --- |
| 1 | 10.0 s | One-liner: Opticycle is an autonomous SPY defined-risk credit-vertical paper agent on Alpaca. |
| 2 | 9.0 s | Dedicated $100,000 paper book. Live trading off. No keys on screen. |
| 3 | 12.0 s | Proof-carrying loop: observe → thesis / `NO_TRADE` → payload-bound Risk Certificate → MCP MLEG → broker reconcile → ledger. |
| 4 | 12.0 s | Fail-closed gates: options-only, notional cap, daily cap. Veto does not submit. Unknown broker state HALTs. |
| 5 | 10.0 s | Sole live channel: `alpaca-mcp-server==2.3.0` tool `place_option_order` (`order_class=mleg`). |
| 6 | 12.0 s | How to run once (dry-run): `python3 -m opticycle run --profile hackathon --backend mcp --once --dry-run` and `python3 scripts/verify-paper-mcp-order.py --dry-run`. |

Gate 12 will replace `artifacts/demo.mp4` with a Remotion render of this locked story. Do not treat the current file as the submission demo.
