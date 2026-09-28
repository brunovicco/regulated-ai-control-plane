import json
from pathlib import Path

import pytest

import regulated_ai.entrypoints.api as api
import regulated_ai.entrypoints.live_composition_pilot as pilot
from regulated_ai.domain import (
    DataClassification,
    ExecutionPlan,
    ProviderCallMetadata,
    ProviderExecutionReceipt,
)
from regulated_ai.entrypoints.live_composition_pilot import (
    LiveCompositionPilotError,
    main,
    run_live_composition_pilot,
)


class _SyntheticGatewayExecution:
    def __init__(self) -> None:
        self.plan: ExecutionPlan | None = None

    def execute(self, plan: ExecutionPlan) -> ProviderExecutionReceipt:
        self.plan = plan
        return ProviderExecutionReceipt(
            execution_id="gw_00000000000000000000000000000001",
            provider_target=plan.provider.identifier,
            plan_id=plan.plan_id,
            output_digest=plan.output_digest,
            call_metadata=ProviderCallMetadata(
                gateway_request_id="00000000-0000-0000-0000-000000000001",
                routing_decision_id="routing-pilot-1",
                policy_id="gateway.pilot",
                policy_version="1",
                provider="openai",
                model="synthetic-model",
                deployment="synthetic-deployment",
                latency_ms=25,
                attempt_number=1,
                fallback_index=0,
                cached=False,
            ),
        )


def test_live_composition_pilot_proves_metadata_only_gateway_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _SyntheticGatewayExecution()
    monkeypatch.setattr(api, "_execution_adapter_from_environment", lambda: (gateway, None))
    runtime = api.build_runtime(evidence_path=tmp_path / "pilot.sqlite3")

    report = run_live_composition_pilot(runtime, correlation_id="pilot-contract-1")

    encoded = json.dumps(report, sort_keys=True)
    assert report["status"] == "LIVE_COMPOSITION_VERIFIED"
    assert report["data_handling"] == {
        "input_profile": "FIXED_SYNTHETIC",
        "request_content_persisted": False,
        "model_output_persisted": False,
        "model_output_returned": False,
        "tool_execution_enabled": False,
    }
    assert isinstance(report["report_digest"], str)
    assert report["report_digest"].startswith("sha256:")
    assert "synthetic-customer-document" not in encoded
    assert "synthetic support availability question" not in encoded
    assert gateway.plan is not None
    values = {item.field: item.value for item in gateway.plan.data_items}
    assert values["customer_document"].startswith("tok_")
    assert "synthetic-customer-document" not in repr(gateway.plan)
    assert (
        DataClassification.PERSONAL_DIRECT_IDENTIFIER
        in next(
            item for item in gateway.plan.data_items if item.field == "customer_document"
        ).labels
    )


def test_live_composition_pilot_rejects_mock_runtime(
    tmp_path: Path,
) -> None:
    runtime = api.build_runtime(evidence_path=tmp_path / "mock.sqlite3")

    with pytest.raises(LiveCompositionPilotError, match="gateway execution mode"):
        run_live_composition_pilot(runtime, correlation_id="pilot-contract-2")


def test_live_composition_cli_requires_explicit_gateway_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("REGULAAI_EXECUTION_MODE", raising=False)

    assert main(["--correlation-prefix", "pilot-contract-3"]) == 1

    assert "gateway execution mode is required" in capsys.readouterr().err


def test_live_composition_cli_rejects_production_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("REGULAAI_EXECUTION_MODE", "gateway")
    monkeypatch.setenv("REGULAAI_ENVIRONMENT", "production")
    monkeypatch.setenv("REGULAAI_EVIDENCE_DB", "/synthetic/pilot.sqlite3")

    assert main([]) == 1

    assert "non-production environment is required" in capsys.readouterr().err


def test_live_composition_cli_requires_dedicated_evidence_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("REGULAAI_EXECUTION_MODE", "gateway")
    monkeypatch.setenv("REGULAAI_ENVIRONMENT", "pilot")
    monkeypatch.delenv("REGULAAI_EVIDENCE_DB", raising=False)

    assert main([]) == 1

    assert "dedicated evidence database is required" in capsys.readouterr().err


def test_live_composition_cli_emits_fresh_metadata_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gateway = _SyntheticGatewayExecution()
    monkeypatch.setattr(api, "_execution_adapter_from_environment", lambda: (gateway, None))
    runtime = api.build_runtime(evidence_path=tmp_path / "pilot-cli.sqlite3")
    monkeypatch.setattr(pilot, "build_runtime", lambda: runtime)
    monkeypatch.setenv("REGULAAI_EXECUTION_MODE", "gateway")
    monkeypatch.setenv("REGULAAI_ENVIRONMENT", "pilot")
    monkeypatch.setenv("REGULAAI_EVIDENCE_DB", str(tmp_path / "pilot-cli.sqlite3"))

    assert main(["--correlation-prefix", "change-123"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "LIVE_COMPOSITION_VERIFIED"
    assert report["correlation_id"].startswith("change-123-")
    assert "synthetic support availability question" not in json.dumps(report)
