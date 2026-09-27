from pathlib import Path

import pytest

from regulated_ai.adapters import ScenarioSuiteError, load_scenario_suite_file
from regulated_ai.domain import DataClassification


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "scenarios.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _document(*, evaluated_at: str = "2026-09-25T12:00:00Z", extra: str = "") -> str:
    return f'''schema_version: "1"
suite:
  id: "test-suite"
  version: "1.0.0"
  evaluated_at: "{evaluated_at}"
scenarios:
  - id: "test-scenario"
    policy_set_id: "test-policy"
    jurisdiction: "BR"
    sector: "financial_services"
    purpose: "customer_support"
    operation_kind: "external_inference"
    assurance_level: "high"
    provider:
      provider: "test-provider"
      service: "test-service"
      region: "test-region"
    data:
      - field: "customer_document"
        labels: ["BRAZIL_CPF"]
{extra}'''


def test_loads_metadata_only_suite_with_digest_and_fixed_clock(tmp_path: Path) -> None:
    path = _write(tmp_path, _document())

    suite = load_scenario_suite_file(path)

    assert suite.id == "test-suite"
    assert suite.evaluated_at.isoformat() == "2026-09-25T12:00:00+00:00"
    assert suite.suite_digest.startswith("sha256:")
    assert suite.scenarios[0].data_items[0].value == ""
    assert suite.scenarios[0].data_items[0].labels == (DataClassification.BRAZIL_CPF,)


def test_schema_v2_loads_metadata_only_tool_requests(tmp_path: Path) -> None:
    document = _document(extra='    tools:\n      - name: "cards.read"\n').replace(
        'schema_version: "1"', 'schema_version: "2"'
    )

    suite = load_scenario_suite_file(_write(tmp_path, document))

    assert suite.scenarios[0].tools[0].name == "cards.read"


@pytest.mark.parametrize(
    "document",
    [
        _document(evaluated_at="2026-09-25T12:00:00"),
        _document(extra='        value: "raw-content"\n'),
        _document().replace('id: "test-scenario"', 'id: "test-scenario"\n    id: "duplicate"'),
    ],
)
def test_rejects_unfixed_clock_raw_values_and_duplicate_keys(tmp_path: Path, document: str) -> None:
    with pytest.raises(ScenarioSuiteError, match="schema validation"):
        load_scenario_suite_file(_write(tmp_path, document))
