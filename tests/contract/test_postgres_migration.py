import ast
from pathlib import Path

from regulated_ai.adapters import POSTGRES_SCHEMA_REVISION

_ROOT = Path(__file__).parents[2]
_BASE_MIGRATION = _ROOT / "migrations" / "versions" / "0001_production_persistence.py"
_HEAD_MIGRATION = _ROOT / "migrations" / "versions" / "0002_operator_authority.py"


def test_postgres_migration_matches_runtime_revision_and_metadata_boundary() -> None:
    source = _BASE_MIGRATION.read_text(encoding="utf-8")
    head_source = _HEAD_MIGRATION.read_text(encoding="utf-8")
    module = ast.parse(head_source)
    assignments: dict[str, object] = {}
    for node in module.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in {"revision", "down_revision"}
            and node.value is not None
        ):
            assignments[node.target.id] = ast.literal_eval(node.value)

    assert assignments == {
        "revision": POSTGRES_SCHEMA_REVISION,
        "down_revision": "0001_production_persistence",
    }
    assert len(POSTGRES_SCHEMA_REVISION) <= 32
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
    assert head_source.count("ADD COLUMN authority_key_id TEXT") == 3
    assert "private_key" not in head_source
    assert "assertion" not in head_source


def test_postgres_downgrade_drops_trigger_owners_before_lifecycle_functions() -> None:
    module = ast.parse(_BASE_MIGRATION.read_text(encoding="utf-8"))
    downgrade = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    sql = "\n".join(
        str(ast.literal_eval(node.args[0]))
        for node in ast.walk(downgrade)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
        and node.func.attr == "execute"
    )

    record_function = sql.index("DROP FUNCTION IF EXISTS regulaai_record_lifecycle();")
    for table in ("evidence", "enforcement", "tool_action"):
        assert sql.index(f"DROP TABLE IF EXISTS {table};") < record_function
    assert sql.index("DROP TABLE IF EXISTS operator_lifecycle_event;") < sql.index(
        "DROP FUNCTION IF EXISTS regulaai_reject_lifecycle_mutation();"
    )
