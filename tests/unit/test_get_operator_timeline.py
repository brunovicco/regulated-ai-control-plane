from dataclasses import replace
from datetime import timedelta

import pytest

from regulated_ai.application import (
    GetOperatorTimeline,
    OperatorTimelineIntegrityError,
    OperatorTimelineNotFoundError,
)
from regulated_ai.domain import (
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    OperatorAttentionCode,
    OperatorTimelineStageKind,
    ToolActionRecord,
    ToolActionStatus,
)

from ..helpers import NOW, MemoryEnforcementRepository, MemoryEvidenceRepository


class _MemoryActionRepository:
    def __init__(self, items: tuple[ToolActionRecord, ...] = ()) -> None:
        self.items = {item.action_id: item for item in items}

    def save(self, record: ToolActionRecord) -> ToolActionRecord:
        self.items[record.action_id] = record
        return record

    def claim_execution(self, record: ToolActionRecord) -> tuple[ToolActionRecord, bool]:
        return record, False

    def get(self, action_id: str) -> ToolActionRecord | None:
        return self.items.get(action_id)

    def list_for_enforcement(
        self, enforcement_id: str, *, limit: int
    ) -> tuple[ToolActionRecord, ...]:
        matching = sorted(
            (item for item in self.items.values() if item.enforcement_id == enforcement_id),
            key=lambda item: (item.created_at, item.action_id),
        )
        return tuple(matching[:limit])


def _evidence() -> EvidenceMetadata:
    return EvidenceMetadata(
        evidence_id="ev_operator_test",
        created_at=NOW,
        correlation_id="correlation-operator-test",
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        policy_set_version="policy@test",
        provider_registry_version="registry@test",
        matched_policy_ids=("rule@test",),
        provider_capability_ids=("provider.control",),
        control_objective_ids=("CONTROL.TEST",),
        obligation_types=(),
        classification_labels=(),
        reason_codes=("TEST",),
        input_digest=f"sha256:{'1' * 64}",
        output_digest=f"sha256:{'2' * 64}",
        event_digest=f"sha256:{'3' * 64}",
        tool_catalog_version="tools@test",
        authorized_tool_ids=("cards.unblock@1.1.0",),
    )


def _enforcement(status: EnforcementStatus = EnforcementStatus.EXECUTED) -> EnforcementRecord:
    return EnforcementRecord(
        enforcement_id="enf_operator_test",
        created_at=NOW,
        evaluation_id="eval_operator_test",
        evaluation_evidence_id="ev_operator_test",
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        status=status,
        policy_set_version="policy@test",
        provider_registry_version="registry@test",
        provider_target="provider.service.region",
        transformation_receipts=(),
        reason_codes=(),
        input_digest=f"sha256:{'1' * 64}",
        output_digest=f"sha256:{'4' * 64}",
        provider_execution_id="mockexec_operator_test",
    )


def _action(index: int, status: ToolActionStatus) -> ToolActionRecord:
    return ToolActionRecord(
        action_id=f"act_operator_{index:03d}",
        created_at=NOW + timedelta(seconds=index),
        enforcement_id="enf_operator_test",
        evaluation_id="eval_operator_test",
        call_id=f"call_operator_{index:03d}",
        tool_name="cards.unblock",
        tool_schema_version="1.1.0",
        tool_schema_digest=f"sha256:{'5' * 64}",
        arguments_digest=f"sha256:{'6' * 64}",
        workload_identity="workload.operator-test",
        idempotency_key_digest=f"sha256:{'7' * 64}",
        action_digest=f"sha256:{index:064x}",
        status=status,
        output_schema_digest=f"sha256:{'8' * 64}",
    )


def _service(
    *,
    enforcement: EnforcementRecord | None = None,
    evidence: EvidenceMetadata | None = None,
    actions: tuple[ToolActionRecord, ...] = (),
) -> GetOperatorTimeline:
    evidence_repository = MemoryEvidenceRepository()
    if evidence is not None:
        evidence_repository.items[evidence.evidence_id] = evidence
    enforcement_repository = MemoryEnforcementRepository()
    if enforcement is not None:
        enforcement_repository.items[enforcement.enforcement_id] = enforcement
    return GetOperatorTimeline(
        evidence=evidence_repository,
        enforcement=enforcement_repository,
        actions=_MemoryActionRepository(actions),
    )


def test_operator_timeline_orders_stages_and_aggregates_attention() -> None:
    timeline = _service(
        enforcement=_enforcement(),
        evidence=_evidence(),
        actions=(
            _action(3, ToolActionStatus.RESULT_REJECTED),
            _action(1, ToolActionStatus.WAITING_APPROVAL),
            _action(2, ToolActionStatus.RECONCILIATION_REQUIRED),
        ),
    ).execute("enf_operator_test")

    assert tuple(stage.kind for stage in timeline.stages) == (
        OperatorTimelineStageKind.EVALUATION,
        OperatorTimelineStageKind.ENFORCEMENT,
        OperatorTimelineStageKind.TOOL_ACTION,
        OperatorTimelineStageKind.TOOL_ACTION,
        OperatorTimelineStageKind.TOOL_ACTION,
    )
    assert tuple(stage.record_id for stage in timeline.stages[2:]) == (
        "act_operator_001",
        "act_operator_002",
        "act_operator_003",
    )
    assert timeline.attention_codes == (
        OperatorAttentionCode.TOOL_ACTION_APPROVAL_REQUIRED,
        OperatorAttentionCode.TOOL_ACTION_RECONCILIATION_REQUIRED,
        OperatorAttentionCode.TOOL_RESULT_REJECTED,
    )
    assert not timeline.actions_truncated


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (
            EnforcementStatus.WAITING_APPROVAL,
            OperatorAttentionCode.ENFORCEMENT_APPROVAL_REQUIRED,
        ),
        (
            EnforcementStatus.DISPATCHED,
            OperatorAttentionCode.ENFORCEMENT_RECONCILIATION_REQUIRED,
        ),
        (
            EnforcementStatus.TRANSFORMATION_FAILED,
            OperatorAttentionCode.ENFORCEMENT_TRANSFORMATION_FAILED,
        ),
        (
            EnforcementStatus.EXECUTION_FAILED,
            OperatorAttentionCode.ENFORCEMENT_EXECUTION_FAILED,
        ),
    ],
)
def test_operator_timeline_maps_enforcement_attention(
    status: EnforcementStatus, code: OperatorAttentionCode
) -> None:
    timeline = _service(enforcement=_enforcement(status), evidence=_evidence()).execute(
        "enf_operator_test"
    )

    assert timeline.attention_codes == (code,)


def test_operator_timeline_fails_closed_for_missing_or_inconsistent_metadata() -> None:
    with pytest.raises(OperatorTimelineNotFoundError):
        _service().execute("enf_operator_test")

    inconsistent = replace(_evidence(), policy_set_version="different-policy@test")
    with pytest.raises(OperatorTimelineIntegrityError):
        _service(enforcement=_enforcement(), evidence=inconsistent).execute("enf_operator_test")


def test_operator_timeline_is_bounded_and_reports_truncation() -> None:
    actions = tuple(_action(index, ToolActionStatus.EXECUTED) for index in range(129))

    timeline = _service(enforcement=_enforcement(), evidence=_evidence(), actions=actions).execute(
        "enf_operator_test"
    )

    assert len(timeline.stages) == 130
    assert timeline.actions_truncated
    assert timeline.attention_codes == (OperatorAttentionCode.ACTION_LIST_TRUNCATED,)
