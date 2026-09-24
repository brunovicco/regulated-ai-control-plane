"""Domain-separated HMAC assertions for exact tool-action authority."""

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

from regulated_ai.domain import ActionApprovalGrant, ActionApprovalReceipt

_PREFIX = "ra2"
_MAX_ASSERTION_BYTES = 4096
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z")
_PAYLOAD_FIELDS = {
    "action_digest",
    "actor_id",
    "approval_id",
    "expires_at",
    "issued_at",
    "schema_version",
    "subject_type",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_approval_consumption (
    approval_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    action_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT NOT NULL
)
"""
_INSERT = """
INSERT INTO action_approval_consumption (
    approval_id, actor_id, action_digest, action_id, issued_at, expires_at, consumed_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
"""


class ActionApprovalAssertionError(RuntimeError):
    """An action assertion is invalid, expired, mismatched or already consumed."""


class _DuplicateJsonKeyError(ValueError):
    pass


class HmacActionApprovalAdapter:
    """Verify domain-separated action assertions and prevent replay."""

    def __init__(
        self,
        path: Path,
        key: bytes,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Initialize a dedicated-key verifier and local action replay ledger."""
        if len(key) < 32:
            raise ValueError("Action approval HMAC key must be at least 32 bytes")
        if max_lifetime_seconds <= 0 or max_lifetime_seconds > 86_400:
            raise ValueError("Action approval lifetime ceiling must be in the range [1, 86400]")
        self._path = path
        self._key = bytes(key)
        self._max_lifetime_seconds = max_lifetime_seconds
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_SCHEMA)

    def inspect(
        self,
        assertion: str,
        *,
        action_digest: str,
        now: datetime,
    ) -> ActionApprovalGrant:
        """Verify signature, action binding and time bounds without consuming authority."""
        checked_now = _utc_datetime(now, "Action approval verification time")
        if not assertion or len(assertion.encode()) > _MAX_ASSERTION_BYTES:
            raise ActionApprovalAssertionError("Action approval assertion is invalid")
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
            raise ActionApprovalAssertionError("Action approval assertion is invalid")
        try:
            signed = f"{prefix}.{payload_segment}".encode("ascii", errors="strict")
        except UnicodeEncodeError as exc:
            raise ActionApprovalAssertionError("Action approval assertion is invalid") from exc
        expected_signature = hmac.new(self._key, signed, hashlib.sha256).digest()
        if not hmac.compare_digest(_decode_segment(signature_segment), expected_signature):
            raise ActionApprovalAssertionError("Action approval assertion is invalid")

        payload = _payload(payload_segment)
        approval_id = _required_string(payload, "approval_id")
        actor_id = _required_string(payload, "actor_id")
        asserted_digest = _required_string(payload, "action_digest")
        if payload.get("schema_version") != "2" or payload.get("subject_type") != "tool_action":
            raise ActionApprovalAssertionError("Action approval assertion is invalid")
        if (
            _SAFE_ID.fullmatch(approval_id) is None
            or _SAFE_ID.fullmatch(actor_id) is None
            or _DIGEST.fullmatch(asserted_digest) is None
            or asserted_digest != action_digest
        ):
            raise ActionApprovalAssertionError("Action approval assertion is invalid")
        issued_at = _timestamp(payload, "issued_at")
        expires_at = _timestamp(payload, "expires_at")
        lifetime = int((expires_at - issued_at).total_seconds())
        if (
            issued_at > checked_now
            or expires_at <= checked_now
            or lifetime <= 0
            or lifetime > self._max_lifetime_seconds
        ):
            raise ActionApprovalAssertionError("Action approval assertion is invalid")
        return ActionApprovalGrant(
            approval_id=approval_id,
            actor_id=actor_id,
            action_digest=asserted_digest,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def consume(
        self,
        grant: ActionApprovalGrant,
        *,
        action_id: str,
        now: datetime,
    ) -> ActionApprovalReceipt:
        """Atomically consume a still-valid action approval identifier."""
        checked_now = _utc_datetime(now, "Action approval consumption time")
        issued_at = _utc_datetime(grant.issued_at, "Action approval issuance time")
        expires_at = _utc_datetime(grant.expires_at, "Action approval expiration time")
        if (
            _SAFE_ID.fullmatch(grant.approval_id) is None
            or _SAFE_ID.fullmatch(grant.actor_id) is None
            or _DIGEST.fullmatch(grant.action_digest) is None
            or _SAFE_ID.fullmatch(action_id) is None
            or issued_at > checked_now
            or checked_now >= expires_at
            or expires_at <= issued_at
            or (expires_at - issued_at).total_seconds() > self._max_lifetime_seconds
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
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    _INSERT,
                    (
                        receipt.approval_id,
                        receipt.actor_id,
                        receipt.action_digest,
                        receipt.action_id,
                        receipt.issued_at.isoformat(),
                        receipt.expires_at.isoformat(),
                        receipt.consumed_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ActionApprovalAssertionError(
                "Action approval assertion cannot be consumed"
            ) from exc
        return receipt

    def get(self, approval_id: str) -> ActionApprovalReceipt | None:
        """Return metadata-only action approval consumption evidence."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM action_approval_consumption WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return ActionApprovalReceipt(
            approval_id=str(row[0]),
            actor_id=str(row[1]),
            action_digest=str(row[2]),
            action_id=str(row[3]),
            issued_at=datetime.fromisoformat(str(row[4])),
            expires_at=datetime.fromisoformat(str(row[5])),
            consumed_at=datetime.fromisoformat(str(row[6])),
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


def _payload(segment: str) -> dict[str, object]:
    try:
        raw = _decode_segment(segment)
        parsed = cast(
            object,
            json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_json_object),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKeyError) as exc:
        raise ActionApprovalAssertionError("Action approval assertion is invalid") from exc
    if not isinstance(parsed, dict) or set(parsed) != _PAYLOAD_FIELDS:
        raise ActionApprovalAssertionError("Action approval assertion is invalid")
    canonical = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    if raw != canonical:
        raise ActionApprovalAssertionError("Action approval assertion is invalid")
    return parsed


def _decode_segment(segment: str) -> bytes:
    try:
        encoded = segment.encode("ascii", errors="strict")
        padding = b"=" * (-len(encoded) % 4)
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ActionApprovalAssertionError("Action approval assertion is invalid") from exc
    if encoded != base64.urlsafe_b64encode(decoded).rstrip(b"="):
        raise ActionApprovalAssertionError("Action approval assertion is invalid")
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
        raise ActionApprovalAssertionError("Action approval assertion is invalid")
    return value


def _timestamp(payload: dict[str, object], key: str) -> datetime:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ActionApprovalAssertionError("Action approval assertion is invalid")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ActionApprovalAssertionError("Action approval assertion is invalid") from exc


def _utc_datetime(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ActionApprovalAssertionError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
