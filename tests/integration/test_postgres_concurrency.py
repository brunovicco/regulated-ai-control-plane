import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict

from regulated_ai.adapters import (
    PostgresDatabase,
    PostgresEnforcementRepository,
    PostgresHmacApprovalAdapter,
    PostgresToolActionRepository,
)
from regulated_ai.domain import (
    ApprovalGrant,
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    ToolActionRecord,
    ToolActionStatus,
)

_DATABASE_URL = os.environ.get("REGULAAI_TEST_POSTGRES_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        _DATABASE_URL is None,
        reason="REGULAAI_TEST_POSTGRES_URL is not configured",
    ),
]


@pytest.fixture(scope="module")
def database() -> PostgresDatabase:
    assert _DATABASE_URL is not None
    database_name = str(conninfo_to_dict(_DATABASE_URL).get("dbname") or "").casefold()
    if "test" not in database_name:
        raise RuntimeError("REGULAAI_TEST_POSTGRES_URL must name a dedicated test database")
    configuration = Config("alembic.ini")
    previous = os.environ.get("REGULAAI_DATABASE_URL")
    os.environ["REGULAAI_DATABASE_URL"] = _DATABASE_URL
    try:
        command.upgrade(configuration, "head")
    finally:
        if previous is None:
            os.environ.pop("REGULAAI_DATABASE_URL", None)
        else:
            os.environ["REGULAAI_DATABASE_URL"] = previous
    configured = PostgresDatabase(_DATABASE_URL)
    configured.verify_schema()
    return configured


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
