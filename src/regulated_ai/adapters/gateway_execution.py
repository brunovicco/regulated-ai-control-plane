"""Opt-in execution adapter for the provider-neutral Governed LLM Gateway."""

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from governed_llm_gateway_client import GatewayClient, GatewayClientConfig
from governed_llm_gateway_contracts import (
    DataClassification as GatewayDataClassification,
)
from governed_llm_gateway_contracts import (
    ExecutionStatus,
    GatewayResponse,
    Message,
    MessageRole,
    RiskLevel,
)

from regulated_ai.domain import (
    AssuranceLevel,
    DataClassification,
    ExecutionPlan,
    ProviderCallMetadata,
    ProviderExecutionReceipt,
)

_SAFE_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_SAFE_WORKLOAD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}\Z")


class _GatewayClient(Protocol):
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
        """Execute one provider-neutral request."""
        ...

    async def aclose(self) -> None:
        """Close client-owned transport resources."""
        ...


GatewayClientFactory = Callable[[GatewayClientConfig], _GatewayClient]


@dataclass(frozen=True, slots=True)
class GovernedGatewayExecutionConfig:
    """Explicit gateway binding and bounded execution limits."""

    base_url: str
    api_key: str = field(repr=False)
    workload: str
    allowed_target: str
    expected_provider: str
    request_timeout_seconds: float = 60.0
    provider_timeout_seconds: float = 30.0
    max_output_tokens: int = 2000
    max_input_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        """Reject ambiguous workload bindings and unbounded request settings."""
        if _SAFE_WORKLOAD.fullmatch(self.workload) is None:
            raise ValueError("Gateway workload is invalid")
        for name, value in (
            ("allowed target", self.allowed_target),
            ("expected provider", self.expected_provider),
        ):
            if value != value.casefold() or _SAFE_IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"Gateway {name} must be a normalized identifier")
        if self.provider_timeout_seconds <= 0 or self.provider_timeout_seconds > 300:
            raise ValueError("Gateway provider timeout must be in the range (0, 300]")
        if self.max_output_tokens <= 0 or self.max_output_tokens > 65_536:
            raise ValueError("Gateway max output tokens must be in the range [1, 65536]")
        if self.max_input_bytes <= 0 or self.max_input_bytes > 8 * 1024 * 1024:
            raise ValueError("Gateway max input bytes must be in the range [1, 8388608]")


class GovernedGatewayExecutionAdapter:
    """Execute sanitized text through one configured, provider-constrained gateway workload."""

    def __init__(
        self,
        config: GovernedGatewayExecutionConfig,
        *,
        client_factory: GatewayClientFactory | None = None,
    ) -> None:
        """Validate transport configuration without opening a network connection."""
        self._config = config
        self._client_config = GatewayClientConfig(
            base_url=config.base_url,
            api_key=config.api_key,
            request_timeout_seconds=config.request_timeout_seconds,
        )
        self._client_factory = client_factory or _default_client_factory

    def execute(self, plan: ExecutionPlan) -> ProviderExecutionReceipt:
        """Run one request with no local retry and return metadata-only provenance."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Synchronous gateway adapter cannot run inside an event loop")
        return asyncio.run(self._execute(plan))

    async def _execute(self, plan: ExecutionPlan) -> ProviderExecutionReceipt:
        if plan.provider.identifier != self._config.allowed_target:
            raise ValueError("Execution target is not bound to the configured gateway workload")
        if plan.tools:
            raise ValueError("Gateway execution does not support tool requests in this phase")
        _require_secret_transformations(plan)
        content = _message_content(plan)
        encoded = content.encode("utf-8")
        if len(encoded) > self._config.max_input_bytes:
            raise ValueError("Sanitized gateway input exceeds the configured size limit")

        request_id = uuid5(NAMESPACE_URL, plan.plan_id)
        client = self._client_factory(self._client_config)
        try:
            response = await client.generate(
                workload=self._config.workload,
                messages=(Message(role=MessageRole.USER, content=content),),
                risk_level=_risk_level(plan),
                data_classification=_data_classification(plan),
                context_tokens_estimated=max(1, (len(encoded) + 3) // 4),
                max_output_tokens=self._config.max_output_tokens,
                provider_timeout_seconds=self._config.provider_timeout_seconds,
                request_id=request_id,
            )
        finally:
            await client.aclose()
        return _receipt(response, plan, request_id, self._config.expected_provider)


def _default_client_factory(config: GatewayClientConfig) -> _GatewayClient:
    return GatewayClient(config)


def _message_content(plan: ExecutionPlan) -> str:
    return json.dumps(
        {
            "data": [
                {
                    "field": item.field,
                    "value": item.value,
                }
                for item in plan.data_items
            ],
            "operation_kind": plan.operation_kind,
            "purpose": plan.purpose,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _require_secret_transformations(plan: ExecutionPlan) -> None:
    transformed = {receipt.target for receipt in plan.transformation_receipts}
    if any(
        DataClassification.AUTHENTICATION_SECRET in item.labels and item.field not in transformed
        for item in plan.data_items
    ):
        raise ValueError("Authentication-secret input lacks a transformation receipt")


def _risk_level(plan: ExecutionPlan) -> RiskLevel:
    return {
        AssuranceLevel.LOW: RiskLevel.LOW,
        AssuranceLevel.STANDARD: RiskLevel.MEDIUM,
        AssuranceLevel.HIGH: RiskLevel.HIGH,
    }[plan.assurance_level]


def _data_classification(plan: ExecutionPlan) -> GatewayDataClassification:
    if any(item.labels for item in plan.data_items):
        return GatewayDataClassification.RESTRICTED
    return GatewayDataClassification.INTERNAL


def _receipt(
    response: GatewayResponse,
    plan: ExecutionPlan,
    request_id: UUID,
    expected_provider: str,
) -> ProviderExecutionReceipt:
    execution = response.execution
    routing = response.routing
    if (
        response.request_id != request_id
        or response.status is not ExecutionStatus.SUCCEEDED
        or response.error is not None
        or execution is None
        or not response.content
        or response.tool_calls
        or response.structured_output is not None
    ):
        raise ValueError("Gateway returned an invalid terminal response")
    if (
        execution.provider != expected_provider
        or routing.provider != execution.provider
        or routing.model != execution.model
        or routing.deployment != execution.deployment
    ):
        raise ValueError("Gateway routing would violate the configured provider boundary")
    metadata = ProviderCallMetadata(
        gateway_request_id=str(response.request_id),
        routing_decision_id=routing.routing_decision_id,
        policy_id=routing.policy.policy_id,
        policy_version=routing.policy.policy_version,
        provider=execution.provider,
        model=execution.model,
        deployment=execution.deployment,
        latency_ms=execution.latency_ms,
        attempt_number=execution.attempt_number,
        fallback_index=execution.fallback_index,
        cached=execution.cached,
    )
    return ProviderExecutionReceipt(
        execution_id=f"gw_{response.request_id.hex}",
        provider_target=plan.provider.identifier,
        plan_id=plan.plan_id,
        output_digest=plan.output_digest,
        call_metadata=metadata,
    )
