from pathlib import Path

import pytest

from regulated_ai.adapters.yaml_files import (
    FileProviderCapabilityRepository,
    FileToolCatalogRepository,
    MalformedYamlError,
    UnsupportedSchemaVersionError,
    load_capability_file,
    load_policy_file,
    load_tool_catalog_bytes,
    load_tool_catalog_file,
)
from regulated_ai.domain import ProviderTarget


def test_example_files_load_with_versions_and_sources() -> None:
    root = Path(__file__).resolve().parents[2]
    policy = load_policy_file(root / "examples/policies/br-financial-external-inference.yaml")
    registry = FileProviderCapabilityRepository(
        (
            root / "examples/provider-capabilities/openai-responses.yaml",
            root / "examples/provider-capabilities/aws-bedrock.yaml",
        )
    )
    tools = FileToolCatalogRepository(root / "examples/tools/br-financial-tools.yaml")

    record = registry.get(ProviderTarget("openai", "responses_api", "global"))

    assert policy.identifier == "br-financial-demo@1.0.0"
    assert registry.registry_version == "2026-09-22.1"
    assert record is not None
    assert record.source_urls
    assert record.verified_at.isoformat() == "2026-09-22"
    assert len(registry.list()) == 2
    assert tools.catalog_version == "br-financial-tools@1.1.0"
    assert tools.get("cards.unblock") is not None
    assert tools.get("cards.unblock").risk_class == "high_impact_state_change"  # type: ignore[union-attr]


def test_authenticated_tool_catalog_bytes_are_parsed_without_reopening_path() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "examples/tools/br-financial-tools.yaml"

    version, tools = load_tool_catalog_bytes(path.read_bytes(), path.name)

    assert version == "br-financial-tools@1.1.0"
    assert tuple(item.name for item in tools) == ("cards.read", "cards.unblock")


def test_malformed_yaml_is_rejected_at_boundary(tmp_path: Path) -> None:
    path = tmp_path / "malformed.yaml"
    path.write_text("schema_version: '1'\nrules: [", encoding="utf-8")

    with pytest.raises(MalformedYamlError):
        load_policy_file(path)


def test_unsupported_policy_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "future.yaml"
    path.write_text("schema_version: '999'\npolicy_set: {}\nrules: []\n", encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError):
        load_policy_file(path)


def test_unknown_capability_fields_and_unsafe_sources_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "capability.yaml"
    path.write_text(
        """schema_version: "1"
registry_version: "test"
provider: "test"
service: "test"
verified_at: "2026-01-01"
record_version: 1
sources: ["http://not-secure.invalid"]
unexpected: true
capabilities:
  control:
    state: "supported"
""",
        encoding="utf-8",
    )

    with pytest.raises(MalformedYamlError):
        load_capability_file(path)


def test_open_or_unversioned_tool_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tools.yaml"
    path.write_text(
        """schema_version: "1"
catalog_version: "tools@test"
tools:
  cards.read:
    description: "Synthetic read tool."
    risk_class: "read_only"
    schema_version: "1"
    input_schema:
      type: "object"
      additionalProperties: true
      properties:
        token:
          type: "string"
""",
        encoding="utf-8",
    )

    with pytest.raises(MalformedYamlError):
        load_tool_catalog_file(path)


def test_duplicate_tool_catalog_keys_are_rejected_before_construction(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-tools.yaml"
    path.write_text(
        """schema_version: "1"
catalog_version: "tools@1"
catalog_version: "tools@2"
tools: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(MalformedYamlError):
        load_tool_catalog_file(path)


def test_tool_definition_digest_binds_description(tmp_path: Path) -> None:
    template = """schema_version: "1"
catalog_version: "tools@1"
tools:
  cards.read:
    description: "{description}"
    risk_class: "read_only"
    schema_version: "1"
    input_schema:
      type: "object"
      additionalProperties: false
      properties:
        token:
          type: "string"
    output_schema:
      type: "object"
      additionalProperties: false
      properties:
        status:
          type: "string"
          enum: ["OK"]
          classification: "INTERNAL"
          handling: "RETURN"
      required: ["status"]
"""
    first_path = tmp_path / "first.yaml"
    second_path = tmp_path / "second.yaml"
    first_path.write_text(
        template.format(description="First trusted description."), encoding="utf-8"
    )
    second_path.write_text(
        template.format(description="Second trusted description."), encoding="utf-8"
    )

    _, first = load_tool_catalog_file(first_path)
    _, second = load_tool_catalog_file(second_path)

    assert first[0].definition_digest != second[0].definition_digest


@pytest.mark.parametrize(
    ("classification", "handling", "enum_line"),
    [
        ("FINANCIAL", "RETURN", '          enum: ["OK"]\n'),
        ("AUTHENTICATION_SECRET", "MASK", ""),
        ("INTERNAL", "RETURN", ""),
    ],
)
def test_unsafe_tool_result_exposure_policy_is_rejected(
    tmp_path: Path, classification: str, handling: str, enum_line: str
) -> None:
    path = tmp_path / "unsafe-output.yaml"
    path.write_text(
        f'''schema_version: "1"
catalog_version: "tools@1"
tools:
  cards.read:
    description: "Synthetic read tool."
    risk_class: "read_only"
    schema_version: "1"
    input_schema:
      type: "object"
      additionalProperties: false
      properties:
        token:
          type: "string"
    output_schema:
      type: "object"
      additionalProperties: false
      properties:
        result:
          type: "string"
{enum_line}          classification: "{classification}"
          handling: "{handling}"
      required: ["result"]
''',
        encoding="utf-8",
    )

    with pytest.raises(MalformedYamlError):
        load_tool_catalog_file(path)
