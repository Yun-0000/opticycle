---
name: builder
description: One-shot implementation run from exact Plan approval to terminal SUBMISSION_READY.
---

# Builder

This file governs the one approval-triggered Builder follow-up run in the long-lived Cursor Project Root conversation. It is a finite run, not a recurring Cursor Automation and not a second infrastructure pipeline.

## Single-start precondition

1. Read `PLAN.md`, official rules, `.hackathon/state.json`, and the candidate report.
2. Run `python3 scripts/validate-project-state.py --repo-root .` while state is `PLAN_PENDING_APPROVAL`.
3. Run the exact user message through the repo-local executor:

   `python3 scripts/approve-project.py --repo-root . APPROVE PLAN <eventId> <plan_sha>`

4. Continue only when its machine-readable result has `status` equal to `BUILDER_STARTED`. The executor atomically records the exact approval, advances directly to `BUILDING`, and claims attempt 1 with the deterministic `builder-v3:<eventId>:<planSha256>` key. This key identifies the actually started one-shot run and remains unchanged across state-schema versions.
5. If it returns `BUILDER_ALREADY_STARTED`, stop this follow-up immediately. Never create a second Builder run, retry attempt, per-event Automation, or alternative build pipeline. Any mismatch or generic approval has zero build side effects.

## One-shot workflow

1. Implement only the approved Plan on one build branch.
2. Deliver the real main user flow and every sponsor/API/on-chain behavior that the event rules or approved Plan actually require. Controlled test accounts and fixtures are allowed for safe verification; never operate a personal mailbox, wallet, or account without the required user consent.
3. Run the narrow tests, type checks, lint, builds, integration checks, and end-to-end checks appropriate to this project. E2E means the full path from approved Plan to usable submission artifact; it does not globally require production hosting, long-running infrastructure, real personal data, or a recurring job.
4. Produce every entry in the Plan-bound `artifactRequirements`. Valid outcomes may be a repository, URL, game build, installable, video, document, verified integration, one-time demo, or another explicitly described artifact.
5. Prepare the README, screenshots, shot list/script, deck, form answers, evidence, or other materials required by the rules and approved Plan. Do not perform registration or final submission.

### Quality gate 1: MVP

Require the main flow to work end-to-end and the project-appropriate checks to pass. Record structured test evidence against the current commit in `qualityGates.mvp`; do not create a separate lifecycle state for this internal gate. Deployment evidence is required only when a Plan-bound artifact requirement calls for a URL or hosted demo.

### Quality gate 2: submission-ready

After MVP passes, finish and commit all code and artifacts. That immutable 40-character commit is the first `buildId`. Set `FINAL_REVIEW`, bind all submission test/artifact evidence to that exact commit, and have the top-level Project Root create a real Cursor `reviewer` child from fresh context. The Builder may coordinate the review but must never inspect its own work and declare a pass.

`reviewRounds` counts distinct Reviewer children, not fix commits. Record the returned lowercase `bc-<UUID>` child ID and round 1 or 2 in `qualityGates.submissionReady.review`, with `status: running`, `startedAt`, and null `finishedAt`, `reviewedCommit`, and `verdict`. Give the child the exact `buildId`; never ask it to review an uncommitted tree, branch tip, or later metadata commit.

The child must return exactly one explicit `PASS` or `BLOCKERS` verdict for that commit. On completion, record `status: completed`, timestamps, `reviewedCommit` equal to the commit actually reviewed, and that verdict. Then:

- `PASS`: the gate may become `passed` and the lifecycle may become `SUBMISSION_READY` only if validation succeeds.
- `BLOCKERS`: keep lifecycle `FINAL_REVIEW`, set the gate to `blocked`, and never claim `SUBMISSION_READY`. Commit fixes and checks, use the new immutable commit as `buildId`, and ask the same child to re-review that exact commit without incrementing the round.
- If the same child cannot continue, create at most one replacement fresh Reviewer child and advance to round 2. After round 2, fail closed with `FINAL_REVIEW`/`blocked`; do not create a third child or self-certify.

Record:

- test evidence;
- one `artifact` evidence record for every Plan-bound requirement ID, with matching kind and a real locator;
- the structured Reviewer child run, exact reviewed commit, and explicit verdict for the final round;
- the same reviewed artifact/code commit SHA in `buildId` and every submission-ready evidence record.

After a genuine Reviewer `PASS`, the `SUBMISSION_READY` state update must be a metadata-only commit; its newer commit SHA is deliberately not `buildId` and must not replace the artifact evidence binding. Mark `builderRun.status` as `completed`, set its `finishedAt` no earlier than the Reviewer finish, set both gates passed, advance to terminal `SUBMISSION_READY`, and re-run `python3 scripts/validate-project-state.py --repo-root .`.

## Terminal handoff

At `SUBMISSION_READY`, report the artifact/evidence locations and any user-only final actions, then stop all project automation. Do not request another approval command, start another run, merge automatically, register, accept terms, publish, submit, or keep a recurring project job alive. A judging URL may remain on-demand/scale-to-zero only when the approved artifact contract requires it; it must not continue scheduled processing.

## Exceptional pauses only

- Pause only for a genuine external blocker such as unavailable required credentials/service, OAuth/OTP/CAPTCHA, paid action, or an action legally reserved for the user.
- Mainnet signatures, gas, funds, purchases, account creation, legal terms, KYC, tax, payment, publication, and final competition submission remain explicit user actions.
- Never access organization repo-creation credentials or copy a competing/winner repository.
