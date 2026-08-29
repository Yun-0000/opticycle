#!/usr/bin/env python3
"""Bind a pre-Build PLAN.md revision to durable state, or finalize it.

This command never approves a Plan and never starts Builder. It only runs while
the project is at PLAN_PENDING_APPROVAL. A normal update requires PLAN.md bytes
to have changed; --finalize may bind the current bytes and prints the one exact
approval command for a later, separate Project Root follow-up.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_validator():
    path = Path(__file__).with_name("validate-project-state.py")
    spec = importlib.util.spec_from_file_location("validate_project_state", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _lock_path(repo_root: Path) -> Path:
    git_entry = repo_root / ".git"
    if git_entry.is_dir():
        return git_entry / "hackathon-builder-approval.lock"
    if git_entry.is_file():
        lines = git_entry.read_text(encoding="utf-8").splitlines()
        if not lines or not lines[0].startswith("gitdir: "):
            raise ValueError(".git file does not contain a gitdir pointer")
        git_dir = Path(lines[0][len("gitdir: ") :])
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


def _requirements(plan_text: str) -> list[dict[str, str]]:
    errors: list[str] = []
    requirements = VALIDATOR._plan_requirements(plan_text, errors)
    if errors:
        raise ValueError("; ".join(errors))
    if not requirements:
        raise ValueError("PLAN.md must declare at least one artifact requirement")
    return requirements


def apply_plan_update(
    repo_root: Path,
    *,
    finalize: bool = False,
    now: str | None = None,
) -> tuple[str, str]:
    """Update the pending Plan binding and return (event_id, latest_sha)."""

    repo_root = repo_root.resolve()
    plan_path = repo_root / "PLAN.md"
    state_path = repo_root / ".hackathon" / "state.json"
    lock_path = _lock_path(repo_root)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            original_state = state_path.read_bytes()
            state: Any = json.loads(original_state)
            if not isinstance(state, dict):
                raise ValueError("state root must be an object")
            if state.get("state") != "PLAN_PENDING_APPROVAL":
                raise ValueError("Plan updates require PLAN_PENDING_APPROVAL; Plan is immutable once BUILDING starts")
            if state.get("planApproval") is not None or state.get("builderRun") is not None:
                raise ValueError("pending Plan updates require null planApproval and builderRun")
            if state.get("buildId") is not None:
                raise ValueError("pending Plan updates require null buildId")

            plan_bytes = plan_path.read_bytes()
            try:
                plan_text = plan_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"PLAN.md must be UTF-8: {exc}") from exc
            latest_sha = hashlib.sha256(plan_bytes).hexdigest()
            previous_sha = state.get("planSha256")
            if not finalize and latest_sha == previous_sha:
                raise ValueError("a Plan revision must change the exact PLAN.md bytes")

            state["planSha256"] = latest_sha
            state["artifactRequirements"] = _requirements(plan_text)
            state["updatedAt"] = now or _now()
            candidate = f"{json.dumps(state, indent=2, ensure_ascii=False)}\n".encode()
            _atomic_replace_bytes(state_path, candidate)
            errors = VALIDATOR.validate_repository(repo_root)
            if errors:
                raise ValueError("; ".join(errors))
            event_id = state.get("eventId")
            if not isinstance(event_id, str):
                raise ValueError("eventId must be a string")
            return event_id, latest_sha
        except Exception:
            if "original_state" in locals():
                _atomic_replace_bytes(state_path, original_state)
            raise
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Bind current Plan bytes and print approval command without approving or starting Builder",
    )
    args = parser.parse_args(argv)
    try:
        event_id, latest_sha = apply_plan_update(
            args.repo_root,
            finalize=args.finalize,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.finalize:
        print(f"APPROVE PLAN {event_id} {latest_sha}")
    else:
        print(
            json.dumps(
                {"status": "PLAN_UPDATED", "eventId": event_id, "planSha256": latest_sha},
                separators=(",", ":"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
