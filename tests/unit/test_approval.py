import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from regulated_ai.adapters import ApprovalAssertionError, HmacApprovalAdapter

from ..helpers import NOW, approval_assertion

KEY = b"a" * 32
DIGEST = f"sha256:{'1' * 64}"
VALID_ASSERTION = approval_assertion(KEY, DIGEST)
PREFIX, PAYLOAD, SIGNATURE = VALID_ASSERTION.split(".")
TAMPERED_ASSERTION = f"{PREFIX}.{PAYLOAD}.{'A' if SIGNATURE[0] != 'A' else 'B'}{SIGNATURE[1:]}"


def _adapter(tmp_path: Path) -> HmacApprovalAdapter:
    return HmacApprovalAdapter(tmp_path / "approval.sqlite3", KEY)


def test_valid_assertion_is_bound_and_consumed_once(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    assertion = approval_assertion(KEY, DIGEST)

    grant = adapter.inspect(assertion, decision_digest=DIGEST, now=NOW)
    receipt = adapter.consume(grant, enforcement_id="enf_test", now=NOW)

    assert receipt.approval_id == "approval-test-1"
    assert receipt.decision_digest == DIGEST
    assert adapter.get(receipt.approval_id) == receipt
    with pytest.raises(ApprovalAssertionError):
        adapter.consume(grant, enforcement_id="enf_other", now=NOW)
    assert assertion not in (tmp_path / "approval.sqlite3").read_bytes().decode(errors="ignore")


@pytest.mark.parametrize(
    "assertion",
    [
        "not-an-assertion",
        TAMPERED_ASSERTION,
        "ra1.é.invalid",
        VALID_ASSERTION + "=",
    ],
)
def test_malformed_or_tampered_assertion_is_rejected(tmp_path: Path, assertion: str) -> None:
    with pytest.raises(ApprovalAssertionError):
        _adapter(tmp_path).inspect(assertion, decision_digest=DIGEST, now=NOW)


def test_assertion_is_rejected_for_a_different_decision(tmp_path: Path) -> None:
    assertion = approval_assertion(KEY, DIGEST)

    with pytest.raises(ApprovalAssertionError):
        _adapter(tmp_path).inspect(
            assertion,
            decision_digest=f"sha256:{'2' * 64}",
            now=NOW,
        )


def test_noncanonical_signed_payload_is_rejected(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1",
        "approval_id": "approval-test-1",
        "actor_id": "approver-test-1",
        "decision_digest": DIGEST,
        "issued_at": int(NOW.timestamp()),
        "expires_at": int((NOW + timedelta(minutes=5)).timestamp()),
    }
    noncanonical = json.dumps(payload, indent=2).encode()
    segment = base64.urlsafe_b64encode(noncanonical).rstrip(b"=").decode()
    signed = f"ra1.{segment}"
    signature = base64.urlsafe_b64encode(
        hmac.new(KEY, signed.encode(), hashlib.sha256).digest()
    ).rstrip(b"=")
    assertion = f"{signed}.{signature.decode()}"

    with pytest.raises(ApprovalAssertionError):
        _adapter(tmp_path).inspect(assertion, decision_digest=DIGEST, now=NOW)


@pytest.mark.parametrize(
    "issued_at,expires_at,now",
    [
        (NOW - timedelta(minutes=10), NOW - timedelta(minutes=1), NOW),
        (NOW + timedelta(seconds=1), NOW + timedelta(minutes=1), NOW),
        (NOW, NOW + timedelta(hours=2), NOW),
    ],
)
def test_assertion_time_bounds_fail_closed(
    tmp_path: Path,
    issued_at: datetime,
    expires_at: datetime,
    now: datetime,
) -> None:
    assertion = approval_assertion(
        KEY,
        DIGEST,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    with pytest.raises(ApprovalAssertionError):
        _adapter(tmp_path).inspect(
            assertion,
            decision_digest=DIGEST,
            now=now,
        )


def test_short_keys_and_unsafe_lifetime_configuration_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        HmacApprovalAdapter(tmp_path / "short.sqlite3", b"short")
    with pytest.raises(ValueError):
        HmacApprovalAdapter(tmp_path / "long.sqlite3", KEY, max_lifetime_seconds=86_401)
