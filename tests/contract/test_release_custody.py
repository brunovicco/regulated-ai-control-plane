import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.manage_release_custody import main as custody_main

from regulated_ai.adapters.release_custody import (
    ReleaseCustodyArtifactKind,
    ReleaseCustodyError,
    create_release_custody,
    verify_release_custody,
)


def _write_json_with_digest(path: Path, core: dict[str, object], field: str) -> Path:
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    document = {**core, field: f"sha256:{hashlib.sha256(encoded).hexdigest()}"}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _artifacts(tmp_path: Path) -> tuple[tuple[ReleaseCustodyArtifactKind, Path], ...]:
    release_identity = {
        "id": "test-pack",
        "version": "1",
        "signing_key_id": "test-key",
        "payload_digest": f"sha256:{'a' * 64}",
    }
    bundle = _write_json_with_digest(
        tmp_path / "release-bundle.json",
        {
            "schema_version": "2",
            "status": "EVIDENCE_COMPLETE",
            "base_pack": release_identity,
            "candidate_pack": {**release_identity, "version": "2"},
            "static_analysis": {},
            "scenario_replay": {},
            "review_evidence": [],
            "findings": [],
            "summary": {},
            "evidence_scope": "Synthetic metadata-only test evidence.",
        },
        "bundle_digest",
    )
    bundle_digest = json.loads(bundle.read_text(encoding="utf-8"))["bundle_digest"]
    authorization = _write_json_with_digest(
        tmp_path / "promotion-report.json",
        {
            "schema_version": "1",
            "status": "PROMOTION_AUTHORIZED",
            "bundle_digest": bundle_digest,
            "base_pack": release_identity,
            "candidate_pack": {**release_identity, "version": "2"},
            "policy": {},
            "evaluated_at": "2026-09-26T18:00:00+00:00",
            "attestations": [],
            "findings": [],
            "authorization_scope": "Synthetic metadata-only test authorization.",
        },
        "authorization_digest",
    )
    trust = tmp_path / "release-trust.yaml"
    trust.write_text('schema_version: "2"\nkeys: {}\n', encoding="utf-8")
    return (
        (ReleaseCustodyArtifactKind.RELEASE_EVIDENCE_BUNDLE, bundle),
        (ReleaseCustodyArtifactKind.PROMOTION_AUTHORIZATION_REPORT, authorization),
        (ReleaseCustodyArtifactKind.PUBLIC_TRUST_STORE, trust),
    )


def test_creates_and_verifies_content_addressed_archive(tmp_path: Path) -> None:
    archive = tmp_path / "release-custody"

    created = create_release_custody(
        archive,
        archive_id="release-2026-09-26",
        created_at=datetime(2026, 9, 26, 18, tzinfo=UTC),
        artifacts=_artifacts(tmp_path),
    )
    verified = verify_release_custody(archive)

    assert created == verified
    assert created.artifact_count == 3
    assert created.manifest_digest.startswith("sha256:")
    assert len(tuple((archive / "artifacts").iterdir())) == 3


def test_detects_tampering_and_untracked_files(tmp_path: Path) -> None:
    archive = tmp_path / "release-custody"
    create_release_custody(
        archive,
        archive_id="release-2026-09-26",
        created_at=datetime(2026, 9, 26, 18, tzinfo=UTC),
        artifacts=_artifacts(tmp_path),
    )
    artifact = next((archive / "artifacts").iterdir())
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"\n")

    with pytest.raises(ReleaseCustodyError, match="digest or size"):
        verify_release_custody(archive)

    artifact.write_bytes(original)
    (archive / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseCustodyError, match="untracked files"):
        verify_release_custody(archive)


def test_rejects_private_keys_and_existing_output(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    trust = artifacts[-1][1]
    trust.write_text("-----BEGIN PRIVATE KEY-----\nnot-a-key\n", encoding="utf-8")

    with pytest.raises(ReleaseCustodyError, match="Private key material"):
        create_release_custody(
            tmp_path / "release-custody",
            archive_id="release-2026-09-26",
            created_at=datetime(2026, 9, 26, 18, tzinfo=UTC),
            artifacts=tuple(artifacts),
        )

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ReleaseCustodyError, match="already exists"):
        create_release_custody(
            existing,
            archive_id="release-2026-09-26",
            created_at=datetime(2026, 9, 26, 18, tzinfo=UTC),
            artifacts=_artifacts(tmp_path),
        )


def test_rejects_symlinked_input(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    trust = artifacts[-1][1]
    symlink = tmp_path / "linked-trust.yaml"
    symlink.symlink_to(trust)
    artifacts[-1] = (ReleaseCustodyArtifactKind.PUBLIC_TRUST_STORE, symlink)

    with pytest.raises(ReleaseCustodyError, match="path or name is not allowed"):
        create_release_custody(
            tmp_path / "release-custody",
            archive_id="release-2026-09-26",
            created_at=datetime(2026, 9, 26, 18, tzinfo=UTC),
            artifacts=tuple(artifacts),
        )


def test_cli_create_and_verify_emit_same_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "release-custody"
    arguments = [
        "create",
        "--output",
        str(archive),
        "--archive-id",
        "release-2026-09-26",
        "--created-at",
        "2026-09-26T18:00:00+00:00",
    ]
    for kind, path in _artifacts(tmp_path):
        arguments.extend(("--artifact", f"{kind.value}={path}"))

    assert custody_main(arguments) == 0
    created = capsys.readouterr()
    assert custody_main(("verify", "--archive", str(archive))) == 0
    verified = capsys.readouterr()

    assert created.err == verified.err == ""
    assert json.loads(created.out) == json.loads(verified.out)
