"""A4b append-only Core store for content-bearing Cortxt records (#609).

Implements the frozen 4a storage spec (lab/product-packaging-discovery/
20260914/swarm-04a/contracts.md, section 7.1 A4b and 7.2 EVP-A) as the
durable, content-bearing foundation that the product-packaging domain
records (W-2a, #606) are designed against. Pattern source:
``state/ledger.py`` (canonical JSON, fail-closed validation, append-only
files, bounded inputs). Standard library only; offline; no network code.

Normative behaviour (frozen 4a section 7.1 / 7.2):

1. APPEND-ONLY. Ingestion-only: a record is written exactly once with a
   single atomic create and is never modified, renamed, or deleted by this
   module. Supersession is a SEPARATE appended record that names the
   ``record_digest`` it supersedes; the superseded record stays
   byte-identical. There is no update or delete API.

2. DIGEST-KEYED. Every content-bearing record carries ``record_digest`` =
   SHA-256 of its canonical JSON payload, in the frozen 4a section 2.1
   canonical form: ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
   ensure_ascii=True, default=str)``, UTF-8, no trailing newline. (This is
   the packaging-layer canonical form from #606, so domain records digest
   identically here; it is deliberately NOT ``state/ledger.py``'s
   ``ensure_ascii=False`` variant.) Dedupe = unique identity.

3. ATOMIC INSERT-IF-ABSENT / CAS on key existence (P1-3, section 7.2).
   The first write to an identity is a single atomic create-if-key-absent
   (``open(O_CREAT | O_EXCL)``) -- not an unlocked check-then-write.
   Exactly one of two concurrent first-writes to the same identity wins.
   The loser reads the winner's stored record and renders the deterministic
   outcome: ``re-delivery`` when the payload digest is the same,
   ``conflict`` when it differs. Never a double append, never a silent
   overwrite. The identity defaults to the record's own content digest
   (pure content addressing); a caller may declare a domain identity to
   get first-writer-wins semantics over an external key.

4. CONFLICT-NOT-MERGE. Identity conflicts are rendered explicitly with
   both payload digests listed -- the ``run_authority.py``
   conflict-not-merge pattern (both values, never resolved, never merged,
   never overwritten).

5. DURABLE LOCATION; BACKUP POLICY DECLARED OPEN (P2-9). The store root is
   injectable: the caller MUST supply a durable Core directory under the
   control-plane data home -- NOT ``.codex-work``, NOT ``Temp/``. The
   concrete backup location and routine (S4-B6, P2-9) remain an OPEN
   design gap that requires an operator/infra decision. The mechanism is
   parameterized: an optional ``backup`` hook may be supplied; without one
   the store reports ``backup_status == "declared-unfulfilled"`` and never
   silently invents a location or policy. Tests prove durability semantics
   against a temporary directory ONLY; any real deployment path is a
   separate operator decision, never silently filled by this module.

6. GITHUB ISSUES = REFERENCE ONLY (ADR-018 unchanged). A record MAY carry
   an issue reference as an opaque correlation string. The store never
   syncs, reconciles, or communicates with GitHub; there is no GitHub or
   network code in this module ("reference, not reconciliation").

Durability/crash note: the winning write is fsynced before the append is
reported. A writer killed between file creation and its completed write
leaves a partial record that fails integrity verification on every read
(fail closed). This module unlinks only a partial file it wrote itself
within the same call; a partial file left by a killed process must be
removed by an operator, after which the identity can be appended again.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA_VERSION = 1

OUTCOME_APPENDED = "appended"
OUTCOME_REDELIVERY = "re-delivery"
OUTCOME_CONFLICT = "conflict"

BACKUP_CONFIGURED = "configured"
BACKUP_UNFULFILLED = "declared-unfulfilled"

CONFLICT_FIELD = "payload_digest"

MAX_JSON_BYTES = 1_048_576
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000
MAX_TEXT_LENGTH = 16_384
MAX_KEY_LENGTH = 256
MAX_REF_LENGTH = 128

READ_ATTEMPTS = 50
READ_DELAY_SECONDS = 0.02
CAS_ATTEMPTS = 3

SHA256_PREFIX = "sha256:"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
ISSUE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.#-]{0,127}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
REPARSE_POINT = 0x400

_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_BINARY"):  # pragma: no branch - platform dependent
    _WRITE_FLAGS |= os.O_BINARY

BackupHook = Callable[[Path, Mapping[str, Any]], None]

_FIELDS = frozenset({
    "schema_version", "identity", "record_digest", "payload",
    "issue_ref", "supersedes", "appended_at", "record_hash",
})
_UNSIGNED_FIELDS = tuple(sorted(_FIELDS - {"record_hash"}))


class CoreError(Exception):
    """Fail-closed error with a coarse category and process exit code."""

    def __init__(self, category: str, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.category, self.message, self.exit_code = category, message, exit_code


# --- canonicalization and digests (frozen 4a section 2.1 form) -----------


def canonical_json(value: Any) -> str:
    """Canonical JSON text: sorted keys, compact, ASCII, no trailing newline."""
    try:
        return json.dumps(value, ensure_ascii=True, allow_nan=False,
                          sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError, RecursionError) as error:
        raise CoreError("invalid_input",
                        "value cannot be represented as canonical JSON", 3) from error


def sha256_hex(text: str) -> str:
    """SHA-256 of a UTF-8 string, as bare lowercase hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


# --- fail-closed input validation ----------------------------------------


def validate_identity(value: Any) -> str:
    """Validate a store identity (the CAS key / record filename stem).

    Lowercase alphanumerics plus ``._:-``; no slashes, no traversal, no
    uppercase (case-insensitive filesystems are not an identity source).
    """
    if (not isinstance(value, str) or not value
            or not IDENTITY_RE.fullmatch(value)):
        raise CoreError("invalid_input",
                        "identity must match ^[a-z0-9][a-z0-9._:-]{0,127}$", 3)
    return value


def validate_issue_ref(value: Any) -> str | None:
    """Validate an optional GitHub issue reference (opaque correlation only).

    Accepts bounded opaque identifiers such as ``owner/repo#123``. Rejects
    anything filesystem-looking (absolute paths, traversal, drive letters,
    backslashes) and anything over 128 characters. The store never interprets
    or resolves the value; it is carried verbatim.
    """
    if value is None:
        return None
    if (not isinstance(value, str) or not value or len(value) > MAX_REF_LENGTH
            or not ISSUE_REF_RE.fullmatch(value)):
        raise CoreError("invalid_input",
                        "issue_ref must be an opaque bounded reference string", 3)
    if ("\\" in value or value.startswith(("/", "./", "../")) or "/../" in value
            or (len(value) >= 3 and value[1:3] in (":/", ":\\"))):
        raise CoreError("invalid_input",
                        "issue_ref must not look like a filesystem path", 3)
    return value


def normalize_digest_input(value: Any, *, field: str = "digest") -> str:
    """Normalize a digest input to bare 64-char lowercase hex (P1-7 style).

    Permitted input: exactly 64 lowercase hex characters, optionally with a
    single ``sha256:`` prefix. Uppercase hex, a doubled prefix, or a wrong
    length is a fail-closed rejection. Re-derived for this module (the W-2a
    packaging module is not an import dependency of the Core store).
    """
    if not isinstance(value, str):
        raise CoreError("invalid_input", f"{field}: digest input must be a string", 3)
    stripped = value
    if stripped.startswith(SHA256_PREFIX):
        stripped = stripped[len(SHA256_PREFIX):]
        if stripped.startswith(SHA256_PREFIX):
            raise CoreError("invalid_input",
                            f"{field}: doubled sha256: prefix is not permitted", 3)
    if not HEX64_RE.fullmatch(stripped):
        raise CoreError("invalid_input",
                        f"{field}: must be 64 lowercase hex chars, optionally "
                        "with a single sha256: prefix", 3)
    return stripped


def _validate_utc(value: Any) -> bool:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo == timezone.utc


def _is_reparse(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & REPARSE_POINT)
    except OSError:
        return False


def _reject_link_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and (current.is_symlink() or _is_reparse(current)):
            raise CoreError("unsafe_path",
                            "links and reparse points are not allowed", 3)


def _validate_json_shape(value: Any, depth: int = 0,
                         counter: list[int] | None = None) -> None:
    """Bound stored JSON: depth, node count, string and key sizes, finiteness."""
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
        raise CoreError("invalid_input", "JSON exceeds complexity limits", 3)
    if value is None or type(value) in (bool, int, str):
        if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
            raise CoreError("invalid_input", "JSON string exceeds size limit", 3)
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise CoreError("invalid_input", "JSON numbers must be finite", 3)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_shape(item, depth + 1, counter)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for key, item in value.items():
            if len(key) > MAX_KEY_LENGTH:
                raise CoreError("invalid_input", "JSON key exceeds size limit", 3)
            _validate_json_shape(item, depth + 1, counter)
        return
    raise CoreError("invalid_input", "JSON contains an unsupported value", 3)


# --- record envelope integrity -------------------------------------------


def _hash_envelope(envelope: Mapping[str, Any]) -> str:
    unsigned = {key: envelope[key] for key in _UNSIGNED_FIELDS}
    return sha256_hex(canonical_json(unsigned))


def verify_envelope(envelope: Any) -> None:
    """Fail-closed re-verification of one stored record envelope.

    Checks the exact field set, types, canonical UTC timestamp, identity and
    reference rules, the payload content digest, and the self-certifying
    ``record_hash`` over every other field. Any mismatch is an
    ``integrity_error`` -- a tampered or partial record is never served.
    """
    if not isinstance(envelope, dict) or set(envelope) != _FIELDS:
        raise CoreError("integrity_error", "record has an invalid schema", 6)
    if (type(envelope["schema_version"]) is not int
            or envelope["schema_version"] != SCHEMA_VERSION):
        raise CoreError("integrity_error", "record schema version is invalid", 6)
    if not isinstance(envelope["identity"], str) or not IDENTITY_RE.fullmatch(envelope["identity"]):
        raise CoreError("integrity_error", "record identity is invalid", 6)
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise CoreError("integrity_error", "record payload is not an object", 6)
    try:
        _validate_json_shape(payload)
    except CoreError as error:
        raise CoreError("integrity_error", error.message, 6) from error
    digest = sha256_hex(canonical_json(payload))
    if envelope["record_digest"] != digest:
        raise CoreError("integrity_error", "record digest does not match payload", 6)
    try:
        validate_issue_ref(envelope["issue_ref"])
    except CoreError as error:
        raise CoreError("integrity_error", error.message, 6) from error
    supersedes = envelope["supersedes"]
    if supersedes is not None and not (isinstance(supersedes, str)
                                       and HEX64_RE.fullmatch(supersedes)):
        raise CoreError("integrity_error", "record supersedes digest is invalid", 6)
    if not _validate_utc(envelope["appended_at"]):
        raise CoreError("integrity_error", "record timestamp is not canonical UTC", 6)
    unsigned = {key: envelope[key] for key in _UNSIGNED_FIELDS}
    expected = sha256_hex(canonical_json(unsigned))
    if (not isinstance(envelope["record_hash"], str)
            or envelope["record_hash"] != expected):
        raise CoreError("integrity_error", "record hash is invalid", 6)


# --- atomic insert-if-absent storage --------------------------------------


def _read_verified(path: Path) -> dict[str, Any]:
    """Read and fully verify one record file, retrying a concurrent writer.

    A concurrent first-writer creates the file (atomic) and then writes and
    fsyncs its content; a reader in that window sees a partial file and
    retries briefly rather than guessing. Persistent integrity failure is
    raised as ``integrity_error`` (fail closed), never silently skipped.
    """
    last_error: CoreError | None = None
    for attempt in range(READ_ATTEMPTS):
        try:
            raw = path.read_bytes()
        except FileNotFoundError as error:
            raise CoreError("not_found", "record file not found", 4) from error
        except OSError:
            # Transient sharing/delete-pending violations while a concurrent
            # writer or an out-of-contract external deletion touches the
            # file: bounded retry, then fail closed below.
            last_error = CoreError("io_error", "could not read record", 7)
        else:
            try:
                if len(raw) > MAX_JSON_BYTES:
                    raise CoreError("integrity_error", "record exceeds size limit", 6)
                envelope = json.loads(raw.decode("utf-8"),
                                      parse_constant=lambda _token: (
                                          (_ for _ in ()).throw(ValueError())))
                _validate_json_shape(envelope)
                verify_envelope(envelope)
                return envelope
            except CoreError as error:
                last_error = error
            except (UnicodeError, ValueError, RecursionError) as error:
                last_error = CoreError("integrity_error",
                                       "record is not valid bounded JSON", 6)
                last_error.__cause__ = error
        if attempt + 1 < READ_ATTEMPTS:
            time.sleep(READ_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


def _render_loser(existing: Mapping[str, Any], record_digest: str,
                  identity: str) -> dict[str, Any]:
    """Deterministic loser rendering: re-delivery on equal digest, else conflict."""
    existing_digest = existing["record_digest"]
    outcome = (OUTCOME_REDELIVERY if existing_digest == record_digest
               else OUTCOME_CONFLICT)
    rendering: dict[str, Any] = {
        "outcome": outcome,
        "appended": False,
        "identity": identity,
        "record_digest": record_digest,
        "existing_record_digest": existing_digest,
    }
    if outcome == OUTCOME_REDELIVERY:
        rendering["existing_appended_at"] = existing["appended_at"]
    else:
        rendering["conflict"] = {"field": CONFLICT_FIELD,
                                 "values": [existing_digest, record_digest]}
    return rendering


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return  # Python stdlib exposes no portable directory fsync on Windows.
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise CoreError("io_error", "could not synchronize core store directory", 7) from error


class CoreStore:
    """Append-only, digest-keyed Core store with atomic insert-if-absent.

    ``root`` is the durable Core directory under the control-plane data home
    (injectable; never defaulted here -- see P2-9 in the module docstring).
    ``backup`` is an optional hook ``Callable[[Path, Mapping], None]``
    invoked after each successful first append with the record path and the
    frozen envelope. Without it, ``backup_status`` reports the P2-9 gap as
    declared-but-unfulfilled; the store never invents a backup policy.
    """

    def __init__(self, root: str | Path, *, backup: BackupHook | None = None) -> None:
        if backup is not None and not callable(backup):
            raise CoreError("invalid_input", "backup hook must be callable or None", 3)
        raw = Path(root)
        if ".." in raw.parts:
            raise CoreError("unsafe_path", "path traversal is not allowed", 3)
        try:
            raw.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise CoreError("io_error", "could not create core store root", 7) from error
        absolute = raw.absolute()
        _reject_link_components(absolute)
        try:
            resolved = absolute.resolve(strict=True)
        except OSError as error:
            raise CoreError("unsafe_path", "core store root could not be resolved", 3) from error
        if resolved != absolute.resolve(strict=False) or not resolved.is_dir():
            raise CoreError("unsafe_path", "core store root resolution changed", 3)
        self._root = resolved
        self._records = resolved / "records"
        try:
            self._records.mkdir(exist_ok=True)
        except OSError as error:
            raise CoreError("io_error", "could not create records directory", 7) from error
        _reject_link_components(self._records)
        self._backup: BackupHook | None = backup

    @property
    def root(self) -> Path:
        return self._root

    @property
    def records_dir(self) -> Path:
        return self._records

    @property
    def backup_status(self) -> str:
        """P2-9: the declared state of the backup policy hook."""
        return BACKUP_CONFIGURED if self._backup is not None else BACKUP_UNFULFILLED

    def append(self, payload: Mapping[str, Any], *, identity: str | None = None,
               issue_ref: str | None = None,
               supersedes: str | None = None) -> dict[str, Any]:
        """Append one content-bearing record; return the deterministic outcome.

        The record is frozen at first write. Same identity + same payload
        digest later renders ``re-delivery`` (nothing appended); a different
        payload under the same identity renders ``conflict`` (explicit,
        never merged or overwritten). ``identity`` defaults to the payload
        digest (pure content addressing). ``issue_ref`` is carried as an
        opaque GitHub reference only. ``supersedes`` names an existing
        record digest and is validated against the store (fail closed).
        """
        if not isinstance(payload, dict):
            raise CoreError("invalid_input", "payload must be a JSON object", 3)
        _validate_json_shape(payload)
        canonical_payload = canonical_json(payload)
        if len(canonical_payload.encode("utf-8")) > MAX_JSON_BYTES:
            raise CoreError("invalid_input", "payload exceeds size limit", 3)
        record_digest = sha256_hex(canonical_payload)
        checked_identity = validate_identity(
            identity if identity is not None else record_digest)
        checked_ref = validate_issue_ref(issue_ref)
        checked_supersedes = (
            None if supersedes is None
            else normalize_digest_input(supersedes, field="supersedes"))
        if checked_supersedes is not None and self._scan_by_digest(checked_supersedes) is None:
            raise CoreError("invalid_input",
                            "supersedes digest does not match any stored record", 3)
        # Store the re-parsed payload so the envelope is independent of any
        # later mutation of the caller's object.
        envelope: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "identity": checked_identity,
            "record_digest": record_digest,
            "payload": json.loads(canonical_payload),
            "issue_ref": checked_ref,
            "supersedes": checked_supersedes,
            "appended_at": utc_now(),
        }
        envelope["record_hash"] = sha256_hex(canonical_json(envelope))
        verify_envelope(envelope)
        blob = (canonical_json(envelope) + "\n").encode("utf-8")
        if len(blob) > MAX_JSON_BYTES:
            raise CoreError("invalid_input", "record exceeds size limit", 3)
        path = self._records / f"{checked_identity}.json"
        _reject_link_components(path)
        # Atomic insert-if-absent (CAS on key existence, P1-3): a single
        # O_CREAT|O_EXCL create decides the winner. No check-then-write.
        for attempt in range(CAS_ATTEMPTS):
            try:
                descriptor = os.open(path, _WRITE_FLAGS, 0o600)
            except FileExistsError:
                try:
                    existing = _read_verified(path)
                except CoreError as error:
                    if error.category == "not_found" and attempt + 1 < CAS_ATTEMPTS:
                        continue  # winning writer vanished mid-write; retry the CAS
                    raise
                return _render_loser(existing, record_digest, checked_identity)
            except OSError as error:
                raise CoreError("io_error", "could not create record", 7) from error
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(blob)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError:
                try:
                    os.unlink(path)  # remove our own partial record; CAS stays retryable
                except OSError:
                    pass
                raise CoreError("io_error", "could not persist record", 7)
            _fsync_directory(self._records)
            if self._backup is not None:
                self._backup(path, dict(envelope))
            return {"outcome": OUTCOME_APPENDED, "appended": True,
                    "identity": checked_identity, "record_digest": record_digest}
        raise CoreError("io_error", "concurrent appends did not resolve", 7)  # pragma: no cover

    def get(self, identity: str) -> dict[str, Any] | None:
        """Return the verified record stored under ``identity``, or None.

        A record that existed at the existence check but vanished before it
        could be read (an external, out-of-contract deletion) reads as None;
        a present but corrupt record fails closed instead.
        """
        checked = validate_identity(identity)
        path = self._records / f"{checked}.json"
        _reject_link_components(path)
        if not path.is_file():
            return None
        try:
            return _read_verified(path)
        except CoreError as error:
            if error.category == "not_found":
                return None
            raise

    def get_by_digest(self, digest: str) -> dict[str, Any] | None:
        """Content-addressed lookup by record digest (bounded linear scan)."""
        digest = normalize_digest_input(digest, field="digest")
        return self._scan_by_digest(digest)

    def iter_records(self) -> list[dict[str, Any]]:
        """All verified stored records, ordered by identity."""
        return [_read_verified(path) for path in sorted(self._records.glob("*.json"))]

    def verify(self) -> int:
        """Verify every stored record's integrity; return the record count.

        Raises ``CoreError`` (``integrity_error``) on the first tampered or
        partial record -- fail closed, never a partial trust statement.
        """
        count = 0
        for path in sorted(self._records.glob("*.json")):
            _read_verified(path)
            count += 1
        return count

    def _scan_by_digest(self, digest: str) -> dict[str, Any] | None:
        for record in self.iter_records():
            if record["record_digest"] == digest:
                return record
        return None


__all__ = [
    "BACKUP_CONFIGURED",
    "BACKUP_UNFULFILLED",
    "BackupHook",
    "CONFLICT_FIELD",
    "OUTCOME_APPENDED",
    "OUTCOME_CONFLICT",
    "OUTCOME_REDELIVERY",
    "SCHEMA_VERSION",
    "CoreError",
    "CoreStore",
    "canonical_json",
    "normalize_digest_input",
    "sha256_hex",
    "utc_now",
    "validate_identity",
    "validate_issue_ref",
    "verify_envelope",
]
