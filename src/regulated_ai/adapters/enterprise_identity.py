"""Offline verification for enterprise-issued API access tokens."""

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ApiRole = Literal["regulaai.runtime", "regulaai.operator", "regulaai.reconciler"]

_MAX_TOKEN_BYTES = 8192
_MAX_JWKS_BYTES = 262_144
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@|/-]{0,127}\Z")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z")
_ALLOWED_ROLES: frozenset[str] = frozenset(
    {"regulaai.runtime", "regulaai.operator", "regulaai.reconciler"}
)


class ApiIdentityConfigurationError(ValueError):
    """The enterprise API identity configuration is unavailable or invalid."""


class ApiAuthenticationError(RuntimeError):
    """The presented bearer token cannot establish an authenticated principal."""


class ApiAuthorizationError(RuntimeError):
    """The authenticated principal lacks the required RegulaAI role."""


@dataclass(frozen=True, slots=True)
class EnterpriseJwtConfig:
    """Pinned resource-server identity and token-validation policy."""

    issuer: str
    audience: str
    jwks_path: Path
    max_token_age_seconds: int = 3600
    clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        """Reject incomplete or excessively permissive validation policy."""
        try:
            parsed_issuer = urlsplit(self.issuer)
            _ = parsed_issuer.port
        except ValueError:
            raise ApiIdentityConfigurationError("Enterprise JWT issuer is invalid") from None
        if (
            parsed_issuer.scheme != "https"
            or parsed_issuer.hostname is None
            or parsed_issuer.username is not None
            or parsed_issuer.password is not None
            or parsed_issuer.query
            or parsed_issuer.fragment
            or len(self.issuer) > 512
            or any(ord(char) <= 32 or ord(char) == 127 for char in self.issuer)
        ):
            raise ApiIdentityConfigurationError("Enterprise JWT issuer is invalid")
        if _SAFE_ID.fullmatch(self.audience) is None:
            raise ApiIdentityConfigurationError("Enterprise JWT audience is invalid")
        if self.max_token_age_seconds <= 0 or self.max_token_age_seconds > 86_400:
            raise ApiIdentityConfigurationError(
                "Enterprise JWT maximum lifetime must be in the range [1, 86400]"
            )
        if self.clock_skew_seconds < 0 or self.clock_skew_seconds > 300:
            raise ApiIdentityConfigurationError(
                "Enterprise JWT clock skew must be in the range [0, 300]"
            )


@dataclass(frozen=True, slots=True)
class AuthenticatedApiPrincipal:
    """Ephemeral, bounded identity used only for route authorization."""

    subject: str
    key_id: str
    roles: tuple[ApiRole, ...]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _JwkModel(_StrictModel):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    use: Literal["sig"]
    alg: Literal["EdDSA"]
    kid: str = Field(min_length=1, max_length=128)
    x: str = Field(min_length=43, max_length=43)

    @field_validator("kid")
    @classmethod
    def valid_key_id(cls, value: str) -> str:
        if _SAFE_ID.fullmatch(value) is None:
            raise ValueError("enterprise JWT key identifier is invalid")
        return value


class _JwksModel(_StrictModel):
    keys: tuple[_JwkModel, ...] = Field(min_length=1, max_length=64)

    @field_validator("keys")
    @classmethod
    def unique_keys(cls, value: tuple[_JwkModel, ...]) -> tuple[_JwkModel, ...]:
        key_ids = tuple(key.kid for key in value)
        if len(key_ids) != len(set(key_ids)):
            raise ValueError("enterprise JWKS contains duplicate key identifiers")
        return value


class EnterpriseJwtVerifier:
    """Verify strict EdDSA access tokens using deployment-pinned public keys."""

    def __init__(self, config: EnterpriseJwtConfig) -> None:
        """Load and validate all public verification keys at startup."""
        self._config = config
        self._keys = _load_jwks(config.jwks_path)

    def authenticate(
        self,
        token: str,
        *,
        required_role: ApiRole,
        now: datetime | None = None,
    ) -> AuthenticatedApiPrincipal:
        """Authenticate one token and require one exact application role."""
        checked_now = _utc_now(now)
        principal = self._verify(token, checked_now)
        if required_role not in principal.roles:
            raise ApiAuthorizationError("Authenticated principal is not authorized")
        return principal

    def _verify(self, token: str, now: datetime) -> AuthenticatedApiPrincipal:
        if not token or not token.isascii() or len(token) > _MAX_TOKEN_BYTES:
            raise ApiAuthenticationError("Bearer token is invalid")
        header_segment, separator, remainder = token.partition(".")
        payload_segment, signature_separator, signature_segment = remainder.partition(".")
        if (
            not separator
            or not signature_separator
            or "." in signature_segment
            or not header_segment
            or not payload_segment
            or not signature_segment
        ):
            raise ApiAuthenticationError("Bearer token is invalid")

        header = _decode_json_segment(header_segment)
        if set(header) != {"alg", "kid", "typ"} or header.get("alg") != "EdDSA":
            raise ApiAuthenticationError("Bearer token is invalid")
        token_type = _required_string(header, "typ")
        if token_type.casefold() not in {"at+jwt", "application/at+jwt"}:
            raise ApiAuthenticationError("Bearer token is invalid")
        key_id = _required_string(header, "kid")
        key = self._keys.get(key_id)
        if key is None:
            raise ApiAuthenticationError("Bearer token is invalid")

        signature = _decode_base64url(signature_segment, expected_bytes=64)
        try:
            key.verify(signature, f"{header_segment}.{payload_segment}".encode("ascii"))
        except (InvalidSignature, ValueError) as exc:
            raise ApiAuthenticationError("Bearer token is invalid") from exc

        claims = _decode_json_segment(payload_segment)
        subject = _required_string(claims, "sub")
        client_id = _required_string(claims, "client_id")
        token_id = _required_string(claims, "jti")
        issuer = _required_string(claims, "iss")
        issued_at = _numeric_date(claims, "iat")
        not_before = _optional_numeric_date(claims, "nbf", issued_at)
        expires_at = _numeric_date(claims, "exp")
        audiences = _audiences(claims.get("aud"))
        roles = _roles(claims.get("roles"))
        skew = self._config.clock_skew_seconds
        now_seconds = int(now.timestamp())
        if (
            _SAFE_ID.fullmatch(subject) is None
            or _SAFE_ID.fullmatch(client_id) is None
            or _SAFE_ID.fullmatch(token_id) is None
            or issuer != self._config.issuer
            or self._config.audience not in audiences
            or issued_at > now_seconds + skew
            or not_before > now_seconds + skew
            or expires_at <= now_seconds - skew
            or expires_at <= issued_at
            or not_before < issued_at
            or not_before >= expires_at
            or expires_at - issued_at > self._config.max_token_age_seconds
        ):
            raise ApiAuthenticationError("Bearer token is invalid")
        return AuthenticatedApiPrincipal(
            subject=subject,
            key_id=key_id,
            roles=roles,
        )


def _load_jwks(path: Path) -> dict[str, Ed25519PublicKey]:
    try:
        with path.open("rb") as stream:
            encoded = stream.read(_MAX_JWKS_BYTES + 1)
        if len(encoded) > _MAX_JWKS_BYTES:
            raise ApiIdentityConfigurationError("Enterprise JWKS is too large")
        raw = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_json_constant,
        )
        parsed = _JwksModel.model_validate(raw)
        return {
            key.kid: Ed25519PublicKey.from_public_bytes(
                _decode_base64url(key.x, expected_bytes=32, configuration=True)
            )
            for key in parsed.keys
        }
    except ApiIdentityConfigurationError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        RecursionError,
    ):
        # Validation errors may embed forbidden private fields from a misconfigured document.
        raise ApiIdentityConfigurationError("Enterprise JWKS is invalid") from None


def _decode_json_segment(segment: str) -> dict[str, object]:
    try:
        decoded = _decode_base64url(segment)
        raw: object = json.loads(
            decoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ApiAuthenticationError("Bearer token is invalid") from exc
    if not isinstance(raw, dict):
        raise ApiAuthenticationError("Bearer token is invalid")
    return raw


def _decode_base64url(
    value: str,
    *,
    expected_bytes: int | None = None,
    configuration: bool = False,
) -> bytes:
    if _BASE64URL.fullmatch(value) is None or "=" in value:
        raise _encoded_value_error(configuration)
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise _encoded_value_error(configuration) from exc
    if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
        raise _encoded_value_error(configuration)
    if expected_bytes is not None and len(decoded) != expected_bytes:
        raise _encoded_value_error(configuration)
    return decoded


def _encoded_value_error(configuration: bool) -> Exception:
    if configuration:
        return ApiIdentityConfigurationError("Encoded identity value is invalid")
    return ApiAuthenticationError("Encoded identity value is invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("identity document contains duplicate fields")
        result[key] = value
    return result


def _invalid_json_constant(_value: str) -> object:
    raise ValueError("identity document contains a non-JSON constant")


def _required_string(value: dict[str, object], field: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ApiAuthenticationError("Bearer token is invalid")
    return candidate


def _numeric_date(value: dict[str, object], field: str) -> int:
    candidate = value.get(field)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise ApiAuthenticationError("Bearer token is invalid")
    return candidate


def _optional_numeric_date(value: dict[str, object], field: str, default: int) -> int:
    candidate = value.get(field, default)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise ApiAuthenticationError("Bearer token is invalid")
    return candidate


def _audiences(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif (
        isinstance(value, list)
        and 1 <= len(value) <= 8
        and all(isinstance(item, str) for item in value)
    ):
        values = tuple(value)
    else:
        raise ApiAuthenticationError("Bearer token is invalid")
    if len(values) != len(set(values)) or any(_SAFE_ID.fullmatch(item) is None for item in values):
        raise ApiAuthenticationError("Bearer token is invalid")
    return values


def _roles(value: object) -> tuple[ApiRole, ...]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= len(_ALLOWED_ROLES)
        or any(not isinstance(item, str) or item not in _ALLOWED_ROLES for item in value)
        or len(value) != len(set(value))
    ):
        raise ApiAuthenticationError("Bearer token is invalid")
    return cast(tuple[ApiRole, ...], tuple(sorted(value)))


def _utc_now(value: datetime | None) -> datetime:
    checked = value or datetime.now(UTC)
    if checked.tzinfo is None or checked.utcoffset() is None:
        raise ValueError("Identity verification time must be timezone-aware")
    return checked.astimezone(UTC)
