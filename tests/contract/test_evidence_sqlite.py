from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters.evidence_sqlite import (
    SqliteEnforcementRepository,
    SqliteEvidenceRepository,
)
from regulated_ai.domain import (
    DataClassification,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ObligationType,
    ProviderCallMetadata,
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
        )
    )

    assert completed.status is EnforcementStatus.EXECUTED
    assert claimed
    assert completed.provider_execution_id == "mockexec_test"
    assert completed.provider_call_metadata is not None
    assert completed.provider_call_metadata.routing_decision_id == "route_1"
    replayed, replay_claimed = repository.claim_execution(
        replace(prepared, status=EnforcementStatus.DISPATCHED)
    )
    assert replayed.status is EnforcementStatus.EXECUTED
    assert not replay_claimed
    assert repository.save(prepared).status is EnforcementStatus.EXECUTED
    assert repository.get("missing") is None
    assert "raw-sensitive-sentinel" not in path.read_bytes().decode(errors="ignore")
