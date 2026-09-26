import json
from pathlib import Path

import pytest
import yaml
from scripts.review_provider_capability_update import main as review_main


def _arguments(root: Path, review_path: Path) -> list[str]:
    return [
        "--base-manifest",
        str(root / "src" / "regulated_ai" / "resources" / "control-pack-manifest.yaml"),
        "--trust-store",
        str(
            root / "src" / "regulated_ai" / "resources" / "trust" / "control-pack-signing-keys.yaml"
        ),
        "--candidate-record",
        str(root / "examples" / "provider-capability-updates" / "openai-responses-candidate.yaml"),
        "--review-record",
        str(review_path),
    ]


def test_cli_passes_complete_review_and_blocks_inconclusive_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[2]
    approved_review = (
        root / "examples" / "provider-capability-reviews" / "openai-responses-2026-09-26.yaml"
    )

    assert review_main(_arguments(root, approved_review)) == 0
    approved_capture = capsys.readouterr()
    approved = json.loads(approved_capture.out)
    assert approved_capture.err == ""
    assert approved["status"] == "REVIEW_GATE_PASSED"
    assert approved["summary"] == {"findings": 0, "required_capabilities": 5}
    assert approved["findings"] == []

    blocked_document = yaml.safe_load(approved_review.read_text(encoding="utf-8"))
    blocked_document["review"]["source_reviews"][0]["conclusion"] = "INCONCLUSIVE"
    blocked_review = tmp_path / "blocked-review.yaml"
    blocked_review.write_text(
        yaml.safe_dump(blocked_document, sort_keys=False),
        encoding="utf-8",
    )

    assert review_main(_arguments(root, blocked_review)) == 2
    blocked_capture = capsys.readouterr()
    blocked = json.loads(blocked_capture.out)
    assert blocked_capture.err == ""
    assert blocked["status"] == "REVIEW_GATE_BLOCKED"
    assert blocked["summary"] == {"findings": 5, "required_capabilities": 5}
    assert {item["code"] for item in blocked["findings"]} == {"CAPABILITY_INCONCLUSIVE"}
    assert "source_url" not in blocked_capture.out
