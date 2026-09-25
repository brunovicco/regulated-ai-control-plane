"""FastAPI transport and composition root for evaluation and enforcement."""

import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from regulated_ai.adapters import (
    DeterministicDataClassifier,
    FilePolicyRepository,
    FileProviderCapabilityRepository,
    FileToolCatalogRepository,
    GovernedGatewayExecutionAdapter,
    GovernedGatewayExecutionConfig,
    HmacActionApprovalAdapter,
    HmacApprovalAdapter,
    HmacTokenizationAdapter,
    MockInferenceExecutionAdapter,
    MockToolExecutionAdapter,
    SqliteEnforcementRepository,
    SqliteEvidenceRepository,
    SqliteOperatorLifecycleEventRepository,
    SqliteToolActionRepository,
    StructuredEvaluationObserver,
)
from regulated_ai.application import (
    EnforceAiOperation,
    EvaluateAiOperation,
    EvaluationError,
    ExecuteToolAction,
    GetOperatorTimeline,
    OperatorTimelineIntegrityError,
    OperatorTimelineNotFoundError,
)
from regulated_ai.application.ports import (
    EnforcementRepository,
    EvidenceRepository,
    InferenceExecutionPort,
    OperatorLifecycleEventRepository,
    ProviderCapabilityRepository,
    ToolActionRepository,
    ToolExecutionPort,
)
from regulated_ai.domain import (
    ActionApprovalReceipt,
    ApprovalReceipt,
    AssuranceLevel,
    DataClassification,
    DataItem,
    EnforcementRecord,
    EnforcementResult,
    EvaluationContext,
    EvaluationResult,
    EvidenceMetadata,
    Jurisdiction,
    OperatorTimeline,
    ProviderCallMetadata,
    ProviderCapabilitySnapshot,
    ProviderTarget,
    Purpose,
    Sector,
    ToolActionRecord,
    ToolActionResult,
    ToolProposal,
    ToolRequest,
    TransformationReceipt,
)
from regulated_ai.entrypoints.operator_dashboard import (
    dashboard_headers,
    operator_dashboard_css,
    render_operator_dashboard,
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
    """Requested tool name plus an optional claim checked against trusted control-plane data."""

    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    risk_class: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$"
    )


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


class EnforcementRequest(EvaluationRequest):
    """Evaluation context plus ephemeral externally issued approval authority."""

    approval_assertion: SecretStr | None = Field(default=None, min_length=1, max_length=4096)


ToolArgumentValue = Annotated[str, Field(strict=True, max_length=4096)]


class ToolActionRequest(_TransportModel):
    """Ephemeral exact arguments plus downstream authority context."""

    call_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")
    arguments: dict[str, ToolArgumentValue] = Field(max_length=128)
    workload_identity: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$"
    )
    idempotency_key: SecretStr = Field(min_length=1, max_length=256)
    approval_assertion: SecretStr | None = Field(default=None, min_length=1, max_length=4096)


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
    action_executor: ExecuteToolAction
    actions: ToolActionRepository
    lifecycle_events: OperatorLifecycleEventRepository
    operator_timeline: GetOperatorTimeline
    tool_execution: ToolExecutionPort
    mock_tool_execution: MockToolExecutionAdapter


def build_runtime(
    *,
    policy_paths: tuple[Path, ...] | None = None,
    capability_paths: tuple[Path, ...] | None = None,
    tool_catalog_path: Path | None = None,
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
    tools = FileToolCatalogRepository(
        tool_catalog_path or Path(str(resource_root.joinpath("tools/br-financial-tools.yaml")))
    )
    configured_path = os.environ.get("REGULAAI_EVIDENCE_DB")
    database_path = evidence_path or Path(configured_path or "var/regulaai-evidence.sqlite3")
    repository = SqliteEvidenceRepository(database_path)
    enforcement = SqliteEnforcementRepository(database_path)
    actions = SqliteToolActionRepository(database_path)
    lifecycle_events = SqliteOperatorLifecycleEventRepository(database_path)
    observer = StructuredEvaluationObserver()
    evaluator = EvaluateAiOperation(
        policies=policies,
        capabilities=capabilities,
        evidence=repository,
        classifier=DeterministicDataClassifier(),
        tools=tools,
        observer=observer,
    )
    configured_key = os.environ.get("REGULAAI_TOKENIZATION_KEY")
    tokenizer = HmacTokenizationAdapter(
        configured_key.encode() if configured_key is not None else secrets.token_bytes(32)
    )
    execution, mock_execution = _execution_adapter_from_environment()
    configured_approval_key = os.environ.get("REGULAAI_APPROVAL_HMAC_KEY")
    approval = (
        None
        if configured_approval_key is None
        else HmacApprovalAdapter(
            database_path,
            configured_approval_key.encode(),
            max_lifetime_seconds=_integer_environment(
                "REGULAAI_APPROVAL_MAX_LIFETIME_SECONDS", 3600
            ),
        )
    )
    enforcer = EnforceAiOperation(
        evaluator=evaluator,
        tokenizer=tokenizer,
        enforcement=enforcement,
        execution=execution,
        approval=approval,
        observer=observer,
    )
    configured_action_approval_key = os.environ.get("REGULAAI_ACTION_APPROVAL_HMAC_KEY")
    if (
        configured_action_approval_key is not None
        and configured_action_approval_key == configured_approval_key
    ):
        raise ValueError("Decision and action approval HMAC keys must differ")
    action_approval = (
        None
        if configured_action_approval_key is None
        else HmacActionApprovalAdapter(
            database_path,
            configured_action_approval_key.encode(),
            max_lifetime_seconds=_integer_environment(
                "REGULAAI_ACTION_APPROVAL_MAX_LIFETIME_SECONDS", 3600
            ),
        )
    )
    mock_tool_execution = MockToolExecutionAdapter()
    action_executor = ExecuteToolAction(
        enforcement=enforcement,
        evidence=repository,
        tools=tools,
        actions=actions,
        execution=mock_tool_execution,
        approval=action_approval,
        observer=observer,
    )
    operator_timeline = GetOperatorTimeline(
        evidence=repository,
        enforcement=enforcement,
        actions=actions,
        events=lifecycle_events,
    )
    return Runtime(
        evaluator=evaluator,
        evidence=repository,
        capabilities=capabilities,
        enforcer=enforcer,
        enforcement=enforcement,
        execution=execution,
        mock_execution=mock_execution,
        action_executor=action_executor,
        actions=actions,
        lifecycle_events=lifecycle_events,
        operator_timeline=operator_timeline,
        tool_execution=mock_tool_execution,
        mock_tool_execution=mock_tool_execution,
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
        elif exc.code in {
            "ACTION_APPROVAL_FAILED",
            "APPROVAL_FAILED",
            "TOOL_NOT_AUTHORIZED",
        }:
            status = 403
        elif exc.code in {"OPERATOR_TIMELINE_NOT_FOUND", "TOOL_ACTION_NOT_FOUND"}:
            status = 404
        elif exc.code == "INVALID_TOOL_ACTION":
            status = 422
        elif exc.code == "TOOL_ACTION_CONFLICT":
            status = 409
        elif exc.code == "TOOL_RESULT_REJECTED":
            status = 502
        else:
            status = 503
        return _error_response(status, exc.code, str(exc))

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/operator/assets/dashboard.css", response_class=Response)
    def operator_stylesheet() -> Response:
        return Response(
            content=operator_dashboard_css(),
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
        )

    @application.get("/operator", response_class=HTMLResponse)
    def operator_dashboard(enforcement_id: str | None = None) -> HTMLResponse:
        selected = "" if enforcement_id is None else enforcement_id.strip()
        displayed = selected if len(selected) <= 128 else ""
        if not selected:
            return HTMLResponse(
                render_operator_dashboard(enforcement_id=displayed),
                headers=dashboard_headers(),
            )
        try:
            timeline = _runtime(application).operator_timeline.execute(selected)
        except OperatorTimelineNotFoundError:
            return HTMLResponse(
                render_operator_dashboard(enforcement_id=displayed, error="not_found"),
                status_code=404,
                headers=dashboard_headers(),
            )
        except OperatorTimelineIntegrityError:
            return HTMLResponse(
                render_operator_dashboard(enforcement_id=displayed, error="unavailable"),
                status_code=503,
                headers=dashboard_headers(),
            )
        return HTMLResponse(
            render_operator_dashboard(timeline, enforcement_id=displayed),
            headers=dashboard_headers(),
        )

    @application.post("/v1/evaluations")
    def evaluate(request: EvaluationRequest) -> dict[str, object]:
        runtime = _runtime(application)
        result = runtime.evaluator.execute(_to_context(request))
        return _result_payload(result)

    @application.post("/v1/enforcements")
    def enforce(request: EnforcementRequest) -> dict[str, object]:
        assertion = (
            None
            if request.approval_assertion is None
            else request.approval_assertion.get_secret_value()
        )
        result = _runtime(application).enforcer.execute(
            _to_context(request), approval_assertion=assertion
        )
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

    @application.post("/v1/enforcements/{enforcement_id}/tool-actions")
    def execute_tool_action(enforcement_id: str, request: ToolActionRequest) -> dict[str, object]:
        assertion = (
            None
            if request.approval_assertion is None
            else request.approval_assertion.get_secret_value()
        )
        result = _runtime(application).action_executor.execute(
            enforcement_id=enforcement_id,
            call_id=request.call_id,
            arguments=request.arguments,
            workload_identity=request.workload_identity,
            idempotency_key=request.idempotency_key.get_secret_value(),
            approval_assertion=assertion,
        )
        return _tool_action_result_payload(result)

    @application.get("/v1/tool-actions/{action_id}", response_model=None)
    def get_tool_action(action_id: str) -> JSONResponse | dict[str, object]:
        record = _runtime(application).actions.get(action_id)
        if record is None:
            return _error_response(404, "TOOL_ACTION_NOT_FOUND", "Tool action was not found")
        return _tool_action_record_payload(record)

    @application.get("/v1/operator/enforcements/{enforcement_id}/timeline", response_model=None)
    def get_operator_timeline(enforcement_id: str) -> dict[str, object]:
        timeline = _runtime(application).operator_timeline.execute(enforcement_id)
        return _operator_timeline_payload(timeline)

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
            ToolRequest(
                name=item.name,
                claimed_risk_class=(
                    None if item.risk_class is None else item.risk_class.casefold()
                ),
            )
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
        "tool_catalog_version": result.tool_catalog_version,
        "authorized_tools": [item.identifier for item in result.authorized_tools],
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
        "provider_capability_snapshots": [
            _provider_capability_snapshot_payload(item)
            for item in evidence.provider_capability_snapshots
        ],
        "provider_context_complete": {
            item.capability_id for item in evidence.provider_capability_snapshots
        }
        == set(evidence.provider_capability_ids),
        "control_objective_ids": list(evidence.control_objective_ids),
        "reason_codes": list(evidence.reason_codes),
        "policy_set_version": evidence.policy_set_version,
        "provider_registry_version": evidence.provider_registry_version,
        "input_digest": evidence.input_digest,
        "output_digest": evidence.output_digest,
        "event_digest": evidence.event_digest,
        "previous_event_digest": evidence.previous_event_digest,
        "tool_catalog_version": evidence.tool_catalog_version,
        "authorized_tools": list(evidence.authorized_tool_ids),
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
        "approval_receipt": _approval_receipt_payload(result.approval_receipt),
        "tool_proposals": [_tool_proposal_payload(item) for item in result.tool_proposals],
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
        approval_receipt=record.approval_receipt,
        tool_proposals=record.tool_proposals,
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


def _approval_receipt_payload(receipt: ApprovalReceipt | None) -> dict[str, object] | None:
    if receipt is None:
        return None
    return {
        "approval_id": receipt.approval_id,
        "actor_id": receipt.actor_id,
        "decision_digest": receipt.decision_digest,
        "enforcement_id": receipt.enforcement_id,
        "issued_at": receipt.issued_at.isoformat(),
        "expires_at": receipt.expires_at.isoformat(),
        "consumed_at": receipt.consumed_at.isoformat(),
    }


def _tool_proposal_payload(proposal: ToolProposal) -> dict[str, object]:
    return {
        "call_id": proposal.call_id,
        "tool_name": proposal.tool_name,
        "tool_schema_version": proposal.tool_schema_version,
        "tool_schema_digest": proposal.tool_schema_digest,
        "arguments_digest": proposal.arguments_digest,
        "execution_authorized": False,
    }


def _tool_action_result_payload(result: ToolActionResult) -> dict[str, object]:
    return {
        "action_id": result.action_id,
        "enforcement_id": result.enforcement_id,
        "call_id": result.call_id,
        "tool_name": result.tool_name,
        "workload_identity": result.workload_identity,
        "action_digest": result.action_digest,
        "status": result.status.value,
        "output_schema_digest": result.output_schema_digest,
        "approval_receipt": _action_approval_receipt_payload(result.approval_receipt),
        "tool_execution_id": result.tool_execution_id,
        "output_digest": result.output_digest,
        "safe_output_digest": result.safe_output_digest,
        "result_classifications": [item.value for item in result.result_classifications],
        "exposed_result_fields": list(result.exposed_result_fields),
        "safe_result": None if result.safe_output is None else dict(result.safe_output),
    }


def _tool_action_record_payload(record: ToolActionRecord) -> dict[str, object]:
    result = ToolActionResult(
        action_id=record.action_id,
        enforcement_id=record.enforcement_id,
        call_id=record.call_id,
        tool_name=record.tool_name,
        workload_identity=record.workload_identity,
        action_digest=record.action_digest,
        status=record.status,
        output_schema_digest=record.output_schema_digest,
        approval_receipt=record.approval_receipt,
        tool_execution_id=record.tool_execution_id,
        output_digest=record.output_digest,
        safe_output_digest=record.safe_output_digest,
        result_classifications=record.result_classifications,
        exposed_result_fields=record.exposed_result_fields,
    )
    return {
        **_tool_action_result_payload(result),
        "created_at": record.created_at.isoformat(),
        "evaluation_id": record.evaluation_id,
        "tool_schema_version": record.tool_schema_version,
        "tool_schema_digest": record.tool_schema_digest,
        "arguments_digest": record.arguments_digest,
        "idempotency_key_digest": record.idempotency_key_digest,
    }


def _operator_timeline_payload(timeline: OperatorTimeline) -> dict[str, object]:
    return {
        "timeline_version": "1",
        "enforcement_id": timeline.enforcement_id,
        "evaluation_id": timeline.evaluation_id,
        "evidence_id": timeline.evidence_id,
        "correlation_id": timeline.correlation_id,
        "policy_set_version": timeline.policy_set_version,
        "provider_registry_version": timeline.provider_registry_version,
        "tool_catalog_version": timeline.tool_catalog_version,
        "classification_labels": [item.value for item in timeline.classification_labels],
        "obligation_types": [item.value for item in timeline.obligation_types],
        "matched_policy_ids": list(timeline.matched_policy_ids),
        "provider_capability_ids": list(timeline.provider_capability_ids),
        "provider_capability_snapshots": [
            _provider_capability_snapshot_payload(item)
            for item in timeline.provider_capability_snapshots
        ],
        "provider_context_complete": timeline.provider_context_complete,
        "control_objective_ids": list(timeline.control_objective_ids),
        "decision_reason_codes": list(timeline.decision_reason_codes),
        "enforcement_reason_codes": list(timeline.enforcement_reason_codes),
        "authorized_tool_ids": list(timeline.authorized_tool_ids),
        "provider_target": timeline.provider_target,
        "transformation_receipts": [
            _receipt_payload(item) for item in timeline.transformation_receipts
        ],
        "approval": (
            None
            if timeline.approval is None
            else {
                "approval_id": timeline.approval.approval_id,
                "issued_at": timeline.approval.issued_at.isoformat(),
                "expires_at": timeline.approval.expires_at.isoformat(),
                "consumed_at": timeline.approval.consumed_at.isoformat(),
            }
        ),
        "input_digest": timeline.input_digest,
        "output_digest": timeline.output_digest,
        "event_digest": timeline.event_digest,
        "previous_event_digest": timeline.previous_event_digest,
        "attention_required": bool(timeline.attention_codes),
        "attention_codes": [item.value for item in timeline.attention_codes],
        "history_complete": timeline.history_complete,
        "actions_truncated": timeline.actions_truncated,
        "events_truncated": timeline.events_truncated,
        "stages": [
            {
                "sequence": stage.sequence,
                "kind": stage.kind.value,
                "record_id": stage.record_id,
                "created_at": stage.created_at.isoformat(),
                "status": stage.status,
                "attention_codes": [item.value for item in stage.attention_codes],
                "tool_name": stage.tool_name,
                "call_id": stage.call_id,
                "approval_recorded": stage.approval_recorded,
            }
            for stage in timeline.stages
        ],
        "lifecycle_events": [
            {
                "sequence": event.sequence,
                "event_id": event.event_id,
                "recorded_at": event.recorded_at.isoformat(),
                "source": event.source.value,
                "kind": event.kind.value,
                "record_id": event.record_id,
                "enforcement_id": event.enforcement_id,
                "status": event.status,
            }
            for event in timeline.lifecycle_events
        ],
    }


def _provider_capability_snapshot_payload(
    snapshot: ProviderCapabilitySnapshot,
) -> dict[str, object]:
    return {
        "capability_id": snapshot.capability_id,
        "provider_target": snapshot.provider_target,
        "key": snapshot.key,
        "state": snapshot.state.value,
        "conditions": list(snapshot.conditions),
        "verified_at": snapshot.verified_at.isoformat(),
        "record_version": snapshot.record_version,
        "registry_version": snapshot.registry_version,
        "source_urls": list(snapshot.source_urls),
    }


def _action_approval_receipt_payload(
    receipt: ActionApprovalReceipt | None,
) -> dict[str, object] | None:
    if receipt is None:
        return None
    return {
        "approval_id": receipt.approval_id,
        "actor_id": receipt.actor_id,
        "action_digest": receipt.action_digest,
        "action_id": receipt.action_id,
        "issued_at": receipt.issued_at.isoformat(),
        "expires_at": receipt.expires_at.isoformat(),
        "consumed_at": receipt.consumed_at.isoformat(),
    }


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


app = create_app()
