import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from regulated_ai.adapters.signed_packs import SignedPackError, verify_control_pack
from regulated_ai.adapters.yaml_files import FilePolicyRepository


def _write_signed_pack(root: Path) -> tuple[Path, Path]:
    policy_path = root / "policies" / "policy.yaml"
    capability_path = root / "provider-capabilities" / "provider.yaml"
    policy_path.parent.mkdir()
    capability_path.parent.mkdir()
    policy_path.write_text('schema_version: "1"\nkind: "synthetic-policy"\n', encoding="utf-8")
    capability_path.write_text(
        'schema_version: "1"\nkind: "synthetic-capability"\n', encoding="utf-8"
    )
    files = [
        {
            "kind": "policy",
            "path": "policies/policy.yaml",
            "sha256": f"sha256:{hashlib.sha256(policy_path.read_bytes()).hexdigest()}",
        },
        {
            "kind": "provider_capability",
            "path": "provider-capabilities/provider.yaml",
            "sha256": f"sha256:{hashlib.sha256(capability_path.read_bytes()).hexdigest()}",
        },
    ]
    signing = {"algorithm": "ed25519", "key_id": "synthetic-key"}
    unsigned: dict[str, object] = {
        "schema_version": "1",
        "pack_id": "synthetic-pack",
        "pack_version": "1.0.0",
        "files": files,
        "signing": signing,
    }
    payload = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    private_key = Ed25519PrivateKey.generate()
    signature = base64.b64encode(private_key.sign(payload)).decode()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode()
    manifest_path = root / "manifest.yaml"
    trust_store_path = root / "trust.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                **unsigned,
                "signing": {**signing, "signature": signature},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    trust_store_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "keys": {
                    "synthetic-key": {
                        "algorithm": "ed25519",
                        "public_key": public_key,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return manifest_path, trust_store_path


def test_signed_pack_returns_only_verified_paths_and_release_identity(tmp_path: Path) -> None:
    manifest_path, trust_store_path = _write_signed_pack(tmp_path)

    pack = verify_control_pack(manifest_path, trust_store_path)

    assert pack.identity.pack_id == "synthetic-pack"
    assert pack.identity.pack_version == "1.0.0"
    assert pack.identity.signing_key_id == "synthetic-key"
    assert pack.identity.payload_digest.startswith("sha256:")
    assert tuple(item.path for item in pack.policy_files) == ("policies/policy.yaml",)
    assert tuple(item.path for item in pack.capability_files) == (
        "provider-capabilities/provider.yaml",
    )
    assert b"synthetic-policy" in pack.policy_files[0].content


def test_signed_pack_rejects_file_tampering(tmp_path: Path) -> None:
    manifest_path, trust_store_path = _write_signed_pack(tmp_path)
    (tmp_path / "policies" / "policy.yaml").write_text(
        'schema_version: "1"\nkind: "tampered"\n', encoding="utf-8"
    )

    with pytest.raises(SignedPackError, match="digest does not match"):
        verify_control_pack(manifest_path, trust_store_path)


def test_signed_pack_rejects_signature_tampering(tmp_path: Path) -> None:
    manifest_path, trust_store_path = _write_signed_pack(tmp_path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["pack_version"] = "2.0.0"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(SignedPackError, match="signature is invalid"):
        verify_control_pack(manifest_path, trust_store_path)


def test_signature_is_rejected_before_untrusted_manifest_drives_file_reads(
    tmp_path: Path,
) -> None:
    manifest_path, trust_store_path = _write_signed_pack(tmp_path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "policies/missing.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(SignedPackError, match="signature is invalid"):
        verify_control_pack(manifest_path, trust_store_path)


def test_signed_pack_rejects_unknown_key(tmp_path: Path) -> None:
    manifest_path, trust_store_path = _write_signed_pack(tmp_path)
    trust_store = yaml.safe_load(trust_store_path.read_text(encoding="utf-8"))
    trust_store["keys"]["renamed-key"] = trust_store["keys"].pop("synthetic-key")
    trust_store_path.write_text(yaml.safe_dump(trust_store, sort_keys=False), encoding="utf-8")

    with pytest.raises(SignedPackError, match="not trusted"):
        verify_control_pack(manifest_path, trust_store_path)


def test_signed_pack_rejects_path_traversal_before_file_access(tmp_path: Path) -> None:
    manifest_path, trust_store_path = _write_signed_pack(tmp_path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(SignedPackError, match="schema validation"):
        verify_control_pack(manifest_path, trust_store_path)


def test_signed_pack_rejects_symlink_even_when_content_digest_matches(tmp_path: Path) -> None:
    manifest_path, trust_store_path = _write_signed_pack(tmp_path)
    capability_path = tmp_path / "provider-capabilities" / "provider.yaml"
    outside_path = tmp_path / "outside.yaml"
    outside_path.write_bytes(capability_path.read_bytes())
    capability_path.unlink()
    capability_path.symlink_to(outside_path)

    with pytest.raises(SignedPackError, match="path is not allowed"):
        verify_control_pack(manifest_path, trust_store_path)


def test_verified_bytes_are_parsed_without_reopening_changed_file(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "src" / "regulated_ai" / "resources"
    copied = tmp_path / "resources"
    shutil.copytree(source, copied)
    pack = verify_control_pack(
        copied / "control-pack-manifest.yaml",
        copied / "trust" / "control-pack-signing-keys.yaml",
    )
    policy_path = copied / pack.policy_files[0].path
    policy_path.write_text("tampered after verification", encoding="utf-8")

    repository = FilePolicyRepository.from_bytes(
        tuple((item.path, item.content) for item in pack.policy_files)
    )

    assert repository.get("br-financial-demo@1.0.0") is not None
