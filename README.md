# hackathon-template

Private reusable starter for one selected hackathon project under `yun-hackathons`.

## Durable workflow

1. Project Root verifies `.hackathon/candidate-report.md` against `.hackathon/event.json`, then its initial run follows Planner.
2. Without question turns, Planner chooses documented safe reversible defaults and writes a recommended, decision-complete `PLAN.md` with one Plan-bound artifact-requirements JSON block, mirrors that list into `.hackathon/state.json`, records the exact SHA-256, opens one Draft Plan PR, and stops at `PLAN_PENDING_APPROVAL`. Missing information is excluded from automated Build scope or recorded as a user-only blocker; the first run never ends with only a chat question and no durable Plan. `What's the plan?` presents or creates this Plan and is not approval.
3. Before approval, the user may request arbitrary natural-language revisions. Every revision updates the same `PLAN.md`, artifact requirements, state, exact SHA, branch, and Draft PR through `scripts/update-plan.py`; previous approval commands become stale.
4. `这是最终 Plan，请更新 PR 并生成批准命令。` or an unambiguous equivalent only finalizes that same Plan PR and returns `APPROVE PLAN <eventId> <latest_plan_sha>`. It does not call `approve-project.py` or start Builder.
5. Only a later separate follow-up containing that exact command calls `python3 scripts/approve-project.py --repo-root . APPROVE PLAN <eventId> <latest_plan_sha>`. Only `BUILDER_STARTED` may proceed; `BUILDER_ALREADY_STARTED` stops a replay without attempt 2.
6. Builder implements, tests, creates every artifact required by the official rules/approved Plan, commits an immutable artifact revision, and has a real fresh Cursor Reviewer child inspect that exact `buildId`. At most two distinct child rounds are allowed; blocker fixes may be re-reviewed by the same child in the same round. A hosted deployment is required only when the Plan-bound contract asks for a URL or hosted demo.
7. v5 state has exactly four lifecycle states: `PLAN_PENDING_APPROVAL`, `BUILDING`, `FINAL_REVIEW`, and `SUBMISSION_READY`. MVP progress lives only in `qualityGates.mvp`. State records test evidence, one matching artifact record per requirement, the lowercase `bc-<UUID>` child ID, round, status/timestamps, exact reviewed commit, explicit `PASS` or `BLOCKERS`, and the reviewed artifact/code commit as `buildId`. A later metadata-only state commit is not `buildId`. Only PASS may reach terminal `SUBMISSION_READY`; BLOCKERS stays `FINAL_REVIEW`/blocked. Builder self-certification is invalid.
8. The user takes over demo materials and final submission. There is no post-ready approval command, automatic merge, recurring project job, publication, registration, or submission after `SUBMISSION_READY`.

## Agent roles

- `.cursor/agents/planner.md`
- `.cursor/agents/reuse-scout.md`
- `.cursor/agents/builder.md`
- `.cursor/agents/reviewer.md`

## Guardrails

- No application code before the exact event/hash-bound Plan approval.
- No Org-level GitHub or Provisioner credentials in the project environment.
- No copying competitor, winner, gallery, or whole-repository implementations.
- No automatic public release, registration, recurring project execution, or final submission.
- `.hackathon/state.json` must satisfy the v5 `.hackathon/state.schema.json` contract; removed compatibility lifecycle states are invalid.
- `scripts/update-plan.py` only binds revisions/finalization while `PLAN_PENDING_APPROVAL`; once `BUILDING` starts the Plan is immutable, and no reset contract is implied.
- Plan approval and the unique Builder attempt are recorded only by `scripts/approve-project.py`; a failed command restores previous state bytes and a replay cannot start again.
- Finalization and Build remain separate Project Root follow-ups; neither Plan PR activity nor finalization creates a PR-triggered Automation.
- Pull requests run `.github/workflows/project-state-validation.yml`, which uses the trusted base validator and never auto-merges.

The Provisioner writes `.hackathon/candidate-report.md` and `.hackathon/event.json` when it initializes a selected event repository.

## v4 to v5 state migration

v4 and earlier states are intentionally rejected by the v5 validator. Existing v4 projects may set only `schemaVersion` to 5 when they already use one of the four v5 lifecycle states and all durable Plan, approval, Builder, artifact, gate, buildId, and Reviewer evidence remains valid. Preserve `builder-v3:<eventId>:<planSha256>` because it identifies the one actually started Builder run; it is not a legacy pipeline name. Never map `SELECTED`, `REPO_PROVISIONED`, `PLANNING`, or `MVP_GATE_PASSED` into a hidden compatibility state. Selection/provisioning progress belongs to the control plane, while MVP progress belongs to `qualityGates.mvp`. Do not infer PASS or invent evidence/timestamps during migration. A completed historical review may retain `startedAt: null` only when its start time was never recorded; every new or running review requires a real start time. From `FINAL_REVIEW` onward, `buildId` must remain the real reviewed ancestor commit. The validator keeps the record structured and fail-closed but does not authenticate Cursor API provenance, so retain the actual child run evidence.
