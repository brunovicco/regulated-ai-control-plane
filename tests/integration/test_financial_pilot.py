"""Real PostgreSQL plus the complete API/authority/gateway/tool adapter composition."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from governed_llm_gateway_contracts import ToolCall

import regulated_ai.adapters.gateway_execution as gateway_module
import regulated_ai.adapters.state_changing_tool_execution as tool_module
from regulated_ai.adapters import PostgresDatabase
from regulated_ai.entrypoints.api import build_runtime, create_app
from regulated_ai.entrypoints.identity_pilot import PilotApiTokens, probe_enterprise_identity

from ..unit.test_gateway_execution import FakeGatewayClient
from .pilot_support import PilotIssuer

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("provider", ["openai", "aws"])
@pytest.mark.parametrize("outcome", ["success", "EXECUTED", "NOT_EXECUTED"])
def test_financial_pilot_identity_gateway_approval_and_recovery(
    database: PostgresDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    outcome: str,
) -> None:
    issuer = PilotIssuer(tmp_path)
    arguments = {"account_token": "tok_pilot_synthetic", "reason_code": "CUSTOMER_VERIFIED"}
    gateway_tool = f"ra_cards_unblock_{hashlib.sha256(b'cards.unblock').hexdigest()[:32]}"
    gateway = FakeGatewayClient(
        provider=provider,
        tool_calls=(ToolCall(call_id="pilot_call", name=gateway_tool, arguments=arguments),),
    )
    monkeypatch.setattr(gateway_module, "_default_client_factory", lambda _config: gateway)
    tool_calls = 0

    def sandbox(request: httpx.Request) -> httpx.Response:
        nonlocal tool_calls
        tool_calls += 1
        body = json.loads(request.content)
        if outcome != "success":
            raise httpx.ReadTimeout("synthetic ambiguous outcome")
        return httpx.Response(
            200,
            json={
                "action_id": body["action_id"],
                "action_digest": body["action_digest"],
                "idempotency_key_digest": body["idempotency_key_digest"],
                "execution_id": "pilot-effect",
                "output": {
                    "operation_status": "SUCCEEDED",
                    "operation_reference": "synthetic-result-sentinel",
                    "diagnostic": "drop",
                },
            },
        )

    monkeypatch.setattr(
        tool_module,
        "_default_client_factory",
        lambda _config: httpx.Client(
            transport=httpx.MockTransport(sandbox),
            timeout=1,
            trust_env=False,
        ),
    )
    target = (
        "openai.responses_api.global" if provider == "openai" else "aws.bedrock_runtime.sa-east-1"
    )
    settings = {
        "REGULAAI_DATABASE_URL": os.environ["REGULAAI_TEST_POSTGRES_URL"],
        "REGULAAI_ENVIRONMENT": "pilot",
        "REGULAAI_API_AUTH_MODE": "oidc_jwt",
        "REGULAAI_OIDC_ISSUER": "https://identity.example.test/pilot",
        "REGULAAI_OIDC_AUDIENCE": "regulaai-pilot",
        "REGULAAI_OIDC_JWKS_PATH": str(issuer.jwks),
        "REGULAAI_OPERATOR_AUTHORITY_TRUST_STORE": str(issuer.trust_store),
        "REGULAAI_EXECUTION_MODE": "gateway",
        "GOVERNED_LLM_GATEWAY_URL": "https://gateway.example.test",
        "GOVERNED_LLM_GATEWAY_API_KEY": "synthetic-only",
        "REGULAAI_GATEWAY_WORKLOAD": "pilot.inference",
        "REGULAAI_GATEWAY_ALLOWED_TARGET": target,
        "REGULAAI_GATEWAY_EXPECTED_PROVIDER": provider,
        "REGULAAI_TOOL_EXECUTION_MODE": "state_change_http",
        "REGULAAI_STATE_CHANGE_TOOL_URL": "https://sandbox.example.test/unblock",
        "REGULAAI_STATE_CHANGE_TOOL_API_KEY": "synthetic-only",
        "REGULAAI_STATE_CHANGE_TOOL_WORKLOAD_IDENTITY": "pilot.cards",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    runtime = build_runtime()
    runtime_headers = issuer.headers("regulaai.runtime")
    operator_headers = issuer.headers("regulaai.operator")
    reconciler_headers = issuer.headers("regulaai.reconciler")
    request_body = {
        "correlation_id": f"pilot-{uuid4().hex}",
        "jurisdiction": "BR",
        "sector": "financial_services",
        "purpose": "customer_support",
        "operation_kind": "external_inference",
        "assurance_level": "standard",
        "provider": {
            "provider": provider,
            "service": "responses_api" if provider == "openai" else "bedrock_runtime",
            "region": "global" if provider == "openai" else "sa-east-1",
        },
        "data": [
            {
                "field": "customer_document",
                "value": "synthetic-document-sentinel",
                "labels": ["PERSONAL_DIRECT_IDENTIFIER"],
            }
        ],
        "tools": [{"name": "cards.unblock"}],
        "policy_set_version": "br-financial-demo@1.0.0",
    }
    with TestClient(create_app(lambda: runtime)) as client:
        identity_report = probe_enterprise_identity(
            client,
            PilotApiTokens(
                runtime_headers["Authorization"].removeprefix("Bearer "),
                operator_headers["Authorization"].removeprefix("Bearer "),
                reconciler_headers["Authorization"].removeprefix("Bearer "),
            ),
        )
        assert identity_report["status"] == "ENTERPRISE_IDENTITY_VERIFIED"
        assert identity_report["business_mutations"] == 0
        assert client.get("/v1/providers").status_code == 401
        assert (
            client.post("/v1/enforcements", json=request_body, headers=operator_headers).status_code
            == 403
        )
        waiting = client.post("/v1/enforcements", json=request_body, headers=runtime_headers)
        assert waiting.status_code == 200, waiting.text
        assert waiting.json()["status"] == "WAITING_APPROVAL"
        assert not gateway.calls and tool_calls == 0
        evidence = client.get(
            f"/v1/evidence/{waiting.json()['evaluation_evidence_id']}", headers=operator_headers
        ).json()
        decision_assertion = issuer.assertion("decision_approval", evidence["output_digest"])
        enforced = client.post(
            "/v1/enforcements",
            json={**request_body, "approval_assertion": decision_assertion},
            headers=runtime_headers,
        )
        assert enforced.status_code == 200, enforced.text
        assert enforced.json()["status"] == "EXECUTED"
        enforcement_id = enforced.json()["enforcement_id"]
        action_url = f"/v1/enforcements/{enforcement_id}/tool-actions"
        action_body = {
            "call_id": "pilot_call",
            "arguments": arguments,
            "workload_identity": "pilot.cards",
            "idempotency_key": f"pilot-{uuid4().hex}",
        }
        waiting_action = client.post(action_url, json=action_body, headers=runtime_headers)
        assert waiting_action.status_code == 200, waiting_action.text
        assert waiting_action.json()["status"] == "WAITING_APPROVAL"
        assert tool_calls == 0
        action_id = waiting_action.json()["action_id"]
        action_assertion = issuer.assertion(
            "action_approval", waiting_action.json()["action_digest"]
        )
        execution = client.post(
            action_url,
            json={**action_body, "approval_assertion": action_assertion},
            headers=runtime_headers,
        )
        assert tool_calls == 1
        if outcome == "success":
            assert execution.status_code == 200, execution.text
            assert execution.json()["status"] == "EXECUTED"
            assert "synthetic-result-sentinel" not in execution.text
        else:
            assert execution.status_code == 503, execution.text
            reconcile_url = f"/v1/tool-actions/{action_id}/reconciliation"
            reconciliation = issuer.assertion(
                "reconciliation", waiting_action.json()["action_digest"], outcome=outcome
            )
            body = {"reconciliation_assertion": reconciliation}
            assert client.post(reconcile_url, json=body, headers=runtime_headers).status_code == 403
            recovered = client.post(reconcile_url, json=body, headers=reconciler_headers)
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["status"] == f"RECONCILED_{outcome}"
            assert (
                client.post(reconcile_url, json=body, headers=reconciler_headers).json()
                == recovered.json()
            )
        client.post(
            action_url,
            json={**action_body, "approval_assertion": action_assertion},
            headers=runtime_headers,
        )
        assert tool_calls == 1 and len(gateway.calls) == 1
        timeline = client.get(
            f"/v1/operator/enforcements/{enforcement_id}/timeline", headers=operator_headers
        )
        assert timeline.status_code == 200, timeline.text
        assert timeline.json()["history_complete"]
        assert timeline.json()["stages"][-1]["approval_recorded"]
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT to_jsonb(e)::text FROM evidence e WHERE correlation_id=%s",
            (request_body["correlation_id"],),
        ).fetchall()
    stored = json.dumps(rows) + repr(runtime.actions.get(action_id)) + timeline.text
    for forbidden in (
        "synthetic-document-sentinel",
        "tok_pilot_synthetic",
        "synthetic-result-sentinel",
        decision_assertion,
        action_assertion,
        *runtime_headers.values(),
    ):
        assert forbidden not in stored
