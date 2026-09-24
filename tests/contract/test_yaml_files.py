from pathlib import Path

import pytest

from regulated_ai.adapters.yaml_files import (
    FileProviderCapabilityRepository,
    MalformedYamlError,
    UnsupportedSchemaVersionError,
    load_capability_file,
    load_policy_file,
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

    record = registry.get(ProviderTarget("openai", "responses_api", "global"))

    assert policy.identifier == "br-financial-demo@1.0.0"
    assert registry.registry_version == "2026-09-22.1"
    assert record is not None
    assert record.source_urls
    assert record.verified_at.isoformat() == "2026-09-22"
    assert len(registry.list()) == 2


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
