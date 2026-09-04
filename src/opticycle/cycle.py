"""Durable fail-closed cycle state machine (Gate 8).

SQLite is the source of truth for cycle identity. Restart recovers the same
cycle, payload, and client_order_id. Unknown broker state forbids a new cycle.
There is no CLI path, no resubmit with a new client id, and no channel switch.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from opticycle.protocol import (
    CanonicalOrderPayload,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
    RiskCertificate,
    parse_occ_symbol,
)


class CycleState(str, Enum):
    OBSERVED = "OBSERVED"
    THESIS_READY = "THESIS_READY"
    CANDIDATES_READY = "CANDIDATES_READY"
    VETOED = "VETOED"
    AUTHORIZED = "AUTHORIZED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"
    COMPLETED = "COMPLETED"
    HALTED = "HALTED"


TERMINAL_STATES = frozenset({CycleState.VETOED, CycleState.COMPLETED, CycleState.HALTED})
POST_SUBMIT_STATES = frozenset(
    {CycleState.SUBMITTING, CycleState.ACKNOWLEDGED, CycleState.RECONCILING}
)

LEGAL_EDGES: dict[CycleState, frozenset[CycleState]] = {
    CycleState.OBSERVED: frozenset(
        {CycleState.THESIS_READY, CycleState.VETOED, CycleState.HALTED}
    ),
    CycleState.THESIS_READY: frozenset(
        {CycleState.CANDIDATES_READY, CycleState.VETOED, CycleState.HALTED}
    ),
    CycleState.CANDIDATES_READY: frozenset(
        {CycleState.AUTHORIZED, CycleState.VETOED, CycleState.HALTED}
    ),
    CycleState.AUTHORIZED: frozenset({CycleState.SUBMITTING, CycleState.HALTED}),
    CycleState.SUBMITTING: frozenset({CycleState.ACKNOWLEDGED, CycleState.HALTED}),
    CycleState.ACKNOWLEDGED: frozenset(
        {CycleState.RECONCILING, CycleState.RECONCILED, CycleState.HALTED}
    ),
    CycleState.RECONCILING: frozenset(
        {CycleState.RECONCILED, CycleState.HALTED}
    ),
    CycleState.RECONCILED: frozenset({CycleState.COMPLETED, CycleState.HALTED}),
    CycleState.VETOED: frozenset(),
    CycleState.COMPLETED: frozenset(),
    CycleState.HALTED: frozenset(),
}


class CycleError(Exception):
    """Base error for the durable cycle engine."""


class IllegalTransition(CycleError):
    """State jump that is not on the legal edge set."""


class DuplicateTransition(CycleError):
    """The same transition was applied twice."""


class StaleCertificate(CycleError):
    """Certificate does not bind this payload, is expired, or is reused."""


class CycleHalted(CycleError):
    """New work is forbidden because broker state is unknown or a cycle is active."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state(value: CycleState | str) -> CycleState:
    return value if isinstance(value, CycleState) else CycleState(value)


def payload_to_dict(payload: CanonicalOrderPayload) -> dict[str, Any]:
    return payload.to_canonical_dict()


def payload_from_dict(data: dict[str, Any]) -> CanonicalOrderPayload:
    raw = dict(data)
    legs: list[OptionLegSpec] = []
    for item in raw["legs"]:
        symbol = str(item["symbol"]).upper()
        _root, expiration, occ_type, occ_strike = parse_occ_symbol(symbol)
        option_type = OptionType(item["option_type"]) if item.get("option_type") else occ_type
        strike = Decimal(str(item.get("strike_price") or occ_strike))
        if item.get("expiration"):
            expiration = datetime.strptime(str(item["expiration"]), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        legs.append(
            OptionLegSpec(
                symbol=symbol,
                ratio_qty=int(item["ratio_qty"]),
                side=OrderSide(str(item["side"]).lower()),
                position_intent=PositionIntent(str(item["position_intent"]).lower()),
                option_type=option_type,
                strike_price=strike,
                expiration=expiration,
            )
        )
    return CanonicalOrderPayload(
        client_order_id=str(raw["client_order_id"]),
        account_id=str(raw["account_id"]),
        underlying=str(raw["underlying"]),
        order_class=str(raw["order_class"]),
        order_type=str(raw["order_type"]),
        time_in_force=str(raw["time_in_force"]),
        qty=int(raw["qty"]),
        limit_price=Decimal(str(raw["limit_price"])),
        legs=tuple(legs),
    )


def certificate_to_dict(certificate: RiskCertificate) -> dict[str, Any]:
    return {
        "account_hash": certificate.account_hash,
        "account_id": certificate.account_id,
        "approval": certificate.approval,
        "binding_hash": certificate.binding_hash,
        "certificate_id": certificate.certificate_id,
        "client_order_id": certificate.client_order_id,
        "cycle_id": certificate.cycle_id,
        "evidence_hash": certificate.evidence_hash,
        "expires_at": certificate.expires_at.isoformat(),
        "issued_at": certificate.issued_at.isoformat(),
        "payload_hash": certificate.payload_hash,
        "reasons": list(certificate.reasons),
        "veto": certificate.veto,
    }


@dataclass(slots=True)
class CycleRecord:
    cycle_id: str
    state: CycleState
    version: int
    client_order_id: str
    snapshot_hash: str | None
    payload_hash: str | None
    certificate_hash: str | None
    certificate_id: str | None
    payload_json: str | None
    certificate_json: str | None
    attempts: int
    broker_order_id: str | None
    broker_status: str | None
    halt_reason: str | None
    replan_reason: str | None
    forbids_new: bool
    created_at: str
    updated_at: str

    def payload(self) -> CanonicalOrderPayload | None:
        if not self.payload_json:
            return None
        loaded = payload_from_dict(json.loads(self.payload_json))
        if self.payload_hash and loaded.payload_hash != self.payload_hash:
            raise CycleError("stored payload hash does not match reconstructed payload")
        if loaded.client_order_id != self.client_order_id:
            raise CycleError("stored payload client_order_id does not match cycle")
        return loaded


def _row_to_record(row: sqlite3.Row) -> CycleRecord:
    return CycleRecord(
        cycle_id=row["cycle_id"],
        state=CycleState(row["state"]),
        version=int(row["version"]),
        client_order_id=row["client_order_id"],
        snapshot_hash=row["snapshot_hash"],
        payload_hash=row["payload_hash"],
        certificate_hash=row["certificate_hash"],
        certificate_id=row["certificate_id"],
        payload_json=row["payload_json"],
        certificate_json=row["certificate_json"],
        attempts=int(row["attempts"]),
        broker_order_id=row["broker_order_id"],
        broker_status=row["broker_status"],
        halt_reason=row["halt_reason"],
        replan_reason=row["replan_reason"],
        forbids_new=bool(row["forbids_new"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    client_order_id TEXT NOT NULL UNIQUE,
    snapshot_hash TEXT,
    payload_hash TEXT,
    certificate_hash TEXT,
    certificate_id TEXT,
    payload_json TEXT,
    certificate_json TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    broker_order_id TEXT,
    broker_status TEXT,
    halt_reason TEXT,
    replan_reason TEXT,
    forbids_new INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (state IN (
        'OBSERVED','THESIS_READY','CANDIDATES_READY','VETOED','AUTHORIZED',
        'SUBMITTING','ACKNOWLEDGED','RECONCILING','RECONCILED','COMPLETED','HALTED'
    )),
    CHECK (client_order_id != ''),
    CHECK (attempts >= 0 AND attempts <= 1),
    CHECK (forbids_new IN (0, 1))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_cycle
    ON cycles((1)) WHERE state NOT IN ('COMPLETED', 'HALTED', 'VETOED');
CREATE UNIQUE INDEX IF NOT EXISTS idx_payload_hash
    ON cycles(payload_hash) WHERE payload_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_certificate_hash
    ON cycles(certificate_hash) WHERE certificate_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_certificate_id
    ON cycles(certificate_id) WHERE certificate_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    version INTEGER NOT NULL,
    at TEXT NOT NULL,
    payload_hash TEXT,
    certificate_hash TEXT,
    reason TEXT,
    UNIQUE(cycle_id, version),
    FOREIGN KEY (cycle_id) REFERENCES cycles(cycle_id)
);
CREATE TABLE IF NOT EXISTS attempts (
    cycle_id TEXT PRIMARY KEY,
    attempt_no INTEGER NOT NULL DEFAULT 1,
    mcp_tool TEXT,
    arguments_hash TEXT,
    broker_order_id TEXT,
    raw_status TEXT,
    raw_hash TEXT,
    at TEXT NOT NULL,
    CHECK (attempt_no = 1),
    FOREIGN KEY (cycle_id) REFERENCES cycles(cycle_id)
);
CREATE TRIGGER IF NOT EXISTS freeze_client_order_id
BEFORE UPDATE ON cycles
FOR EACH ROW
WHEN OLD.client_order_id IS NOT NEW.client_order_id
BEGIN
    SELECT RAISE(ABORT, 'client_order_id is immutable');
END;
"""


class CycleStore:
    """SQLite durable store. One active cycle. client_order_id never changes."""

    def __init__(self, path: Path | str = Path("data/cycles.sqlite")) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def load(self, cycle_id: str) -> CycleRecord:
        row = self._conn.execute(
            "SELECT * FROM cycles WHERE cycle_id = ?", (cycle_id,)
        ).fetchone()
        if row is None:
            raise CycleError(f"unknown cycle {cycle_id}")
        return _row_to_record(row)

    def load_by_client_order_id(self, client_order_id: str) -> CycleRecord | None:
        row = self._conn.execute(
            "SELECT * FROM cycles WHERE client_order_id = ?", (client_order_id,)
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    def active_cycle(self) -> CycleRecord | None:
        rows = self._conn.execute(
            "SELECT * FROM cycles WHERE state NOT IN ('COMPLETED', 'HALTED', 'VETOED')"
        ).fetchall()
        if len(rows) > 1:
            raise CycleError("one cycle ↔ one active execution violated")
        if not rows:
            return None
        return _row_to_record(rows[0])

    def forbids_new_cycle(self) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM cycles WHERE forbids_new = 1 LIMIT 1"
        ).fetchone()
        return row is not None

    def begin_cycle(
        self,
        *,
        cycle_id: str | None = None,
        client_order_id: str | None = None,
        snapshot_hash: str | None = None,
    ) -> CycleRecord:
        if self.forbids_new_cycle():
            raise CycleHalted("unknown broker state forbids a new cycle")
        if self.active_cycle() is not None:
            raise CycleHalted("one cycle ↔ one active execution")
        cid = cycle_id or uuid.uuid4().hex
        client = client_order_id or f"oc-{uuid.uuid4().hex}"
        clock = _now()
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO cycles (
                        cycle_id, state, version, client_order_id, snapshot_hash,
                        attempts, forbids_new, created_at, updated_at
                    ) VALUES (?, 'OBSERVED', 0, ?, ?, 0, 0, ?, ?)
                    """,
                    (cid, client, snapshot_hash, clock, clock),
                )
                self._conn.execute(
                    """
                    INSERT INTO transitions (
                        cycle_id, from_state, to_state, version, at, reason
                    ) VALUES (?, NULL, 'OBSERVED', 0, ?, 'cycle start')
                    """,
                    (cid, clock),
                )
        except sqlite3.IntegrityError as exc:
            raise CycleError(f"cycle start rejected: {exc}") from exc
        return self.load(cid)

    def attach_snapshot(self, cycle_id: str, snapshot_hash: str) -> CycleRecord:
        rec = self.load(cycle_id)
        if rec.state is not CycleState.OBSERVED:
            raise IllegalTransition("snapshot hash is recorded on OBSERVED")
        with self._conn:
            self._conn.execute(
                "UPDATE cycles SET snapshot_hash = ?, updated_at = ? WHERE cycle_id = ?",
                (snapshot_hash, _now(), cycle_id),
            )
        return self.load(cycle_id)

    def transition(
        self,
        cycle_id: str,
        to_state: CycleState | str,
        *,
        snapshot_hash: str | None = None,
        payload: CanonicalOrderPayload | None = None,
        halt_reason: str | None = None,
        replan_reason: str | None = None,
        broker_order_id: str | None = None,
        broker_status: str | None = None,
        forbids_new: bool | None = None,
        reason: str | None = None,
    ) -> CycleRecord:
        target = _state(to_state)
        rec = self.load(cycle_id)
        if rec.state is target:
            raise DuplicateTransition(f"{rec.state.value} already applied")
        allowed = LEGAL_EDGES[rec.state]
        if target not in allowed:
            raise IllegalTransition(f"{rec.state.value} → {target.value} is not a legal edge")
        payload_hash = rec.payload_hash
        payload_json = rec.payload_json
        if payload is not None:
            if payload.client_order_id != rec.client_order_id:
                raise CycleError("client_order_id is created at cycle start and never changes")
            if rec.payload_hash and rec.payload_hash != payload.payload_hash:
                raise CycleError("one cycle ↔ one payload")
            payload_hash = payload.payload_hash
            payload_json = json.dumps(payload_to_dict(payload), sort_keys=True, separators=(",", ":"))
        new_version = rec.version + 1
        clock = _now()
        forbid = rec.forbids_new if forbids_new is None else int(bool(forbids_new))
        assignments = {
            "state": target.value,
            "version": new_version,
            "updated_at": clock,
            "snapshot_hash": snapshot_hash if snapshot_hash is not None else rec.snapshot_hash,
            "payload_hash": payload_hash,
            "payload_json": payload_json,
            "halt_reason": halt_reason if halt_reason is not None else rec.halt_reason,
            "replan_reason": replan_reason if replan_reason is not None else rec.replan_reason,
            "broker_order_id": broker_order_id if broker_order_id is not None else rec.broker_order_id,
            "broker_status": broker_status if broker_status is not None else rec.broker_status,
            "forbids_new": forbid,
        }
        try:
            with self._conn:
                self._conn.execute(
                    """
                    UPDATE cycles SET
                        state = :state,
                        version = :version,
                        updated_at = :updated_at,
                        snapshot_hash = :snapshot_hash,
                        payload_hash = :payload_hash,
                        payload_json = :payload_json,
                        halt_reason = :halt_reason,
                        replan_reason = :replan_reason,
                        broker_order_id = :broker_order_id,
                        broker_status = :broker_status,
                        forbids_new = :forbids_new
                    WHERE cycle_id = :cycle_id AND version = :prev_version AND state = :from_state
                    """,
                    {
                        **assignments,
                        "cycle_id": cycle_id,
                        "prev_version": rec.version,
                        "from_state": rec.state.value,
                    },
                )
                changed = self._conn.execute("SELECT changes()").fetchone()[0]
                if changed != 1:
                    raise DuplicateTransition("stale version or duplicate transition")
                self._conn.execute(
                    """
                    INSERT INTO transitions (
                        cycle_id, from_state, to_state, version, at,
                        payload_hash, certificate_hash, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id,
                        rec.state.value,
                        target.value,
                        new_version,
                        clock,
                        payload_hash,
                        rec.certificate_hash,
                        reason or target.value,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise CycleError(f"transition rejected: {exc}") from exc
        return self.load(cycle_id)

    def authorize(
        self,
        cycle_id: str,
        payload: CanonicalOrderPayload,
        certificate: RiskCertificate,
        *,
        now: datetime | None = None,
    ) -> CycleRecord:
        rec = self.load(cycle_id)
        clock = now or datetime.now(timezone.utc)
        if rec.state is CycleState.AUTHORIZED:
            raise DuplicateTransition("AUTHORIZED already applied")
        if rec.state is not CycleState.CANDIDATES_READY:
            raise IllegalTransition(f"{rec.state.value} → AUTHORIZED is not a legal edge")
        if payload.client_order_id != rec.client_order_id:
            raise CycleError("client_order_id is created at cycle start and never changes")
        if certificate.client_order_id != rec.client_order_id:
            raise StaleCertificate("certificate client_order_id does not match cycle")
        if certificate.payload_hash != payload.payload_hash:
            raise StaleCertificate("one certificate ↔ one payload")
        if rec.payload_hash and rec.payload_hash != payload.payload_hash:
            raise StaleCertificate("payload does not match cycle")
        if rec.certificate_hash and rec.certificate_hash != certificate.binding_hash:
            raise StaleCertificate("stale certificate reuse")
        if rec.certificate_id and rec.certificate_id != certificate.certificate_id:
            raise StaleCertificate("stale certificate reuse")
        if certificate.expires_at <= clock:
            raise StaleCertificate("certificate expired")
        if not certificate.approval or certificate.veto:
            raise StaleCertificate("certificate is not an approval")
        payload_json = json.dumps(payload_to_dict(payload), sort_keys=True, separators=(",", ":"))
        cert_json = json.dumps(certificate_to_dict(certificate), sort_keys=True, separators=(",", ":"))
        new_version = rec.version + 1
        stamp = _now()
        try:
            with self._conn:
                self._conn.execute(
                    """
                    UPDATE cycles SET
                        state = 'AUTHORIZED',
                        version = ?,
                        updated_at = ?,
                        payload_hash = ?,
                        payload_json = ?,
                        certificate_hash = ?,
                        certificate_id = ?,
                        certificate_json = ?
                    WHERE cycle_id = ? AND version = ? AND state = 'CANDIDATES_READY'
                    """,
                    (
                        new_version,
                        stamp,
                        payload.payload_hash,
                        payload_json,
                        certificate.binding_hash,
                        certificate.certificate_id,
                        cert_json,
                        cycle_id,
                        rec.version,
                    ),
                )
                changed = self._conn.execute("SELECT changes()").fetchone()[0]
                if changed != 1:
                    raise DuplicateTransition("stale version or duplicate AUTHORIZED")
                self._conn.execute(
                    """
                    INSERT INTO transitions (
                        cycle_id, from_state, to_state, version, at,
                        payload_hash, certificate_hash, reason
                    ) VALUES (?, 'CANDIDATES_READY', 'AUTHORIZED', ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id,
                        new_version,
                        stamp,
                        payload.payload_hash,
                        certificate.binding_hash,
                        "authorize",
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise StaleCertificate(f"certificate or payload already bound: {exc}") from exc
        return self.load(cycle_id)

    def record_attempt(
        self,
        cycle_id: str,
        *,
        mcp_tool: str,
        arguments_hash: str,
        broker_order_id: str | None,
        raw_status: str,
        raw_hash: str,
    ) -> CycleRecord:
        rec = self.load(cycle_id)
        if rec.state is not CycleState.SUBMITTING:
            raise IllegalTransition("attempts are recorded only in SUBMITTING")
        if rec.attempts >= 1:
            raise DuplicateTransition("one cycle ↔ one active execution")
        stamp = _now()
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO attempts (
                        cycle_id, attempt_no, mcp_tool, arguments_hash,
                        broker_order_id, raw_status, raw_hash, at
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id,
                        mcp_tool,
                        arguments_hash,
                        broker_order_id,
                        raw_status,
                        raw_hash,
                        stamp,
                    ),
                )
                self._conn.execute(
                    """
                    UPDATE cycles SET
                        attempts = 1,
                        broker_order_id = COALESCE(?, broker_order_id),
                        broker_status = COALESCE(?, broker_status),
                        updated_at = ?
                    WHERE cycle_id = ?
                    """,
                    (broker_order_id, raw_status, stamp, cycle_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateTransition(f"second execution attempt rejected: {exc}") from exc
        return self.load(cycle_id)

    def halt(self, cycle_id: str, reason: str, *, forbids_new: bool = False) -> CycleRecord:
        rec = self.load(cycle_id)
        if rec.state is CycleState.HALTED:
            raise DuplicateTransition("HALTED already applied")
        if rec.state in TERMINAL_STATES:
            raise IllegalTransition(f"{rec.state.value} → HALTED is not a legal edge")
        post = rec.state in POST_SUBMIT_STATES or rec.attempts > 0
        return self.transition(
            cycle_id,
            CycleState.HALTED,
            halt_reason=reason,
            forbids_new=True if forbids_new or post else False,
            reason=reason,
        )

    def veto(self, cycle_id: str, reason: str) -> CycleRecord:
        return self.transition(
            cycle_id,
            CycleState.VETOED,
            replan_reason=reason,
            reason=reason,
        )

    def replay(self, cycle_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT from_state, to_state, version, at, payload_hash, certificate_hash, reason
            FROM transitions WHERE cycle_id = ? ORDER BY version ASC, id ASC
            """,
            (cycle_id,),
        ).fetchall()
        return [
            {
                "from_state": row["from_state"],
                "to_state": row["to_state"],
                "version": int(row["version"]),
                "at": row["at"],
                "payload_hash": row["payload_hash"],
                "certificate_hash": row["certificate_hash"],
                "reason": row["reason"],
            }
            for row in rows
        ]

    def attempt(self, cycle_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM attempts WHERE cycle_id = ?", (cycle_id,)
        ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}
