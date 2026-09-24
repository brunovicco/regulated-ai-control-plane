import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters.evidence_sqlite import (
    SqliteEnforcementRepository,
    SqliteEvidenceRepository,
    SqliteToolActionRepository,
)
from regulated_ai.domain import (
    ActionApprovalReceipt,
    ApprovalReceipt,
    DataClassification,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ObligationType,
    ProviderCallMetadata,
    ToolActionRecord,
    ToolActionStatus,
    ToolProposal,
    TransformationReceipt,
)


def test_sqlite_round_trip_contains_only_metadata(tmp_path: Path) -> None:
    repository = SqliteEvidenceRepository(tmp_path / "evidence.sqlite3")
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
    )

    stored = repository.save(evidence)
    duplicate = repository.save(evidence)

    assert stored == evidence
    assert duplicate == evidence
    assert repository.get("missing") is None
    assert "raw-sensitive-sentinel" not in (tmp_path / "evidence.sqlite3").read_bytes().decode(
        errors="ignore"
    )


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
    assert "raw-sensitive-sentinel" not in path.read_bytes().decode(errors="ignore")


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
        )
    )

    assert claimed
    assert not replay_claimed
    assert replayed.status is ToolActionStatus.DISPATCHED
    assert completed.status is ToolActionStatus.EXECUTED
    assert completed.approval_receipt is not None
    assert repository.save(waiting).status is ToolActionStatus.EXECUTED
    stored = path.read_bytes().decode(errors="ignore")
    assert "raw-arguments-sentinel" not in stored
    assert "raw-idempotency-sentinel" not in stored
