"""Strict offline boundary for policy drafts and regulatory review records."""

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from regulated_ai.adapters.yaml_files import load_policy_bytes
from regulated_ai.domain import (
    ControlPackChangeType,
    PolicyDraft,
    PolicyRuleRegulatoryReview,
    PolicyUpdateRegulatoryReview,
    RegulatoryReviewConclusion,
)


class PolicyReviewBoundaryError(ValueError):
    """A policy draft or regulatory review failed strict boundary validation."""

    code = "POLICY_REVIEW_INVALID"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _PolicySetReviewModel(_StrictModel):
    changed_fields: tuple[Literal["version", "jurisdiction", "sector", "status"], ...] = Field(
        default=(), max_length=4
    )
    conclusion: RegulatoryReviewConclusion

    @field_validator("changed_fields")
    @classmethod
    def unique_changed_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("reviewed policy-set fields must be unique")
        return value


class _RuleReviewModel(_StrictModel):
    rule_id: str = Field(min_length=1, max_length=128)
    change_type: ControlPackChangeType
    control_objective_ids: tuple[str, ...] = Field(default=(), max_length=128)
    regulatory_support_refs: tuple[str, ...] = Field(default=(), max_length=128)
    conclusion: RegulatoryReviewConclusion

    @field_validator("rule_id")
    @classmethod
    def normalized_rule_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("review rule id must be a normalized identifier")
        return value

    @field_validator("control_objective_ids", "regulatory_support_refs")
    @classmethod
    def normalized_mapping_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            _IDENTIFIER.fullmatch(item) is None for item in value
        ):
            raise ValueError("review mapping ids must be unique normalized identifiers")
        return value


class _ReviewModel(_StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")
    reviewer_role: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]*$"
    )
    reviewed_at: str = Field(min_length=10, max_length=10)
    base_pack_payload_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_policy_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_set_id: str = Field(min_length=1, max_length=128)
    policy_set_review: _PolicySetReviewModel
    rule_reviews: tuple[_RuleReviewModel, ...] = Field(default=(), max_length=256)

    @field_validator("reviewed_at")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("policy_set_id")
    @classmethod
    def normalized_policy_set_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("review policy-set id must be a normalized identifier")
        return value

    @model_validator(mode="after")
    def unique_rule_reviews(self) -> "_ReviewModel":
        rule_ids = tuple(item.rule_id for item in self.rule_reviews)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("regulatory review rule ids must be unique")
        return self


class _ReviewFileModel(_StrictModel):
    schema_version: Literal["1"]
    review: _ReviewModel


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")


def load_policy_draft(path: Path) -> PolicyDraft:
    """Parse one candidate policy from exact bounded bytes and bind its digest."""
    content = _read_bounded(path, label="Policy draft")
    return PolicyDraft(
        policy_set=load_policy_bytes(content, path.name),
        content_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
    )


def load_policy_regulatory_review(path: Path) -> PolicyUpdateRegulatoryReview:
    """Parse strict review metadata and bind the exact review document bytes."""
    content = _read_bounded(path, label="Policy regulatory review")
    try:
        text = content.decode("utf-8")
        syntax_tree = yaml.compose(text, Loader=yaml.SafeLoader)
        if syntax_tree is not None:
            _reject_duplicate_mapping_keys(syntax_tree)
        raw: Any = yaml.safe_load(text)
        document = _ReviewFileModel.model_validate(raw)
    except (UnicodeDecodeError, ValidationError, ValueError, yaml.YAMLError) as exc:
        raise PolicyReviewBoundaryError(
            "Policy regulatory review failed schema validation"
        ) from exc

    review = document.review
    return PolicyUpdateRegulatoryReview(
        review_id=review.id,
        reviewer_role=review.reviewer_role,
        reviewed_at=date.fromisoformat(review.reviewed_at),
        base_pack_payload_digest=review.base_pack_payload_digest,
        candidate_policy_digest=review.candidate_policy_digest,
        policy_set_id=review.policy_set_id,
        reviewed_policy_set_fields=tuple(sorted(review.policy_set_review.changed_fields)),
        policy_set_conclusion=review.policy_set_review.conclusion,
        rule_reviews=tuple(
            PolicyRuleRegulatoryReview(
                rule_id=item.rule_id,
                change_type=item.change_type,
                control_objective_ids=tuple(sorted(item.control_objective_ids)),
                regulatory_support_refs=tuple(sorted(item.regulatory_support_refs)),
                conclusion=item.conclusion,
            )
            for item in sorted(review.rule_reviews, key=lambda item: item.rule_id)
        ),
        review_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
    )


def _read_bounded(path: Path, *, label: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PolicyReviewBoundaryError(f"{label} is unavailable") from exc
    if len(content) > 1_048_576:
        raise PolicyReviewBoundaryError(f"{label} exceeds the size limit")
    return content


def _reject_duplicate_mapping_keys(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                raise yaml.YAMLError("policy review keys must be scalar")
            identity = (key.tag, key.value)
            if identity in seen:
                raise yaml.YAMLError("policy review contains a duplicate key")
            seen.add(identity)
            _reject_duplicate_mapping_keys(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _reject_duplicate_mapping_keys(value)
