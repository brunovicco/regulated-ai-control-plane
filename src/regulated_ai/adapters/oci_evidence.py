"""Deterministic OCI image-layout packaging for metadata-only release evidence."""

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from regulated_ai.adapters.release_custody import ReleaseCustodyArtifactKind

_ARTIFACT_TYPE: Literal["application/vnd.regulaai.release-evidence.v1"] = (
    "application/vnd.regulaai.release-evidence.v1"
)
_CONFIG_MEDIA_TYPE = "application/vnd.regulaai.release-evidence.config.v1+json"
_INDEX_MEDIA_TYPE: Literal["application/vnd.oci.image.index.v1+json"] = (
    "application/vnd.oci.image.index.v1+json"
)
_MANIFEST_MEDIA_TYPE: Literal["application/vnd.oci.image.manifest.v1+json"] = (
    "application/vnd.oci.image.manifest.v1+json"
)
_JSON_LAYER_MEDIA_TYPE = "application/vnd.regulaai.evidence+json"
_YAML_LAYER_MEDIA_TYPE = "application/vnd.regulaai.evidence+yaml"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_REFERENCE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,255}\.(json|ya?ml)\Z")
_PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
)


class OciEvidenceError(ValueError):
    """OCI evidence input or layout failed closed validation."""

    code = "OCI_EVIDENCE_INVALID"


@dataclass(frozen=True, slots=True)
class OciEvidenceIdentity:
    """Stable identity of one verified OCI evidence package."""

    package_ref: str
    created_at: datetime
    manifest_digest: str
    config_digest: str
    artifact_count: int


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, strict=True)


class _Descriptor(_StrictModel):
    media_type: str = Field(alias="mediaType", min_length=1, max_length=255)
    digest: str = Field(pattern=_DIGEST)
    size: int = Field(ge=1, le=67_108_864)
    artifact_type: str | None = Field(default=None, alias="artifactType", max_length=255)
    annotations: dict[str, str] | None = None

    @model_validator(mode="after")
    def bounded_annotations(self) -> "_Descriptor":
        if self.annotations is not None and (
            len(self.annotations) > 16
            or any(len(key) > 255 or len(value) > 1024 for key, value in self.annotations.items())
        ):
            raise ValueError("OCI descriptor annotations are not bounded")
        return self


class _Index(_StrictModel):
    schema_version: Literal[2] = Field(alias="schemaVersion")
    media_type: Literal["application/vnd.oci.image.index.v1+json"] = Field(alias="mediaType")
    manifests: tuple[_Descriptor, ...] = Field(min_length=1, max_length=1)


class _Manifest(_StrictModel):
    schema_version: Literal[2] = Field(alias="schemaVersion")
    media_type: Literal["application/vnd.oci.image.manifest.v1+json"] = Field(alias="mediaType")
    artifact_type: Literal["application/vnd.regulaai.release-evidence.v1"] = Field(
        alias="artifactType"
    )
    config: _Descriptor
    layers: tuple[_Descriptor, ...] = Field(min_length=1, max_length=512)


class _ConfigArtifact(_StrictModel):
    kind: ReleaseCustodyArtifactKind
    name: str = Field(min_length=1, max_length=261)
    media_type: str = Field(alias="mediaType", min_length=1, max_length=255)
    digest: str = Field(pattern=_DIGEST)
    size: int = Field(ge=1, le=8_388_608)

    @model_validator(mode="after")
    def safe_name_and_media_type(self) -> "_ConfigArtifact":
        if _FILENAME.fullmatch(self.name) is None:
            raise ValueError("OCI evidence artifact name is invalid")
        if self.media_type != _media_type_for_name(self.name):
            raise ValueError("OCI evidence artifact media type does not match its name")
        return self


class _Config(_StrictModel):
    schema_version: Literal["1"]
    package_ref: str
    created_at: datetime
    artifacts: tuple[_ConfigArtifact, ...] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def valid_identity(self) -> "_Config":
        _validate_package_ref(self.package_ref)
        _require_utc(self.created_at, "OCI evidence creation time")
        identities = tuple((item.kind, item.name) for item in self.artifacts)
        if len(identities) != len(set(identities)):
            raise ValueError("OCI evidence config contains duplicate artifact identities")
        return self


def create_oci_evidence_layout(
    output_path: Path,
    *,
    package_ref: str,
    created_at: datetime,
    artifacts: tuple[tuple[ReleaseCustodyArtifactKind, Path], ...],
) -> OciEvidenceIdentity:
    """Create a new deterministic OCI image layout without overwriting a path."""
    _validate_package_ref(package_ref)
    _require_utc(created_at, "OCI evidence creation time")
    if not artifacts or len(artifacts) > 512:
        raise OciEvidenceError("OCI evidence artifact count is invalid")
    if output_path.exists():
        raise OciEvidenceError("OCI evidence output path already exists")
    try:
        parent = output_path.parent.resolve(strict=True)
    except OSError as exc:
        raise OciEvidenceError("OCI evidence output parent is unavailable") from exc
    if not output_path.name or output_path.name in {".", ".."}:
        raise OciEvidenceError("OCI evidence output name is invalid")

    loaded = tuple(_load_input(kind, path) for kind, path in artifacts)
    if sum(len(item[2]) for item in loaded) > 67_108_864:
        raise OciEvidenceError("OCI evidence artifacts exceed the total size limit")
    identities = tuple((item[0], item[1].name) for item in loaded)
    if len(identities) != len(set(identities)):
        raise OciEvidenceError("OCI evidence artifacts contain duplicate identities")

    config = _Config(
        schema_version="1",
        package_ref=package_ref,
        created_at=created_at,
        artifacts=tuple(
            _ConfigArtifact(
                kind=kind,
                name=path.name,
                media_type=_media_type_for_name(path.name),
                digest=_digest(content),
                size=len(content),
            )
            for kind, path, content in loaded
        ),
    )
    config_bytes = _encode(config.model_dump(mode="json", by_alias=True))
    config_descriptor = _Descriptor(
        media_type=_CONFIG_MEDIA_TYPE,
        digest=_digest(config_bytes),
        size=len(config_bytes),
    )
    layers = tuple(
        _Descriptor(
            media_type=_media_type_for_name(path.name),
            digest=_digest(content),
            size=len(content),
            annotations={
                "org.opencontainers.image.title": path.name,
                "io.regulaai.evidence.kind": kind.value,
            },
        )
        for kind, path, content in loaded
    )
    manifest = _Manifest(
        schema_version=2,
        media_type=_MANIFEST_MEDIA_TYPE,
        artifact_type=_ARTIFACT_TYPE,
        config=config_descriptor,
        layers=layers,
    )
    manifest_bytes = _encode(manifest.model_dump(mode="json", by_alias=True, exclude_none=True))
    manifest_descriptor = _Descriptor(
        media_type=_MANIFEST_MEDIA_TYPE,
        artifact_type=_ARTIFACT_TYPE,
        digest=_digest(manifest_bytes),
        size=len(manifest_bytes),
        annotations={
            "org.opencontainers.image.ref.name": package_ref,
            "org.opencontainers.image.created": created_at.isoformat(),
        },
    )
    index = _Index(
        schema_version=2,
        media_type=_INDEX_MEDIA_TYPE,
        manifests=(manifest_descriptor,),
    )

    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.", dir=parent))
    try:
        blob_root = staging / "blobs" / "sha256"
        blob_root.mkdir(parents=True)
        for _, _, content in loaded:
            _write_blob(blob_root, content)
        _write_blob(blob_root, config_bytes)
        _write_blob(blob_root, manifest_bytes)
        (staging / "oci-layout").write_bytes(_encode({"imageLayoutVersion": "1.0.0"}))
        (staging / "index.json").write_bytes(
            _encode(index.model_dump(mode="json", by_alias=True, exclude_none=True))
        )
        os.rename(staging, output_path)
    except (OSError, ValueError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise OciEvidenceError("OCI evidence layout could not be created") from exc
    return verify_oci_evidence_layout(output_path, expected_package_ref=package_ref)


def verify_oci_evidence_layout(
    layout_path: Path, *, expected_package_ref: str | None = None
) -> OciEvidenceIdentity:
    """Verify one OCI evidence layout and all tracked content-addressed blobs."""
    if expected_package_ref is not None:
        _validate_package_ref(expected_package_ref)
    if layout_path.is_symlink() or not layout_path.is_dir():
        raise OciEvidenceError("OCI evidence layout path is not allowed")
    if {item.name for item in layout_path.iterdir()} != {"oci-layout", "index.json", "blobs"}:
        raise OciEvidenceError("OCI evidence layout contains untracked root entries")
    layout = _read_json(layout_path / "oci-layout", maximum_size=4096)
    if layout != {"imageLayoutVersion": "1.0.0"}:
        raise OciEvidenceError("OCI image-layout version is invalid")
    try:
        index_bytes = _read_json_bytes(layout_path / "index.json", maximum_size=1_048_576)
        _decode_json(index_bytes, "index.json")
        index = _Index.model_validate_json(index_bytes)
    except ValidationError as exc:
        raise OciEvidenceError("OCI evidence index failed schema validation") from exc
    manifest_descriptor = index.manifests[0]
    if (
        manifest_descriptor.media_type != _MANIFEST_MEDIA_TYPE
        or manifest_descriptor.artifact_type != _ARTIFACT_TYPE
    ):
        raise OciEvidenceError("OCI evidence manifest descriptor is invalid")
    manifest_bytes = _read_blob(layout_path, manifest_descriptor)
    try:
        _decode_json(manifest_bytes, "manifest")
        manifest = _Manifest.model_validate_json(manifest_bytes)
    except ValidationError as exc:
        raise OciEvidenceError("OCI evidence manifest failed schema validation") from exc
    if manifest.config.media_type != _CONFIG_MEDIA_TYPE:
        raise OciEvidenceError("OCI evidence config media type is invalid")
    config_bytes = _read_blob(layout_path, manifest.config)
    try:
        _decode_json(config_bytes, "config")
        config = _Config.model_validate_json(config_bytes)
    except ValidationError as exc:
        raise OciEvidenceError("OCI evidence config failed schema validation") from exc
    if expected_package_ref is not None and config.package_ref != expected_package_ref:
        raise OciEvidenceError("OCI evidence package reference does not match")
    annotations = manifest_descriptor.annotations or {}
    if annotations != {
        "org.opencontainers.image.ref.name": config.package_ref,
        "org.opencontainers.image.created": config.created_at.isoformat(),
    } or len(manifest.layers) != len(config.artifacts):
        raise OciEvidenceError("OCI evidence index or layer binding does not match config")

    expected_blobs = {manifest_descriptor.digest, manifest.config.digest}
    for artifact, descriptor in zip(config.artifacts, manifest.layers, strict=True):
        if (
            descriptor.digest != artifact.digest
            or descriptor.size != artifact.size
            or descriptor.media_type != artifact.media_type
            or descriptor.artifact_type is not None
            or descriptor.annotations
            != {
                "org.opencontainers.image.title": artifact.name,
                "io.regulaai.evidence.kind": artifact.kind.value,
            }
        ):
            raise OciEvidenceError("OCI evidence layer does not match config")
        content = _read_blob(layout_path, descriptor)
        if any(marker in content for marker in _PRIVATE_KEY_MARKERS):
            raise OciEvidenceError("Private key material is not allowed in OCI evidence")
        expected_blobs.add(descriptor.digest)
    _verify_blob_inventory(layout_path, expected_blobs)
    return OciEvidenceIdentity(
        package_ref=config.package_ref,
        created_at=config.created_at,
        manifest_digest=manifest_descriptor.digest,
        config_digest=manifest.config.digest,
        artifact_count=len(config.artifacts),
    )


def _load_input(
    kind: ReleaseCustodyArtifactKind, path: Path
) -> tuple[ReleaseCustodyArtifactKind, Path, bytes]:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise OciEvidenceError("OCI evidence input artifact is unavailable") from exc
    if (
        path.is_symlink()
        or resolved != path.absolute()
        or not resolved.is_file()
        or _FILENAME.fullmatch(path.name) is None
    ):
        raise OciEvidenceError("OCI evidence artifact path or name is not allowed")
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise OciEvidenceError("OCI evidence input artifact is unavailable") from exc
    if not content or len(content) > 8_388_608:
        raise OciEvidenceError("OCI evidence artifact has an invalid size")
    if any(marker in content for marker in _PRIVATE_KEY_MARKERS):
        raise OciEvidenceError("Private key material is not allowed in OCI evidence")
    return kind, path, content


def _read_blob(layout_path: Path, descriptor: _Descriptor) -> bytes:
    path = layout_path / "blobs" / "sha256" / descriptor.digest.removeprefix("sha256:")
    if path.is_symlink() or not path.is_file():
        raise OciEvidenceError("OCI evidence blob path is not allowed")
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise OciEvidenceError("OCI evidence blob is unavailable") from exc
    if len(value) != descriptor.size or _digest(value) != descriptor.digest:
        raise OciEvidenceError("OCI evidence blob digest or size does not match")
    return value


def _verify_blob_inventory(layout_path: Path, expected_digests: set[str]) -> None:
    blobs = layout_path / "blobs"
    algorithm = blobs / "sha256"
    if blobs.is_symlink() or algorithm.is_symlink() or not algorithm.is_dir():
        raise OciEvidenceError("OCI evidence blob directory is invalid")
    if {item.name for item in blobs.iterdir()} != {"sha256"}:
        raise OciEvidenceError("OCI evidence layout contains unsupported blob algorithms")
    entries = tuple(algorithm.iterdir())
    if any(item.is_symlink() or not item.is_file() for item in entries):
        raise OciEvidenceError("OCI evidence blob inventory contains an invalid entry")
    actual = {f"sha256:{item.name}" for item in entries}
    if actual != expected_digests:
        raise OciEvidenceError("OCI evidence blob inventory is incomplete or untracked")


def _write_blob(blob_root: Path, value: bytes) -> None:
    destination = blob_root / _digest(value).removeprefix("sha256:")
    if destination.exists():
        if destination.read_bytes() != value:
            raise OciEvidenceError("OCI evidence blob digest collision detected")
        return
    destination.write_bytes(value)


def _read_json(path: Path, *, maximum_size: int) -> dict[str, JsonValue]:
    return _decode_json(_read_json_bytes(path, maximum_size=maximum_size), path.name)


def _read_json_bytes(path: Path, *, maximum_size: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OciEvidenceError("OCI evidence JSON path is not allowed")
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise OciEvidenceError("OCI evidence JSON is unavailable") from exc
    if not value or len(value) > maximum_size:
        raise OciEvidenceError("OCI evidence JSON has an invalid size")
    return value


def _decode_json(value: bytes, label: str) -> dict[str, JsonValue]:
    try:
        parsed = json.loads(value.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OciEvidenceError(f"OCI evidence {label} is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise OciEvidenceError(f"OCI evidence {label} must be a JSON mapping")
    return parsed


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise OciEvidenceError("OCI evidence JSON contains a duplicate key")
        result[key] = value
    return result


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _media_type_for_name(name: str) -> str:
    return _JSON_LAYER_MEDIA_TYPE if name.endswith(".json") else _YAML_LAYER_MEDIA_TYPE


def _validate_package_ref(value: str) -> None:
    if not value or len(value) > 128 or _REFERENCE.fullmatch(value) is None:
        raise OciEvidenceError("OCI evidence package reference is invalid")


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise OciEvidenceError(f"{label} must be timezone-aware UTC")
