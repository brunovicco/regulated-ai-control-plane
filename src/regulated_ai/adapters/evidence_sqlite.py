"""Metadata-only SQLite evidence repository."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from regulated_ai.domain import (
    ActionApprovalReceipt,
    ApprovalReceipt,
    DataClassification,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ObligationType,
    ProviderCallMetadata,
    ToolActionRecord,
    ToolActionStatus,
    ToolProposal,
    ToolResultClassification,
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
    previous_event_digest TEXT,
    tool_catalog_version TEXT,
    authorized_tool_ids TEXT NOT NULL DEFAULT '[]'
)
"""
_INSERT = """
INSERT OR IGNORE INTO evidence (
    evidence_id, created_at, correlation_id, decision, policy_set_version,
    provider_registry_version, matched_policy_ids, provider_capability_ids,
    control_objective_ids, obligation_types, classification_labels, reason_codes,
    input_digest, output_digest, event_digest, previous_event_digest,
    tool_catalog_version, authorized_tool_ids
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""
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
    provider_execution_id TEXT,
    provider_call_metadata TEXT,
    approval_receipt TEXT,
    tool_proposals TEXT NOT NULL DEFAULT '[]'
)
"""
_ENFORCEMENT_UPSERT = """
INSERT INTO enforcement (
    enforcement_id,
    created_at,
    evaluation_id,
    evaluation_evidence_id,
    decision,
    status,
    policy_set_version,
    provider_registry_version,
    provider_target,
    transformation_receipts,
    reason_codes,
    input_digest,
    output_digest,
    provider_execution_id,
    provider_call_metadata,
    approval_receipt,
    tool_proposals
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(enforcement_id) DO UPDATE SET
    created_at=excluded.created_at,
    status=excluded.status,
    transformation_receipts=excluded.transformation_receipts,
    reason_codes=excluded.reason_codes,
    output_digest=excluded.output_digest,
    provider_execution_id=excluded.provider_execution_id,
    provider_call_metadata=excluded.provider_call_metadata,
    approval_receipt=excluded.approval_receipt,
    tool_proposals=excluded.tool_proposals
WHERE enforcement.status NOT IN ('DISPATCHED', 'EXECUTED', 'APPROVAL_FAILED', 'EXECUTION_FAILED')
   OR (
       enforcement.status = 'DISPATCHED'
       AND excluded.status IN ('EXECUTED', 'APPROVAL_FAILED', 'EXECUTION_FAILED')
   )
"""
_ENFORCEMENT_CLAIM = """
UPDATE enforcement
SET status = 'DISPATCHED'
WHERE enforcement_id = ? AND status = 'PREPARED'
"""
_TOOL_ACTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_action (
    action_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    enforcement_id TEXT NOT NULL,
    evaluation_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_schema_version TEXT NOT NULL,
    tool_schema_digest TEXT NOT NULL,
    arguments_digest TEXT NOT NULL,
    workload_identity TEXT NOT NULL,
    idempotency_key_digest TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_receipt TEXT,
    tool_execution_id TEXT,
    output_digest TEXT,
    output_schema_digest TEXT,
    safe_output_digest TEXT,
    result_classifications TEXT NOT NULL DEFAULT '[]',
    exposed_result_fields TEXT NOT NULL DEFAULT '[]',
    UNIQUE(enforcement_id, call_id)
)
"""
_TOOL_ACTION_UPSERT = """
INSERT INTO tool_action (
    action_id, created_at, enforcement_id, evaluation_id, call_id, tool_name,
    tool_schema_version, tool_schema_digest, arguments_digest, workload_identity,
    idempotency_key_digest, action_digest, status, approval_receipt,
    tool_execution_id, output_digest, output_schema_digest, safe_output_digest,
    result_classifications, exposed_result_fields
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(action_id) DO UPDATE SET
    status=excluded.status,
    approval_receipt=excluded.approval_receipt,
    tool_execution_id=excluded.tool_execution_id,
    output_digest=excluded.output_digest,
    safe_output_digest=excluded.safe_output_digest,
    result_classifications=excluded.result_classifications,
    exposed_result_fields=excluded.exposed_result_fields
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
  AND tool_action.output_schema_digest IS excluded.output_schema_digest
  AND (
      (tool_action.status='WAITING_APPROVAL' AND excluded.status IN ('WAITING_APPROVAL','PREPARED'))
      OR (
          tool_action.status='DISPATCHED'
          AND excluded.status IN (
              'EXECUTED','APPROVAL_FAILED','RECONCILIATION_REQUIRED','RESULT_REJECTED'
          )
      )
  )
"""
_TOOL_ACTION_CLAIM = """
UPDATE tool_action
SET status = 'DISPATCHED'
WHERE action_id = ? AND status = 'PREPARED'
"""


class SqliteEvidenceRepository:
    """Persist only fields allowlisted by `EvidenceMetadata`."""

    def __init__(self, path: Path) -> None:
        """Initialize the metadata-only table at an explicit local path."""
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_SCHEMA)
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(evidence)")}
            if "tool_catalog_version" not in columns:
                connection.execute("ALTER TABLE evidence ADD COLUMN tool_catalog_version TEXT")
            if "authorized_tool_ids" not in columns:
                connection.execute(
                    "ALTER TABLE evidence ADD COLUMN authorized_tool_ids TEXT NOT NULL DEFAULT '[]'"
                )

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
            evidence.tool_catalog_version,
            _json(evidence.authorized_tool_ids),
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
            tool_catalog_version=None if row[16] is None else str(row[16]),
            authorized_tool_ids=_string_tuple(row[17]),
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
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(enforcement)")}
            if "provider_call_metadata" not in columns:
                connection.execute("ALTER TABLE enforcement ADD COLUMN provider_call_metadata TEXT")
            if "approval_receipt" not in columns:
                connection.execute("ALTER TABLE enforcement ADD COLUMN approval_receipt TEXT")
            if "tool_proposals" not in columns:
                connection.execute(
                    "ALTER TABLE enforcement ADD COLUMN tool_proposals TEXT NOT NULL DEFAULT '[]'"
                )

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
            _provider_call_json(record.provider_call_metadata),
            _approval_receipt_json(record.approval_receipt),
            _tool_proposals_json(record.tool_proposals),
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
            provider_call_metadata=_provider_call_metadata(row[14]),
            approval_receipt=_approval_receipt(row[15]),
            tool_proposals=_tool_proposals(row[16]),
        )

    def claim_execution(self, record: EnforcementRecord) -> tuple[EnforcementRecord, bool]:
        """Atomically claim one prepared attempt before external execution."""
        if record.status is not EnforcementStatus.DISPATCHED:
            raise ValueError("Execution claim requires DISPATCHED status")
        with self._connect() as connection:
            cursor = connection.execute(_ENFORCEMENT_CLAIM, (record.enforcement_id,))
            claimed = cursor.rowcount == 1
        stored = self.get(record.enforcement_id)
        if stored is None:
            raise RuntimeError("Execution claim has no enforcement record")
        return stored, claimed

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


class SqliteToolActionRepository:
    """Persist action-binding metadata without raw arguments or outputs."""

    def __init__(self, path: Path) -> None:
        """Initialize the action table in the shared local database."""
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_TOOL_ACTION_SCHEMA)
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tool_action)")}
            if "output_schema_digest" not in columns:
                connection.execute("ALTER TABLE tool_action ADD COLUMN output_schema_digest TEXT")
            if "safe_output_digest" not in columns:
                connection.execute("ALTER TABLE tool_action ADD COLUMN safe_output_digest TEXT")
            if "result_classifications" not in columns:
                connection.execute(
                    "ALTER TABLE tool_action ADD COLUMN "
                    "result_classifications TEXT NOT NULL DEFAULT '[]'"
                )
            if "exposed_result_fields" not in columns:
                connection.execute(
                    "ALTER TABLE tool_action ADD COLUMN "
                    "exposed_result_fields TEXT NOT NULL DEFAULT '[]'"
                )

    def save(self, record: ToolActionRecord) -> ToolActionRecord:
        """Insert or safely advance one action state."""
        values = (
            record.action_id,
            record.created_at.isoformat(),
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
        )
        with self._connect() as connection:
            connection.execute(_TOOL_ACTION_UPSERT, values)
        stored = self.get(record.action_id)
        if stored is None:
            raise RuntimeError("Tool-action insert did not produce a record")
        return stored

    def get(self, action_id: str) -> ToolActionRecord | None:
        """Return one metadata-only action record."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tool_action WHERE action_id = ?", (action_id,)
            ).fetchone()
        if row is None:
            return None
        from datetime import datetime

        return ToolActionRecord(
            action_id=str(row[0]),
            created_at=datetime.fromisoformat(str(row[1])),
            enforcement_id=str(row[2]),
            evaluation_id=str(row[3]),
            call_id=str(row[4]),
            tool_name=str(row[5]),
            tool_schema_version=str(row[6]),
            tool_schema_digest=str(row[7]),
            arguments_digest=str(row[8]),
            workload_identity=str(row[9]),
            idempotency_key_digest=str(row[10]),
            action_digest=str(row[11]),
            status=ToolActionStatus(str(row[12])),
            approval_receipt=_action_approval_receipt(row[13]),
            tool_execution_id=None if row[14] is None else str(row[14]),
            output_digest=None if row[15] is None else str(row[15]),
            output_schema_digest=None if row[16] is None else str(row[16]),
            safe_output_digest=None if row[17] is None else str(row[17]),
            result_classifications=tuple(
                ToolResultClassification(item) for item in _string_tuple(row[18])
            ),
            exposed_result_fields=_string_tuple(row[19]),
        )

    def claim_execution(self, record: ToolActionRecord) -> tuple[ToolActionRecord, bool]:
        """Atomically claim one prepared action before crossing the boundary."""
        if record.status is not ToolActionStatus.DISPATCHED:
            raise ValueError("Tool-action claim requires DISPATCHED status")
        with self._connect() as connection:
            cursor = connection.execute(_TOOL_ACTION_CLAIM, (record.action_id,))
            claimed = cursor.rowcount == 1
        stored = self.get(record.action_id)
        if stored is None:
            raise RuntimeError("Tool-action claim has no record")
        return stored, claimed

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


def _provider_call_json(metadata: ProviderCallMetadata | None) -> str | None:
    if metadata is None:
        return None
    return json.dumps(
        {
            "attempt_number": metadata.attempt_number,
            "cached": metadata.cached,
            "deployment": metadata.deployment,
            "fallback_index": metadata.fallback_index,
            "gateway_request_id": metadata.gateway_request_id,
            "latency_ms": metadata.latency_ms,
            "model": metadata.model,
            "policy_id": metadata.policy_id,
            "policy_version": metadata.policy_version,
            "provider": metadata.provider,
            "routing_decision_id": metadata.routing_decision_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _provider_call_metadata(value: object) -> ProviderCallMetadata | None:
    if value is None:
        return None
    parsed = json.loads(str(value))
    expected = {
        "attempt_number",
        "cached",
        "deployment",
        "fallback_index",
        "gateway_request_id",
        "latency_ms",
        "model",
        "policy_id",
        "policy_version",
        "provider",
        "routing_decision_id",
    }
    if not isinstance(parsed, dict) or set(parsed) != expected:
        raise ValueError("Stored provider call metadata is invalid")
    string_fields = (
        "deployment",
        "gateway_request_id",
        "model",
        "policy_id",
        "policy_version",
        "provider",
        "routing_decision_id",
    )
    integer_fields = ("attempt_number", "fallback_index", "latency_ms")
    if (
        not all(isinstance(parsed[key], str) for key in string_fields)
        or not all(
            isinstance(parsed[key], int) and not isinstance(parsed[key], bool)
            for key in integer_fields
        )
        or not isinstance(parsed["cached"], bool)
    ):
        raise ValueError("Stored provider call metadata is invalid")
    return ProviderCallMetadata(
        gateway_request_id=parsed["gateway_request_id"],
        routing_decision_id=parsed["routing_decision_id"],
        policy_id=parsed["policy_id"],
        policy_version=parsed["policy_version"],
        provider=parsed["provider"],
        model=parsed["model"],
        deployment=parsed["deployment"],
        latency_ms=parsed["latency_ms"],
        attempt_number=parsed["attempt_number"],
        fallback_index=parsed["fallback_index"],
        cached=parsed["cached"],
    )


def _approval_receipt_json(receipt: ApprovalReceipt | None) -> str | None:
    if receipt is None:
        return None
    return json.dumps(
        {
            "actor_id": receipt.actor_id,
            "approval_id": receipt.approval_id,
            "consumed_at": receipt.consumed_at.isoformat(),
            "decision_digest": receipt.decision_digest,
            "enforcement_id": receipt.enforcement_id,
            "expires_at": receipt.expires_at.isoformat(),
            "issued_at": receipt.issued_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _approval_receipt(value: object) -> ApprovalReceipt | None:
    if value is None:
        return None
    parsed = json.loads(str(value))
    expected = {
        "actor_id",
        "approval_id",
        "consumed_at",
        "decision_digest",
        "enforcement_id",
        "expires_at",
        "issued_at",
    }
    if (
        not isinstance(parsed, dict)
        or set(parsed) != expected
        or not all(isinstance(parsed[key], str) for key in expected)
    ):
        raise ValueError("Stored approval receipt is invalid")
    from datetime import datetime

    return ApprovalReceipt(
        approval_id=parsed["approval_id"],
        actor_id=parsed["actor_id"],
        decision_digest=parsed["decision_digest"],
        enforcement_id=parsed["enforcement_id"],
        issued_at=datetime.fromisoformat(parsed["issued_at"]),
        expires_at=datetime.fromisoformat(parsed["expires_at"]),
        consumed_at=datetime.fromisoformat(parsed["consumed_at"]),
    )


def _action_approval_receipt_json(receipt: ActionApprovalReceipt | None) -> str | None:
    if receipt is None:
        return None
    return json.dumps(
        {
            "action_digest": receipt.action_digest,
            "action_id": receipt.action_id,
            "actor_id": receipt.actor_id,
            "approval_id": receipt.approval_id,
            "consumed_at": receipt.consumed_at.isoformat(),
            "expires_at": receipt.expires_at.isoformat(),
            "issued_at": receipt.issued_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _action_approval_receipt(value: object) -> ActionApprovalReceipt | None:
    if value is None:
        return None
    parsed = json.loads(str(value))
    expected = {
        "action_digest",
        "action_id",
        "actor_id",
        "approval_id",
        "consumed_at",
        "expires_at",
        "issued_at",
    }
    if (
        not isinstance(parsed, dict)
        or set(parsed) != expected
        or not all(isinstance(parsed[key], str) for key in expected)
    ):
        raise ValueError("Stored action approval receipt is invalid")
    from datetime import datetime

    return ActionApprovalReceipt(
        approval_id=parsed["approval_id"],
        actor_id=parsed["actor_id"],
        action_digest=parsed["action_digest"],
        action_id=parsed["action_id"],
        issued_at=datetime.fromisoformat(parsed["issued_at"]),
        expires_at=datetime.fromisoformat(parsed["expires_at"]),
        consumed_at=datetime.fromisoformat(parsed["consumed_at"]),
    )


def _tool_proposals_json(proposals: tuple[ToolProposal, ...]) -> str:
    return json.dumps(
        [
            {
                "arguments_digest": item.arguments_digest,
                "call_id": item.call_id,
                "tool_name": item.tool_name,
                "tool_schema_digest": item.tool_schema_digest,
                "tool_schema_version": item.tool_schema_version,
            }
            for item in proposals
        ],
        sort_keys=True,
        separators=(",", ":"),
    )


def _tool_proposals(value: object) -> tuple[ToolProposal, ...]:
    parsed = json.loads(str(value))
    expected = {
        "arguments_digest",
        "call_id",
        "tool_name",
        "tool_schema_digest",
        "tool_schema_version",
    }
    if not isinstance(parsed, list):
        raise ValueError("Stored tool proposals are invalid")
    proposals: list[ToolProposal] = []
    for item in parsed:
        if (
            not isinstance(item, dict)
            or set(item) != expected
            or not all(isinstance(item[key], str) for key in expected)
        ):
            raise ValueError("Stored tool proposal is invalid")
        proposals.append(
            ToolProposal(
                call_id=item["call_id"],
                tool_name=item["tool_name"],
                tool_schema_version=item["tool_schema_version"],
                tool_schema_digest=item["tool_schema_digest"],
                arguments_digest=item["arguments_digest"],
            )
        )
    return tuple(proposals)
