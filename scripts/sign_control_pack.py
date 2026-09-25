#!/usr/bin/env python3
"""Refresh file digests and sign a control-pack manifest with an external key."""

import argparse
import base64
import hashlib
import tempfile
from pathlib import Path, PurePosixPath

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from regulated_ai.adapters.signed_packs import (
    SignedPackError,
    _canonical_payload,
    _parse_manifest,
    verify_control_pack,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh and sign a strict policy/provider control-pack manifest."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()

    manifest_path: Path = args.manifest.resolve()
    trust_store_path: Path = args.trust_store.resolve()
    private_key_path: Path = args.private_key.resolve()
    manifest = _parse_manifest(manifest_path)
    root = manifest_path.parent
    refreshed_files = []
    total_size = 0
    for item in manifest.files:
        candidate = root.joinpath(*PurePosixPath(item.path).parts)
        path = candidate.resolve(strict=True)
        if not path.is_relative_to(root) or path != candidate.absolute() or not path.is_file():
            raise SignedPackError("Control pack file path is not allowed")
        content = path.read_bytes()
        if len(content) > 1_048_576:
            raise SignedPackError("Control pack file exceeds the size limit")
        total_size += len(content)
        if total_size > 8_388_608:
            raise SignedPackError("Control pack exceeds the total size limit")
        refreshed_files.append(
            item.model_copy(update={"sha256": f"sha256:{hashlib.sha256(content).hexdigest()}"})
        )

    try:
        private_key = load_pem_private_key(private_key_path.read_bytes(), password=None)
    except (OSError, TypeError, ValueError) as exc:
        raise SignedPackError("Ed25519 private key could not be loaded") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SignedPackError("Signing key must be an Ed25519 private key")

    refreshed = manifest.model_copy(update={"files": tuple(refreshed_files)})
    signature = base64.b64encode(private_key.sign(_canonical_payload(refreshed))).decode()
    refreshed = refreshed.model_copy(
        update={"signing": refreshed.signing.model_copy(update={"signature": signature})}
    )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=root,
            prefix=".control-pack-",
            suffix=".yaml",
            delete=False,
        ) as temporary:
            yaml.safe_dump(refreshed.model_dump(mode="json"), temporary, sort_keys=False)
            temporary_path = Path(temporary.name)
        verify_control_pack(temporary_path, trust_store_path)
        temporary_path.replace(manifest_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    print(f"Signed control pack: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
