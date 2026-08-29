#!/usr/bin/env python3
"""Validate PLAN.md and .hackathon/state.json without third-party packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


STATES = (
    "PLAN_PENDING_APPROVAL",
    "BUILDING",
    "FINAL_REVIEW",
    "SUBMISSION_READY",
)
STATE_INDEX = {name: index for index, name in enumerate(STATES)}
GATE_STATUSES = {"pending", "running", "passed", "failed", "blocked"}
EVIDENCE_TYPES = {"command", "test", "artifact"}
ARTIFACT_KINDS = {
    "repository",
    "url",
    "game_build",
    "installable",
    "video",
    "document",
    "integration",
    "demo",
    "other",
}
ARTIFACT_SOURCES = {"event_rules", "approved_plan"}
EVENT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
COMMIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")
REVIEWER_CHILD_ID_RE = re.compile(
    r"^bc-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$")
PLACEHOLDER_RE = re.compile(r"\[REDACTED\]|placeholder", re.IGNORECASE)
REQUIREMENTS_BLOCK_RE = re.compile(
    r"```hackathon-artifact-requirements[ \t]*\r?\n(.*?)\r?\n```",
    re.DOTALL,
)


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_state(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"cannot read {path}: {exc}"]
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        return None, [f"invalid state JSON: {exc}"]
    if not isinstance(value, dict):
        return None, ["state root must be a JSON object"]
    return value, []


def _fields(value: Any, path: str, required: set[str], errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return None
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required)
    if missing:
        errors.append(f"{path} missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"{path} has unknown fields: {', '.join(unknown)}")
    return value


def _timestamp(value: Any, path: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        errors.append(f"{path} must be a timezone-aware ISO 8601 timestamp")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path} must be a valid ISO 8601 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{path} must include a UTC offset")
        return None
    return parsed


def _reject_placeholder(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, str) and PLACEHOLDER_RE.search(value):
        errors.append(f"{path} must not contain a [REDACTED] or placeholder literal")


def _https_url(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{path} must be an HTTPS URL")
        return
    _reject_placeholder(value, path, errors)
    try:
        parsed = urlparse(value)
    except ValueError:
        errors.append(f"{path} must be an HTTPS URL")
        return
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        errors.append(f"{path} must be an HTTPS URL without credentials")


def _commit_sha(value: Any, path: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not COMMIT_SHA_RE.fullmatch(value):
        errors.append(f"{path} must be a 40-character lowercase commit SHA")
        return None
    return value


def _reachable_commit(repo_root: Path, commit: str, path: str, errors: list[str]) -> None:
    exists = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", f"{commit}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode != 0:
        errors.append(f"{path} must identify a commit present in this repository")
        return
    ancestor = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", commit, "HEAD"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if ancestor.returncode != 0:
        errors.append(f"{path} must be an ancestor of the current repository HEAD")


def _exit_code(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path} must be an integer")
    elif value != 0:
        errors.append(f"{path} must be 0 for successful evidence")


def _artifact_requirements(value: Any, path: str, errors: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        errors.append(f"{path} must be an array")
        return []
    requirements: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        obj = _fields(item, item_path, {"id", "kind", "source", "description"}, errors)
        if obj is None:
            continue
        requirement_id = obj.get("id")
        if not isinstance(requirement_id, str) or not EVENT_ID_RE.fullmatch(requirement_id):
            errors.append(f"{item_path}.id must be a lowercase DNS-style slug")
        elif requirement_id in seen:
            errors.append(f"{path} contains duplicate requirement id {requirement_id!r}")
        else:
            seen.add(requirement_id)
        kind = obj.get("kind")
        if not isinstance(kind, str) or kind not in ARTIFACT_KINDS:
            errors.append(f"{item_path}.kind is not an allowed artifact kind")
        source = obj.get("source")
        if not isinstance(source, str) or source not in ARTIFACT_SOURCES:
            errors.append(f"{item_path}.source must be event_rules or approved_plan")
        description = obj.get("description")
        if not isinstance(description, str) or not description.strip() or len(description) > 500:
            errors.append(f"{item_path}.description must be 1-500 non-whitespace characters")
        for key in ("id", "description"):
            _reject_placeholder(obj.get(key), f"{item_path}.{key}", errors)
        requirements.append(
            {
                "id": requirement_id if isinstance(requirement_id, str) else "",
                "kind": kind if isinstance(kind, str) else "",
                "source": source if isinstance(source, str) else "",
                "description": description if isinstance(description, str) else "",
            }
        )
    return requirements


def _plan_requirements(plan_text: str, errors: list[str]) -> list[dict[str, str]]:
    blocks = REQUIREMENTS_BLOCK_RE.findall(plan_text)
    if len(blocks) != 1:
        errors.append(
            "PLAN.md must contain exactly one ```hackathon-artifact-requirements JSON block"
        )
        return []
    try:
        value = json.loads(blocks[0], object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        errors.append(f"PLAN.md artifact requirements JSON is invalid: {exc}")
        return []
    return _artifact_requirements(value, "PLAN.md artifactRequirements", errors)


def _evidence(value: Any, path: str, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{path} must be an array")
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path} must be an object")
            continue
        kind = item.get("type")
        if not isinstance(kind, str) or kind not in EVIDENCE_TYPES:
            errors.append(f"{item_path}.type is not an allowed evidence type")
            continue
        common = {"type", "commitSha", "timestamp", "checkedBy"}
        extra = {
            "command": {"command", "exitCode"},
            "test": {"name", "exitCode"},
            "artifact": {"requirementId", "kind", "locator"},
        }[kind]
        obj = _fields(item, item_path, common | extra, errors)
        if obj is None:
            continue
        commit = _commit_sha(obj.get("commitSha"), f"{item_path}.commitSha", errors)
        timestamp = _timestamp(obj.get("timestamp"), f"{item_path}.timestamp", errors)
        checked_by = obj.get("checkedBy")
        if not isinstance(checked_by, str) or not checked_by.strip() or len(checked_by) > 128:
            errors.append(f"{item_path}.checkedBy must be a non-empty identifier")
        _reject_placeholder(checked_by, f"{item_path}.checkedBy", errors)
        record: dict[str, Any] = {
            "type": kind,
            "commitSha": commit,
            "timestamp": timestamp,
            "checkedBy": checked_by,
        }
        if kind == "command":
            command = obj.get("command")
            if not isinstance(command, str) or not command.strip():
                errors.append(f"{item_path}.command must be a non-empty string")
            _reject_placeholder(command, f"{item_path}.command", errors)
            _exit_code(obj.get("exitCode"), f"{item_path}.exitCode", errors)
        elif kind == "test":
            name = obj.get("name")
            if not isinstance(name, str) or not name.strip():
                errors.append(f"{item_path}.name must be a non-empty string")
            _reject_placeholder(name, f"{item_path}.name", errors)
            _exit_code(obj.get("exitCode"), f"{item_path}.exitCode", errors)
        elif kind == "artifact":
            requirement_id = obj.get("requirementId")
            if not isinstance(requirement_id, str) or not EVENT_ID_RE.fullmatch(requirement_id):
                errors.append(f"{item_path}.requirementId must be a lowercase DNS-style slug")
            artifact_kind = obj.get("kind")
            if not isinstance(artifact_kind, str) or artifact_kind not in ARTIFACT_KINDS:
                errors.append(f"{item_path}.kind is not an allowed artifact kind")
            locator = obj.get("locator")
            if not isinstance(locator, str) or not locator.strip() or len(locator) > 2048:
                errors.append(f"{item_path}.locator must be 1-2048 non-whitespace characters")
            _reject_placeholder(locator, f"{item_path}.locator", errors)
            if artifact_kind in {"url", "repository"}:
                _https_url(locator, f"{item_path}.locator", errors)
            elif isinstance(locator, str) and "://" in locator:
                _https_url(locator, f"{item_path}.locator", errors)
            record.update(
                requirementId=requirement_id,
                kind=artifact_kind,
                locator=locator,
            )
        result.append(record)
    return result


def _reviewer_run(value: Any, path: str, errors: list[str]) -> dict[str, Any] | None:
    if value is None:
        return None
    obj = _fields(
        value,
        path,
        {
            "childId",
            "round",
            "status",
            "startedAt",
            "finishedAt",
            "reviewedCommit",
            "verdict",
        },
        errors,
    )
    if obj is None:
        return None
    child_id = obj.get("childId")
    if not isinstance(child_id, str) or not REVIEWER_CHILD_ID_RE.fullmatch(child_id):
        errors.append(f"{path}.childId must be a lowercase bc- UUID")
    _reject_placeholder(child_id, f"{path}.childId", errors)
    review_round = obj.get("round")
    if isinstance(review_round, bool) or review_round not in (1, 2):
        errors.append(f"{path}.round must be 1 or 2")
    status = obj.get("status")
    if status not in {"running", "completed"}:
        errors.append(f"{path}.status must be running or completed")
    started_raw = obj.get("startedAt")
    started_at = None
    if started_raw is not None:
        started_at = _timestamp(started_raw, f"{path}.startedAt", errors)
    finished_raw = obj.get("finishedAt")
    finished_at = None
    if finished_raw is not None:
        finished_at = _timestamp(finished_raw, f"{path}.finishedAt", errors)
    reviewed_raw = obj.get("reviewedCommit")
    reviewed_commit = None
    if reviewed_raw is not None:
        reviewed_commit = _commit_sha(reviewed_raw, f"{path}.reviewedCommit", errors)
    verdict = obj.get("verdict")
    if status == "running":
        if started_raw is None:
            errors.append(f"{path}.startedAt is required while running")
        if finished_raw is not None:
            errors.append(f"{path}.finishedAt must be null while running")
        if reviewed_raw is not None:
            errors.append(f"{path}.reviewedCommit must be null while running")
        if verdict is not None:
            errors.append(f"{path}.verdict must be null while running")
    elif status == "completed":
        if finished_raw is None:
            errors.append(f"{path}.finishedAt is required when completed")
        if reviewed_raw is None:
            errors.append(f"{path}.reviewedCommit is required when completed")
        if verdict not in {"PASS", "BLOCKERS"}:
            errors.append(f"{path}.verdict must be PASS or BLOCKERS when completed")
    if started_at and finished_at and finished_at < started_at:
        errors.append(f"{path}.finishedAt must not precede startedAt")
    return {
        "childId": child_id,
        "round": review_round,
        "status": status,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "reviewedCommit": reviewed_commit,
        "verdict": verdict,
    }


def _gate(value: Any, path: str, errors: list[str], *, submission: bool = False) -> dict[str, Any]:
    required = {"status", "checkedAt", "evidence"}
    if submission:
        required.update({"reviewRounds", "review"})
    obj = _fields(value, path, required, errors) or {}
    status = obj.get("status")
    checked_at_raw = obj.get("checkedAt")
    if not isinstance(status, str) or status not in GATE_STATUSES:
        errors.append(f"{path}.status is not an allowed gate status")
    checked_at = None
    if checked_at_raw is not None:
        checked_at = _timestamp(checked_at_raw, f"{path}.checkedAt", errors)
    evidence = _evidence(obj.get("evidence"), f"{path}.evidence", errors)
    if status == "pending":
        if checked_at_raw is not None:
            errors.append(f"{path}.checkedAt must be null while pending")
        if evidence:
            errors.append(f"{path}.evidence must be empty while pending")
    elif isinstance(status, str) and status in GATE_STATUSES and checked_at_raw is None:
        errors.append(f"{path}.checkedAt is required once the gate is not pending")
    if status == "passed" and not evidence:
        errors.append(f"{path}.evidence is required when the gate passed")

    review_rounds = obj.get("reviewRounds") if submission else None
    review = _reviewer_run(obj.get("review"), f"{path}.review", errors) if submission else None
    if submission:
        if isinstance(review_rounds, bool) or not isinstance(review_rounds, int):
            errors.append(f"{path}.reviewRounds must be an integer")
        elif not 0 <= review_rounds <= 2:
            errors.append(f"{path}.reviewRounds must be between 0 and 2")
        if status == "pending" and review_rounds != 0:
            errors.append(f"{path}.reviewRounds must be 0 while pending")
        if status == "pending" and review is not None:
            errors.append(f"{path}.review must be null while pending")
        if status in {"running", "passed", "blocked"} and review is None:
            errors.append(f"{path}.review is required once final review starts")
        if status == "passed" and review_rounds not in (1, 2):
            errors.append(f"{path}.reviewRounds must be 1 or 2 when passed")
        if review is not None:
            if review_rounds != review["round"]:
                errors.append(f"{path}.reviewRounds must equal review.round")
            if review["status"] == "running":
                if status != "running":
                    errors.append(f"{path}.status must be running while review is running")
                if checked_at != review["startedAt"]:
                    errors.append(f"{path}.checkedAt must equal review.startedAt while running")
            elif review["status"] == "completed":
                expected_status = "passed" if review["verdict"] == "PASS" else "blocked"
                if status != expected_status:
                    errors.append(
                        f"{path}.status must be {expected_status} for reviewer verdict {review['verdict']}"
                    )
                if checked_at != review["finishedAt"]:
                    errors.append(f"{path}.checkedAt must equal review.finishedAt when completed")
    return {
        "status": status,
        "checkedAt": checked_at,
        "evidence": evidence,
        "reviewRounds": review_rounds,
        "review": review,
    }


def _approval(value: Any, errors: list[str], *, event_id: Any, plan_sha: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    obj = _fields(value, "planApproval", {"command", "eventId", "planSha256", "approvedAt"}, errors)
    if obj is None:
        return None
    if obj.get("eventId") != event_id:
        errors.append("planApproval.eventId must match eventId")
    if obj.get("planSha256") != plan_sha:
        errors.append("planApproval.planSha256 must match planSha256")
    expected = f"APPROVE PLAN {event_id} {plan_sha}"
    if obj.get("command") != expected:
        errors.append(f"planApproval.command must exactly equal {expected!r}")
    _reject_placeholder(obj.get("command"), "planApproval.command", errors)
    return {"approvedAt": _timestamp(obj.get("approvedAt"), "planApproval.approvedAt", errors)}


def builder_idempotency_key(event_id: Any, plan_sha: Any) -> str:
    return f"builder-v3:{event_id}:{plan_sha}"


def _builder_run(value: Any, errors: list[str], *, event_id: Any, plan_sha: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    obj = _fields(
        value,
        "builderRun",
        {"idempotencyKey", "attempt", "status", "startedAt", "finishedAt"},
        errors,
    )
    if obj is None:
        return None
    expected_key = builder_idempotency_key(event_id, plan_sha)
    if obj.get("idempotencyKey") != expected_key:
        errors.append("builderRun.idempotencyKey must be bound to eventId and planSha256")
    if obj.get("attempt") != 1 or isinstance(obj.get("attempt"), bool):
        errors.append("builderRun.attempt must equal 1")
    status = obj.get("status")
    if status not in {"running", "completed", "blocked"}:
        errors.append("builderRun.status must be running, completed, or blocked")
    started_at = _timestamp(obj.get("startedAt"), "builderRun.startedAt", errors)
    finished_raw = obj.get("finishedAt")
    finished_at = None
    if finished_raw is not None:
        finished_at = _timestamp(finished_raw, "builderRun.finishedAt", errors)
    if status == "running" and finished_raw is not None:
        errors.append("builderRun.finishedAt must be null while running")
    if status in {"completed", "blocked"} and finished_raw is None:
        errors.append("builderRun.finishedAt is required when completed or blocked")
    if started_at and finished_at and finished_at < started_at:
        errors.append("builderRun.finishedAt must not precede startedAt")
    return {"status": status, "startedAt": started_at, "finishedAt": finished_at}


def validate_repository(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    state_path = repo_root / ".hackathon" / "state.json"
    plan_path = repo_root / "PLAN.md"
    state, errors = _read_state(state_path)
    if state is None:
        return errors
    try:
        plan_bytes = plan_path.read_bytes()
        plan_text = plan_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read UTF-8 {plan_path}: {exc}")
        return errors
    actual_plan_sha = hashlib.sha256(plan_bytes).hexdigest()

    required = {
        "schemaVersion",
        "eventId",
        "state",
        "planSha256",
        "artifactRequirements",
        "buildId",
        "planApproval",
        "builderRun",
        "qualityGates",
        "updatedAt",
    }
    _fields(state, "state", required, errors)
    if state.get("schemaVersion") != 5:
        errors.append("schemaVersion must equal 5")

    event_id = state.get("eventId")
    if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
        errors.append("eventId must be a lowercase DNS-style slug")
    _reject_placeholder(event_id, "eventId", errors)
    lifecycle = state.get("state")
    if not isinstance(lifecycle, str) or lifecycle not in STATE_INDEX:
        errors.append("state is not an allowed lifecycle state")
    stage = STATE_INDEX.get(lifecycle, -1) if isinstance(lifecycle, str) else -1

    plan_sha = state.get("planSha256")
    if plan_sha is not None and (
        not isinstance(plan_sha, str) or not SHA256_RE.fullmatch(plan_sha)
    ):
        errors.append("planSha256 must be null or exactly 64 lowercase hex characters")
    if plan_sha is not None and plan_sha != actual_plan_sha:
        errors.append("planSha256 does not match the exact PLAN.md bytes")
    if stage >= STATE_INDEX["PLAN_PENDING_APPROVAL"] and plan_sha is None:
        errors.append("planSha256 is required from PLAN_PENDING_APPROVAL onward")

    requirements = _artifact_requirements(
        state.get("artifactRequirements"), "artifactRequirements", errors
    )
    plan_requirements = _plan_requirements(plan_text, errors)
    if requirements != plan_requirements:
        errors.append("artifactRequirements must exactly match the Plan-bound JSON block")
    if stage >= STATE_INDEX["PLAN_PENDING_APPROVAL"] and not requirements:
        errors.append("at least one Plan-bound artifact requirement is required")

    build_id = state.get("buildId")
    if build_id is not None and (
        not isinstance(build_id, str) or not COMMIT_SHA_RE.fullmatch(build_id)
    ):
        errors.append("buildId must be null or the reviewed artifact/code commit SHA")
    elif isinstance(build_id, str):
        _reachable_commit(repo_root, build_id, "buildId", errors)

    updated_at = _timestamp(state.get("updatedAt"), "updatedAt", errors)
    quality_gates = _fields(
        state.get("qualityGates"), "qualityGates", {"mvp", "submissionReady"}, errors
    ) or {}
    mvp = _gate(quality_gates.get("mvp"), "qualityGates.mvp", errors)
    submission = _gate(
        quality_gates.get("submissionReady"),
        "qualityGates.submissionReady",
        errors,
        submission=True,
    )
    plan_approval = _approval(
        state.get("planApproval"), errors, event_id=event_id, plan_sha=plan_sha
    )
    builder_run = _builder_run(
        state.get("builderRun"), errors, event_id=event_id, plan_sha=plan_sha
    )

    building_stage = STATE_INDEX["BUILDING"]
    review_stage = STATE_INDEX["FINAL_REVIEW"]
    ready_stage = STATE_INDEX["SUBMISSION_READY"]

    if 0 <= stage < building_stage:
        if plan_approval is not None:
            errors.append("planApproval must be null before the dedicated Builder run starts")
        if builder_run is not None:
            errors.append("builderRun must be null before exact Plan approval")
        if build_id is not None:
            errors.append("buildId must be null before FINAL_REVIEW")
        if mvp["status"] != "pending" or submission["status"] != "pending":
            errors.append("quality gates must remain pending before the Builder run starts")
    elif stage >= building_stage:
        if plan_approval is None:
            errors.append("BUILDING and later states require exact Plan approval")
        if builder_run is None:
            errors.append("BUILDING and later states require the single Plan-bound builderRun")

    if building_stage <= stage < review_stage:
        if build_id is not None:
            errors.append("buildId must remain null before FINAL_REVIEW")
    if building_stage <= stage < ready_stage:
        if builder_run and builder_run["status"] not in {"running", "blocked"}:
            errors.append("builderRun must be running or blocked before SUBMISSION_READY")
    if stage == building_stage and submission["status"] != "pending":
        errors.append("submissionReady gate must remain pending while the MVP is still building")
    if stage >= review_stage and mvp["status"] != "passed":
        errors.append("FINAL_REVIEW and later states require the MVP gate passed")
    if stage == review_stage and submission["status"] == "pending":
        errors.append("FINAL_REVIEW requires the submissionReady gate to have started")
    if submission["status"] == "passed" and stage != ready_stage:
        errors.append("state must advance directly to terminal SUBMISSION_READY when final review passes")

    if mvp["status"] == "passed" and not any(
        evidence.get("type") == "test" for evidence in mvp["evidence"]
    ):
        errors.append("a passed MVP gate requires test evidence")

    if stage >= review_stage:
        if build_id is None:
            errors.append("FINAL_REVIEW and later states require an immutable buildId commit")
        evidence = submission["evidence"]
        if not any(item.get("type") == "test" for item in evidence):
            errors.append("FINAL_REVIEW and later states require submission test evidence")

        requirement_by_id = {item["id"]: item for item in requirements}
        artifacts: dict[str, dict[str, Any]] = {}
        for item in evidence:
            if item.get("type") != "artifact":
                continue
            requirement_id = item.get("requirementId")
            if requirement_id in artifacts:
                errors.append(f"duplicate artifact evidence for requirement {requirement_id!r}")
                continue
            artifacts[requirement_id] = item
            expected = requirement_by_id.get(requirement_id)
            if expected is None:
                errors.append(f"artifact evidence references unknown requirement {requirement_id!r}")
            elif item.get("kind") != expected["kind"]:
                errors.append(
                    f"artifact evidence kind for {requirement_id!r} must match the approved Plan"
                )
        for requirement_id in requirement_by_id:
            if requirement_id not in artifacts:
                errors.append(
                    f"FINAL_REVIEW and later states require artifact evidence for {requirement_id!r}"
                )
        for item in evidence:
            commit = item.get("commitSha")
            if build_id is not None and commit is not None and commit != build_id:
                errors.append("all final-review evidence must bind to buildId/artifact commit")

        review = submission["review"]
        if review and review["status"] == "completed":
            if build_id is not None and review["reviewedCommit"] != build_id:
                errors.append("completed review.reviewedCommit must exactly equal buildId")
        if review and review["startedAt"] and mvp["checkedAt"]:
            if review["startedAt"] < mvp["checkedAt"]:
                errors.append("review.startedAt must not precede the passed MVP gate")
        if review:
            review_boundary = (
                review["startedAt"]
                if review["status"] == "running"
                else review["finishedAt"]
            )
            if review_boundary:
                for index, item in enumerate(evidence):
                    timestamp = item.get("timestamp")
                    if timestamp and timestamp > review_boundary:
                        errors.append(
                            "qualityGates.submissionReady."
                            f"evidence[{index}].timestamp must not be later than the Reviewer check"
                        )

    if stage == ready_stage:
        if mvp["status"] != "passed" or submission["status"] != "passed":
            errors.append("SUBMISSION_READY requires both quality gates passed")
        if not builder_run or builder_run["status"] != "completed":
            errors.append("SUBMISSION_READY requires the single builderRun completed")
        review = submission["review"]
        if not review or review["status"] != "completed" or review["verdict"] != "PASS":
            errors.append("SUBMISSION_READY requires a completed fresh Reviewer PASS")

    time_fields = [
        ("planApproval.approvedAt", plan_approval and plan_approval["approvedAt"]),
        ("builderRun.startedAt", builder_run and builder_run["startedAt"]),
        ("builderRun.finishedAt", builder_run and builder_run["finishedAt"]),
        ("qualityGates.mvp.checkedAt", mvp["checkedAt"]),
        ("qualityGates.submissionReady.checkedAt", submission["checkedAt"]),
        ("qualityGates.submissionReady.review.startedAt", submission["review"] and submission["review"]["startedAt"]),
        ("qualityGates.submissionReady.review.finishedAt", submission["review"] and submission["review"]["finishedAt"]),
    ]
    if plan_approval and builder_run:
        approved_at = plan_approval["approvedAt"]
        started_at = builder_run["startedAt"]
        if approved_at and started_at and started_at < approved_at:
            errors.append("builderRun.startedAt must not precede Plan approval")
    if updated_at:
        for path, timestamp in time_fields:
            if timestamp and timestamp > updated_at:
                errors.append(f"{path} must not be later than updatedAt")
        for gate_name, gate in (("mvp", mvp), ("submissionReady", submission)):
            for index, item in enumerate(gate["evidence"]):
                timestamp = item.get("timestamp")
                if timestamp and timestamp > updated_at:
                    errors.append(
                        f"qualityGates.{gate_name}.evidence[{index}].timestamp must not be later than updatedAt"
                    )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    errors = validate_repository(args.repo_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Project state is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
