"""Strict, safe YAML adapters for policy and provider registry files."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from regulated_ai.domain import (
    AssuranceLevel,
    CapabilityRequirement,
    CapabilityState,
    DataClassification,
    DecisionOutcome,
    ObligationType,
    PolicyMatch,
    PolicyObligation,
    PolicyRule,
    PolicySet,
    ProviderCapability,
    ProviderCapabilityRecord,
    ProviderTarget,
)


class ConfigurationBoundaryError(ValueError):
    """Base error for rejected external configuration."""

    code = "CONFIGURATION_INVALID"


class MalformedYamlError(ConfigurationBoundaryError):
    """YAML could not be parsed as a mapping matching the schema."""

    code = "MALFORMED_YAML"


class UnsupportedSchemaVersionError(ConfigurationBoundaryError):
    """A configuration file uses an unsupported schema version."""

    code = "POLICY_SCHEMA_UNSUPPORTED"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CapabilityModel(_StrictModel):
    state: CapabilityState
    conditions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class _CapabilityFileModel(_StrictModel):
    schema_version: Literal["1"]
    registry_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    service: str = Field(min_length=1)
    region: str | None = None
    verified_at: str
    record_version: str | int
    sources: tuple[str, ...] = Field(min_length=1)
    capabilities: dict[str, _CapabilityModel] = Field(min_length=1)

    @field_validator("verified_at")
    @classmethod
    def valid_date(cls, value: str) -> str:
        """Require an ISO calendar date."""
        from datetime import date

        date.fromisoformat(value)
        return value

    @field_validator("sources")
    @classmethod
    def authoritative_urls(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require explicit HTTPS source URLs."""
        if any(not value.startswith("https://") for value in values):
            raise ValueError("capability sources must be HTTPS URLs")
        return values


class _PolicySetModel(_StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    status: str = Field(min_length=1)


class _MatchModel(_StrictModel):
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


class _ObligationModel(_StrictModel):
    type: ObligationType
    target: str | None = None
    target_class: DataClassification | None = None
    reason_code: str = Field(min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_target_selector(self) -> "_ObligationModel":
        """Reject ambiguous obligation targeting."""
        if self.target is not None and self.target_class is not None:
            raise ValueError("obligation cannot define target and target_class together")
        return self


class _RequirementModel(_StrictModel):
    key: str = Field(min_length=1)
    accepted_states: tuple[CapabilityState, ...] = Field(min_length=1)
    required_condition_assertions: tuple[str, ...] = ()
    max_age_days: int | None = Field(default=None, ge=0)


class _RuleModel(_StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    match: _MatchModel = Field(default_factory=_MatchModel)
    decision: DecisionOutcome | None = None
    obligations: tuple[_ObligationModel, ...] = ()
    requires_capabilities: tuple[_RequirementModel, ...] = ()
    control_objectives: tuple[str, ...] = ()
    regulatory_support: tuple[str, ...] = ()
    reason_code: str | None = None

    @model_validator(mode="after")
    def has_effect(self) -> "_RuleModel":
        """Require every rule to contribute an enforceable effect."""
        if self.decision is None and not self.obligations and not self.requires_capabilities:
            raise ValueError("policy rule must define a decision, obligation, or capability")
        return self


class _PolicyFileModel(_StrictModel):
    schema_version: Literal["1"]
    policy_set: _PolicySetModel
    rules: tuple[_RuleModel, ...] = Field(min_length=1)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MalformedYamlError(f"Invalid configuration file: {path.name}") from exc
    if not isinstance(raw, dict):
        raise MalformedYamlError(f"Configuration must be a mapping: {path.name}")
    schema_version = raw.get("schema_version")
    if schema_version != "1":
        raise UnsupportedSchemaVersionError(
            f"Unsupported schema version in configuration file: {path.name}"
        )
    return raw


def load_policy_file(path: Path) -> PolicySet:
    """Translate one strict policy YAML document into domain types."""
    try:
        document = _PolicyFileModel.model_validate(_read_yaml(path))
    except UnsupportedSchemaVersionError:
        raise
    except (ValidationError, ValueError) as exc:
        raise MalformedYamlError(f"Policy file failed schema validation: {path.name}") from exc
    metadata = document.policy_set
    return PolicySet(
        id=metadata.id,
        version=metadata.version,
        jurisdiction=metadata.jurisdiction,
        sector=metadata.sector,
        status=metadata.status,
        rules=tuple(_to_rule(rule) for rule in document.rules),
    )


def load_capability_file(path: Path) -> ProviderCapabilityRecord:
    """Translate one strict capability YAML document into domain types."""
    from datetime import date

    try:
        document = _CapabilityFileModel.model_validate(_read_yaml(path))
    except UnsupportedSchemaVersionError:
        raise
    except (ValidationError, ValueError) as exc:
        raise MalformedYamlError(f"Capability file failed schema validation: {path.name}") from exc
    record_version = str(document.record_version)
    verified_at = date.fromisoformat(document.verified_at)
    capabilities = tuple(
        ProviderCapability(
            provider=document.provider,
            service=document.service,
            region=document.region,
            key=key,
            state=value.state,
            conditions=value.conditions,
            notes=value.notes,
            source_urls=document.sources,
            verified_at=verified_at,
            record_version=record_version,
            registry_version=document.registry_version,
        )
        for key, value in sorted(document.capabilities.items())
    )
    return ProviderCapabilityRecord(
        target=ProviderTarget(document.provider, document.service, document.region),
        registry_version=document.registry_version,
        record_version=record_version,
        verified_at=verified_at,
        source_urls=document.sources,
        capabilities=capabilities,
    )


def _to_rule(rule: _RuleModel) -> PolicyRule:
    match = rule.match
    return PolicyRule(
        id=rule.id,
        version=rule.version,
        match=PolicyMatch(
            jurisdiction=match.jurisdiction,
            sector=match.sector,
            purpose=match.purpose,
            operation_kind=match.operation_kind,
            assurance_level=match.assurance_level,
            provider=match.provider,
            service=match.service,
            region=match.region,
            data_class_any=match.data_class_any,
            tool_risk_class_any=match.tool_risk_class_any,
        ),
        decision=rule.decision,
        obligations=tuple(
            PolicyObligation(
                type=item.type,
                target=item.target,
                target_class=item.target_class,
                reason_code=item.reason_code,
                parameters=tuple(sorted(item.parameters.items())),
            )
            for item in rule.obligations
        ),
        required_capabilities=tuple(
            CapabilityRequirement(
                key=item.key,
                accepted_states=item.accepted_states,
                required_condition_assertions=item.required_condition_assertions,
                max_age_days=item.max_age_days,
            )
            for item in rule.requires_capabilities
        ),
        control_objective_ids=rule.control_objectives,
        regulatory_support_refs=rule.regulatory_support,
        reason_code=rule.reason_code,
    )


class FilePolicyRepository:
    """Eagerly validated immutable policy-set collection."""

    def __init__(self, paths: tuple[Path, ...]) -> None:
        """Load every configured policy file and reject duplicate identifiers."""
        loaded = tuple(load_policy_file(path) for path in paths)
        self._items = {item.identifier: item for item in loaded}
        if len(self._items) != len(loaded):
            raise ConfigurationBoundaryError("Duplicate policy-set identifier")

    def get(self, identifier: str) -> PolicySet | None:
        """Return one immutable policy set."""
        return self._items.get(identifier)


class FileProviderCapabilityRepository:
    """Eagerly validated immutable provider capability registry."""

    def __init__(self, paths: tuple[Path, ...]) -> None:
        """Load records and require one registry release version."""
        loaded = tuple(load_capability_file(path) for path in paths)
        versions = {item.registry_version for item in loaded}
        if not loaded or len(versions) != 1:
            raise ConfigurationBoundaryError("Provider records must share one registry version")
        self._registry_version = next(iter(versions))
        self._items = {
            (item.target.provider, item.target.service, item.target.region): item for item in loaded
        }
        if len(self._items) != len(loaded):
            raise ConfigurationBoundaryError("Duplicate provider capability target")

    @property
    def registry_version(self) -> str:
        """Return the immutable registry release version."""
        return self._registry_version

    def get(self, target: ProviderTarget) -> ProviderCapabilityRecord | None:
        """Resolve an exact provider/service/region record."""
        return self._items.get((target.provider, target.service, target.region))

    def list(self) -> tuple[ProviderCapabilityRecord, ...]:
        """Return records in stable provider/service/region order."""
        return tuple(
            sorted(
                self._items.values(),
                key=lambda item: (
                    item.target.provider,
                    item.target.service,
                    item.target.region or "",
                ),
            )
        )
