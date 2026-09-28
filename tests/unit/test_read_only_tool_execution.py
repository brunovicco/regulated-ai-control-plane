import gzip
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from regulated_ai.adapters import (
    ReadOnlyHttpToolExecutionAdapter,
    ReadOnlyHttpToolExecutionConfig,
)
from regulated_ai.domain import ActionApprovalReceipt, ToolActionPlan

from ..helpers import authorized_tool


def _plan() -> ToolActionPlan:
    now = datetime(2026, 9, 28, 12, tzinfo=UTC)
    return ToolActionPlan(
        action_id="action-read-1",
        action_digest=f"sha256:{'1' * 64}",
        enforcement_id="enforcement-read-1",
        call_id="call-read-1",
        tool=authorized_tool("cards.read", "read_only"),
        workload_identity="workload.cards-sandbox",
        idempotency_key="idempotency-read-1",
        arguments=(("account_token", "tok_synthetic"),),
        approval_receipt=ActionApprovalReceipt(
            approval_id="approval-read-1",
            actor_id="reviewer-synthetic",
            action_digest=f"sha256:{'1' * 64}",
            action_id="action-read-1",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            consumed_at=now,
        ),
    )


def _config(**changes: object) -> ReadOnlyHttpToolExecutionConfig:
    values: dict[str, object] = {
        "endpoint_url": "https://cards-sandbox.example.test/v1/card-status",
        "api_key": "synthetic-sandbox-credential",
        "workload_identity": "workload.cards-sandbox",
    }
    values.update(changes)
    return ReadOnlyHttpToolExecutionConfig(**values)  # type: ignore[arg-type]


def _adapter(handler: httpx.MockTransport) -> ReadOnlyHttpToolExecutionAdapter:
    return ReadOnlyHttpToolExecutionAdapter(
        _config(),
        client_factory=lambda config: httpx.Client(
            transport=handler,
            timeout=config.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ),
    )


def test_read_only_adapter_sends_one_bound_canonical_request() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        assert str(request.url) == "https://cards-sandbox.example.test/v1/card-status"
        assert request.headers["authorization"] == "Bearer synthetic-sandbox-credential"
        assert request.headers["idempotency-key"] == "idempotency-read-1"
        assert json.loads(request.content) == {
            "action_id": "action-read-1",
            "arguments": {"account_token": "tok_synthetic"},
            "tool": "cards.read",
            "workload_identity": "workload.cards-sandbox",
        }
        return httpx.Response(
            200,
            json={
                "action_id": "action-read-1",
                "execution_id": "sandbox-read-1",
                "output": {
                    "card_status": "ACTIVE",
                    "internal_reference": "synthetic-reference",
                    "diagnostic": "synthetic-diagnostic",
                },
            },
        )

    result = _adapter(httpx.MockTransport(handle)).execute(_plan())

    assert calls == 1
    assert result.receipt.execution_id == "sandbox-read-1"
    assert result.receipt.action_id == "action-read-1"
    assert result.output == {
        "card_status": "ACTIVE",
        "internal_reference": "synthetic-reference",
        "diagnostic": "synthetic-diagnostic",
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://cards.example.test/v1/read",
        "http://localhost/v1/read",
        "ftp://cards.example.test/v1/read",
        "https://user@cards.example.test/v1/read",
        "https://cards.example.test/v1/read?target=other",
        "https://cards.example.test/v1/read#fragment",
        "https://cards.example.test",
        "https://cards.example.test/v1/read\nunsafe",
    ],
)
def test_read_only_config_rejects_unsafe_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        _config(endpoint_url=endpoint)


def test_read_only_config_accepts_loopback_http_and_hides_secret() -> None:
    config = _config(endpoint_url="http://127.0.0.1:9000/v1/read")

    assert "synthetic-sandbox-credential" not in repr(config)


def test_read_only_config_rejects_header_unsafe_credential() -> None:
    with pytest.raises(ValueError, match="API key"):
        _config(api_key="unsafe\x00credential")


@pytest.mark.parametrize(
    "plan",
    [
        replace(_plan(), tool=authorized_tool("cards.unblock", "high_impact_state_change")),
        replace(_plan(), workload_identity="workload.other-sandbox"),
        replace(_plan(), tool=authorized_tool("cards.read", "high_impact_state_change")),
    ],
)
def test_read_only_adapter_rejects_out_of_scope_plan_before_network(
    plan: ToolActionPlan,
) -> None:
    adapter = ReadOnlyHttpToolExecutionAdapter(
        _config(), client_factory=lambda _config: pytest.fail("network must not be reached")
    )

    with pytest.raises(ValueError, match="outside"):
        adapter.execute(plan)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(307, headers={"location": "https://other.test"}), "non-success"),
        (httpx.Response(200, text="not-json"), "content type"),
        (
            httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                },
                content=gzip.compress(b"{}"),
            ),
            "content encoding",
        ),
        (
            httpx.Response(200, json={"action_id": "action-read-1", "execution_id": "read-1"}),
            "shape",
        ),
        (
            httpx.Response(
                200,
                json={
                    "action_id": "different-action",
                    "execution_id": "read-1",
                    "output": {},
                },
            ),
            "binding",
        ),
        (
            httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"action_id":"action-read-1","action_id":"duplicate",'
                b'"execution_id":"read-1","output":{}}',
            ),
            "duplicate",
        ),
    ],
)
def test_read_only_adapter_rejects_untrusted_response(
    response: httpx.Response, message: str
) -> None:
    adapter = _adapter(httpx.MockTransport(lambda _request: response))

    with pytest.raises(ValueError, match=message):
        adapter.execute(_plan())


def test_read_only_adapter_enforces_response_size_limit() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b"{" + b"x" * 128 + b"}",
    )
    adapter = ReadOnlyHttpToolExecutionAdapter(
        _config(max_response_bytes=64),
        client_factory=lambda config: httpx.Client(
            transport=httpx.MockTransport(lambda _request: response),
            timeout=config.timeout_seconds,
        ),
    )

    with pytest.raises(ValueError, match="size limit"):
        adapter.execute(_plan())
