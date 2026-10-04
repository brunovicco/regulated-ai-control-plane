import gzip
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from regulated_ai.adapters import (
    StateChangingHttpToolExecutionAdapter,
    StateChangingHttpToolExecutionConfig,
)
from regulated_ai.domain import ActionApprovalReceipt, ToolActionPlan

from ..helpers import authorized_tool

_IDEMPOTENCY_KEY = "idempotency-unblock-1"
_IDEMPOTENCY_DIGEST = f"sha256:{hashlib.sha256(_IDEMPOTENCY_KEY.encode()).hexdigest()}"


def _plan() -> ToolActionPlan:
    now = datetime(2026, 9, 29, 12, tzinfo=UTC)
    return ToolActionPlan(
        action_id="action-unblock-1",
        action_digest=f"sha256:{'2' * 64}",
        enforcement_id="enforcement-unblock-1",
        call_id="call-unblock-1",
        tool=authorized_tool("cards.unblock", "high_impact_state_change"),
        workload_identity="workload.cards-unblock-sandbox",
        idempotency_key=_IDEMPOTENCY_KEY,
        arguments=(
            ("account_token", "tok_synthetic"),
            ("reason_code", "CUSTOMER_VERIFIED"),
        ),
        approval_receipt=ActionApprovalReceipt(
            approval_id="approval-unblock-1",
            actor_id="reviewer-synthetic",
            action_digest=f"sha256:{'2' * 64}",
            action_id="action-unblock-1",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            consumed_at=now,
        ),
    )


def _config(**changes: object) -> StateChangingHttpToolExecutionConfig:
    values: dict[str, object] = {
        "endpoint_url": "https://cards-sandbox.example.test/v1/card-unblocks",
        "api_key": "synthetic-state-change-credential",
        "workload_identity": "workload.cards-unblock-sandbox",
    }
    values.update(changes)
    return StateChangingHttpToolExecutionConfig(**values)  # type: ignore[arg-type]


def _adapter(handler: httpx.MockTransport) -> StateChangingHttpToolExecutionAdapter:
    return StateChangingHttpToolExecutionAdapter(
        _config(),
        client_factory=lambda config: httpx.Client(
            transport=handler,
            timeout=config.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ),
    )


def test_state_changing_adapter_sends_one_bound_idempotent_request() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        assert str(request.url) == "https://cards-sandbox.example.test/v1/card-unblocks"
        assert request.headers["authorization"] == "Bearer synthetic-state-change-credential"
        assert request.headers["idempotency-key"] == _IDEMPOTENCY_KEY
        assert _IDEMPOTENCY_KEY.encode() not in request.content
        assert json.loads(request.content) == {
            "action_id": "action-unblock-1",
            "action_digest": f"sha256:{'2' * 64}",
            "arguments": {
                "account_token": "tok_synthetic",
                "reason_code": "CUSTOMER_VERIFIED",
            },
            "idempotency_key_digest": _IDEMPOTENCY_DIGEST,
            "tool": "cards.unblock",
            "workload_identity": "workload.cards-unblock-sandbox",
        }
        return httpx.Response(
            200,
            json={
                "action_id": "action-unblock-1",
                "action_digest": f"sha256:{'2' * 64}",
                "execution_id": "sandbox-unblock-1",
                "idempotency_key_digest": _IDEMPOTENCY_DIGEST,
                "output": {
                    "operation_status": "SUCCEEDED",
                    "operation_reference": "synthetic-operation-reference",
                    "diagnostic": "synthetic-diagnostic",
                },
            },
        )

    result = _adapter(httpx.MockTransport(handle)).execute(_plan())

    assert calls == 1
    assert result.receipt.execution_id == "sandbox-unblock-1"
    assert result.receipt.action_id == "action-unblock-1"
    assert result.output == {
        "operation_status": "SUCCEEDED",
        "operation_reference": "synthetic-operation-reference",
        "diagnostic": "synthetic-diagnostic",
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://cards.example.test/v1/unblock",
        "http://localhost/v1/unblock",
        "ftp://cards.example.test/v1/unblock",
        "https://user@cards.example.test/v1/unblock",
        "https://cards.example.test/v1/unblock?target=other",
        "https://cards.example.test/v1/unblock#fragment",
        "https://cards.example.test",
        "https://cards.example.test/v1/unblock\nunsafe",
    ],
)
def test_state_changing_config_rejects_unsafe_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        _config(endpoint_url=endpoint)


def test_state_changing_config_accepts_loopback_http_and_hides_secret() -> None:
    config = _config(endpoint_url="http://127.0.0.1:9000/v1/unblock")

    assert "synthetic-state-change-credential" not in repr(config)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"api_key": "unsafe\x00credential"}, "API key"),
        ({"workload_identity": "unsafe workload"}, "workload identity"),
        ({"timeout_seconds": 0}, "timeout"),
        ({"timeout_seconds": 61}, "timeout"),
        ({"max_request_bytes": 0}, "request limit"),
        ({"max_response_bytes": 1024 * 1024 + 1}, "response limit"),
    ],
)
def test_state_changing_config_rejects_unsafe_bounds(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _config(**changes)


@pytest.mark.parametrize(
    "plan",
    [
        replace(_plan(), tool=authorized_tool("cards.read", "read_only")),
        replace(_plan(), workload_identity="workload.other-sandbox"),
        replace(_plan(), tool=authorized_tool("cards.unblock", "read_only")),
        replace(_plan(), idempotency_key="unsafe\nkey"),
        replace(_plan(), action_digest="invalid"),
    ],
)
def test_state_changing_adapter_rejects_out_of_scope_plan_before_network(
    plan: ToolActionPlan,
) -> None:
    adapter = StateChangingHttpToolExecutionAdapter(
        _config(), client_factory=lambda _config: pytest.fail("network must not be reached")
    )

    with pytest.raises(ValueError, match="outside"):
        adapter.execute(plan)


def test_state_changing_adapter_enforces_request_size_limit() -> None:
    adapter = StateChangingHttpToolExecutionAdapter(
        _config(max_request_bytes=64),
        client_factory=lambda _config: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ValueError, match="request exceeds"):
        adapter.execute(_plan())


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(307, headers={"location": "https://other.test"}), "non-success"),
        (httpx.Response(200, text="not-json"), "content type"),
        (
            httpx.Response(
                200,
                headers={"content-type": "application/json", "content-encoding": "gzip"},
                content=gzip.compress(b"{}"),
            ),
            "content encoding",
        ),
        (
            httpx.Response(
                200,
                json={
                    "action_id": "action-unblock-1",
                    "action_digest": f"sha256:{'0' * 64}",
                    "execution_id": "unblock-1",
                    "idempotency_key_digest": _IDEMPOTENCY_DIGEST,
                    "output": {},
                },
            ),
            "binding",
        ),
        (
            httpx.Response(
                200,
                json={
                    "action_id": "action-unblock-1",
                    "action_digest": f"sha256:{'2' * 64}",
                    "execution_id": "unblock-1",
                    "output": {},
                },
            ),
            "shape",
        ),
        (
            httpx.Response(
                200,
                json={
                    "action_id": "different-action",
                    "action_digest": f"sha256:{'2' * 64}",
                    "execution_id": "unblock-1",
                    "idempotency_key_digest": _IDEMPOTENCY_DIGEST,
                    "output": {},
                },
            ),
            "binding",
        ),
        (
            httpx.Response(
                200,
                json={
                    "action_id": "action-unblock-1",
                    "action_digest": f"sha256:{'2' * 64}",
                    "execution_id": "unblock-1",
                    "idempotency_key_digest": f"sha256:{'0' * 64}",
                    "output": {},
                },
            ),
            "binding",
        ),
        (
            httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"action_id":"action-unblock-1","action_id":"duplicate",'
                b'"action_digest":"sha256:'
                + b"2" * 64
                + b'","execution_id":"unblock-1","idempotency_key_digest":"'
                + _IDEMPOTENCY_DIGEST.encode()
                + b'","output":{}}',
            ),
            "duplicate",
        ),
    ],
)
def test_state_changing_adapter_rejects_untrusted_response(
    response: httpx.Response, message: str
) -> None:
    adapter = _adapter(httpx.MockTransport(lambda _request: response))

    with pytest.raises(ValueError, match=message):
        adapter.execute(_plan())


def test_state_changing_adapter_enforces_response_size_limit() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b"{" + b"x" * 128 + b"}",
    )
    adapter = StateChangingHttpToolExecutionAdapter(
        _config(max_response_bytes=64),
        client_factory=lambda config: httpx.Client(
            transport=httpx.MockTransport(lambda _request: response),
            timeout=config.timeout_seconds,
        ),
    )

    with pytest.raises(ValueError, match="size limit"):
        adapter.execute(_plan())
