from __future__ import annotations

import hashlib
import hmac


def compute_signature(payload: bytes | str, secret: str, scheme: str = "sha256", prefix: bool = True) -> str:
    """Compute HMAC signature for a payload given a secret."""
    if isinstance(payload, str):
        payload_bytes = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        payload_bytes = payload
    else:
        raise ValueError("Payload must be bytes or str")

    if not isinstance(secret, str):
        raise ValueError("Secret must be a string")

    secret_bytes = secret.encode("utf-8")
    if scheme.lower() == "sha256":
        digest = hmac.new(secret_bytes, payload_bytes, hashlib.sha256).hexdigest()
        return f"sha256={digest}" if prefix else digest
    raise ValueError(f"Unsupported signing scheme: {scheme}")


def verify_signature(payload: bytes | str, secret: str, signature: str | None, scheme: str = "sha256") -> bool:
    """Constant-time HMAC verification; returns False on missing/malformed/wrong signature."""
    if signature is None or not isinstance(signature, str) or not signature.strip():
        return False
    if secret is None or not isinstance(secret, str) or not secret:
        return False
    if payload is None or not isinstance(payload, (bytes, str)):
        return False

    scheme_norm = scheme.strip().lower()
    if scheme_norm not in ("sha256", "x-hub-signature-256", "x-cortxt-signature"):
        return False

    if isinstance(payload, str):
        payload_bytes = payload.encode("utf-8")
    else:
        payload_bytes = payload

    try:
        secret_bytes = secret.encode("utf-8")
        expected_hex = hmac.new(secret_bytes, payload_bytes, hashlib.sha256).hexdigest()

        actual_hex = signature.strip()
        if actual_hex.lower().startswith("sha256="):
            actual_hex = actual_hex[7:]

        if len(actual_hex) != len(expected_hex):
            return False

        # Validate that actual_hex contains only valid hex chars
        int(actual_hex, 16)

        return hmac.compare_digest(actual_hex.lower(), expected_hex.lower())
    except Exception:
        return False
