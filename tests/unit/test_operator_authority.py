import base64
import json
import traceback
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from regulated_ai.adapters import (
    ActionApprovalAssertionError,
    ApprovalAssertionError,
    Ed25519ActionApprovalAdapter,
    Ed25519ApprovalAdapter,
    Ed25519OperatorAuthorityVerifier,
    Ed25519ToolActionReconciliationAdapter,
    OperatorAuthorityTrustStoreError,
    ToolActionReconciliationAssertionError,
)
from regulated_ai.entrypoints.api import build_runtime

from ..helpers import NOW

DECISION_DIGEST = f"sha256:{'1' * 64}"
ACTION_DIGEST = f"sha256:{'2' * 64}"


def _trust_store(
    path: Path,
    key: Ed25519PrivateKey,
    *,
    actor_id: str = "operator-test-1",
    authorities: tuple[str, ...] = (
        "decision_approval",
        "action_approval",
        "reconciliation",
    ),
    status: str = "ACTIVE",
) -> Path:
    public_key = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "keys": {
                    "operator-key-1": {
                        "algorithm": "ed25519",
                        "public_key": base64.b64encode(public_key).decode(),
                        "actor_id": actor_id,
                        "authorities": list(authorities),
                        "status": status,
                        "valid_from": (NOW - timedelta(days=1)).isoformat(),
                        "valid_until": (NOW + timedelta(days=1)).isoformat(),
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _assertion(key: Ed25519PrivateKey, prefix: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    segment = base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()
    signed = f"{prefix}.{segment}"
    signature = base64.urlsafe_b64encode(key.sign(signed.encode())).rstrip(b"=").decode()
    return f"{signed}.{signature}"


def _decision_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "2",
        "authority_kind": "decision_approval",
        "key_id": "operator-key-1",
        "approval_id": "approval-ed25519-1",
        "actor_id": "operator-test-1",
        "decision_digest": DECISION_DIGEST,
        "issued_at": int(NOW.timestamp()),
        "expires_at": int((NOW + timedelta(minutes=5)).timestamp()),
    }
    payload.update(updates)
    return payload


def _action_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "3",
        "subject_type": "tool_action",
        "authority_kind": "action_approval",
        "key_id": "operator-key-1",
        "approval_id": "action-approval-ed25519-1",
        "actor_id": "operator-test-1",
        "action_digest": ACTION_DIGEST,
        "issued_at": int(NOW.timestamp()),
        "expires_at": int((NOW + timedelta(minutes=5)).timestamp()),
    }
    payload.update(updates)
    return payload


def _reconciliation_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "2",
        "subject_type": "tool_action_reconciliation",
        "authority_kind": "reconciliation",
        "key_id": "operator-key-1",
        "reconciliation_id": "reconciliation-ed25519-1",
        "actor_id": "operator-test-1",
        "action_digest": ACTION_DIGEST,
        "outcome": "EXECUTED",
        "tool_execution_id": "execution-test-1",
        "issued_at": int(NOW.timestamp()),
        "expires_at": int((NOW + timedelta(minutes=5)).timestamp()),
    }
    payload.update(updates)
    return payload


def test_decision_assertion_binds_actor_key_digest_and_consumption(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    verifier = Ed25519OperatorAuthorityVerifier(_trust_store(tmp_path / "trust.yaml", key))
    adapter = Ed25519ApprovalAdapter(tmp_path / "evidence.sqlite3", verifier)
    assertion = _assertion(key, "ra1e", _decision_payload())

    grant = adapter.inspect(assertion, decision_digest=DECISION_DIGEST, now=NOW)
    receipt = adapter.consume(grant, enforcement_id="enforcement-test-1", now=NOW)

    assert receipt.actor_id == "operator-test-1"
    assert receipt.authority_key_id == "operator-key-1"
    assert adapter.get(receipt.approval_id) == receipt
    with pytest.raises(ApprovalAssertionError):
        adapter.consume(grant, enforcement_id="enforcement-test-2", now=NOW)


def test_action_and_reconciliation_authority_are_domain_separated(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    verifier = Ed25519OperatorAuthorityVerifier(_trust_store(tmp_path / "trust.yaml", key))
    action = Ed25519ActionApprovalAdapter(tmp_path / "evidence.sqlite3", verifier)
    reconciliation = Ed25519ToolActionReconciliationAdapter(tmp_path / "evidence.sqlite3", verifier)

    action_grant = action.inspect(
        _assertion(key, "ra2e", _action_payload()), action_digest=ACTION_DIGEST, now=NOW
    )
    action_receipt = action.consume(action_grant, action_id="action-test-1", now=NOW)
    reconciliation_grant = reconciliation.inspect(
        _assertion(key, "rr1e", _reconciliation_payload()),
        action_digest=ACTION_DIGEST,
        now=NOW,
    )
    reconciliation_receipt = reconciliation.consume(
        reconciliation_grant, action_id="action-test-2", now=NOW
    )

    assert action_receipt.authority_key_id == "operator-key-1"
    assert reconciliation_receipt.authority_key_id == "operator-key-1"
    with pytest.raises(ActionApprovalAssertionError):
        action.inspect(
            _assertion(key, "rr1e", _reconciliation_payload()),
            action_digest=ACTION_DIGEST,
            now=NOW,
        )


def test_key_scope_actor_lifecycle_and_signature_fail_closed(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    trust_store = _trust_store(tmp_path / "trust.yaml", key, authorities=("decision_approval",))
    verifier = Ed25519OperatorAuthorityVerifier(trust_store)

    with pytest.raises(ActionApprovalAssertionError):
        verifier.inspect_action(
            _assertion(key, "ra2e", _action_payload()),
            action_digest=ACTION_DIGEST,
            now=NOW,
            max_lifetime_seconds=3600,
        )
    with pytest.raises(ApprovalAssertionError):
        verifier.inspect_decision(
            _assertion(key, "ra1e", _decision_payload(actor_id="another-operator")),
            decision_digest=DECISION_DIGEST,
            now=NOW,
            max_lifetime_seconds=3600,
        )

    retired = Ed25519OperatorAuthorityVerifier(
        _trust_store(tmp_path / "retired.yaml", key, status="RETIRED")
    )
    with pytest.raises(ApprovalAssertionError):
        retired.inspect_decision(
            _assertion(key, "ra1e", _decision_payload()),
            decision_digest=DECISION_DIGEST,
            now=NOW,
            max_lifetime_seconds=3600,
        )

    other_key = Ed25519PrivateKey.generate()
    with pytest.raises(ApprovalAssertionError):
        verifier.inspect_decision(
            _assertion(other_key, "ra1e", _decision_payload()),
            decision_digest=DECISION_DIGEST,
            now=NOW,
            max_lifetime_seconds=3600,
        )


def test_invalid_trust_store_is_rejected_before_runtime_use(tmp_path: Path) -> None:
    path = tmp_path / "trust.yaml"
    path.write_text("schema_version: '1'\nkeys: {}\n", encoding="utf-8")

    with pytest.raises(OperatorAuthorityTrustStoreError):
        Ed25519OperatorAuthorityVerifier(path)

    key = Ed25519PrivateKey.generate()
    malformed_path = _trust_store(tmp_path / "malformed-key.yaml", key)
    public_key = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()
    malformed_path.write_text(
        malformed_path.read_text(encoding="utf-8").replace(public_key, "not-base64"),
        encoding="utf-8",
    )
    with pytest.raises(OperatorAuthorityTrustStoreError):
        Ed25519OperatorAuthorityVerifier(malformed_path)


def test_runtime_rejects_mixed_asymmetric_and_hmac_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Ed25519PrivateKey.generate()
    trust_store = _trust_store(tmp_path / "trust.yaml", key)
    monkeypatch.setenv("REGULAAI_OPERATOR_AUTHORITY_TRUST_STORE", str(trust_store))
    monkeypatch.setenv("REGULAAI_APPROVAL_HMAC_KEY", "a" * 32)

    with pytest.raises(ValueError, match="mutually exclusive"):
        build_runtime(evidence_path=tmp_path / "evidence.sqlite3")


@pytest.mark.parametrize("malformed_yaml", [False, True])
def test_trust_store_failure_does_not_expose_private_content_in_traceback(
    tmp_path: Path, malformed_yaml: bool
) -> None:
    sentinel = "synthetic-private-content-sentinel"
    path = _trust_store(tmp_path / "trust.yaml", Ed25519PrivateKey.generate())
    content = path.read_text(encoding="utf-8")
    if malformed_yaml:
        content += f"private_key: [{sentinel}\n"
    else:
        content += f"private_key: {sentinel}\n"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(OperatorAuthorityTrustStoreError) as captured:
        Ed25519OperatorAuthorityVerifier(path)

    rendered = "".join(traceback.format_exception(captured.value))
    assert sentinel not in rendered
    assert "Operator authority trust store is invalid" in rendered


def test_reconciliation_rejects_invalid_outcome_binding(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    verifier = Ed25519OperatorAuthorityVerifier(_trust_store(tmp_path / "trust.yaml", key))
    adapter = Ed25519ToolActionReconciliationAdapter(tmp_path / "evidence.sqlite3", verifier)

    with pytest.raises(ToolActionReconciliationAssertionError):
        adapter.inspect(
            _assertion(
                key,
                "rr1e",
                _reconciliation_payload(outcome="NOT_EXECUTED", tool_execution_id="unexpected"),
            ),
            action_digest=ACTION_DIGEST,
            now=NOW,
        )
