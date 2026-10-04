"""PostgreSQL replay ledgers for externally issued HMAC authority."""

import re
from datetime import UTC, datetime

from psycopg.errors import UniqueViolation

from regulated_ai.adapters.action_approval import (
    ActionApprovalAssertionError,
    HmacActionApprovalAdapter,
)
from regulated_ai.adapters.approval import ApprovalAssertionError, HmacApprovalAdapter
from regulated_ai.adapters.evidence_postgres import (
    PostgresDatabase,
    PostgresEnforcementRepository,
    PostgresToolActionRepository,
)
from regulated_ai.adapters.evidence_sqlite import (
    _action_approval_receipt_json,
    _approval_receipt_json,
    _tool_action_reconciliation_receipt_json,
)
from regulated_ai.adapters.reconciliation import (
    HmacToolActionReconciliationAdapter,
    ToolActionReconciliationAssertionError,
)
from regulated_ai.domain import (
    ActionApprovalGrant,
    ActionApprovalReceipt,
    ApprovalGrant,
    ApprovalReceipt,
    EnforcementRecord,
    EnforcementStatus,
    ToolActionReconciliationGrant,
    ToolActionReconciliationOutcome,
    ToolActionReconciliationReceipt,
    ToolActionRecord,
    ToolActionStatus,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PostgresHmacApprovalAdapter(HmacApprovalAdapter):
    """Verify decision approvals and consume them in a shared PostgreSQL ledger."""

    def __init__(
        self,
        database: PostgresDatabase,
        key: bytes,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind decision verification to the shared production ledger."""
        if len(key) < 32:
            raise ValueError("Approval HMAC key must be at least 32 bytes")
        self._key = bytes(key)
        self._initialize_database(database, max_lifetime_seconds)

    def _initialize_database(self, database: PostgresDatabase, max_lifetime_seconds: int) -> None:
        """Initialize the algorithm-independent PostgreSQL decision ledger."""
        _validate_lifetime(max_lifetime_seconds, "Approval")
        self._database = database
        self._max_lifetime_seconds = max_lifetime_seconds

    def consume(
        self,
        grant: ApprovalGrant,
        *,
        enforcement_id: str,
        now: datetime,
    ) -> ApprovalReceipt:
        """Atomically consume a still-valid approval identifier."""
        checked_now = _utc(now, "Approval consumption time", ApprovalAssertionError)
        issued_at = _utc(grant.issued_at, "Approval issuance time", ApprovalAssertionError)
        expires_at = _utc(grant.expires_at, "Approval expiration time", ApprovalAssertionError)
        if (
            not _valid_identifier(grant.approval_id)
            or not _valid_identifier(grant.actor_id)
            or not _valid_authority_key(grant.authority_key_id)
            or _DIGEST.fullmatch(grant.decision_digest) is None
            or not _valid_identifier(enforcement_id)
            or not _valid_window(issued_at, expires_at, checked_now, self._max_lifetime_seconds)
        ):
            raise ApprovalAssertionError("Approval assertion cannot be consumed")
        receipt = ApprovalReceipt(
            approval_id=grant.approval_id,
            actor_id=grant.actor_id,
            decision_digest=grant.decision_digest,
            enforcement_id=enforcement_id,
            issued_at=issued_at,
            expires_at=expires_at,
            consumed_at=checked_now,
            authority_key_id=grant.authority_key_id,
        )
        try:
            with self._database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO approval_consumption (
                        approval_id, actor_id, decision_digest, enforcement_id,
                        issued_at, expires_at, consumed_at, authority_key_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        receipt.approval_id,
                        receipt.actor_id,
                        receipt.decision_digest,
                        receipt.enforcement_id,
                        receipt.issued_at,
                        receipt.expires_at,
                        receipt.consumed_at,
                        receipt.authority_key_id,
                    ),
                )
        except UniqueViolation as exc:
            raise ApprovalAssertionError("Approval assertion cannot be consumed") from exc
        return receipt

    def claim_execution(
        self,
        grant: ApprovalGrant,
        *,
        record: EnforcementRecord,
        now: datetime,
    ) -> tuple[EnforcementRecord, bool, ApprovalReceipt | None]:
        """Consume approval and claim the prepared enforcement in one transaction."""
        if record.status is not EnforcementStatus.DISPATCHED:
            raise ValueError("Execution claim requires DISPATCHED status")
        receipt = _decision_receipt(
            grant,
            enforcement_id=record.enforcement_id,
            now=now,
            maximum_seconds=self._max_lifetime_seconds,
        )
        try:
            with self._database.connect() as connection:
                claimed = connection.execute(
                    "UPDATE enforcement SET status='DISPATCHED', approval_receipt=%s "
                    "WHERE enforcement_id=%s AND status='PREPARED' RETURNING enforcement_id",
                    (_approval_receipt_json(receipt), record.enforcement_id),
                ).fetchone()
                if claimed is not None:
                    connection.execute(
                        """
                        INSERT INTO approval_consumption (
                            approval_id, actor_id, decision_digest, enforcement_id,
                            issued_at, expires_at, consumed_at, authority_key_id
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            receipt.approval_id,
                            receipt.actor_id,
                            receipt.decision_digest,
                            receipt.enforcement_id,
                            receipt.issued_at,
                            receipt.expires_at,
                            receipt.consumed_at,
                            receipt.authority_key_id,
                        ),
                    )
        except UniqueViolation as exc:
            raise ApprovalAssertionError("Approval assertion cannot be consumed") from exc
        stored = PostgresEnforcementRepository(self._database).get(record.enforcement_id)
        if stored is None:
            raise RuntimeError("Execution claim has no enforcement record")
        return stored, claimed is not None, receipt if claimed is not None else None

    def get(self, approval_id: str) -> ApprovalReceipt | None:
        """Return metadata-only decision approval consumption evidence."""
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT approval_id, actor_id, decision_digest, enforcement_id,
                       issued_at, expires_at, consumed_at, authority_key_id
                FROM approval_consumption WHERE approval_id=%s
                """,
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return ApprovalReceipt(
            approval_id=str(row[0]),
            actor_id=str(row[1]),
            decision_digest=str(row[2]),
            enforcement_id=str(row[3]),
            issued_at=_as_datetime(row[4]),
            expires_at=_as_datetime(row[5]),
            consumed_at=_as_datetime(row[6]),
            authority_key_id=None if row[7] is None else str(row[7]),
        )


class PostgresHmacActionApprovalAdapter(HmacActionApprovalAdapter):
    """Verify action approvals and consume them in a shared PostgreSQL ledger."""

    def __init__(
        self,
        database: PostgresDatabase,
        key: bytes,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind action verification to the shared production ledger."""
        if len(key) < 32:
            raise ValueError("Action approval HMAC key must be at least 32 bytes")
        self._key = bytes(key)
        self._initialize_database(database, max_lifetime_seconds)

    def _initialize_database(self, database: PostgresDatabase, max_lifetime_seconds: int) -> None:
        """Initialize the algorithm-independent PostgreSQL action ledger."""
        _validate_lifetime(max_lifetime_seconds, "Action approval")
        self._database = database
        self._max_lifetime_seconds = max_lifetime_seconds

    def consume(
        self,
        grant: ActionApprovalGrant,
        *,
        action_id: str,
        now: datetime,
    ) -> ActionApprovalReceipt:
        """Atomically consume a still-valid action approval identifier."""
        checked_now = _utc(now, "Action approval consumption time", ActionApprovalAssertionError)
        issued_at = _utc(
            grant.issued_at, "Action approval issuance time", ActionApprovalAssertionError
        )
        expires_at = _utc(
            grant.expires_at, "Action approval expiration time", ActionApprovalAssertionError
        )
        if (
            not _valid_identifier(grant.approval_id)
            or not _valid_identifier(grant.actor_id)
            or not _valid_authority_key(grant.authority_key_id)
            or _DIGEST.fullmatch(grant.action_digest) is None
            or not _valid_identifier(action_id)
            or not _valid_window(issued_at, expires_at, checked_now, self._max_lifetime_seconds)
        ):
            raise ActionApprovalAssertionError("Action approval assertion cannot be consumed")
        receipt = ActionApprovalReceipt(
            approval_id=grant.approval_id,
            actor_id=grant.actor_id,
            action_digest=grant.action_digest,
            action_id=action_id,
            issued_at=issued_at,
            expires_at=expires_at,
            consumed_at=checked_now,
            authority_key_id=grant.authority_key_id,
        )
        try:
            with self._database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO action_approval_consumption (
                        approval_id, actor_id, action_digest, action_id,
                        issued_at, expires_at, consumed_at, authority_key_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        receipt.approval_id,
                        receipt.actor_id,
                        receipt.action_digest,
                        receipt.action_id,
                        receipt.issued_at,
                        receipt.expires_at,
                        receipt.consumed_at,
                        receipt.authority_key_id,
                    ),
                )
        except UniqueViolation as exc:
            raise ActionApprovalAssertionError(
                "Action approval assertion cannot be consumed"
            ) from exc
        return receipt

    def claim_execution(
        self,
        grant: ActionApprovalGrant,
        *,
        record: ToolActionRecord,
        now: datetime,
    ) -> tuple[ToolActionRecord, bool, ActionApprovalReceipt | None]:
        """Consume approval and claim the prepared tool action in one transaction."""
        if record.status is not ToolActionStatus.DISPATCHED:
            raise ValueError("Tool-action claim requires DISPATCHED status")
        receipt = _action_receipt(
            grant,
            action_id=record.action_id,
            now=now,
            maximum_seconds=self._max_lifetime_seconds,
        )
        try:
            with self._database.connect() as connection:
                claimed = connection.execute(
                    "UPDATE tool_action SET status='DISPATCHED', approval_receipt=%s "
                    "WHERE action_id=%s AND status='PREPARED' RETURNING action_id",
                    (_action_approval_receipt_json(receipt), record.action_id),
                ).fetchone()
                if claimed is not None:
                    connection.execute(
                        """
                        INSERT INTO action_approval_consumption (
                            approval_id, actor_id, action_digest, action_id,
                            issued_at, expires_at, consumed_at, authority_key_id
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            receipt.approval_id,
                            receipt.actor_id,
                            receipt.action_digest,
                            receipt.action_id,
                            receipt.issued_at,
                            receipt.expires_at,
                            receipt.consumed_at,
                            receipt.authority_key_id,
                        ),
                    )
        except UniqueViolation as exc:
            with self._database.connect() as connection:
                connection.execute(
                    "UPDATE tool_action SET status='APPROVAL_FAILED' "
                    "WHERE action_id=%s AND status='PREPARED'",
                    (record.action_id,),
                )
            raise ActionApprovalAssertionError(
                "Action approval assertion cannot be consumed"
            ) from exc
        stored = PostgresToolActionRepository(self._database).get(record.action_id)
        if stored is None:
            raise RuntimeError("Tool-action claim has no record")
        return stored, claimed is not None, receipt if claimed is not None else None

    def get(self, approval_id: str) -> ActionApprovalReceipt | None:
        """Return metadata-only action approval consumption evidence."""
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT approval_id, actor_id, action_digest, action_id,
                       issued_at, expires_at, consumed_at, authority_key_id
                FROM action_approval_consumption WHERE approval_id=%s
                """,
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return ActionApprovalReceipt(
            approval_id=str(row[0]),
            actor_id=str(row[1]),
            action_digest=str(row[2]),
            action_id=str(row[3]),
            issued_at=_as_datetime(row[4]),
            expires_at=_as_datetime(row[5]),
            consumed_at=_as_datetime(row[6]),
            authority_key_id=None if row[7] is None else str(row[7]),
        )


class PostgresHmacToolActionReconciliationAdapter(HmacToolActionReconciliationAdapter):
    """Verify reconciliation authority and retain exact-replay state in PostgreSQL."""

    def __init__(
        self,
        database: PostgresDatabase,
        key: bytes,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind reconciliation verification to the shared production ledger."""
        if len(key) < 32:
            raise ValueError("Reconciliation HMAC key must be at least 32 bytes")
        self._key = bytes(key)
        self._initialize_database(database, max_lifetime_seconds)

    def _initialize_database(self, database: PostgresDatabase, max_lifetime_seconds: int) -> None:
        """Initialize the algorithm-independent PostgreSQL reconciliation ledger."""
        _validate_lifetime(max_lifetime_seconds, "Reconciliation")
        self._database = database
        self._max_lifetime_seconds = max_lifetime_seconds

    def consume(
        self,
        grant: ToolActionReconciliationGrant,
        *,
        action_id: str,
        now: datetime,
    ) -> ToolActionReconciliationReceipt:
        """Consume once while allowing exact recovery after a partial application failure."""
        checked_now = _utc(
            now, "Reconciliation consumption time", ToolActionReconciliationAssertionError
        )
        issued_at = _utc(
            grant.issued_at,
            "Reconciliation issuance time",
            ToolActionReconciliationAssertionError,
        )
        expires_at = _utc(
            grant.expires_at,
            "Reconciliation expiration time",
            ToolActionReconciliationAssertionError,
        )
        if (
            not _valid_identifier(grant.reconciliation_id)
            or not _valid_identifier(grant.actor_id)
            or not _valid_authority_key(grant.authority_key_id)
            or _DIGEST.fullmatch(grant.action_digest) is None
            or not _valid_identifier(action_id)
            or expires_at <= issued_at
            or (expires_at - issued_at).total_seconds() > self._max_lifetime_seconds
            or not _valid_outcome(grant.outcome, grant.tool_execution_id)
        ):
            raise ToolActionReconciliationAssertionError(
                "Reconciliation assertion cannot be consumed"
            )
        receipt = ToolActionReconciliationReceipt(
            reconciliation_id=grant.reconciliation_id,
            actor_id=grant.actor_id,
            action_digest=grant.action_digest,
            action_id=action_id,
            outcome=grant.outcome,
            tool_execution_id=grant.tool_execution_id,
            issued_at=issued_at,
            expires_at=expires_at,
            consumed_at=checked_now,
            authority_key_id=grant.authority_key_id,
        )
        existing = self.get(receipt.reconciliation_id)
        if existing is not None:
            if not _same_reconciliation(existing, receipt):
                raise ToolActionReconciliationAssertionError(
                    "Reconciliation assertion cannot be consumed"
                )
            return existing
        if issued_at > checked_now or checked_now >= expires_at:
            raise ToolActionReconciliationAssertionError(
                "Reconciliation assertion cannot be consumed"
            )
        try:
            with self._database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO tool_action_reconciliation_consumption (
                        reconciliation_id, actor_id, action_digest, action_id, outcome,
                        tool_execution_id, issued_at, expires_at, consumed_at, authority_key_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        receipt.reconciliation_id,
                        receipt.actor_id,
                        receipt.action_digest,
                        receipt.action_id,
                        receipt.outcome.value,
                        receipt.tool_execution_id,
                        receipt.issued_at,
                        receipt.expires_at,
                        receipt.consumed_at,
                        receipt.authority_key_id,
                    ),
                )
        except UniqueViolation as exc:
            existing = self.get(receipt.reconciliation_id)
            if existing is None or not _same_reconciliation(existing, receipt):
                raise ToolActionReconciliationAssertionError(
                    "Reconciliation assertion cannot be consumed"
                ) from exc
            return existing
        return receipt

    def reconcile(
        self,
        grant: ToolActionReconciliationGrant,
        *,
        record: ToolActionRecord,
        now: datetime,
    ) -> ToolActionRecord:
        """Consume authority and close an ambiguous action in one transaction."""
        if record.status is not ToolActionStatus.RECONCILIATION_REQUIRED:
            raise ToolActionReconciliationAssertionError(
                "Tool action does not require reconciliation"
            )
        receipt = _reconciliation_receipt(
            grant,
            action_id=record.action_id,
            now=now,
            maximum_seconds=self._max_lifetime_seconds,
        )
        target = (
            ToolActionStatus.RECONCILED_EXECUTED
            if grant.outcome is ToolActionReconciliationOutcome.EXECUTED
            else ToolActionStatus.RECONCILED_NOT_EXECUTED
        )
        try:
            with self._database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO tool_action_reconciliation_consumption (
                        reconciliation_id, actor_id, action_digest, action_id, outcome,
                        tool_execution_id, issued_at, expires_at, consumed_at, authority_key_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        receipt.reconciliation_id,
                        receipt.actor_id,
                        receipt.action_digest,
                        receipt.action_id,
                        receipt.outcome.value,
                        receipt.tool_execution_id,
                        receipt.issued_at,
                        receipt.expires_at,
                        receipt.consumed_at,
                        receipt.authority_key_id,
                    ),
                )
                updated = connection.execute(
                    "UPDATE tool_action SET status=%s, tool_execution_id=%s, "
                    "reconciliation_receipt=%s "
                    "WHERE action_id=%s AND status='RECONCILIATION_REQUIRED' RETURNING action_id",
                    (
                        target.value,
                        receipt.tool_execution_id,
                        _tool_action_reconciliation_receipt_json(receipt),
                        record.action_id,
                    ),
                ).fetchone()
                if updated is None:
                    raise ToolActionReconciliationAssertionError(
                        "Tool action does not require reconciliation"
                    )
        except UniqueViolation as exc:
            existing = self.get(receipt.reconciliation_id)
            stored = PostgresToolActionRepository(self._database).get(record.action_id)
            if (
                existing is None
                or stored is None
                or not _same_reconciliation(existing, receipt)
                or stored.status is not target
                or stored.reconciliation_receipt != existing
            ):
                raise ToolActionReconciliationAssertionError(
                    "Reconciliation assertion cannot be consumed"
                ) from exc
            return stored
        stored = PostgresToolActionRepository(self._database).get(record.action_id)
        if stored is None:
            raise RuntimeError("Reconciled tool action has no record")
        return stored

    def get(self, reconciliation_id: str) -> ToolActionReconciliationReceipt | None:
        """Return metadata-only reconciliation consumption evidence."""
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT reconciliation_id, actor_id, action_digest, action_id, outcome,
                       tool_execution_id, issued_at, expires_at, consumed_at, authority_key_id
                FROM tool_action_reconciliation_consumption WHERE reconciliation_id=%s
                """,
                (reconciliation_id,),
            ).fetchone()
        if row is None:
            return None
        return ToolActionReconciliationReceipt(
            reconciliation_id=str(row[0]),
            actor_id=str(row[1]),
            action_digest=str(row[2]),
            action_id=str(row[3]),
            outcome=ToolActionReconciliationOutcome(str(row[4])),
            tool_execution_id=None if row[5] is None else str(row[5]),
            issued_at=_as_datetime(row[6]),
            expires_at=_as_datetime(row[7]),
            consumed_at=_as_datetime(row[8]),
            authority_key_id=None if row[9] is None else str(row[9]),
        )


def _validate_lifetime(value: int, label: str) -> None:
    if value <= 0 or value > 86_400:
        raise ValueError(f"{label} lifetime ceiling must be in the range [1, 86400]")


def _decision_receipt(
    grant: ApprovalGrant,
    *,
    enforcement_id: str,
    now: datetime,
    maximum_seconds: int,
) -> ApprovalReceipt:
    checked_now = _utc(now, "Approval consumption time", ApprovalAssertionError)
    issued_at = _utc(grant.issued_at, "Approval issuance time", ApprovalAssertionError)
    expires_at = _utc(grant.expires_at, "Approval expiration time", ApprovalAssertionError)
    if (
        not _valid_identifier(grant.approval_id)
        or not _valid_identifier(grant.actor_id)
        or not _valid_authority_key(grant.authority_key_id)
        or _DIGEST.fullmatch(grant.decision_digest) is None
        or not _valid_identifier(enforcement_id)
        or not _valid_window(issued_at, expires_at, checked_now, maximum_seconds)
    ):
        raise ApprovalAssertionError("Approval assertion cannot be consumed")
    return ApprovalReceipt(
        approval_id=grant.approval_id,
        actor_id=grant.actor_id,
        decision_digest=grant.decision_digest,
        enforcement_id=enforcement_id,
        issued_at=issued_at,
        expires_at=expires_at,
        consumed_at=checked_now,
        authority_key_id=grant.authority_key_id,
    )


def _action_receipt(
    grant: ActionApprovalGrant,
    *,
    action_id: str,
    now: datetime,
    maximum_seconds: int,
) -> ActionApprovalReceipt:
    checked_now = _utc(now, "Action approval consumption time", ActionApprovalAssertionError)
    issued_at = _utc(grant.issued_at, "Action approval issuance time", ActionApprovalAssertionError)
    expires_at = _utc(
        grant.expires_at, "Action approval expiration time", ActionApprovalAssertionError
    )
    if (
        not _valid_identifier(grant.approval_id)
        or not _valid_identifier(grant.actor_id)
        or not _valid_authority_key(grant.authority_key_id)
        or _DIGEST.fullmatch(grant.action_digest) is None
        or not _valid_identifier(action_id)
        or not _valid_window(issued_at, expires_at, checked_now, maximum_seconds)
    ):
        raise ActionApprovalAssertionError("Action approval assertion cannot be consumed")
    return ActionApprovalReceipt(
        approval_id=grant.approval_id,
        actor_id=grant.actor_id,
        action_digest=grant.action_digest,
        action_id=action_id,
        issued_at=issued_at,
        expires_at=expires_at,
        consumed_at=checked_now,
        authority_key_id=grant.authority_key_id,
    )


def _reconciliation_receipt(
    grant: ToolActionReconciliationGrant,
    *,
    action_id: str,
    now: datetime,
    maximum_seconds: int,
) -> ToolActionReconciliationReceipt:
    checked_now = _utc(
        now, "Reconciliation consumption time", ToolActionReconciliationAssertionError
    )
    issued_at = _utc(
        grant.issued_at, "Reconciliation issuance time", ToolActionReconciliationAssertionError
    )
    expires_at = _utc(
        grant.expires_at, "Reconciliation expiration time", ToolActionReconciliationAssertionError
    )
    if (
        not _valid_identifier(grant.reconciliation_id)
        or not _valid_identifier(grant.actor_id)
        or not _valid_authority_key(grant.authority_key_id)
        or _DIGEST.fullmatch(grant.action_digest) is None
        or not _valid_identifier(action_id)
        or not _valid_window(issued_at, expires_at, checked_now, maximum_seconds)
        or not _valid_outcome(grant.outcome, grant.tool_execution_id)
    ):
        raise ToolActionReconciliationAssertionError("Reconciliation assertion cannot be consumed")
    return ToolActionReconciliationReceipt(
        reconciliation_id=grant.reconciliation_id,
        actor_id=grant.actor_id,
        action_digest=grant.action_digest,
        action_id=action_id,
        outcome=grant.outcome,
        tool_execution_id=grant.tool_execution_id,
        issued_at=issued_at,
        expires_at=expires_at,
        consumed_at=checked_now,
        authority_key_id=grant.authority_key_id,
    )


def _valid_identifier(value: str) -> bool:
    return _SAFE_ID.fullmatch(value) is not None


def _valid_authority_key(value: str | None) -> bool:
    return value is None or _valid_identifier(value)


def _valid_window(
    issued_at: datetime,
    expires_at: datetime,
    now: datetime,
    maximum_seconds: int,
) -> bool:
    return (
        issued_at <= now < expires_at
        and expires_at > issued_at
        and (expires_at - issued_at).total_seconds() <= maximum_seconds
    )


def _valid_outcome(outcome: ToolActionReconciliationOutcome, tool_execution_id: str | None) -> bool:
    if outcome is ToolActionReconciliationOutcome.EXECUTED:
        return tool_execution_id is not None and _valid_identifier(tool_execution_id)
    return outcome is ToolActionReconciliationOutcome.NOT_EXECUTED and tool_execution_id is None


def _same_reconciliation(
    stored: ToolActionReconciliationReceipt,
    requested: ToolActionReconciliationReceipt,
) -> bool:
    return (
        stored.reconciliation_id == requested.reconciliation_id
        and stored.actor_id == requested.actor_id
        and stored.action_digest == requested.action_digest
        and stored.action_id == requested.action_id
        and stored.outcome is requested.outcome
        and stored.tool_execution_id == requested.tool_execution_id
        and stored.issued_at == requested.issued_at
        and stored.expires_at == requested.expires_at
        and stored.authority_key_id == requested.authority_key_id
    )


def _utc(
    value: datetime,
    label: str,
    error_type: type[RuntimeError],
) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise error_type(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
