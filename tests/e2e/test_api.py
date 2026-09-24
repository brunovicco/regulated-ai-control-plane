from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from regulated_ai.adapters import (
    DeterministicDataClassifier,
    FilePolicyRepository,
    FileProviderCapabilityRepository,
    FileToolCatalogRepository,
    GovernedGatewayExecutionAdapter,
    HmacApprovalAdapter,
    HmacTokenizationAdapter,
    MockInferenceExecutionAdapter,
    SqliteEnforcementRepository,
    SqliteEvidenceRepository,
)
from regulated_ai.application import EnforceAiOperation, EvaluateAiOperation
from regulated_ai.entrypoints.api import (
    EvaluationRequest,
    Runtime,
    _to_context,
    build_runtime,
    create_app,
)

from ..helpers import approval_assertion, synthetic_cpf

APPROVAL_KEY = b"p" * 32


def _runtime(tmp_path: Path) -> Runtime:
    root = Path(__file__).resolve().parents[2]
    policies = FilePolicyRepository(
        (root / "examples/policies/br-financial-external-inference.yaml",)
    )
    capabilities = FileProviderCapabilityRepository(
        (
            root / "examples/provider-capabilities/openai-responses.yaml",
            root / "examples/provider-capabilities/aws-bedrock.yaml",
        )
    )
    tools = FileToolCatalogRepository(root / "examples/tools/br-financial-tools.yaml")
    database_path = tmp_path / "evidence.sqlite3"
    evidence = SqliteEvidenceRepository(database_path)
    enforcement = SqliteEnforcementRepository(database_path)
    evaluator = EvaluateAiOperation(
        policies=policies,
        capabilities=capabilities,
        evidence=evidence,
        classifier=DeterministicDataClassifier(),
        tools=tools,
        clock=lambda: datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    mock = MockInferenceExecutionAdapter()
    approval = HmacApprovalAdapter(database_path, APPROVAL_KEY)
    enforcer = EnforceAiOperation(
        evaluator=evaluator,
        tokenizer=HmacTokenizationAdapter(b"e" * 32),
        enforcement=enforcement,
        execution=mock,
        approval=approval,
        clock=lambda: datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    return Runtime(
        evaluator=evaluator,
        evidence=evidence,
        capabilities=capabilities,
        enforcer=enforcer,
        enforcement=enforcement,
        execution=mock,
        mock_execution=mock,
    )


def _request() -> dict[str, object]:
    return {
        "correlation_id": "demo-card-001",
        "jurisdiction": "BR",
        "sector": "financial_services",
        "purpose": "customer_support",
        "operation_kind": "external_inference",
        "assurance_level": "high",
        "provider": {
            "provider": "openai",
            "service": "responses_api",
            "region": "global",
        },
        "organization_assertions": {
            "eligible_organization_required": True,
            "endpoint_or_feature_must_be_zdr_eligible": True,
        },
        "data": [
            {
                "field": "customer_document",
                "value": synthetic_cpf(),
                "labels": ["PERSONAL_DIRECT_IDENTIFIER"],
            },
            {"field": "question", "value": "synthetic support question", "labels": []},
        ],
        "tools": [
            {"name": "cards.read", "risk_class": "read_only"},
            {"name": "cards.unblock", "risk_class": "high_impact_state_change"},
        ],
        "policy_set_version": "br-financial-demo@1.0.0",
    }


def test_end_to_end_card_unblock_evaluation_and_evidence_privacy(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    app = create_app(lambda: runtime)
    request = _request()

    with TestClient(app) as client:
        response = client.post("/v1/evaluations", json=request)
        assert response.status_code == 200
        body = response.json()
        evidence = client.get(f"/v1/evidence/{body['evidence_id']}")
        providers = client.get("/v1/providers")
        health = client.get("/health")

    assert body["decision"] == "REQUIRE_APPROVAL"
    assert {item["type"] for item in body["obligations"]} >= {
        "TOKENIZE",
        "REQUIRE_HUMAN_APPROVAL",
        "REQUIRE_EVIDENCE",
    }
    assert evidence.status_code == 200
    assert body["tool_catalog_version"] == "br-financial-tools@1.0.0"
    assert body["authorized_tools"] == ["cards.read@1.0.0", "cards.unblock@1.0.0"]
    serialized_evidence = evidence.text
    data = request["data"]
    assert isinstance(data, list)
    for item in data:
        assert isinstance(item, dict)
        assert item["value"] not in serialized_evidence
    assert evidence.json()["policy_set_version"] == "br-financial-demo@1.0.0"
    assert evidence.json()["provider_registry_version"] == "2026-09-22.1"
    assert providers.status_code == 200
    assert len(providers.json()["providers"]) == 2
    assert health.json() == {"status": "ok"}


def test_api_rejects_forged_tool_risk_claim(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    app = create_app(lambda: runtime)
    request = _request()
    request["tools"] = [{"name": "cards.unblock", "risk_class": "read_only"}]

    with TestClient(app) as client:
        response = client.post("/v1/evaluations", json=request)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TOOL_NOT_AUTHORIZED"


def test_packaged_runtime_records_are_loadable(tmp_path: Path) -> None:
    runtime = build_runtime(evidence_path=tmp_path / "packaged-evidence.sqlite3")

    assert runtime.capabilities.registry_version == "2026-09-22.1"
    assert {item.target.provider for item in runtime.capabilities.list()} == {"aws", "openai"}


def test_runtime_gateway_mode_requires_complete_explicit_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGULAAI_EXECUTION_MODE", "gateway")
    monkeypatch.setenv("GOVERNED_LLM_GATEWAY_URL", "https://gateway.example.test")
    monkeypatch.setenv("GOVERNED_LLM_GATEWAY_API_KEY", "synthetic-gateway-credential")
    monkeypatch.setenv("REGULAAI_GATEWAY_WORKLOAD", "regulated-ai.external-inference")
    monkeypatch.setenv("REGULAAI_GATEWAY_ALLOWED_TARGET", "openai.responses_api.global")
    monkeypatch.setenv("REGULAAI_GATEWAY_EXPECTED_PROVIDER", "openai")

    runtime = build_runtime(evidence_path=tmp_path / "gateway-evidence.sqlite3")

    assert isinstance(runtime.execution, GovernedGatewayExecutionAdapter)
    assert runtime.mock_execution is None


def test_runtime_gateway_mode_fails_closed_on_partial_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGULAAI_EXECUTION_MODE", "gateway")
    monkeypatch.delenv("GOVERNED_LLM_GATEWAY_URL", raising=False)

    with pytest.raises(ValueError, match="GOVERNED_LLM_GATEWAY_URL"):
        build_runtime(evidence_path=tmp_path / "gateway-evidence.sqlite3")


def test_runtime_approval_verifier_rejects_short_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGULAAI_APPROVAL_HMAC_KEY", "short")

    with pytest.raises(ValueError, match="at least 32 bytes"):
        build_runtime(evidence_path=tmp_path / "approval-evidence.sqlite3")


def test_enforcement_api_returns_only_metadata_after_mock_execution(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    app = create_app(lambda: runtime)
    request = _request()
    request["tools"] = [{"name": "cards.read", "risk_class": "read_only"}]
    data = request["data"]
    assert isinstance(data, list)
    raw_values = [item["value"] for item in data if isinstance(item, dict)]

    with TestClient(app) as client:
        response = client.post("/v1/enforcements", json=request)
        assert response.status_code == 200
        body = response.json()
        stored = client.get(f"/v1/enforcements/{body['enforcement_id']}")

    assert body["status"] == "EXECUTED"
    assert body["decision"] == "ALLOW_WITH_TRANSFORMATION"
    assert body["provider_execution_id"].startswith("mockexec_")
    assert stored.status_code == 200
    assert stored.json()["status"] == "EXECUTED"
    for value in raw_values:
        assert value not in response.text
        assert value not in stored.text
    mock_execution = runtime.mock_execution
    assert mock_execution is not None
    assert mock_execution.last_plan is not None
    plan_values = {item.field: item.value for item in mock_execution.last_plan.data_items}
    assert plan_values["customer_document"].startswith("tok_")
    assert raw_values[0] not in repr(mock_execution.last_plan)


def test_external_approval_resumes_same_enforcement_and_is_consumed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    app = create_app(lambda: runtime)
    request = _request()

    with TestClient(app) as client:
        waiting = client.post("/v1/enforcements", json=request)
        assert waiting.status_code == 200
        waiting_body = waiting.json()
        evidence = client.get(f"/v1/evidence/{waiting_body['evaluation_evidence_id']}")
        assert evidence.status_code == 200
        assertion = approval_assertion(APPROVAL_KEY, evidence.json()["output_digest"])
        approved_request = {**request, "approval_assertion": assertion}
        approved = client.post("/v1/enforcements", json=approved_request)
        stored = client.get(f"/v1/enforcements/{waiting_body['enforcement_id']}")

    assert waiting_body["status"] == "WAITING_APPROVAL"
    assert waiting_body["approval_receipt"] is None
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["status"] == "EXECUTED"
    assert approved_body["enforcement_id"] == waiting_body["enforcement_id"]
    assert approved_body["approval_receipt"] == stored.json()["approval_receipt"]
    assert approved_body["approval_receipt"]["approval_id"] == "approval-test-1"
    assert assertion not in approved.text
    assert assertion not in (tmp_path / "evidence.sqlite3").read_bytes().decode(errors="ignore")
    assert runtime.mock_execution is not None
    assert runtime.mock_execution.last_plan is not None
    assert runtime.mock_execution.last_plan.approval_receipt is not None


def test_invalid_external_approval_fails_closed_without_echoing_it(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    app = create_app(lambda: runtime)
    request = {**_request(), "approval_assertion": "synthetic-invalid-approval"}

    with TestClient(app) as client:
        response = client.post("/v1/enforcements", json=request)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "APPROVAL_FAILED"
    assert "synthetic-invalid-approval" not in response.text
    assert runtime.mock_execution is not None
    assert runtime.mock_execution.call_count == 0


def test_approval_cannot_authorize_a_different_operation_with_same_policy_result(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    app = create_app(lambda: runtime)
    first_request = _request()

    with TestClient(app) as client:
        first = client.post("/v1/enforcements", json=first_request)
        first_evidence = client.get(f"/v1/evidence/{first.json()['evaluation_evidence_id']}").json()
        assertion = approval_assertion(APPROVAL_KEY, first_evidence["output_digest"])
        different_request = {
            **first_request,
            "correlation_id": "demo-card-002",
            "approval_assertion": assertion,
        }
        rejected = client.post("/v1/enforcements", json=different_request)

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "APPROVAL_FAILED"
    assert runtime.mock_execution is not None
    assert runtime.mock_execution.call_count == 0


def test_api_returns_stable_errors_without_echoing_sensitive_content(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    app = create_app(lambda: runtime)
    sentinel = "synthetic-secret-error-sentinel"

    with TestClient(app) as client:
        invalid = client.post(
            "/v1/evaluations", json={"correlation_id": sentinel, "unexpected": sentinel}
        )
        missing_evidence = client.get("/v1/evidence/ev_missing")
        missing_enforcement = client.get("/v1/enforcements/enf_missing")
        request = _request()
        request["policy_set_version"] = "missing@1"
        missing_policy = client.post("/v1/evaluations", json=request)

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_EVALUATION_CONTEXT"
    assert sentinel not in invalid.text
    assert missing_evidence.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"
    assert missing_enforcement.json()["error"]["code"] == "ENFORCEMENT_NOT_FOUND"
    assert missing_policy.status_code == 404
    assert missing_policy.json()["error"]["code"] == "POLICY_SET_NOT_FOUND"


def test_evaluation_requires_no_network_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("live network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", blocked)
    runtime = _runtime(tmp_path)
    request = _request()
    request["tools"] = [{"name": "cards.read", "risk_class": "read_only"}]

    result = runtime.enforcer.execute(_to_context(EvaluationRequest.model_validate(request)))

    assert result.status.value == "EXECUTED"
