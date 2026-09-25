"""Read-only metadata composition for one exact enforcement timeline."""

import re
from itertools import pairwise

from regulated_ai.application.evaluate_operation import EvaluationError
from regulated_ai.application.ports import (
    EnforcementRepository,
    EvidenceRepository,
    OperatorLifecycleEventRepository,
    ToolActionRepository,
)
from regulated_ai.domain import (
    ApprovalReceipt,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    OperatorApprovalSummary,
    OperatorAttentionCode,
    OperatorLifecycleEvent,
    OperatorLifecycleEventSource,
    OperatorTimeline,
    OperatorTimelineStage,
    OperatorTimelineStageKind,
    ToolActionRecord,
    ToolActionStatus,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_MAX_ACTIONS = 128
_MAX_EVENTS = 256


class OperatorTimelineNotFoundError(EvaluationError):
    """The exact enforcement timeline does not exist."""

    code = "OPERATOR_TIMELINE_NOT_FOUND"


class OperatorTimelineIntegrityError(EvaluationError):
    """Stored metadata cannot form one trustworthy timeline."""

    code = "OPERATOR_TIMELINE_INTEGRITY_FAILED"


class GetOperatorTimeline:
    """Compose a bounded current-state timeline without payload recovery."""

    def __init__(
        self,
        *,
        evidence: EvidenceRepository,
        enforcement: EnforcementRepository,
        actions: ToolActionRepository,
        events: OperatorLifecycleEventRepository,
    ) -> None:
        """Bind metadata repositories used by the read-only query."""
        self._evidence = evidence
        self._enforcement = enforcement
        self._actions = actions
        self._events = events

    def execute(self, enforcement_id: str) -> OperatorTimeline:
        """Return ordered metadata stages for one exact enforcement identifier."""
        if _SAFE_ID.fullmatch(enforcement_id) is None:
            raise OperatorTimelineNotFoundError("Operator timeline was not found")
        try:
            enforcement = self._enforcement.get(enforcement_id)
            if enforcement is None:
                raise OperatorTimelineNotFoundError("Operator timeline was not found")
            evidence = self._evidence.get(enforcement.evaluation_evidence_id)
            actions = self._actions.list_for_enforcement(enforcement_id, limit=_MAX_ACTIONS + 1)
            events = self._events.list_for_timeline(
                enforcement_id=enforcement_id,
                evidence_id=enforcement.evaluation_evidence_id,
                limit=_MAX_EVENTS + 1,
            )
        except EvaluationError:
            raise
        except Exception as exc:
            raise OperatorTimelineIntegrityError(
                "Operator timeline metadata could not be read"
            ) from exc
        if evidence is None or (
            evidence.decision is not enforcement.decision
            or evidence.policy_set_version != enforcement.policy_set_version
            or evidence.provider_registry_version != enforcement.provider_registry_version
            or evidence.input_digest != enforcement.input_digest
        ):
            raise OperatorTimelineIntegrityError("Operator timeline metadata is inconsistent")
        snapshot_ids = {
            snapshot.capability_id for snapshot in evidence.provider_capability_snapshots
        }
        snapshot_identities = {
            (snapshot.capability_id, snapshot.provider_target)
            for snapshot in evidence.provider_capability_snapshots
        }
        capability_ids = set(evidence.provider_capability_ids)
        if (
            any(
                snapshot.registry_version != evidence.provider_registry_version
                for snapshot in evidence.provider_capability_snapshots
            )
            or not snapshot_ids <= capability_ids
            or len(snapshot_identities) != len(evidence.provider_capability_snapshots)
        ):
            raise OperatorTimelineIntegrityError("Operator timeline metadata is inconsistent")

        actions_truncated = len(actions) > _MAX_ACTIONS
        if any(
            action.enforcement_id != enforcement.enforcement_id
            or action.evaluation_id != enforcement.evaluation_id
            or not _action_approval_is_consistent(action)
            for action in actions
        ) or not _approval_is_consistent(enforcement.approval_receipt, enforcement, evidence):
            raise OperatorTimelineIntegrityError("Operator timeline metadata is inconsistent")
        selected_actions = actions[:_MAX_ACTIONS]
        events_truncated = len(events) > _MAX_EVENTS
        if any(
            (
                event.kind is OperatorTimelineStageKind.EVALUATION
                and (event.record_id != evidence.evidence_id or event.enforcement_id is not None)
            )
            or (
                event.kind is not OperatorTimelineStageKind.EVALUATION
                and event.enforcement_id != enforcement.enforcement_id
            )
            for event in events
        ) or any(current.sequence >= following.sequence for current, following in pairwise(events)):
            raise OperatorTimelineIntegrityError("Operator timeline metadata is inconsistent")
        selected_events = events[:_MAX_EVENTS]

        enforcement_attention = _enforcement_attention(enforcement.status)
        stages: list[OperatorTimelineStage] = [
            OperatorTimelineStage(
                sequence=1,
                kind=OperatorTimelineStageKind.EVALUATION,
                record_id=evidence.evidence_id,
                created_at=evidence.created_at,
                status=evidence.decision.value,
            ),
            OperatorTimelineStage(
                sequence=2,
                kind=OperatorTimelineStageKind.ENFORCEMENT,
                record_id=enforcement.enforcement_id,
                created_at=enforcement.created_at,
                status=enforcement.status.value,
                attention_codes=enforcement_attention,
                approval_recorded=enforcement.approval_receipt is not None,
            ),
        ]
        attention = list(enforcement_attention)
        for sequence, action in enumerate(selected_actions, start=3):
            action_attention = _action_attention(action)
            attention.extend(action_attention)
            stages.append(
                OperatorTimelineStage(
                    sequence=sequence,
                    kind=OperatorTimelineStageKind.TOOL_ACTION,
                    record_id=action.action_id,
                    created_at=action.created_at,
                    status=action.status.value,
                    attention_codes=action_attention,
                    tool_name=action.tool_name,
                    call_id=action.call_id,
                    approval_recorded=action.approval_receipt is not None,
                )
            )
        if actions_truncated:
            attention.append(OperatorAttentionCode.ACTION_LIST_TRUNCATED)
        if events_truncated:
            attention.append(OperatorAttentionCode.EVENT_LIST_TRUNCATED)

        return OperatorTimeline(
            enforcement_id=enforcement.enforcement_id,
            evaluation_id=enforcement.evaluation_id,
            evidence_id=evidence.evidence_id,
            correlation_id=evidence.correlation_id,
            policy_set_version=evidence.policy_set_version,
            provider_registry_version=evidence.provider_registry_version,
            tool_catalog_version=evidence.tool_catalog_version,
            classification_labels=evidence.classification_labels,
            obligation_types=evidence.obligation_types,
            matched_policy_ids=evidence.matched_policy_ids,
            provider_capability_ids=evidence.provider_capability_ids,
            provider_capability_snapshots=evidence.provider_capability_snapshots,
            provider_context_complete=snapshot_ids == capability_ids,
            control_objective_ids=evidence.control_objective_ids,
            decision_reason_codes=evidence.reason_codes,
            enforcement_reason_codes=enforcement.reason_codes,
            authorized_tool_ids=evidence.authorized_tool_ids,
            provider_target=enforcement.provider_target,
            transformation_receipts=enforcement.transformation_receipts,
            approval=_approval_summary(enforcement.approval_receipt),
            input_digest=evidence.input_digest,
            output_digest=evidence.output_digest,
            event_digest=evidence.event_digest,
            previous_event_digest=evidence.previous_event_digest,
            stages=tuple(stages),
            attention_codes=tuple(dict.fromkeys(attention)),
            lifecycle_events=selected_events,
            history_complete=_history_complete(
                events=selected_events,
                events_truncated=events_truncated,
                actions_truncated=actions_truncated,
                evidence_id=evidence.evidence_id,
                evidence_status=evidence.decision.value,
                enforcement_id=enforcement.enforcement_id,
                enforcement_status=enforcement.status.value,
                actions=selected_actions,
            ),
            actions_truncated=actions_truncated,
            events_truncated=events_truncated,
        )


def _approval_is_consistent(
    receipt: ApprovalReceipt | None,
    enforcement: EnforcementRecord,
    evidence: EvidenceMetadata,
) -> bool:
    if receipt is None:
        return True
    return (
        receipt.enforcement_id == enforcement.enforcement_id
        and receipt.decision_digest == evidence.output_digest
        and receipt.issued_at <= receipt.consumed_at <= receipt.expires_at
    )


def _action_approval_is_consistent(action: ToolActionRecord) -> bool:
    receipt = action.approval_receipt
    if receipt is None:
        return True
    return (
        receipt.action_id == action.action_id
        and receipt.action_digest == action.action_digest
        and receipt.issued_at <= receipt.consumed_at <= receipt.expires_at
    )


def _approval_summary(receipt: ApprovalReceipt | None) -> OperatorApprovalSummary | None:
    if receipt is None:
        return None
    return OperatorApprovalSummary(
        approval_id=receipt.approval_id,
        issued_at=receipt.issued_at,
        expires_at=receipt.expires_at,
        consumed_at=receipt.consumed_at,
    )


def _history_complete(
    *,
    events: tuple[OperatorLifecycleEvent, ...],
    events_truncated: bool,
    actions_truncated: bool,
    evidence_id: str,
    evidence_status: str,
    enforcement_id: str,
    enforcement_status: str,
    actions: tuple[ToolActionRecord, ...],
) -> bool:
    if (
        events_truncated
        or actions_truncated
        or not events
        or any(event.source is not OperatorLifecycleEventSource.TRANSITION for event in events)
    ):
        return False
    observed = {(event.kind, event.record_id, event.status) for event in events}
    required = {
        (OperatorTimelineStageKind.EVALUATION, evidence_id, evidence_status),
        (OperatorTimelineStageKind.ENFORCEMENT, enforcement_id, enforcement_status),
    }
    required.update(
        (OperatorTimelineStageKind.TOOL_ACTION, action.action_id, action.status.value)
        for action in actions
    )
    return required <= observed


def _enforcement_attention(
    status: EnforcementStatus,
) -> tuple[OperatorAttentionCode, ...]:
    mapping = {
        EnforcementStatus.WAITING_APPROVAL: (OperatorAttentionCode.ENFORCEMENT_APPROVAL_REQUIRED,),
        EnforcementStatus.APPROVAL_FAILED: (OperatorAttentionCode.ENFORCEMENT_APPROVAL_FAILED,),
        EnforcementStatus.DISPATCHED: (OperatorAttentionCode.ENFORCEMENT_RECONCILIATION_REQUIRED,),
        EnforcementStatus.TRANSFORMATION_FAILED: (
            OperatorAttentionCode.ENFORCEMENT_TRANSFORMATION_FAILED,
        ),
        EnforcementStatus.EXECUTION_FAILED: (OperatorAttentionCode.ENFORCEMENT_EXECUTION_FAILED,),
    }
    return mapping.get(status, ())


def _action_attention(action: ToolActionRecord) -> tuple[OperatorAttentionCode, ...]:
    mapping = {
        ToolActionStatus.WAITING_APPROVAL: (OperatorAttentionCode.TOOL_ACTION_APPROVAL_REQUIRED,),
        ToolActionStatus.APPROVAL_FAILED: (OperatorAttentionCode.TOOL_ACTION_APPROVAL_FAILED,),
        ToolActionStatus.DISPATCHED: (OperatorAttentionCode.TOOL_ACTION_RECONCILIATION_REQUIRED,),
        ToolActionStatus.RECONCILIATION_REQUIRED: (
            OperatorAttentionCode.TOOL_ACTION_RECONCILIATION_REQUIRED,
        ),
        ToolActionStatus.RESULT_REJECTED: (OperatorAttentionCode.TOOL_RESULT_REJECTED,),
    }
    return mapping.get(action.status, ())
