from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from regulated_ai.adapters import (
    ActionApprovalAssertionError,
    Ed25519OperatorAuthorityVerifier,
    PostgresDatabase,
    PostgresEd25519ActionApprovalAdapter,
    PostgresEd25519ToolActionReconciliationAdapter,
    PostgresEnforcementRepository,
    PostgresHmacApprovalAdapter,
    PostgresToolActionRepository,
    ToolActionReconciliationAssertionError,
)
from regulated_ai.domain import (
    ApprovalGrant,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    ToolActionRecord,
    ToolActionStatus,
)

from .pilot_support import PilotIssuer

pytestmark = pytest.mark.integration


def test_enforcement_claim_has_one_winner_across_connections(
    database: PostgresDatabase,
) -> None:
    repository = PostgresEnforcementRepository(database)
    identifier = f"enf_{uuid4().hex}"
    prepared = _enforcement(identifier)
    repository.save(prepared)
    dispatched = replace(prepared, status=EnforcementStatus.DISPATCHED)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _: repository.claim_execution(dispatched), range(8)))

    assert sum(claimed for _record, claimed in results) == 1
    assert all(record.status is EnforcementStatus.DISPATCHED for record, _claimed in results)


def test_action_claim_has_one_winner_across_connections(database: PostgresDatabase) -> None:
    repository = PostgresToolActionRepository(database)
    suffix = uuid4().hex
    prepared = _action(f"act_{suffix}", f"enf_{suffix}")
    repository.save(prepared)
    dispatched = replace(prepared, status=ToolActionStatus.DISPATCHED)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _: repository.claim_execution(dispatched), range(8)))

    assert sum(claimed for _record, claimed in results) == 1
    assert all(record.status is ToolActionStatus.DISPATCHED for record, _claimed in results)


def test_decision_approval_consumption_and_claim_are_atomic(
    database: PostgresDatabase,
) -> None:
    repository = PostgresEnforcementRepository(database)
    identifier = f"enf_{uuid4().hex}"
    prepared = _enforcement(identifier)
    repository.save(prepared)
    dispatched = replace(prepared, status=EnforcementStatus.DISPATCHED)
    now = datetime.now(UTC)
    grant = ApprovalGrant(
        approval_id=f"approval_{uuid4().hex}",
        actor_id="operator_test",
        decision_digest=f"sha256:{'1' * 64}",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
    )
    authority = PostgresHmacApprovalAdapter(database, b"d" * 32)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(
            executor.map(
                lambda _: authority.claim_execution(grant, record=dispatched, now=now),
                range(8),
            )
        )

    assert sum(claimed for _record, claimed, _receipt in results) == 1
    receipts = tuple(receipt for _record, _claimed, receipt in results if receipt is not None)
    assert len(receipts) == 1
    assert authority.get(grant.approval_id) == receipts[0]


def test_signed_action_approval_is_consumed_by_one_concurrent_claim(
    database: PostgresDatabase, tmp_path: Path
) -> None:
    issuer = PilotIssuer(tmp_path)
    authority = PostgresEd25519ActionApprovalAdapter(
        database, Ed25519OperatorAuthorityVerifier(issuer.trust_store)
    )
    repository = PostgresToolActionRepository(database)
    suffix = uuid4().hex
    record = repository.save(_action(f"act_{suffix}", f"enf_{suffix}"))
    now = datetime.now(UTC)
    grant = authority.inspect(
        issuer.assertion("action_approval", record.action_digest),
        action_digest=record.action_digest,
        now=now,
    )
    dispatched = replace(record, status=ToolActionStatus.DISPATCHED)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(
            executor.map(
                lambda _: authority.claim_execution(grant, record=dispatched, now=now), range(8)
            )
        )
    assert sum(claimed for _, claimed, _ in results) == 1
    assert authority.get(grant.approval_id) is not None
    other = repository.save(_action(f"act_other_{suffix}", f"enf_other_{suffix}"))
    with pytest.raises(ActionApprovalAssertionError):
        authority.claim_execution(
            grant, record=replace(other, status=ToolActionStatus.DISPATCHED), now=now
        )
    failed = repository.get(other.action_id)
    assert failed is not None and failed.status is ToolActionStatus.APPROVAL_FAILED
    with database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM operator_lifecycle_event "
            "WHERE entity_id=%s AND status='DISPATCHED'",
            (other.action_id,),
        ).fetchone()
    assert count == (0,)


@pytest.mark.parametrize("outcome", ["EXECUTED", "NOT_EXECUTED"])
def test_signed_reconciliation_is_atomic_idempotent_and_rejects_conflicting_outcome(
    database: PostgresDatabase, tmp_path: Path, outcome: str
) -> None:
    issuer = PilotIssuer(tmp_path)
    authority = PostgresEd25519ToolActionReconciliationAdapter(
        database, Ed25519OperatorAuthorityVerifier(issuer.trust_store)
    )
    repository = PostgresToolActionRepository(database)
    suffix = uuid4().hex
    record = repository.save(
        replace(
            _action(f"act_{suffix}", f"enf_{suffix}"),
            status=ToolActionStatus.RECONCILIATION_REQUIRED,
        )
    )
    now = datetime.now(UTC)
    grant = authority.inspect(
        issuer.assertion("reconciliation", record.action_digest, outcome=outcome),
        action_digest=record.action_digest,
        now=now,
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(
            executor.map(lambda _: authority.reconcile(grant, record=record, now=now), range(8))
        )
    assert all(item == results[0] for item in results)
    assert results[0].status.value == f"RECONCILED_{outcome}"
    other_outcome = "NOT_EXECUTED" if outcome == "EXECUTED" else "EXECUTED"
    conflicting = authority.inspect(
        issuer.assertion("reconciliation", record.action_digest, outcome=other_outcome),
        action_digest=record.action_digest,
        now=now,
    )
    with pytest.raises(ToolActionReconciliationAssertionError):
        authority.reconcile(conflicting, record=record, now=now)
    assert authority.get(conflicting.reconciliation_id) is None
    assert repository.get(record.action_id) == results[0]


def _enforcement(identifier: str) -> EnforcementRecord:
    return EnforcementRecord(
        enforcement_id=identifier,
        created_at=datetime.now(UTC),
        evaluation_id=f"eval_{identifier}",
        evaluation_evidence_id=f"ev_{identifier}",
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        status=EnforcementStatus.PREPARED,
        policy_set_version="policy@test",
        provider_registry_version="registry@test",
        provider_target="provider.service.region",
        transformation_receipts=(),
        reason_codes=(),
        input_digest=f"sha256:{'2' * 64}",
        output_digest=f"sha256:{'3' * 64}",
        provider_execution_id=None,
    )


def _action(action_id: str, enforcement_id: str) -> ToolActionRecord:
    return ToolActionRecord(
        action_id=action_id,
        created_at=datetime.now(UTC),
        enforcement_id=enforcement_id,
        evaluation_id=f"eval_{enforcement_id}",
        call_id=f"call_{action_id}",
        tool_name="cards.read",
        tool_schema_version="1",
        tool_schema_digest=f"sha256:{'4' * 64}",
        arguments_digest=f"sha256:{'5' * 64}",
        workload_identity="workload.test",
        idempotency_key_digest=f"sha256:{'6' * 64}",
        action_digest=f"sha256:{'7' * 64}",
        status=ToolActionStatus.PREPARED,
        output_schema_digest=f"sha256:{'8' * 64}",
    )
