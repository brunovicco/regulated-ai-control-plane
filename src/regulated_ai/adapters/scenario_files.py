"""Strict metadata-only scenario-suite boundary for control-pack replay."""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.domain import (
    AssuranceLevel,
    ControlPackScenario,
    ControlPackScenarioSuite,
    DataClassification,
    DataItem,
    Jurisdiction,
    ProviderTarget,
    Purpose,
    Sector,
    ToolRequest,
)


class ScenarioSuiteError(ValueError):
    """A scenario suite failed strict metadata-only validation."""

    code = "SCENARIO_SUITE_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SuiteModel(_StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    version: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    evaluated_at: str = Field(min_length=1, max_length=64)

    @field_validator("evaluated_at")
    @classmethod
    def timezone_aware_timestamp(cls, value: str) -> str:
        parsed = _parse_timestamp(value)
        if parsed.utcoffset() is None:
            raise ValueError("scenario evaluation timestamp must include a timezone")
        return value


class _TargetModel(_StrictModel):
    provider: str = Field(min_length=1, max_length=128)
    service: str = Field(min_length=1, max_length=128)
    region: str | None = Field(default=None, min_length=1, max_length=128)
    model_family: str | None = Field(default=None, min_length=1, max_length=128)
    processing_mode: str | None = Field(default=None, min_length=1, max_length=128)


class _DataItemModel(_StrictModel):
    field: str = Field(min_length=1, max_length=128)
    labels: tuple[DataClassification, ...] = Field(min_length=1, max_length=16)

    @field_validator("labels")
    @classmethod
    def unique_labels(cls, value: tuple[DataClassification, ...]) -> tuple[DataClassification, ...]:
        if len(value) != len(set(value)):
            raise ValueError("scenario data labels must be unique")
        return value


class _ToolRequestModel(_StrictModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    claimed_risk_class: str | None = Field(default=None, min_length=1, max_length=128)


class _ScenarioModel(_StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    policy_set_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
    )
    jurisdiction: str = Field(min_length=1, max_length=128)
    sector: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=128)
    operation_kind: str = Field(min_length=1, max_length=128)
    assurance_level: AssuranceLevel
    provider: _TargetModel
    data: tuple[_DataItemModel, ...] = Field(default=(), max_length=128)
    organization_assertions: dict[str, bool] = Field(default_factory=dict, max_length=128)
    fallback_providers: tuple[_TargetModel, ...] = Field(default=(), max_length=8)
    tools: tuple[_ToolRequestModel, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def unique_metadata(self) -> "_ScenarioModel":
        fields = tuple(item.field for item in self.data)
        targets = tuple(_target_identity(item) for item in self.fallback_providers)
        if len(fields) != len(set(fields)):
            raise ValueError("scenario data fields must be unique")
        if len(targets) != len(set(targets)):
            raise ValueError("scenario fallback providers must be unique")
        tool_names = tuple(tool.name for tool in self.tools)
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("scenario tool names must be unique")
        if any(_SAFE_IDENTIFIER.fullmatch(key) is None for key in self.organization_assertions):
            raise ValueError("scenario assertion identifier is invalid")
        return self


class _ScenarioFileModel(_StrictModel):
    schema_version: Literal["1", "2"]
    suite: _SuiteModel
    scenarios: tuple[_ScenarioModel, ...] = Field(min_length=1, max_length=256)

    @field_validator("scenarios")
    @classmethod
    def unique_scenarios(cls, value: tuple[_ScenarioModel, ...]) -> tuple[_ScenarioModel, ...]:
        identifiers = tuple(item.id for item in value)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("scenario identifiers must be unique")
        return value

    @model_validator(mode="after")
    def tools_require_v2(self) -> "_ScenarioFileModel":
        if self.schema_version == "1" and any(item.tools for item in self.scenarios):
            raise ValueError("scenario tools require schema version 2")
        return self


_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")


def load_scenario_suite_file(path: Path) -> ControlPackScenarioSuite:
    """Load one bounded suite and bind its exact bytes to a SHA-256 digest."""
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ScenarioSuiteError("Scenario suite is unavailable") from exc
    if len(content) > 1_048_576:
        raise ScenarioSuiteError("Scenario suite exceeds the size limit")
    try:
        text = content.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw = yaml.safe_load(text)
        document = _ScenarioFileModel.model_validate(raw)
    except (UnicodeDecodeError, ValidationError, ValueError, yaml.YAMLError) as exc:
        raise ScenarioSuiteError("Scenario suite failed schema validation") from exc

    metadata = document.suite
    return ControlPackScenarioSuite(
        id=metadata.id,
        version=metadata.version,
        suite_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
        evaluated_at=_parse_timestamp(metadata.evaluated_at).astimezone(UTC),
        scenarios=tuple(_scenario(item) for item in document.scenarios),
    )


def _scenario(item: _ScenarioModel) -> ControlPackScenario:
    return ControlPackScenario(
        id=item.id,
        policy_set_id=item.policy_set_id,
        jurisdiction=Jurisdiction(item.jurisdiction),
        sector=Sector(item.sector),
        purpose=Purpose(item.purpose),
        operation_kind=item.operation_kind,
        assurance_level=item.assurance_level,
        provider=_target(item.provider),
        data_items=tuple(
            DataItem(field=data.field, value="", supplied_labels=data.labels) for data in item.data
        ),
        organization_assertions=tuple(sorted(item.organization_assertions.items())),
        fallback_providers=tuple(_target(target) for target in item.fallback_providers),
        tools=tuple(ToolRequest(tool.name, tool.claimed_risk_class) for tool in item.tools),
    )


def _target(item: _TargetModel) -> ProviderTarget:
    return ProviderTarget(
        provider=item.provider,
        service=item.service,
        region=item.region,
        model_family=item.model_family,
        processing_mode=item.processing_mode,
    )


def _target_identity(item: _TargetModel) -> tuple[str, str, str | None]:
    return item.provider, item.service, item.region


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("scenario evaluation timestamp is invalid") from exc


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("scenario suite keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("scenario suite contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)
