"""Transactional PostgreSQL persistence for production deployments."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import tuple_row

from regulated_ai.adapters.evidence_sqlite import (
    _action_approval_receipt_json,
    _approval_receipt,
    _approval_receipt_json,
    _json,
    _operator_lifecycle_event,
    _provider_call_json,
    _provider_call_metadata,
    _provider_capability_snapshots,
    _provider_capability_snapshots_json,
    _receipts,
    _receipts_json,
    _string_tuple,
    _tool_action_reconciliation_receipt_json,
    _tool_action_record,
    _tool_proposals,
    _tool_proposals_json,
)
from regulated_ai.domain import (
    DataClassification,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ObligationType,
    OperatorLifecycleEvent,
    ToolActionRecord,
    ToolActionStatus,
)

POSTGRES_SCHEMA_REVISION = "0001_production_persistence"

_EVIDENCE_INSERT = """
INSERT INTO evidence (
    evidence_id, created_at, correlation_id, decision, policy_set_version,
    provider_registry_version, matched_policy_ids, provider_capability_ids,
    control_objective_ids, obligation_types, classification_labels, reason_codes,
    input_digest, output_digest, event_digest, previous_event_digest,
    tool_catalog_version, authorized_tool_ids, provider_capability_snapshots
)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT DO NOTHING
"""
_EVIDENCE_SELECT = """
SELECT evidence_id, created_at, correlation_id, decision, policy_set_version,
       provider_registry_version, matched_policy_ids, provider_capability_ids,
       control_objective_ids, obligation_types, classification_labels, reason_codes,
       input_digest, output_digest, event_digest, previous_event_digest,
       tool_catalog_version, authorized_tool_ids, provider_capability_snapshots
FROM evidence WHERE evidence_id=%s
"""
_ENFORCEMENT_UPSERT = """
INSERT INTO enforcement (
    enforcement_id, created_at, evaluation_id, evaluation_evidence_id, decision, status,
    policy_set_version, provider_registry_version, provider_target, transformation_receipts,
    reason_codes, input_digest, output_digest, provider_execution_id, provider_call_metadata,
    approval_receipt, tool_proposals
)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT(enforcement_id) DO UPDATE SET
    created_at=excluded.created_at, status=excluded.status,
    transformation_receipts=excluded.transformation_receipts,
    reason_codes=excluded.reason_codes, output_digest=excluded.output_digest,
    provider_execution_id=excluded.provider_execution_id,
    provider_call_metadata=excluded.provider_call_metadata,
    approval_receipt=excluded.approval_receipt, tool_proposals=excluded.tool_proposals
WHERE enforcement.status NOT IN ('DISPATCHED','EXECUTED','APPROVAL_FAILED','EXECUTION_FAILED')
   OR (enforcement.status='DISPATCHED'
       AND excluded.status IN ('EXECUTED','APPROVAL_FAILED','EXECUTION_FAILED'))
"""
_ENFORCEMENT_SELECT = """
SELECT enforcement_id, created_at, evaluation_id, evaluation_evidence_id, decision, status,
       policy_set_version, provider_registry_version, provider_target, transformation_receipts,
       reason_codes, input_digest, output_digest, provider_execution_id, provider_call_metadata,
       approval_receipt, tool_proposals
FROM enforcement WHERE enforcement_id=%s
"""
_TOOL_ACTION_UPSERT = """
INSERT INTO tool_action (
    action_id, created_at, enforcement_id, evaluation_id, call_id, tool_name,
    tool_schema_version, tool_schema_digest, arguments_digest, workload_identity,
    idempotency_key_digest, action_digest, status, approval_receipt, tool_execution_id,
    output_digest, output_schema_digest, safe_output_digest, result_classifications,
    exposed_result_fields, reconciliation_receipt
)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT(action_id) DO UPDATE SET
    status=excluded.status, approval_receipt=excluded.approval_receipt,
    tool_execution_id=excluded.tool_execution_id, output_digest=excluded.output_digest,
    safe_output_digest=excluded.safe_output_digest,
    result_classifications=excluded.result_classifications,
    exposed_result_fields=excluded.exposed_result_fields,
    reconciliation_receipt=excluded.reconciliation_receipt
WHERE tool_action.enforcement_id=excluded.enforcement_id
  AND tool_action.evaluation_id=excluded.evaluation_id
  AND tool_action.call_id=excluded.call_id
  AND tool_action.tool_name=excluded.tool_name
  AND tool_action.tool_schema_version=excluded.tool_schema_version
  AND tool_action.tool_schema_digest=excluded.tool_schema_digest
  AND tool_action.arguments_digest=excluded.arguments_digest
  AND tool_action.workload_identity=excluded.workload_identity
  AND tool_action.idempotency_key_digest=excluded.idempotency_key_digest
  AND tool_action.action_digest=excluded.action_digest
  AND tool_action.output_schema_digest IS NOT DISTINCT FROM excluded.output_schema_digest
  AND (
      (tool_action.reconciliation_receipt IS NOT DISTINCT FROM excluded.reconciliation_receipt
       AND ((tool_action.status='WAITING_APPROVAL'
             AND excluded.status IN ('WAITING_APPROVAL','PREPARED'))
            OR (tool_action.status='DISPATCHED'
                AND excluded.status IN
                    ('EXECUTED','APPROVAL_FAILED','RECONCILIATION_REQUIRED','RESULT_REJECTED'))))
      OR (tool_action.status='RECONCILIATION_REQUIRED'
          AND excluded.status IN ('RECONCILED_EXECUTED','RECONCILED_NOT_EXECUTED')
          AND tool_action.reconciliation_receipt IS NULL
          AND excluded.reconciliation_receipt IS NOT NULL
          AND tool_action.approval_receipt IS NOT DISTINCT FROM excluded.approval_receipt
          AND tool_action.output_digest IS NOT DISTINCT FROM excluded.output_digest
          AND tool_action.safe_output_digest IS NOT DISTINCT FROM excluded.safe_output_digest
          AND tool_action.result_classifications=excluded.result_classifications
          AND tool_action.exposed_result_fields=excluded.exposed_result_fields
          AND ((excluded.status='RECONCILED_EXECUTED'
                AND tool_action.tool_execution_id IS NULL
                AND excluded.tool_execution_id IS NOT NULL)
               OR (excluded.status='RECONCILED_NOT_EXECUTED'
                   AND tool_action.tool_execution_id IS NOT DISTINCT FROM
                       excluded.tool_execution_id)))
  )
"""
_TOOL_ACTION_SELECT = """
SELECT action_id, created_at, enforcement_id, evaluation_id, call_id, tool_name,
       tool_schema_version, tool_schema_digest, arguments_digest, workload_identity,
       idempotency_key_digest, action_digest, status, approval_receipt, tool_execution_id,
       output_digest, output_schema_digest, safe_output_digest, result_classifications,
       exposed_result_fields, reconciliation_receipt
FROM tool_action WHERE action_id=%s
"""
_TOOL_ACTION_LIST = """
SELECT action_id, created_at, enforcement_id, evaluation_id, call_id, tool_name,
       tool_schema_version, tool_schema_digest, arguments_digest, workload_identity,
       idempotency_key_digest, action_digest, status, approval_receipt, tool_execution_id,
       output_digest, output_schema_digest, safe_output_digest, result_classifications,
       exposed_result_fields, reconciliation_receipt
FROM tool_action
WHERE enforcement_id=%s ORDER BY created_at, action_id LIMIT %s
"""


class PostgresSchemaError(RuntimeError):
    """The configured production database is unavailable or not at the expected revision."""


class PostgresDatabase:
    """Open bounded PostgreSQL transactions without retaining credentials in logs."""

    def __init__(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int = 5,
        statement_timeout_milliseconds: int = 5_000,
    ) -> None:
        """Validate connection settings without opening a connection."""
        if not dsn.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("REGULAAI_DATABASE_URL must use PostgreSQL")
        if connect_timeout_seconds < 1 or connect_timeout_seconds > 30:
            raise ValueError("PostgreSQL connect timeout must be in the range [1, 30]")
        if statement_timeout_milliseconds < 100 or statement_timeout_milliseconds > 60_000:
            raise ValueError("PostgreSQL statement timeout must be in the range [100, 60000]")
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        self._connect_timeout_seconds = connect_timeout_seconds
        self._statement_timeout_milliseconds = statement_timeout_milliseconds

    @contextmanager
    def connect(self) -> Iterator[Connection[Any]]:
        """Yield one transaction and always commit, roll back and close deterministically."""
        connection = psycopg.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_seconds,
            application_name="regulaai-control-plane",
            row_factory=tuple_row,
        )
        try:
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._statement_timeout_milliseconds),),
            )
            connection.execute("SELECT set_config('lock_timeout', %s, true)", ("5000",))
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def verify_schema(self) -> None:
        """Fail startup when migrations have not reached the application revision."""
        try:
            with self.connect() as connection:
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except psycopg.Error as exc:
            raise PostgresSchemaError(
                "PostgreSQL is unavailable or migrations have not been applied"
            ) from exc
        if row is None or str(row[0]) != POSTGRES_SCHEMA_REVISION:
            raise PostgresSchemaError("PostgreSQL schema revision is not supported")


class PostgresEvidenceRepository:
    """Persist immutable metadata-only evaluation evidence in PostgreSQL."""

    def __init__(self, database: PostgresDatabase) -> None:
        """Bind the repository to a migrated PostgreSQL database."""
        self._database = database

    def save(self, evidence: EvidenceMetadata) -> EvidenceMetadata:
        """Insert one immutable record, preserving an existing identical id."""
        values = (
            evidence.evidence_id,
            evidence.created_at,
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
            evidence.tool_catalog_version,
            _json(evidence.authorized_tool_ids),
            _provider_capability_snapshots_json(evidence.provider_capability_snapshots),
        )
        with self._database.connect() as connection:
            connection.execute(_EVIDENCE_INSERT, values)
        stored = self.get(evidence.evidence_id)
        if stored is None:
            raise RuntimeError("Evidence insert did not produce a record")
        return stored

    def get(self, evidence_id: str) -> EvidenceMetadata | None:
        """Return one record reconstructed as immutable domain metadata."""
        with self._database.connect() as connection:
            row = connection.execute(_EVIDENCE_SELECT, (evidence_id,)).fetchone()
        if row is None:
            return None
        snapshots = _provider_capability_snapshots(row[18])
        evidence = EvidenceMetadata(
            evidence_id=str(row[0]),
            created_at=_datetime(row[1]),
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
            tool_catalog_version=None if row[16] is None else str(row[16]),
            authorized_tool_ids=_string_tuple(row[17]),
            provider_capability_snapshots=snapshots,
        )
        if any(
            snapshot.registry_version != evidence.provider_registry_version
            for snapshot in snapshots
        ):
            raise ValueError("Stored provider capability snapshot is inconsistent")
        return evidence


class PostgresEnforcementRepository:
    """Persist enforcement state using guarded transactional transitions."""

    def __init__(self, database: PostgresDatabase) -> None:
        """Bind the repository to a migrated PostgreSQL database."""
        self._database = database

    def save(self, record: EnforcementRecord) -> EnforcementRecord:
        """Insert or advance one enforcement state without weakening terminal state."""
        values = (
            record.enforcement_id,
            record.created_at,
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
            _provider_call_json(record.provider_call_metadata),
            _approval_receipt_json(record.approval_receipt),
            _tool_proposals_json(record.tool_proposals),
        )
        with self._database.connect() as connection:
            connection.execute(_ENFORCEMENT_UPSERT, values)
        stored = self.get(record.enforcement_id)
        if stored is None:
            raise RuntimeError("Enforcement insert did not produce a record")
        return stored

    def get(self, enforcement_id: str) -> EnforcementRecord | None:
        """Return one metadata-only enforcement record."""
        with self._database.connect() as connection:
            row = connection.execute(_ENFORCEMENT_SELECT, (enforcement_id,)).fetchone()
        if row is None:
            return None
        return EnforcementRecord(
            enforcement_id=str(row[0]),
            created_at=_datetime(row[1]),
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
            provider_call_metadata=_provider_call_metadata(row[14]),
            approval_receipt=_approval_receipt(row[15]),
            tool_proposals=_tool_proposals(row[16]),
        )

    def claim_execution(self, record: EnforcementRecord) -> tuple[EnforcementRecord, bool]:
        """Allow exactly one transaction to advance PREPARED to DISPATCHED."""
        if record.status is not EnforcementStatus.DISPATCHED:
            raise ValueError("Execution claim requires DISPATCHED status")
        with self._database.connect() as connection:
            row = connection.execute(
                "UPDATE enforcement SET status='DISPATCHED' "
                "WHERE enforcement_id=%s AND status='PREPARED' RETURNING enforcement_id",
                (record.enforcement_id,),
            ).fetchone()
        stored = self.get(record.enforcement_id)
        if stored is None:
            raise RuntimeError("Execution claim has no enforcement record")
        return stored, row is not None


class PostgresToolActionRepository:
    """Persist exact action bindings with concurrency-safe claims."""

    def __init__(self, database: PostgresDatabase) -> None:
        """Bind the repository to a migrated PostgreSQL database."""
        self._database = database

    def save(self, record: ToolActionRecord) -> ToolActionRecord:
        """Insert or safely advance one action state."""
        values = (
            record.action_id,
            record.created_at,
            record.enforcement_id,
            record.evaluation_id,
            record.call_id,
            record.tool_name,
            record.tool_schema_version,
            record.tool_schema_digest,
            record.arguments_digest,
            record.workload_identity,
            record.idempotency_key_digest,
            record.action_digest,
            record.status.value,
            _action_approval_receipt_json(record.approval_receipt),
            record.tool_execution_id,
            record.output_digest,
            record.output_schema_digest,
            record.safe_output_digest,
            _json(tuple(item.value for item in record.result_classifications)),
            _json(record.exposed_result_fields),
            _tool_action_reconciliation_receipt_json(record.reconciliation_receipt),
        )
        with self._database.connect() as connection:
            connection.execute(_TOOL_ACTION_UPSERT, values)
        stored = self.get(record.action_id)
        if stored is None:
            raise RuntimeError("Tool-action insert did not produce a record")
        return stored

    def get(self, action_id: str) -> ToolActionRecord | None:
        """Return one metadata-only action record."""
        with self._database.connect() as connection:
            row = connection.execute(_TOOL_ACTION_SELECT, (action_id,)).fetchone()
        return None if row is None else _tool_action_record(row)

    def list_for_enforcement(
        self, enforcement_id: str, *, limit: int
    ) -> tuple[ToolActionRecord, ...]:
        """Return a bounded stable action list for an enforcement."""
        if limit < 1 or limit > 129:
            raise ValueError("Tool-action list limit is invalid")
        with self._database.connect() as connection:
            rows = connection.execute(_TOOL_ACTION_LIST, (enforcement_id, limit)).fetchall()
        return tuple(_tool_action_record(row) for row in rows)

    def claim_execution(self, record: ToolActionRecord) -> tuple[ToolActionRecord, bool]:
        """Allow exactly one transaction to claim a prepared action."""
        if record.status is not ToolActionStatus.DISPATCHED:
            raise ValueError("Tool-action claim requires DISPATCHED status")
        with self._database.connect() as connection:
            row = connection.execute(
                "UPDATE tool_action SET status='DISPATCHED' "
                "WHERE action_id=%s AND status='PREPARED' RETURNING action_id",
                (record.action_id,),
            ).fetchone()
        stored = self.get(record.action_id)
        if stored is None:
            raise RuntimeError("Tool-action claim has no record")
        return stored, row is not None


class PostgresOperatorLifecycleEventRepository:
    """Read append-only lifecycle events written in the state transaction."""

    def __init__(self, database: PostgresDatabase) -> None:
        """Bind the repository to a migrated PostgreSQL database."""
        self._database = database

    def list_for_timeline(
        self,
        *,
        enforcement_id: str,
        evidence_id: str,
        limit: int,
    ) -> tuple[OperatorLifecycleEvent, ...]:
        """Return one bounded event sequence for exact linked identifiers."""
        if limit < 1 or limit > 257:
            raise ValueError("Lifecycle-event list limit is invalid")
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT event_sequence, recorded_at, source, entity_kind,
                       entity_id, enforcement_id, status
                FROM operator_lifecycle_event
                WHERE enforcement_id=%s OR (entity_kind='EVALUATION' AND entity_id=%s)
                ORDER BY event_sequence LIMIT %s
                """,
                (enforcement_id, evidence_id, limit),
            ).fetchall()
        return tuple(_operator_lifecycle_event(row) for row in rows)


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
