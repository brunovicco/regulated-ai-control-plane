"""FastAPI transport and composition root for evaluation and enforcement."""

import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from regulated_ai.adapters import (
    DeterministicDataClassifier,
    FilePolicyRepository,
    FileProviderCapabilityRepository,
    GovernedGatewayExecutionAdapter,
    GovernedGatewayExecutionConfig,
    HmacTokenizationAdapter,
    MockInferenceExecutionAdapter,
    SqliteEnforcementRepository,
    SqliteEvidenceRepository,
    StructuredEvaluationObserver,
)
from regulated_ai.application import EnforceAiOperation, EvaluateAiOperation, EvaluationError
from regulated_ai.application.ports import (
    EnforcementRepository,
    EvidenceRepository,
    InferenceExecutionPort,
    ProviderCapabilityRepository,
)
from regulated_ai.domain import (
    AssuranceLevel,
    DataClassification,
    DataItem,
    EnforcementRecord,
    EnforcementResult,
    EvaluationContext,
    EvaluationResult,
    EvidenceMetadata,
    Jurisdiction,
    ProviderCallMetadata,
    ProviderTarget,
    Purpose,
    Sector,
    ToolRequest,
    TransformationReceipt,
)


class _TransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderInput(_TransportModel):
    """Provider target accepted over HTTP."""

    provider: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    service: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    region: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    model_family: str | None = Field(default=None, max_length=128)
    processing_mode: str | None = Field(default=None, max_length=64)


class DataInput(_TransportModel):
    """Ephemeral field value and caller-supplied labels."""

    field: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    value: str = Field(max_length=100_000)
    labels: tuple[DataClassification, ...] = ()


class ToolInput(_TransportModel):
    """Requested tool/action and organization-defined risk class."""

    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    risk_class: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")


class EvaluationRequest(_TransportModel):
    """Normalized Phase 1 evaluation request."""

    correlation_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    jurisdiction: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    sector: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    purpose: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    operation_kind: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    assurance_level: AssuranceLevel
    provider: ProviderInput
    data: tuple[DataInput, ...] = ()
    tools: tuple[ToolInput, ...] = ()
    policy_set_version: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._@-]+$")
    organization_assertions: dict[str, bool] = Field(default_factory=dict)
    fallback_providers: tuple[ProviderInput, ...] = ()


@dataclass(frozen=True, slots=True)
class Runtime:
    """Initialized application services exposed to transport handlers."""

    evaluator: EvaluateAiOperation
    evidence: EvidenceRepository
    capabilities: ProviderCapabilityRepository
    enforcer: EnforceAiOperation
    enforcement: EnforcementRepository
    execution: InferenceExecutionPort
    mock_execution: MockInferenceExecutionAdapter | None


def build_runtime(
    *,
    policy_paths: tuple[Path, ...] | None = None,
    capability_paths: tuple[Path, ...] | None = None,
    evidence_path: Path | None = None,
) -> Runtime:
    """Validate local control-plane files and compose the enforcement use case."""
    resource_root = resources.files("regulated_ai.resources")
    policies = FilePolicyRepository(
        policy_paths
        or (Path(str(resource_root.joinpath("policies/br-financial-external-inference.yaml"))),)
    )
    capabilities = FileProviderCapabilityRepository(
        capability_paths
        or (
            Path(str(resource_root.joinpath("provider-capabilities/openai-responses.yaml"))),
            Path(str(resource_root.joinpath("provider-capabilities/aws-bedrock.yaml"))),
        )
    )
    configured_path = os.environ.get("REGULAAI_EVIDENCE_DB")
    database_path = evidence_path or Path(configured_path or "var/regulaai-evidence.sqlite3")
    repository = SqliteEvidenceRepository(database_path)
    enforcement = SqliteEnforcementRepository(database_path)
    observer = StructuredEvaluationObserver()
    evaluator = EvaluateAiOperation(
        policies=policies,
        capabilities=capabilities,
        evidence=repository,
        classifier=DeterministicDataClassifier(),
        observer=observer,
    )
    configured_key = os.environ.get("REGULAAI_TOKENIZATION_KEY")
    tokenizer = HmacTokenizationAdapter(
        configured_key.encode() if configured_key is not None else secrets.token_bytes(32)
    )
    execution, mock_execution = _execution_adapter_from_environment()
    enforcer = EnforceAiOperation(
        evaluator=evaluator,
        tokenizer=tokenizer,
        enforcement=enforcement,
        execution=execution,
        observer=observer,
    )
    return Runtime(
        evaluator=evaluator,
        evidence=repository,
        capabilities=capabilities,
        enforcer=enforcer,
        enforcement=enforcement,
        execution=execution,
        mock_execution=mock_execution,
    )


def _execution_adapter_from_environment() -> tuple[
    InferenceExecutionPort, MockInferenceExecutionAdapter | None
]:
    mode = os.environ.get("REGULAAI_EXECUTION_MODE", "mock").strip().casefold()
    if mode == "mock":
        mock = MockInferenceExecutionAdapter()
        return mock, mock
    if mode != "gateway":
        raise ValueError("REGULAAI_EXECUTION_MODE must be 'mock' or 'gateway'")
    adapter = GovernedGatewayExecutionAdapter(
        GovernedGatewayExecutionConfig(
            base_url=_required_environment("GOVERNED_LLM_GATEWAY_URL"),
            api_key=_required_environment("GOVERNED_LLM_GATEWAY_API_KEY"),
            workload=_required_environment("REGULAAI_GATEWAY_WORKLOAD"),
            allowed_target=_required_environment("REGULAAI_GATEWAY_ALLOWED_TARGET"),
            expected_provider=_required_environment("REGULAAI_GATEWAY_EXPECTED_PROVIDER"),
            request_timeout_seconds=_float_environment(
                "REGULAAI_GATEWAY_REQUEST_TIMEOUT_SECONDS", 60.0
            ),
            provider_timeout_seconds=_float_environment(
                "REGULAAI_GATEWAY_PROVIDER_TIMEOUT_SECONDS", 30.0
            ),
            max_output_tokens=_integer_environment("REGULAAI_GATEWAY_MAX_OUTPUT_TOKENS", 2000),
            max_input_bytes=_integer_environment("REGULAAI_GATEWAY_MAX_INPUT_BYTES", 1024 * 1024),
        )
    )
    return adapter, None


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required in gateway execution mode")
    return value


def _float_environment(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _integer_environment(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def create_app(runtime_factory: Callable[[], Runtime] = build_runtime) -> FastAPI:
    """Create an API whose control-plane data is validated before serving traffic."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.runtime = runtime_factory()
        yield

    application = FastAPI(title="RegulaAI", version="0.1.0", lifespan=lifespan)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _error_response(422, "INVALID_EVALUATION_CONTEXT", "Request validation failed")

    @application.exception_handler(EvaluationError)
    async def evaluation_error(_request: Request, exc: EvaluationError) -> JSONResponse:
        if exc.code == "POLICY_SET_NOT_FOUND":
            status = 404
        elif exc.code == "INVALID_EVALUATION_CONTEXT":
            status = 422
        else:
            status = 503
        return _error_response(status, exc.code, str(exc))

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/v1/evaluations")
    def evaluate(request: EvaluationRequest) -> dict[str, object]:
        runtime = _runtime(application)
        result = runtime.evaluator.execute(_to_context(request))
        return _result_payload(result)

    @application.post("/v1/enforcements")
    def enforce(request: EvaluationRequest) -> dict[str, object]:
        result = _runtime(application).enforcer.execute(_to_context(request))
        return _enforcement_result_payload(result)

    @application.get("/v1/evidence/{evidence_id}", response_model=None)
    def get_evidence(evidence_id: str) -> JSONResponse | dict[str, object]:
        evidence = _runtime(application).evidence.get(evidence_id)
        if evidence is None:
            return _error_response(404, "EVIDENCE_NOT_FOUND", "Evidence record was not found")
        return _evidence_payload(evidence)

    @application.get("/v1/enforcements/{enforcement_id}", response_model=None)
    def get_enforcement(enforcement_id: str) -> JSONResponse | dict[str, object]:
        record = _runtime(application).enforcement.get(enforcement_id)
        if record is None:
            return _error_response(404, "ENFORCEMENT_NOT_FOUND", "Enforcement record was not found")
        return _enforcement_record_payload(record)

    @application.get("/v1/providers")
    def get_providers() -> dict[str, object]:
        registry = _runtime(application).capabilities
        return {
            "provider_registry_version": registry.registry_version,
            "providers": [
                {
                    "provider": record.target.provider,
                    "service": record.target.service,
                    "region": record.target.region,
                    "record_version": record.record_version,
                    "verified_at": record.verified_at.isoformat(),
                    "source_urls": list(record.source_urls),
                    "capabilities": [
                        {
                            "key": fact.key,
                            "state": fact.state.value,
                            "conditions": list(fact.conditions),
                        }
                        for fact in record.capabilities
                    ],
                }
                for record in registry.list()
            ],
        }

    return application


def _runtime(application: FastAPI) -> Runtime:
    runtime: Runtime = application.state.runtime
    return runtime


def _to_context(request: EvaluationRequest) -> EvaluationContext:
    provider = _to_provider(request.provider)
    return EvaluationContext(
        correlation_id=request.correlation_id,
        jurisdiction=Jurisdiction(request.jurisdiction.upper()),
        sector=Sector(request.sector.casefold()),
        purpose=Purpose(request.purpose.casefold()),
        operation_kind=request.operation_kind.casefold(),
        assurance_level=request.assurance_level,
        provider=provider,
        data_items=tuple(
            DataItem(
                field=item.field,
                value=item.value,
                supplied_labels=tuple(item.labels),
            )
            for item in request.data
        ),
        tools=tuple(
            ToolRequest(name=item.name, risk_class=item.risk_class.casefold())
            for item in request.tools
        ),
        policy_set_version=request.policy_set_version,
        organization_assertions=tuple(sorted(request.organization_assertions.items())),
        fallback_providers=tuple(_to_provider(item) for item in request.fallback_providers),
    )


def _to_provider(provider: ProviderInput) -> ProviderTarget:
    return ProviderTarget(
        provider=provider.provider.casefold(),
        service=provider.service.casefold(),
        region=None if provider.region is None else provider.region.casefold(),
        model_family=provider.model_family,
        processing_mode=provider.processing_mode,
    )


def _result_payload(result: EvaluationResult) -> dict[str, object]:
    return {
        "evaluation_id": result.evaluation_id,
        "decision": result.decision.value,
        "obligations": [
            {
                "type": obligation.type.value,
                "target": obligation.target,
                "reason_code": obligation.reason_code,
                "control_objective_ids": list(obligation.control_objective_ids),
                "parameters": dict(obligation.parameters),
            }
            for obligation in result.obligations
        ],
        "matched_policies": list(result.matched_policy_ids),
        "provider_capabilities_used": list(result.provider_capability_ids),
        "reason_codes": list(result.reason_codes),
        "policy_set_version": result.policy_set_version,
        "provider_registry_version": result.provider_registry_version,
        "evidence_id": result.evidence_id,
    }


def _evidence_payload(evidence: EvidenceMetadata) -> dict[str, object]:
    return {
        "evidence_id": evidence.evidence_id,
        "created_at": evidence.created_at.isoformat(),
        "correlation_id": evidence.correlation_id,
        "decision": evidence.decision.value,
        "classification_labels": [item.value for item in evidence.classification_labels],
        "obligation_types": [item.value for item in evidence.obligation_types],
        "matched_policies": list(evidence.matched_policy_ids),
        "provider_capabilities_used": list(evidence.provider_capability_ids),
        "control_objective_ids": list(evidence.control_objective_ids),
        "reason_codes": list(evidence.reason_codes),
        "policy_set_version": evidence.policy_set_version,
        "provider_registry_version": evidence.provider_registry_version,
        "input_digest": evidence.input_digest,
        "output_digest": evidence.output_digest,
        "event_digest": evidence.event_digest,
        "previous_event_digest": evidence.previous_event_digest,
    }


def _enforcement_result_payload(result: EnforcementResult) -> dict[str, object]:
    return {
        "enforcement_id": result.enforcement_id,
        "evaluation_id": result.evaluation_id,
        "evaluation_evidence_id": result.evaluation_evidence_id,
        "decision": result.decision.value,
        "status": result.status.value,
        "transformation_receipts": [
            _receipt_payload(item) for item in result.transformation_receipts
        ],
        "reason_codes": list(result.reason_codes),
        "output_digest": result.output_digest,
        "provider_execution_id": result.provider_execution_id,
        "provider_call_metadata": _provider_call_payload(result.provider_call_metadata),
    }


def _enforcement_record_payload(record: EnforcementRecord) -> dict[str, object]:
    result = EnforcementResult(
        enforcement_id=record.enforcement_id,
        evaluation_id=record.evaluation_id,
        evaluation_evidence_id=record.evaluation_evidence_id,
        decision=record.decision,
        status=record.status,
        transformation_receipts=record.transformation_receipts,
        reason_codes=record.reason_codes,
        output_digest=record.output_digest,
        provider_execution_id=record.provider_execution_id,
        provider_call_metadata=record.provider_call_metadata,
    )
    return {
        **_enforcement_result_payload(result),
        "created_at": record.created_at.isoformat(),
        "policy_set_version": record.policy_set_version,
        "provider_registry_version": record.provider_registry_version,
        "provider_target": record.provider_target,
        "input_digest": record.input_digest,
    }


def _receipt_payload(receipt: TransformationReceipt) -> dict[str, str]:
    return {
        "receipt_id": receipt.receipt_id,
        "type": receipt.type.value,
        "target": receipt.target,
        "input_digest": receipt.input_digest,
        "output_digest": receipt.output_digest,
        "reason_code": receipt.reason_code,
    }


def _provider_call_payload(metadata: ProviderCallMetadata | None) -> dict[str, object] | None:
    if metadata is None:
        return None
    return {
        "gateway_request_id": metadata.gateway_request_id,
        "routing_decision_id": metadata.routing_decision_id,
        "policy_id": metadata.policy_id,
        "policy_version": metadata.policy_version,
        "provider": metadata.provider,
        "model": metadata.model,
        "deployment": metadata.deployment,
        "latency_ms": metadata.latency_ms,
        "attempt_number": metadata.attempt_number,
        "fallback_index": metadata.fallback_index,
        "cached": metadata.cached,
    }


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


app = create_app()
