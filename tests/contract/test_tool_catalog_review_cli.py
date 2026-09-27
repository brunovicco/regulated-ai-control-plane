import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.review_tool_catalog_update import main as review_main

from regulated_ai.adapters.signed_packs import verify_control_pack


def test_cli_passes_complete_review_and_blocks_revision_request(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = root / "src" / "regulated_ai" / "resources" / "control-pack-manifest.yaml"
    trust_store = (
        root / "src" / "regulated_ai" / "resources" / "trust" / "control-pack-signing-keys.yaml"
    )
    source = root / "src" / "regulated_ai" / "resources" / "tools" / "br-financial-tools.yaml"
    candidate_document = yaml.safe_load(source.read_text(encoding="utf-8"))
    candidate_document["catalog_version"] = "br-financial-tools@1.2.0"
    candidate_document["tools"]["cards.read"]["description"] = (
        "Read synthetic card status through the reviewed implementation."
    )
    candidate = tmp_path / "candidate-tools.yaml"
    candidate.write_text(yaml.safe_dump(candidate_document, sort_keys=False), encoding="utf-8")
    candidate_digest = f"sha256:{hashlib.sha256(candidate.read_bytes()).hexdigest()}"
    base_digest = verify_control_pack(manifest, trust_store).identity.payload_digest

    review_document: dict[str, Any] = {
        "schema_version": "1",
        "review": {
            "id": "tool-review-2026-09-27",
            "reviewer_role": "tool-governance-reviewer",
            "reviewed_at": "2026-09-27",
            "base_pack_payload_digest": base_digest,
            "candidate_catalog_digest": candidate_digest,
            "tool_reviews": [
                {
                    "tool_name": "cards.read",
                    "change_type": "MODIFIED",
                    "owner_role": "payments-platform-owner",
                    "implementation_refs": ["https://engineering.invalid/tools/cards-read"],
                    "conclusion": "APPROVED",
                }
            ],
        },
    }
    review = tmp_path / "review.yaml"
    review.write_text(yaml.safe_dump(review_document, sort_keys=False), encoding="utf-8")
    arguments = [
        "--base-manifest",
        str(manifest),
        "--trust-store",
        str(trust_store),
        "--candidate-catalog",
        str(candidate),
        "--review-record",
        str(review),
    ]

    assert review_main(arguments) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["status"] == "TOOL_REVIEW_PASSED"
    assert approved["required_tool_names"] == ["cards.read"]

    review_document["review"]["tool_reviews"][0]["conclusion"] = "NEEDS_REVISION"
    review.write_text(yaml.safe_dump(review_document, sort_keys=False), encoding="utf-8")
    assert review_main(arguments) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["findings"] == [{"code": "TOOL_NEEDS_REVISION", "tool_name": "cards.read"}]
