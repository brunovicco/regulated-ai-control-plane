"""Ephemeral synthetic issuers; private signing material never leaves memory."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class PilotIssuer:
    """Issue role-separated test JWTs and domain-separated operation assertions."""

    def __init__(self, directory: Path) -> None:
        self.identity_key = Ed25519PrivateKey.generate()
        self.authority_key = Ed25519PrivateKey.generate()
        self.jwks = directory / "jwks.json"
        self.trust_store = directory / "operator-public.yaml"
        self.jwks.write_text(
            json.dumps(
                {
                    "keys": [
                        {
                            "alg": "EdDSA",
                            "crv": "Ed25519",
                            "kid": "pilot-api",
                            "kty": "OKP",
                            "use": "sig",
                            "x": _segment(self.identity_key.public_key().public_bytes_raw()),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        now = datetime.now(UTC)
        self.trust_store.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "1",
                    "keys": {
                        "pilot-operator": {
                            "algorithm": "ed25519",
                            "public_key": base64.b64encode(
                                self.authority_key.public_key().public_bytes_raw()
                            ).decode(),
                            "actor_id": "pilot-operator",
                            "authorities": [
                                "decision_approval",
                                "action_approval",
                                "reconciliation",
                            ],
                            "status": "ACTIVE",
                            "valid_from": (now - timedelta(days=1)).isoformat(),
                            "valid_until": (now + timedelta(days=1)).isoformat(),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def headers(self, role: str) -> dict[str, str]:
        now = int(datetime.now(UTC).timestamp())
        header = _segment(
            json.dumps(
                {
                    "alg": "EdDSA",
                    "kid": "pilot-api",
                    "typ": "at+jwt",
                }
            ).encode()
        )
        payload = _segment(
            json.dumps(
                {
                    "iss": "https://identity.example.test/pilot",
                    "aud": "regulaai-pilot",
                    "sub": "pilot-workload",
                    "client_id": "pilot-client",
                    "jti": uuid4().hex,
                    "iat": now - 1,
                    "exp": now + 300,
                    "roles": [role],
                }
            ).encode()
        )
        signed = f"{header}.{payload}"
        token = f"{signed}.{_segment(self.identity_key.sign(signed.encode()))}"
        return {"Authorization": f"Bearer {token}"}

    def assertion(self, kind: str, digest: str, *, outcome: str = "EXECUTED") -> str:
        now = int(datetime.now(UTC).timestamp())
        payload: dict[str, object] = {
            "authority_kind": kind,
            "key_id": "pilot-operator",
            "actor_id": "pilot-operator",
            "issued_at": now - 1,
            "expires_at": now + 300,
        }
        if kind == "decision_approval":
            prefix = "ra1e"
            payload.update(schema_version="2", approval_id=uuid4().hex, decision_digest=digest)
        elif kind == "action_approval":
            prefix = "ra2e"
            payload.update(
                schema_version="3",
                subject_type="tool_action",
                approval_id=uuid4().hex,
                action_digest=digest,
            )
        else:
            assert kind == "reconciliation"
            prefix = "rr1e"
            payload.update(
                schema_version="2",
                subject_type="tool_action_reconciliation",
                reconciliation_id=uuid4().hex,
                action_digest=digest,
                outcome=outcome,
                tool_execution_id="pilot-effect" if outcome == "EXECUTED" else None,
            )
        segment = _segment(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signed = f"{prefix}.{segment}"
        return f"{signed}.{_segment(self.authority_key.sign(signed.encode()))}"
