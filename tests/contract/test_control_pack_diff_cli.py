import base64
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.diff_control_packs import main as diff_main
from scripts.sign_control_pack import main as sign_main


def test_cli_verifies_both_packs_and_reports_decision_impact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[2]
    resources = root / "src" / "regulated_ai" / "resources"
    base = tmp_path / "base"
    candidate = tmp_path / "candidate"
    shutil.copytree(resources, base)
    shutil.copytree(resources, candidate)

    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()
    private_key_path = tmp_path / "candidate-private.pem"
    private_key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    trust_store_path = tmp_path / "trust-store.yaml"
    trust_store = yaml.safe_load(
        (base / "trust" / "control-pack-signing-keys.yaml").read_text(encoding="utf-8")
    )
    trust_store["keys"]["candidate-test-key"] = {
        "algorithm": "ed25519",
        "public_key": public_key,
    }
    trust_store_path.write_text(yaml.safe_dump(trust_store, sort_keys=False), encoding="utf-8")

    capability_path = candidate / "provider-capabilities" / "openai-responses.yaml"
    capability = yaml.safe_load(capability_path.read_text(encoding="utf-8"))
    capability["capabilities"]["zero_data_retention"]["state"] = "unsupported"
    capability_path.write_text(yaml.safe_dump(capability, sort_keys=False), encoding="utf-8")
    candidate_manifest = candidate / "control-pack-manifest.yaml"
    manifest = yaml.safe_load(candidate_manifest.read_text(encoding="utf-8"))
    manifest["pack_version"] = "2026-09-25.2"
    manifest["signing"]["key_id"] = "candidate-test-key"
    candidate_manifest.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sign_control_pack.py",
            "--manifest",
            str(candidate_manifest),
            "--trust-store",
            str(trust_store_path),
            "--private-key",
            str(private_key_path),
        ],
    )
    assert sign_main() == 0
    capsys.readouterr()

    exit_code = diff_main(
        [
            "--base-manifest",
            str(base / "control-pack-manifest.yaml"),
            "--candidate-manifest",
            str(candidate_manifest),
            "--trust-store",
            str(trust_store_path),
            "--fail-on-decision-impact",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert exit_code == 2
    assert captured.err == ""
    assert report["status"] == "CHANGES_DETECTED"
    assert report["highest_impact"] == "DECISION"
    assert report["version_reused"] is False
    assert report["signing_key_changed"] is True
    assert report["summary"]["by_impact"]["DECISION"] >= 1
    capability_changes = [
        change for change in report["changes"] if change["kind"] == "PROVIDER_CAPABILITY"
    ]
    assert any(
        change["identifier"] == "openai.responses_api.global:zero_data_retention"
        and "state" in change["changed_fields"]
        for change in capability_changes
    )
    assert "PRIVATE KEY" not in captured.out
