"""Content-bound lineage checkpoints for public verification-key trust stores."""

import base64
import binascii
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

_DIGEST = r"^sha256:[0-9a-f]{64}$"
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
_PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
)


class TrustStoreLineageError(ValueError):
    """A trust-store checkpoint or its lineage failed closed validation."""

    code = "TRUST_STORE_LINEAGE_INVALID"


class TrustStoreKind(StrEnum):
    """Public-key authority boundaries that can be independently distributed."""

    CONTROL_PACK = "CONTROL_PACK"
    RELEASE_REVIEW = "RELEASE_REVIEW"
    RELEASE_PROMOTION = "RELEASE_PROMOTION"


@dataclass(frozen=True, slots=True)
class TrustStoreCheckpointIdentity:
    """Verified identity of one exact public trust-store checkpoint."""

    store_id: str
    store_kind: TrustStoreKind
    sequence: int
    issued_at: datetime
    trust_store_digest: str
    previous_checkpoint_digest: str | None
    checkpoint_digest: str
    signing_key_id: str
    signature_digest: str


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CheckpointModel(_StrictModel):
    schema_version: Literal["1"]
    store_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    store_kind: TrustStoreKind
    sequence: int = Field(ge=1, le=2_147_483_647)
    issued_at: datetime
    trust_store_digest: str = Field(pattern=_DIGEST)
    previous_checkpoint_digest: str | None = Field(default=None, pattern=_DIGEST)
    signing_algorithm: Literal["ed25519"]
    signing_key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    checkpoint_digest: str = Field(pattern=_DIGEST)
    signature: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def valid_time_and_genesis(self) -> "_CheckpointModel":
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() != UTC.utcoffset(
            self.issued_at
        ):
            raise ValueError("trust-store checkpoint time must be timezone-aware UTC")
        if (self.sequence == 1) != (self.previous_checkpoint_digest is None):
            raise ValueError("trust-store checkpoint genesis linkage is invalid")
        return self


def create_trust_store_checkpoint(
    trust_store_path: Path,
    output_path: Path,
    *,
    store_id: str,
    store_kind: TrustStoreKind,
    sequence: int,
    issued_at: datetime,
    signing_key_id: str,
    private_key_path: Path,
    previous_checkpoint_path: Path | None = None,
) -> TrustStoreCheckpointIdentity:
    """Create one fail-if-present checkpoint for exact validated trust-store bytes."""
    trust_store = _read_trust_store(trust_store_path)
    if re.fullmatch(_IDENTIFIER, signing_key_id) is None or len(signing_key_id) > 128:
        raise TrustStoreLineageError("Checkpoint signing key id is invalid")
    private_key = _load_private_key(private_key_path)
    previous = (
        _load_checkpoint(previous_checkpoint_path, private_key.public_key(), signing_key_id)
        if previous_checkpoint_path is not None
        else None
    )
    _validate_requested_lineage(
        store_id=store_id,
        store_kind=store_kind,
        sequence=sequence,
        issued_at=issued_at,
        trust_store_digest=_digest_bytes(trust_store),
        previous=previous,
    )
    core = {
        "issued_at": issued_at.isoformat(),
        "previous_checkpoint_digest": (
            previous.checkpoint_digest if previous is not None else None
        ),
        "schema_version": "1",
        "sequence": sequence,
        "signing_algorithm": "ed25519",
        "signing_key_id": signing_key_id,
        "store_id": store_id,
        "store_kind": store_kind.value,
        "trust_store_digest": _digest_bytes(trust_store),
    }
    canonical = _canonical_json(core)
    signature = private_key.sign(canonical)
    document = {
        **core,
        "checkpoint_digest": _digest_bytes(canonical),
        "signature": base64.b64encode(signature).decode(),
    }
    encoded = (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()
    _write_new_file(output_path, encoded)
    return _load_checkpoint(output_path, private_key.public_key(), signing_key_id)


def verify_trust_store_checkpoint(
    trust_store_path: Path,
    checkpoint_path: Path,
    *,
    public_key_path: Path,
    signing_key_id: str,
    previous_checkpoint_path: Path | None = None,
    minimum_sequence: int | None = None,
    expected_checkpoint_digest: str | None = None,
) -> TrustStoreCheckpointIdentity:
    """Verify exact bytes and a caller-pinned rollback floor or predecessor."""
    if (
        previous_checkpoint_path is None
        and minimum_sequence is None
        and expected_checkpoint_digest is None
    ):
        raise TrustStoreLineageError("Checkpoint verification requires a trusted rollback anchor")
    trust_store = _read_trust_store(trust_store_path)
    public_key = _load_public_key(public_key_path)
    checkpoint = _load_checkpoint(checkpoint_path, public_key, signing_key_id)
    if checkpoint.trust_store_digest != _digest_bytes(trust_store):
        raise TrustStoreLineageError("Checkpoint does not bind the supplied trust store")
    if minimum_sequence is not None and (
        minimum_sequence < 1 or checkpoint.sequence < minimum_sequence
    ):
        raise TrustStoreLineageError("Checkpoint is below the trusted minimum sequence")
    if (
        expected_checkpoint_digest is not None
        and checkpoint.checkpoint_digest != expected_checkpoint_digest
    ):
        raise TrustStoreLineageError("Checkpoint does not match the trusted digest")
    if previous_checkpoint_path is not None:
        previous = _load_checkpoint(previous_checkpoint_path, public_key, signing_key_id)
        _validate_checkpoint_successor(checkpoint, previous)
    return checkpoint


def _validate_requested_lineage(
    *,
    store_id: str,
    store_kind: TrustStoreKind,
    sequence: int,
    issued_at: datetime,
    trust_store_digest: str,
    previous: TrustStoreCheckpointIdentity | None,
) -> None:
    if re.fullmatch(_IDENTIFIER, store_id) is None or len(store_id) > 128:
        raise TrustStoreLineageError("Trust-store id is invalid")
    if issued_at.tzinfo is None or issued_at.utcoffset() != UTC.utcoffset(issued_at):
        raise TrustStoreLineageError("Checkpoint issue time must be timezone-aware UTC")
    if previous is None:
        if sequence != 1:
            raise TrustStoreLineageError("Genesis checkpoint sequence must be one")
        return
    if (
        previous.store_id != store_id
        or previous.store_kind is not store_kind
        or sequence != previous.sequence + 1
        or issued_at <= previous.issued_at
    ):
        raise TrustStoreLineageError("Checkpoint does not extend the supplied lineage")
    if trust_store_digest == previous.trust_store_digest:
        raise TrustStoreLineageError("Checkpoint cannot advance unchanged trust-store bytes")


def _validate_checkpoint_successor(
    checkpoint: TrustStoreCheckpointIdentity,
    previous: TrustStoreCheckpointIdentity,
) -> None:
    if (
        checkpoint.store_id != previous.store_id
        or checkpoint.store_kind is not previous.store_kind
        or checkpoint.sequence != previous.sequence + 1
        or checkpoint.previous_checkpoint_digest != previous.checkpoint_digest
        or checkpoint.issued_at <= previous.issued_at
    ):
        raise TrustStoreLineageError("Checkpoint predecessor linkage is invalid")


def _load_checkpoint(
    path: Path,
    public_key: Ed25519PublicKey,
    expected_signing_key_id: str,
) -> TrustStoreCheckpointIdentity:
    raw = _read_json(path, maximum_bytes=65_536)
    try:
        model = _CheckpointModel.model_validate(raw)
    except ValidationError as exc:
        raise TrustStoreLineageError("Trust-store checkpoint failed schema validation") from exc
    canonical = dict(raw)
    supplied_signature = canonical.pop("signature", None)
    supplied_digest = canonical.pop("checkpoint_digest", None)
    encoded = _canonical_json(canonical)
    if supplied_digest != _digest_bytes(encoded):
        raise TrustStoreLineageError("Trust-store checkpoint digest does not match")
    if model.signing_key_id != expected_signing_key_id:
        raise TrustStoreLineageError("Checkpoint signing key id does not match")
    try:
        signature = base64.b64decode(str(supplied_signature), validate=True)
        if len(signature) != 64:
            raise ValueError("invalid signature length")
        public_key.verify(signature, encoded)
    except (binascii.Error, InvalidSignature, ValueError) as exc:
        raise TrustStoreLineageError("Trust-store checkpoint signature is invalid") from exc
    return TrustStoreCheckpointIdentity(
        store_id=model.store_id,
        store_kind=model.store_kind,
        sequence=model.sequence,
        issued_at=model.issued_at,
        trust_store_digest=model.trust_store_digest,
        previous_checkpoint_digest=model.previous_checkpoint_digest,
        checkpoint_digest=model.checkpoint_digest,
        signing_key_id=model.signing_key_id,
        signature_digest=_digest_bytes(signature),
    )


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        key = load_pem_private_key(_read_key_file(path), password=None)
    except (OSError, TypeError, ValueError) as exc:
        raise TrustStoreLineageError("Checkpoint private key could not be loaded") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise TrustStoreLineageError("Checkpoint signing key must be Ed25519")
    return key


def _load_public_key(path: Path) -> Ed25519PublicKey:
    try:
        key = load_pem_public_key(_read_key_file(path))
    except (OSError, TypeError, ValueError) as exc:
        raise TrustStoreLineageError("Checkpoint public key could not be loaded") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise TrustStoreLineageError("Checkpoint verification key must be Ed25519")
    return key


def _read_key_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise TrustStoreLineageError("Checkpoint key path is not an allowed file")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise TrustStoreLineageError("Checkpoint key is unavailable") from exc
    if not content or len(content) > 16_384:
        raise TrustStoreLineageError("Checkpoint key has an invalid size")
    return content


def _read_trust_store(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise TrustStoreLineageError("Trust-store path is not an allowed file")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise TrustStoreLineageError("Trust store is unavailable") from exc
    if not content or len(content) > 1_048_576:
        raise TrustStoreLineageError("Trust store has an invalid size")
    if any(marker in content for marker in _PRIVATE_KEY_MARKERS):
        raise TrustStoreLineageError("Private key material is not allowed in a trust store")
    try:
        text = content.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw: Any = yaml.safe_load(text)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise TrustStoreLineageError("Trust store is not valid YAML") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema_version", "keys"}
        or raw.get("schema_version") != "2"
        or not isinstance(raw.get("keys"), dict)
        or not raw["keys"]
        or len(raw["keys"]) > 64
    ):
        raise TrustStoreLineageError("Trust store is not a supported public-key document")
    return content


def _read_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TrustStoreLineageError("Checkpoint path is not an allowed file")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise TrustStoreLineageError("Checkpoint is unavailable") from exc
    if not content or len(content) > maximum_bytes:
        raise TrustStoreLineageError("Checkpoint has an invalid size")
    try:
        raw = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrustStoreLineageError("Checkpoint is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise TrustStoreLineageError("Checkpoint must be a JSON object")
    return raw


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrustStoreLineageError("Checkpoint contains a duplicate key")
        result[key] = value
    return result


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("trust-store keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("trust store contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def _write_new_file(path: Path, content: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except OSError as exc:
        raise TrustStoreLineageError("Checkpoint output already exists or is unavailable") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise TrustStoreLineageError("Checkpoint output could not be written") from exc


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
