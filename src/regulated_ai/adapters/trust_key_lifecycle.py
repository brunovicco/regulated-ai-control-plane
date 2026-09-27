"""Shared strict lifecycle metadata for public verification keys."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class TrustKeyLifecycleModel(BaseModel):
    """Deployment-owned validity and revocation state for one public key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ACTIVE", "RETIRED", "REVOKED"]
    valid_from: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def valid_lifecycle(self) -> "TrustKeyLifecycleModel":
        """Require UTC bounds with an increasing optional validity interval."""
        if self.valid_from.tzinfo is None or self.valid_from.utcoffset() != UTC.utcoffset(
            self.valid_from
        ):
            raise ValueError("trust key valid_from must be timezone-aware UTC")
        if self.valid_until is not None and (
            self.valid_until.tzinfo is None
            or self.valid_until.utcoffset() != UTC.utcoffset(self.valid_until)
            or self.valid_until <= self.valid_from
        ):
            raise ValueError("trust key valid_until must follow valid_from in UTC")
        return self

    def active_at(self, evaluated_at: datetime) -> bool:
        """Return whether this key is active for one explicit UTC instant."""
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise ValueError("trust key evaluation time must be timezone-aware UTC")
        return (
            self.status == "ACTIVE"
            and evaluated_at >= self.valid_from
            and (self.valid_until is None or evaluated_at < self.valid_until)
        )
