"""Strict offline boundary for provider capability drafts and review records."""

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.adapters.yaml_files import load_capability_bytes
from regulated_ai.domain import (
    ProviderCapabilityDraft,
    ProviderCapabilityUpdateReview,
    ProviderReviewConclusion,
    ProviderSourceReview,
    ProviderTarget,
)


class ProviderReviewBoundaryError(ValueError):
    """A provider draft or review record failed strict boundary validation."""

    code = "PROVIDER_REVIEW_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _TargetModel(_StrictModel):
    provider: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    service: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    region: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class _SourceReviewModel(_StrictModel):
    source_url: str = Field(min_length=1, max_length=2048)
    capability_keys: tuple[str, ...] = Field(min_length=1, max_length=256)
    conclusion: ProviderReviewConclusion

    @field_validator("source_url")
    @classmethod
    def authoritative_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("review source URL must use HTTPS")
        return value

    @field_validator("capability_keys")
    @classmethod
    def normalized_capability_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            _IDENTIFIER.fullmatch(item) is None for item in value
        ):
            raise ValueError("review capability keys must be unique identifiers")
        return value


class _ReviewModel(_StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    reviewer_role: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
    )
    reviewed_at: str = Field(min_length=10, max_length=10)
    base_pack_payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_record_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target: _TargetModel
    source_reviews: tuple[_SourceReviewModel, ...] = Field(min_length=1, max_length=256)

    @field_validator("reviewed_at")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def unique_source_capability_coverage(self) -> "_ReviewModel":
        coverage = tuple(
            (item.source_url, capability_key)
            for item in self.source_reviews
            for capability_key in item.capability_keys
        )
        if len(coverage) != len(set(coverage)):
            raise ValueError("review source and capability coverage must be unique")
        return self


class _ReviewFileModel(_StrictModel):
    schema_version: Literal["1"]
    review: _ReviewModel


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")


def load_provider_capability_draft(path: Path) -> ProviderCapabilityDraft:
    """Parse one candidate record from exact bounded bytes and bind its digest."""
    content = _read_bounded(path, label="Provider capability draft")
    return ProviderCapabilityDraft(
        record=load_capability_bytes(content, path.name),
        content_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
    )


def load_provider_capability_review(path: Path) -> ProviderCapabilityUpdateReview:
    """Parse strict review metadata and bind the exact review document bytes."""
    content = _read_bounded(path, label="Provider capability review")
    try:
        text = content.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw: Any = yaml.safe_load(text)
        document = _ReviewFileModel.model_validate(raw)
    except (UnicodeDecodeError, ValidationError, ValueError, yaml.YAMLError) as exc:
        raise ProviderReviewBoundaryError(
            "Provider capability review failed schema validation"
        ) from exc

    review = document.review
    return ProviderCapabilityUpdateReview(
        review_id=review.id,
        reviewer_role=review.reviewer_role,
        reviewed_at=date.fromisoformat(review.reviewed_at),
        base_pack_payload_digest=review.base_pack_payload_digest,
        candidate_record_digest=review.candidate_record_digest,
        target=ProviderTarget(
            provider=review.target.provider,
            service=review.target.service,
            region=review.target.region,
        ),
        source_reviews=tuple(
            ProviderSourceReview(
                source_url=item.source_url,
                capability_keys=tuple(sorted(item.capability_keys)),
                conclusion=item.conclusion,
            )
            for item in sorted(
                review.source_reviews,
                key=lambda item: (
                    item.source_url,
                    item.conclusion.value,
                    item.capability_keys,
                ),
            )
        ),
        review_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
    )


def _read_bounded(path: Path, *, label: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ProviderReviewBoundaryError(f"{label} is unavailable") from exc
    if len(content) > 1_048_576:
        raise ProviderReviewBoundaryError(f"{label} exceeds the size limit")
    return content


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("provider review keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("provider review contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)
