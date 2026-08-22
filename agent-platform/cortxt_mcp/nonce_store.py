"""Durable, file-backed nonce replay-store and per-mandate cumulative
budget store for cortxt_mcp's mandate verification (ADR-032).

Storage-form decision (ADR-032 open question, resolved for v1): a plain
JSON file per store, written atomically (tempfile + `os.replace`,
mirroring `runtime.session_state`'s own atomic-write primitive) rather
than reusing the session_state ledger machinery -- the nonce/budget
registers are global across every server session, while session_state's
ledger is deliberately per-session, so bolting a global register onto a
per-session store would need a synthetic well-known session id and would
mix two different lifetimes in one file. A dedicated file per concern
keeps each one simple and independently inspectable.

Both stores are durable across server restarts (the whole point of AC 3
surviving a restart) via a plain on-disk file, and safe against a crash
mid-write (atomic replace never leaves a partially-written file). A
process-local `threading.Lock` serializes concurrent access from multiple
threads of the same server process. Cross-process concurrent writers are
not a supported scenario for this v1 -- the MCP server is a single stdio
process per connection -- and is flagged as an open question in
ADR-032, not silently assumed safe.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


def _atomic_write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp = tempfile.mkstemp(prefix=".mandate-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError):
        return default


class NonceStore:
    """Durable used-nonce register, checked-and-consumed atomically
    (within this process) by `check_and_consume`. Backed by a JSON file
    at `path` -- `{"nonces": [...]}` -- so a fresh `NonceStore` pointed at
    the same path after a process restart sees every nonce a prior
    process consumed."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def check_and_consume(self, nonce: str) -> bool:
        """Return True and record `nonce` as used if it was not already
        used; return False (and record nothing new) if it was already
        used. Any malformed/unreadable store file is treated as empty
        (never as an error that lets a nonce through) -- if a nonce is
        empty/falsy, fail closed and return False."""
        if not nonce:
            return False
        with self._lock:
            doc = _read_json(self._path, {"nonces": []})
            used = set(doc.get("nonces", []))
            if nonce in used:
                return False
            used.add(nonce)
            _atomic_write_json(self._path, {"nonces": sorted(used)})
            return True


class BudgetStore:
    """Durable per-mandate cumulative spend register. `record_and_check`
    debits `cost` against `mandate_id`'s running total *before* reporting
    whether the mandate is still within `cap` -- the debit always
    happens, whether or not the mandate ends up within budget, so a
    second concurrent call sees the first call's debit already applied
    (closes the 'N parallel calls each individually under cap' bypass,
    adversarial review MED-2)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def record_and_check(self, mandate_id: str | None, cost: float, cap: float) -> bool:
        if not mandate_id:
            return False
        with self._lock:
            doc = _read_json(self._path, {"spent": {}})
            spent = dict(doc.get("spent", {}))
            total = float(spent.get(mandate_id, 0.0)) + max(float(cost), 0.0)
            spent[mandate_id] = total
            _atomic_write_json(self._path, {"spent": spent})
            return total <= cap
