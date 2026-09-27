import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.verify_trust_store_rollout import main as rollout_main

from regulated_ai.adapters import (
    TrustStoreKind,
    create_trust_store_checkpoint,
    load_trust_store_rollout_policy,
)


def _checkpoint_keys(root: Path) -> tuple[Ed25519PrivateKey, Path, Path]:
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
    return key, private_path, public_path


def _public_key_base64(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()


def _write_acknowledgement(
    path: Path,
    key: Ed25519PrivateKey,
    *,
    key_id: str,
    target_id: str,
    checkpoint_digest: str,
    policy_digest: str,
) -> Path:
    document = {
        "schema_version": "1",
        "acknowledgement_id": f"ack-{target_id}",
        "checkpoint_digest": checkpoint_digest,
        "rollout_policy_digest": policy_digest,
        "store_id": "production-control-pack",
        "store_kind": "CONTROL_PACK",
        "sequence": 1,
        "target_id": target_id,
        "accepted_at": "2026-09-27T14:00:00+00:00",
        "signing_key_id": key_id,
    }
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    document["signature"] = base64.b64encode(key.sign(encoded)).decode()
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_cli_verifies_complete_and_incomplete_rollout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trust_store = tmp_path / "control-pack-trust.yaml"
    trust_store.write_text(
        'schema_version: "2"\nkeys:\n  release-key:\n    status: "ACTIVE"\n',
        encoding="utf-8",
    )
    _, checkpoint_private, checkpoint_public = _checkpoint_keys(tmp_path)
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = create_trust_store_checkpoint(
        trust_store,
        checkpoint_path,
        store_id="production-control-pack",
        store_kind=TrustStoreKind.CONTROL_PACK,
        sequence=1,
        issued_at=datetime(2026, 9, 27, 13, tzinfo=UTC),
        signing_key_id="distribution-root",
        private_key_path=checkpoint_private,
    )
    policy_path = tmp_path / "rollout-policy.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "policy_id": "production-rollout",
                "policy_version": "1",
                "checkpoint_digest": checkpoint.checkpoint_digest,
                "allowed_target_ids": ["node-a", "node-b"],
                "required_target_ids": ["node-a"],
                "minimum_acknowledgements": 2,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    policy = load_trust_store_rollout_policy(policy_path)
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    acknowledgement_trust_store = tmp_path / "ack-trust.yaml"
    acknowledgement_trust_store.write_text(
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
    ack_a = _write_acknowledgement(
        tmp_path / "ack-a.yaml",
        key_a,
        key_id="node-a-key",
        target_id="node-a",
        checkpoint_digest=checkpoint.checkpoint_digest,
        policy_digest=policy.policy_digest,
    )
    ack_b = _write_acknowledgement(
        tmp_path / "ack-b.yaml",
        key_b,
        key_id="node-b-key",
        target_id="node-b",
        checkpoint_digest=checkpoint.checkpoint_digest,
        policy_digest=policy.policy_digest,
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
        "--rollout-policy",
        str(policy_path),
        "--acknowledgement-trust-store",
        str(acknowledgement_trust_store),
        "--evaluated-at",
        "2026-09-27T15:00:00+00:00",
    ]

    assert rollout_main([*arguments, "--acknowledgement", str(ack_a)]) == 2
    incomplete = json.loads(capsys.readouterr().out)
    assert incomplete["status"] == "ROLLOUT_INCOMPLETE"

    assert (
        rollout_main(
            [
                *arguments,
                "--acknowledgement",
                str(ack_a),
                "--acknowledgement",
                str(ack_b),
            ]
        )
        == 0
    )
    complete = json.loads(capsys.readouterr().out)
    assert complete["status"] == "ROLLOUT_ACKNOWLEDGED"
    assert complete["report_digest"].startswith("sha256:")
