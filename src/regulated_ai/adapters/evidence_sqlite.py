"""Metadata-only SQLite evidence repository."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from regulated_ai.domain import (
    DataClassification,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ObligationType,
    TransformationReceipt,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    policy_set_version TEXT NOT NULL,
    provider_registry_version TEXT NOT NULL,
    matched_policy_ids TEXT NOT NULL,
    provider_capability_ids TEXT NOT NULL,
    control_objective_ids TEXT NOT NULL,
    obligation_types TEXT NOT NULL,
    classification_labels TEXT NOT NULL,
    reason_codes TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    output_digest TEXT NOT NULL,
    event_digest TEXT NOT NULL,
    previous_event_digest TEXT
)
"""
_INSERT = "INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
_ENFORCEMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS enforcement (
    enforcement_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    evaluation_id TEXT NOT NULL,
    evaluation_evidence_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    status TEXT NOT NULL,
    policy_set_version TEXT NOT NULL,
    provider_registry_version TEXT NOT NULL,
    provider_target TEXT NOT NULL,
    transformation_receipts TEXT NOT NULL,
    reason_codes TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    output_digest TEXT,
    provider_execution_id TEXT
)
"""
_ENFORCEMENT_UPSERT = """
INSERT INTO enforcement VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(enforcement_id) DO UPDATE SET
    created_at=excluded.created_at,
    status=excluded.status,
    transformation_receipts=excluded.transformation_receipts,
    reason_codes=excluded.reason_codes,
    output_digest=excluded.output_digest,
    provider_execution_id=excluded.provider_execution_id
WHERE enforcement.status != 'EXECUTED'
"""


class SqliteEvidenceRepository:
    """Persist only fields allowlisted by `EvidenceMetadata`."""

    def __init__(self, path: Path) -> None:
        """Initialize the metadata-only table at an explicit local path."""
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_SCHEMA)

    def save(self, evidence: EvidenceMetadata) -> EvidenceMetadata:
        """Insert one immutable record, preserving an existing identical id."""
        values = (
            evidence.evidence_id,
            evidence.created_at.isoformat(),
            evidence.correlation_id,
            evidence.decision.value,
            evidence.policy_set_version,
            evidence.provider_registry_version,
            _json(evidence.matched_policy_ids),
            _json(evidence.provider_capability_ids),
            _json(evidence.control_objective_ids),
            _json(tuple(item.value for item in evidence.obligation_types)),
            _json(tuple(item.value for item in evidence.classification_labels)),
            _json(evidence.reason_codes),
            evidence.input_digest,
            evidence.output_digest,
            evidence.event_digest,
            evidence.previous_event_digest,
        )
        with self._connect() as connection:
            connection.execute(_INSERT, values)
        stored = self.get(evidence.evidence_id)
        if stored is None:
            raise RuntimeError("Evidence insert did not produce a record")
        return stored

    def get(self, evidence_id: str) -> EvidenceMetadata | None:
        """Return one record reconstructed as immutable domain metadata."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
        if row is None:
            return None
        from datetime import datetime

        return EvidenceMetadata(
            evidence_id=str(row[0]),
            created_at=datetime.fromisoformat(str(row[1])),
            correlation_id=str(row[2]),
            decision=DecisionOutcome(str(row[3])),
            policy_set_version=str(row[4]),
            provider_registry_version=str(row[5]),
            matched_policy_ids=_string_tuple(row[6]),
            provider_capability_ids=_string_tuple(row[7]),
            control_objective_ids=_string_tuple(row[8]),
            obligation_types=tuple(ObligationType(item) for item in _string_tuple(row[9])),
            classification_labels=tuple(
                DataClassification(item) for item in _string_tuple(row[10])
            ),
            reason_codes=_string_tuple(row[11]),
            input_digest=str(row[12]),
            output_digest=str(row[13]),
            event_digest=str(row[14]),
            previous_event_digest=None if row[15] is None else str(row[15]),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _json(values: tuple[str, ...]) -> str:
    return json.dumps(values, separators=(",", ":"))


def _string_tuple(value: object) -> tuple[str, ...]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("Stored evidence metadata is invalid")
    return tuple(parsed)


class SqliteEnforcementRepository:
    """Persist only metadata allowlisted by `EnforcementRecord`."""

    def __init__(self, path: Path) -> None:
        """Initialize the enforcement table in the shared local database."""
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_ENFORCEMENT_SCHEMA)

    def save(self, record: EnforcementRecord) -> EnforcementRecord:
        """Insert or advance the state of one enforcement attempt."""
        values = (
            record.enforcement_id,
            record.created_at.isoformat(),
            record.evaluation_id,
            record.evaluation_evidence_id,
            record.decision.value,
            record.status.value,
            record.policy_set_version,
            record.provider_registry_version,
            record.provider_target,
            _receipts_json(record.transformation_receipts),
            _json(record.reason_codes),
            record.input_digest,
            record.output_digest,
            record.provider_execution_id,
        )
        with self._connect() as connection:
            connection.execute(_ENFORCEMENT_UPSERT, values)
        stored = self.get(record.enforcement_id)
        if stored is None:
            raise RuntimeError("Enforcement insert did not produce a record")
        return stored

    def get(self, enforcement_id: str) -> EnforcementRecord | None:
        """Return one metadata-only enforcement record."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM enforcement WHERE enforcement_id = ?", (enforcement_id,)
            ).fetchone()
        if row is None:
            return None
        from datetime import datetime

        return EnforcementRecord(
            enforcement_id=str(row[0]),
            created_at=datetime.fromisoformat(str(row[1])),
            evaluation_id=str(row[2]),
            evaluation_evidence_id=str(row[3]),
            decision=DecisionOutcome(str(row[4])),
            status=EnforcementStatus(str(row[5])),
            policy_set_version=str(row[6]),
            provider_registry_version=str(row[7]),
            provider_target=str(row[8]),
            transformation_receipts=_receipts(str(row[9])),
            reason_codes=_string_tuple(row[10]),
            input_digest=str(row[11]),
            output_digest=None if row[12] is None else str(row[12]),
            provider_execution_id=None if row[13] is None else str(row[13]),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _receipts_json(receipts: tuple[TransformationReceipt, ...]) -> str:
    return json.dumps(
        [
            {
                "input_digest": item.input_digest,
                "output_digest": item.output_digest,
                "reason_code": item.reason_code,
                "receipt_id": item.receipt_id,
                "target": item.target,
                "type": item.type.value,
            }
            for item in receipts
        ],
        sort_keys=True,
        separators=(",", ":"),
    )


def _receipts(value: str) -> tuple[TransformationReceipt, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("Stored transformation receipts are invalid")
    receipts: list[TransformationReceipt] = []
    for item in parsed:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str)
            for key in (
                "input_digest",
                "output_digest",
                "reason_code",
                "receipt_id",
                "target",
                "type",
            )
        ):
            raise ValueError("Stored transformation receipt is invalid")
        receipts.append(
            TransformationReceipt(
                receipt_id=item["receipt_id"],
                type=ObligationType(item["type"]),
                target=item["target"],
                input_digest=item["input_digest"],
                output_digest=item["output_digest"],
                reason_code=item["reason_code"],
            )
        )
    return tuple(receipts)
