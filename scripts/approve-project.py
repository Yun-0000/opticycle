#!/usr/bin/env python3
"""Record the one exact Plan approval and atomically claim the Builder run.

Run this only inside the approval-triggered follow-up run of the same Cursor
Project Root conversation. Ordinary chat, PR comments, and hand-edited state
are not authorization. A replay is side-effect free and reports that the
single Plan-bound Builder run already started.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


COMMAND_RE = re.compile(
    r"^APPROVE PLAN ([a-z0-9]+(?:-[a-z0-9]+)*) ([a-f0-9]{64})$"
)


def _load_validator():
    path = Path(__file__).with_name("validate-project-state.py")
    spec = importlib.util.spec_from_file_location("validate_project_state", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


class ApprovalResult:
    __slots__ = ("status", "idempotency_key")

    def __init__(
        self,
        status: Literal["BUILDER_STARTED", "BUILDER_ALREADY_STARTED"],
        idempotency_key: str,
    ) -> None:
        self.status = status
        self.idempotency_key = idempotency_key


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validated_state(repo_root: Path) -> dict[str, Any]:
    errors = VALIDATOR.validate_repository(repo_root)
    if errors:
        raise ValueError("; ".join(errors))
    state = json.loads((repo_root / ".hackathon" / "state.json").read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("state root must be an object")
    return state


def _lock_path(repo_root: Path) -> Path:
    git_entry = repo_root / ".git"
    if git_entry.is_dir():
        return git_entry / "hackathon-builder-approval.lock"
    if git_entry.is_file():
        lines = git_entry.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise ValueError(".git file is empty")
        first_line = lines[0]
        prefix = "gitdir: "
        if not first_line.startswith(prefix):
            raise ValueError(".git file does not contain a gitdir pointer")
        git_dir = Path(first_line[len(prefix) :])
        if not git_dir.is_absolute():
            git_dir = (repo_root / git_dir).resolve()
        if not git_dir.is_dir():
            raise ValueError("gitdir pointer does not resolve to a directory")
        return git_dir / "hackathon-builder-approval.lock"
    raise ValueError("repo root must contain a .git directory or gitdir file")


def _atomic_replace_bytes(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".state.json.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def apply_approval(repo_root: Path, command: str, now: str | None = None) -> ApprovalResult:
    exact_command = command
    match = COMMAND_RE.fullmatch(exact_command)
    if not match:
        raise ValueError("command must be exactly APPROVE PLAN <eventId> <plan_sha>")
    event_id, binding = match.group(1), match.group(2)
    repo_root = repo_root.resolve()
    state_path = repo_root / ".hackathon" / "state.json"
    lock_path = _lock_path(repo_root)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            # Read and validate only after the cross-process lock is held. A
            # concurrent follow-up must observe the first claim, never the old
            # PLAN_PENDING_APPROVAL bytes.
            original = state_path.read_bytes()
            state = _validated_state(repo_root)
            if state.get("eventId") != event_id:
                raise ValueError("eventId does not match the approval command")
            plan_sha = hashlib.sha256((repo_root / "PLAN.md").read_bytes()).hexdigest()
            if binding != plan_sha or state.get("planSha256") != plan_sha:
                raise ValueError("plan_sha does not match PLAN.md and state.planSha256")
            idempotency_key = VALIDATOR.builder_idempotency_key(event_id, plan_sha)

            existing_approval = state.get("planApproval")
            existing_run = state.get("builderRun")
            if (
                state.get("state")
                in {"BUILDING", "FINAL_REVIEW", "SUBMISSION_READY"}
                and isinstance(existing_approval, dict)
                and existing_approval.get("command") == exact_command
                and isinstance(existing_run, dict)
                and existing_run.get("idempotencyKey") == idempotency_key
                and existing_run.get("attempt") == 1
            ):
                return ApprovalResult("BUILDER_ALREADY_STARTED", idempotency_key)
            if state.get("state") != "PLAN_PENDING_APPROVAL":
                raise ValueError("Plan approval requires PLAN_PENDING_APPROVAL")

            timestamp = now or _now()
            state["state"] = "BUILDING"
            state["planApproval"] = {
                "command": exact_command,
                "eventId": event_id,
                "planSha256": plan_sha,
                "approvedAt": timestamp,
            }
            state["builderRun"] = {
                "idempotencyKey": idempotency_key,
                "attempt": 1,
                "status": "running",
                "startedAt": timestamp,
                "finishedAt": None,
            }
            state["updatedAt"] = timestamp
            candidate = f"{json.dumps(state, indent=2, ensure_ascii=False)}\n".encode()
            _atomic_replace_bytes(state_path, candidate)
            errors = VALIDATOR.validate_repository(repo_root)
            if errors:
                raise ValueError("; ".join(errors))
            return ApprovalResult("BUILDER_STARTED", idempotency_key)
        except Exception:
            if "original" in locals():
                _atomic_replace_bytes(state_path, original)
            raise
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("command", nargs="+", help="Exact APPROVE PLAN command")
    args = parser.parse_args(argv)
    try:
        result = apply_approval(args.repo_root, " ".join(args.command))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": result.status,
                "builderIdempotencyKey": result.idempotency_key,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
