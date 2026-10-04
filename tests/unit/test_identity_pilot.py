import json

import httpx
import pytest

from regulated_ai.entrypoints.identity_pilot import (
    PilotApiTokens,
    _validate_url,
    main,
    probe_enterprise_identity,
)


def test_identity_probe_checks_each_role_without_mutations_or_token_output() -> None:
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        expected = (
            "operator"
            if request.method == "GET"
            else "reconciler"
            if "reconciliation" in request.url.path
            else "runtime"
        )
        role = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not role:
            return httpx.Response(401)
        if role != expected:
            return httpx.Response(403)
        if request.method == "GET":
            return httpx.Response(
                200, json={"control_pack": {"payload_digest": f"sha256:{'a' * 64}"}}
            )
        assert json.loads(request.content) == {}
        return httpx.Response(422)

    with httpx.Client(
        base_url="https://pilot.example.test", transport=httpx.MockTransport(respond)
    ) as client:
        report = probe_enterprise_identity(
            client, PilotApiTokens("runtime", "operator", "reconciler")
        )
    assert len(seen) == 12 and report["business_mutations"] == 0
    assert report["status"] == "ENTERPRISE_IDENTITY_VERIFIED"
    assert "Bearer" not in json.dumps(report)


def test_disabled_auth_cannot_pass_identity_probe() -> None:
    with (
        httpx.Client(
            base_url="https://pilot.example.test",
            transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        ) as client,
        pytest.raises(ValueError, match="role matrix"),
    ):
        probe_enterprise_identity(client, PilotApiTokens("runtime", "operator", "reconciler"))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "http://localhost",
        "https://user@api.test",
        "https://api.test?token=x",
        "https://api.test/#fragment",
        "https://api.test\n",
    ],
)
def test_probe_rejects_unsafe_endpoints(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_url(url)


def test_probe_cli_rejects_production_without_reading_tokens(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("REGULAAI_ENVIRONMENT", "production")
    monkeypatch.setenv("REGULAAI_PILOT_RUNTIME_TOKEN", "sensitive-sentinel")
    assert main([]) == 1
    assert "sensitive-sentinel" not in capsys.readouterr().err
