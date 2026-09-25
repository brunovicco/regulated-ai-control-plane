import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from regulated_ai.adapters.evidence_sqlite import (
    SqliteEnforcementRepository,
    SqliteEvidenceRepository,
    SqliteOperatorLifecycleEventRepository,
    SqliteToolActionRepository,
)
from regulated_ai.domain import (
    ActionApprovalReceipt,
    ApprovalReceipt,
    CapabilityState,
    DataClassification,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ObligationType,
    OperatorLifecycleEventSource,
    OperatorTimelineStageKind,
    ProviderCallMetadata,
    ProviderCapabilitySnapshot,
    ToolActionRecord,
    ToolActionStatus,
    ToolProposal,
    ToolResultClassification,
    TransformationReceipt,
)


def test_sqlite_round_trip_contains_only_metadata(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    repository = SqliteEvidenceRepository(path)
    evidence = EvidenceMetadata(
        evidence_id="ev_test",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        correlation_id="correlation-test",
        decision=DecisionOutcome.ALLOW_WITH_TRANSFORMATION,
        policy_set_version="policy@1",
        provider_registry_version="registry@1",
        matched_policy_ids=("rule@1",),
        provider_capability_ids=("provider.service.control",),
        control_objective_ids=("CONTROL.TEST",),
        obligation_types=(ObligationType.TOKENIZE,),
        classification_labels=(DataClassification.BRAZIL_CPF,),
        reason_codes=("TEST",),
        input_digest="sha256:input",
        output_digest="sha256:output",
        event_digest="sha256:event",
        tool_catalog_version="tools@1",
        authorized_tool_ids=("cards.read@1",),
        provider_capability_snapshots=(
            ProviderCapabilitySnapshot(
                capability_id="provider.service.control",
                provider_target="provider.service.region",
                key="control",
                state=CapabilityState.SUPPORTED,
                conditions=(),
                verified_at=date(2026, 9, 22),
                record_version="1",
                registry_version="registry@1",
                source_urls=("https://provider.invalid/documentation",),
            ),
        ),
    )

    stored = repository.save(evidence)
    duplicate = repository.save(evidence)

    assert stored == evidence
    assert duplicate == evidence
    assert repository.get("missing") is None
    events = SqliteOperatorLifecycleEventRepository(path).list_for_timeline(
        enforcement_id="enf_test", evidence_id=evidence.evidence_id, limit=257
    )
    assert tuple((event.kind, event.status) for event in events) == (
        (OperatorTimelineStageKind.EVALUATION, DecisionOutcome.ALLOW_WITH_TRANSFORMATION.value),
    )
    assert events[0].source is OperatorLifecycleEventSource.TRANSITION
    assert "raw-sensitive-sentinel" not in path.read_bytes().decode(errors="ignore")

    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE evidence SET provider_capability_snapshots = '[{}]' WHERE evidence_id = ?",
            (evidence.evidence_id,),
        )
        connection.commit()
    with pytest.raises(ValueError, match="capability snapshot"):
        repository.get(evidence.evidence_id)


def test_evidence_repository_migrates_provider_snapshot_column(tmp_path: Path) -> None:
    path = tmp_path / "legacy-evidence.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE evidence (
                evidence_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                policy_set_version TEXT NOT NULL,
                provider_registry_version TEXT NOT NULL,
                matched_policy_ids TEXT NOT NULL,
                provider_capability_ids TEXT NOT NULL,
                control_objective_ids TEXT NOT NULL,
                obligation_types TEXT NOT NULL,
                classification_labels TEXT NOT NULL,
                reason_codes TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                output_digest TEXT NOT NULL,
                event_digest TEXT NOT NULL,
                previous_event_digest TEXT,
                tool_catalog_version TEXT,
                authorized_tool_ids TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO evidence VALUES (
                'ev_legacy', '2026-09-23T12:00:00+00:00', 'correlation-legacy', 'ALLOW',
                'policy@1', 'registry@1', '[]', '["provider.service.control"]', '[]',
                '["REQUIRE_EVIDENCE"]', '[]', '[]', 'sha256:input', 'sha256:output',
                'sha256:event', NULL, NULL, '[]'
            )
            """
        )
        connection.commit()

    repository = SqliteEvidenceRepository(path)
    stored = repository.get("ev_legacy")

    assert stored is not None
    assert stored.provider_capability_snapshots == ()
    with closing(sqlite3.connect(path)) as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(evidence)")}
    assert "provider_capability_snapshots" in columns


def test_enforcement_round_trip_advances_state_without_raw_values(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    repository = SqliteEnforcementRepository(path)
    receipt = TransformationReceipt(
        receipt_id="tr_test",
        type=ObligationType.TOKENIZE,
        target="customer_document",
        input_digest="sha256:input",
        output_digest="sha256:output",
        reason_code="MINIMIZE",
    )
    prepared = EnforcementRecord(
        enforcement_id="enf_test",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        evaluation_id="eval_test",
        evaluation_evidence_id="ev_test",
        decision=DecisionOutcome.ALLOW_WITH_TRANSFORMATION,
        status=EnforcementStatus.PREPARED,
        policy_set_version="policy@1",
        provider_registry_version="registry@1",
        provider_target="provider.service.region",
        transformation_receipts=(receipt,),
        reason_codes=(),
        input_digest="sha256:evaluation-input",
        output_digest="sha256:transformed-output",
        provider_execution_id=None,
    )

    repository.save(prepared)
    dispatched, claimed = repository.claim_execution(
        replace(prepared, status=EnforcementStatus.DISPATCHED)
    )
    completed = repository.save(
        replace(
            dispatched,
            status=EnforcementStatus.EXECUTED,
            provider_execution_id="mockexec_test",
            approval_receipt=ApprovalReceipt(
                approval_id="approval-test",
                actor_id="approver-test",
                decision_digest="sha256:decision",
                enforcement_id="enf_test",
                issued_at=datetime(2026, 9, 23, 11, 55, tzinfo=UTC),
                expires_at=datetime(2026, 9, 23, 12, 5, tzinfo=UTC),
                consumed_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
            ),
            provider_call_metadata=ProviderCallMetadata(
                gateway_request_id="00000000-0000-0000-0000-000000000001",
                routing_decision_id="route_1",
                policy_id="gateway.policy",
                policy_version="1.0",
                provider="openai",
                model="gpt-test",
                deployment="openai-test",
                latency_ms=25,
                attempt_number=1,
                fallback_index=0,
                cached=False,
            ),
            tool_proposals=(
                ToolProposal(
                    call_id="call_1",
                    tool_name="cards.read",
                    tool_schema_version="1",
                    tool_schema_digest="sha256:schema",
                    arguments_digest="sha256:arguments",
                ),
            ),
        )
    )

    assert completed.status is EnforcementStatus.EXECUTED
    assert claimed
    assert completed.provider_execution_id == "mockexec_test"
    assert completed.provider_call_metadata is not None
    assert completed.provider_call_metadata.routing_decision_id == "route_1"
    assert completed.approval_receipt is not None
    assert completed.approval_receipt.approval_id == "approval-test"
    assert completed.tool_proposals[0].tool_name == "cards.read"
    replayed, replay_claimed = repository.claim_execution(
        replace(prepared, status=EnforcementStatus.DISPATCHED)
    )
    assert replayed.status is EnforcementStatus.EXECUTED
    assert not replay_claimed
    assert repository.save(prepared).status is EnforcementStatus.EXECUTED
    assert repository.get("missing") is None
    events = SqliteOperatorLifecycleEventRepository(path).list_for_timeline(
        enforcement_id=prepared.enforcement_id,
        evidence_id=prepared.evaluation_evidence_id,
        limit=257,
    )
    assert tuple(event.status for event in events) == ("PREPARED", "DISPATCHED", "EXECUTED")
    assert all(event.source is OperatorLifecycleEventSource.TRANSITION for event in events)
    assert "raw-sensitive-sentinel" not in path.read_bytes().decode(errors="ignore")


def test_lifecycle_event_failure_rolls_back_state_transition(tmp_path: Path) -> None:
    path = tmp_path / "atomic-lifecycle.sqlite3"
    repository = SqliteEnforcementRepository(path)
    prepared = EnforcementRecord(
        enforcement_id="enf_atomic",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        evaluation_id="eval_atomic",
        evaluation_evidence_id="ev_atomic",
        decision=DecisionOutcome.ALLOW,
        status=EnforcementStatus.PREPARED,
        policy_set_version="policy@1",
        provider_registry_version="registry@1",
        provider_target="provider.service.region",
        transformation_receipts=(),
        reason_codes=(),
        input_digest="sha256:input",
        output_digest="sha256:output",
        provider_execution_id=None,
    )
    repository.save(prepared)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_dispatched_lifecycle
            BEFORE INSERT ON operator_lifecycle_event
            WHEN NEW.entity_kind = 'ENFORCEMENT' AND NEW.status = 'DISPATCHED'
            BEGIN
                SELECT RAISE(ABORT, 'simulated lifecycle write failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="simulated lifecycle write failure"):
        repository.claim_execution(replace(prepared, status=EnforcementStatus.DISPATCHED))

    stored = repository.get(prepared.enforcement_id)
    assert stored is not None
    assert stored.status is EnforcementStatus.PREPARED
    events = SqliteOperatorLifecycleEventRepository(path).list_for_timeline(
        enforcement_id=prepared.enforcement_id,
        evidence_id=prepared.evaluation_evidence_id,
        limit=257,
    )
    assert tuple(event.status for event in events) == ("PREPARED",)


def test_enforcement_repository_migrates_phase_three_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE enforcement (
                enforcement_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                evaluation_id TEXT NOT NULL,
                evaluation_evidence_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                status TEXT NOT NULL,
                policy_set_version TEXT NOT NULL,
                provider_registry_version TEXT NOT NULL,
                provider_target TEXT NOT NULL,
                transformation_receipts TEXT NOT NULL,
                reason_codes TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                output_digest TEXT,
                provider_execution_id TEXT,
                provider_call_metadata TEXT
            )
            """
        )
        connection.commit()

    SqliteEnforcementRepository(path)

    with closing(sqlite3.connect(path)) as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(enforcement)")}
    assert "approval_receipt" in columns
    assert "tool_proposals" in columns


def test_tool_action_round_trip_claims_once_without_ephemeral_values(tmp_path: Path) -> None:
    path = tmp_path / "actions.sqlite3"
    repository = SqliteToolActionRepository(path)
    waiting = ToolActionRecord(
        action_id="act_test",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        enforcement_id="enf_test",
        evaluation_id="eval_test",
        call_id="call_test",
        tool_name="cards.unblock",
        tool_schema_version="1",
        tool_schema_digest="sha256:schema",
        arguments_digest="sha256:arguments",
        workload_identity="workload.test",
        idempotency_key_digest="sha256:idempotency",
        action_digest="sha256:action",
        status=ToolActionStatus.WAITING_APPROVAL,
        output_schema_digest="sha256:output-schema",
    )
    repository.save(waiting)
    prepared = repository.save(replace(waiting, status=ToolActionStatus.PREPARED))

    dispatched, claimed = repository.claim_execution(
        replace(prepared, status=ToolActionStatus.DISPATCHED)
    )
    replayed, replay_claimed = repository.claim_execution(
        replace(prepared, status=ToolActionStatus.DISPATCHED)
    )
    completed = repository.save(
        replace(
            dispatched,
            status=ToolActionStatus.EXECUTED,
            approval_receipt=ActionApprovalReceipt(
                approval_id="action-approval-test",
                actor_id="approver-test",
                action_digest=waiting.action_digest,
                action_id=waiting.action_id,
                issued_at=datetime(2026, 9, 23, 11, 55, tzinfo=UTC),
                expires_at=datetime(2026, 9, 23, 12, 5, tzinfo=UTC),
                consumed_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
            ),
            tool_execution_id="mocktool_test",
            output_digest="sha256:output",
            safe_output_digest="sha256:safe-output",
            result_classifications=(
                ToolResultClassification.FINANCIAL,
                ToolResultClassification.INTERNAL,
            ),
            exposed_result_fields=("operation_reference", "operation_status"),
        )
    )

    assert claimed
    assert not replay_claimed
    assert replayed.status is ToolActionStatus.DISPATCHED
    assert completed.status is ToolActionStatus.EXECUTED
    assert completed.approval_receipt is not None
    assert completed.output_schema_digest == "sha256:output-schema"
    assert completed.safe_output_digest == "sha256:safe-output"
    assert completed.result_classifications == (
        ToolResultClassification.FINANCIAL,
        ToolResultClassification.INTERNAL,
    )
    assert completed.exposed_result_fields == ("operation_reference", "operation_status")
    assert repository.save(waiting).status is ToolActionStatus.EXECUTED
    events = SqliteOperatorLifecycleEventRepository(path).list_for_timeline(
        enforcement_id=waiting.enforcement_id,
        evidence_id="ev_missing",
        limit=257,
    )
    assert tuple(event.status for event in events) == (
        "WAITING_APPROVAL",
        "PREPARED",
        "DISPATCHED",
        "EXECUTED",
    )
    with closing(sqlite3.connect(path)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE operator_lifecycle_event SET status = 'ALTERED' WHERE event_sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM operator_lifecycle_event WHERE event_sequence = 1")
    second = repository.save(
        replace(
            waiting,
            action_id="act_second",
            created_at=waiting.created_at + timedelta(seconds=1),
            call_id="call_second",
            arguments_digest="sha256:second-arguments",
            idempotency_key_digest="sha256:second-idempotency",
            action_digest="sha256:second-action",
        )
    )
    repository.save(
        replace(
            waiting,
            action_id="act_other",
            enforcement_id="enf_other",
            evaluation_id="eval_other",
            call_id="call_other",
            arguments_digest="sha256:other-arguments",
            idempotency_key_digest="sha256:other-idempotency",
            action_digest="sha256:other-action",
        )
    )
    assert repository.list_for_enforcement("enf_test", limit=129) == (completed, second)
    assert repository.list_for_enforcement("enf_test", limit=1) == (completed,)
    assert repository.list_for_enforcement("missing", limit=129) == ()
    with pytest.raises(ValueError):
        repository.list_for_enforcement("enf_test", limit=130)
    stored = path.read_bytes().decode(errors="ignore")
    assert "raw-arguments-sentinel" not in stored
    assert "raw-idempotency-sentinel" not in stored


def test_tool_action_repository_migrates_phase_four_c_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy-actions.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE tool_action (
                action_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                enforcement_id TEXT NOT NULL,
                evaluation_id TEXT NOT NULL,
                call_id TEXT NOT NULL UNIQUE,
                tool_name TEXT NOT NULL,
                tool_schema_version TEXT NOT NULL,
                tool_schema_digest TEXT NOT NULL,
                arguments_digest TEXT NOT NULL,
                workload_identity TEXT NOT NULL,
                idempotency_key_digest TEXT NOT NULL,
                action_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                approval_receipt TEXT,
                tool_execution_id TEXT,
                output_digest TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO tool_action VALUES (
                'act_legacy', '2026-09-23T12:00:00+00:00', 'enf_legacy', 'eval_legacy',
                'call_legacy', 'cards.read', '1', 'sha256:schema', 'sha256:arguments',
                'workload.legacy', 'sha256:idempotency', 'sha256:action', 'EXECUTED',
                NULL, 'mocktool_legacy', 'sha256:output'
            )
            """
        )
        connection.commit()

    SqliteToolActionRepository(path)

    with closing(sqlite3.connect(path)) as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tool_action)")}
    assert {
        "output_schema_digest",
        "safe_output_digest",
        "result_classifications",
        "exposed_result_fields",
    }.issubset(columns)
    events = SqliteOperatorLifecycleEventRepository(path).list_for_timeline(
        enforcement_id="enf_legacy", evidence_id="ev_legacy", limit=257
    )
    assert len(events) == 1
    assert events[0].record_id == "act_legacy"
    assert events[0].source is OperatorLifecycleEventSource.MIGRATION_BASELINE
