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


@pytest.mark.parametrize("provider", ["openai", "bedrock"])
def test_organizational_draft_requires_explicit_reviewed_provider_conditions(
    provider: str,
) -> None:
    profile = load_pilot_profile(_ROOT / f"examples/financial-pilot/{provider}.json")
    policies = FilePolicyRepository((_ROOT / "examples/financial-pilot/policy.yaml",))
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
    assert evaluator.execute(selected).decision is DecisionOutcome.DENY
    asserted = replace(
        selected,
        organization_assertions=tuple((name, True) for name in profile.organization_assertions),
    )
    assert evaluator.execute(asserted).decision is DecisionOutcome.ALLOW_WITH_TRANSFORMATION
    stale = EvaluateAiOperation(
        policies=policies,
        capabilities=records,
        evidence=MemoryEvidenceRepository(),
        classifier=DeterministicDataClassifier(),
        clock=lambda: NOW + timedelta(days=40),
    )
    assert stale.execute(asserted).decision is DecisionOutcome.DENY
    policy = policies.get(profile.policy_set_version)
    assert policy is not None
    assert policy.status == "draft"
