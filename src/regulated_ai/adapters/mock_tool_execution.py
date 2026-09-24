"""Network-silent tool execution adapter for local proofs and tests."""

import hashlib
import json

from regulated_ai.domain import ToolActionPlan, ToolExecutionReceipt, ToolExecutionResult


class MockToolExecutionAdapter:
    """Capture one approved action plan and return metadata-only evidence."""

    def __init__(self, output: object | None = None) -> None:
        """Initialize an empty process-local capture surface."""
        self.last_plan: ToolActionPlan | None = None
        self.call_count = 0
        self._output = output

    def execute(self, plan: ToolActionPlan) -> ToolExecutionResult:
        """Simulate an idempotent downstream action and return ephemeral output."""
        self.last_plan = plan
        self.call_count += 1
        execution_digest = hashlib.sha256(
            f"{plan.action_id}:{plan.idempotency_key}".encode()
        ).hexdigest()
        return ToolExecutionResult(
            receipt=ToolExecutionReceipt(
                execution_id=f"mocktool_{execution_digest[:24]}",
                action_id=plan.action_id,
            ),
            output=self._output if self._output is not None else _synthetic_output(plan),
        )


def _synthetic_output(plan: ToolActionPlan) -> dict[str, str]:
    parsed: object = json.loads(plan.tool.output_schema_json)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("properties"), dict):
        raise ValueError("Trusted tool output schema is invalid")
    output: dict[str, str] = {}
    for field, raw_constraints in parsed["properties"].items():
        if not isinstance(field, str) or not isinstance(raw_constraints, dict):
            raise ValueError("Trusted tool output schema is invalid")
        choices = raw_constraints.get("enum")
        output[field] = (
            choices[0]
            if isinstance(choices, list) and choices and isinstance(choices[0], str)
            else f"synthetic-{field.replace('_', '-')}"
        )
    return output
