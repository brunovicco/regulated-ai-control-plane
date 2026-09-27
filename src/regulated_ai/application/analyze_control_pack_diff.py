"""Deterministic semantic impact analysis for two verified control packs."""

from collections.abc import Callable, Iterable

from regulated_ai.domain import (
    ControlPackChange,
    ControlPackChangeKind,
    ControlPackChangeType,
    ControlPackDiffReport,
    ControlPackImpact,
    ControlPackRelease,
    PolicyRule,
    PolicySet,
    ProviderCapabilityRecord,
    ProviderTarget,
)


class ControlPackDiffError(ValueError):
    """Two releases cannot be compared safely."""

    code = "CONTROL_PACK_DIFF_INVALID"


class AnalyzeControlPackDiff:
    """Compare trusted domain records without executing policies or external calls."""

    def execute(
        self, base: ControlPackRelease, candidate: ControlPackRelease
    ) -> ControlPackDiffReport:
        """Return a stable conservative impact report for one pack lineage."""
        if base.identity.pack_id != candidate.identity.pack_id:
            raise ControlPackDiffError("Control-pack identifiers must match")

        policies = (*base.policy_sets, *candidate.policy_sets)
        changes = [
            *_policy_changes(base.policy_sets, candidate.policy_sets),
            *_provider_changes(base.provider_records, candidate.provider_records, policies),
            *_tool_changes(base, candidate),
        ]
        ordered = tuple(
            sorted(
                changes,
                key=lambda item: (item.kind.value, item.identifier, item.change_type.value),
            )
        )
        return ControlPackDiffReport(
            base=base.identity,
            candidate=candidate.identity,
            changes=ordered,
            version_reused=(
                base.identity.pack_version == candidate.identity.pack_version
                and base.identity.payload_digest != candidate.identity.payload_digest
            ),
            signing_key_changed=(base.identity.signing_key_id != candidate.identity.signing_key_id),
        )


def _policy_changes(
    base_items: tuple[PolicySet, ...], candidate_items: tuple[PolicySet, ...]
) -> tuple[ControlPackChange, ...]:
    base = _unique_index(base_items, lambda item: item.identifier, "policy set")
    candidate = _unique_index(candidate_items, lambda item: item.identifier, "policy set")
    changes: list[ControlPackChange] = []
    for identifier in sorted(base.keys() - candidate.keys()):
        changes.append(
            _change(
                ControlPackChangeKind.POLICY_SET,
                ControlPackChangeType.REMOVED,
                identifier,
                ControlPackImpact.DECISION,
            )
        )
    for identifier in sorted(candidate.keys() - base.keys()):
        changes.append(
            _change(
                ControlPackChangeKind.POLICY_SET,
                ControlPackChangeType.ADDED,
                identifier,
                ControlPackImpact.DECISION,
            )
        )
    for identifier in sorted(base.keys() & candidate.keys()):
        changes.extend(_one_policy_set_changes(base[identifier], candidate[identifier]))
    return tuple(changes)


def _one_policy_set_changes(base: PolicySet, candidate: PolicySet) -> tuple[ControlPackChange, ...]:
    changes: list[ControlPackChange] = []
    metadata_fields = _changed_fields(base, candidate, ("jurisdiction", "sector", "status"))
    if metadata_fields:
        changes.append(
            _change(
                ControlPackChangeKind.POLICY_SET,
                ControlPackChangeType.MODIFIED,
                base.identifier,
                ControlPackImpact.GOVERNANCE,
                metadata_fields,
            )
        )

    base_rules = _unique_index(base.rules, lambda item: item.identifier, "policy rule")
    candidate_rules = _unique_index(candidate.rules, lambda item: item.identifier, "policy rule")
    for identifier in sorted(base_rules.keys() - candidate_rules.keys()):
        changes.append(
            _change(
                ControlPackChangeKind.POLICY_RULE,
                ControlPackChangeType.REMOVED,
                f"{base.identifier}:{identifier}",
                ControlPackImpact.DECISION,
            )
        )
    for identifier in sorted(candidate_rules.keys() - base_rules.keys()):
        changes.append(
            _change(
                ControlPackChangeKind.POLICY_RULE,
                ControlPackChangeType.ADDED,
                f"{candidate.identifier}:{identifier}",
                ControlPackImpact.DECISION,
            )
        )
    for identifier in sorted(base_rules.keys() & candidate_rules.keys()):
        fields = _changed_fields(
            base_rules[identifier],
            candidate_rules[identifier],
            (
                "match",
                "decision",
                "obligations",
                "required_capabilities",
                "control_objective_ids",
                "regulatory_support_refs",
                "reason_code",
            ),
        )
        if fields:
            changes.append(
                _change(
                    ControlPackChangeKind.POLICY_RULE,
                    ControlPackChangeType.MODIFIED,
                    f"{base.identifier}:{identifier}",
                    _policy_rule_impact(fields),
                    fields,
                )
            )
    return tuple(changes)


def _provider_changes(
    base_items: tuple[ProviderCapabilityRecord, ...],
    candidate_items: tuple[ProviderCapabilityRecord, ...],
    policies: tuple[PolicySet, ...],
) -> tuple[ControlPackChange, ...]:
    base = _unique_index(base_items, lambda item: item.target.identifier, "provider target")
    candidate = _unique_index(
        candidate_items, lambda item: item.target.identifier, "provider target"
    )
    changes: list[ControlPackChange] = []
    for identifier in sorted(base.keys() - candidate.keys()):
        record = base[identifier]
        changes.append(
            _change(
                ControlPackChangeKind.PROVIDER_TARGET,
                ControlPackChangeType.REMOVED,
                identifier,
                ControlPackImpact.DECISION,
                dependent_policy_rule_ids=_dependent_policy_rules(
                    policies,
                    record.target,
                    tuple(item.key for item in record.capabilities),
                ),
            )
        )
    for identifier in sorted(candidate.keys() - base.keys()):
        record = candidate[identifier]
        changes.append(
            _change(
                ControlPackChangeKind.PROVIDER_TARGET,
                ControlPackChangeType.ADDED,
                identifier,
                ControlPackImpact.DECISION,
                dependent_policy_rule_ids=_dependent_policy_rules(
                    policies,
                    record.target,
                    tuple(item.key for item in record.capabilities),
                ),
            )
        )
    for identifier in sorted(base.keys() & candidate.keys()):
        changes.extend(
            _one_provider_target_changes(base[identifier], candidate[identifier], policies)
        )
    return tuple(changes)


def _tool_changes(
    base_release: ControlPackRelease, candidate_release: ControlPackRelease
) -> tuple[ControlPackChange, ...]:
    changes: list[ControlPackChange] = []
    if base_release.tool_catalog_version != candidate_release.tool_catalog_version:
        changes.append(
            _change(
                ControlPackChangeKind.TOOL_CATALOG,
                ControlPackChangeType.MODIFIED,
                "trusted-tool-catalog",
                ControlPackImpact.EVIDENCE,
                ("catalog_version",),
            )
        )
    base = _unique_index(base_release.tools, lambda item: item.name, "tool definition")
    candidate = _unique_index(candidate_release.tools, lambda item: item.name, "tool definition")
    for identifier in sorted(base.keys() - candidate.keys()):
        changes.append(
            _change(
                ControlPackChangeKind.TOOL_DEFINITION,
                ControlPackChangeType.REMOVED,
                identifier,
                ControlPackImpact.DECISION,
            )
        )
    for identifier in sorted(candidate.keys() - base.keys()):
        changes.append(
            _change(
                ControlPackChangeKind.TOOL_DEFINITION,
                ControlPackChangeType.ADDED,
                identifier,
                ControlPackImpact.DECISION,
            )
        )
    for identifier in sorted(base.keys() & candidate.keys()):
        fields = _changed_fields(
            base[identifier],
            candidate[identifier],
            (
                "description",
                "risk_class",
                "schema_version",
                "input_schema_digest",
                "output_schema_digest",
            ),
        )
        if fields:
            changes.append(
                _change(
                    ControlPackChangeKind.TOOL_DEFINITION,
                    ControlPackChangeType.MODIFIED,
                    identifier,
                    ControlPackImpact.DECISION,
                    fields,
                )
            )
    return tuple(changes)


def _one_provider_target_changes(
    base: ProviderCapabilityRecord,
    candidate: ProviderCapabilityRecord,
    policies: tuple[PolicySet, ...],
) -> tuple[ControlPackChange, ...]:
    base_facts = _unique_index(base.capabilities, lambda item: item.key, "provider capability")
    candidate_facts = _unique_index(
        candidate.capabilities, lambda item: item.key, "provider capability"
    )
    changes: list[ControlPackChange] = []
    for key in sorted(base_facts.keys() - candidate_facts.keys()):
        changes.append(
            _provider_capability_change(
                base.target,
                key,
                ControlPackChangeType.REMOVED,
                ControlPackImpact.DECISION,
                (),
                policies,
            )
        )
    for key in sorted(candidate_facts.keys() - base_facts.keys()):
        changes.append(
            _provider_capability_change(
                candidate.target,
                key,
                ControlPackChangeType.ADDED,
                ControlPackImpact.DECISION,
                (),
                policies,
            )
        )
    for key in sorted(base_facts.keys() & candidate_facts.keys()):
        fields = _changed_fields(
            base_facts[key],
            candidate_facts[key],
            (
                "state",
                "conditions",
                "verified_at",
                "record_version",
                "registry_version",
                "source_urls",
                "notes",
            ),
        )
        if fields:
            changes.append(
                _provider_capability_change(
                    base.target,
                    key,
                    ControlPackChangeType.MODIFIED,
                    _provider_capability_impact(fields),
                    fields,
                    policies,
                )
            )
    return tuple(changes)


def _provider_capability_change(
    target: ProviderTarget,
    key: str,
    change_type: ControlPackChangeType,
    impact: ControlPackImpact,
    changed_fields: tuple[str, ...],
    policies: tuple[PolicySet, ...],
) -> ControlPackChange:
    return _change(
        ControlPackChangeKind.PROVIDER_CAPABILITY,
        change_type,
        f"{target.identifier}:{key}",
        impact,
        changed_fields,
        _dependent_policy_rules(policies, target, (key,)),
    )


def _dependent_policy_rules(
    policies: tuple[PolicySet, ...], target: ProviderTarget, capability_keys: tuple[str, ...]
) -> tuple[str, ...]:
    keys = set(capability_keys)
    identifiers = {
        f"{policy.identifier}:{rule.identifier}"
        for policy in policies
        for rule in policy.rules
        if any(requirement.key in keys for requirement in rule.required_capabilities)
        and _rule_can_match_target(rule, target)
    }
    return tuple(sorted(identifiers))


def _rule_can_match_target(rule: PolicyRule, target: ProviderTarget) -> bool:
    match = rule.match
    return (
        (match.provider is None or match.provider == target.provider)
        and (match.service is None or match.service == target.service)
        and (match.region is None or match.region == target.region)
    )


def _policy_rule_impact(fields: tuple[str, ...]) -> ControlPackImpact:
    if set(fields) & {"match", "decision", "obligations", "required_capabilities"}:
        return ControlPackImpact.DECISION
    if set(fields) & {"control_objective_ids", "reason_code"}:
        return ControlPackImpact.EVIDENCE
    return ControlPackImpact.GOVERNANCE


def _provider_capability_impact(fields: tuple[str, ...]) -> ControlPackImpact:
    if set(fields) & {"state", "conditions", "verified_at"}:
        return ControlPackImpact.DECISION
    if set(fields) & {"record_version", "registry_version", "source_urls"}:
        return ControlPackImpact.EVIDENCE
    return ControlPackImpact.GOVERNANCE


def _change(
    kind: ControlPackChangeKind,
    change_type: ControlPackChangeType,
    identifier: str,
    impact: ControlPackImpact,
    changed_fields: tuple[str, ...] = (),
    dependent_policy_rule_ids: tuple[str, ...] = (),
) -> ControlPackChange:
    return ControlPackChange(
        kind=kind,
        change_type=change_type,
        identifier=identifier,
        impact=impact,
        changed_fields=changed_fields,
        dependent_policy_rule_ids=dependent_policy_rule_ids,
    )


def _changed_fields(base: object, candidate: object, fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in fields if getattr(base, name) != getattr(candidate, name))


def _unique_index[Item](
    items: Iterable[Item], key: Callable[[Item], str], label: str
) -> dict[str, Item]:
    indexed: dict[str, Item] = {}
    for item in items:
        identifier = key(item)
        if identifier in indexed:
            raise ControlPackDiffError(f"Duplicate {label} identifier")
        indexed[identifier] = item
    return indexed
