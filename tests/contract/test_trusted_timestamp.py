import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.verify_trusted_timestamp import main as timestamp_main

from regulated_ai.adapters import (
    TimestampSubjectKind,
    TrustedTimestampError,
    verify_trusted_timestamp,
)


def _fixture(root: Path) -> tuple[Path, Path, Path, Ed25519PrivateKey]:
    artifact = root / "release-evidence.json"
    artifact.write_text('{"release":"2026.09"}\n', encoding="utf-8")
    key = Ed25519PrivateKey.generate()
    trust_store = root / "timestamp-trust.yaml"
    trust_store.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2",
                "keys": {
                    "tsa-key-1": {
                        "algorithm": "ed25519",
                        "public_key": base64.b64encode(
                            key.public_key().public_bytes(
                                serialization.Encoding.Raw,
                                serialization.PublicFormat.Raw,
                            )
                        ).decode(),
                        "authority_id": "external-tsa",
                        "status": "ACTIVE",
                        "valid_from": "2026-09-01T00:00:00Z",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    receipt = root / "timestamp-receipt.yaml"
    _write_receipt(receipt, artifact, key)
    return artifact, receipt, trust_store, key


def _write_receipt(
    path: Path,
    artifact: Path,
    key: Ed25519PrivateKey,
    *,
    issued_at: str = "2026-09-27T14:00:00+00:00",
    subject_kind: str = "RELEASE_EVIDENCE_BUNDLE",
) -> None:
    document = {
        "schema_version": "1",
        "receipt_id": "tsa-receipt-1",
        "subject_kind": subject_kind,
        "subject_digest": f"sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}",
        "issued_at": issued_at,
        "authority_id": "external-tsa",
        "signing_key_id": "tsa-key-1",
    }
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    document["signature"] = base64.b64encode(key.sign(payload)).decode()
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_cli_verifies_timestamp_and_emits_metadata_only_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact, receipt, trust_store, _ = _fixture(tmp_path)

    assert (
        timestamp_main(
            [
                "--artifact",
                str(artifact),
                "--receipt",
                str(receipt),
                "--trust-store",
                str(trust_store),
                "--subject-kind",
                "RELEASE_EVIDENCE_BUNDLE",
                "--evaluated-at",
                "2026-09-27T15:00:00+00:00",
                "--minimum-issued-at",
                "2026-09-27T13:00:00+00:00",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "TRUSTED_TIMESTAMP_VERIFIED"
    assert report["subject_digest"].startswith("sha256:")
    assert report["signature_digest"].startswith("sha256:")
    assert "release" not in report


@pytest.mark.parametrize("failure", ["artifact", "kind", "future", "floor", "signature"])
def test_invalid_digest_kind_time_floor_and_signature_fail_closed(
    tmp_path: Path, failure: str
) -> None:
    artifact, receipt, trust_store, key = _fixture(tmp_path)
    expected_kind = TimestampSubjectKind.RELEASE_EVIDENCE_BUNDLE
    evaluated_at = datetime(2026, 9, 27, 15, tzinfo=UTC)
    minimum_issued_at: datetime | None = None
    if failure == "artifact":
        artifact.write_text('{"release":"tampered"}\n', encoding="utf-8")
    elif failure == "kind":
        expected_kind = TimestampSubjectKind.TRUST_STORE_CHECKPOINT
    elif failure == "future":
        _write_receipt(receipt, artifact, key, issued_at="2026-09-27T16:00:00+00:00")
    elif failure == "floor":
        minimum_issued_at = datetime(2026, 9, 27, 14, 1, tzinfo=UTC)
    else:
        document = yaml.safe_load(receipt.read_text(encoding="utf-8"))
        document["signature"] = base64.b64encode(b"x" * 64).decode()
        receipt.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    with pytest.raises(TrustedTimestampError):
        verify_trusted_timestamp(
            artifact,
            receipt,
            trust_store,
            expected_subject_kind=expected_kind,
            evaluated_at=evaluated_at,
            minimum_issued_at=minimum_issued_at,
        )
