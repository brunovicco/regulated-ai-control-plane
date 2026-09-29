"""Domain-separated authority for terminal tool-action reconciliation."""

import base64
import binascii
import hashlib
import hmac
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from regulated_ai.domain import (
    ToolActionReconciliationGrant,
    ToolActionReconciliationOutcome,
    ToolActionReconciliationReceipt,
)

_PREFIX = "rr1"
_MAX_ASSERTION_BYTES = 4096
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z")
_PAYLOAD_FIELDS = {
    "action_digest",
    "actor_id",
    "expires_at",
    "issued_at",
    "outcome",
    "reconciliation_id",
    "schema_version",
    "subject_type",
    "tool_execution_id",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_action_reconciliation_consumption (
    reconciliation_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    action_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    tool_execution_id TEXT,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    authority_key_id TEXT,
    UNIQUE(action_id)
)
"""
_INSERT = """
INSERT INTO tool_action_reconciliation_consumption (
    reconciliation_id, actor_id, action_digest, action_id, outcome, tool_execution_id,
    issued_at, expires_at, consumed_at, authority_key_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class ToolActionReconciliationAssertionError(RuntimeError):
    """A reconciliation assertion is invalid, mismatched or not consumable."""


class _DuplicateJsonKeyError(ValueError):
    pass


class HmacToolActionReconciliationAdapter:
    """Verify exact reconciliation assertions and preserve replay evidence."""

    def __init__(
        self,
        path: Path,
        key: bytes,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Initialize a dedicated-key verifier and local consumption ledger."""
        if len(key) < 32:
            raise ValueError("Reconciliation HMAC key must be at least 32 bytes")
        self._key = bytes(key)
        self._initialize_ledger(path, max_lifetime_seconds)

    def _initialize_ledger(self, path: Path, max_lifetime_seconds: int) -> None:
        """Initialize the algorithm-independent local reconciliation ledger."""
        if max_lifetime_seconds <= 0 or max_lifetime_seconds > 86_400:
            raise ValueError("Reconciliation lifetime ceiling must be in the range [1, 86400]")
        self._path = path
        self._max_lifetime_seconds = max_lifetime_seconds
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_SCHEMA)
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(tool_action_reconciliation_consumption)"
                ).fetchall()
            }
            if "authority_key_id" not in columns:
                connection.execute(
                    "ALTER TABLE tool_action_reconciliation_consumption "
                    "ADD COLUMN authority_key_id TEXT"
                )

    def inspect(
        self,
        assertion: str,
        *,
        action_digest: str,
        now: datetime,
    ) -> ToolActionReconciliationGrant:
        """Verify signature, action/outcome binding and bounded validity."""
        checked_now = _utc_datetime(now, "Reconciliation verification time")
        if not assertion or len(assertion.encode()) > _MAX_ASSERTION_BYTES:
            raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
        prefix, separator, remainder = assertion.partition(".")
        payload_segment, signature_separator, signature_segment = remainder.partition(".")
        if (
            prefix != _PREFIX
            or not separator
            or not signature_separator
            or not payload_segment
            or not signature_segment
            or "." in signature_segment
            or _BASE64URL.fullmatch(payload_segment) is None
            or _BASE64URL.fullmatch(signature_segment) is None
        ):
            raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
        try:
            signed = f"{prefix}.{payload_segment}".encode("ascii", errors="strict")
        except UnicodeEncodeError as exc:
            raise ToolActionReconciliationAssertionError(
                "Reconciliation assertion is invalid"
            ) from exc
        expected_signature = hmac.new(self._key, signed, hashlib.sha256).digest()
        if not hmac.compare_digest(_decode_segment(signature_segment), expected_signature):
            raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")

        payload = _payload(payload_segment)
        reconciliation_id = _required_string(payload, "reconciliation_id")
        actor_id = _required_string(payload, "actor_id")
        asserted_digest = _required_string(payload, "action_digest")
        if payload.get("schema_version") != "1" or payload.get("subject_type") != (
            "tool_action_reconciliation"
        ):
            raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
        try:
            outcome = ToolActionReconciliationOutcome(_required_string(payload, "outcome"))
        except ValueError as exc:
            raise ToolActionReconciliationAssertionError(
                "Reconciliation assertion is invalid"
            ) from exc
        tool_execution_value = payload.get("tool_execution_id")
        tool_execution_id = tool_execution_value if isinstance(tool_execution_value, str) else None
        if (
            _SAFE_ID.fullmatch(reconciliation_id) is None
            or _SAFE_ID.fullmatch(actor_id) is None
            or _DIGEST.fullmatch(asserted_digest) is None
            or asserted_digest != action_digest
            or (
                outcome is ToolActionReconciliationOutcome.EXECUTED
                and (tool_execution_id is None or _SAFE_ID.fullmatch(tool_execution_id) is None)
            )
            or (
                outcome is ToolActionReconciliationOutcome.NOT_EXECUTED
                and tool_execution_value is not None
            )
        ):
            raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
        issued_at = _timestamp(payload, "issued_at")
        expires_at = _timestamp(payload, "expires_at")
        lifetime = int((expires_at - issued_at).total_seconds())
        if (
            issued_at > checked_now
            or expires_at <= checked_now
            or lifetime <= 0
            or lifetime > self._max_lifetime_seconds
        ):
            existing = self.get(reconciliation_id)
            candidate = ToolActionReconciliationGrant(
                reconciliation_id=reconciliation_id,
                actor_id=actor_id,
                action_digest=asserted_digest,
                outcome=outcome,
                tool_execution_id=tool_execution_id,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            if existing is None or not _same_grant_binding(existing, candidate):
                raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
            return candidate
        return ToolActionReconciliationGrant(
            reconciliation_id=reconciliation_id,
            actor_id=actor_id,
            action_digest=asserted_digest,
            outcome=outcome,
            tool_execution_id=tool_execution_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def consume(
        self,
        grant: ToolActionReconciliationGrant,
        *,
        action_id: str,
        now: datetime,
    ) -> ToolActionReconciliationReceipt:
        """Consume a grant, allowing exact recovery after a partial local failure."""
        checked_now = _utc_datetime(now, "Reconciliation consumption time")
        issued_at = _utc_datetime(grant.issued_at, "Reconciliation issuance time")
        expires_at = _utc_datetime(grant.expires_at, "Reconciliation expiration time")
        if (
            _SAFE_ID.fullmatch(grant.reconciliation_id) is None
            or _SAFE_ID.fullmatch(grant.actor_id) is None
            or (
                grant.authority_key_id is not None
                and _SAFE_ID.fullmatch(grant.authority_key_id) is None
            )
            or _DIGEST.fullmatch(grant.action_digest) is None
            or _SAFE_ID.fullmatch(action_id) is None
            or expires_at <= issued_at
            or (expires_at - issued_at).total_seconds() > self._max_lifetime_seconds
            or not _valid_outcome_binding(grant.outcome, grant.tool_execution_id)
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
            if not _same_binding(existing, receipt):
                raise ToolActionReconciliationAssertionError(
                    "Reconciliation assertion cannot be consumed"
                )
            return existing
        if issued_at > checked_now or checked_now >= expires_at:
            raise ToolActionReconciliationAssertionError(
                "Reconciliation assertion cannot be consumed"
            )
        try:
            with self._connect() as connection:
                connection.execute(
                    _INSERT,
                    (
                        receipt.reconciliation_id,
                        receipt.actor_id,
                        receipt.action_digest,
                        receipt.action_id,
                        receipt.outcome.value,
                        receipt.tool_execution_id,
                        receipt.issued_at.isoformat(),
                        receipt.expires_at.isoformat(),
                        receipt.consumed_at.isoformat(),
                        receipt.authority_key_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get(receipt.reconciliation_id)
            if existing is None or not _same_binding(existing, receipt):
                raise ToolActionReconciliationAssertionError(
                    "Reconciliation assertion cannot be consumed"
                ) from exc
            return existing
        return receipt

    def get(self, reconciliation_id: str) -> ToolActionReconciliationReceipt | None:
        """Return metadata-only reconciliation consumption evidence."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT reconciliation_id, actor_id, action_digest, action_id, outcome, "
                "tool_execution_id, issued_at, expires_at, consumed_at, authority_key_id "
                "FROM tool_action_reconciliation_consumption WHERE reconciliation_id = ?",
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
            issued_at=datetime.fromisoformat(str(row[6])),
            expires_at=datetime.fromisoformat(str(row[7])),
            consumed_at=datetime.fromisoformat(str(row[8])),
            authority_key_id=None if row[9] is None else str(row[9]),
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


def _valid_outcome_binding(
    outcome: ToolActionReconciliationOutcome, tool_execution_id: str | None
) -> bool:
    if outcome is ToolActionReconciliationOutcome.EXECUTED:
        return tool_execution_id is not None and _SAFE_ID.fullmatch(tool_execution_id) is not None
    return outcome is ToolActionReconciliationOutcome.NOT_EXECUTED and tool_execution_id is None


def _same_binding(
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


def _same_grant_binding(
    stored: ToolActionReconciliationReceipt,
    requested: ToolActionReconciliationGrant,
) -> bool:
    return (
        stored.reconciliation_id == requested.reconciliation_id
        and stored.actor_id == requested.actor_id
        and stored.action_digest == requested.action_digest
        and stored.outcome is requested.outcome
        and stored.tool_execution_id == requested.tool_execution_id
        and stored.issued_at == requested.issued_at
        and stored.expires_at == requested.expires_at
        and stored.authority_key_id == requested.authority_key_id
    )


def _payload(segment: str) -> dict[str, object]:
    try:
        raw = _decode_segment(segment)
        parsed = cast(
            object,
            json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_json_object),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKeyError) as exc:
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid") from exc
    if not isinstance(parsed, dict) or set(parsed) != _PAYLOAD_FIELDS:
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
    canonical = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    if raw != canonical:
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
    return parsed


def _decode_segment(segment: str) -> bytes:
    try:
        encoded = segment.encode("ascii", errors="strict")
        padding = b"=" * (-len(encoded) % 4)
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid") from exc
    if encoded != base64.urlsafe_b64encode(decoded).rstrip(b"="):
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
    return decoded


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
    return value


def _timestamp(payload: dict[str, object], key: str) -> datetime:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid") from exc


def _utc_datetime(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ToolActionReconciliationAssertionError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
