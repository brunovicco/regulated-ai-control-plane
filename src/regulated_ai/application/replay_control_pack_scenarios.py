"""Deterministic scenario replay across two verified control-pack releases."""

import hashlib
import json

from regulated_ai.application.evaluate_operation import EvaluateAiOperation, EvaluationError
from regulated_ai.domain import (
    ControlPackImpact,
    ControlPackRelease,
    ControlPackScenario,
    ControlPackScenarioReplayReport,
    ControlPackScenarioSuite,
    DataItem,
    EvaluationContext,
    EvidenceMetadata,
    Obligation,
    PolicySet,
    ProviderCapabilityRecord,
    ProviderTarget,
    ScenarioReplayOutcome,
    ScenarioReplayResult,
    ScenarioReplayStatus,
)


class ControlPackScenarioReplayError(ValueError):
    """Scenario replay inputs cannot be evaluated safely."""

    code = "CONTROL_PACK_SCENARIO_REPLAY_INVALID"


class ReplayControlPackScenarios:
    """Evaluate one metadata-only suite against an approved base and candidate."""

    def execute(
        self,
        base: ControlPackRelease,
        candidate: ControlPackRelease,
        suite: ControlPackScenarioSuite,
    ) -> ControlPackScenarioReplayReport:
        """Return stable observed impact without external calls or persistent evidence."""
        if base.identity.pack_id != candidate.identity.pack_id:
            raise ControlPackScenarioReplayError("Control-pack identifiers must match")
        if not suite.scenarios:
            raise ControlPackScenarioReplayError("Scenario suite must not be empty")
        if suite.evaluated_at.utcoffset() is None:
            raise ControlPackScenarioReplayError(
                "Scenario evaluation timestamp must be timezone-aware"
            )
        scenario_ids = tuple(item.id for item in suite.scenarios)
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ControlPackScenarioReplayError("Scenario identifiers must be unique")
        if any(item.value for scenario in suite.scenarios for item in scenario.data_items):
            raise ControlPackScenarioReplayError("Scenario data values are not allowed")

        base_evaluator = _ReleaseEvaluator(base, suite)
        candidate_evaluator = _ReleaseEvaluator(candidate, suite)
        results = tuple(
            _compare(
                scenario.id,
                base_evaluator.evaluate(scenario),
                candidate_evaluator.evaluate(scenario),
            )
            for scenario in sorted(suite.scenarios, key=lambda item: item.id)
        )
        if any(item.base.status is ScenarioReplayStatus.FAILED_CLOSED for item in results):
            raise ControlPackScenarioReplayError("Approved base failed scenario evaluation")
        return ControlPackScenarioReplayReport(
            base=base.identity,
            candidate=candidate.identity,
            suite_id=suite.id,
            suite_version=suite.version,
            suite_digest=suite.suite_digest,
            evaluated_at=suite.evaluated_at,
            results=results,
        )


class _ReleaseEvaluator:
    def __init__(self, release: ControlPackRelease, suite: ControlPackScenarioSuite) -> None:
        self._policies = _ReleasePolicyRepository(release.policy_sets)
        capabilities = _ReleaseCapabilityRepository(release.provider_records)
        self._evaluator = EvaluateAiOperation(
            policies=self._policies,
            capabilities=capabilities,
            evidence=_DiscardingEvidenceRepository(),
            classifier=_MetadataOnlyClassifier(),
            clock=lambda: suite.evaluated_at,
        )

    def evaluate(self, scenario: ControlPackScenario) -> ScenarioReplayOutcome:
        policy, resolution_error = self._policies.resolve_logical_id(scenario.policy_set_id)
        if policy is None:
            return _failed_outcome(resolution_error or "POLICY_SET_NOT_FOUND")
        context = EvaluationContext(
            correlation_id=f"replay.{scenario.id}",
            jurisdiction=scenario.jurisdiction,
            sector=scenario.sector,
            purpose=scenario.purpose,
            operation_kind=scenario.operation_kind,
            assurance_level=scenario.assurance_level,
            provider=scenario.provider,
            data_items=scenario.data_items,
            tools=(),
            policy_set_version=policy.identifier,
            organization_assertions=scenario.organization_assertions,
            fallback_providers=scenario.fallback_providers,
        )
        try:
            result = self._evaluator.execute(context)
        except EvaluationError as exc:
            return _failed_outcome(exc.code)
        return ScenarioReplayOutcome(
            status=ScenarioReplayStatus.EVALUATED,
            decision=result.decision,
            obligation_types=tuple(item.type for item in result.obligations),
            obligations_digest=_obligations_digest(result.obligations),
            matched_policy_ids=result.matched_policy_ids,
            provider_capability_ids=result.provider_capability_ids,
            reason_codes=result.reason_codes,
            policy_set_version=result.policy_set_version,
            provider_registry_version=result.provider_registry_version,
            output_digest=result.output_digest,
        )


class _ReleasePolicyRepository:
    def __init__(self, policies: tuple[PolicySet, ...]) -> None:
        self._by_identifier = {item.identifier: item for item in policies}
        if not policies or len(self._by_identifier) != len(policies):
            raise ControlPackScenarioReplayError("Release policy sets must be unique")
        logical: dict[str, list[PolicySet]] = {}
        for policy in policies:
            logical.setdefault(policy.id, []).append(policy)
        self._by_logical_id = logical

    def get(self, identifier: str) -> PolicySet | None:
        return self._by_identifier.get(identifier)

    def resolve_logical_id(self, identifier: str) -> tuple[PolicySet | None, str | None]:
        matches = self._by_logical_id.get(identifier, [])
        if not matches:
            return None, "POLICY_SET_NOT_FOUND"
        if len(matches) != 1:
            return None, "POLICY_SET_AMBIGUOUS"
        return matches[0], None


class _ReleaseCapabilityRepository:
    def __init__(self, records: tuple[ProviderCapabilityRecord, ...]) -> None:
        versions = {item.registry_version for item in records}
        if not records or len(versions) != 1:
            raise ControlPackScenarioReplayError(
                "Release provider records must share one registry version"
            )
        self._registry_version = next(iter(versions))
        self._items = {
            (item.target.provider, item.target.service, item.target.region): item
            for item in records
        }
        if len(self._items) != len(records):
            raise ControlPackScenarioReplayError("Release provider targets must be unique")

    @property
    def registry_version(self) -> str:
        return self._registry_version

    def get(self, target: ProviderTarget) -> ProviderCapabilityRecord | None:
        return self._items.get((target.provider, target.service, target.region))

    def list(self) -> tuple[ProviderCapabilityRecord, ...]:
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


class _MetadataOnlyClassifier:
    def classify(self, item: DataItem) -> tuple[DataItem, ...]:
        return (item,)


class _DiscardingEvidenceRepository:
    def save(self, evidence: EvidenceMetadata) -> EvidenceMetadata:
        return evidence

    def get(self, evidence_id: str) -> EvidenceMetadata | None:
        del evidence_id
        return None


def _failed_outcome(error_code: str) -> ScenarioReplayOutcome:
    return ScenarioReplayOutcome(
        status=ScenarioReplayStatus.FAILED_CLOSED,
        decision=None,
        obligation_types=(),
        obligations_digest=None,
        matched_policy_ids=(),
        provider_capability_ids=(),
        reason_codes=(),
        policy_set_version=None,
        provider_registry_version=None,
        output_digest=None,
        error_code=error_code,
    )


def _compare(
    scenario_id: str,
    base: ScenarioReplayOutcome,
    candidate: ScenarioReplayOutcome,
) -> ScenarioReplayResult:
    fields = (
        "status",
        "decision",
        "obligations_digest",
        "matched_policy_ids",
        "provider_capability_ids",
        "reason_codes",
        "policy_set_version",
        "provider_registry_version",
        "output_digest",
        "error_code",
    )
    changed = tuple(field for field in fields if getattr(base, field) != getattr(candidate, field))
    decision_fields = {"status", "decision", "obligations_digest", "error_code"}
    impact = None
    if decision_fields.intersection(changed):
        impact = ControlPackImpact.DECISION
    elif changed:
        impact = ControlPackImpact.EVIDENCE
    return ScenarioReplayResult(
        scenario_id=scenario_id,
        base=base,
        candidate=candidate,
        changed_fields=changed,
        impact=impact,
    )


def _obligations_digest(obligations: tuple[Obligation, ...]) -> str:
    payload = [
        {
            "control_objective_ids": item.control_objective_ids,
            "parameters": item.parameters,
            "reason_code": item.reason_code,
            "target": item.target,
            "type": item.type.value,
        }
        for item in obligations
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
