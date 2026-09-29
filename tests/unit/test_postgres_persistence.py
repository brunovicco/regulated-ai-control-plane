from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from regulated_ai.adapters import (
    POSTGRES_SCHEMA_REVISION,
    PostgresDatabase,
    PostgresHmacActionApprovalAdapter,
    PostgresHmacApprovalAdapter,
    PostgresHmacToolActionReconciliationAdapter,
    PostgresSchemaError,
)
from regulated_ai.adapters.action_approval import ActionApprovalAssertionError
from regulated_ai.adapters.approval import ApprovalAssertionError
from regulated_ai.adapters.reconciliation import ToolActionReconciliationAssertionError
from regulated_ai.domain import (
    ActionApprovalGrant,
    ApprovalGrant,
    ToolActionReconciliationGrant,
    ToolActionReconciliationOutcome,
)

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, rows: list[tuple[object, ...] | None] | None = None) -> None:
        self.rows = [] if rows is None else rows
        self.statements: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement: str, parameters: object = ()) -> _Cursor:
        self.statements.append((statement, parameters))
        row = self.rows.pop(0) if self.rows else None
        return _Cursor(row)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _Database:
    def __init__(self, connections: list[_Connection]) -> None:
        self.connections = connections

    @contextmanager
    def connect(self) -> Iterator[_Connection]:
        yield self.connections.pop(0)


def test_postgres_database_validates_url_and_timeouts() -> None:
    PostgresDatabase("postgresql://database.invalid/regulaai")
    PostgresDatabase("postgresql+psycopg://database.invalid/regulaai")

    with pytest.raises(ValueError, match="must use PostgreSQL"):
        PostgresDatabase("sqlite:///tmp/evidence.db")
    with pytest.raises(ValueError, match="connect timeout"):
        PostgresDatabase("postgresql://database.invalid/regulaai", connect_timeout_seconds=0)
    with pytest.raises(ValueError, match="statement timeout"):
        PostgresDatabase(
            "postgresql://database.invalid/regulaai", statement_timeout_milliseconds=99
        )


def test_postgres_connection_sets_timeouts_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection()
    monkeypatch.setattr(
        "regulated_ai.adapters.evidence_postgres.psycopg.connect",
        lambda *_args, **_kwargs: connection,
    )
    database = PostgresDatabase("postgresql://database.invalid/regulaai")

    with database.connect() as opened:
        assert cast(object, opened) is connection

    assert "statement_timeout" in connection.statements[0][0]
    assert "lock_timeout" in connection.statements[1][0]
    assert connection.committed
    assert connection.closed


def test_postgres_connection_rolls_back_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection()
    monkeypatch.setattr(
        "regulated_ai.adapters.evidence_postgres.psycopg.connect",
        lambda *_args, **_kwargs: connection,
    )
    database = PostgresDatabase("postgresql://database.invalid/regulaai")

    with pytest.raises(RuntimeError, match="synthetic"), database.connect():
        raise RuntimeError("synthetic")

    assert connection.rolled_back
    assert connection.closed


def test_schema_revision_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = [_Connection([None, None, (POSTGRES_SCHEMA_REVISION,)])]
    monkeypatch.setattr(
        "regulated_ai.adapters.evidence_postgres.psycopg.connect",
        lambda *_args, **_kwargs: connections.pop(0),
    )
    PostgresDatabase("postgresql://database.invalid/regulaai").verify_schema()

    connections = [_Connection([None, None, ("old",)])]
    with pytest.raises(PostgresSchemaError, match="revision"):
        PostgresDatabase("postgresql://database.invalid/regulaai").verify_schema()


def test_postgres_authority_adapters_preserve_assertion_validation() -> None:
    database = cast(PostgresDatabase, _Database([]))
    approval = PostgresHmacApprovalAdapter(database, b"d" * 32)
    action = PostgresHmacActionApprovalAdapter(database, b"a" * 32)
    reconciliation = PostgresHmacToolActionReconciliationAdapter(database, b"r" * 32)

    with pytest.raises(ApprovalAssertionError, match="invalid"):
        approval.inspect("invalid", decision_digest=f"sha256:{'1' * 64}", now=NOW)
    with pytest.raises(ActionApprovalAssertionError, match="invalid"):
        action.inspect("invalid", action_digest=f"sha256:{'2' * 64}", now=NOW)
    with pytest.raises(ToolActionReconciliationAssertionError, match="invalid"):
        reconciliation.inspect("invalid", action_digest=f"sha256:{'3' * 64}", now=NOW)


def test_postgres_authority_rejects_invalid_consumption_before_database_access() -> None:
    database = cast(PostgresDatabase, _Database([]))
    approval = PostgresHmacApprovalAdapter(database, b"d" * 32)
    action = PostgresHmacActionApprovalAdapter(database, b"a" * 32)
    reconciliation = PostgresHmacToolActionReconciliationAdapter(database, b"r" * 32)

    with pytest.raises(ApprovalAssertionError, match="cannot be consumed"):
        approval.consume(
            ApprovalGrant(
                approval_id="approval",
                actor_id="actor",
                decision_digest=f"sha256:{'1' * 64}",
                issued_at=NOW - timedelta(minutes=2),
                expires_at=NOW - timedelta(minutes=1),
            ),
            enforcement_id="enforcement",
            now=NOW,
        )
    with pytest.raises(ActionApprovalAssertionError, match="cannot be consumed"):
        action.consume(
            ActionApprovalGrant(
                approval_id="approval",
                actor_id="actor",
                action_digest=f"sha256:{'2' * 64}",
                issued_at=NOW - timedelta(minutes=2),
                expires_at=NOW - timedelta(minutes=1),
            ),
            action_id="action",
            now=NOW,
        )
    with pytest.raises(ToolActionReconciliationAssertionError, match="cannot be consumed"):
        reconciliation.consume(
            ToolActionReconciliationGrant(
                reconciliation_id="reconciliation",
                actor_id="actor",
                action_digest=f"sha256:{'3' * 64}",
                outcome=ToolActionReconciliationOutcome.EXECUTED,
                tool_execution_id=None,
                issued_at=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(minutes=1),
            ),
            action_id="action",
            now=NOW,
        )


def test_authority_configuration_is_bounded() -> None:
    database = cast(PostgresDatabase, _Database([]))
    with pytest.raises(ValueError, match="at least 32"):
        PostgresHmacApprovalAdapter(database, b"short")
    with pytest.raises(ValueError, match="range"):
        PostgresHmacActionApprovalAdapter(database, b"a" * 32, max_lifetime_seconds=0)
    with pytest.raises(ValueError, match="range"):
        PostgresHmacToolActionReconciliationAdapter(
            database, b"r" * 32, max_lifetime_seconds=86_401
        )
