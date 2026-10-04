from pathlib import Path
from xml.etree import ElementTree

import pytest
from scripts.report_financial_pilot_ci import report_results


def _results(path: Path, *, failure: str | None = None, missing: bool = False) -> Path:
    root = ElementTree.Element("testsuite")
    names = [
        "test_enforcement_claim_has_one_winner_across_connections",
        "test_action_claim_has_one_winner_across_connections",
        "test_decision_approval_consumption_and_claim_are_atomic",
        "test_signed_action_approval_is_consumed_by_one_concurrent_claim",
        *[
            f"test_signed_reconciliation_is_atomic_idempotent_and_rejects_conflicting_outcome[{outcome}]"
            for outcome in ("EXECUTED", "NOT_EXECUTED")
        ],
        *[
            f"test_financial_pilot_identity_gateway_approval_and_recovery[{outcome}-{provider}]"
            for outcome in ("success", "EXECUTED", "NOT_EXECUTED")
            for provider in ("openai", "aws")
        ],
    ]
    for name in names[:-1] if missing else names:
        case = ElementTree.SubElement(
            root, "testcase", classname="tests.integration.test_pilot", name=name
        )
        if failure:
            ElementTree.SubElement(case, failure).text = "sensitive failure detail sentinel"
    ElementTree.ElementTree(root).write(path, encoding="utf-8")
    return path


def test_ci_summary_distinguishes_real_database_from_simulated_external_boundaries(
    tmp_path: Path,
) -> None:
    result = report_results(_results(tmp_path / "results.xml"), "1" * 40)
    assert result["status"] == "POSTGRES_CI_VERIFIED"
    assert result["external_provider_mode"] == "SIMULATED"
    assert result["observed_cases"] == 12


@pytest.mark.parametrize("failure", ["skipped", "error", "failure"])
def test_ci_evidence_cannot_hide_skips_or_failures(tmp_path: Path, failure: str) -> None:
    result = report_results(_results(tmp_path / "results.xml", failure=failure), "1" * 40)
    assert result["status"] == "POSTGRES_CI_BLOCKED"
    assert "sensitive failure detail" not in repr(result)


def test_ci_requires_all_cases_and_rejects_entities(tmp_path: Path) -> None:
    path = _results(tmp_path / "results.xml", missing=True)
    assert report_results(path, "1" * 40)["status"] == "POSTGRES_CI_BLOCKED"
    path.write_text('<!DOCTYPE testsuite [<!ENTITY x "sentinel">]><testsuite>&x;</testsuite>')
    with pytest.raises(ValueError):
        report_results(path, "1" * 40)
