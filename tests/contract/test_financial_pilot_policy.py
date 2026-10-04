from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from regulated_ai.adapters import (
    DeterministicDataClassifier,
    FilePolicyRepository,
    FileProviderCapabilityRepository,
)
from regulated_ai.adapters.pilot_profile import load_pilot_profile
from regulated_ai.application import EvaluateAiOperation
from regulated_ai.domain import DataClassification, DataItem, DecisionOutcome

from ..helpers import NOW, MemoryEvidenceRepository, MemoryToolCatalogRepository, context

_ROOT = Path(__file__).parents[2]


def _evaluate_profile(profile_directory: str, provider: str) -> DecisionOutcome:
    directory = _ROOT / f"examples/{profile_directory}"
    profile = load_pilot_profile(directory / f"{provider}.json")
    policies = FilePolicyRepository((directory / "policy.yaml",))
    records = FileProviderCapabilityRepository(
        tuple(sorted((_ROOT / "src/regulated_ai/resources/provider-capabilities").glob("*.yaml")))
    )
    evaluator = EvaluateAiOperation(
        policies=policies,
        capabilities=records,
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        tools=MemoryToolCatalogRepository(),
        clock=lambda: NOW,
    )
    selected = replace(
        context(
            data_items=(
                DataItem(
                    "customer_document",
                    "synthetic",
                    supplied_labels=(DataClassification.PERSONAL_DIRECT_IDENTIFIER,),
                ),
            )
        ),
        provider=profile.target,
        policy_set_version=profile.policy_set_version,
        organization_assertions=tuple(profile.organization_assertions.items()),
    )
    return evaluator.execute(selected).decision


@pytest.mark.parametrize("provider", ["openai", "bedrock"])
def test_poc_uses_demonstrable_provider_controls_without_organization_assertions(
    provider: str,
) -> None:
    assert (
        _evaluate_profile("financial-pilot", provider) is DecisionOutcome.ALLOW_WITH_TRANSFORMATION
    )

    policy = (_ROOT / "examples/financial-pilot/policy.yaml").read_text(encoding="utf-8")
    assert "store_false" in policy
    assert "iam_authorization" in policy
    assert "zero_data_retention" not in policy
    assert "aws_privatelink" not in policy


@pytest.mark.parametrize("provider", ["openai", "bedrock"])
def test_future_enterprise_profile_retains_stricter_conditional_controls(provider: str) -> None:
    assert _evaluate_profile("financial-pilot-enterprise", provider) is DecisionOutcome.DENY

    directory = _ROOT / "examples/financial-pilot-enterprise"
    profile = load_pilot_profile(directory / f"{provider}.json")
    policies = FilePolicyRepository((directory / "policy.yaml",))
    records = FileProviderCapabilityRepository(
        tuple(sorted((_ROOT / "src/regulated_ai/resources/provider-capabilities").glob("*.yaml")))
    )
    selected = replace(
        context(
            data_items=(
                DataItem(
                    "customer_document",
                    "synthetic",
                    supplied_labels=(DataClassification.PERSONAL_DIRECT_IDENTIFIER,),
                ),
            )
        ),
        provider=profile.target,
        policy_set_version=profile.policy_set_version,
        organization_assertions=tuple((name, True) for name in profile.organization_assertions),
    )
    evaluator = EvaluateAiOperation(
        policies=policies,
        capabilities=records,
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        tools=MemoryToolCatalogRepository(),
        clock=lambda: NOW,
    )
    assert evaluator.execute(selected).decision is DecisionOutcome.ALLOW_WITH_TRANSFORMATION

    stale = EvaluateAiOperation(
        policies=policies,
        capabilities=records,
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        tools=MemoryToolCatalogRepository(),
        clock=lambda: NOW + timedelta(days=40),
    )
    assert stale.execute(selected).decision is DecisionOutcome.DENY

    policy = (directory / "policy.yaml").read_text(encoding="utf-8")
    assert "zero_data_retention" in policy
    assert "aws_privatelink" in policy
