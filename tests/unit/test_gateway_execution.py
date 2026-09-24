import json
from collections.abc import Sequence
from uuid import UUID

import pytest
from governed_llm_gateway_client import GatewayClientConfig, GatewayConfigurationError
from governed_llm_gateway_contracts import (
    DataClassification as GatewayDataClassification,
)
from governed_llm_gateway_contracts import (
    ExecutionStatus,
    GatewayResponse,
    Message,
    PolicyProvenance,
    ProviderExecution,
    RiskLevel,
    RoutingProvenance,
)

from regulated_ai.adapters.gateway_execution import (
    GovernedGatewayExecutionAdapter,
    GovernedGatewayExecutionConfig,
)
from regulated_ai.domain import (
    AssuranceLevel,
    DataClassification,
    DataItem,
    ExecutionPlan,
    ObligationType,
    ProviderTarget,
    ToolRequest,
    TransformationReceipt,
)


class FakeGatewayClient:
    def __init__(self, *, provider: str = "openai", succeeded: bool = True) -> None:
        self.provider = provider
        self.succeeded = succeeded
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def generate(
        self,
        *,
        workload: str,
        messages: Sequence[Message],
        risk_level: RiskLevel,
        data_classification: GatewayDataClassification,
        context_tokens_estimated: int,
        max_output_tokens: int,
        provider_timeout_seconds: float,
        request_id: UUID,
    ) -> GatewayResponse:
        self.calls.append(
            {
                "workload": workload,
                "messages": tuple(messages),
                "risk_level": risk_level,
                "data_classification": data_classification,
                "context_tokens_estimated": context_tokens_estimated,
                "max_output_tokens": max_output_tokens,
                "provider_timeout_seconds": provider_timeout_seconds,
                "request_id": request_id,
            }
        )
        policy = PolicyProvenance(
            decision_id="decision_1",
            policy_id="gateway.policy",
            policy_version="1.0",
            policy_digest="sha256:policy",
        )
        routing = RoutingProvenance(
            routing_decision_id="route_1",
            policy=policy,
            authorized_model_group="balanced",
            model_registry_digest="sha256:registry",
            ranking_policy_version="ranking@1",
            provider=self.provider,
            model="gpt-test",
            deployment="openai-test",
        )
        execution = ProviderExecution(
            provider=self.provider,
            model="gpt-test",
            deployment="openai-test",
            status=ExecutionStatus.SUCCEEDED,
            latency_ms=25,
            attempt_number=2,
            fallback_index=1,
        )
        return GatewayResponse(
            request_id=request_id,
            status=ExecutionStatus.SUCCEEDED if self.succeeded else ExecutionStatus.FAILED,
            content="ephemeral response" if self.succeeded else None,
            routing=routing,
            execution=execution if self.succeeded else None,
        )

    async def aclose(self) -> None:
        self.closed = True


def _config(**changes: object) -> GovernedGatewayExecutionConfig:
    values: dict[str, object] = {
        "base_url": "https://gateway.example.test",
        "api_key": "synthetic-gateway-credential",
        "workload": "regulated-ai.external-inference",
        "allowed_target": "openai.responses_api.global",
        "expected_provider": "openai",
    }
    values.update(changes)
    return GovernedGatewayExecutionConfig(**values)  # type: ignore[arg-type]


def _plan(
    *,
    tools: tuple[ToolRequest, ...] = (),
    secret_receipt: bool = True,
) -> ExecutionPlan:
    receipt = TransformationReceipt(
        receipt_id="tr_test",
        type=ObligationType.TOKENIZE,
        target="customer_document",
        input_digest="sha256:input",
        output_digest="sha256:output",
        reason_code="MINIMIZE",
    )
    return ExecutionPlan(
        plan_id="plan_test",
        evaluation_id="eval_test",
        decision_digest="sha256:decision",
        operation_kind="external_inference",
        purpose="customer_support",
        assurance_level=AssuranceLevel.HIGH,
        provider=ProviderTarget("openai", "responses_api", "global"),
        data_items=(
            DataItem(
                field="customer_document",
                value="tok_sanitized",
                supplied_labels=(DataClassification.AUTHENTICATION_SECRET,),
            ),
        ),
        tools=tools,
        transformation_receipts=(receipt,) if secret_receipt else (),
        output_digest="sha256:plan-output",
    )


def test_gateway_adapter_sends_only_sanitized_text_and_returns_metadata() -> None:
    fake = FakeGatewayClient()
    client_configs: list[GatewayClientConfig] = []

    def factory(config: GatewayClientConfig) -> FakeGatewayClient:
        client_configs.append(config)
        return fake

    adapter = GovernedGatewayExecutionAdapter(_config(), client_factory=factory)

    receipt = adapter.execute(_plan())

    assert len(fake.calls) == 1
    call = fake.calls[0]
    messages = call["messages"]
    assert isinstance(messages, tuple)
    message = messages[0]
    assert isinstance(message, Message)
    payload = json.loads(message.content)
    assert payload["data"] == [{"field": "customer_document", "value": "tok_sanitized"}]
    assert call["risk_level"] is RiskLevel.HIGH
    assert call["data_classification"] is GatewayDataClassification.RESTRICTED
    assert call["provider_timeout_seconds"] == 30.0
    assert call["max_output_tokens"] == 2000
    assert client_configs[0].request_timeout_seconds == 60.0
    assert fake.closed
    assert receipt.execution_id.startswith("gw_")
    assert receipt.call_metadata is not None
    assert receipt.call_metadata.provider == "openai"
    assert receipt.call_metadata.fallback_index == 1
    assert "ephemeral response" not in repr(receipt)


@pytest.mark.parametrize(
    "plan",
    [
        _plan(tools=(ToolRequest("cards.read", "read_only"),)),
        _plan(secret_receipt=False),
    ],
)
def test_gateway_adapter_rejects_unsupported_plan_before_client_creation(
    plan: ExecutionPlan,
) -> None:
    created = False

    def factory(_config: GatewayClientConfig) -> FakeGatewayClient:
        nonlocal created
        created = True
        return FakeGatewayClient()

    adapter = GovernedGatewayExecutionAdapter(_config(), client_factory=factory)

    with pytest.raises(ValueError):
        adapter.execute(plan)

    assert not created


def test_gateway_adapter_fails_closed_on_provider_downgrade() -> None:
    fake = FakeGatewayClient(provider="aws")
    adapter = GovernedGatewayExecutionAdapter(_config(), client_factory=lambda _config: fake)

    with pytest.raises(ValueError, match="provider boundary"):
        adapter.execute(_plan())

    assert fake.closed


def test_gateway_adapter_validates_connection_configuration_without_network() -> None:
    config = _config(base_url="http://gateway.example.test")

    with pytest.raises(GatewayConfigurationError):
        GovernedGatewayExecutionAdapter(config)

    assert "synthetic-gateway-credential" not in repr(config)
