"""Opt-in HTTP adapter for one reviewed read-only enterprise sandbox tool."""

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
_ALLOWED_TOOL = "cards.read"


@dataclass(frozen=True, slots=True)
class ReadOnlyHttpToolExecutionConfig:
    """Explicit binding for one sandbox endpoint, tool and workload identity."""

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
            raise ValueError("Read-only tool API key is invalid")
        if _SAFE_IDENTIFIER.fullmatch(self.workload_identity) is None:
            raise ValueError("Read-only tool workload identity is invalid")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("Read-only tool timeout must be in the range (0, 60]")
        for name, value in (
            ("request", self.max_request_bytes),
            ("response", self.max_response_bytes),
        ):
            if value <= 0 or value > 1024 * 1024:
                raise ValueError(f"Read-only tool {name} limit must be in the range [1, 1048576]")


HttpClientFactory = Callable[[ReadOnlyHttpToolExecutionConfig], httpx.Client]


class ReadOnlyHttpToolExecutionAdapter:
    """Execute only approved `cards.read` actions against one bound sandbox service."""

    def __init__(
        self,
        config: ReadOnlyHttpToolExecutionConfig,
        *,
        client_factory: HttpClientFactory | None = None,
    ) -> None:
        """Bind validated configuration without opening a network connection."""
        self._config = config
        self._client_factory = client_factory or _default_client_factory

    def execute(self, plan: ToolActionPlan) -> ToolExecutionResult:
        """Make one bounded request and return an untrusted ephemeral output."""
        if (
            plan.tool.name != _ALLOWED_TOOL
            or plan.tool.risk_class != "read_only"
            or plan.workload_identity != self._config.workload_identity
            or _SAFE_IDEMPOTENCY_KEY.fullmatch(plan.idempotency_key) is None
        ):
            raise ValueError("Tool action is outside the configured read-only boundary")

        payload = json.dumps(
            {
                "action_id": plan.action_id,
                "arguments": dict(plan.arguments),
                "tool": plan.tool.name,
                "workload_identity": plan.workload_identity,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        if len(payload) > self._config.max_request_bytes:
            raise ValueError("Read-only tool request exceeds the configured size limit")

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
                    raise ValueError("Read-only tool returned a non-success status")
                content_type = response.headers.get("content-type", "").partition(";")[0].strip()
                if content_type.casefold() != "application/json":
                    raise ValueError("Read-only tool returned an unsupported content type")
                content_encoding = response.headers.get("content-encoding", "identity").strip()
                if content_encoding.casefold() != "identity":
                    raise ValueError("Read-only tool returned an unsupported content encoding")
                body = _bounded_response(response, self._config.max_response_bytes)
        finally:
            client.close()

        decoded = _decode_response(body)
        action_id = decoded.get("action_id")
        execution_id = decoded.get("execution_id")
        if (
            action_id != plan.action_id
            or not isinstance(execution_id, str)
            or _SAFE_IDENTIFIER.fullmatch(execution_id) is None
        ):
            raise ValueError("Read-only tool response binding is invalid")
        return ToolExecutionResult(
            receipt=ToolExecutionReceipt(execution_id=execution_id, action_id=plan.action_id),
            output=decoded["output"],
        )


def _default_client_factory(config: ReadOnlyHttpToolExecutionConfig) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(config.timeout_seconds),
        follow_redirects=False,
        trust_env=False,
    )


def _validate_endpoint(value: str) -> None:
    if not value.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("Read-only tool endpoint is invalid")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Read-only tool endpoint is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path
    ):
        raise ValueError("Read-only tool endpoint is invalid")
    if parsed.scheme == "http" and not _is_loopback_literal(parsed.hostname):
        raise ValueError("Read-only tool HTTP endpoint must use a loopback IP literal")


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
            raise ValueError("Read-only tool response exceeds the configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_response(body: bytes) -> dict[str, object]:
    try:
        decoded: object = json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Read-only tool response is invalid JSON") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"action_id", "execution_id", "output"}:
        raise ValueError("Read-only tool response shape is invalid")
    return decoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Read-only tool response contains duplicate fields")
        result[key] = value
    return result
