"""Network-silent inference execution adapter for local enforcement tests and demos."""

import hashlib

from regulated_ai.domain import ExecutionPlan, ProviderExecutionReceipt


class MockInferenceExecutionAdapter:
    """Capture a sanitized execution plan and return metadata without model content."""

    def __init__(self) -> None:
        """Initialize an empty process-local capture surface."""
        self.last_plan: ExecutionPlan | None = None
        self.call_count = 0

    def execute(self, plan: ExecutionPlan) -> ProviderExecutionReceipt:
        """Capture only the already-transformed plan and simulate no external call."""
        self.last_plan = plan
        self.call_count += 1
        digest = hashlib.sha256(f"{plan.plan_id}:{plan.output_digest}".encode()).hexdigest()
        return ProviderExecutionReceipt(
            execution_id=f"mockexec_{digest[:24]}",
            provider_target=plan.provider.identifier,
            plan_id=plan.plan_id,
            output_digest=plan.output_digest,
        )
