import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from regulated_ai.adapters import (
    HmacActionApprovalAdapter,
    MockToolExecutionAdapter,
    SqliteToolActionRepository,
)
from regulated_ai.application import (
    ExecuteToolAction,
    InvalidToolActionError,
    ToolActionConflictError,
    ToolActionExecutionFailedError,
    ToolResultRejectedError,
)
from regulated_ai.domain import (
    DecisionOutcome,
    EnforcementRecord,
    EnforcementStatus,
    EvidenceMetadata,
    ToolActionPlan,
    ToolActionResult,
    ToolActionStatus,
    ToolExecutionReceipt,
    ToolExecutionResult,
    ToolProposal,
    ToolResultClassification,
)

from ..helpers import (
    NOW,
    MemoryEnforcementRepository,
    MemoryEvidenceRepository,
    MemoryToolCatalogRepository,
    action_approval_assertion,
    authorized_tool,
)

KEY = b"t" * 32
RAW_ARGUMENT = "synthetic-account-token"
IDEMPOTENCY_KEY = "synthetic-idempotency-key"


class _FailingExecution:
    def __init__(self) -> None:
        self.call_count = 0
        self.last_plan: ToolActionPlan | None = None

    def execute(self, plan: ToolActionPlan) -> ToolExecutionResult:
        self.call_count += 1
        self.last_plan = plan
        raise TimeoutError("synthetic timeout")


def _arguments_digest(arguments: dict[str, str], *, tool_name: str, schema_digest: str) -> str:
    binding = json.dumps(
        {
            "arguments": arguments,
            "schema_digest": schema_digest,
            "tool": tool_name,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return f"sha256:{hashlib.sha256(binding).hexdigest()}"


def _service(
    tmp_path: Path,
    *,
    execution: MockToolExecutionAdapter | _FailingExecution | None = None,
) -> tuple[ExecuteToolAction, MockToolExecutionAdapter | _FailingExecution, Path]:
    tool = authorized_tool("cards.unblock", "high_impact_state_change")
    proposal = ToolProposal(
        call_id="call_test_1",
        tool_name=tool.name,
        tool_schema_version=tool.schema_version,
        tool_schema_digest=tool.input_schema_digest,
        arguments_digest=_arguments_digest(
            {"token": RAW_ARGUMENT},
            tool_name=tool.name,
            schema_digest=tool.input_schema_digest,
        ),
    )
    evidence = EvidenceMetadata(
        evidence_id="ev_action_test",
        created_at=NOW,
        correlation_id="correlation-action-test",
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        policy_set_version="policy@test",
        provider_registry_version="registry@test",
        matched_policy_ids=("rule@test",),
        provider_capability_ids=(),
        control_objective_ids=("CONTROL.TEST",),
        obligation_types=(),
        classification_labels=(),
        reason_codes=("TEST",),
        input_digest=f"sha256:{'1' * 64}",
        output_digest=f"sha256:{'2' * 64}",
        event_digest=f"sha256:{'3' * 64}",
        tool_catalog_version=tool.catalog_version,
        authorized_tool_ids=(tool.identifier,),
    )
    enforcement = EnforcementRecord(
        enforcement_id="enf_action_test",
        created_at=NOW,
        evaluation_id="eval_action_test",
        evaluation_evidence_id=evidence.evidence_id,
        decision=DecisionOutcome.REQUIRE_APPROVAL,
        status=EnforcementStatus.EXECUTED,
        policy_set_version=evidence.policy_set_version,
        provider_registry_version=evidence.provider_registry_version,
        provider_target="provider.service.region",
        transformation_receipts=(),
        reason_codes=(),
        input_digest=evidence.input_digest,
        output_digest=evidence.output_digest,
        provider_execution_id="provider_action_test",
        tool_proposals=(proposal,),
    )
    evidence_repository = MemoryEvidenceRepository()
    evidence_repository.items[evidence.evidence_id] = evidence
    enforcement_repository = MemoryEnforcementRepository()
    enforcement_repository.items[enforcement.enforcement_id] = enforcement
    database_path = tmp_path / "actions.sqlite3"
    selected_execution = execution or MockToolExecutionAdapter()
    service = ExecuteToolAction(
        enforcement=enforcement_repository,
        evidence=evidence_repository,
        tools=MemoryToolCatalogRepository((tool,)),
        actions=SqliteToolActionRepository(database_path),
        execution=selected_execution,
        approval=HmacActionApprovalAdapter(database_path, KEY),
        clock=lambda: NOW,
    )
    return service, selected_execution, database_path


def _execute(
    service: ExecuteToolAction,
    *,
    approval_assertion: str | None = None,
    arguments: dict[str, object] | None = None,
    idempotency_key: str = IDEMPOTENCY_KEY,
) -> ToolActionResult:
    return service.execute(
        enforcement_id="enf_action_test",
        call_id="call_test_1",
        arguments={"token": RAW_ARGUMENT} if arguments is None else arguments,
        workload_identity="workload.cards-test",
        idempotency_key=idempotency_key,
        approval_assertion=approval_assertion,
    )


def test_exact_action_waits_for_new_approval_then_executes_once(tmp_path: Path) -> None:
    service, execution, database_path = _service(tmp_path)

    waiting = _execute(service)
    assertion = action_approval_assertion(KEY, waiting.action_digest)
    completed = _execute(service, approval_assertion=assertion)
    replayed = _execute(service, approval_assertion=assertion)

    assert waiting.status is ToolActionStatus.WAITING_APPROVAL
    assert waiting.approval_receipt is None
    assert completed.status is ToolActionStatus.EXECUTED
    assert completed.approval_receipt is not None
    assert completed.approval_receipt.action_digest == waiting.action_digest
    assert replayed.action_id == completed.action_id
    assert replayed.status == completed.status
    assert replayed.safe_output is None
    assert dict(completed.safe_output or ()) == {
        "public_result": "SUCCEEDED",
        "sensitive_result": "***MASKED***",
    }
    assert completed.exposed_result_fields == ("public_result", "sensitive_result")
    assert completed.result_classifications == (
        ToolResultClassification.AUTHENTICATION_SECRET,
        ToolResultClassification.FINANCIAL,
        ToolResultClassification.INTERNAL,
    )
    assert completed.safe_output_digest is not None
    assert execution.call_count == 1
    assert execution.last_plan is not None
    assert dict(execution.last_plan.arguments) == {"token": RAW_ARGUMENT}
    stored = database_path.read_bytes().decode(errors="ignore")
    assert RAW_ARGUMENT not in stored
    assert IDEMPOTENCY_KEY not in stored
    assert assertion not in stored
    assert "SUCCEEDED" not in stored
    assert "synthetic-sensitive-result" not in stored
    assert "synthetic-secret-result" not in stored


def test_ephemeral_tool_result_repr_excludes_raw_output() -> None:
    result = ToolExecutionResult(
        receipt=ToolExecutionReceipt(execution_id="mocktool_test", action_id="act_test"),
        output={"secret_result": "raw-output-sentinel"},
    )

    assert "raw-output-sentinel" not in repr(result)


@pytest.mark.parametrize(
    "output",
    [
        {
            "public_result": "SUCCEEDED",
            "sensitive_result": "sensitive-sentinel",
            "secret_result": "secret-sentinel",
            "unexpected": "unexpected-sentinel",
        },
        {
            "public_result": "SUCCEEDED",
            "sensitive_result": "sensitive-sentinel",
        },
        {
            "public_result": 123,
            "sensitive_result": "sensitive-sentinel",
            "secret_result": "secret-sentinel",
        },
        {
            "public_result": "UNAPPROVED",
            "sensitive_result": "sensitive-sentinel",
            "secret_result": "secret-sentinel",
        },
    ],
)
def test_untrusted_tool_result_fails_closed_without_persisting_content(
    tmp_path: Path, output: dict[str, object]
) -> None:
    execution = MockToolExecutionAdapter(output=output)
    service, _selected, database_path = _service(tmp_path, execution=execution)
    waiting = _execute(service)
    assertion = action_approval_assertion(KEY, waiting.action_digest)

    with pytest.raises(ToolResultRejectedError):
        _execute(service, approval_assertion=assertion)
    rejected = _execute(service, approval_assertion=assertion)

    assert rejected.status is ToolActionStatus.RESULT_REJECTED
    assert rejected.output_digest is None
    assert rejected.safe_output_digest is None
    assert rejected.safe_output is None
    assert execution.call_count == 1
    stored = database_path.read_bytes().decode(errors="ignore")
    for sentinel in (
        "sensitive-sentinel",
        "secret-sentinel",
        "unexpected-sentinel",
        "UNAPPROVED",
    ):
        assert sentinel not in stored


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"token": RAW_ARGUMENT, "unexpected": "value"},
        {"token": 123},
        {"token": "different-token"},
    ],
)
def test_invalid_or_digest_mismatched_arguments_fail_before_execution(
    tmp_path: Path, arguments: dict[str, object]
) -> None:
    service, execution, _database_path = _service(tmp_path)

    with pytest.raises(InvalidToolActionError):
        _execute(service, arguments=arguments)

    assert execution.call_count == 0


def test_same_proposal_cannot_be_rebound_to_another_idempotency_key(tmp_path: Path) -> None:
    service, execution, _database_path = _service(tmp_path)
    waiting = _execute(service)

    with pytest.raises(ToolActionConflictError):
        _execute(service, idempotency_key="different-key")

    assert waiting.status is ToolActionStatus.WAITING_APPROVAL
    assert execution.call_count == 0


def test_prepared_action_resumes_atomic_claim_without_rebinding(tmp_path: Path) -> None:
    service, execution, database_path = _service(tmp_path)
    waiting = _execute(service)
    repository = SqliteToolActionRepository(database_path)
    record = repository.get(waiting.action_id)
    assert record is not None
    repository.save(replace(record, status=ToolActionStatus.PREPARED))
    assertion = action_approval_assertion(KEY, waiting.action_digest)

    completed = _execute(service, approval_assertion=assertion)

    assert completed.status is ToolActionStatus.EXECUTED
    assert execution.call_count == 1


def test_ambiguous_failure_is_terminal_and_never_retried(tmp_path: Path) -> None:
    execution = _FailingExecution()
    service, _selected, _database_path = _service(tmp_path, execution=execution)
    waiting = _execute(service)
    assertion = action_approval_assertion(KEY, waiting.action_digest)

    with pytest.raises(ToolActionExecutionFailedError):
        _execute(service, approval_assertion=assertion)
    reconciled = _execute(service, approval_assertion=assertion)

    assert reconciled.status is ToolActionStatus.RECONCILIATION_REQUIRED
    assert execution.call_count == 1
