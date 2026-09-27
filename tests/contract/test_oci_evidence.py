import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.manage_oci_evidence import main as oci_main

from regulated_ai.adapters import (
    OciEvidenceError,
    ReleaseCustodyArtifactKind,
    create_oci_evidence_layout,
    verify_oci_evidence_layout,
)

_CREATED_AT = datetime(2026, 9, 27, 18, tzinfo=UTC)


def _artifacts(tmp_path: Path) -> tuple[tuple[ReleaseCustodyArtifactKind, Path], ...]:
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text('{"status":"EVIDENCE_COMPLETE"}\n', encoding="utf-8")
    trust = tmp_path / "public-trust.yaml"
    trust.write_text('schema_version: "2"\nkeys: {}\n', encoding="utf-8")
    return (
        (ReleaseCustodyArtifactKind.RELEASE_EVIDENCE_BUNDLE, evidence),
        (ReleaseCustodyArtifactKind.PUBLIC_TRUST_STORE, trust),
    )


def test_creates_deterministic_oci_layout_and_verifies_reference(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    first = create_oci_evidence_layout(
        tmp_path / "first",
        package_ref="release-2026.09",
        created_at=_CREATED_AT,
        artifacts=artifacts,
    )
    second = create_oci_evidence_layout(
        tmp_path / "second",
        package_ref="release-2026.09",
        created_at=_CREATED_AT,
        artifacts=artifacts,
    )

    assert first == second
    assert first.artifact_count == 2
    assert first.manifest_digest.startswith("sha256:")
    assert (
        verify_oci_evidence_layout(tmp_path / "first", expected_package_ref="release-2026.09")
        == first
    )
    assert (tmp_path / "first" / "oci-layout").is_file()
    assert (tmp_path / "first" / "index.json").is_file()


def test_cli_create_and_verify_emit_same_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = tmp_path / "layout"
    arguments = [
        "create",
        "--output",
        str(layout),
        "--package-ref",
        "release-2026.09",
        "--created-at",
        _CREATED_AT.isoformat(),
    ]
    for kind, path in _artifacts(tmp_path):
        arguments.extend(("--artifact", f"{kind.value}={path}"))

    assert oci_main(arguments) == 0
    created = json.loads(capsys.readouterr().out)
    assert oci_main(("verify", "--layout", str(layout), "--package-ref", "release-2026.09")) == 0
    verified = json.loads(capsys.readouterr().out)

    assert created == verified
    assert created["status"] == "OCI_EVIDENCE_VERIFIED"
    assert "release" not in created


@pytest.mark.parametrize("failure", ["blob", "root", "reference"])
def test_tampering_untracked_files_and_wrong_reference_fail_closed(
    tmp_path: Path, failure: str
) -> None:
    layout = tmp_path / "layout"
    create_oci_evidence_layout(
        layout,
        package_ref="release-2026.09",
        created_at=_CREATED_AT,
        artifacts=_artifacts(tmp_path),
    )
    expected_ref = "release-2026.09"
    if failure == "blob":
        blob = next((layout / "blobs" / "sha256").iterdir())
        blob.write_bytes(blob.read_bytes() + b"tampered")
    elif failure == "root":
        (layout / "unexpected.json").write_text("{}", encoding="utf-8")
    else:
        expected_ref = "release-2026.10"

    with pytest.raises(OciEvidenceError):
        verify_oci_evidence_layout(layout, expected_package_ref=expected_ref)


def test_rejects_unsafe_reference_symlink_and_private_key(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    with pytest.raises(OciEvidenceError, match="reference"):
        create_oci_evidence_layout(
            tmp_path / "invalid-ref",
            package_ref="Registry/Release:latest",
            created_at=_CREATED_AT,
            artifacts=artifacts,
        )

    target = artifacts[0][1]
    symlink = tmp_path / "linked-evidence.json"
    symlink.symlink_to(target)
    with pytest.raises(OciEvidenceError, match="path or name"):
        create_oci_evidence_layout(
            tmp_path / "symlink",
            package_ref="release-2026.09",
            created_at=_CREATED_AT,
            artifacts=((ReleaseCustodyArtifactKind.RELEASE_EVIDENCE_BUNDLE, symlink),),
        )

    target.write_text("-----BEGIN PRIVATE KEY-----\nnot-a-key\n", encoding="utf-8")
    with pytest.raises(OciEvidenceError, match="Private key"):
        create_oci_evidence_layout(
            tmp_path / "private-key",
            package_ref="release-2026.09",
            created_at=_CREATED_AT,
            artifacts=artifacts,
        )
