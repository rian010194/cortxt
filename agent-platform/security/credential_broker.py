"""Credential broker core -- Fas 4, implementing the design cleared by
`docs/security/credential-broker-threat-model.md` (Fas 1).

This is a control-plane-owned store of third-party bearer credentials. It
is deliberately narrow: no enumeration API, no unconfirmed writes, no
partial reads on integrity doubt. Every method here maps directly to one
of the threat model's four sections:

- Encryption at rest, per record (§3.1): `encrypt`/`decrypt` are injected
  callables so real callers wire in OS-level key storage (DPAPI on
  Windows, see `security/dpapi.py`) while tests use a fake transform --
  same dependency-injection shape as `routing/discovery.py`'s `which`.
  Each credential is its own encrypted record, not one shared blob.
- Write path is operator-gated (§3.2.1): `store()` requires
  `operator_confirmed=True`, always. There is no path that persists a
  credential without that flag explicitly set by the caller -- an
  agent/tool code path that never sets it can never write.
- Read path is runtime- and purpose-bound (§3.2.2): `inject()` requires
  `requesting_runtime` and `purpose`; there is no "give me the store"
  method. §32.3's no-self-grant invariant holds here architecturally: this
  class exposes no method that expands what it is willing to grant.
- No enumeration (§3.2.3): deliberately no `list`/`list_ids`/`get_all`
  method. `test_broker_exposes_no_list_all_method` in the test suite is a
  standing guard against one being added by accident.
- Audit trail (§3.2.5): every store/inject attempt -- granted or denied --
  is appended to an audit log carrying the credential_id, requester,
  purpose, and result, but never the plaintext.
- Fail closed on integrity doubt (§3.3.2): a decrypt failure (bad key,
  corrupted record) raises `IntegrityError` and is audited as an error; it
  never falls back to returning a partial or stale value.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_CREDENTIAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class NotOperatorConfirmedError(PermissionError):
    """Raised when store() is called without operator_confirmed=True."""


class CredentialNotFoundError(KeyError):
    """Raised when inject() is asked for a credential_id that was never stored."""


class IntegrityError(RuntimeError):
    """Raised when a stored record cannot be trusted -- decrypt failure or
    corrupted ciphertext. The broker fails closed: no plaintext, no retry
    with a weaker check, no partial value."""


class InvalidCredentialIdError(ValueError):
    """Raised when credential_id contains anything other than
    [A-Za-z0-9_-]. credential_id becomes a filename component
    (`_record_path`); without this check, an id like "../../x" escapes
    store_dir entirely -- this is a path-traversal guard, not cosmetic
    validation."""


@dataclass(frozen=True)
class AuditRecord:
    timestamp: str
    action: str  # "store" | "inject"
    credential_id: str
    requesting_runtime: str | None
    purpose: str | None
    result: str  # "ok" | "denied" | "error"


class CredentialBroker:
    def __init__(
        self,
        store_dir: Path,
        *,
        encrypt: Callable[[bytes], bytes],
        decrypt: Callable[[bytes], bytes],
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self._store_dir = Path(store_dir)
        self._encrypt = encrypt
        self._decrypt = decrypt
        self._now = now
        self._audit_path = self._store_dir / "audit.log"

    @classmethod
    def with_dpapi(cls, store_dir: Path) -> "CredentialBroker":
        """Real-world constructor: encrypt/decrypt bound to the current
        Windows login session via security/dpapi.py. Tests use the base
        constructor with a fake transform instead -- see test_credential_broker.py."""
        from security import dpapi

        return cls(store_dir, encrypt=dpapi.protect, decrypt=dpapi.unprotect)

    def store(self, credential_id: str, plaintext: str, *, operator_confirmed: bool) -> None:
        """Persist a credential. Never called implicitly -- the caller must
        set operator_confirmed=True, which only an operator-facing code
        path (the admin surface's confirm action, not an agent/tool
        request) is meant to do."""
        if not operator_confirmed:
            self._audit("store", credential_id, None, None, "denied")
            raise NotOperatorConfirmedError(
                f"refusing to store credential {credential_id!r} without operator_confirmed=True"
            )
        self._validate_credential_id("store", credential_id, None, None)
        ciphertext = self._encrypt(plaintext.encode("utf-8"))
        self._atomic_write(self._record_path(credential_id), ciphertext)
        self._audit("store", credential_id, None, None, "ok")

    def inject(self, credential_id: str, *, requesting_runtime: str, purpose: str) -> str:
        """Return one credential's plaintext for immediate use. Requires an
        explicit runtime identity and purpose -- there is no unscoped read."""
        self._validate_credential_id("inject", credential_id, requesting_runtime, purpose)
        path = self._record_path(credential_id)
        if not path.is_file():
            self._audit("inject", credential_id, requesting_runtime, purpose, "error")
            raise CredentialNotFoundError(credential_id)
        try:
            ciphertext = path.read_bytes()
            plaintext = self._decrypt(ciphertext).decode("utf-8")
        except Exception as error:
            self._audit("inject", credential_id, requesting_runtime, purpose, "error")
            raise IntegrityError(
                f"credential {credential_id!r} could not be decrypted; refusing to serve a partial or stale value"
            ) from error
        self._audit("inject", credential_id, requesting_runtime, purpose, "ok")
        return plaintext

    def audit_log(self) -> list[AuditRecord]:
        if not self._audit_path.is_file():
            return []
        records = []
        for line in self._audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            records.append(AuditRecord(**data))
        return records

    def _validate_credential_id(
        self,
        action: str,
        credential_id: str,
        requesting_runtime: str | None,
        purpose: str | None,
    ) -> None:
        if not _CREDENTIAL_ID_RE.fullmatch(credential_id):
            self._audit(action, credential_id, requesting_runtime, purpose, "error")
            raise InvalidCredentialIdError(
                f"credential_id {credential_id!r} must match [A-Za-z0-9_-]+"
            )

    def _record_path(self, credential_id: str) -> Path:
        return self._store_dir / "records" / f"{credential_id}.cred"

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, tmp = tempfile.mkstemp(prefix=".cred-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _audit(
        self,
        action: str,
        credential_id: str,
        requesting_runtime: str | None,
        purpose: str | None,
        result: str,
    ) -> None:
        record = AuditRecord(
            timestamp=self._now(),
            action=action,
            credential_id=credential_id,
            requesting_runtime=requesting_runtime,
            purpose=purpose,
            result=result,
        )
        self._store_dir.mkdir(parents=True, exist_ok=True)
        with open(self._audit_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")
