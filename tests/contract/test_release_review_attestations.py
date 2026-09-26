import base64
import json
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from regulated_ai.adapters.release_review_attestations import (
    ReleaseReviewAttestationError,
    verify_release_review_attestations,
)
from regulated_ai.domain import ControlPackChangeType, ReleaseReviewConclusion


def test_verifies_role_and_change_authority_for_lifecycle_review(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(tmp_path / "trust.yaml", private_key)
    attestation = _write_attestation(tmp_path / "attestation.yaml", private_key)

    verified = verify_release_review_attestations((attestation,), trust_store)

    assert len(verified) == 1
    assert verified[0].change_type is ControlPackChangeType.ADDED
    assert verified[0].conclusion is ReleaseReviewConclusion.APPROVE
    assert verified[0].review_id is None
    assert verified[0].attestation_digest.startswith("sha256:")
    assert verified[0].signature_digest.startswith("sha256:")


def test_rejects_tampering_and_unauthorized_change_type(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(tmp_path / "trust.yaml", private_key)
    attestation = _write_attestation(tmp_path / "attestation.yaml", private_key)
    document = yaml.safe_load(attestation.read_text(encoding="utf-8"))
    document["conclusion"] = "REJECT"
    attestation.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    with pytest.raises(ReleaseReviewAttestationError, match="signature is invalid"):
        verify_release_review_attestations((attestation,), trust_store)

    attestation = _write_attestation(
        tmp_path / "removal.yaml",
        private_key,
        change_type="REMOVED",
    )
    with pytest.raises(ReleaseReviewAttestationError, match="change type is not authorized"):
        verify_release_review_attestations((attestation,), trust_store)


def test_modified_attestation_requires_detailed_review_binding(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(
        tmp_path / "trust.yaml",
        private_key,
        change_types=("ADDED", "MODIFIED"),
    )
    attestation = _write_attestation(
        tmp_path / "modified.yaml",
        private_key,
        change_type="MODIFIED",
    )

    with pytest.raises(ReleaseReviewAttestationError, match="schema validation"):
        verify_release_review_attestations((attestation,), trust_store)


def test_modified_tool_catalog_attestation_uses_whole_artifact_binding(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(
        tmp_path / "trust.yaml",
        private_key,
        change_types=("MODIFIED",),
        artifact_kind="TOOL_CATALOG",
    )
    attestation = _write_attestation(
        tmp_path / "tool-catalog.yaml",
        private_key,
        change_type="MODIFIED",
        artifact_kind="TOOL_CATALOG",
    )

    verified = verify_release_review_attestations((attestation,), trust_store)

    assert verified[0].review_id is None


def _write_trust_store(
    path: Path,
    private_key: Ed25519PrivateKey,
    *,
    change_types: tuple[str, ...] = ("ADDED",),
    artifact_kind: str = "POLICY_SET",
) -> Path:
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "keys": {
                    "policy-review-key": {
                        "algorithm": "ed25519",
                        "public_key": public_key,
                        "roles": ["policy-governance"],
                        "artifact_kinds": [artifact_kind],
                        "change_types": list(change_types),
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_attestation(
    path: Path,
    private_key: Ed25519PrivateKey,
    *,
    change_type: str = "ADDED",
    artifact_kind: str = "POLICY_SET",
) -> Path:
    document = {
        "schema_version": "1",
        "attestation_id": f"test-{change_type.lower()}",
        "artifact_kind": artifact_kind,
        "subject_id": ("trusted-tool-catalog" if artifact_kind == "TOOL_CATALOG" else "new-policy"),
        "change_type": change_type,
        "base_pack_payload_digest": f"sha256:{'a' * 64}",
        "candidate_pack_payload_digest": f"sha256:{'b' * 64}",
        "reviewed_content_digest": f"sha256:{'c' * 64}",
        "reviewer_role": "policy-governance",
        "conclusion": "APPROVE",
        "attested_at": "2026-09-26T15:00:00+00:00",
        "signing_key_id": "policy-review-key",
    }
    encoded = json.dumps(
        {
            **document,
            "review_digest": None,
            "review_id": None,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    document["signature"] = base64.b64encode(private_key.sign(encoded)).decode()
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path
