"""Tests for the project-owned quality gate configuration."""

from pathlib import Path

from scripts.quality_gate import configured_checks


def test_dependency_audit_uses_osv_service() -> None:
    """Audit Git dependencies without querying nonexistent PyPI project pages."""
    root = Path(__file__).resolve().parents[2]
    checks = {check.name: check.command for check in configured_checks(root)}

    assert checks["dependencies"] == (
        "pip-audit",
        "--vulnerability-service",
        "osv",
    )
