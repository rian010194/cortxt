"""Resolve the Cortxt read area -- where Cortxt is allowed to *look*.

Cortxt can be told where its durable state lives (``state/data_home.py``) but
not where it may read. Every discovery today is therefore implicit: a path
appears in a prompt, in a hard-coded constant, or in whatever directory a
process happened to start in. This module is the explicit counterpart --
one configured list of roots that bounds what Cortxt will scan.

Three rules carry the design, and the third is the one that is easy to get
wrong by copying the neighbouring resolver.

1. **Unconfigured is not an error.** With ``CORTXT_READ_AREA`` unset and no
   explicit argument, ``resolve_read_area`` returns an empty tuple: no read
   area, no discovery, and every caller keeps its existing behaviour. This is
   the same non-breaking contract as ``resolve_data_home`` returning ``None``.
   Nothing about a default start changes, and selecting a read area is never
   a mandatory first step for anything.

2. **Set but invalid is a refusal, never a fallback.** A configured-but-wrong
   read area is a configuration defect the operator must see. Silently
   scanning a guessed location is how a proposal ends up describing a tree
   nobody chose. Every refusal raises ``ReadAreaError`` with a stable
   ``.code``.

3. **There is deliberately no ``inside_checkout`` refusal here, and there must
   not be one.** ``data_home.py`` refuses a location inside the repository
   checkout because durable state must not live in a tree that changes
   branch. A read area is the *opposite* concern: it is expected to contain
   repository checkouts -- that is its entire purpose. Copying that rule
   across would refuse every valid configuration.

Multiple roots are separated by ``os.pathsep``, so the variable behaves the
way ``PATH`` does on this platform rather than inventing a second convention.

**Read is not write.** Nothing here grants, records, or implies permission to
modify anything. A read area bounds looking; it is not an allowlist, and no
write path is derived from it anywhere.

Standard library only; offline; no network code; no side effects -- the
resolver never creates a directory and never touches what it names.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

READ_AREA_ENV = "CORTXT_READ_AREA"


class ReadAreaError(Exception):
    """Fail-closed configuration error carrying a stable ``.code``.

    Deliberately the same shape as ``DataHomeError``: a configuration code
    about where Cortxt may look, never a storage category about a record.
    """

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


def _split(value: str | Path) -> list[str]:
    """The configured value as its individual roots.

    A ``Path`` is one root and is never split: a path object is already a
    single location, and splitting its string form on ``os.pathsep`` would
    break any path that legitimately contains the separator character.
    """
    if isinstance(value, Path):
        return [str(value)]
    return str(value).split(os.pathsep)


def resolve_read_area(explicit: str | Path | None = None, *,
                      env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """The resolved, absolute read-area roots, in the order given.

    Resolution order: ``explicit``, then ``env[CORTXT_READ_AREA]`` (default
    ``os.environ``), then an empty tuple. Several roots are separated by
    ``os.pathsep``.

    An absent read area yields ``()`` -- unconfigured is a normal state, not
    a defect. A value that is *present* but unusable raises ``ReadAreaError``
    rather than falling back to a guess.
    """
    environment = os.environ if env is None else env
    source = "the --read-area argument"
    value = explicit
    if value is None:
        value, source = environment.get(READ_AREA_ENV), READ_AREA_ENV
    if value is None:
        return ()

    entries = _split(value)
    if not str(value).strip():
        raise ReadAreaError(
            "unset_value",
            f"{source} is set to an empty value. Unset it to run without a read "
            f"area, or set it to one or more absolute directories separated by "
            f"{os.pathsep!r}.")

    roots: list[Path] = []
    for entry in entries:
        if not entry.strip():
            raise ReadAreaError(
                "unset_value",
                f"{source} contains an empty entry ({str(value)!r}). Every "
                f"{os.pathsep!r}-separated entry must name an absolute directory; "
                f"remove the stray separator.")
        # Stripped before use: a value assembled by hand or by a shell often
        # carries padding around a separator, and a root that differs only by
        # whitespace is the same root.
        entry = entry.strip()
        raw = Path(entry)
        if not raw.is_absolute():
            raise ReadAreaError(
                "not_absolute",
                f"{source} names a root that is not an absolute path ({entry!r}). "
                f"A relative root would resolve against the process working "
                f"directory, so what Cortxt is allowed to read would depend on "
                f"where it happened to be started.")
        if ".." in raw.parts:
            # Checked before resolving, which would erase the component.
            raise ReadAreaError(
                "unsafe_path",
                f"{source} names a root containing a '..' component ({entry!r}). "
                f"Give the directory by its literal absolute path, so what the "
                f"read area covers is readable from the value itself.")
        try:
            resolved = raw.resolve(strict=False)
        except OSError as error:  # pragma: no cover - platform dependent
            raise ReadAreaError(
                "not_a_directory",
                f"{source} names {entry!r}, which could not be resolved: {error}"
            ) from error
        if not resolved.is_dir():
            raise ReadAreaError(
                "not_a_directory",
                f"{source} names {resolved}, which does not exist or is not a "
                f"directory. A read area is only ever scanned, never created; "
                f"name a directory that is already there.")
        roots.append(resolved)

    for index, root in enumerate(roots):
        for other in roots[:index]:
            if root == other:
                raise ReadAreaError(
                    "duplicate_root",
                    f"{source} names {root} more than once. Scanning would report "
                    f"every repository beneath it twice; list it once.")
            # Nesting is the same defect wearing a different value: the inner
            # root's repositories lie beneath the outer one and would be
            # discovered under both.
            if _is_within(root, other):
                raise ReadAreaError(
                    "duplicate_root",
                    f"{source} names {root}, which lies inside {other}. Scanning "
                    f"would report the repositories beneath it twice; name the "
                    f"outer directory alone.")
            if _is_within(other, root):
                raise ReadAreaError(
                    "duplicate_root",
                    f"{source} names {root}, which contains {other}. Scanning "
                    f"would report the repositories beneath it twice; name the "
                    f"outer directory alone.")

    return tuple(roots)
