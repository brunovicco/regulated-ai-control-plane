"""Content-addressed offline custody for metadata-only release artifacts."""

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from regulated_ai.adapters.promotion_attestations import (
    PromotionAttestationBoundaryError,
    load_release_evidence_bundle_bytes,
)

_DIGEST = r"^sha256:[0-9a-f]{64}$"
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,255}\.(json|ya?ml)\Z")
_STORED_NAME = re.compile(r"[0-9a-f]{64}\.(json|ya?ml)\Z")
_PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
)


class ReleaseCustodyError(ValueError):
    """Release custody input or archive failed closed validation."""

    code = "RELEASE_CUSTODY_INVALID"


class ReleaseCustodyArtifactKind(StrEnum):
    """Allowlisted metadata or public-verification artifact type."""

    RELEASE_EVIDENCE_BUNDLE = "RELEASE_EVIDENCE_BUNDLE"
    PROMOTION_AUTHORIZATION_REPORT = "PROMOTION_AUTHORIZATION_REPORT"
    CONTROL_PACK_MANIFEST = "CONTROL_PACK_MANIFEST"
    PUBLIC_TRUST_STORE = "PUBLIC_TRUST_STORE"
    RELEASE_REVIEW_ATTESTATION = "RELEASE_REVIEW_ATTESTATION"
    PROMOTION_ATTESTATION = "PROMOTION_ATTESTATION"
    PROMOTION_POLICY = "PROMOTION_POLICY"
    SCENARIO_SUITE = "SCENARIO_SUITE"


@dataclass(frozen=True, slots=True)
class ReleaseCustodyIdentity:
    """Stable identity of one verified release-custody archive."""

    archive_id: str
    created_at: datetime
    evidence_bundle_digest: str
    authorization_digest: str
    manifest_digest: str
    artifact_count: int


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ArtifactModel(_StrictModel):
    kind: ReleaseCustodyArtifactKind
    original_name: str = Field(min_length=1, max_length=261)
    stored_name: str = Field(min_length=1, max_length=69)
    sha256: str = Field(pattern=_DIGEST)
    size_bytes: int = Field(ge=1, le=8_388_608)

    @model_validator(mode="after")
    def safe_names(self) -> "_ArtifactModel":
        if _FILENAME.fullmatch(self.original_name) is None:
            raise ValueError("custody artifact original name is invalid")
        if _STORED_NAME.fullmatch(self.stored_name) is None:
            raise ValueError("custody artifact stored name is invalid")
        if self.stored_name.split(".", 1)[0] != self.sha256.removeprefix("sha256:"):
            raise ValueError("custody artifact stored name does not match its digest")
        return self


class _CustodyManifestModel(_StrictModel):
    schema_version: Literal["1"]
    archive_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    created_at: datetime
    evidence_bundle_digest: str = Field(pattern=_DIGEST)
    authorization_digest: str = Field(pattern=_DIGEST)
    artifacts: tuple[_ArtifactModel, ...] = Field(min_length=3, max_length=512)
    manifest_digest: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def valid_manifest(self) -> "_CustodyManifestModel":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != UTC.utcoffset(
            self.created_at
        ):
            raise ValueError("custody creation time must be timezone-aware UTC")
        identities = tuple((item.kind, item.original_name) for item in self.artifacts)
        if len(identities) != len(set(identities)):
            raise ValueError("custody manifest contains duplicate artifact identities")
        kinds = tuple(item.kind for item in self.artifacts)
        if kinds.count(ReleaseCustodyArtifactKind.RELEASE_EVIDENCE_BUNDLE) != 1:
            raise ValueError("custody archive requires one release evidence bundle")
        if kinds.count(ReleaseCustodyArtifactKind.PROMOTION_AUTHORIZATION_REPORT) != 1:
            raise ValueError("custody archive requires one promotion authorization report")
        if ReleaseCustodyArtifactKind.PUBLIC_TRUST_STORE not in kinds:
            raise ValueError("custody archive requires at least one public trust store")
        return self


class _PromotionAuthorizationModel(_StrictModel):
    schema_version: Literal["1"]
    status: Literal["PROMOTION_AUTHORIZED"]
    bundle_digest: str = Field(pattern=_DIGEST)
    base_pack: dict[str, JsonValue]
    candidate_pack: dict[str, JsonValue]
    policy: dict[str, JsonValue]
    evaluated_at: datetime
    attestations: tuple[dict[str, JsonValue], ...] = Field(max_length=512)
    findings: tuple[dict[str, JsonValue], ...] = Field(max_length=512)
    authorization_scope: str = Field(min_length=1, max_length=2048)
    authorization_digest: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def utc_and_complete(self) -> "_PromotionAuthorizationModel":
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() != UTC.utcoffset(
            self.evaluated_at
        ):
            raise ValueError("promotion authorization evaluation time must be UTC")
        if self.findings:
            raise ValueError("promotion authorization report contains findings")
        return self


def create_release_custody(
    output_path: Path,
    *,
    archive_id: str,
    created_at: datetime,
    artifacts: tuple[tuple[ReleaseCustodyArtifactKind, Path], ...],
) -> ReleaseCustodyIdentity:
    """Create one new archive atomically without overwriting an existing path."""
    if re.fullmatch(_IDENTIFIER, archive_id) is None or len(archive_id) > 128:
        raise ReleaseCustodyError("Custody archive id is invalid")
    if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
        raise ReleaseCustodyError("Custody creation time must be timezone-aware UTC")
    if output_path.exists():
        raise ReleaseCustodyError("Custody output path already exists")
    try:
        parent = output_path.parent.resolve(strict=True)
    except OSError as exc:
        raise ReleaseCustodyError("Custody output parent is unavailable") from exc
    if not output_path.name or output_path.name in {".", ".."}:
        raise ReleaseCustodyError("Custody output name is invalid")

    loaded = tuple(_load_artifact(kind, path) for kind, path in artifacts)
    if sum(len(item[2]) for item in loaded) > 67_108_864:
        raise ReleaseCustodyError("Custody input artifacts exceed the total size limit")
    evidence_digest, authorization_digest = _validate_core_artifacts(loaded)
    artifact_models = tuple(
        _ArtifactModel(
            kind=kind,
            original_name=path.name,
            stored_name=f"{digest.removeprefix('sha256:')}{path.suffix.lower()}",
            sha256=digest,
            size_bytes=len(content),
        )
        for kind, path, content, digest in loaded
    )
    core = {
        "archive_id": archive_id,
        "artifacts": [item.model_dump(mode="json") for item in artifact_models],
        "authorization_digest": authorization_digest,
        "created_at": created_at.isoformat(),
        "evidence_bundle_digest": evidence_digest,
        "schema_version": "1",
    }
    manifest_digest = _digest_json(core)
    manifest = {**core, "manifest_digest": manifest_digest}

    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.name}-", dir=parent))
    try:
        artifact_root = staging / "artifacts"
        artifact_root.mkdir()
        for model, (_, _, content, _) in zip(artifact_models, loaded, strict=True):
            target = artifact_root / model.stored_name
            if target.exists() and target.read_bytes() != content:
                raise ReleaseCustodyError("Custody artifact digest collision detected")
            if not target.exists():
                target.write_bytes(content)
        (staging / "custody-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        os.rename(staging, output_path)
    except (OSError, ReleaseCustodyError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, ReleaseCustodyError):
            raise
        raise ReleaseCustodyError("Custody archive could not be created") from exc

    return verify_release_custody(output_path)


def verify_release_custody(path: Path) -> ReleaseCustodyIdentity:
    """Recompute the manifest and every referenced artifact digest."""
    if path.is_symlink() or not path.is_dir():
        raise ReleaseCustodyError("Custody archive path is not an allowed directory")
    manifest_path = path / "custody-manifest.json"
    raw = _read_json(manifest_path, maximum_bytes=1_048_576)
    try:
        manifest = _CustodyManifestModel.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseCustodyError("Custody manifest failed schema validation") from exc
    canonical = dict(raw)
    supplied_digest = canonical.pop("manifest_digest", None)
    if supplied_digest != _digest_json(canonical):
        raise ReleaseCustodyError("Custody manifest digest does not match")

    expected_paths = {Path("custody-manifest.json")}
    loaded: list[tuple[ReleaseCustodyArtifactKind, Path, bytes, str]] = []
    for artifact in manifest.artifacts:
        relative = Path("artifacts") / artifact.stored_name
        expected_paths.add(relative)
        artifact_path = path / relative
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ReleaseCustodyError("Custody artifact path is not allowed")
        try:
            content = artifact_path.read_bytes()
        except OSError as exc:
            raise ReleaseCustodyError("Custody artifact is unavailable") from exc
        digest = _digest_bytes(content)
        if digest != artifact.sha256 or len(content) != artifact.size_bytes:
            raise ReleaseCustodyError("Custody artifact digest or size does not match")
        loaded.append((artifact.kind, Path(artifact.original_name), content, digest))
    if sum(len(item[2]) for item in loaded) > 67_108_864:
        raise ReleaseCustodyError("Custody artifacts exceed the total size limit")

    actual_paths = {
        item.relative_to(path) for item in path.rglob("*") if item.is_file() or item.is_symlink()
    }
    if actual_paths != expected_paths:
        raise ReleaseCustodyError("Custody archive contains missing or untracked files")
    evidence_digest, authorization_digest = _validate_core_artifacts(tuple(loaded))
    if (
        evidence_digest != manifest.evidence_bundle_digest
        or authorization_digest != manifest.authorization_digest
    ):
        raise ReleaseCustodyError("Custody core artifact identity does not match")
    return ReleaseCustodyIdentity(
        archive_id=manifest.archive_id,
        created_at=manifest.created_at,
        evidence_bundle_digest=evidence_digest,
        authorization_digest=authorization_digest,
        manifest_digest=manifest.manifest_digest,
        artifact_count=len(manifest.artifacts),
    )


def _load_artifact(
    kind: ReleaseCustodyArtifactKind, path: Path
) -> tuple[ReleaseCustodyArtifactKind, Path, bytes, str]:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ReleaseCustodyError("Custody input artifact is unavailable") from exc
    if (
        path.is_symlink()
        or resolved != path.absolute()
        or not resolved.is_file()
        or _FILENAME.fullmatch(path.name) is None
    ):
        raise ReleaseCustodyError("Custody input artifact path or name is not allowed")
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise ReleaseCustodyError("Custody input artifact is unavailable") from exc
    if not content or len(content) > 8_388_608:
        raise ReleaseCustodyError("Custody input artifact has an invalid size")
    if any(marker in content for marker in _PRIVATE_KEY_MARKERS):
        raise ReleaseCustodyError("Private key material is not allowed in custody artifacts")
    return kind, path, content, _digest_bytes(content)


def _validate_core_artifacts(
    artifacts: tuple[tuple[ReleaseCustodyArtifactKind, Path, bytes, str], ...],
) -> tuple[str, str]:
    evidence = [
        item for item in artifacts if item[0] is ReleaseCustodyArtifactKind.RELEASE_EVIDENCE_BUNDLE
    ]
    authorization = [
        item
        for item in artifacts
        if item[0] is ReleaseCustodyArtifactKind.PROMOTION_AUTHORIZATION_REPORT
    ]
    trust_stores = [
        item for item in artifacts if item[0] is ReleaseCustodyArtifactKind.PUBLIC_TRUST_STORE
    ]
    if len(evidence) != 1 or len(authorization) != 1 or not trust_stores:
        raise ReleaseCustodyError("Custody archive composition is incomplete")
    report = _read_json_bytes(authorization[0][2], authorization[0][1].name)
    try:
        evidence_identity = load_release_evidence_bundle_bytes(evidence[0][2], evidence[0][1].name)
    except PromotionAttestationBoundaryError as exc:
        raise ReleaseCustodyError("Custody release evidence bundle is invalid") from exc
    evidence_digest = evidence_identity.bundle_digest
    try:
        _PromotionAuthorizationModel.model_validate(report)
    except ValidationError as exc:
        raise ReleaseCustodyError(
            "Custody promotion authorization report failed schema validation"
        ) from exc
    authorization_digest = _verified_embedded_digest(
        report,
        "authorization_digest",
        "PROMOTION_AUTHORIZED",
        "promotion authorization report",
    )
    if report.get("bundle_digest") != evidence_digest:
        raise ReleaseCustodyError("Promotion report does not bind the release evidence bundle")
    return evidence_digest, authorization_digest


def _verified_embedded_digest(
    document: dict[str, JsonValue], digest_field: str, required_status: str, label: str
) -> str:
    if document.get("status") != required_status or document.get("findings") not in ([], ()):
        raise ReleaseCustodyError(f"Custody {label} is not complete")
    canonical = dict(document)
    supplied = canonical.pop(digest_field, None)
    actual = _digest_json(canonical)
    if supplied != actual:
        raise ReleaseCustodyError(f"Custody {label} digest does not match")
    return actual


def _read_json(path: Path, *, maximum_bytes: int) -> dict[str, JsonValue]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ReleaseCustodyError("Custody manifest is unavailable") from exc
    if not content or len(content) > maximum_bytes:
        raise ReleaseCustodyError("Custody manifest has an invalid size")
    return _read_json_bytes(content, path.name)


def _read_json_bytes(content: bytes, filename: str) -> dict[str, JsonValue]:
    try:
        parsed = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseCustodyError(f"Custody JSON artifact is invalid: {filename}") from exc
    if not isinstance(parsed, dict):
        raise ReleaseCustodyError(f"Custody JSON artifact must be a mapping: {filename}")
    return parsed


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseCustodyError("Custody JSON artifact contains a duplicate key")
        result[key] = value
    return result


def _digest_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return _digest_bytes(encoded)


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
