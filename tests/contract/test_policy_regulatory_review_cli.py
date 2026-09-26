import json
from pathlib import Path

import pytest
import yaml
from scripts.review_policy_update import main as review_main


def _arguments(root: Path, review_path: Path) -> list[str]:
    return [
        "--base-manifest",
        str(root / "src" / "regulated_ai" / "resources" / "control-pack-manifest.yaml"),
        "--trust-store",
        str(
            root / "src" / "regulated_ai" / "resources" / "trust" / "control-pack-signing-keys.yaml"
        ),
        "--candidate-policy",
        str(
            root / "examples" / "policy-updates" / "br-financial-external-inference-candidate.yaml"
        ),
        "--review-record",
        str(review_path),
    ]


def test_cli_passes_complete_review_and_blocks_revision_request(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[2]
    approved_review = (
        root / "examples" / "regulatory-reviews" / "br-financial-external-inference-2026-09-26.yaml"
    )

    assert review_main(_arguments(root, approved_review)) == 0
    approved_capture = capsys.readouterr()
    approved = json.loads(approved_capture.out)
    assert approved_capture.err == ""
    assert approved["status"] == "REGULATORY_REVIEW_PASSED"
    assert approved["summary"] == {
        "findings": 0,
        "required_policy_set_fields": 1,
        "required_rule_reviews": 1,
    }
    assert approved["findings"] == []

    blocked_document = yaml.safe_load(approved_review.read_text(encoding="utf-8"))
    blocked_document["review"]["rule_reviews"][0]["conclusion"] = "NEEDS_REVISION"
    blocked_review = tmp_path / "blocked-review.yaml"
    blocked_review.write_text(
        yaml.safe_dump(blocked_document, sort_keys=False),
        encoding="utf-8",
    )

    assert review_main(_arguments(root, blocked_review)) == 2
    blocked_capture = capsys.readouterr()
    blocked = json.loads(blocked_capture.out)
    assert blocked_capture.err == ""
    assert blocked["status"] == "REGULATORY_REVIEW_BLOCKED"
    assert blocked["summary"]["findings"] == 1
    assert blocked["findings"][0]["code"] == "RULE_NEEDS_REVISION"
    assert "regulatory_support_refs" not in blocked_capture.out
