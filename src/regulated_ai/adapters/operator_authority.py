"""Asymmetric, role-bound operator authority for production mutations."""

import base64
import binascii
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.adapters.action_approval import (
    ActionApprovalAssertionError,
    HmacActionApprovalAdapter,
)
from regulated_ai.adapters.approval import ApprovalAssertionError, HmacApprovalAdapter
from regulated_ai.adapters.authority_postgres import (
    PostgresHmacActionApprovalAdapter,
    PostgresHmacApprovalAdapter,
    PostgresHmacToolActionReconciliationAdapter,
)
from regulated_ai.adapters.evidence_postgres import PostgresDatabase
from regulated_ai.adapters.reconciliation import (
    HmacToolActionReconciliationAdapter,
    ToolActionReconciliationAssertionError,
)
from regulated_ai.adapters.trust_key_lifecycle import TrustKeyLifecycleModel
from regulated_ai.domain import (
    ActionApprovalGrant,
    ApprovalGrant,
    ToolActionReconciliationGrant,
    ToolActionReconciliationOutcome,
    ToolActionReconciliationReceipt,
)

OperatorAuthorityKind = Literal["decision_approval", "action_approval", "reconciliation"]

_MAX_ASSERTION_BYTES = 4096
_MAX_TRUST_STORE_BYTES = 262_144
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z")
_DECISION_FIELDS = {
    "actor_id",
    "approval_id",
    "authority_kind",
    "decision_digest",
    "expires_at",
    "issued_at",
    "key_id",
    "schema_version",
}
_ACTION_FIELDS = {
    "action_digest",
    "actor_id",
    "approval_id",
    "authority_kind",
    "expires_at",
    "issued_at",
    "key_id",
    "schema_version",
    "subject_type",
}
_RECONCILIATION_FIELDS = {
    "action_digest",
    "actor_id",
    "authority_kind",
    "expires_at",
    "issued_at",
    "key_id",
    "outcome",
    "reconciliation_id",
    "schema_version",
    "subject_type",
    "tool_execution_id",
}


class OperatorAuthorityTrustStoreError(ValueError):
    """The operator authority trust store is unavailable or invalid."""


class _DuplicateJsonKeyError(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _OperatorKeyModel(TrustKeyLifecycleModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$",
    )
    authorities: tuple[OperatorAuthorityKind, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_authorities(self) -> "_OperatorKeyModel":
        if len(self.authorities) != len(set(self.authorities)):
            raise ValueError("operator authority key contains duplicate authorities")
        return self


class _OperatorTrustStoreModel(_StrictModel):
    schema_version: Literal["1"]
    keys: dict[str, _OperatorKeyModel] = Field(min_length=1, max_length=64)

    @field_validator("keys")
    @classmethod
    def valid_key_ids(cls, value: dict[str, _OperatorKeyModel]) -> dict[str, _OperatorKeyModel]:
        if any(_SAFE_ID.fullmatch(key_id) is None for key_id in value):
            raise ValueError("operator authority key identifier is invalid")
        return value


class Ed25519OperatorAuthorityVerifier:
    """Verify canonical assertions against a lifecycle-aware public trust store."""

    def __init__(self, trust_store_path: Path) -> None:
        """Load a deployment-controlled verification-only trust store."""
        self._trust_store = _load_trust_store(trust_store_path)

    def inspect_decision(
        self,
        assertion: str,
        *,
        decision_digest: str,
        now: datetime,
        max_lifetime_seconds: int,
    ) -> ApprovalGrant:
        """Verify one exact decision approval assertion."""
        checked_now = _utc(now, ApprovalAssertionError)
        payload = self._verify(
            assertion,
            prefix="ra1e",
            fields=_DECISION_FIELDS,
            authority="decision_approval",
            now=checked_now,
            error_type=ApprovalAssertionError,
        )
        approval_id = _required_string(payload, "approval_id", ApprovalAssertionError)
        actor_id = _required_string(payload, "actor_id", ApprovalAssertionError)
        asserted_digest = _required_string(payload, "decision_digest", ApprovalAssertionError)
        issued_at, expires_at = _valid_window(
            payload,
            checked_now,
            max_lifetime_seconds,
            ApprovalAssertionError,
        )
        if (
            payload.get("schema_version") != "2"
            or _SAFE_ID.fullmatch(approval_id) is None
            or _DIGEST.fullmatch(asserted_digest) is None
            or asserted_digest != decision_digest
        ):
            raise ApprovalAssertionError("Approval assertion is invalid")
        return ApprovalGrant(
            approval_id=approval_id,
            actor_id=actor_id,
            decision_digest=asserted_digest,
            issued_at=issued_at,
            expires_at=expires_at,
            authority_key_id=cast(str, payload["key_id"]),
        )

    def inspect_action(
        self,
        assertion: str,
        *,
        action_digest: str,
        now: datetime,
        max_lifetime_seconds: int,
    ) -> ActionApprovalGrant:
        """Verify one exact tool-action approval assertion."""
        checked_now = _utc(now, ActionApprovalAssertionError)
        payload = self._verify(
            assertion,
            prefix="ra2e",
            fields=_ACTION_FIELDS,
            authority="action_approval",
            now=checked_now,
            error_type=ActionApprovalAssertionError,
        )
        approval_id = _required_string(payload, "approval_id", ActionApprovalAssertionError)
        actor_id = _required_string(payload, "actor_id", ActionApprovalAssertionError)
        asserted_digest = _required_string(payload, "action_digest", ActionApprovalAssertionError)
        issued_at, expires_at = _valid_window(
            payload,
            checked_now,
            max_lifetime_seconds,
            ActionApprovalAssertionError,
        )
        if (
            payload.get("schema_version") != "3"
            or payload.get("subject_type") != "tool_action"
            or _SAFE_ID.fullmatch(approval_id) is None
            or _DIGEST.fullmatch(asserted_digest) is None
            or asserted_digest != action_digest
        ):
            raise ActionApprovalAssertionError("Action approval assertion is invalid")
        return ActionApprovalGrant(
            approval_id=approval_id,
            actor_id=actor_id,
            action_digest=asserted_digest,
            issued_at=issued_at,
            expires_at=expires_at,
            authority_key_id=cast(str, payload["key_id"]),
        )

    def inspect_reconciliation(
        self,
        assertion: str,
        *,
        action_digest: str,
        now: datetime,
        max_lifetime_seconds: int,
        existing: Callable[[str], ToolActionReconciliationReceipt | None],
    ) -> ToolActionReconciliationGrant:
        """Verify one exact terminal reconciliation assertion."""
        checked_now = _utc(now, ToolActionReconciliationAssertionError)
        payload = self._verify(
            assertion,
            prefix="rr1e",
            fields=_RECONCILIATION_FIELDS,
            authority="reconciliation",
            now=checked_now,
            error_type=ToolActionReconciliationAssertionError,
        )
        reconciliation_id = _required_string(
            payload, "reconciliation_id", ToolActionReconciliationAssertionError
        )
        actor_id = _required_string(payload, "actor_id", ToolActionReconciliationAssertionError)
        asserted_digest = _required_string(
            payload, "action_digest", ToolActionReconciliationAssertionError
        )
        try:
            outcome = ToolActionReconciliationOutcome(
                _required_string(payload, "outcome", ToolActionReconciliationAssertionError)
            )
        except ValueError as exc:
            raise ToolActionReconciliationAssertionError(
                "Reconciliation assertion is invalid"
            ) from exc
        tool_execution_value = payload.get("tool_execution_id")
        tool_execution_id = tool_execution_value if isinstance(tool_execution_value, str) else None
        issued_at = _timestamp(payload, "issued_at", ToolActionReconciliationAssertionError)
        expires_at = _timestamp(payload, "expires_at", ToolActionReconciliationAssertionError)
        grant = ToolActionReconciliationGrant(
            reconciliation_id=reconciliation_id,
            actor_id=actor_id,
            action_digest=asserted_digest,
            outcome=outcome,
            tool_execution_id=tool_execution_id,
            issued_at=issued_at,
            expires_at=expires_at,
            authority_key_id=cast(str, payload["key_id"]),
        )
        if (
            payload.get("schema_version") != "2"
            or payload.get("subject_type") != "tool_action_reconciliation"
            or _SAFE_ID.fullmatch(reconciliation_id) is None
            or _DIGEST.fullmatch(asserted_digest) is None
            or asserted_digest != action_digest
            or not _valid_outcome(outcome, tool_execution_value)
            or expires_at <= issued_at
            or (expires_at - issued_at).total_seconds() > max_lifetime_seconds
        ):
            raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
        if issued_at > checked_now or checked_now >= expires_at:
            stored = existing(reconciliation_id)
            if stored is None or not _same_reconciliation_grant(stored, grant):
                raise ToolActionReconciliationAssertionError("Reconciliation assertion is invalid")
        return grant

    def _verify(
        self,
        assertion: str,
        *,
        prefix: str,
        fields: set[str],
        authority: OperatorAuthorityKind,
        now: datetime,
        error_type: type[RuntimeError],
    ) -> dict[str, object]:
        payload, payload_segment, signature = _decode_assertion(
            assertion,
            prefix=prefix,
            fields=fields,
            error_type=error_type,
        )
        key_id = _required_string(payload, "key_id", error_type)
        actor_id = _required_string(payload, "actor_id", error_type)
        issued_at = _timestamp(payload, "issued_at", error_type)
        key = self._trust_store.keys.get(key_id)
        if (
            payload.get("authority_kind") != authority
            or key is None
            or key.actor_id != actor_id
            or authority not in key.authorities
            or not key.active_at(now)
            or not key.active_at(issued_at)
        ):
            raise error_type(_invalid_message(error_type))
        public_key = _decode_base64(key.public_key, 32, error_type)
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                signature,
                f"{prefix}.{payload_segment}".encode("ascii"),
            )
        except (InvalidSignature, ValueError) as exc:
            raise error_type(_invalid_message(error_type)) from exc
        return payload


class Ed25519ApprovalAdapter(HmacApprovalAdapter):
    """Use asymmetric decision verification with the existing SQLite ledger."""

    def __init__(
        self,
        path: Path,
        verifier: Ed25519OperatorAuthorityVerifier,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind asymmetric verification to the SQLite decision ledger."""
        self._verifier = verifier
        self._initialize_ledger(path, max_lifetime_seconds)

    def inspect(self, assertion: str, *, decision_digest: str, now: datetime) -> ApprovalGrant:
        """Verify one Ed25519 decision assertion."""
        return self._verifier.inspect_decision(
            assertion,
            decision_digest=decision_digest,
            now=now,
            max_lifetime_seconds=self._max_lifetime_seconds,
        )


class Ed25519ActionApprovalAdapter(HmacActionApprovalAdapter):
    """Use asymmetric action verification with the existing SQLite ledger."""

    def __init__(
        self,
        path: Path,
        verifier: Ed25519OperatorAuthorityVerifier,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind asymmetric verification to the SQLite action ledger."""
        self._verifier = verifier
        self._initialize_ledger(path, max_lifetime_seconds)

    def inspect(self, assertion: str, *, action_digest: str, now: datetime) -> ActionApprovalGrant:
        """Verify one Ed25519 action assertion."""
        return self._verifier.inspect_action(
            assertion,
            action_digest=action_digest,
            now=now,
            max_lifetime_seconds=self._max_lifetime_seconds,
        )


class Ed25519ToolActionReconciliationAdapter(HmacToolActionReconciliationAdapter):
    """Use asymmetric reconciliation verification with the existing SQLite ledger."""

    def __init__(
        self,
        path: Path,
        verifier: Ed25519OperatorAuthorityVerifier,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind asymmetric verification to the SQLite reconciliation ledger."""
        self._verifier = verifier
        self._initialize_ledger(path, max_lifetime_seconds)

    def inspect(
        self, assertion: str, *, action_digest: str, now: datetime
    ) -> ToolActionReconciliationGrant:
        """Verify one Ed25519 reconciliation assertion."""
        return self._verifier.inspect_reconciliation(
            assertion,
            action_digest=action_digest,
            now=now,
            max_lifetime_seconds=self._max_lifetime_seconds,
            existing=self.get,
        )


class PostgresEd25519ApprovalAdapter(PostgresHmacApprovalAdapter):
    """Asymmetric decision verification with atomic PostgreSQL consumption."""

    def __init__(
        self,
        database: PostgresDatabase,
        verifier: Ed25519OperatorAuthorityVerifier,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind asymmetric verification to the PostgreSQL decision ledger."""
        self._verifier = verifier
        self._initialize_database(database, max_lifetime_seconds)

    def inspect(self, assertion: str, *, decision_digest: str, now: datetime) -> ApprovalGrant:
        """Verify one Ed25519 decision assertion."""
        return self._verifier.inspect_decision(
            assertion,
            decision_digest=decision_digest,
            now=now,
            max_lifetime_seconds=self._max_lifetime_seconds,
        )


class PostgresEd25519ActionApprovalAdapter(PostgresHmacActionApprovalAdapter):
    """Asymmetric action verification with atomic PostgreSQL consumption."""

    def __init__(
        self,
        database: PostgresDatabase,
        verifier: Ed25519OperatorAuthorityVerifier,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind asymmetric verification to the PostgreSQL action ledger."""
        self._verifier = verifier
        self._initialize_database(database, max_lifetime_seconds)

    def inspect(self, assertion: str, *, action_digest: str, now: datetime) -> ActionApprovalGrant:
        """Verify one Ed25519 action assertion."""
        return self._verifier.inspect_action(
            assertion,
            action_digest=action_digest,
            now=now,
            max_lifetime_seconds=self._max_lifetime_seconds,
        )


class PostgresEd25519ToolActionReconciliationAdapter(PostgresHmacToolActionReconciliationAdapter):
    """Asymmetric reconciliation verification with atomic PostgreSQL closure."""

    def __init__(
        self,
        database: PostgresDatabase,
        verifier: Ed25519OperatorAuthorityVerifier,
        *,
        max_lifetime_seconds: int = 3600,
    ) -> None:
        """Bind asymmetric verification to the PostgreSQL reconciliation ledger."""
        self._verifier = verifier
        self._initialize_database(database, max_lifetime_seconds)

    def inspect(
        self, assertion: str, *, action_digest: str, now: datetime
    ) -> ToolActionReconciliationGrant:
        """Verify one Ed25519 reconciliation assertion."""
        return self._verifier.inspect_reconciliation(
            assertion,
            action_digest=action_digest,
            now=now,
            max_lifetime_seconds=self._max_lifetime_seconds,
            existing=self.get,
        )


def _load_trust_store(path: Path) -> _OperatorTrustStoreModel:
    try:
        with path.open("rb") as stream:
            encoded = stream.read(_MAX_TRUST_STORE_BYTES + 1)
        if len(encoded) > _MAX_TRUST_STORE_BYTES:
            raise OperatorAuthorityTrustStoreError("Operator authority trust store is too large")
        content = encoded.decode("utf-8", errors="strict")
        syntax_tree = yaml.compose(content, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw = yaml.safe_load(content)
        trust_store = _OperatorTrustStoreModel.model_validate(raw)
        for key in trust_store.keys.values():
            Ed25519PublicKey.from_public_bytes(_decode_trust_public_key(key.public_key))
        return trust_store
    except OperatorAuthorityTrustStoreError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        yaml.YAMLError,
        ValidationError,
        ValueError,
        RecursionError,
    ):
        # Parser/validation errors can include forbidden private material from the document.
        raise OperatorAuthorityTrustStoreError(
            "Operator authority trust store is invalid"
        ) from None


def _decode_trust_public_key(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise OperatorAuthorityTrustStoreError("Operator authority public key is invalid") from exc
    if len(decoded) != 32 or base64.b64encode(decoded).decode() != value:
        raise OperatorAuthorityTrustStoreError("Operator authority public key is invalid")
    return decoded


def _decode_assertion(
    assertion: str,
    *,
    prefix: str,
    fields: set[str],
    error_type: type[RuntimeError],
) -> tuple[dict[str, object], str, bytes]:
    if not assertion or len(assertion.encode("utf-8")) > _MAX_ASSERTION_BYTES:
        raise error_type(_invalid_message(error_type))
    actual_prefix, separator, remainder = assertion.partition(".")
    payload_segment, signature_separator, signature_segment = remainder.partition(".")
    if (
        actual_prefix != prefix
        or not separator
        or not signature_separator
        or not payload_segment
        or not signature_segment
        or "." in signature_segment
        or _BASE64URL.fullmatch(payload_segment) is None
        or _BASE64URL.fullmatch(signature_segment) is None
    ):
        raise error_type(_invalid_message(error_type))
    raw = _decode_base64url(payload_segment, error_type)
    signature = _decode_base64url(signature_segment, error_type)
    if len(signature) != 64:
        raise error_type(_invalid_message(error_type))
    try:
        parsed = cast(
            object,
            json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_json_object),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKeyError) as exc:
        raise error_type(_invalid_message(error_type)) from exc
    if not isinstance(parsed, dict) or set(parsed) != fields:
        raise error_type(_invalid_message(error_type))
    canonical = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    if raw != canonical:
        raise error_type(_invalid_message(error_type))
    return cast(dict[str, object], parsed), payload_segment, signature


def _decode_base64url(value: str, error_type: type[RuntimeError]) -> bytes:
    try:
        encoded = value.encode("ascii", errors="strict")
        padding = b"=" * (-len(encoded) % 4)
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise error_type(_invalid_message(error_type)) from exc
    if encoded != base64.urlsafe_b64encode(decoded).rstrip(b"="):
        raise error_type(_invalid_message(error_type))
    return decoded


def _decode_base64(value: str, length: int, error_type: type[RuntimeError]) -> bytes:
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise error_type(_invalid_message(error_type)) from exc
    if len(decoded) != length or base64.b64encode(decoded).decode() != value:
        raise error_type(_invalid_message(error_type))
    return decoded


def _required_string(payload: dict[str, object], key: str, error_type: type[RuntimeError]) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise error_type(_invalid_message(error_type))
    return value


def _timestamp(payload: dict[str, object], key: str, error_type: type[RuntimeError]) -> datetime:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(_invalid_message(error_type))
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise error_type(_invalid_message(error_type)) from exc


def _valid_window(
    payload: dict[str, object],
    now: datetime,
    maximum_seconds: int,
    error_type: type[RuntimeError],
) -> tuple[datetime, datetime]:
    issued_at = _timestamp(payload, "issued_at", error_type)
    expires_at = _timestamp(payload, "expires_at", error_type)
    lifetime = int((expires_at - issued_at).total_seconds())
    if issued_at > now or expires_at <= now or lifetime <= 0 or lifetime > maximum_seconds:
        raise error_type(_invalid_message(error_type))
    return issued_at, expires_at


def _valid_outcome(outcome: ToolActionReconciliationOutcome, value: object) -> bool:
    if outcome is ToolActionReconciliationOutcome.EXECUTED:
        return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None
    return outcome is ToolActionReconciliationOutcome.NOT_EXECUTED and value is None


def _same_reconciliation_grant(
    receipt: ToolActionReconciliationReceipt,
    grant: ToolActionReconciliationGrant,
) -> bool:
    return (
        receipt.reconciliation_id == grant.reconciliation_id
        and receipt.actor_id == grant.actor_id
        and receipt.action_digest == grant.action_digest
        and receipt.outcome is grant.outcome
        and receipt.tool_execution_id == grant.tool_execution_id
        and receipt.issued_at == grant.issued_at
        and receipt.expires_at == grant.expires_at
        and receipt.authority_key_id == grant.authority_key_id
    )


def _utc(value: datetime, error_type: type[RuntimeError]) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise error_type(_invalid_message(error_type))
    return value.astimezone(UTC)


def _invalid_message(error_type: type[RuntimeError]) -> str:
    if error_type is ApprovalAssertionError:
        return "Approval assertion is invalid"
    if error_type is ActionApprovalAssertionError:
        return "Action approval assertion is invalid"
    return "Reconciliation assertion is invalid"


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("operator authority trust-store keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("operator authority trust store contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            _reject_duplicate_mapping_keys(item)
