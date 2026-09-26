"""Fail-closed verification for signed control packs."""

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


class SignedPackError(ValueError):
    """A signed control pack failed strict validation or verification."""

    code = "SIGNED_CONTROL_PACK_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _PackFileModel(_StrictModel):
    kind: Literal["policy", "provider_capability", "tool_catalog"]
    path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def normalized_relative_yaml_path(cls, value: str) -> str:
        """Require an unambiguous relative POSIX YAML path."""
        candidate = PurePosixPath(value)
        if (
            candidate.is_absolute()
            or candidate.suffix not in {".yaml", ".yml"}
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or candidate.as_posix() != value
        ):
            raise ValueError("pack file path must be a normalized relative YAML path")
        return value


class _SigningModel(_StrictModel):
    algorithm: Literal["ed25519"]
    key_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$",
    )
    signature: str = Field(min_length=1, max_length=256)


class _ManifestModel(_StrictModel):
    schema_version: Literal["1"]
    pack_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    pack_version: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$",
    )
    files: tuple[_PackFileModel, ...] = Field(min_length=3, max_length=256)
    signing: _SigningModel

    @model_validator(mode="after")
    def valid_composition(self) -> "_ManifestModel":
        """Require unique files and both maintained-intelligence record kinds."""
        paths = tuple(item.path for item in self.files)
        kinds = {item.kind for item in self.files}
        if len(paths) != len(set(paths)):
            raise ValueError("signed pack contains duplicate paths")
        if kinds != {"policy", "provider_capability", "tool_catalog"}:
            raise ValueError(
                "signed pack must contain policy, provider capability and tool catalog files"
            )
        if sum(item.kind == "tool_catalog" for item in self.files) != 1:
            raise ValueError("signed pack must contain exactly one tool catalog")
        return self


class _TrustedKeyModel(_StrictModel):
    algorithm: Literal["ed25519"]
    public_key: str = Field(min_length=1, max_length=128)


class _TrustStoreModel(_StrictModel):
    schema_version: Literal["1"]
    keys: dict[str, _TrustedKeyModel] = Field(min_length=1, max_length=64)

    @field_validator("keys")
    @classmethod
    def normalized_key_ids(cls, value: dict[str, _TrustedKeyModel]) -> dict[str, _TrustedKeyModel]:
        """Reject key identifiers that cannot be safely logged or selected."""
        import re

        pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}\Z")
        if any(pattern.fullmatch(key_id) is None for key_id in value):
            raise ValueError("trusted signing key identifier is invalid")
        return value


@dataclass(frozen=True, slots=True)
class ControlPackIdentity:
    """Non-secret identity of one verified control-pack release."""

    pack_id: str
    pack_version: str
    signing_key_id: str
    payload_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedControlFile:
    """Exact authenticated bytes passed to a configuration parser."""

    path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class VerifiedControlPack:
    """Authenticated release identity and exact configuration bytes."""

    identity: ControlPackIdentity
    policy_files: tuple[VerifiedControlFile, ...]
    capability_files: tuple[VerifiedControlFile, ...]
    tool_files: tuple[VerifiedControlFile, ...]


def verify_control_pack(manifest_path: Path, trust_store_path: Path) -> VerifiedControlPack:
    """Validate hashes and signature before returning any configuration path."""
    manifest = _parse_manifest(manifest_path)
    trust_store = _parse_trust_store(trust_store_path)
    trusted_key = trust_store.keys.get(manifest.signing.key_id)
    if trusted_key is None or trusted_key.algorithm != manifest.signing.algorithm:
        raise SignedPackError("Control pack signing key is not trusted")

    payload = _canonical_payload(manifest)
    public_key_bytes = _decode_base64(trusted_key.public_key, expected_length=32)
    signature_bytes = _decode_base64(manifest.signing.signature, expected_length=64)
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature_bytes, payload)
    except (InvalidSignature, ValueError) as exc:
        raise SignedPackError("Control pack signature is invalid") from exc

    root = manifest_path.resolve().parent
    verified_files: dict[str, VerifiedControlFile] = {}
    total_size = 0
    for item in manifest.files:
        candidate = root.joinpath(*PurePosixPath(item.path).parts)
        try:
            path = candidate.resolve(strict=True)
        except OSError as exc:
            raise SignedPackError("Control pack file is unavailable") from exc
        if not path.is_relative_to(root) or path != candidate.absolute() or not path.is_file():
            raise SignedPackError("Control pack file path is not allowed")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise SignedPackError("Control pack file is unavailable") from exc
        if len(content) > 1_048_576:
            raise SignedPackError("Control pack file exceeds the size limit")
        total_size += len(content)
        if total_size > 8_388_608:
            raise SignedPackError("Control pack exceeds the total size limit")
        actual_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if actual_digest != item.sha256:
            raise SignedPackError("Control pack file digest does not match")
        verified_files[item.path] = VerifiedControlFile(path=item.path, content=content)

    ordered_files = sorted(manifest.files, key=lambda item: (item.kind, item.path))
    return VerifiedControlPack(
        identity=ControlPackIdentity(
            pack_id=manifest.pack_id,
            pack_version=manifest.pack_version,
            signing_key_id=manifest.signing.key_id,
            payload_digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        ),
        policy_files=tuple(
            verified_files[item.path] for item in ordered_files if item.kind == "policy"
        ),
        capability_files=tuple(
            verified_files[item.path]
            for item in ordered_files
            if item.kind == "provider_capability"
        ),
        tool_files=tuple(
            verified_files[item.path] for item in ordered_files if item.kind == "tool_catalog"
        ),
    )


def _parse_manifest(path: Path) -> _ManifestModel:
    try:
        return _ManifestModel.model_validate(_read_strict_yaml(path))
    except SignedPackError:
        raise
    except (ValidationError, ValueError) as exc:
        raise SignedPackError("Control pack manifest failed schema validation") from exc


def _parse_trust_store(path: Path) -> _TrustStoreModel:
    try:
        return _TrustStoreModel.model_validate(_read_strict_yaml(path))
    except SignedPackError:
        raise
    except (ValidationError, ValueError) as exc:
        raise SignedPackError("Control pack trust store failed schema validation") from exc


def _read_strict_yaml(path: Path) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
        if len(encoded) > 262_144:
            raise SignedPackError("Signed control metadata exceeds the size limit")
        content = encoded.decode("utf-8")
        syntax_tree = yaml.compose(content, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw = yaml.safe_load(content)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SignedPackError("Signed control metadata is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise SignedPackError("Signed control metadata must be a mapping")
    return raw


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("signed control metadata keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("signed control metadata contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def _canonical_payload(manifest: _ManifestModel) -> bytes:
    payload = {
        "files": [
            {"kind": item.kind, "path": item.path, "sha256": item.sha256}
            for item in sorted(manifest.files, key=lambda item: (item.kind, item.path))
        ],
        "pack_id": manifest.pack_id,
        "pack_version": manifest.pack_version,
        "schema_version": manifest.schema_version,
        "signing": {
            "algorithm": manifest.signing.algorithm,
            "key_id": manifest.signing.key_id,
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _decode_base64(value: str, *, expected_length: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignedPackError("Signed control metadata contains invalid base64") from exc
    if len(decoded) != expected_length:
        raise SignedPackError("Signed control metadata has an invalid cryptographic length")
    return decoded
