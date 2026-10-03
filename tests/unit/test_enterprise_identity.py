import base64
import json
import traceback
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from regulated_ai.adapters import (
    ApiAuthenticationError,
    ApiAuthorizationError,
    ApiIdentityConfigurationError,
    EnterpriseJwtConfig,
    EnterpriseJwtVerifier,
)

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
NOW_SECONDS = int(NOW.timestamp())


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _write_jwks(path: Path, private_key: Ed25519PrivateKey, *, kid: str = "idp-key-1") -> None:
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "alg": "EdDSA",
                        "crv": "Ed25519",
                        "kid": kid,
                        "kty": "OKP",
                        "use": "sig",
                        "x": _b64url(public_key),
                    }
                ]
            }
        )
    )


def _config(path: Path, **changes: object) -> EnterpriseJwtConfig:
    values: dict[str, object] = {
        "issuer": "https://identity.example.test/tenant/regulaai",
        "audience": "regulaai-api",
        "jwks_path": path,
        "max_token_age_seconds": 900,
        "clock_skew_seconds": 30,
    }
    values.update(changes)
    return EnterpriseJwtConfig(**values)  # type: ignore[arg-type]


def _claims(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "aud": "regulaai-api",
        "client_id": "customer-support",
        "exp": NOW_SECONDS + 300,
        "iat": NOW_SECONDS - 10,
        "iss": "https://identity.example.test/tenant/regulaai",
        "jti": "synthetic-token-1",
        "nbf": NOW_SECONDS - 10,
        "roles": ["regulaai.runtime", "regulaai.operator"],
        "sub": "workload:customer-support",
    }
    values.update(changes)
    return values


def _token(
    private_key: Ed25519PrivateKey,
    *,
    claims: dict[str, object] | None = None,
    header: dict[str, object] | None = None,
) -> str:
    return _token_from_json(
        private_key,
        header=json.dumps(
            header or {"alg": "EdDSA", "kid": "idp-key-1", "typ": "at+jwt"},
            sort_keys=True,
            separators=(",", ":"),
        ),
        claims=json.dumps(claims or _claims(), sort_keys=True, separators=(",", ":")),
    )


def _token_from_json(private_key: Ed25519PrivateKey, *, header: str, claims: str) -> str:
    encoded_header = _b64url(header.encode())
    encoded_claims = _b64url(claims.encode())
    signing_input = f"{encoded_header}.{encoded_claims}"
    signature = _b64url(private_key.sign(signing_input.encode()))
    return f"{signing_input}.{signature}"


def _verifier(tmp_path: Path) -> tuple[EnterpriseJwtVerifier, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    jwks_path = tmp_path / "api-identity.jwks.json"
    _write_jwks(jwks_path, private_key)
    return EnterpriseJwtVerifier(_config(jwks_path)), private_key


def test_authenticates_exact_issuer_audience_role_and_signature(tmp_path: Path) -> None:
    verifier, private_key = _verifier(tmp_path)

    principal = verifier.authenticate(
        _token(private_key),
        required_role="regulaai.runtime",
        now=NOW,
    )

    assert principal.subject == "workload:customer-support"
    assert principal.key_id == "idp-key-1"
    assert principal.roles == ("regulaai.operator", "regulaai.runtime")


def test_authenticated_principal_must_have_required_role(tmp_path: Path) -> None:
    verifier, private_key = _verifier(tmp_path)

    with pytest.raises(ApiAuthorizationError, match="not authorized"):
        verifier.authenticate(
            _token(private_key),
            required_role="regulaai.reconciler",
            now=NOW,
        )


@pytest.mark.parametrize("token_type", ["at+jwt", "application/at+jwt", "at+JWT"])
def test_access_token_typing_is_explicit(tmp_path: Path, token_type: str) -> None:
    verifier, private_key = _verifier(tmp_path)

    assert (
        verifier.authenticate(
            _token(private_key, header={"alg": "EdDSA", "kid": "idp-key-1", "typ": token_type}),
            required_role="regulaai.runtime",
            now=NOW,
        ).subject
        == "workload:customer-support"
    )


@pytest.mark.parametrize(
    "header,claims",
    [
        ('{"alg":"EdDSA","alg":"EdDSA","kid":"idp-key-1","typ":"at+jwt"}', None),
        (None, '{"iss":"issuer","iss":"issuer"}'),
        (None, '{"unexpected":NaN}'),
        (None, '{"unexpected":Infinity}'),
        (None, "[]"),
        (None, "not-json"),
        ('{"unexpected":' + "[" * 1200 + "0" + "]" * 1200 + "}", None),
    ],
)
def test_malformed_json_and_duplicate_fields_fail_closed(
    tmp_path: Path, header: str | None, claims: str | None
) -> None:
    verifier, private_key = _verifier(tmp_path)
    token = _token_from_json(
        private_key,
        header=header or '{"alg":"EdDSA","kid":"idp-key-1","typ":"at+jwt"}',
        claims=claims or json.dumps(_claims()),
    )

    with pytest.raises(ApiAuthenticationError, match="invalid"):
        verifier.authenticate(token, required_role="regulaai.runtime", now=NOW)


@pytest.mark.parametrize("token", ["", "a.b.c.d", "a.b.é", "a.b.\ud800", "x" * 8193])
def test_invalid_compact_token_fails_closed(tmp_path: Path, token: str) -> None:
    verifier, _private_key = _verifier(tmp_path)

    with pytest.raises(ApiAuthenticationError, match="invalid"):
        verifier.authenticate(token, required_role="regulaai.runtime", now=NOW)


@pytest.mark.parametrize(
    "claims",
    [
        _claims(iss="https://other.example.test"),
        _claims(aud="another-api"),
        _claims(aud=["regulaai-api", "regulaai-api"]),
        _claims(exp=NOW_SECONDS - 31),
        _claims(iat=NOW_SECONDS + 31, nbf=NOW_SECONDS + 31),
        _claims(nbf=NOW_SECONDS + 31),
        _claims(exp=NOW_SECONDS + 1000),
        _claims(roles=["regulaai.runtime", "unknown-role"]),
        _claims(sub="unsafe subject"),
        _claims(client_id=None),
        _claims(jti="unsafe token id"),
        _claims(exp=True),
        _claims(nbf=NOW_SECONDS - 11),
        _claims(roles=["regulaai.runtime", "regulaai.runtime"]),
    ],
)
def test_rejects_untrusted_or_invalid_claims(tmp_path: Path, claims: dict[str, object]) -> None:
    verifier, private_key = _verifier(tmp_path)

    with pytest.raises(ApiAuthenticationError, match="invalid"):
        verifier.authenticate(
            _token(private_key, claims=claims),
            required_role="regulaai.runtime",
            now=NOW,
        )


def test_rejects_unknown_key_wrong_signature_and_header_confusion(tmp_path: Path) -> None:
    verifier, private_key = _verifier(tmp_path)
    other_key = Ed25519PrivateKey.generate()
    tokens = (
        _token(private_key, header={"alg": "EdDSA", "kid": "unknown", "typ": "at+jwt"}),
        _token(other_key),
        _token(private_key, header={"alg": "HS256", "kid": "idp-key-1", "typ": "at+jwt"}),
        _token(private_key, header={"alg": "EdDSA", "kid": "idp-key-1", "typ": "JWT"}),
        _token(
            private_key,
            header={"alg": "EdDSA", "crit": ["exp"], "kid": "idp-key-1", "typ": "at+jwt"},
        ),
    )

    for token in tokens:
        with pytest.raises(ApiAuthenticationError, match="invalid"):
            verifier.authenticate(token, required_role="regulaai.runtime", now=NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer": "http://identity.example.test"},
        {"issuer": "https://user@identity.example.test/tenant"},
        {"issuer": "https://identity.example.test/tenant?other=true"},
        {"audience": "unsafe audience"},
        {"max_token_age_seconds": 0},
        {"max_token_age_seconds": 86_401},
        {"clock_skew_seconds": -1},
        {"clock_skew_seconds": 301},
    ],
)
def test_rejects_unsafe_identity_configuration(tmp_path: Path, changes: dict[str, object]) -> None:
    with pytest.raises(ApiIdentityConfigurationError):
        _config(tmp_path / "unused.json", **changes)


def test_rejects_invalid_jwks_at_startup(tmp_path: Path) -> None:
    jwks_path = tmp_path / "api-identity.jwks.json"
    jwks_path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "alg": "EdDSA",
                        "crv": "Ed25519",
                        "kid": "idp-key-1",
                        "kty": "OKP",
                        "use": "sig",
                        "x": "invalid-public-key-material-not-32-bytes",
                    }
                ]
            }
        )
    )

    with pytest.raises(ApiIdentityConfigurationError, match="invalid"):
        EnterpriseJwtVerifier(_config(jwks_path))


@pytest.mark.parametrize(
    "document",
    [
        '{"keys":[],"keys":[]}',
        '{"keys":NaN}',
        "[" * 12_000 + "0" + "]" * 12_000,
        " " * 262_145,
    ],
)
def test_malformed_or_oversized_jwks_fails_startup(tmp_path: Path, document: str) -> None:
    jwks_path = tmp_path / "api-identity.jwks.json"
    jwks_path.write_text(document)

    with pytest.raises(ApiIdentityConfigurationError):
        EnterpriseJwtVerifier(_config(jwks_path))


@pytest.mark.parametrize("mutation", ["duplicate-kid", "private-key", "wrong-alg"])
def test_untrusted_jwks_key_metadata_fails_startup(tmp_path: Path, mutation: str) -> None:
    private_key = Ed25519PrivateKey.generate()
    jwks_path = tmp_path / "api-identity.jwks.json"
    _write_jwks(jwks_path, private_key)
    raw = json.loads(jwks_path.read_text())
    if mutation == "duplicate-kid":
        raw["keys"].append(raw["keys"][0].copy())
    elif mutation == "private-key":
        raw["keys"][0]["d"] = "synthetic-forbidden-private-field"
    else:
        raw["keys"][0]["alg"] = "HS256"
    jwks_path.write_text(json.dumps(raw))

    with pytest.raises(ApiIdentityConfigurationError) as captured:
        EnterpriseJwtVerifier(_config(jwks_path))
    assert "synthetic-forbidden-private-field" not in "".join(
        traceback.format_exception(captured.value)
    )


def test_key_rotation_requires_reload_and_supports_overlap(tmp_path: Path) -> None:
    old_key = Ed25519PrivateKey.generate()
    new_key = Ed25519PrivateKey.generate()
    jwks_path = tmp_path / "api-identity.jwks.json"
    new_jwks_path = tmp_path / "new-api-identity.jwks.json"
    _write_jwks(jwks_path, old_key)
    _write_jwks(new_jwks_path, new_key, kid="idp-key-2")
    old_document = json.loads(jwks_path.read_text())
    new_document = json.loads(new_jwks_path.read_text())
    jwks_path.write_text(json.dumps({"keys": old_document["keys"] + new_document["keys"]}))
    overlapping_verifier = EnterpriseJwtVerifier(_config(jwks_path))
    old_token = _token(old_key)
    new_token = _token(new_key, header={"alg": "EdDSA", "kid": "idp-key-2", "typ": "at+jwt"})

    for token in (old_token, new_token):
        overlapping_verifier.authenticate(token, required_role="regulaai.runtime", now=NOW)

    jwks_path.write_text(json.dumps(new_document))
    overlapping_verifier.authenticate(old_token, required_role="regulaai.runtime", now=NOW)
    reloaded_verifier = EnterpriseJwtVerifier(_config(jwks_path))
    reloaded_verifier.authenticate(new_token, required_role="regulaai.runtime", now=NOW)
    with pytest.raises(ApiAuthenticationError):
        reloaded_verifier.authenticate(old_token, required_role="regulaai.runtime", now=NOW)


def test_requires_timezone_aware_verification_time(tmp_path: Path) -> None:
    verifier, private_key = _verifier(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        verifier.authenticate(
            _token(private_key),
            required_role="regulaai.runtime",
            now=datetime(2026, 9, 29, 12),
        )
