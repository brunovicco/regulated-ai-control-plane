import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.verify_runtime_trust_state import main as runtime_state_main

from regulated_ai.adapters import (
    TrustStoreKind,
    create_trust_store_checkpoint,
    load_runtime_trust_state_policy,
)


def _checkpoint_keys(root: Path) -> tuple[Path, Path]:
    key = Ed25519PrivateKey.generate()
    private_path = root / "checkpoint-private.pem"
    public_path = root / "checkpoint-public.pem"
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def _public_key_base64(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()


def _write_attestation(
    path: Path,
    key: Ed25519PrivateKey,
    *,
    key_id: str,
    target_id: str,
    checkpoint_digest: str,
    policy_digest: str,
    trust_store_digest: str,
    observed_at: str,
) -> Path:
    document = {
        "schema_version": "1",
        "attestation_id": f"state-{target_id}",
        "checkpoint_digest": checkpoint_digest,
        "runtime_policy_digest": policy_digest,
        "store_id": "production-control-pack",
        "store_kind": "CONTROL_PACK",
        "sequence": 1,
        "loaded_trust_store_digest": trust_store_digest,
        "target_id": target_id,
        "observed_at": observed_at,
        "signing_key_id": key_id,
    }
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    document["signature"] = base64.b64encode(key.sign(encoded)).decode()
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_cli_verifies_current_and_stale_runtime_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trust_store = tmp_path / "control-pack-trust.yaml"
    trust_store.write_text(
        'schema_version: "2"\nkeys:\n  release-key:\n    status: "ACTIVE"\n',
        encoding="utf-8",
    )
    checkpoint_private, checkpoint_public = _checkpoint_keys(tmp_path)
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = create_trust_store_checkpoint(
        trust_store,
        checkpoint_path,
        store_id="production-control-pack",
        store_kind=TrustStoreKind.CONTROL_PACK,
        sequence=1,
        issued_at=datetime(2026, 9, 27, 14, tzinfo=UTC),
        signing_key_id="distribution-root",
        private_key_path=checkpoint_private,
    )
    policy_path = tmp_path / "runtime-policy.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "policy_id": "production-runtime-state",
                "policy_version": "1",
                "checkpoint_digest": checkpoint.checkpoint_digest,
                "allowed_target_ids": ["node-a", "node-b"],
                "required_target_ids": ["node-a"],
                "minimum_attestations": 2,
                "maximum_age_seconds": 300,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    policy = load_runtime_trust_state_policy(policy_path)
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    attestation_trust_store = tmp_path / "runtime-keys.yaml"
    attestation_trust_store.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2",
                "keys": {
                    "node-a-key": {
                        "algorithm": "ed25519",
                        "public_key": _public_key_base64(key_a),
                        "target_ids": ["node-a"],
                        "status": "ACTIVE",
                        "valid_from": "2026-09-01T00:00:00Z",
                    },
                    "node-b-key": {
                        "algorithm": "ed25519",
                        "public_key": _public_key_base64(key_b),
                        "target_ids": ["node-b"],
                        "status": "ACTIVE",
                        "valid_from": "2026-09-01T00:00:00Z",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    stale_a = _write_attestation(
        tmp_path / "state-a-stale.yaml",
        key_a,
        key_id="node-a-key",
        target_id="node-a",
        checkpoint_digest=checkpoint.checkpoint_digest,
        policy_digest=policy.policy_digest,
        trust_store_digest=checkpoint.trust_store_digest,
        observed_at="2026-09-27T14:50:00+00:00",
    )
    attestation_directory = tmp_path / "attestations"
    attestation_directory.mkdir()
    current_a = _write_attestation(
        attestation_directory / "state-a.yaml",
        key_a,
        key_id="node-a-key",
        target_id="node-a",
        checkpoint_digest=checkpoint.checkpoint_digest,
        policy_digest=policy.policy_digest,
        trust_store_digest=checkpoint.trust_store_digest,
        observed_at="2026-09-27T14:58:00+00:00",
    )
    current_b = _write_attestation(
        attestation_directory / "state-b.yaml",
        key_b,
        key_id="node-b-key",
        target_id="node-b",
        checkpoint_digest=checkpoint.checkpoint_digest,
        policy_digest=policy.policy_digest,
        trust_store_digest=checkpoint.trust_store_digest,
        observed_at="2026-09-27T14:59:00+00:00",
    )
    arguments = [
        "--trust-store",
        str(trust_store),
        "--checkpoint",
        str(checkpoint_path),
        "--checkpoint-public-key",
        str(checkpoint_public),
        "--checkpoint-signing-key-id",
        "distribution-root",
        "--expected-checkpoint-digest",
        checkpoint.checkpoint_digest,
        "--runtime-policy",
        str(policy_path),
        "--attestation-trust-store",
        str(attestation_trust_store),
        "--evaluated-at",
        "2026-09-27T15:00:00+00:00",
    ]

    assert runtime_state_main([*arguments, "--attestation", str(stale_a)]) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == "RUNTIME_TRUST_STATE_BLOCKED"
    assert {item["code"] for item in blocked["findings"]} == {
        "ATTESTATION_STALE",
        "REQUIRED_TARGET_MISSING",
        "ATTESTATION_QUORUM_NOT_MET",
    }

    assert (
        runtime_state_main(
            [
                *arguments,
                "--attestation",
                str(current_a),
                "--attestation",
                str(current_b),
            ]
        )
        == 0
    )
    current = json.loads(capsys.readouterr().out)
    assert current["status"] == "RUNTIME_TRUST_STATE_CURRENT"
    assert current["report_digest"].startswith("sha256:")

    assert (
        runtime_state_main([*arguments, "--attestation-directory", str(attestation_directory)]) == 0
    )
    directory_result = json.loads(capsys.readouterr().out)
    assert directory_result == current
