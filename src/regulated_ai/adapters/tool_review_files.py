"""Strict offline boundary for tool-catalog drafts and detailed review records."""

import hashlib
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.adapters.yaml_files import load_tool_catalog_bytes
from regulated_ai.domain import (
    ControlPackChangeType,
    ToolCatalogDraft,
    ToolCatalogUpdateReview,
    ToolDefinitionReview,
    ToolDefinitionReviewConclusion,
)


class ToolReviewBoundaryError(ValueError):
    """A tool-catalog draft or review record failed strict boundary validation."""

    code = "TOOL_REVIEW_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ToolReviewModel(_StrictModel):
    tool_name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    change_type: ControlPackChangeType
    owner_role: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    implementation_refs: tuple[str, ...] = Field(min_length=1, max_length=32)
    conclusion: ToolDefinitionReviewConclusion

    @field_validator("implementation_refs")
    @classmethod
    def normalized_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            len(item) > 2048 or not item.startswith("https://") for item in value
        ):
            raise ValueError("implementation references must be unique HTTPS URLs")
        return value


class _ReviewModel(_StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    reviewer_role: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
    )
    reviewed_at: str = Field(min_length=10, max_length=10)
    base_pack_payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_catalog_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    tool_reviews: tuple[_ToolReviewModel, ...] = Field(default=(), max_length=256)

    @field_validator("reviewed_at")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def unique_tool_reviews(self) -> "_ReviewModel":
        names = tuple(item.tool_name for item in self.tool_reviews)
        if len(names) != len(set(names)):
            raise ValueError("tool review names must be unique")
        return self


class _ReviewFileModel(_StrictModel):
    schema_version: Literal["1"]
    review: _ReviewModel


def load_tool_catalog_draft(path: Path) -> ToolCatalogDraft:
    """Parse one candidate catalog from exact bounded bytes and bind its digest."""
    content = _read_bounded(path, label="Tool-catalog draft")
    try:
        catalog_version, tools = load_tool_catalog_bytes(content, path.name)
    except ValueError as exc:
        raise ToolReviewBoundaryError("Tool-catalog draft failed schema validation") from exc
    return ToolCatalogDraft(
        catalog_version=catalog_version,
        tools=tools,
        content_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
    )


def load_tool_catalog_review(path: Path) -> ToolCatalogUpdateReview:
    """Parse strict detailed review metadata and bind the exact document bytes."""
    content = _read_bounded(path, label="Tool-catalog review")
    try:
        text = content.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw: Any = yaml.safe_load(text)
        document = _ReviewFileModel.model_validate(raw)
    except (UnicodeDecodeError, ValidationError, ValueError, yaml.YAMLError) as exc:
        raise ToolReviewBoundaryError("Tool-catalog review failed schema validation") from exc

    review = document.review
    return ToolCatalogUpdateReview(
        review_id=review.id,
        reviewer_role=review.reviewer_role,
        reviewed_at=date.fromisoformat(review.reviewed_at),
        base_pack_payload_digest=review.base_pack_payload_digest,
        candidate_catalog_digest=review.candidate_catalog_digest,
        tool_reviews=tuple(
            ToolDefinitionReview(
                tool_name=item.tool_name,
                change_type=item.change_type,
                owner_role=item.owner_role,
                implementation_refs=tuple(sorted(item.implementation_refs)),
                conclusion=item.conclusion,
            )
            for item in sorted(review.tool_reviews, key=lambda item: item.tool_name)
        ),
        review_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
    )


def _read_bounded(path: Path, *, label: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ToolReviewBoundaryError(f"{label} is unavailable") from exc
    if len(content) > 1_048_576:
        raise ToolReviewBoundaryError(f"{label} exceeds the size limit")
    return content


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("tool review keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("tool review contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)
