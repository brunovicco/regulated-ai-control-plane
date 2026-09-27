"""Offline detailed review gate for trusted tool-catalog drafts."""

from regulated_ai.domain import (
    AuthorizedTool,
    ControlPackChangeType,
    ControlPackRelease,
    ToolCatalogDraft,
    ToolCatalogUpdateReview,
    ToolCatalogUpdateReviewReport,
    ToolDefinitionReviewConclusion,
    ToolDefinitionReviewFinding,
    ToolDefinitionReviewFindingCode,
)


class ToolCatalogUpdateReviewError(ValueError):
    """A tool review cannot be bound to the approved catalog lineage."""

    code = "TOOL_CATALOG_UPDATE_REVIEW_INVALID"


class ReviewToolCatalogUpdate:
    """Check owner/source coverage for every changed tool without network access."""

    def execute(
        self,
        base: ControlPackRelease,
        draft: ToolCatalogDraft,
        review: ToolCatalogUpdateReview,
    ) -> ToolCatalogUpdateReviewReport:
        """Return a deterministic pass/block report for one catalog update."""
        if review.base_pack_payload_digest != base.identity.payload_digest:
            raise ToolCatalogUpdateReviewError("Review does not bind the approved base pack")
        if review.candidate_catalog_digest != draft.content_digest:
            raise ToolCatalogUpdateReviewError("Review does not bind the candidate catalog")
        if base.tool_catalog_version is None:
            raise ToolCatalogUpdateReviewError("Approved base has no tool catalog")

        base_tools = _tool_index(base.tools, "approved base")
        candidate_tools = _tool_index(draft.tools, "candidate")
        changes = _tool_changes(base_tools, candidate_tools)
        required_names = tuple(sorted(changes))
        reviews = {item.tool_name: item for item in review.tool_reviews}
        if not set(reviews).issubset(changes):
            raise ToolCatalogUpdateReviewError(
                "Review contains a tool outside the changed catalog lineage"
            )
        for name, submitted_review in reviews.items():
            if submitted_review.change_type is not changes[name]:
                raise ToolCatalogUpdateReviewError(
                    "Review tool change type does not match the catalog lineage"
                )

        findings: list[ToolDefinitionReviewFinding] = []
        if draft.catalog_version == base.tool_catalog_version:
            findings.append(_finding(ToolDefinitionReviewFindingCode.CATALOG_VERSION_UNCHANGED))
        for name in required_names:
            tool_review = reviews.get(name)
            if tool_review is None:
                findings.append(_finding(ToolDefinitionReviewFindingCode.TOOL_REVIEW_MISSING, name))
                continue
            if changes[name] is ControlPackChangeType.MODIFIED:
                approved = base_tools[name]
                candidate = candidate_tools[name]
                schema_changed = (
                    approved.input_schema_digest != candidate.input_schema_digest
                    or approved.output_schema_digest != candidate.output_schema_digest
                )
                if schema_changed and approved.schema_version == candidate.schema_version:
                    findings.append(
                        _finding(
                            ToolDefinitionReviewFindingCode.TOOL_SCHEMA_VERSION_UNCHANGED,
                            name,
                        )
                    )
            if tool_review.conclusion is ToolDefinitionReviewConclusion.REJECTED:
                findings.append(_finding(ToolDefinitionReviewFindingCode.TOOL_REJECTED, name))
            elif tool_review.conclusion is ToolDefinitionReviewConclusion.NEEDS_REVISION:
                findings.append(_finding(ToolDefinitionReviewFindingCode.TOOL_NEEDS_REVISION, name))

        return ToolCatalogUpdateReviewReport(
            base=base.identity,
            candidate_catalog_version=draft.catalog_version,
            candidate_catalog_digest=draft.content_digest,
            review_id=review.review_id,
            reviewer_role=review.reviewer_role,
            reviewed_at=review.reviewed_at,
            review_digest=review.review_digest,
            required_tool_names=required_names,
            findings=tuple(
                sorted(findings, key=lambda item: (item.code.value, item.tool_name or ""))
            ),
        )


def _tool_index(items: tuple[AuthorizedTool, ...], label: str) -> dict[str, AuthorizedTool]:
    indexed: dict[str, AuthorizedTool] = {}
    for item in items:
        if item.name in indexed:
            raise ToolCatalogUpdateReviewError(f"Duplicate tool name in {label}")
        indexed[item.name] = item
    return indexed


def _tool_changes(
    base: dict[str, AuthorizedTool], candidate: dict[str, AuthorizedTool]
) -> dict[str, ControlPackChangeType]:
    changes = dict.fromkeys(base.keys() - candidate.keys(), ControlPackChangeType.REMOVED)
    changes.update(dict.fromkeys(candidate.keys() - base.keys(), ControlPackChangeType.ADDED))
    changes.update(
        {
            name: ControlPackChangeType.MODIFIED
            for name in base.keys() & candidate.keys()
            if _semantic_definition(base[name]) != _semantic_definition(candidate[name])
        }
    )
    return changes


def _semantic_definition(tool: AuthorizedTool) -> tuple[str, str, str, str, str]:
    return (
        tool.description,
        tool.risk_class,
        tool.schema_version,
        tool.input_schema_digest,
        tool.output_schema_digest,
    )


def _finding(
    code: ToolDefinitionReviewFindingCode, tool_name: str | None = None
) -> ToolDefinitionReviewFinding:
    return ToolDefinitionReviewFinding(code=code, tool_name=tool_name)
