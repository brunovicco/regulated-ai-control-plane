import base64
import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.verify_financial_pilot_acceptance import main

from regulated_ai.adapters.financial_pilot_evidence import verify_pilot_reviews
from regulated_ai.application.accept_financial_pilot import pilot_bundle_digest

from ..helpers import NOW
from ..unit.test_financial_pilot_acceptance import observations, scope


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _bundle(directory: Path) -> tuple[list[str], Path, list[Path]]:
    selected = scope()
    evidence = observations()
    args = [
        "--scope",
        str(_write(directory / "scope.json", {"schema_version": "1", **asdict(selected)})),
        "--evaluated-at",
        NOW.isoformat(),
    ]
    for observation in evidence:
        payload = {
            "schema_version": "1",
            **asdict(observation),
            "observed_at": observation.observed_at.isoformat(),
        }
        args.extend(["--evidence", str(_write(directory / f"{observation.check}.json", payload))])
    keys = {}
    review_paths = []
    for role in ("OPERATIONS", "POLICY_OWNER"):
        private = Ed25519PrivateKey.generate()
        key_id = f"key-{role}"
        keys[key_id] = {
            "algorithm": "ed25519",
            "role": role,
            "status": "ACTIVE",
            "public_key": base64.b64encode(private.public_key().public_bytes_raw()).decode(),
            "valid_from": (NOW - timedelta(days=1)).isoformat(),
            "valid_until": (NOW + timedelta(days=2)).isoformat(),
        }
        payload = {
            "schema_version": "1",
            "domain": "regulaai.financial-pilot.review.v1",
            "bundle_digest": pilot_bundle_digest(selected, evidence),
            "role": role,
            "key_id": key_id,
            "approved": True,
            "issued_at": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        review = _write(
            directory / f"review-{role}.json",
            {
                **payload,
                "signature": base64.b64encode(private.sign(canonical)).decode(),
            },
        )
        review_paths.append(review)
        args.extend(["--review", str(review)])
    trust = _write(directory / "trust.json", {"schema_version": "1", "keys": keys})
    args.extend(["--trust-store", str(trust)])
    return args, trust, review_paths


def test_cli_accepts_only_verified_exact_organization_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, _, _ = _bundle(tmp_path)
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PILOT_ACCEPTED"
    observation = tmp_path / "OPENAI_GATEWAY.json"
    modified = json.loads(observation.read_text())
    modified["artifact_digest"] = f"sha256:{'b' * 64}"
    _write(observation, modified)
    assert main(args) == 2
    assert "REVIEW_INVALID" in json.loads(capsys.readouterr().out)["findings"]


@pytest.mark.parametrize("change", ["signature", "role", "domain", "revoked", "duplicate-key"])
def test_pilot_review_rejects_forgery_scope_confusion_and_revocation(
    tmp_path: Path,
    change: str,
) -> None:
    _, trust, paths = _bundle(tmp_path)
    if change in {"revoked", "duplicate-key"}:
        document = json.loads(trust.read_text())
        keys = document["keys"]
        if change == "revoked":
            keys["key-OPERATIONS"]["status"] = "REVOKED"
        else:
            keys["key-POLICY_OWNER"]["public_key"] = keys["key-OPERATIONS"]["public_key"]
        _write(trust, document)
    else:
        document = json.loads(paths[0].read_text())
        document[change] = {
            "signature": "A" * 88,
            "role": "POLICY_OWNER",
            "domain": "regulaai.release-promotion",
        }[change]
        _write(paths[0], document)
    with pytest.raises(ValueError):
        verify_pilot_reviews(tuple(paths), trust, evaluated_at=NOW)


def test_draft_example_is_blocked_and_invalid_input_is_not_echoed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).parents[2]
    assert main(["--scope", str(root / "examples/financial-pilot/scope.json")]) == 2
    assert "SCOPE_NOT_READY" in json.loads(capsys.readouterr().out)["findings"]
    unsafe = tmp_path / "invalid.json"
    unsafe.write_text('{"prompt":"sensitive-sentinel","prompt":"duplicated"}')
    assert main(["--scope", str(unsafe)]) == 1
    assert "sensitive-sentinel" not in str(capsys.readouterr())
