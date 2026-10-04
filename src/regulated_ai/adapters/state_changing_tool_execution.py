"""Opt-in HTTP adapter for one reviewed state-changing enterprise sandbox tool."""

import hashlib
import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from regulated_ai.domain import ToolActionPlan, ToolExecutionReceipt, ToolExecutionResult

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_SAFE_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}\Z")
_SAFE_BEARER = re.compile(r"[!-~]{1,4096}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ALLOWED_TOOL = "cards.unblock"
_ALLOWED_RISK = "high_impact_state_change"


@dataclass(frozen=True, slots=True)
class StateChangingHttpToolExecutionConfig:
    """Explicit binding for one state-changing sandbox endpoint and workload."""

    endpoint_url: str
    api_key: str = field(repr=False)
    workload_identity: str
    timeout_seconds: float = 10.0
    max_request_bytes: int = 64 * 1024
    max_response_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        """Reject unsafe endpoints, credentials and unbounded payload settings."""
        _validate_endpoint(self.endpoint_url)
        if _SAFE_BEARER.fullmatch(self.api_key) is None:
            raise ValueError("State-changing tool API key is invalid")
        if _SAFE_IDENTIFIER.fullmatch(self.workload_identity) is None:
            raise ValueError("State-changing tool workload identity is invalid")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("State-changing tool timeout must be in the range (0, 60]")
        for name, value in (
            ("request", self.max_request_bytes),
            ("response", self.max_response_bytes),
        ):
            if value <= 0 or value > 1024 * 1024:
                raise ValueError(
                    f"State-changing tool {name} limit must be in the range [1, 1048576]"
                )


HttpClientFactory = Callable[[StateChangingHttpToolExecutionConfig], httpx.Client]


class StateChangingHttpToolExecutionAdapter:
    """Execute only approved `cards.unblock` actions against one bound sandbox."""

    def __init__(
        self,
        config: StateChangingHttpToolExecutionConfig,
        *,
        client_factory: HttpClientFactory | None = None,
    ) -> None:
        """Bind validated configuration without opening a network connection."""
        self._config = config
        self._client_factory = client_factory or _default_client_factory

    def execute(self, plan: ToolActionPlan) -> ToolExecutionResult:
        """Make one idempotency-bound request and return untrusted ephemeral output."""
        if (
            _SAFE_IDENTIFIER.fullmatch(plan.action_id) is None
            or _DIGEST.fullmatch(plan.action_digest) is None
            or plan.tool.name != _ALLOWED_TOOL
            or plan.tool.risk_class != _ALLOWED_RISK
            or plan.workload_identity != self._config.workload_identity
            or _SAFE_IDEMPOTENCY_KEY.fullmatch(plan.idempotency_key) is None
        ):
            raise ValueError("Tool action is outside the configured state-changing boundary")

        idempotency_key_digest = _digest(plan.idempotency_key)
        payload = json.dumps(
            {
                "action_id": plan.action_id,
                "action_digest": plan.action_digest,
                "arguments": dict(plan.arguments),
                "idempotency_key_digest": idempotency_key_digest,
                "tool": plan.tool.name,
                "workload_identity": plan.workload_identity,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        if len(payload) > self._config.max_request_bytes:
            raise ValueError("State-changing tool request exceeds the configured size limit")

        client = self._client_factory(self._config)
        try:
            with client.stream(
                "POST",
                self._config.endpoint_url,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": plan.idempotency_key,
                },
                content=payload,
            ) as response:
                if response.status_code != 200:
                    raise ValueError("State-changing tool returned a non-success status")
                content_type = response.headers.get("content-type", "").partition(";")[0].strip()
                if content_type.casefold() != "application/json":
                    raise ValueError("State-changing tool returned an unsupported content type")
                content_encoding = response.headers.get("content-encoding", "identity").strip()
                if content_encoding.casefold() != "identity":
                    raise ValueError("State-changing tool returned an unsupported content encoding")
                body = _bounded_response(response, self._config.max_response_bytes)
        finally:
            client.close()

        decoded = _decode_response(body)
        action_id = decoded.get("action_id")
        response_action_digest = decoded.get("action_digest")
        execution_id = decoded.get("execution_id")
        response_idempotency_digest = decoded.get("idempotency_key_digest")
        if (
            action_id != plan.action_id
            or response_action_digest != plan.action_digest
            or not isinstance(execution_id, str)
            or _SAFE_IDENTIFIER.fullmatch(execution_id) is None
            or not isinstance(response_idempotency_digest, str)
            or _DIGEST.fullmatch(response_idempotency_digest) is None
            or response_idempotency_digest != idempotency_key_digest
        ):
            raise ValueError("State-changing tool response binding is invalid")
        return ToolExecutionResult(
            receipt=ToolExecutionReceipt(execution_id=execution_id, action_id=plan.action_id),
            output=decoded["output"],
        )


def _default_client_factory(config: StateChangingHttpToolExecutionConfig) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(config.timeout_seconds),
        follow_redirects=False,
        trust_env=False,
    )


def _validate_endpoint(value: str) -> None:
    if not value.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("State-changing tool endpoint is invalid")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("State-changing tool endpoint is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path
    ):
        raise ValueError("State-changing tool endpoint is invalid")
    if parsed.scheme == "http" and not _is_loopback_literal(parsed.hostname):
        raise ValueError("State-changing tool HTTP endpoint must use a loopback IP literal")


def _is_loopback_literal(hostname: str) -> bool:
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _bounded_response(response: httpx.Response, maximum: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > maximum:
            raise ValueError("State-changing tool response exceeds the configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_response(body: bytes) -> dict[str, object]:
    try:
        decoded: object = json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("State-changing tool response is invalid JSON") from exc
    expected = {
        "action_id",
        "action_digest",
        "execution_id",
        "idempotency_key_digest",
        "output",
    }
    if not isinstance(decoded, dict) or set(decoded) != expected:
        raise ValueError("State-changing tool response shape is invalid")
    return decoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("State-changing tool response contains duplicate fields")
        result[key] = value
    return result


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
