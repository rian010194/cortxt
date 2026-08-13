"""Offline, append-only run-state ledger for Cortxt."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# The policy implementation is authoritative and remains owned by inference/.
INFERENCE_DIR = Path(__file__).resolve().parent.parent / "inference"
if str(INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(INFERENCE_DIR))
from provider_policy import AssuranceStatus, ProviderEvidence, evaluate_provider  # noqa: E402

SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
RUN_ID_RE = re.compile(r"^run_[0-9a-f]{32}$")
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
MAX_JSON_BYTES = 1_048_576
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000
MAX_TEXT_LENGTH = 16_384
REPARSE_POINT = 0x400


class LedgerError(Exception):
    def __init__(self, category: str, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.category, self.message, self.exit_code = category, message, exit_code


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise LedgerError("invalid_input", "value cannot be represented as canonical JSON", 3)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_utc(value: Any) -> bool:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo == timezone.utc


def parse_budget(value: str) -> str:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        raise LedgerError("invalid_input", "max_cost_usd must be a decimal number", 3)
    if not amount.is_finite() or amount < 0:
        raise LedgerError("invalid_input", "max_cost_usd must be finite and nonnegative", 3)
    normalized = amount.normalize()
    integer_digits = max(normalized.adjusted() + 1, 1) if normalized else 1
    scale = max(-normalized.as_tuple().exponent, 0)
    significant = len(normalized.as_tuple().digits)
    if integer_digits > 12 or scale > 6 or significant > 18:
        raise LedgerError("invalid_input", "max_cost_usd exceeds 12 integer or 6 fractional digits", 3)
    result = format(normalized, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if result in ("", "-0") else result


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
            raise LedgerError("unsafe_path", "links and reparse points are not allowed", 3)


def safe_store(store: str) -> Path:
    raw = Path(store)
    if ".." in raw.parts:
        raise LedgerError("unsafe_path", "path traversal is not allowed", 3)
    absolute = raw.absolute()
    _reject_link_components(absolute)
    if not absolute.is_dir():
        raise LedgerError("unsafe_path", "state store must be an existing directory", 3)
    resolved = absolute.resolve(strict=True)
    if resolved != absolute.resolve(strict=False):
        raise LedgerError("unsafe_path", "state store resolution changed", 3)
    return resolved


def safe_input_file(filename: str) -> Path:
    raw = Path(filename)
    if ".." in raw.parts:
        raise LedgerError("unsafe_path", "path traversal is not allowed", 3)
    absolute = raw.absolute()
    _reject_link_components(absolute)
    if not absolute.is_file():
        raise LedgerError("invalid_input", "input must be a regular file", 3)
    resolved = absolute.resolve(strict=True)
    if resolved != absolute:
        raise LedgerError("unsafe_path", "input resolution changed", 3)
    return resolved


def run_path(store: Path, run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise LedgerError("invalid_input", "invalid run_id", 3)
    target = store / run_id / "ledger.json"
    if not target.is_relative_to(store):
        raise LedgerError("unsafe_path", "run path escaped the state store", 3)
    return target


def _validate_json_shape(value: Any, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
        raise LedgerError("invalid_input", "JSON exceeds complexity limits", 3)
    if value is None or type(value) in (bool, int, str):
        if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
            raise LedgerError("invalid_input", "JSON string exceeds size limit", 3)
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise LedgerError("invalid_input", "JSON numbers must be finite", 3)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_shape(item, depth + 1, counter)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for key, item in value.items():
            if len(key) > 256:
                raise LedgerError("invalid_input", "JSON key exceeds size limit", 3)
            _validate_json_shape(item, depth + 1, counter)
        return
    raise LedgerError("invalid_input", "JSON contains an unsupported value", 3)


def read_json_file(filename: str) -> Any:
    path = safe_input_file(filename)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise LedgerError("invalid_input", "input exceeds size limit", 3)
        text = path.read_text(encoding="utf-8")
        value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _validate_json_shape(value)
        return value
    except LedgerError:
        raise
    except (OSError, UnicodeError):
        raise LedgerError("io_error", "could not read input", 7)
    except (json.JSONDecodeError, ValueError, RecursionError):
        raise LedgerError("invalid_input", "input is not valid bounded JSON", 3)


def evaluate_evidence(data_class: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LedgerError("invalid_input", "provider evidence must be an object", 3)
    evidence = dict(value)
    status = evidence.get("independent_assurance")
    if isinstance(status, str):
        try:
            evidence["independent_assurance"] = AssuranceStatus(status)
        except ValueError:
            pass
    try:
        decision = evaluate_provider(data_class, ProviderEvidence(**evidence))
    except (TypeError, ValueError):
        raise LedgerError("invalid_input", "provider evidence has an invalid schema", 3)
    if decision.allowed is not True:
        raise LedgerError("policy_denied", "authoritative provider policy denied the run", 3)
    result = asdict(decision)
    result["reasons"] = list(decision.reasons)
    return result


def _event(sequence: int, event_type: str, payload: Any, previous_hash: str,
           run_id: str) -> dict[str, Any]:
    unsigned = {"event_type": event_type, "payload": payload, "previous_hash": previous_hash,
                "run_id": run_id, "schema_version": SCHEMA_VERSION, "sequence": sequence,
                "timestamp": utc_now()}
    return {**unsigned, "hash": hashlib.sha256(canonical_json(unsigned)).hexdigest()}


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
        raise LedgerError("io_error", "could not synchronize ledger directory", 7) from error


def _replace(path: Path, ledger: dict[str, Any]) -> None:
    _reject_link_components(path)
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".ledger-", suffix=".tmp", dir=path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json(ledger) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _reject_link_components(path.parent)
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    except LedgerError:
        raise
    except OSError as error:
        raise LedgerError("io_error", "could not persist ledger", 7) from error
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


@contextmanager
def _exclusive_append(run_directory: Path):
    lock_path = run_directory / ".append.lock"
    try:
        handle = lock_path.open("a+b")
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as error:
        try:
            handle.close()
        except (UnboundLocalError, OSError):
            pass
        raise LedgerError("sequence_conflict", "another append is in progress", 5) from error
    try:
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        except OSError as error:
            raise LedgerError("io_error", "could not release append lock", 7) from error


def create(store_name: str, task_id: str, data_class: str, workflow: str,
           budget: str, evidence_file: str) -> dict[str, Any]:
    store = safe_store(store_name)
    if not all(isinstance(x, str) and x.strip() and len(x) <= 256
               for x in (task_id, data_class, workflow)):
        raise LedgerError("invalid_input", "task_id, data_class, and workflow must be bounded strings", 3)
    decision = evaluate_evidence(data_class, read_json_file(evidence_file))
    max_cost = parse_budget(budget)
    run_id = "run_" + uuid.uuid4().hex
    path = run_path(store, run_id)
    payload = {"budget": {"max_cost_usd": max_cost}, "data_class": data_class,
               "policy_decision": decision, "task_id": task_id, "workflow": workflow}
    ledger = {"schema_version": SCHEMA_VERSION, "run_id": run_id,
              "events": [_event(0, "run.created", payload, ZERO_HASH, run_id)]}
    try:
        path.parent.mkdir(exist_ok=False)
        _fsync_directory(store)
        _reject_link_components(path.parent)
        _replace(path, ledger)
    except LedgerError:
        raise
    except OSError as error:
        raise LedgerError("io_error", "could not create run directory", 7) from error
    return ledger


def load(store_name: str, run_id: str) -> tuple[Path, dict[str, Any]]:
    store = safe_store(store_name)
    path = run_path(store, run_id)
    _reject_link_components(path)
    if not path.is_file() or path.resolve(strict=True).parent.parent != store:
        raise LedgerError("not_found", "run ledger was not found", 4)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise LedgerError("integrity_error", "ledger exceeds size limit", 6)
        ledger = json.loads(path.read_text(encoding="utf-8"),
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _validate_json_shape(ledger)
    except LedgerError as error:
        if error.category == "invalid_input":
            raise LedgerError("integrity_error", error.message, 6)
        raise
    except (json.JSONDecodeError, ValueError, RecursionError):
        raise LedgerError("integrity_error", "ledger is not valid bounded JSON", 6)
    except (OSError, UnicodeError):
        raise LedgerError("io_error", "could not read ledger", 7)
    validate(ledger, run_id)
    return path, ledger


def validate(ledger: Any, run_id: str) -> None:
    if not isinstance(ledger, dict) or set(ledger) != {"schema_version", "run_id", "events"}:
        raise LedgerError("integrity_error", "ledger has an invalid schema", 6)
    if type(ledger["schema_version"]) is not int or ledger["schema_version"] != SCHEMA_VERSION:
        raise LedgerError("integrity_error", "ledger schema version is invalid", 6)
    if ledger["run_id"] != run_id:
        raise LedgerError("integrity_error", "ledger identity is invalid", 6)
    events = ledger["events"]
    if not isinstance(events, list) or not events:
        raise LedgerError("integrity_error", "ledger must contain events", 6)
    previous = ZERO_HASH
    fields = {"event_type", "payload", "previous_hash", "run_id", "schema_version",
              "sequence", "timestamp", "hash"}
    for sequence, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != fields:
            raise LedgerError("integrity_error", "event has an invalid schema", 6)
        if type(event["sequence"]) is not int or event["sequence"] != sequence:
            raise LedgerError("integrity_error", "event sequence is invalid", 6)
        if type(event["schema_version"]) is not int or event["schema_version"] != SCHEMA_VERSION:
            raise LedgerError("integrity_error", "event schema version is invalid", 6)
        if event["run_id"] != run_id or event["previous_hash"] != previous:
            raise LedgerError("integrity_error", "event context or chain is invalid", 6)
        if not isinstance(event["event_type"], str) or not EVENT_TYPE_RE.fullmatch(event["event_type"]):
            raise LedgerError("integrity_error", "event type is invalid", 6)
        if not _validate_utc(event["timestamp"]):
            raise LedgerError("integrity_error", "event timestamp is not canonical UTC", 6)
        unsigned = {key: event[key] for key in fields if key != "hash"}
        expected = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        if not isinstance(event["hash"], str) or event["hash"] != expected:
            raise LedgerError("integrity_error", "event hash is invalid", 6)
        previous = event["hash"]


def append(store_name: str, run_id: str, expected_sequence: int,
           event_type: str, payload_file: str) -> dict[str, Any]:
    if type(expected_sequence) is not int or expected_sequence < 0:
        raise LedgerError("invalid_input", "expected_sequence must be a nonnegative integer", 3)
    if not EVENT_TYPE_RE.fullmatch(event_type):
        raise LedgerError("invalid_input", "invalid event_type", 3)
    payload = read_json_file(payload_file)
    store = safe_store(store_name)
    target = run_path(store, run_id)
    _reject_link_components(target)
    if not target.parent.is_dir() or target.parent.resolve(strict=True).parent != store:
        raise LedgerError("not_found", "run ledger was not found", 4)
    with _exclusive_append(target.parent):
        path, ledger = load(store_name, run_id)
        current = len(ledger["events"]) - 1
        if current != expected_sequence:
            raise LedgerError("sequence_conflict", f"expected sequence {expected_sequence}, found {current}", 5)
        ledger["events"].append(_event(current + 1, event_type, payload,
                                        ledger["events"][-1]["hash"], run_id))
        _replace(path, ledger)
        return ledger
