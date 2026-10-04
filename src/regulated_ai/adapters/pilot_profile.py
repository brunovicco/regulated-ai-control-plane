"""Bounded, non-secret configuration for a fixed financial pilot scenario."""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from regulated_ai.domain import ProviderTarget


class FinancialPilotProfile(BaseModel):
    """Non-secret condition assertions and one explicit gateway/provider binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    profile_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    provider: Literal["openai", "bedrock"]
    gateway_provider: Literal["openai", "aws", "bedrock"]
    gateway_model: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    )
    gateway_deployment: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    )
    policy_set_version: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9._-]+$"
    )
    organization_assertions: dict[str, bool] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def validate_binding(self) -> "FinancialPilotProfile":
        """Reject cross-provider bindings and unbounded assertion identifiers."""
        if (self.provider == "openai") != (self.gateway_provider == "openai"):
            raise ValueError("Pilot provider binding is inconsistent")
        if any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name) is None
            for name in self.organization_assertions
        ):
            raise ValueError("Pilot assertion identifier is invalid")
        return self

    @property
    def target(self) -> ProviderTarget:
        """Return the bounded provider-service-region target for this pilot."""
        if self.provider == "openai":
            return ProviderTarget("openai", "responses_api", "global")
        return ProviderTarget("aws", "bedrock_runtime", "sa-east-1")

    @property
    def digest(self) -> str:
        """Bind the normalized non-secret profile, including asserted conditions."""
        encoded = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def load_pilot_profile(path: Path) -> FinancialPilotProfile:
    """Parse one closed metadata document without echoing rejected input."""
    try:
        with path.open("rb") as stream:
            encoded = stream.read(16_385)
        if len(encoded) > 16_384:
            raise ValueError("Pilot profile is too large")
        decoded = json.loads(encoded, object_pairs_hook=_unique_object)
        return FinancialPilotProfile.model_validate(decoded, strict=True)
    except (OSError, ValueError, RecursionError):
        raise ValueError("Financial pilot profile is invalid") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate pilot profile field")
        result[key] = value
    return result
