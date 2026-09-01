# Opticycle

Paper-only SPY credit verticals on Alpaca. ThesisAgent may output only `BULLISH`, `BEARISH`, or `NO_TRADE`. Deterministic code selects a 3–10 DTE, $5-wide spread, sizes it, binds a payload-hash certificate, and submits one multi-leg order through official `alpaca-mcp-server==2.3.0` (`place_option_order`, `order_class=mleg`). If broker state is unknown after accept, the agent looks up the same `client_order_id` and does not place a second order. CLI is read-only.

## Loop

Observe live SPY and the option chain → stance or `NO_TRADE` → risk certificate on the exact payload → MCP submit → broker GET → journal.

## Repository

| Path | What it is |
| --- | --- |
| `src/opticycle/` | Agent |
| `docs/SUBMISSION_WRITEUP.md` | Decision loop, risk gates, Alpaca path |
| `docs/ALPACA_ACCOUNT.md` | Dedicated paper account ID |
| `artifacts/demo.mp4` | Rendered demo (`remotion/` is the source) |
| `artifacts/evidence/` | Sanitized receipts and the public evidence page |
| `FOUNDATION.md` | Pinned MIT baseline and reuse scope |

```hackathon-artifact-requirements
[
  {
    "id": "submission-repository",
    "kind": "repository",
    "source": "event_rules",
    "description": "MIT-licensed project repository containing the autonomous options trading agent and submission documentation."
  },
  {
    "id": "submission-writeup",
    "kind": "document",
    "source": "event_rules",
    "description": "One-page write-up covering AI decision logic, risk gates, and Alpaca MCP infrastructure (paper account workflow)."
  },
  {
    "id": "alpaca-paper-account-id",
    "kind": "document",
    "source": "event_rules",
    "description": "Dedicated $100k Alpaca paper account ID already created for this hackathon, recorded as ID-only in docs/ALPACA_ACCOUNT.md. Never store API keys in the repository."
  },
  {
    "id": "alpaca-mcp-cli-integration",
    "kind": "integration",
    "source": "event_rules",
    "description": "Working official Alpaca MCP Server execution path (alpaca-mcp-server==2.3.0) that places real multi-leg paper option orders, verified by scripts/verify-paper-mcp-order.py. CLI is not an execution channel."
  },
  {
    "id": "options-trading-strategy",
    "kind": "integration",
    "source": "event_rules",
    "description": "Autonomous agent strategy that executes defined-risk SPY vertical spreads on Alpaca paper, not stock-only execution."
  },
  {
    "id": "remotion-demo-video",
    "kind": "video",
    "source": "approved_plan",
    "description": "Formal Remotion-produced demo video of the autonomous options agent (decision, risk gate, MCP paper order). Source in remotion/, rendered MP4 at artifacts/demo.mp4, plus shot list. Screen recordings or empty scripts do not satisfy this requirement."
  },
  {
    "id": "third-party-notices",
    "kind": "document",
    "source": "approved_plan",
    "description": "THIRD_PARTY_NOTICES.md and README attribution for the pinned MIT snapshot and Alpaca SDK/MCP dependencies (CLI is not an execution dependency)."
  }
]
```
