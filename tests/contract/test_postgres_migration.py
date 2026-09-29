import ast
from pathlib import Path

from regulated_ai.adapters import POSTGRES_SCHEMA_REVISION

_ROOT = Path(__file__).parents[2]
_MIGRATION = _ROOT / "migrations" / "versions" / "0001_production_persistence.py"


def test_postgres_migration_matches_runtime_revision_and_metadata_boundary() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    module = ast.parse(source)
    assignments: dict[str, object] = {}
    for node in module.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in {"revision", "down_revision"}
            and node.value is not None
        ):
            assignments[node.target.id] = ast.literal_eval(node.value)

    assert assignments == {"revision": POSTGRES_SCHEMA_REVISION, "down_revision": None}
    for table in (
        "evidence",
        "enforcement",
        "tool_action",
        "approval_consumption",
        "action_approval_consumption",
        "tool_action_reconciliation_consumption",
        "operator_lifecycle_event",
    ):
        assert f"CREATE TABLE {table}" in source
    assert "regulaai_reject_lifecycle_mutation" in source
    assert "raw_prompt" not in source
    assert "raw_response" not in source
    assert "idempotency_key TEXT" not in source
