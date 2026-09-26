"""Strict, safe YAML adapters for policy, provider and tool control-plane files."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.domain import (
    AssuranceLevel,
    AuthorizedTool,
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
    ToolResultClassification,
    ToolResultHandling,
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


class _ToolPropertyModel(_StrictModel):
    type: Literal["string"]
    description: str | None = Field(default=None, min_length=1, max_length=256)
    minLength: int | None = Field(default=None, ge=0, le=4096)
    maxLength: int | None = Field(default=None, ge=1, le=4096)
    pattern: str | None = Field(default=None, min_length=1, max_length=256)
    enum: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def valid_lengths(self) -> "_ToolPropertyModel":
        """Reject contradictory string length constraints."""
        if (
            self.minLength is not None
            and self.maxLength is not None
            and self.minLength > self.maxLength
        ):
            raise ValueError("tool property length constraints are invalid")
        return self


class _ToolInputSchemaModel(_StrictModel):
    type: Literal["object"]
    additionalProperties: Literal[False]
    properties: dict[str, _ToolPropertyModel] = Field(min_length=1, max_length=128)
    required: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_required_fields(self) -> "_ToolInputSchemaModel":
        """Require normalized property names and a unique required subset."""
        if (
            any(_TOOL_NAME.fullmatch(name) is None for name in self.properties)
            or len(self.required) != len(set(self.required))
            or not set(self.required).issubset(self.properties)
        ):
            raise ValueError("tool input schema fields are invalid")
        return self


class _ToolResultPropertyModel(_ToolPropertyModel):
    classification: ToolResultClassification
    handling: ToolResultHandling

    @model_validator(mode="after")
    def safe_exposure(self) -> "_ToolResultPropertyModel":
        """Prevent sensitive result classes from being returned verbatim."""
        if self.handling is ToolResultHandling.RETURN and self.enum is None:
            raise ValueError("returned tool result fields must use a closed enum")
        if (
            self.classification
            in {
                ToolResultClassification.PERSONAL,
                ToolResultClassification.FINANCIAL,
            }
            and self.handling is ToolResultHandling.RETURN
        ):
            raise ValueError("sensitive tool result fields cannot use RETURN")
        if (
            self.classification is ToolResultClassification.AUTHENTICATION_SECRET
            and self.handling is not ToolResultHandling.DROP
        ):
            raise ValueError("authentication-secret tool result fields must use DROP")
        return self


class _ToolOutputSchemaModel(_StrictModel):
    type: Literal["object"]
    additionalProperties: Literal[False]
    properties: dict[str, _ToolResultPropertyModel] = Field(min_length=1, max_length=128)
    required: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_required_fields(self) -> "_ToolOutputSchemaModel":
        """Require normalized property names and a unique required subset."""
        if (
            any(_TOOL_NAME.fullmatch(name) is None for name in self.properties)
            or len(self.required) != len(set(self.required))
            or not set(self.required).issubset(self.properties)
        ):
            raise ValueError("tool output schema fields are invalid")
        return self


class _ToolModel(_StrictModel):
    description: str = Field(min_length=1, max_length=512)
    risk_class: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    schema_version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    input_schema: _ToolInputSchemaModel
    output_schema: _ToolOutputSchemaModel

    @field_validator("description")
    @classmethod
    def normalized_description(cls, value: str) -> str:
        """Reject surrounding whitespace and multiline prompt-like descriptions."""
        if value != value.strip() or "\n" in value or "\r" in value:
            raise ValueError("tool description must be one normalized line")
        return value


class _ToolCatalogFileModel(_StrictModel):
    schema_version: Literal["1"]
    catalog_version: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
    )
    tools: dict[str, _ToolModel] = Field(min_length=1)

    @field_validator("tools")
    @classmethod
    def normalized_names(cls, value: dict[str, _ToolModel]) -> dict[str, _ToolModel]:
        """Require unique normalized tool identifiers at the configuration boundary."""
        if any(_TOOL_NAME.fullmatch(name) is None for name in value):
            raise ValueError("tool name is invalid")
        return value


_TOOL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise MalformedYamlError(f"Invalid configuration file: {path.name}") from exc
    return _read_yaml_bytes(content, path.name)


def _read_yaml_bytes(content: bytes, filename: str) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise MalformedYamlError(f"Invalid configuration file: {filename}") from exc
    if not isinstance(raw, dict):
        raise MalformedYamlError(f"Configuration must be a mapping: {filename}")
    schema_version = raw.get("schema_version")
    if schema_version != "1":
        raise UnsupportedSchemaVersionError(
            f"Unsupported schema version in configuration file: {filename}"
        )
    return raw


def _reject_duplicate_mapping_keys(node: Node) -> None:
    """Reject duplicate or complex YAML mapping keys before safe construction."""
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("configuration mapping keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("configuration contains a duplicate mapping key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)


def load_policy_file(path: Path) -> PolicySet:
    """Translate one strict policy YAML document into domain types."""
    return _load_policy_document(_read_yaml(path), path.name)


def load_policy_bytes(content: bytes, filename: str) -> PolicySet:
    """Translate authenticated policy bytes into domain types without reopening a path."""
    return _load_policy_document(_read_yaml_bytes(content, filename), filename)


def _load_policy_document(raw: dict[str, Any], filename: str) -> PolicySet:
    try:
        document = _PolicyFileModel.model_validate(raw)
    except UnsupportedSchemaVersionError:
        raise
    except (ValidationError, ValueError) as exc:
        raise MalformedYamlError(f"Policy file failed schema validation: {filename}") from exc
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
    return _load_capability_document(_read_yaml(path), path.name)


def load_capability_bytes(content: bytes, filename: str) -> ProviderCapabilityRecord:
    """Translate authenticated capability bytes without reopening a path."""
    return _load_capability_document(_read_yaml_bytes(content, filename), filename)


def _load_capability_document(raw: dict[str, Any], filename: str) -> ProviderCapabilityRecord:
    from datetime import date

    try:
        document = _CapabilityFileModel.model_validate(raw)
    except UnsupportedSchemaVersionError:
        raise
    except (ValidationError, ValueError) as exc:
        raise MalformedYamlError(f"Capability file failed schema validation: {filename}") from exc
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


def load_tool_catalog_file(path: Path) -> tuple[str, tuple[AuthorizedTool, ...]]:
    """Translate one strict tool catalog into immutable trusted definitions."""
    return _load_tool_catalog_document(_read_yaml(path), path.name)


def load_tool_catalog_bytes(
    content: bytes, filename: str
) -> tuple[str, tuple[AuthorizedTool, ...]]:
    """Translate authenticated tool-catalog bytes without reopening a path."""
    return _load_tool_catalog_document(_read_yaml_bytes(content, filename), filename)


def _load_tool_catalog_document(
    raw: dict[str, Any], filename: str
) -> tuple[str, tuple[AuthorizedTool, ...]]:
    try:
        document = _ToolCatalogFileModel.model_validate(raw)
    except UnsupportedSchemaVersionError:
        raise
    except (TypeError, ValidationError, ValueError) as exc:
        raise MalformedYamlError(f"Tool catalog failed schema validation: {filename}") from exc
    tools = tuple(
        _authorized_tool(document.catalog_version, name, item)
        for name, item in sorted(document.tools.items())
    )
    return document.catalog_version, tools


def _authorized_tool(catalog_version: str, name: str, item: _ToolModel) -> AuthorizedTool:
    schema = item.input_schema.model_dump(exclude_none=True)
    schema_json = json.dumps(
        schema,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if len(schema_json.encode()) > 32_768:
        raise MalformedYamlError("Tool input schema exceeds the size limit")
    schema_digest = f"sha256:{hashlib.sha256(schema_json.encode()).hexdigest()}"
    output_schema_json = json.dumps(
        item.output_schema.model_dump(exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if len(output_schema_json.encode()) > 32_768:
        raise MalformedYamlError("Tool output schema exceeds the size limit")
    output_schema_digest = f"sha256:{hashlib.sha256(output_schema_json.encode()).hexdigest()}"
    definition_json = json.dumps(
        {
            "catalog_version": catalog_version,
            "description": item.description,
            "input_schema_digest": schema_digest,
            "name": name,
            "output_schema_digest": output_schema_digest,
            "risk_class": item.risk_class,
            "schema_version": item.schema_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return AuthorizedTool(
        name=name,
        description=item.description,
        risk_class=item.risk_class,
        schema_version=item.schema_version,
        input_schema_json=schema_json,
        input_schema_digest=schema_digest,
        output_schema_json=output_schema_json,
        output_schema_digest=output_schema_digest,
        definition_digest=f"sha256:{hashlib.sha256(definition_json.encode()).hexdigest()}",
        catalog_version=catalog_version,
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
        self._initialize(tuple(load_policy_file(path) for path in paths))

    @classmethod
    def from_bytes(cls, documents: tuple[tuple[str, bytes], ...]) -> "FilePolicyRepository":
        """Build from exact authenticated bytes to avoid a verify/parse path race."""
        instance = cls.__new__(cls)
        instance._initialize(
            tuple(load_policy_bytes(content, filename) for filename, content in documents)
        )
        return instance

    def _initialize(self, loaded: tuple[PolicySet, ...]) -> None:
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
        self._initialize(tuple(load_capability_file(path) for path in paths))

    @classmethod
    def from_bytes(
        cls, documents: tuple[tuple[str, bytes], ...]
    ) -> "FileProviderCapabilityRepository":
        """Build from exact authenticated bytes to avoid a verify/parse path race."""
        instance = cls.__new__(cls)
        instance._initialize(
            tuple(load_capability_bytes(content, filename) for filename, content in documents)
        )
        return instance

    def _initialize(self, loaded: tuple[ProviderCapabilityRecord, ...]) -> None:
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


class FileToolCatalogRepository:
    """Eagerly validated immutable organization tool catalog."""

    def __init__(self, path: Path) -> None:
        """Load one catalog and reject duplicate normalized names."""
        self._catalog_version, loaded = load_tool_catalog_file(path)
        self._items = {item.name: item for item in loaded}
        if len(self._items) != len(loaded):
            raise ConfigurationBoundaryError("Duplicate tool name")

    @classmethod
    def from_bytes(cls, content: bytes, filename: str) -> "FileToolCatalogRepository":
        """Build from exact bytes authenticated by a signed control pack."""
        instance = cls.__new__(cls)
        instance._catalog_version, loaded = load_tool_catalog_bytes(content, filename)
        instance._items = {item.name: item for item in loaded}
        if len(instance._items) != len(loaded):
            raise ConfigurationBoundaryError("Duplicate tool name")
        return instance

    @property
    def catalog_version(self) -> str:
        """Return the immutable tool-catalog release version."""
        return self._catalog_version

    def get(self, name: str) -> AuthorizedTool | None:
        """Resolve one trusted tool definition."""
        return self._items.get(name)

    def list(self) -> tuple[AuthorizedTool, ...]:
        """Return definitions in stable name order."""
        return tuple(self._items[name] for name in sorted(self._items))
