"""Probe enterprise-issued role tokens without performing business mutations."""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True, slots=True)
class PilotApiTokens:
    """Ephemeral bearer tokens issued externally for three distinct API roles."""

    runtime: str = field(repr=False)
    operator: str = field(repr=False)
    reconciler: str = field(repr=False)

    def __post_init__(self) -> None:
        """Reject absent tokens and header control characters without echoing them."""
        for token in (self.runtime, self.operator, self.reconciler):
            if (
                not token.isascii()
                or not 1 <= len(token) <= 8192
                or any(ord(char) <= 32 or ord(char) == 127 for char in token)
            ):
                raise ValueError("Pilot role token is invalid")


def probe_enterprise_identity(client: httpx.Client, tokens: PilotApiTokens) -> dict[str, object]:
    """Verify authentication and the full role matrix using invalid mutation bodies."""
    routes = (
        ("runtime", "POST", "/v1/evaluations", 422),
        ("operator", "GET", "/v1/providers", 200),
        ("reconciler", "POST", "/v1/tool-actions/pilot-identity-probe/reconciliation", 422),
    )
    credentials = {
        "runtime": tokens.runtime,
        "operator": tokens.operator,
        "reconciler": tokens.reconciler,
    }
    pack_digest: str | None = None
    checks: list[str] = []
    for route_role, method, path, expected in routes:
        for caller_role, token in (("anonymous", None), *credentials.items()):
            headers = {"Accept-Encoding": "identity"}
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            wanted = 401 if token is None else expected if caller_role == route_role else 403
            with client.stream(
                method, path, headers=headers, json={} if method == "POST" else None
            ) as response:
                if response.status_code != wanted:
                    raise ValueError("Enterprise identity role matrix failed")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_048_576:
                        raise ValueError("Enterprise identity response exceeds the limit")
                if caller_role == "operator" and route_role == "operator":
                    pack_digest = _control_pack_digest(body)
            checks.append(f"{caller_role}.{route_role}.{wanted}")
    if pack_digest is None:
        raise ValueError("Enterprise identity control pack is unavailable")
    core: dict[str, object] = {
        "schema_version": "1",
        "status": "ENTERPRISE_IDENTITY_VERIFIED",
        "observed_at": datetime.now(UTC).isoformat(),
        "control_pack_digest": pack_digest,
        "checks": checks,
        "business_mutations": 0,
    }
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    return {**core, "report_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}"}


def _control_pack_digest(body: bytearray) -> str:
    value: object = json.loads(body)
    if isinstance(value, dict) and isinstance(value.get("control_pack"), dict):
        digest = value["control_pack"].get("payload_digest")
        if isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            return digest
    raise ValueError("Enterprise identity control-pack response is invalid")


def _validate_url(value: str) -> None:
    url = urlsplit(value)
    _ = url.port
    if (
        not value.isascii()
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        or url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("Pilot API endpoint is invalid")
    if url.scheme == "http" and not ipaddress.ip_address(url.hostname).is_loopback:
        raise ValueError("Pilot API HTTP endpoint must use a loopback IP literal")


def main(argv: Sequence[str] | None = None) -> int:
    """Read endpoint and role tokens from the environment; output metadata only."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        if os.environ.get("REGULAAI_ENVIRONMENT") not in {"pilot", "sandbox", "test", "local"}:
            raise ValueError("Pilot requires an explicit non-production environment")
        endpoint = os.environ.get("REGULAAI_PILOT_API_URL", "")
        _validate_url(endpoint)
        tokens = PilotApiTokens(
            *(
                os.environ.get(name, "")
                for name in (
                    "REGULAAI_PILOT_RUNTIME_TOKEN",
                    "REGULAAI_PILOT_OPERATOR_TOKEN",
                    "REGULAAI_PILOT_RECONCILER_TOKEN",
                )
            )
        )
        with httpx.Client(
            base_url=endpoint.rstrip("/") + "/", timeout=10, follow_redirects=False, trust_env=False
        ) as client:
            report = probe_enterprise_identity(client, tokens)
    except Exception as exc:
        print(f"Enterprise identity pilot failed closed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
