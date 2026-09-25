"""Deterministic AI-operation evaluation use case."""

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from regulated_ai.application.ports import (
    DataClassifier,
    EvaluationObserver,
    EvidenceRepository,
    PolicyRepository,
    ProviderCapabilityRepository,
    ToolCatalogRepository,
)
from regulated_ai.domain import (
    AssuranceLevel,
    AuthorizedTool,
    CapabilityRequirement,
    CapabilityState,
    DataItem,
    DecisionOutcome,
    EvaluationContext,
    EvaluationResult,
    EvidenceMetadata,
    Obligation,
    ObligationType,
    PolicyMatch,
    PolicyObligation,
    PolicyRule,
    ProviderCapability,
    ProviderCapabilitySnapshot,
    ProviderTarget,
    ToolRequest,
    strongest_outcome,
)


class EvaluationError(RuntimeError):
    """Base error carrying a stable, non-sensitive machine code."""

    code = "EVALUATION_FAILED"


class PolicySetNotFoundError(EvaluationError):
    """Requested immutable policy set does not exist."""

    code = "POLICY_SET_NOT_FOUND"


class ProviderRegistryError(EvaluationError):
    """Provider registry cannot support a policy-relevant evaluation."""

    code = "PROVIDER_REGISTRY_UNAVAILABLE"


class EvidencePersistenceError(EvaluationError):
    """Metadata evidence could not be persisted."""

    code = "EVIDENCE_PERSISTENCE_FAILED"


class InvalidEvaluationContextError(EvaluationError):
    """Normalized metadata contains an invalid or unsafe identifier."""

    code = "INVALID_EVALUATION_CONTEXT"


class ToolAuthorizationError(EvaluationError):
    """A requested tool is absent from or conflicts with the trusted catalog."""

    code = "TOOL_NOT_AUTHORIZED"


class NullEvaluationObserver:
    """Network-silent observer used when no metadata sink is configured."""

    def emit(self, event: str, metadata: Mapping[str, str]) -> None:
        """Discard an already sanitized event."""
        del event, metadata


class EvaluateAiOperation:
    """Classify, evaluate, verify capabilities and persist evidence."""

    def __init__(
        self,
        *,
        policies: PolicyRepository,
        capabilities: ProviderCapabilityRepository,
        evidence: EvidenceRepository,
        classifier: DataClassifier,
        tools: ToolCatalogRepository | None = None,
        observer: EvaluationObserver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind explicit ports and deterministic infrastructure inputs."""
        self._policies = policies
        self._capabilities = capabilities
        self._evidence = evidence
        self._classifier = classifier
        self._tools = tools
        self._observer = observer or NullEvaluationObserver()
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self, context: EvaluationContext) -> EvaluationResult:
        """Evaluate one normalized operation and store metadata-only evidence."""
        try:
            normalized_input = normalize_evaluation_context(context)
            self._emit("evaluation.started", correlation_id=normalized_input.correlation_id)
            authorized_tools = self._authorize_tools(normalized_input.tools)
            policy_set = self._policies.get(normalized_input.policy_set_version)
            if policy_set is None:
                raise PolicySetNotFoundError("Requested policy set is unavailable")
            classified = self._classify(normalized_input.data_items)
            normalized = replace(normalized_input, data_items=classified)
            matched = tuple(
                rule
                for rule in policy_set.rules
                if _matches(rule.match, normalized, authorized_tools)
            )
            for rule in matched:
                self._emit("policy.matched", policy_id=rule.identifier)

            obligations = _expand_obligations(matched, normalized, authorized_tools)
            outcomes = tuple(rule.decision for rule in matched if rule.decision is not None)
            reasons = {rule.reason_code for rule in matched if rule.reason_code is not None}
            capability_ids: set[str] = set()
            capability_snapshots: set[ProviderCapabilitySnapshot] = set()
            capability_outcomes: list[DecisionOutcome] = []

            registry_version = self._capabilities.registry_version
            for rule in matched:
                for requirement in rule.required_capabilities:
                    obligations.append(
                        Obligation(
                            type=ObligationType.REQUIRE_PROVIDER_CAPABILITY,
                            target=requirement.key,
                            reason_code="MANDATORY_PROVIDER_CAPABILITY",
                            control_objective_ids=rule.control_objective_ids,
                        )
                    )
                    for target in (normalized.provider, *normalized.fallback_providers):
                        fact = self._resolve_capability(target, requirement)
                        if fact is not None:
                            capability_ids.add(fact.identifier)
                            capability_snapshots.add(_capability_snapshot(fact, target))
                        failure = _capability_failure(
                            fact,
                            requirement,
                            normalized,
                            now=self._clock(),
                        )
                        if failure is not None:
                            capability_outcomes.append(DecisionOutcome.DENY)
                            reasons.add(failure)
                        self._emit(
                            "capability.resolved",
                            capability_key=requirement.key,
                            provider_target=target.identifier,
                            outcome=failure or "SATISFIED",
                        )

            obligations.append(
                Obligation(
                    type=ObligationType.REQUIRE_EVIDENCE,
                    target=None,
                    reason_code="EVIDENCE_REQUIRED",
                )
            )
            ordered_obligations = tuple(sorted(set(obligations), key=_obligation_sort_key))
            outcome = strongest_outcome((*outcomes, *capability_outcomes))
            reason_codes = tuple(sorted(reasons))
            matched_ids = tuple(sorted(rule.identifier for rule in matched))
            control_ids = tuple(
                sorted({item for rule in matched for item in rule.control_objective_ids})
            )
            capability_id_tuple = tuple(sorted(capability_ids))
            capability_snapshot_tuple = tuple(
                sorted(
                    capability_snapshots,
                    key=lambda item: (
                        item.provider_target,
                        item.capability_id,
                        item.record_version,
                    ),
                )
            )
            labels = tuple(sorted({label for item in classified for label in item.labels}, key=str))
            tool_ids = tuple(tool.identifier for tool in authorized_tools)
            tool_catalog_version = self._tools.catalog_version if self._tools is not None else None
            input_digest = _digest(_canonical_context(normalized, authorized_tools))
            output_payload = {
                "decision": outcome.value,
                "input_digest": input_digest,
                "matched_policy_ids": matched_ids,
                "obligations": [_canonical_obligation(item) for item in ordered_obligations],
                "policy_set_version": policy_set.identifier,
                "provider_capability_ids": capability_id_tuple,
                "provider_capability_snapshots": [
                    _canonical_capability_snapshot(item) for item in capability_snapshot_tuple
                ],
                "provider_registry_version": registry_version,
                "reason_codes": reason_codes,
                "tool_catalog_version": tool_catalog_version,
                "authorized_tool_ids": tool_ids,
            }
            output_digest = _digest(output_payload)
            evaluation_id = f"eval_{output_digest.removeprefix('sha256:')[:24]}"
            evidence_key = _digest(
                {
                    "input": input_digest,
                    "output": output_digest,
                    "policy": policy_set.identifier,
                    "registry": registry_version,
                }
            )
            evidence_id = f"ev_{evidence_key.removeprefix('sha256:')[:24]}"
            created_at = self._clock()
            event_payload = {
                "classification_labels": [item.value for item in labels],
                "control_objective_ids": control_ids,
                "created_at": created_at.isoformat(),
                "decision": outcome.value,
                "evidence_id": evidence_id,
                "input_digest": input_digest,
                "matched_policy_ids": matched_ids,
                "obligation_types": sorted({item.type.value for item in ordered_obligations}),
                "output_digest": output_digest,
                "policy_set_version": policy_set.identifier,
                "provider_capability_ids": capability_id_tuple,
                "provider_capability_snapshots": [
                    _canonical_capability_snapshot(item) for item in capability_snapshot_tuple
                ],
                "provider_registry_version": registry_version,
                "reason_codes": reason_codes,
                "tool_catalog_version": tool_catalog_version,
                "authorized_tool_ids": tool_ids,
            }
            evidence = EvidenceMetadata(
                evidence_id=evidence_id,
                created_at=created_at,
                correlation_id=normalized.correlation_id,
                decision=outcome,
                policy_set_version=policy_set.identifier,
                provider_registry_version=registry_version,
                matched_policy_ids=matched_ids,
                provider_capability_ids=capability_id_tuple,
                control_objective_ids=control_ids,
                obligation_types=tuple(
                    sorted({item.type for item in ordered_obligations}, key=str)
                ),
                classification_labels=labels,
                reason_codes=reason_codes,
                input_digest=input_digest,
                output_digest=output_digest,
                event_digest=_digest(event_payload),
                tool_catalog_version=tool_catalog_version,
                authorized_tool_ids=tool_ids,
                provider_capability_snapshots=capability_snapshot_tuple,
            )
            try:
                stored = self._evidence.save(evidence)
            except Exception as exc:
                raise EvidencePersistenceError("Evidence could not be persisted") from exc
            self._emit("evidence.persisted", evidence_id=stored.evidence_id)
            self._emit("decision.produced", decision=outcome.value)
            return EvaluationResult(
                evaluation_id=evaluation_id,
                decision=outcome,
                obligations=ordered_obligations,
                matched_policy_ids=matched_ids,
                provider_capability_ids=capability_id_tuple,
                reason_codes=reason_codes,
                policy_set_version=policy_set.identifier,
                provider_registry_version=registry_version,
                evidence_id=stored.evidence_id,
                input_digest=input_digest,
                output_digest=output_digest,
                authorized_tools=authorized_tools,
                tool_catalog_version=tool_catalog_version,
            )
        except Exception as exc:
            self._emit("evaluation.failed", error_type=type(exc).__name__)
            raise

    def _classify(self, items: tuple[DataItem, ...]) -> tuple[DataItem, ...]:
        return tuple(classified for item in items for classified in self._classifier.classify(item))

    def _resolve_capability(
        self, target: ProviderTarget, requirement: CapabilityRequirement
    ) -> ProviderCapability | None:
        record = self._capabilities.get(target)
        if record is None:
            return None
        if (
            record.registry_version != self._capabilities.registry_version
            or record.target.provider != target.provider
            or record.target.service != target.service
            or record.target.region != target.region
        ):
            raise ProviderRegistryError("Provider capability record is inconsistent")
        fact = record.capability(requirement.key)
        if fact is not None and (
            fact.provider != target.provider
            or fact.service != target.service
            or fact.region != target.region
            or fact.registry_version != record.registry_version
            or fact.record_version != record.record_version
            or fact.verified_at != record.verified_at
            or fact.source_urls != record.source_urls
        ):
            raise ProviderRegistryError("Provider capability fact is inconsistent")
        return fact

    def _authorize_tools(self, requests: tuple[ToolRequest, ...]) -> tuple[AuthorizedTool, ...]:
        if not requests:
            return ()
        if self._tools is None:
            raise ToolAuthorizationError("Requested tool is not authorized")
        names = [request.name for request in requests]
        if len(names) != len(set(names)):
            raise ToolAuthorizationError("Requested tool is not authorized")
        authorized: list[AuthorizedTool] = []
        for request in requests:
            definition = self._tools.get(request.name)
            if definition is None or (
                request.claimed_risk_class is not None
                and request.claimed_risk_class != definition.risk_class
            ):
                raise ToolAuthorizationError("Requested tool is not authorized")
            authorized.append(definition)
            self._emit(
                "tool.authorized",
                tool_name=definition.name,
                tool_schema_version=definition.schema_version,
            )
        return tuple(sorted(authorized, key=lambda item: item.name))

    def _emit(self, event: str, **metadata: str) -> None:
        try:
            self._observer.emit(event, metadata)
        except Exception:
            return


def _matches(
    match: PolicyMatch,
    context: EvaluationContext,
    authorized_tools: tuple[AuthorizedTool, ...],
) -> bool:
    scalar_checks = (
        (match.jurisdiction, context.jurisdiction.code),
        (match.sector, context.sector.name),
        (match.purpose, context.purpose.name),
        (match.operation_kind, context.operation_kind),
        (match.assurance_level, context.assurance_level),
        (match.provider, context.provider.provider),
        (match.service, context.provider.service),
        (match.region, context.provider.region),
    )
    if any(expected is not None and expected != actual for expected, actual in scalar_checks):
        return False
    labels = {label for item in context.data_items for label in item.labels}
    if match.data_class_any and not labels.intersection(match.data_class_any):
        return False
    risks = {tool.risk_class for tool in authorized_tools}
    return not match.tool_risk_class_any or bool(risks.intersection(match.tool_risk_class_any))


def _expand_obligations(
    rules: tuple[PolicyRule, ...],
    context: EvaluationContext,
    authorized_tools: tuple[AuthorizedTool, ...],
) -> list[Obligation]:
    expanded: list[Obligation] = []
    for rule in rules:
        for template in rule.obligations:
            targets = _obligation_targets(template, rule.match, context, authorized_tools)
            expanded.extend(
                Obligation(
                    type=template.type,
                    target=target,
                    reason_code=template.reason_code,
                    control_objective_ids=rule.control_objective_ids,
                    parameters=template.parameters,
                )
                for target in targets
            )
    return expanded


def _obligation_targets(
    template: PolicyObligation,
    match: PolicyMatch,
    context: EvaluationContext,
    authorized_tools: tuple[AuthorizedTool, ...],
) -> tuple[str | None, ...]:
    if template.target_class is not None:
        return tuple(
            item.field for item in context.data_items if template.target_class in item.labels
        )
    if template.target == "matched_tool":
        return tuple(
            tool.name for tool in authorized_tools if tool.risk_class in match.tool_risk_class_any
        )
    return (template.target,)


def _capability_failure(
    fact: ProviderCapability | None,
    requirement: CapabilityRequirement,
    context: EvaluationContext,
    *,
    now: datetime,
) -> str | None:
    if fact is None or fact.state is CapabilityState.UNKNOWN:
        return "PROVIDER_CAPABILITY_UNKNOWN"
    if fact.state is CapabilityState.UNSUPPORTED or fact.state not in requirement.accepted_states:
        return "PROVIDER_CAPABILITY_UNSUPPORTED"
    if (
        context.assurance_level is AssuranceLevel.HIGH
        and requirement.max_age_days is not None
        and (now.date() - fact.verified_at).days > requirement.max_age_days
    ):
        return "PROVIDER_CAPABILITY_STALE"
    required_conditions = set(fact.conditions) | set(requirement.required_condition_assertions)
    if required_conditions and any(
        condition not in fact.conditions or not context.assertion(condition)
        for condition in required_conditions
    ):
        return "PROVIDER_CAPABILITY_CONDITION_UNSATISFIED"
    return None


def _canonical_context(
    context: EvaluationContext, authorized_tools: tuple[AuthorizedTool, ...]
) -> dict[str, object]:
    return {
        "assurance_level": context.assurance_level.value,
        "correlation_id": context.correlation_id,
        "data": [
            {
                "field": item.field,
                "labels": [label.value for label in item.labels],
                "value_digest": _digest(item.value),
            }
            for item in sorted(context.data_items, key=lambda value: value.field)
        ],
        "fallback_providers": [_canonical_target(target) for target in context.fallback_providers],
        "jurisdiction": context.jurisdiction.code,
        "operation_kind": context.operation_kind,
        "organization_assertions": list(context.organization_assertions),
        "policy_set_version": context.policy_set_version,
        "provider": _canonical_target(context.provider),
        "purpose": context.purpose.name,
        "sector": context.sector.name,
        "tools": [
            {
                "catalog_version": tool.catalog_version,
                "definition_digest": tool.definition_digest,
                "name": tool.name,
                "risk_class": tool.risk_class,
                "schema_digest": tool.input_schema_digest,
                "schema_version": tool.schema_version,
            }
            for tool in authorized_tools
        ],
    }


def _canonical_obligation(obligation: Obligation) -> dict[str, object]:
    return {
        "control_objective_ids": obligation.control_objective_ids,
        "parameters": obligation.parameters,
        "reason_code": obligation.reason_code,
        "target": obligation.target,
        "type": obligation.type.value,
    }


def _capability_snapshot(
    fact: ProviderCapability, target: ProviderTarget
) -> ProviderCapabilitySnapshot:
    return ProviderCapabilitySnapshot(
        capability_id=fact.identifier,
        provider_target=target.identifier,
        key=fact.key,
        state=fact.state,
        conditions=tuple(sorted(fact.conditions)),
        verified_at=fact.verified_at,
        record_version=fact.record_version,
        registry_version=fact.registry_version,
        source_urls=tuple(sorted(fact.source_urls)),
    )


def _canonical_capability_snapshot(snapshot: ProviderCapabilitySnapshot) -> dict[str, object]:
    return {
        "capability_id": snapshot.capability_id,
        "conditions": snapshot.conditions,
        "key": snapshot.key,
        "provider_target": snapshot.provider_target,
        "record_version": snapshot.record_version,
        "registry_version": snapshot.registry_version,
        "source_urls": snapshot.source_urls,
        "state": snapshot.state.value,
        "verified_at": snapshot.verified_at.isoformat(),
    }


def _canonical_target(target: ProviderTarget) -> dict[str, str | None]:
    return {
        "model_family": target.model_family,
        "processing_mode": target.processing_mode,
        "provider": target.provider,
        "region": target.region,
        "service": target.service,
    }


_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]*\Z")


def normalize_evaluation_context(context: EvaluationContext) -> EvaluationContext:
    """Normalize and validate metadata identifiers at the application boundary."""
    return replace(
        context,
        correlation_id=_identifier(context.correlation_id),
        jurisdiction=replace(
            context.jurisdiction, code=_identifier(context.jurisdiction.code).upper()
        ),
        sector=replace(context.sector, name=_identifier(context.sector.name).casefold()),
        purpose=replace(context.purpose, name=_identifier(context.purpose.name).casefold()),
        operation_kind=_identifier(context.operation_kind).casefold(),
        provider=_normalize_target(context.provider),
        data_items=tuple(
            replace(item, field=_identifier(item.field)) for item in context.data_items
        ),
        tools=tuple(
            replace(
                tool,
                name=_identifier(tool.name),
                claimed_risk_class=(
                    None
                    if tool.claimed_risk_class is None
                    else _identifier(tool.claimed_risk_class).casefold()
                ),
            )
            for tool in context.tools
        ),
        policy_set_version=_identifier(context.policy_set_version),
        organization_assertions=tuple(
            sorted((_identifier(key), value) for key, value in context.organization_assertions)
        ),
        fallback_providers=tuple(
            _normalize_target(target) for target in context.fallback_providers
        ),
    )


def _normalize_target(target: ProviderTarget) -> ProviderTarget:
    return replace(
        target,
        provider=_identifier(target.provider).casefold(),
        service=_identifier(target.service).casefold(),
        region=None if target.region is None else _identifier(target.region).casefold(),
        model_family=None if target.model_family is None else _identifier(target.model_family),
        processing_mode=(
            None
            if target.processing_mode is None
            else _identifier(target.processing_mode).casefold()
        ),
    )


def _identifier(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > 128 or _SAFE_IDENTIFIER.fullmatch(normalized) is None:
        raise InvalidEvaluationContextError("Evaluation metadata contains an invalid identifier")
    return normalized


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _obligation_sort_key(obligation: Obligation) -> tuple[str, str, str]:
    return obligation.type.value, obligation.target or "", obligation.reason_code
