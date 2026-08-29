# Plan — Alpaca AI Trading Agents Hackathon

> **Event:** `alpaca-trading-agents-2026` · [Official page](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)
>
> **State target:** `PLAN_PENDING_APPROVAL` · **Foundation:** `gauss-world-trader` (user-selected)
>
> **Candidate report SHA-256:** `fadcfdae7aaf82241a854e9fb9a990a352be6101b6a29ddae83517448ec9fff2` ✓ verified

---

## 1. Executive summary

Build **GaussOptions Agent** — an autonomous, options-first AI trading agent on Alpaca paper — by upgrading the pinned **Gauss World Trader** baseline while preserving its Alpaca-connected strategy/execution skeleton, multi-agent analysis loop, and existing options modules (`wheel`, `vertical_spread`, `TradingOptionEngine`).

The judged artifact is **not** the upstream stock-trading platform demo. It is a **fresh-paper, options-mandatory, MCP-routed autonomous agent** that places real paper orders through **Alpaca MCP Server** (primary) with **Alpaca CLI** as a documented fallback, enforces **$100,000 paper risk gates**, and ships MIT-licensed submission materials including a one-page write-up and Alpaca account ID placeholder for the user to fill at submission time.

**Submission deadline:** 2026-09-04 08:00 PDT (America/Los_Angeles).

---

## 2. Event contract (verified)

| Requirement | Source | Plan response |
| --- | --- | --- |
| Autonomous AI trading agent | Event CORE REQUIREMENTS | Keep GWT `MultiAgentOrchestrator`; add scheduled autonomous cycle with explicit agent decision → risk gate → MCP order path |
| Alpaca Trading API | Sponsor tech | Keep `alpaca-py` data/account clients; paper `TradingClient` for verification and contract discovery |
| Alpaca MCP **or** CLI for orders | Pass/fail gate | **Primary:** `alpaca-mcp-server` via MCP Python SDK; **Fallback:** official `alpacahq/cli` subprocess adapter |
| Strategy **must include options** | Pass/fail gate | Default live path runs option strategies only (`wheel`, `vertical_spread`); stock-only paths disabled in hackathon profile |
| Fresh Alpaca paper account, $100k | Pass/fail gate | Document + env gate for dedicated paper keys; reject reuse of dev account IDs in submission checklist |
| Submit project (MIT), write-up, account ID | Submission rules | Repo MIT + `docs/SUBMISSION_WRITEUP.md` + `docs/ALPACA_ACCOUNT.md` template |
| Original work with prior-code disclosure | Terms §16 | `THIRD_PARTY_NOTICES.md` + README attribution for GWT foundation and Alpaca SDKs |
| Solo team (1 person) | Guidelines | Single-operator build; no team coordination artifacts |

**Judging:** Official page does not publish numeric weights. Optimize for demonstrable autonomous options paper trading, clear AI/risk narrative, and sponsor toolchain compliance.

---

## 3. Foundation (pinned, preserved baseline)

| Field | Value |
| --- | --- |
| **ID** | `gauss-world-trader` |
| **Repository** | https://github.com/Magica-Chen/GaussWorldTrader |
| **Pinned commit** | `31374551bae6fd34a0fe56fe11d208f4ff04fbb4` |
| **License** | MIT |
| **Reuse scope** | Code foundation with disclosure |

### Baseline to keep (do not rewrite)

- Python 3.12+ async platform layout (`src/`, `live_script.py`, CLI entry points)
- Alpaca data provider and account integration (`src/data/alpaca_provider.py`)
- Strategy → `ActionPlan` → `ExecutionEngine` layering
- Existing option strategies: `wheel`, `vertical_spread`
- `TradingOptionEngine` multi-leg order support
- `MultiAgentOrchestrator` and `RiskManagerAgent` patterns
- Streamlit dashboard shell (optional demo surface, not primary judged flow)

### Known baseline gaps (address in Build)

- Live orders today go through direct `alpaca-py` SDK in `ExecutionEngine`, **not** MCP/CLI (event pass/fail)
- Hackathon profile, fresh-account guardrails, and submission docs do not exist yet
- Autonomous loop exists for live CLI but is interactive-first; needs unattended profile for demo/E2E

---

## 4. Product direction

**Product name (working):** GaussOptions Agent

**One-line pitch:** A Gauss World Trader–based autonomous agent that analyzes underlyings with a multi-agent committee, selects option structures (wheel / vertical spreads), passes configurable risk gates sized for a $100k paper book, and executes exclusively through Alpaca MCP on a dedicated hackathon paper account.

**Primary user flow (MVP):**

1. Operator starts agent with hackathon profile: `python -m gaussoptions run --profile hackathon --backend mcp`
2. Agent loads env-configured **fresh paper** Alpaca credentials and validates account equity ≈ $100k and options approval
3. Autonomous cycle runs on a configurable interval (default 15 min during market hours):
   - Fetch watchlist underlyings + option chains via `alpaca-py`
   - Multi-agent analysis produces consensus `ActionPlan`
   - Risk gates evaluate portfolio delta/vega, max position %, daily trade count, buying power
   - Approved plans route to **MCP executor** → `alpaca-mcp-server` tools for option order submit
   - Structured JSON logs + SQLite/JSON trade journal record every decision and order ID
4. Operator runs verification script to prove MCP order path and options leg on paper
5. Submission pack: repo, write-up, account ID doc, demo recording script

**Differentiation vs upstream GWT:** Mandatory MCP execution path, hackathon-only options-first profile, fresh-account compliance checklist, and submission-oriented documentation — not a generic multi-asset trading platform demo.

---

## 5. MVP scope

### In scope (Build automates)

1. **Vendor foundation** — Import GWT `@31374551` into this repo under `vendor/gauss-world-trader/` with `FOUNDATION.md` recording commit, license, and modifications; wire as installable package or path dependency
2. **MCP execution adapter** — `src/trade/mcp/alpaca_mcp_executor.py` spawning `uvx alpaca-mcp-server==2.3.0`; integrate at `ExecutionEngine.execute_decision()` when `EXECUTION_BACKEND=mcp`
3. **CLI execution adapter (fallback)** — `src/trade/cli/alpaca_cli_executor.py` using official `alpacahq/cli`; selectable via `EXECUTION_BACKEND=cli`
4. **Hackathon profile** — `pydantic-settings` block: `starting_capital=100_000`, `require_options=true`, `execution_backend`, risk limits; enforced pre-order
5. **Options-first autonomous runner** — `gaussoptions run` module: unattended loop over option strategies only
6. **Risk gate hardening** — Extend existing limits with portfolio greeks checks using `vollib` (replace/enhance hand-rolled greeks)
7. **Verification & tests** — Unit tests for risk gates and MCP adapter mocking; integration script `scripts/verify-paper-mcp-order.py` (dry-run/mock without live keys in CI; live run documented for user credentials)
8. **Submission docs** — `docs/SUBMISSION_WRITEUP.md`, `docs/ALPACA_ACCOUNT.md`, `docs/DEMO_SCRIPT.md`, updated README, `THIRD_PARTY_NOTICES.md`
9. **Attribution** — Preserve MIT license chain; Apache-2.0 notices for Alpaca SDK/CLI

### Non-goals (explicitly out of Build scope)

- Live/real-money trading or mainnet/crypto brokerage paths
- Replacing GWT core with TradingAgents or TradeAgent architectures
- Hosted 24/7 production deployment or SaaS dashboard
- Social engagement prize campaign automation
- Winning-strategy alpha research / performance guarantees
- LangGraph full rewrite (optional future; not MVP)
- `riskfolio-lib` portfolio optimizer (optional stretch; excluded from MVP gate)

---

## 6. Rejected alternatives

| Alternative | Why rejected |
| --- | --- |
| **trading-agents** (`TauricResearch/TradingAgents`) | User selected `gauss-world-trader`. Apache-2.0 → MIT relicensing overhead; weaker existing Alpaca/options baseline |
| **trade-agent** (`enving/TradeAgent`) | User selected `gauss-world-trader`. No Alpaca-native platform; would discard closer baseline |
| **alpaca-mcp-server as foundation** | Candidate report excludes MCP server as product core; it is integration layer only |
| **Direct SDK-only execution** | Fails event pass/fail gate despite GWT default |
| **Stock-only multi-agent path** | Fails options requirement |
| **LangChain MCP adapters + LangGraph stack** | Heavier deps and `mcp` version conflict; defer unless MCP SDK path blocked |
| **Competing hackathon / gallery repos** | Forbidden by reuse policy |

---

## 7. Architecture

```mermaid
flowchart TB
  subgraph preserved [Preserved from GWT baseline]
    MA[MultiAgentOrchestrator]
    STRAT[Option strategies wheel / vertical_spread]
    EE[ExecutionEngine]
    APY[alpaca-py market + account clients]
  end

  subgraph new [Hackathon additions]
    PROF[HackathonProfile pydantic-settings]
    RG[Risk gates + vollib greeks]
    MCPX[MCP executor]
    CLIX[CLI executor fallback]
    RUN[gaussoptions autonomous runner]
    LOG[Trade journal + structured logs]
  end

  RUN --> MA
  MA --> STRAT
  STRAT --> EE
  PROF --> RG
  RG --> EE
  EE -->|backend=mcp| MCPX
  EE -->|backend=cli| CLIX
  APY --> MA
  APY --> STRAT
  EE --> LOG
  MCPX --> AMS[alpaca-mcp-server subprocess]
```

**Directory plan (post-Build):**

```
vendor/gauss-world-trader/     # pinned upstream snapshot + FOUNDATION.md
src/gaussoptions/              # hackathon profile, runner, config
src/trade/mcp/                   # MCP client + executor
src/trade/cli/                   # CLI executor
docs/                            # write-up, account template, demo script
scripts/verify-paper-mcp-order.py
tests/                           # unit + mocked integration
```

---

## 8. Approved reusable dependencies (Reuse Scout)

Builder may add only these unless Plan is revised:

| Package | Version pin | License | Integration |
| --- | --- | --- | --- |
| `alpaca-py` | ≥0.44.0 | Apache-2.0 | Data, chains, verification client |
| `alpaca-mcp-server` | 2.3.0 via `uvx` | MIT | Order placement subprocess |
| `mcp` | 2.1.1 | MIT | MCP Python client (`Client.call_tool`) |
| `vollib` | 1.0.11 | MIT | Greeks/IV in risk gates |
| `pydantic-settings` | ≥2.14.2 | MIT | Hackathon env config |
| Alpaca CLI (`alpacahq/cli`) | pinned tag in docs/Dockerfile | Apache-2.0 | Fallback executor |

**Explicitly excluded:** `mibian` (GPL), npm `alpaca-cli`, LangGraph stack (MVP), `riskfolio-lib` (MVP).

---

## 9. Credentials and user-only actions

### User-only (never automated by Builder/Agent)

| Action | When | Blocker if missing |
| --- | --- | --- |
| Register on lablab.ai event page | Before submission | Cannot submit |
| Create **brand-new** Alpaca paper account for hackathon only | Before live E2E demo | Cannot pass account-ID artifact |
| Provide paper API key/secret via local `.env` (never commit) | Before live verification | Live MCP order test blocked |
| Fill `docs/ALPACA_ACCOUNT.md` with real account ID | At submission | Incomplete submission |
| Accept lablab/Alpaca terms, W-8BEN/KYC, bank details | If winning | Payout only |
| Final lablab platform submission | By 2026-09-04 08:00 PDT | — |
| Optional: LLM provider key (OpenAI/Anthropic/etc.) for `llm` multi-agent mode | For full agent demo | `fast` mode remains default without LLM key |

### Safe reversible defaults assumed

- **Execution backend:** MCP primary; CLI fallback documented
- **Agent mode:** `fast` multi-agent (no LLM billing) unless user supplies LLM keys
- **Autonomous interval:** 15 minutes; single-symbol watchlist default `SPY` for demo reproducibility
- **Paper account:** Builder uses mocks/fixtures in CI; live paper proof is user-credential gated but scripted

---

## 10. Build phases (post-approval)

| Phase | Deliverable |
| --- | --- |
| **B1 Foundation import** | Vendor tree, NOTICES, runnable baseline smoke test |
| **B2 Execution adapters** | MCP + CLI paths wired through `ExecutionEngine` |
| **B3 Hackathon profile** | Settings, options-only guard, $100k checks |
| **B4 Autonomous runner** | `gaussoptions run` + logging/journal |
| **B5 Risk gates** | vollib greeks, pre-trade veto tests |
| **B6 Verification** | pytest suite + verify script + demo script |
| **B7 Submission pack** | Write-up, README, screenshots list, account template |

**Build branch (post-approval):** `cursor/alpaca-trading-agents-build-622b` off approved Plan commit.

---

## 11. Tests and quality gates

### MVP gate (Builder)

- `pytest tests/` — risk gates, settings validation, MCP adapter mock, execution routing
- `python -m compileall src/` — syntax check
- `python scripts/verify-paper-mcp-order.py --dry-run` — mocked MCP order flow passes
- Manual/automated smoke: `gaussoptions run --profile hackathon --once --dry-run` completes one cycle without error

### E2E (project-appropriate)

Full path: **config load → agent decision → risk gate → MCP tool call (mock or live paper) → journal entry → verification script success**.

Live paper E2E with real Alpaca keys is **documented** in `docs/DEMO_SCRIPT.md` and run by operator; CI uses mocks. Submission-ready evidence binds to commit with mock E2E passing; live run notes included in write-up when user completes it.

### Final review (Reviewer child)

Fresh Reviewer validates exact `buildId` commit against this Plan SHA, artifact locators, MIT/disclosure, options+MCP compliance, and test evidence.

---

## 12. Submission artifacts

| Artifact | Location | Owner |
| --- | --- | --- |
| MIT source repo | This GitHub repository | Builder |
| One-page write-up | `docs/SUBMISSION_WRITEUP.md` | Builder |
| Alpaca paper account ID | `docs/ALPACA_ACCOUNT.md` (user fills ID) | User at submit |
| Demo evidence | `docs/DEMO_SCRIPT.md` + optional terminal recording | Builder script; user records |
| Third-party notices | `THIRD_PARTY_NOTICES.md` | Builder |

No hosted deployment URL required unless user later requests demo hosting (excluded from MVP).

---

## 13. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Reused dev Alpaca account fails eligibility | Checklist + env validator; separate `HACKATHON_PAPER_ACCOUNT_ID` |
| MCP server version/API drift | Pin `alpaca-mcp-server==2.3.0`; adapter integration tests |
| Options paper permissions missing on new account | Preflight account capabilities check with clear error |
| Market closed during demo | `--dry-run` mode + recorded demo script; document market-hours requirement |
| Time pressure (deadline ~7 days) | MVP excludes LangGraph, portfolio optimizer, hosted deploy |
| Apache-2.0 Alpaca SDK in MIT repo | Standard NOTICE file; permitted combination |

---

## 14. Success criteria

1. Autonomous agent completes at least one full **options** decision cycle through **MCP** execution path (mock or live paper)
2. All pass/fail gates satisfied: options present, MCP or CLI used for orders, fresh-account workflow documented
3. pytest suite green; verify script passes in CI dry-run mode
4. Submission write-up covers AI logic, risk gates, Alpaca infra
5. Reviewer child returns `PASS` on immutable `buildId`
6. State reaches `SUBMISSION_READY` with artifact evidence for every requirement below

---

## 15. Attribution and disclosure duties

- README **Foundation** section: Gauss World Trader @ `31374551`, MIT, https://github.com/Magica-Chen/GaussWorldTrader
- `THIRD_PARTY_NOTICES.md`: Alpaca SDK (Apache-2.0), Alpaca MCP Server (MIT), Alpaca CLI (Apache-2.0), vollib (MIT), MCP SDK (MIT)
- `docs/SUBMISSION_WRITEUP.md`: state which components are original hackathon work vs adapted foundation
- Do not remove upstream LICENSE files in vendor tree
- lablab submission: disclose AI coding tools used to build the agent (per hackathon AI policy)

---

## 16. Assumptions log

| ID | Assumption | Reversal |
| --- | --- | --- |
| A1 | MCP Python SDK v2 (`mcp>=2.1.1`) works with `alpaca-mcp-server` 2.3.0 | Fall back to CLI executor as primary |
| A2 | GWT option strategies work on Alpaca paper without code fork | Patch vendor strategy modules in-place with attribution |
| A3 | `fast` multi-agent mode sufficient for MVP autonomous demo | User adds LLM key for `llm` mode post-approval |
| A4 | Single-underlying demo (`SPY`) acceptable for judges | Expand watchlist via env without Plan change |
| A5 | Mock MCP E2E satisfies Reviewer when live keys unavailable in CI | User runs live script before final submission |

---

## 17. Decisions for user inspection at approval

1. **Foundation locked:** `gauss-world-trader` @ `31374551` — no substitution
2. **Execution primary:** Alpaca MCP Server; CLI fallback only
3. **MVP agent mode:** `fast` (no LLM API cost) unless user opts in with keys
4. **Demo symbol:** SPY options wheel/vertical spread rotation
5. **No hosted deployment** in artifact contract
6. **Live paper proof** is user-credential gated but fully scripted

Revise via natural language in this Project Root thread; each revision updates this file and invalidates prior approval commands.

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
    "description": "One-page write-up covering AI decision logic, risk gates, and Alpaca infrastructure (MCP/CLI, paper account workflow)."
  },
  {
    "id": "alpaca-paper-account-id",
    "kind": "document",
    "source": "event_rules",
    "description": "Fresh Alpaca paper trading account ID for hackathon submission, recorded in docs/ALPACA_ACCOUNT.md for the user to confirm before platform submit."
  },
  {
    "id": "alpaca-mcp-cli-integration",
    "kind": "integration",
    "source": "event_rules",
    "description": "Working Alpaca MCP Server or official Alpaca CLI execution path that places real paper option orders, verified by scripts/verify-paper-mcp-order.py."
  },
  {
    "id": "options-trading-strategy",
    "kind": "integration",
    "source": "event_rules",
    "description": "Autonomous agent strategy that includes options trades (wheel and/or vertical spreads) on Alpaca paper, not stock-only execution."
  },
  {
    "id": "autonomous-agent-demo",
    "kind": "demo",
    "source": "approved_plan",
    "description": "End-to-end autonomous agent cycle documented in docs/DEMO_SCRIPT.md with structured logs showing agent decision, risk gate pass, and MCP order routing."
  },
  {
    "id": "third-party-notices",
    "kind": "document",
    "source": "approved_plan",
    "description": "THIRD_PARTY_NOTICES.md and README foundation attribution for Gauss World Trader and Alpaca SDK/MCP/CLI dependencies."
  }
]
```
