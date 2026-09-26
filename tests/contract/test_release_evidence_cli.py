import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.assemble_release_evidence import main as evidence_main

from regulated_ai.adapters.signed_packs import verify_control_pack


def _arguments(root: Path) -> list[str]:
    manifest = root / "src" / "regulated_ai" / "resources" / "control-pack-manifest.yaml"
    return [
        "--base-manifest",
        str(manifest),
        "--candidate-manifest",
        str(manifest),
        "--trust-store",
        str(
            root / "src" / "regulated_ai" / "resources" / "trust" / "control-pack-signing-keys.yaml"
        ),
        "--scenario-suite",
        str(root / "examples" / "scenarios" / "control-pack-regression.yaml"),
    ]


def test_cli_composes_deterministic_complete_evidence_for_unchanged_release(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[2]
    arguments = _arguments(root)

    assert evidence_main(arguments) == 0
    first_capture = capsys.readouterr()
    assert evidence_main(arguments) == 0
    second_capture = capsys.readouterr()
    first = json.loads(first_capture.out)

    assert first_capture.err == ""
    assert second_capture.err == ""
    assert first_capture.out == second_capture.out
    assert first["status"] == "EVIDENCE_COMPLETE"
    assert first["static_analysis"]["status"] == "NO_SEMANTIC_CHANGE"
    assert first["scenario_replay"]["status"] == "NO_OBSERVED_CHANGE"
    assert first["review_evidence"] == []
    assert first["findings"] == []
    assert first["bundle_digest"].startswith("sha256:")


def test_cli_rebinds_policy_review_to_exact_signed_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = Path(__file__).resolve().parents[2]
    base_root = tmp_path / "base"
    candidate_root = tmp_path / "candidate"
    source = repository / "src" / "regulated_ai" / "resources"
    shutil.copytree(source, base_root)
    shutil.copytree(source, candidate_root)

    private_key = Ed25519PrivateKey.generate()
    trust_store = tmp_path / "trust.yaml"
    _write_trust_store(trust_store, private_key)
    base_manifest = _sign_pack(base_root, "test.1", private_key)

    candidate_policy = candidate_root / "policies" / "br-financial-external-inference.yaml"
    policy_document = yaml.safe_load(candidate_policy.read_text(encoding="utf-8"))
    policy_document["policy_set"]["version"] = "1.1.0"
    changed_rule = policy_document["rules"][0]
    changed_rule["version"] = "1.1.0"
    changed_rule["control_objectives"].append("BR.PRIV.DEMONSTRABLE_CONTROLS")
    candidate_policy.write_text(
        yaml.safe_dump(policy_document, sort_keys=False),
        encoding="utf-8",
    )
    candidate_manifest = _sign_pack(candidate_root, "test.2", private_key)

    base_digest = verify_control_pack(base_manifest, trust_store).identity.payload_digest
    candidate_pack_digest = verify_control_pack(
        candidate_manifest, trust_store
    ).identity.payload_digest
    candidate_digest = f"sha256:{hashlib.sha256(candidate_policy.read_bytes()).hexdigest()}"
    review_path = tmp_path / "policy-review.yaml"
    review_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "review": {
                    "id": "test-policy-review",
                    "reviewer_role": "regulatory-governance",
                    "reviewed_at": "2026-09-26",
                    "base_pack_payload_digest": base_digest,
                    "candidate_policy_digest": candidate_digest,
                    "policy_set_id": "br-financial-demo",
                    "policy_set_review": {
                        "changed_fields": ["version"],
                        "conclusion": "APPROVED",
                    },
                    "rule_reviews": [
                        {
                            "rule_id": "br.financial.external_inference.minimize_identifier",
                            "change_type": "MODIFIED",
                            "control_objective_ids": sorted(changed_rule["control_objectives"]),
                            "regulatory_support_refs": changed_rule["regulatory_support"],
                            "conclusion": "APPROVED",
                        }
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    arguments = [
        "--base-manifest",
        str(base_manifest),
        "--candidate-manifest",
        str(candidate_manifest),
        "--trust-store",
        str(trust_store),
        "--scenario-suite",
        str(repository / "examples" / "scenarios" / "control-pack-regression.yaml"),
    ]

    assert evidence_main(arguments) == 2
    missing = json.loads(capsys.readouterr().out)
    assert missing["findings"] == [
        {"code": "POLICY_REVIEW_MISSING", "subject_id": "br-financial-demo"}
    ]

    assert evidence_main([*arguments, "--policy-review-record", str(review_path)]) == 2
    unsigned = json.loads(capsys.readouterr().out)
    assert unsigned["findings"] == [
        {"code": "POLICY_REVIEW_MISSING", "subject_id": "br-financial-demo"}
    ]

    review_private_key = Ed25519PrivateKey.generate()
    review_trust_store = tmp_path / "review-trust.yaml"
    _write_review_trust_store(review_trust_store, review_private_key)
    attestation_path = tmp_path / "policy-review-attestation.yaml"
    _write_review_attestation(
        attestation_path,
        review_private_key,
        base_digest=base_digest,
        candidate_pack_digest=candidate_pack_digest,
        candidate_content_digest=candidate_digest,
        review_path=review_path,
    )

    assert (
        evidence_main(
            [
                *arguments,
                "--policy-review-record",
                str(review_path),
                "--review-trust-store",
                str(review_trust_store),
                "--review-attestation",
                str(attestation_path),
            ]
        )
        == 0
    )
    complete_capture = capsys.readouterr()
    complete = json.loads(complete_capture.out)
    assert complete_capture.err == ""
    assert complete["status"] == "EVIDENCE_COMPLETE"
    assert complete["schema_version"] == "2"
    assert complete["review_evidence"][0]["reviewed_content_digest"] == candidate_digest
    assert complete["review_evidence"][0]["change_type"] == "MODIFIED"
    assert complete["review_evidence"][0]["signing_key_id"] == "review-key"
    assert complete["review_evidence"][0]["approved"] is True


def _write_trust_store(path: Path, private_key: Ed25519PrivateKey) -> None:
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2",
                "keys": {
                    "test-key": {
                        "algorithm": "ed25519",
                        "public_key": public_key,
                        "status": "ACTIVE",
                        "valid_from": "2026-09-01T00:00:00Z",
                        "valid_until": "2099-09-01T00:00:00Z",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_review_trust_store(path: Path, private_key: Ed25519PrivateKey) -> None:
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2",
                "keys": {
                    "review-key": {
                        "algorithm": "ed25519",
                        "public_key": public_key,
                        "roles": ["regulatory-governance"],
                        "artifact_kinds": ["POLICY_SET"],
                        "change_types": ["MODIFIED"],
                        "status": "ACTIVE",
                        "valid_from": "2026-09-01T00:00:00Z",
                        "valid_until": "2099-09-01T00:00:00Z",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_review_attestation(
    path: Path,
    private_key: Ed25519PrivateKey,
    *,
    base_digest: str,
    candidate_pack_digest: str,
    candidate_content_digest: str,
    review_path: Path,
) -> None:
    review_digest = f"sha256:{hashlib.sha256(review_path.read_bytes()).hexdigest()}"
    document = {
        "schema_version": "1",
        "attestation_id": "test-policy-review-attestation",
        "artifact_kind": "POLICY_SET",
        "subject_id": "br-financial-demo",
        "change_type": "MODIFIED",
        "base_pack_payload_digest": base_digest,
        "candidate_pack_payload_digest": candidate_pack_digest,
        "reviewed_content_digest": candidate_content_digest,
        "review_id": "test-policy-review",
        "review_digest": review_digest,
        "reviewer_role": "regulatory-governance",
        "conclusion": "APPROVE",
        "attested_at": "2026-09-26T15:00:00+00:00",
        "signing_key_id": "review-key",
    }
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    document["signature"] = base64.b64encode(private_key.sign(encoded)).decode()
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _sign_pack(
    root: Path,
    version: str,
    private_key: Ed25519PrivateKey,
) -> Path:
    manifest_path = root / "control-pack-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["pack_version"] = version
    manifest["signing"] = {
        "algorithm": "ed25519",
        "key_id": "test-key",
        "signature": "pending",
    }
    for item in manifest["files"]:
        content = (root / item["path"]).read_bytes()
        item["sha256"] = f"sha256:{hashlib.sha256(content).hexdigest()}"
    payload = {
        "files": [
            {"kind": item["kind"], "path": item["path"], "sha256": item["sha256"]}
            for item in sorted(manifest["files"], key=lambda item: (item["kind"], item["path"]))
        ],
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "schema_version": manifest["schema_version"],
        "signing": {"algorithm": "ed25519", "key_id": "test-key"},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    manifest["signing"]["signature"] = base64.b64encode(private_key.sign(encoded)).decode()
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    return manifest_path
