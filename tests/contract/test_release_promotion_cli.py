import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.authorize_release_promotion import main as promotion_main


def test_cli_authorizes_exact_bundle_with_distinct_role_quorum(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = _write_bundle(tmp_path / "bundle.json")
    control_key = Ed25519PrivateKey.generate()
    release_key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(
        tmp_path / "trust.yaml",
        {
            "control-key": (control_key, "CONTROL_OWNER"),
            "release-key": (release_key, "RELEASE_MANAGER"),
        },
    )
    policy = _write_policy(tmp_path / "policy.yaml")
    policy_digest = _policy_digest(policy)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    control_attestation = _write_attestation(
        tmp_path / "control.yaml",
        control_key,
        "control-key",
        "CONTROL_OWNER",
        bundle,
        policy_digest,
    )
    release_attestation = _write_attestation(
        tmp_path / "release.yaml",
        release_key,
        "release-key",
        "RELEASE_MANAGER",
        bundle,
        policy_digest,
    )
    arguments = _arguments(
        bundle_path,
        policy,
        trust_store,
        control_attestation,
        release_attestation,
    )

    assert promotion_main(arguments) == 0
    first_capture = capsys.readouterr()
    assert promotion_main(arguments) == 0
    second_capture = capsys.readouterr()
    payload = json.loads(first_capture.out)

    assert first_capture.err == ""
    assert first_capture.out == second_capture.out
    assert payload["status"] == "PROMOTION_AUTHORIZED"
    assert payload["bundle_digest"] == bundle["bundle_digest"]
    assert payload["findings"] == []
    assert payload["authorization_digest"].startswith("sha256:")
    assert '"signature":' not in first_capture.out


def test_cli_returns_blocked_when_required_role_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = _write_bundle(tmp_path / "bundle.json")
    control_key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(
        tmp_path / "trust.yaml", {"control-key": (control_key, "CONTROL_OWNER")}
    )
    policy = _write_policy(tmp_path / "policy.yaml")
    policy_digest = _policy_digest(policy)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    attestation = _write_attestation(
        tmp_path / "control.yaml",
        control_key,
        "control-key",
        "CONTROL_OWNER",
        bundle,
        policy_digest,
    )

    assert promotion_main(_arguments(bundle_path, policy, trust_store, attestation)) == 2
    capture = capsys.readouterr()
    payload = json.loads(capture.out)

    assert capture.err == ""
    assert payload["status"] == "PROMOTION_BLOCKED"
    assert {item["code"] for item in payload["findings"]} == {
        "APPROVAL_QUORUM_NOT_MET",
        "REQUIRED_ROLE_MISSING",
    }


def test_cli_rejects_tampered_attestation_signature(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = _write_bundle(tmp_path / "bundle.json")
    control_key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(
        tmp_path / "trust.yaml", {"control-key": (control_key, "CONTROL_OWNER")}
    )
    policy = _write_policy(tmp_path / "policy.yaml")
    policy_digest = _policy_digest(policy)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    attestation = _write_attestation(
        tmp_path / "control.yaml",
        control_key,
        "control-key",
        "CONTROL_OWNER",
        bundle,
        policy_digest,
    )
    document = yaml.safe_load(attestation.read_text(encoding="utf-8"))
    document["decision"] = "REJECT"
    attestation.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    assert promotion_main(_arguments(bundle_path, policy, trust_store, attestation)) == 1
    capture = capsys.readouterr()

    assert capture.out == ""
    assert "signature is invalid" in capture.err


def test_cli_rejects_tampered_or_incomplete_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = _write_bundle(tmp_path / "bundle.json")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["status"] = "EVIDENCE_INCOMPLETE"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(
        tmp_path / "trust.yaml", {"control-key": (key, "CONTROL_OWNER")}
    )
    policy = _write_policy(tmp_path / "policy.yaml")

    assert promotion_main(_arguments(bundle_path, policy, trust_store)) == 1
    capture = capsys.readouterr()

    assert capture.out == ""
    assert "bundle digest does not match" in capture.err


def test_cli_rejects_revoked_promotion_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = _write_bundle(tmp_path / "bundle.json")
    key = Ed25519PrivateKey.generate()
    trust_store = _write_trust_store(
        tmp_path / "trust.yaml", {"control-key": (key, "CONTROL_OWNER")}
    )
    trust_document = yaml.safe_load(trust_store.read_text(encoding="utf-8"))
    trust_document["keys"]["control-key"]["status"] = "REVOKED"
    trust_store.write_text(yaml.safe_dump(trust_document, sort_keys=False), encoding="utf-8")
    policy = _write_policy(tmp_path / "policy.yaml")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    attestation = _write_attestation(
        tmp_path / "control.yaml",
        key,
        "control-key",
        "CONTROL_OWNER",
        bundle,
        _policy_digest(policy),
    )

    assert promotion_main(_arguments(bundle_path, policy, trust_store, attestation)) == 1
    capture = capsys.readouterr()
    assert "key is not active" in capture.err


def _arguments(
    bundle: Path,
    policy: Path,
    trust_store: Path,
    *attestations: Path,
) -> list[str]:
    arguments = [
        "--evidence-bundle",
        str(bundle),
        "--promotion-policy",
        str(policy),
        "--attestation-trust-store",
        str(trust_store),
        "--evaluated-at",
        "2026-09-26T15:00:00+00:00",
    ]
    for attestation in attestations:
        arguments.extend(("--attestation", str(attestation)))
    return arguments


def _write_bundle(path: Path) -> Path:
    core: dict[str, object] = {
        "schema_version": "2",
        "status": "EVIDENCE_COMPLETE",
        "base_pack": {
            "id": "test-pack",
            "version": "1",
            "signing_key_id": "pack-key",
            "payload_digest": f"sha256:{'a' * 64}",
        },
        "candidate_pack": {
            "id": "test-pack",
            "version": "2",
            "signing_key_id": "pack-key",
            "payload_digest": f"sha256:{'b' * 64}",
        },
        "static_analysis": {"status": "NO_SEMANTIC_CHANGE"},
        "scenario_replay": {"status": "NO_OBSERVED_CHANGE"},
        "review_evidence": [],
        "findings": [],
        "summary": {"findings": 0},
        "evidence_scope": "Synthetic metadata-only contract evidence.",
    }
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    payload = {
        **core,
        "bundle_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_policy(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "policy_id": "test-promotion-policy",
                "policy_version": "1",
                "required_roles": ["CONTROL_OWNER", "RELEASE_MANAGER"],
                "minimum_approvals": 2,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_trust_store(
    path: Path,
    keys: dict[str, tuple[Ed25519PrivateKey, str]],
) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2",
                "keys": {
                    key_id: {
                        "algorithm": "ed25519",
                        "public_key": base64.b64encode(
                            private_key.public_key().public_bytes(
                                serialization.Encoding.Raw,
                                serialization.PublicFormat.Raw,
                            )
                        ).decode(),
                        "roles": [role],
                        "status": "ACTIVE",
                        "valid_from": "2026-09-01T00:00:00Z",
                        "valid_until": "2099-09-01T00:00:00Z",
                    }
                    for key_id, (private_key, role) in keys.items()
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
    key_id: str,
    role: str,
    bundle: dict[str, object],
    policy_digest: str,
) -> Path:
    candidate = bundle["candidate_pack"]
    assert isinstance(candidate, dict)
    document = {
        "schema_version": "1",
        "attestation_id": f"test-{key_id}",
        "bundle_digest": bundle["bundle_digest"],
        "candidate_pack_payload_digest": candidate["payload_digest"],
        "promotion_policy_digest": policy_digest,
        "decision": "APPROVE",
        "role": role,
        "issued_at": datetime(2026, 9, 26, 14, 0, tzinfo=UTC).isoformat(),
        "expires_at": datetime(2026, 9, 26, 16, 0, tzinfo=UTC).isoformat(),
        "signing_key_id": key_id,
    }
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    document["signature"] = base64.b64encode(private_key.sign(encoded)).decode()
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _policy_digest(path: Path) -> str:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
