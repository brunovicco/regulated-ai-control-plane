import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.manage_trust_store_lineage import main as lineage_main

from regulated_ai.adapters import (
    TrustStoreKind,
    TrustStoreLineageError,
    create_trust_store_checkpoint,
    verify_trust_store_checkpoint,
)


def _write_trust_store(path: Path, *, status: str = "ACTIVE") -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2",
                "keys": {
                    "test-key": {
                        "algorithm": "ed25519",
                        "public_key": "synthetic-public-key",
                        "status": status,
                        "valid_from": "2026-09-01T00:00:00Z",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_checkpoint_keys(root: Path) -> tuple[Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    private_path = root / "checkpoint-private.pem"
    public_path = root / "checkpoint-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def test_creates_and_verifies_genesis_against_pinned_digest(tmp_path: Path) -> None:
    trust_store = _write_trust_store(tmp_path / "trust.yaml")
    private_key, public_key = _write_checkpoint_keys(tmp_path)
    checkpoint = tmp_path / "checkpoint.json"

    created = create_trust_store_checkpoint(
        trust_store,
        checkpoint,
        store_id="release-signing",
        store_kind=TrustStoreKind.CONTROL_PACK,
        sequence=1,
        issued_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        signing_key_id="distribution-root",
        private_key_path=private_key,
    )
    verified = verify_trust_store_checkpoint(
        trust_store,
        checkpoint,
        public_key_path=public_key,
        signing_key_id="distribution-root",
        expected_checkpoint_digest=created.checkpoint_digest,
        minimum_sequence=1,
    )

    assert verified == created
    assert verified.previous_checkpoint_digest is None
    assert verified.trust_store_digest.startswith("sha256:")


def test_successor_binds_previous_checkpoint_and_changed_bytes(tmp_path: Path) -> None:
    trust_store = _write_trust_store(tmp_path / "trust.yaml")
    private_key, public_key = _write_checkpoint_keys(tmp_path)
    first_path = tmp_path / "checkpoint-1.json"
    first = create_trust_store_checkpoint(
        trust_store,
        first_path,
        store_id="release-signing",
        store_kind=TrustStoreKind.CONTROL_PACK,
        sequence=1,
        issued_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        signing_key_id="distribution-root",
        private_key_path=private_key,
    )
    _write_trust_store(trust_store, status="REVOKED")
    second_path = tmp_path / "checkpoint-2.json"
    second = create_trust_store_checkpoint(
        trust_store,
        second_path,
        store_id="release-signing",
        store_kind=TrustStoreKind.CONTROL_PACK,
        sequence=2,
        issued_at=datetime(2026, 9, 27, 13, tzinfo=UTC),
        signing_key_id="distribution-root",
        private_key_path=private_key,
        previous_checkpoint_path=first_path,
    )

    verified = verify_trust_store_checkpoint(
        trust_store,
        second_path,
        public_key_path=public_key,
        signing_key_id="distribution-root",
        previous_checkpoint_path=first_path,
        minimum_sequence=2,
    )

    assert verified == second
    assert second.previous_checkpoint_digest == first.checkpoint_digest


def test_rejects_rollback_tampering_and_unanchored_verification(tmp_path: Path) -> None:
    trust_store = _write_trust_store(tmp_path / "trust.yaml")
    private_key, public_key = _write_checkpoint_keys(tmp_path)
    checkpoint = tmp_path / "checkpoint.json"
    identity = create_trust_store_checkpoint(
        trust_store,
        checkpoint,
        store_id="release-signing",
        store_kind=TrustStoreKind.CONTROL_PACK,
        sequence=1,
        issued_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        signing_key_id="distribution-root",
        private_key_path=private_key,
    )

    with pytest.raises(TrustStoreLineageError, match="trusted rollback anchor"):
        verify_trust_store_checkpoint(
            trust_store,
            checkpoint,
            public_key_path=public_key,
            signing_key_id="distribution-root",
        )
    with pytest.raises(TrustStoreLineageError, match="minimum sequence"):
        verify_trust_store_checkpoint(
            trust_store,
            checkpoint,
            public_key_path=public_key,
            signing_key_id="distribution-root",
            minimum_sequence=2,
        )
    with pytest.raises(TrustStoreLineageError, match="trusted digest"):
        verify_trust_store_checkpoint(
            trust_store,
            checkpoint,
            public_key_path=public_key,
            signing_key_id="distribution-root",
            expected_checkpoint_digest=f"sha256:{'0' * 64}",
        )

    document = json.loads(checkpoint.read_text(encoding="utf-8"))
    document["store_id"] = "tampered-release-signing"
    canonical = dict(document)
    canonical.pop("checkpoint_digest")
    canonical.pop("signature")
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    document["checkpoint_digest"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    checkpoint.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TrustStoreLineageError, match="signature is invalid"):
        verify_trust_store_checkpoint(
            trust_store,
            checkpoint,
            public_key_path=public_key,
            signing_key_id="distribution-root",
            expected_checkpoint_digest=identity.checkpoint_digest,
        )


def test_rejects_unchanged_successor_private_key_and_existing_output(tmp_path: Path) -> None:
    trust_store = _write_trust_store(tmp_path / "trust.yaml")
    private_key, _ = _write_checkpoint_keys(tmp_path)
    first = tmp_path / "checkpoint-1.json"
    create_trust_store_checkpoint(
        trust_store,
        first,
        store_id="release-signing",
        store_kind=TrustStoreKind.CONTROL_PACK,
        sequence=1,
        issued_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        signing_key_id="distribution-root",
        private_key_path=private_key,
    )

    with pytest.raises(TrustStoreLineageError, match="unchanged"):
        create_trust_store_checkpoint(
            trust_store,
            tmp_path / "checkpoint-2.json",
            store_id="release-signing",
            store_kind=TrustStoreKind.CONTROL_PACK,
            sequence=2,
            issued_at=datetime(2026, 9, 27, 13, tzinfo=UTC),
            signing_key_id="distribution-root",
            private_key_path=private_key,
            previous_checkpoint_path=first,
        )
    with pytest.raises(TrustStoreLineageError, match="already exists"):
        create_trust_store_checkpoint(
            trust_store,
            first,
            store_id="other",
            store_kind=TrustStoreKind.CONTROL_PACK,
            sequence=1,
            issued_at=datetime(2026, 9, 27, 13, tzinfo=UTC),
            signing_key_id="distribution-root",
            private_key_path=private_key,
        )

    trust_store.write_text("-----BEGIN PRIVATE KEY-----\nsynthetic\n", encoding="utf-8")
    with pytest.raises(TrustStoreLineageError, match="Private key material"):
        create_trust_store_checkpoint(
            trust_store,
            tmp_path / "private.json",
            store_id="release-signing",
            store_kind=TrustStoreKind.CONTROL_PACK,
            sequence=1,
            issued_at=datetime(2026, 9, 27, 13, tzinfo=UTC),
            signing_key_id="distribution-root",
            private_key_path=private_key,
        )


def test_cli_create_and_verify_emit_same_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trust_store = _write_trust_store(tmp_path / "trust.yaml")
    private_key, public_key = _write_checkpoint_keys(tmp_path)
    checkpoint = tmp_path / "checkpoint.json"
    create_args = (
        "create",
        "--trust-store",
        str(trust_store),
        "--output",
        str(checkpoint),
        "--store-id",
        "release-signing",
        "--store-kind",
        "CONTROL_PACK",
        "--sequence",
        "1",
        "--issued-at",
        "2026-09-27T12:00:00+00:00",
        "--signing-key-id",
        "distribution-root",
        "--private-key",
        str(private_key),
    )

    assert lineage_main(create_args) == 0
    created = json.loads(capsys.readouterr().out)
    assert (
        lineage_main(
            (
                "verify",
                "--trust-store",
                str(trust_store),
                "--checkpoint",
                str(checkpoint),
                "--signing-key-id",
                "distribution-root",
                "--public-key",
                str(public_key),
                "--expected-checkpoint-digest",
                created["checkpoint_digest"],
            )
        )
        == 0
    )
    verified = json.loads(capsys.readouterr().out)

    assert created == verified
