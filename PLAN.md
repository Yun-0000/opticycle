# Plan — Alpaca AI Trading Agents Hackathon

> **Event:** `alpaca-trading-agents-2026` · [Official page](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)
>
> **State target:** `PLAN_PENDING_APPROVAL` · **Foundation:** `pin-31374551` (user-selected)
>
> **Candidate report SHA-256:** `f5bc9bdaa51f191a40fff11d00683f989b3471c9c68b0bc9efa9a1c73f45837a` ✓ verified

---

## 1. Executive summary & Product Definition

**Opticycle** is an autonomous, proof-carrying SPY options trading agent built on Alpaca. It trades only when fresh market evidence survives deterministic pre-trade risk gates, binds cryptographic/hash authorization directly to the option order payload, executes exclusively through the official **Alpaca MCP Server** (`alpaca-mcp-server==2.3.0`), and does not trust execution until post-trade broker portfolio state is fully reconciled.

### Hard Product Contract (No Fallback Product)
1. **Single Strategy:** Defined-risk SPY vertical spreads exclusively (bull put / bear call credit spreads). Stock-only trading, unhedged cash equities, and naked/single-leg options are disabled.
2. **Sole Live Execution Channel:** Official `alpaca-mcp-server==2.3.0` tool invocation (`place_option_order` with `order_class=mleg`).
3. **No Execution Channel Fallbacks:** The CLI is not an execution fallback and does not participate in live execution. If MCP multi-leg execution is down or broker state is indeterminate, Opticycle executes a safe **HALT**. Unknown broker state = HALT. No channel switching, no manual leg-splitting, and no silent re-submissions.
4. **Autonomous Proof-Carrying Loop:** Fresh observation → Thesis/`NO_TRADE` → Authorization Certificate → MCP Multi-Leg Order → Broker State Reconciliation → Ledger Settlement → Re-plan or HALT.
5. **One Completion State:** Delivery of all 12 champion gates without an "MVP then champion" bifurcation.

**Submission deadline:** 2026-09-04 08:00 PDT (America/Los_Angeles).

---

## 2. Event Contract & Rules Compliance

| Requirement | Source | Plan response |
| --- | --- | --- |
| Autonomous AI trading agent | Event CORE REQUIREMENTS | Proof-carrying loop: observation → thesis/`NO_TRADE` → deterministic certificate → MCP multi-leg order → broker reconciliation |
| Alpaca Trading API | Sponsor tech | `alpaca-py` market data client for SPY option chains and account quotes |
| Alpaca MCP for orders | Pass/fail gate | Official `alpaca-mcp-server==2.3.0` via Python MCP SDK as the sole live execution channel |
| Strategy must include options | Pass/fail gate | Defined-risk SPY vertical spreads exclusively (bull put / bear call spreads) |
| Dedicated paper account, $100k | Pass/fail gate | Dedicated $100,000 paper account; credentials in local `.env` only; never stored in repo |
| Submission artifacts (MIT) | Submission rules | MIT repository + `docs/SUBMISSION_WRITEUP.md` + `docs/ALPACA_ACCOUNT.md` |
| Prior-code disclosure | Terms §16 | `THIRD_PARTY_NOTICES.md` + README disclosure for the pinned MIT foundation (`vendor/pin-31374551/`) |
| Solo team (1 person) | Guidelines | Single-operator build |

---

## 3. Foundation & Prior Code Disclosure

| Field | Value |
| --- | --- |
| **Foundation ID** | `pin-31374551` |
| **Snapshot path** | `vendor/pin-31374551/` |
| **Pinned commit** | `31374551bae6fd34a0fe56fe11d208f4ff04fbb4` |
| **License** | MIT |
| **Original author** | Zexun Chen (`Copyright (c) 2026 Zexun Chen`) |
| **Reuse scope** | Pinned baseline algorithmic framework |

### Honest Baseline Distinction
- **Reused Baseline from Snapshot:** Python 3.12 async project layout, Alpaca data client wrapper, analytical Black-Scholes greeks calculation utilities.
- **Opticycle Original Hackathon Contributions:** Proof-carrying execution architecture, pure SPY defined-risk vertical spread selection engine with width/DTE/delta filters, deterministic multi-stage risk gating with payload-bound authorization certificates, MCP multi-leg execution protocol with post-trade broker state reconciliation, and strict fail-closed safety (HALT on unknown state).

---

## 4. Product Direction & The Autonomous Loop

**Product Name:** Opticycle

**One-line Pitch:** A proof-carrying SPY options agent that evaluates fresh market evidence, signs deterministic risk certificates for defined-risk vertical spreads, executes solely through Alpaca MCP, and halts safely if broker state cannot be verified.

### The 6-Stage Proof-Carrying Loop
1. **Observe:** Ingest fresh SPY underlying spot prices, technical indicators, and option chain quotes via `alpaca-py` with strict freshness checks.
2. **Evaluate:** Generate a defined-risk vertical spread candidate or emit an explicit `NO_TRADE` decision.
3. **Certify:** Evaluate deterministic risk gates (paper account bounds, max loss, position limits, net greeks, OCC formatting) and generate a payload-bound authorization certificate.
4. **Execute:** Dispatch the multi-leg order payload exclusively to `alpaca-mcp-server` tool `place_option_order` (`order_class=mleg`).
5. **Reconcile:** Poll broker order and portfolio state until terminal confirmation (`filled`, `rejected`, `canceled`). If state is ambiguous or drifts, trigger safe **HALT**.
6. **Journal:** Record full cryptographic trail (observation, certificate, MCP payload/response, broker state) into an immutable local JSONL trade journal.

---

## 5. 12-Gate Engineering Plan

The Opticycle implementation is organized across 12 champion quality gates:

- **Gate 1 (Current):** Source-of-Truth Contract Alignment — Rewrite `PLAN.md` to define the unique Opticycle contract (SPY defined-risk vertical only, MCP sole execution channel, proof-carrying loop, fail-closed HALT, no CLI fallback).
- **Gate 2:** Architecture Cleanliness & Deprecation — Eliminate legacy fallback routes; enforce MCP as the single live execution path.
- **Gate 3:** SPY Market Observation Engine — Ingest real SPY bars and option chains via Alpaca market data API with quote freshness checks; live path cannot use fixtures as real market data.
- **Gate 4:** Vertical Spread Selection Engine — Construct pure defined-risk SPY vertical spread candidates with strike width and DTE validation.
- **Gate 5:** Deterministic Risk Gate & Proof Certificate — Verify account limits, max loss, portfolio delta/vega, and issue payload-bound authorization certificates.
- **Gate 6:** Alpaca MCP Multi-Leg Adapter — Robust client communication with `alpaca-mcp-server==2.3.0` for multi-leg option orders.
- **Gate 7:** Post-Trade Broker State Reconciliation — Match broker order IDs, fills, and position delta against local intent.
- **Gate 8:** Fail-Closed Safety & Safe HALT Engine — Handle ambiguous broker responses and connection drops safely without channel switching.
- **Gate 9:** Immutable Audit Journal — Structured JSONL logging of all certificates, payload hashes, and reconciled broker states.
- **Gate 10:** Comprehensive Test Suite — Deterministic unit and mock integration tests covering all execution, veto, and reconciliation paths.
- **Gate 11:** Verification Suite — `scripts/verify-paper-mcp-order.py` proving MCP paper flow without secrets leakage.
- **Gate 12:** Release Pack & Demonstration — Submission write-up, notices, and official demonstration (user-managed final release).

---

## 6. Approved Reusable Dependencies

| Package | Version pin | License | Role |
| --- | --- | --- | --- |
| `alpaca-py` | ≥0.44.0 | Apache-2.0 | Market data and account query client |
| `alpaca-mcp-server` | 2.3.0 via `uvx` | MIT | Sole live execution MCP server |
| `mcp` | 2.1.1 | MIT | Python MCP client for tool calling |
| `vollib` | 1.0.11 | MIT | Analytical Black-Scholes greeks calculation |
| `pydantic-settings` | ≥2.14.2 | MIT | Validated environment configuration |
| `pydantic` | ≥2.4.0 | MIT | Schema definition and payload validation |

---

## 7. Submission Artifacts

| Artifact | Location | Description |
| --- | --- | --- |
| MIT source repository | This repository | Autonomous SPY options agent codebase |
| Submission write-up | `docs/SUBMISSION_WRITEUP.md` | Overview of AI decision loop, risk gates, and MCP architecture |
| Paper account ID | `docs/ALPACA_ACCOUNT.md` | Dedicated paper account identifier (`PA3V84C40PJQ`) |
| Demo video | `artifacts/demo.mp4` / `remotion/` | Official programmatic demonstration video and source |
| Third-party notices | `THIRD_PARTY_NOTICES.md` | Complete disclosure and copyright notices for MIT baseline and SDKs |

---

## 8. Success Criteria

1. Opticycle executes unattended SPY vertical spread cycles exclusively over Alpaca MCP.
2. Every order payload is guarded by deterministic pre-trade risk gates with full broker reconciliation.
3. Strict fail-closed policy: ambiguous broker responses trigger immediate safe HALT without unsafe channel fallbacks.
4. Clean test suite and verification script passing under CI dry-run conditions; CI dry-run cannot count as fill/completion evidence.

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
