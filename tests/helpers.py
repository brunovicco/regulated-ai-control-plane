"""Synthetic-safe builders shared by behavior tests."""

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta

from regulated_ai.application.ports import EvaluationObserver
from regulated_ai.domain import (
    AssuranceLevel,
    AuthorizedTool,
    CapabilityState,
    DataItem,
    EnforcementRecord,
    EnforcementStatus,
    EvaluationContext,
    EvidenceMetadata,
    Jurisdiction,
    PolicySet,
    ProviderCapability,
    ProviderCapabilityRecord,
    ProviderTarget,
    Purpose,
    Sector,
    ToolRequest,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def approval_assertion(
    key: bytes,
    decision_digest: str,
    *,
    approval_id: str = "approval-test-1",
    actor_id: str = "approver-test-1",
    issued_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> str:
    """Issue a synthetic external assertion for boundary tests only."""
    payload = json.dumps(
        {
            "actor_id": actor_id,
            "approval_id": approval_id,
            "decision_digest": decision_digest,
            "expires_at": int((expires_at or issued_at + timedelta(minutes=5)).timestamp()),
            "issued_at": int(issued_at.timestamp()),
            "schema_version": "1",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    segment = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signed = f"ra1.{segment}"
    signature = base64.urlsafe_b64encode(
        hmac.new(key, signed.encode(), hashlib.sha256).digest()
    ).rstrip(b"=")
    return f"{signed}.{signature.decode()}"


def synthetic_cpf() -> str:
    """Build a checksum-valid synthetic identifier without a copied fixture value."""
    base = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    first = _digit(base, tuple(range(10, 1, -1)))
    second = _digit([*base, first], tuple(range(11, 1, -1)))
    return "".join(str(value) for value in (*base, first, second))


def synthetic_cnpj() -> str:
    """Build a checksum-valid synthetic company identifier."""
    base = [1, 2, 3, 4, 5, 6, 7, 8, 0, 0, 0, 1]
    first = _digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    second = _digit([*base, first], (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return "".join(str(value) for value in (*base, first, second))


def _digit(numbers: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(value * weight for value, weight in zip(numbers, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


class MemoryEvidenceRepository:
    """In-memory metadata-only evidence fake."""

    def __init__(self) -> None:
        self.items: dict[str, EvidenceMetadata] = {}

    def save(self, evidence: EvidenceMetadata) -> EvidenceMetadata:
        self.items.setdefault(evidence.evidence_id, evidence)
        return self.items[evidence.evidence_id]

    def get(self, evidence_id: str) -> EvidenceMetadata | None:
        return self.items.get(evidence_id)


class MemoryEnforcementRepository:
    """In-memory metadata-only enforcement fake."""

    def __init__(self) -> None:
        self.items: dict[str, EnforcementRecord] = {}
        self.saved_statuses: list[str] = []

    def save(self, record: EnforcementRecord) -> EnforcementRecord:
        existing = self.items.get(record.enforcement_id)
        if existing is not None:
            if existing.status in {
                EnforcementStatus.EXECUTED,
                EnforcementStatus.APPROVAL_FAILED,
                EnforcementStatus.EXECUTION_FAILED,
            }:
                return existing
            if existing.status is EnforcementStatus.DISPATCHED and record.status not in {
                EnforcementStatus.EXECUTED,
                EnforcementStatus.APPROVAL_FAILED,
                EnforcementStatus.EXECUTION_FAILED,
            }:
                return existing
        self.items[record.enforcement_id] = record
        self.saved_statuses.append(record.status.value)
        return record

    def get(self, enforcement_id: str) -> EnforcementRecord | None:
        return self.items.get(enforcement_id)

    def claim_execution(self, record: EnforcementRecord) -> tuple[EnforcementRecord, bool]:
        existing = self.items.get(record.enforcement_id)
        if existing is None or existing.status is not EnforcementStatus.PREPARED:
            return existing or record, False
        self.items[record.enforcement_id] = record
        self.saved_statuses.append(record.status.value)
        return record, True


class MemoryPolicyRepository:
    """In-memory immutable policy fake."""

    def __init__(self, policy: PolicySet) -> None:
        self.policy = policy

    def get(self, identifier: str) -> PolicySet | None:
        return self.policy if self.policy.identifier == identifier else None


class MemoryCapabilityRepository:
    """In-memory provider fact fake."""

    def __init__(self, records: tuple[ProviderCapabilityRecord, ...]) -> None:
        self.records = records

    @property
    def registry_version(self) -> str:
        return "registry@test"

    def get(self, target: ProviderTarget) -> ProviderCapabilityRecord | None:
        return next((item for item in self.records if item.target == target), None)

    def list(self) -> tuple[ProviderCapabilityRecord, ...]:
        return self.records


class MemoryToolCatalogRepository:
    """In-memory immutable trusted tool catalog fake."""

    def __init__(self, tools: tuple[AuthorizedTool, ...] | None = None) -> None:
        self.tools = tools or (
            authorized_tool("cards.read", "read_only"),
            authorized_tool("cards.unblock", "high_impact_state_change"),
        )

    @property
    def catalog_version(self) -> str:
        return "tools@test"

    def get(self, name: str) -> AuthorizedTool | None:
        return next((item for item in self.tools if item.name == name), None)

    def list(self) -> tuple[AuthorizedTool, ...]:
        return self.tools


def authorized_tool(name: str, risk_class: str) -> AuthorizedTool:
    """Build a synthetic trusted tool definition with no sensitive content."""
    schema_json = (
        '{"additionalProperties":false,"properties":{"token":{"type":"string"}},'
        '"required":["token"],"type":"object"}'
    )
    return AuthorizedTool(
        name=name,
        description=f"Synthetic {name} tool.",
        risk_class=risk_class,
        schema_version="1.0.0",
        input_schema_json=schema_json,
        input_schema_digest=f"sha256:{hashlib.sha256(schema_json.encode()).hexdigest()}",
        definition_digest=f"sha256:{hashlib.sha256(f'{name}:{risk_class}:{schema_json}'.encode()).hexdigest()}",
        catalog_version="tools@test",
    )


class CapturingObserver(EvaluationObserver):
    """Capture allowlisted event calls for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Mapping[str, str]]] = []

    def emit(self, event: str, metadata: Mapping[str, str]) -> None:
        self.events.append((event, metadata))


def capability_record(
    *,
    state: CapabilityState = CapabilityState.SUPPORTED,
    verified_at: date = date(2026, 9, 22),
    target: ProviderTarget | None = None,
    conditions: tuple[str, ...] = (),
) -> ProviderCapabilityRecord:
    """Build a source-backed synthetic provider record."""
    selected = target or ProviderTarget("test-provider", "test-service", "test-region")
    fact = ProviderCapability(
        provider=selected.provider,
        service=selected.service,
        region=selected.region,
        key="required_control",
        state=state,
        conditions=conditions,
        notes=(),
        source_urls=("https://provider.invalid/documentation",),
        verified_at=verified_at,
        record_version="1",
        registry_version="registry@test",
    )
    return ProviderCapabilityRecord(
        target=selected,
        registry_version="registry@test",
        record_version="1",
        verified_at=verified_at,
        source_urls=fact.source_urls,
        capabilities=(fact,),
    )


def context(
    *,
    data_items: tuple[DataItem, ...] = (),
    tools: tuple[ToolRequest, ...] = (),
    fallback_providers: tuple[ProviderTarget, ...] = (),
    assertions: tuple[tuple[str, bool], ...] = (),
) -> EvaluationContext:
    """Build a normalized synthetic evaluation context."""
    return EvaluationContext(
        correlation_id="test-correlation",
        jurisdiction=Jurisdiction("BR"),
        sector=Sector("financial_services"),
        purpose=Purpose("customer_support"),
        operation_kind="external_inference",
        assurance_level=AssuranceLevel.HIGH,
        provider=ProviderTarget("test-provider", "test-service", "test-region"),
        data_items=data_items,
        tools=tools,
        policy_set_version="test-policy@1.0.0",
        organization_assertions=assertions,
        fallback_providers=fallback_providers,
    )
