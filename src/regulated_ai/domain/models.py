"""Framework-free domain types and deterministic policy invariants."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class DataClassification(StrEnum):
    """Classification labels understood by the Phase 1 policy model."""

    PERSONAL_DIRECT_IDENTIFIER = "PERSONAL_DIRECT_IDENTIFIER"
    BRAZIL_CPF = "BRAZIL_CPF"
    BRAZIL_CNPJ = "BRAZIL_CNPJ"
    FINANCIAL_ACCOUNT_IDENTIFIER = "FINANCIAL_ACCOUNT_IDENTIFIER"
    FINANCIAL_TRANSACTION_DATA = "FINANCIAL_TRANSACTION_DATA"
    AUTHENTICATION_SECRET = "AUTHENTICATION_SECRET"  # noqa: S105  # nosec B105
    HEALTH_DATA = "HEALTH_DATA"
    BIOMETRIC_DATA = "BIOMETRIC_DATA"


class DecisionOutcome(StrEnum):
    """Supported top-level evaluation outcomes."""

    ALLOW = "ALLOW"
    ALLOW_WITH_TRANSFORMATION = "ALLOW_WITH_TRANSFORMATION"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


class ObligationType(StrEnum):
    """Supported executable or enforceable obligations."""

    REMOVE_FIELD = "REMOVE_FIELD"
    MASK = "MASK"
    TOKENIZE = "TOKENIZE"
    PSEUDONYMIZE = "PSEUDONYMIZE"
    REQUIRE_PROVIDER_CAPABILITY = "REQUIRE_PROVIDER_CAPABILITY"
    REQUIRE_HUMAN_APPROVAL = "REQUIRE_HUMAN_APPROVAL"
    RESTRICT_TOOL = "RESTRICT_TOOL"
    REQUIRE_EVIDENCE = "REQUIRE_EVIDENCE"


class CapabilityState(StrEnum):
    """Explicit provider capability state."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class AssuranceLevel(StrEnum):
    """Organization-selected evaluation assurance level."""

    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"


class EnforcementStatus(StrEnum):
    """Lifecycle state for local enforcement and bounded execution."""

    PREPARED = "PREPARED"
    DISPATCHED = "DISPATCHED"
    EXECUTED = "EXECUTED"
    BLOCKED_DENY = "BLOCKED_DENY"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVAL_FAILED = "APPROVAL_FAILED"
    TRANSFORMATION_FAILED = "TRANSFORMATION_FAILED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class ToolActionStatus(StrEnum):
    """Lifecycle state for one action bound to an exact tool proposal."""

    WAITING_APPROVAL = "WAITING_APPROVAL"
    PREPARED = "PREPARED"
    DISPATCHED = "DISPATCHED"
    EXECUTED = "EXECUTED"
    APPROVAL_FAILED = "APPROVAL_FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    RESULT_REJECTED = "RESULT_REJECTED"


class ToolResultClassification(StrEnum):
    """Organization-owned sensitivity class for one tool-result field."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PERSONAL = "PERSONAL"
    FINANCIAL = "FINANCIAL"
    AUTHENTICATION_SECRET = "AUTHENTICATION_SECRET"  # noqa: S105  # nosec B105


class ToolResultHandling(StrEnum):
    """Deterministic exposure treatment for one validated result field."""

    RETURN = "RETURN"
    MASK = "MASK"
    DROP = "DROP"


class OperatorTimelineStageKind(StrEnum):
    """Control-plane stage exposed to the read-only operator view."""

    EVALUATION = "EVALUATION"
    ENFORCEMENT = "ENFORCEMENT"
    TOOL_ACTION = "TOOL_ACTION"


class OperatorLifecycleEventSource(StrEnum):
    """Origin of one persisted lifecycle-history observation."""

    TRANSITION = "TRANSITION"
    MIGRATION_BASELINE = "MIGRATION_BASELINE"


class OperatorAttentionCode(StrEnum):
    """Stable reason that an operator-facing control timeline needs attention."""

    ENFORCEMENT_APPROVAL_REQUIRED = "ENFORCEMENT_APPROVAL_REQUIRED"
    ENFORCEMENT_APPROVAL_FAILED = "ENFORCEMENT_APPROVAL_FAILED"
    ENFORCEMENT_RECONCILIATION_REQUIRED = "ENFORCEMENT_RECONCILIATION_REQUIRED"
    ENFORCEMENT_TRANSFORMATION_FAILED = "ENFORCEMENT_TRANSFORMATION_FAILED"
    ENFORCEMENT_EXECUTION_FAILED = "ENFORCEMENT_EXECUTION_FAILED"
    TOOL_ACTION_APPROVAL_REQUIRED = "TOOL_ACTION_APPROVAL_REQUIRED"
    TOOL_ACTION_APPROVAL_FAILED = "TOOL_ACTION_APPROVAL_FAILED"
    TOOL_ACTION_RECONCILIATION_REQUIRED = "TOOL_ACTION_RECONCILIATION_REQUIRED"
    TOOL_RESULT_REJECTED = "TOOL_RESULT_REJECTED"
    ACTION_LIST_TRUNCATED = "ACTION_LIST_TRUNCATED"
    EVENT_LIST_TRUNCATED = "EVENT_LIST_TRUNCATED"


@dataclass(frozen=True, slots=True)
class Jurisdiction:
    """Normalized jurisdiction identifier."""

    code: str


@dataclass(frozen=True, slots=True)
class Sector:
    """Normalized sector identifier."""

    name: str


@dataclass(frozen=True, slots=True)
class Purpose:
    """Normalized business purpose."""

    name: str


@dataclass(frozen=True, slots=True)
class DataItem:
    """Ephemeral runtime data plus caller and detected labels."""

    field: str
    value: str
    supplied_labels: tuple[DataClassification, ...] = ()
    detected_labels: tuple[DataClassification, ...] = ()

    @property
    def labels(self) -> tuple[DataClassification, ...]:
        """Return stable, deduplicated effective labels."""
        return tuple(sorted(set(self.supplied_labels) | set(self.detected_labels), key=str))


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Untrusted caller request for one organization-defined tool."""

    name: str
    claimed_risk_class: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedTool:
    """Trusted, versioned tool definition resolved from the control plane."""

    name: str
    description: str
    risk_class: str
    schema_version: str
    input_schema_json: str
    input_schema_digest: str
    output_schema_json: str
    output_schema_digest: str
    definition_digest: str
    catalog_version: str

    @property
    def identifier(self) -> str:
        """Return the immutable catalog identity used in digests and evidence."""
        return f"{self.name}@{self.schema_version}"


@dataclass(frozen=True, slots=True)
class ToolProposal:
    """Metadata-only model proposal that has not been authorized for execution."""

    call_id: str
    tool_name: str
    tool_schema_version: str
    tool_schema_digest: str
    arguments_digest: str


@dataclass(frozen=True, slots=True)
class ProviderTarget:
    """Intended provider execution surface."""

    provider: str
    service: str
    region: str | None = None
    model_family: str | None = None
    processing_mode: str | None = None

    @property
    def identifier(self) -> str:
        """Return a content-free provider/service/region identifier."""
        parts = [self.provider, self.service]
        if self.region is not None:
            parts.append(self.region)
        return ".".join(parts)


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Normalized business context for one evaluation."""

    correlation_id: str
    jurisdiction: Jurisdiction
    sector: Sector
    purpose: Purpose
    operation_kind: str
    assurance_level: AssuranceLevel
    provider: ProviderTarget
    data_items: tuple[DataItem, ...]
    tools: tuple[ToolRequest, ...]
    policy_set_version: str
    organization_assertions: tuple[tuple[str, bool], ...] = ()
    fallback_providers: tuple[ProviderTarget, ...] = ()

    def assertion(self, key: str) -> bool:
        """Return one explicit organization assertion, defaulting closed."""
        return dict(self.organization_assertions).get(key, False)


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """One source-backed provider capability fact."""

    provider: str
    service: str
    region: str | None
    key: str
    state: CapabilityState
    conditions: tuple[str, ...]
    notes: tuple[str, ...]
    source_urls: tuple[str, ...]
    verified_at: date
    record_version: str
    registry_version: str

    @property
    def identifier(self) -> str:
        """Return the stable fact identifier used in decisions and evidence."""
        return f"{self.provider}.{self.service}.{self.key}"


@dataclass(frozen=True, slots=True)
class ProviderCapabilityRecord:
    """Versioned capability facts for one provider target."""

    target: ProviderTarget
    registry_version: str
    record_version: str
    verified_at: date
    source_urls: tuple[str, ...]
    capabilities: tuple[ProviderCapability, ...]

    def capability(self, key: str) -> ProviderCapability | None:
        """Resolve one named fact without coercing missing data."""
        return next((item for item in self.capabilities if item.key == key), None)


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """Mandatory capability predicate emitted by policy."""

    key: str
    accepted_states: tuple[CapabilityState, ...]
    required_condition_assertions: tuple[str, ...] = ()
    max_age_days: int | None = None


@dataclass(frozen=True, slots=True)
class PolicyMatch:
    """Small, explicit set of supported policy match dimensions."""

    jurisdiction: str | None = None
    sector: str | None = None
    purpose: str | None = None
    operation_kind: str | None = None
    assurance_level: AssuranceLevel | None = None
    provider: str | None = None
    service: str | None = None
    region: str | None = None
    data_class_any: tuple[DataClassification, ...] = ()
    tool_risk_class_any: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Obligation:
    """One control that must be honored by a later enforcement step."""

    type: ObligationType
    target: str | None
    reason_code: str
    control_objective_ids: tuple[str, ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyObligation:
    """Policy template expanded into concrete obligations during evaluation."""

    type: ObligationType
    target: str | None
    target_class: DataClassification | None
    reason_code: str
    parameters: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """Organization-approved executable policy rule."""

    id: str
    version: str
    match: PolicyMatch
    decision: DecisionOutcome | None
    obligations: tuple[PolicyObligation, ...]
    required_capabilities: tuple[CapabilityRequirement, ...]
    control_objective_ids: tuple[str, ...]
    regulatory_support_refs: tuple[str, ...]
    reason_code: str | None = None

    @property
    def identifier(self) -> str:
        """Return immutable rule identifier and version."""
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class ControlObjective:
    """Human-approved objective separated from source mappings and policy."""

    id: str
    version: str
    owner: str
    status: str
    source_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicySet:
    """Immutable collection of executable policy rules."""

    id: str
    version: str
    jurisdiction: str
    sector: str
    status: str
    rules: tuple[PolicyRule, ...]

    @property
    def identifier(self) -> str:
        """Return immutable policy-set identifier and version."""
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class EvidenceMetadata:
    """Allowlisted metadata proving one evaluation without retaining content."""

    evidence_id: str
    created_at: datetime
    correlation_id: str
    decision: DecisionOutcome
    policy_set_version: str
    provider_registry_version: str
    matched_policy_ids: tuple[str, ...]
    provider_capability_ids: tuple[str, ...]
    control_objective_ids: tuple[str, ...]
    obligation_types: tuple[ObligationType, ...]
    classification_labels: tuple[DataClassification, ...]
    reason_codes: tuple[str, ...]
    input_digest: str
    output_digest: str
    event_digest: str
    previous_event_digest: str | None = None
    tool_catalog_version: str | None = None
    authorized_tool_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Typed Phase 1 execution plan returned to the caller."""

    evaluation_id: str
    decision: DecisionOutcome
    obligations: tuple[Obligation, ...]
    matched_policy_ids: tuple[str, ...]
    provider_capability_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    policy_set_version: str
    provider_registry_version: str
    evidence_id: str
    input_digest: str
    output_digest: str
    authorized_tools: tuple[AuthorizedTool, ...] = ()
    tool_catalog_version: str | None = None


@dataclass(frozen=True, slots=True)
class TransformationReceipt:
    """Metadata-only proof that one field transformation occurred."""

    receipt_id: str
    type: ObligationType
    target: str
    input_digest: str
    output_digest: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """Verified but not yet consumed external approval authority."""

    approval_id: str
    actor_id: str
    decision_digest: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    """Metadata-only proof that one approval grant was consumed."""

    approval_id: str
    actor_id: str
    decision_digest: str
    enforcement_id: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime


@dataclass(frozen=True, slots=True)
class ActionApprovalGrant:
    """Verified but unconsumed authority for one exact tool action."""

    approval_id: str
    actor_id: str
    action_digest: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ActionApprovalReceipt:
    """Metadata-only proof that action-specific authority was consumed."""

    approval_id: str
    actor_id: str
    action_digest: str
    action_id: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Ephemeral sanitized payload suitable for an inference execution port."""

    plan_id: str
    evaluation_id: str
    decision_digest: str
    operation_kind: str
    purpose: str
    assurance_level: AssuranceLevel
    provider: ProviderTarget
    data_items: tuple[DataItem, ...]
    tools: tuple[AuthorizedTool, ...]
    transformation_receipts: tuple[TransformationReceipt, ...]
    output_digest: str
    approval_receipt: ApprovalReceipt | None = None


@dataclass(frozen=True, slots=True)
class ProviderCallMetadata:
    """Metadata-only routing and execution evidence from an external boundary."""

    gateway_request_id: str
    routing_decision_id: str
    policy_id: str
    policy_version: str
    provider: str
    model: str
    deployment: str
    latency_ms: int
    attempt_number: int
    fallback_index: int
    cached: bool


@dataclass(frozen=True, slots=True)
class ProviderExecutionReceipt:
    """Metadata-only receipt returned by an inference execution adapter."""

    execution_id: str
    provider_target: str
    plan_id: str
    output_digest: str
    call_metadata: ProviderCallMetadata | None = None
    tool_proposals: tuple[ToolProposal, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolActionPlan:
    """Ephemeral exact action passed only to the downstream execution boundary."""

    action_id: str
    action_digest: str
    enforcement_id: str
    call_id: str
    tool: AuthorizedTool
    workload_identity: str
    idempotency_key: str
    arguments: tuple[tuple[str, str], ...]
    approval_receipt: ActionApprovalReceipt


@dataclass(frozen=True, slots=True)
class ToolExecutionReceipt:
    """Metadata-only receipt from the bounded tool execution boundary."""

    execution_id: str
    action_id: str


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """Ephemeral untrusted output paired with metadata-only execution evidence."""

    receipt: ToolExecutionReceipt
    output: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class ToolActionRecord:
    """Persisted metadata for one exact proposed action."""

    action_id: str
    created_at: datetime
    enforcement_id: str
    evaluation_id: str
    call_id: str
    tool_name: str
    tool_schema_version: str
    tool_schema_digest: str
    arguments_digest: str
    workload_identity: str
    idempotency_key_digest: str
    action_digest: str
    status: ToolActionStatus
    output_schema_digest: str | None = None
    approval_receipt: ActionApprovalReceipt | None = None
    tool_execution_id: str | None = None
    output_digest: str | None = None
    safe_output_digest: str | None = None
    result_classifications: tuple[ToolResultClassification, ...] = ()
    exposed_result_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolActionResult:
    """Metadata-only action state returned to a caller."""

    action_id: str
    enforcement_id: str
    call_id: str
    tool_name: str
    workload_identity: str
    action_digest: str
    status: ToolActionStatus
    output_schema_digest: str | None = None
    approval_receipt: ActionApprovalReceipt | None = None
    tool_execution_id: str | None = None
    output_digest: str | None = None
    safe_output_digest: str | None = None
    result_classifications: tuple[ToolResultClassification, ...] = ()
    exposed_result_fields: tuple[str, ...] = ()
    safe_output: tuple[tuple[str, str], ...] | None = None


@dataclass(frozen=True, slots=True)
class EnforcementRecord:
    """Persisted metadata for one enforcement attempt."""

    enforcement_id: str
    created_at: datetime
    evaluation_id: str
    evaluation_evidence_id: str
    decision: DecisionOutcome
    status: EnforcementStatus
    policy_set_version: str
    provider_registry_version: str
    provider_target: str
    transformation_receipts: tuple[TransformationReceipt, ...]
    reason_codes: tuple[str, ...]
    input_digest: str
    output_digest: str | None
    provider_execution_id: str | None
    provider_call_metadata: ProviderCallMetadata | None = None
    approval_receipt: ApprovalReceipt | None = None
    tool_proposals: tuple[ToolProposal, ...] = ()


@dataclass(frozen=True, slots=True)
class EnforcementResult:
    """Metadata-only result returned after local enforcement."""

    enforcement_id: str
    evaluation_id: str
    evaluation_evidence_id: str
    decision: DecisionOutcome
    status: EnforcementStatus
    transformation_receipts: tuple[TransformationReceipt, ...]
    reason_codes: tuple[str, ...]
    output_digest: str | None
    provider_execution_id: str | None
    provider_call_metadata: ProviderCallMetadata | None = None
    approval_receipt: ApprovalReceipt | None = None
    tool_proposals: tuple[ToolProposal, ...] = ()


@dataclass(frozen=True, slots=True)
class OperatorTimelineStage:
    """One metadata-only stage in architectural execution order."""

    sequence: int
    kind: OperatorTimelineStageKind
    record_id: str
    created_at: datetime
    status: str
    attention_codes: tuple[OperatorAttentionCode, ...] = ()
    tool_name: str | None = None
    call_id: str | None = None
    approval_recorded: bool = False


@dataclass(frozen=True, slots=True)
class OperatorLifecycleEvent:
    """One append-only metadata observation from the local lifecycle ledger."""

    sequence: int
    event_id: str
    recorded_at: datetime
    source: OperatorLifecycleEventSource
    kind: OperatorTimelineStageKind
    record_id: str
    enforcement_id: str | None
    status: str


@dataclass(frozen=True, slots=True)
class OperatorApprovalSummary:
    """Approval metadata safe for the operator view without actor identity."""

    approval_id: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime


@dataclass(frozen=True, slots=True)
class OperatorTimeline:
    """Bounded current-state view for one exact enforcement."""

    enforcement_id: str
    evaluation_id: str
    evidence_id: str
    correlation_id: str
    policy_set_version: str
    provider_registry_version: str
    tool_catalog_version: str | None
    classification_labels: tuple[DataClassification, ...]
    obligation_types: tuple[ObligationType, ...]
    matched_policy_ids: tuple[str, ...]
    provider_capability_ids: tuple[str, ...]
    control_objective_ids: tuple[str, ...]
    decision_reason_codes: tuple[str, ...]
    enforcement_reason_codes: tuple[str, ...]
    authorized_tool_ids: tuple[str, ...]
    provider_target: str
    transformation_receipts: tuple[TransformationReceipt, ...]
    approval: OperatorApprovalSummary | None
    input_digest: str
    output_digest: str
    event_digest: str
    previous_event_digest: str | None
    stages: tuple[OperatorTimelineStage, ...]
    attention_codes: tuple[OperatorAttentionCode, ...]
    lifecycle_events: tuple[OperatorLifecycleEvent, ...] = ()
    history_complete: bool = False
    actions_truncated: bool = False
    events_truncated: bool = False


_PRECEDENCE = {
    DecisionOutcome.ALLOW: 0,
    DecisionOutcome.ALLOW_WITH_TRANSFORMATION: 1,
    DecisionOutcome.REQUIRE_APPROVAL: 2,
    DecisionOutcome.DENY: 3,
}


def strongest_outcome(outcomes: tuple[DecisionOutcome, ...]) -> DecisionOutcome:
    """Return the strongest outcome using the documented fixed precedence."""
    return max(outcomes or (DecisionOutcome.ALLOW,), key=_PRECEDENCE.__getitem__)
