from dataclasses import replace
from datetime import date, timedelta

import pytest

from regulated_ai.application import (
    GetOperatorTimeline,
    OperatorTimelineIntegrityError,
    OperatorTimelineNotFoundError,
)
from regulated_ai.domain import (
    ActionApprovalReceipt,
    ApprovalReceipt,
    CapabilityState,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ObligationType,
    OperatorAttentionCode,
    OperatorLifecycleEvent,
    OperatorLifecycleEventSource,
    OperatorTimelineStageKind,
    ProviderCapabilitySnapshot,
    ToolActionRecord,
    ToolActionStatus,
    TransformationReceipt,
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


class _MemoryEventRepository:
    def __init__(self, items: tuple[OperatorLifecycleEvent, ...] = ()) -> None:
        self.items = items

    def list_for_timeline(
        self,
        *,
        enforcement_id: str,
        evidence_id: str,
        limit: int,
    ) -> tuple[OperatorLifecycleEvent, ...]:
        del enforcement_id, evidence_id
        return self.items[:limit]


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


def _event(
    sequence: int,
    *,
    kind: OperatorTimelineStageKind = OperatorTimelineStageKind.TOOL_ACTION,
    source: OperatorLifecycleEventSource = OperatorLifecycleEventSource.TRANSITION,
) -> OperatorLifecycleEvent:
    is_evaluation = kind is OperatorTimelineStageKind.EVALUATION
    is_enforcement = kind is OperatorTimelineStageKind.ENFORCEMENT
    return OperatorLifecycleEvent(
        sequence=sequence,
        event_id=f"ole_{sequence:020d}",
        recorded_at=NOW + timedelta(seconds=sequence),
        source=source,
        kind=kind,
        record_id=(
            "ev_operator_test"
            if is_evaluation
            else "enf_operator_test"
            if is_enforcement
            else f"act_operator_{sequence:03d}"
        ),
        enforcement_id=None if is_evaluation else "enf_operator_test",
        status=(
            DecisionOutcome.REQUIRE_APPROVAL.value
            if is_evaluation
            else EnforcementStatus.EXECUTED.value
            if is_enforcement
            else ToolActionStatus.EXECUTED.value
        ),
    )


def _service(
    *,
    enforcement: EnforcementRecord | None = None,
    evidence: EvidenceMetadata | None = None,
    actions: tuple[ToolActionRecord, ...] = (),
    events: tuple[OperatorLifecycleEvent, ...] = (),
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
        events=_MemoryEventRepository(events),
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
    assert not timeline.provider_context_complete


def test_operator_timeline_exposes_control_context_without_actor_identity() -> None:
    evidence = replace(
        _evidence(),
        previous_event_digest=f"sha256:{'9' * 64}",
        provider_capability_snapshots=(
            ProviderCapabilitySnapshot(
                capability_id="provider.control",
                provider_target="provider.service.region",
                key="control",
                state=CapabilityState.SUPPORTED,
                conditions=(),
                verified_at=date(2026, 9, 22),
                record_version="1",
                registry_version="registry@test",
                source_urls=("https://provider.invalid/documentation",),
            ),
        ),
    )
    approval = ApprovalReceipt(
        approval_id="approval-operator-test",
        actor_id="actor-must-not-be-copied",
        decision_digest=evidence.output_digest,
        enforcement_id="enf_operator_test",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
        consumed_at=NOW,
    )
    transformation = TransformationReceipt(
        receipt_id="tr_operator_test",
        type=ObligationType.TOKENIZE,
        target="customer_document",
        input_digest=f"sha256:{'a' * 64}",
        output_digest=f"sha256:{'b' * 64}",
        reason_code="MINIMIZE_EXTERNAL_IDENTIFIER",
    )
    enforcement = replace(
        _enforcement(),
        approval_receipt=approval,
        transformation_receipts=(transformation,),
        reason_codes=("ENFORCEMENT_COMPLETE",),
    )

    timeline = _service(enforcement=enforcement, evidence=evidence).execute("enf_operator_test")

    assert timeline.matched_policy_ids == ("rule@test",)
    assert timeline.provider_capability_ids == ("provider.control",)
    assert timeline.provider_context_complete
    assert timeline.provider_capability_snapshots[0].verified_at == date(2026, 9, 22)
    assert timeline.control_objective_ids == ("CONTROL.TEST",)
    assert timeline.decision_reason_codes == ("TEST",)
    assert timeline.enforcement_reason_codes == ("ENFORCEMENT_COMPLETE",)
    assert timeline.authorized_tool_ids == ("cards.unblock@1.1.0",)
    assert timeline.provider_target == "provider.service.region"
    assert timeline.transformation_receipts == (transformation,)
    assert timeline.approval is not None
    assert timeline.approval.approval_id == "approval-operator-test"
    assert not hasattr(timeline.approval, "actor_id")
    assert timeline.previous_event_digest == f"sha256:{'9' * 64}"
    assert timeline.stages[1].approval_recorded


def test_operator_timeline_rejects_inconsistent_approval_metadata() -> None:
    evidence = _evidence()
    approval = ApprovalReceipt(
        approval_id="approval-operator-test",
        actor_id="actor-test",
        decision_digest=f"sha256:{'0' * 64}",
        enforcement_id="enf_operator_test",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
        consumed_at=NOW,
    )

    with pytest.raises(OperatorTimelineIntegrityError):
        _service(
            enforcement=replace(_enforcement(), approval_receipt=approval),
            evidence=evidence,
        ).execute("enf_operator_test")


def test_operator_timeline_rejects_duplicate_provider_snapshot_identity() -> None:
    first = ProviderCapabilitySnapshot(
        capability_id="provider.control",
        provider_target="provider.service.region",
        key="control",
        state=CapabilityState.SUPPORTED,
        conditions=(),
        verified_at=date(2026, 9, 22),
        record_version="1",
        registry_version="registry@test",
        source_urls=("https://provider.invalid/documentation",),
    )
    evidence = replace(
        _evidence(),
        provider_capability_snapshots=(
            first,
            replace(
                first,
                source_urls=("https://provider.invalid/conflicting-documentation",),
            ),
        ),
    )

    with pytest.raises(OperatorTimelineIntegrityError):
        _service(enforcement=_enforcement(), evidence=evidence).execute("enf_operator_test")


def test_operator_timeline_rejects_inconsistent_action_approval_metadata() -> None:
    action = _action(1, ToolActionStatus.EXECUTED)
    approval = ActionApprovalReceipt(
        approval_id="action-approval-operator-test",
        actor_id="actor-test",
        action_digest=f"sha256:{'0' * 64}",
        action_id=action.action_id,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
        consumed_at=NOW,
    )

    with pytest.raises(OperatorTimelineIntegrityError):
        _service(
            enforcement=_enforcement(),
            evidence=_evidence(),
            actions=(replace(action, approval_receipt=approval),),
        ).execute("enf_operator_test")


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


def test_operator_timeline_reports_complete_transition_history() -> None:
    events = (
        _event(1, kind=OperatorTimelineStageKind.EVALUATION),
        _event(2, kind=OperatorTimelineStageKind.ENFORCEMENT),
    )

    timeline = _service(enforcement=_enforcement(), evidence=_evidence(), events=events).execute(
        "enf_operator_test"
    )

    assert timeline.lifecycle_events == events
    assert timeline.history_complete
    assert not timeline.events_truncated


def test_operator_timeline_rejects_unordered_lifecycle_events() -> None:
    events = (
        _event(2, kind=OperatorTimelineStageKind.EVALUATION),
        _event(1, kind=OperatorTimelineStageKind.ENFORCEMENT),
    )

    with pytest.raises(OperatorTimelineIntegrityError):
        _service(enforcement=_enforcement(), evidence=_evidence(), events=events).execute(
            "enf_operator_test"
        )


def test_operator_timeline_marks_event_truncation_incomplete() -> None:
    events = tuple(_event(sequence) for sequence in range(1, 258))

    timeline = _service(enforcement=_enforcement(), evidence=_evidence(), events=events).execute(
        "enf_operator_test"
    )

    assert len(timeline.lifecycle_events) == 256
    assert not timeline.history_complete
    assert timeline.events_truncated
    assert timeline.attention_codes == (OperatorAttentionCode.EVENT_LIST_TRUNCATED,)


def test_operator_timeline_marks_migration_baseline_incomplete() -> None:
    baseline = replace(_event(1), source=OperatorLifecycleEventSource.MIGRATION_BASELINE)

    timeline = _service(
        enforcement=_enforcement(), evidence=_evidence(), events=(baseline,)
    ).execute("enf_operator_test")

    assert not timeline.history_complete
    assert not timeline.events_truncated
