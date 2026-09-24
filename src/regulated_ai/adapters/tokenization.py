"""Local HMAC tokenization adapter for Phase 2 enforcement."""

import hashlib
import hmac


class HmacTokenizationAdapter:
    """Produce scoped, non-reversible tokens without retaining source values."""

    def __init__(self, key: bytes) -> None:
        """Bind process-local key material with a minimum 256-bit length."""
        if len(key) < 32:
            raise ValueError("Tokenization key must contain at least 32 bytes")
        self._key = key

    def tokenize(self, value: str, *, field: str, decision_digest: str) -> str:
        """Return a deterministic token scoped to the decision and logical field."""
        return f"tok_{self._derive('tokenize', value, field, decision_digest)[:32]}"

    def pseudonymize(self, value: str, *, field: str, decision_digest: str) -> str:
        """Return a deterministic pseudonym scoped to the decision and logical field."""
        return f"psn_{self._derive('pseudonymize', value, field, decision_digest)[:32]}"

    def _derive(self, purpose: str, value: str, field: str, decision_digest: str) -> str:
        payload = "\0".join((purpose, decision_digest, field, value)).encode()
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()
