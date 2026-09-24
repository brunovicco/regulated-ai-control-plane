"""Network-silent tool execution adapter for local proofs and tests."""

import hashlib

from regulated_ai.domain import ToolActionPlan, ToolExecutionReceipt


class MockToolExecutionAdapter:
    """Capture one approved action plan and return metadata-only evidence."""

    def __init__(self) -> None:
        """Initialize an empty process-local capture surface."""
        self.last_plan: ToolActionPlan | None = None
        self.call_count = 0

    def execute(self, plan: ToolActionPlan) -> ToolExecutionReceipt:
        """Simulate an idempotent downstream action without network access."""
        self.last_plan = plan
        self.call_count += 1
        execution_digest = hashlib.sha256(
            f"{plan.action_id}:{plan.idempotency_key}".encode()
        ).hexdigest()
        output_digest = hashlib.sha256(
            f"{plan.action_digest}:synthetic-success".encode()
        ).hexdigest()
        return ToolExecutionReceipt(
            execution_id=f"mocktool_{execution_digest[:24]}",
            action_id=plan.action_id,
            output_digest=f"sha256:{output_digest}",
        )
