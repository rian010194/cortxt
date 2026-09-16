"""Resolve the Cortxt data home -- durable state, outside the checkout.

Cortxt has no data home at the pin. Every durable location is derived from
where the *module* happens to sit: ``AGENT_PLATFORM_DIR = WIDGET_DIR.parent``
in ``widget/action_host.py``, and from it ``.dispatch/runs.json`` and
``.sessions``. That makes state a property of the source tree, so a branch
switch, a second worktree, or a `git clean` silently changes or destroys it.
``state/core_store.py`` requires the opposite and says so: its root is "the
durable Core directory under the control-plane data home (injectable; never
defaulted here)". This module is the missing resolver that closes that gap.

Two rules carry the whole design:

1. **Unset is not an error.** With ``CORTXT_DATA_HOME`` unset and no explicit
   argument, ``resolve_data_home`` returns ``None``: no store is configured,
   and callers keep their existing unconfigured behaviour (the packaging
   routes keep answering their 503 ``store_unavailable``). Nothing about a
   default start changes.

2. **Set but invalid is a refusal, never a fallback.** A configured-but-wrong
   data home is a configuration defect the operator must see. Guessing a
   location would reproduce exactly the failure this module exists to
   prevent -- #485's Run records landing in a second, unaudited root. Every
   refusal raises ``DataHomeError`` with a stable ``.code``.

``DataHomeError`` deliberately carries ``.code`` rather than ``CoreError``'s
``.category``: these are *configuration* codes about where state may live, not
the storage categories the Core store raises about a record. Keeping them
distinct keeps a misconfigured start from reading as a storage failure.

Directory creation is left to ``CoreStore.__init__``, which already does
``mkdir(parents=True, exist_ok=True)`` and rejects link components. Creating
the directory here too would be a second authority for one rule.

Standard library only; offline; no network code.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Mapping

DATA_HOME_ENV = "CORTXT_DATA_HOME"

# This file is agent-platform/state/data_home.py, so the repository root is
# three parents up. Derived the same way action_host.py derives
# AGENT_PLATFORM_DIR (from __file__, never from cwd), then one more level.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class DataHomeError(Exception):
    """Fail-closed configuration error carrying a stable ``.code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _is_within(candidate: Path, parent: Path) -> bool:
    """True when ``candidate`` is ``parent`` or lies beneath it."""
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve_data_home(explicit: str | Path | None = None, *,
                      env: Mapping[str, str] | None = None,
                      repo_root: str | Path | None = None) -> Path | None:
    """The resolved absolute data home, or ``None`` when none is configured.

    Resolution order: ``explicit``, then ``env[CORTXT_DATA_HOME]`` (default
    ``os.environ``), then ``None``. A value that is present but unusable
    raises ``DataHomeError`` rather than falling back to a guess.
    """
    environment = os.environ if env is None else env
    source = "the --data-home argument"
    value = explicit
    if value is None:
        value, source = environment.get(DATA_HOME_ENV), DATA_HOME_ENV
    if value is None:
        return None

    text = str(value)
    if not text.strip():
        raise DataHomeError(
            "unset_value",
            f"{source} is set to an empty value. Unset it to run without a data "
            f"home, or set it to an absolute directory outside this checkout.")

    raw = Path(text)
    if not raw.is_absolute():
        raise DataHomeError(
            "not_absolute",
            f"{source} is not an absolute path ({text!r}). A relative data home "
            f"would resolve against the process working directory, which is the "
            f"cwd-relative-state defect this resolver exists to prevent.")
    if ".." in raw.parts:
        # Checked before resolving, which would erase the component. Mirrors
        # the same refusal in core_store.CoreStore.__init__.
        raise DataHomeError(
            "unsafe_path",
            f"{source} contains a '..' component. Give the directory by its "
            f"literal absolute path.")

    try:
        resolved = raw.resolve(strict=False)
    except OSError as error:  # pragma: no cover - platform dependent
        raise DataHomeError(
            "io_error", f"{source} could not be resolved: {error}") from error

    checkout = Path(repo_root).resolve(strict=False) if repo_root is not None else REPO_ROOT
    if _is_within(resolved, checkout):
        raise DataHomeError(
            "inside_checkout",
            f"{source} resolves inside the repository checkout ({checkout}). "
            f"Durable state must not live in a tree that changes branch, gets "
            f"cleaned, or exists once per worktree. Choose a directory outside "
            f"the checkout.")

    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    if _is_within(resolved, temp_root):
        raise DataHomeError(
            "temp_path",
            f"{source} resolves under the system temporary directory "
            f"({temp_root}). core_store.py names Temp/ explicitly as a forbidden "
            f"location for the durable Core store.")

    if not resolved.exists():
        parent = resolved.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise DataHomeError(
                "io_error",
                f"{source} names {resolved}, which does not exist and cannot be "
                f"created: {parent} is not a writable directory.")
    elif not resolved.is_dir():
        raise DataHomeError(
            "io_error", f"{source} names {resolved}, which exists but is not a "
                        f"directory.")

    return resolved


def core_root(data_home: str | Path) -> Path:
    """The Core store root beneath a data home. A pure path join."""
    return Path(data_home) / "core"
