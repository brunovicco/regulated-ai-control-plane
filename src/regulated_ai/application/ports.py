"""Application ports for the deterministic evaluation use case."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from regulated_ai.domain import (
    ApprovalGrant,
    ApprovalReceipt,
    AuthorizedTool,
    DataItem,
    EnforcementRecord,
    EvidenceMetadata,
    ExecutionPlan,
    PolicySet,
    ProviderCapabilityRecord,
    ProviderExecutionReceipt,
    ProviderTarget,
)


class PolicyRepository(Protocol):
    """Resolve immutable policy sets by versioned identifier."""

    def get(self, identifier: str) -> PolicySet | None:
        """Return a policy set or no value when the identifier is unknown."""
        ...


class ProviderCapabilityRepository(Protocol):
    """Resolve and list source-backed provider capability records."""

    @property
    def registry_version(self) -> str:
        """Return the immutable registry release version."""
        ...

    def get(self, target: ProviderTarget) -> ProviderCapabilityRecord | None:
        """Return facts for an exact provider/service/region target."""
        ...

    def list(self) -> tuple[ProviderCapabilityRecord, ...]:
        """Return all loaded records in stable order."""
        ...


class ToolCatalogRepository(Protocol):
    """Resolve immutable organization-owned tool definitions."""

    @property
    def catalog_version(self) -> str:
        """Return the immutable tool-catalog release version."""
        ...

    def get(self, name: str) -> AuthorizedTool | None:
        """Return one trusted tool definition by normalized name."""
        ...

    def list(self) -> tuple[AuthorizedTool, ...]:
        """Return every trusted definition in stable order."""
        ...


class EvidenceRepository(Protocol):
    """Persist and retrieve metadata-only evidence."""

    def save(self, evidence: EvidenceMetadata) -> EvidenceMetadata:
        """Persist one immutable record and return the stored representation."""
        ...

    def get(self, evidence_id: str) -> EvidenceMetadata | None:
        """Return one record by id."""
        ...


class EnforcementRepository(Protocol):
    """Persist and retrieve metadata-only enforcement records."""

    def save(self, record: EnforcementRecord) -> EnforcementRecord:
        """Persist the latest state for one enforcement attempt."""
        ...

    def claim_execution(self, record: EnforcementRecord) -> tuple[EnforcementRecord, bool]:
        """Atomically advance PREPARED to DISPATCHED and report claim ownership."""
        ...

    def get(self, enforcement_id: str) -> EnforcementRecord | None:
        """Return one enforcement record by id."""
        ...


class DataClassifier(Protocol):
    """Apply only deterministic classification supported by the MVP."""

    def classify(self, item: DataItem) -> tuple[DataItem, ...]:
        """Return the classified item as a tuple for future split-field support."""
        ...


class EvaluationObserver(Protocol):
    """Receive allowlisted metadata-only evaluation lifecycle events."""

    def emit(self, event: str, metadata: Mapping[str, str]) -> None:
        """Emit one stable event without request content."""
        ...


class ApprovalPort(Protocol):
    """Validate and atomically consume externally issued approval authority."""

    def inspect(
        self,
        assertion: str,
        *,
        decision_digest: str,
        now: datetime,
    ) -> ApprovalGrant:
        """Verify an assertion without consuming it."""
        ...

    def consume(
        self,
        grant: ApprovalGrant,
        *,
        enforcement_id: str,
        now: datetime,
    ) -> ApprovalReceipt:
        """Consume one verified grant exactly once."""
        ...


class TokenizationPort(Protocol):
    """Transform sensitive values without exposing key material to the application."""

    def tokenize(self, value: str, *, field: str, decision_digest: str) -> str:
        """Return a non-reversible local token for one value."""
        ...

    def pseudonymize(self, value: str, *, field: str, decision_digest: str) -> str:
        """Return a stable scoped pseudonym for one value."""
        ...


class InferenceExecutionPort(Protocol):
    """Boundary for post-enforcement provider or gateway execution."""

    def execute(self, plan: ExecutionPlan) -> ProviderExecutionReceipt:
        """Execute only a transformed, evidence-backed decision plan."""
        ...
