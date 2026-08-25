"""Shared theme resolver: decides which visual-tokens.v2 preset applies.

Single resolver used by every consumer (CLI, TUI, widget host) so precedence
logic is never duplicated per surface (issue #374). Precedence, highest wins:

1. Session override -- e.g. a ``--theme`` flag or an in-session
   ``cortxt theme use <preset>`` call. Passed explicitly to :func:`resolve_theme`
   by the caller and never persisted unless the caller also calls
   :func:`save_persisted_theme`.
2. Persisted user preference -- global per user (operator decision
   2026-08-25: v1 ships global-per-user only; workspace-level preference is
   explicitly out of scope, see issue #379). Read from the JSON preference
   file at :data:`DEFAULT_THEME_PREFERENCE_PATH`.
3. Default preset -- ``quiet-slate`` (``widget_contract.tokens.DEFAULT_PRESET_ID``).

This module only resolves *which* preset id applies and persists that
choice; it does not build CLI commands (issue #375) and does not apply the
resolved preset to any rendering surface (issue #376) -- callers take the
returned preset id and do that themselves, e.g. via
``widget_contract.tokens.load_preset_tokens(preset=resolved_id)``.

Persistence mechanism
----------------------
The persisted preference is a small JSON file at
``<home>/.cortxt/theme.json`` (``Path.home() / ".cortxt" / "theme.json"`` --
on Windows this resolves under ``%USERPROFILE%``, matching the existing
per-user config convention used for credentials in
``agent-platform/cli/unified_cli.py``). The file holds a single object:

.. code-block:: json

    {"preset": "graphite-ink"}

Reads and writes are keyed by this one file for v1 (global-per-user only, no
workspace/session scoping in the persisted file itself -- issue #379 tracks
adding workspace-level precedence in a future revision). Writes are atomic
(write to a temp file in the same directory, then replace) so a crash or
concurrent write cannot leave a half-written preference file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from widget_contract.tokens import DEFAULT_PRESET_ID, TokensError, load_presets


class ThemeResolverError(ValueError):
    """Raised when a theme preference cannot be read, written, or resolved."""
    pass


DEFAULT_THEME_PREFERENCE_PATH = Path.home() / ".cortxt" / "theme.json"


def _known_preset_ids(presets_path: str | Path | None = None) -> frozenset[str]:
    """The set of valid preset ids, sourced from the visual-tokens.v2 collection."""
    try:
        envelope = load_presets(presets_path)
    except TokensError as err:
        raise ThemeResolverError(f"Cannot resolve theme: presets unavailable ({err})") from err
    return frozenset(envelope["presets"])


def _validate_preset_id(preset_id: str, *, presets_path: str | Path | None = None) -> None:
    known = _known_preset_ids(presets_path)
    if preset_id not in known:
        raise ThemeResolverError(
            f"Unknown preset '{preset_id}'; expected one of {', '.join(sorted(known))}"
        )


def load_persisted_theme(path: str | Path | None = None) -> str | None:
    """Read the persisted per-user theme preference, if any.

    Parameters:
        path: Optional override for the preference file location. Defaults to
            :data:`DEFAULT_THEME_PREFERENCE_PATH`.

    Returns:
        The persisted preset id, or None if no preference has been saved yet
        (file missing) or the file cannot be parsed as a valid preference.
    """
    target_path = Path(path) if path is not None else DEFAULT_THEME_PREFERENCE_PATH
    if not target_path.is_file():
        return None

    try:
        content = target_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception:
        # A corrupt or unreadable preference file is treated the same as "no
        # preference saved" -- resolution falls through to the default
        # rather than raising, so a bad file never blocks the caller.
        return None

    if not isinstance(data, dict):
        return None

    preset_id = data.get("preset")
    if not isinstance(preset_id, str) or not preset_id:
        return None

    return preset_id


def save_persisted_theme(preset_id: str, path: str | Path | None = None) -> None:
    """Persist a theme preference for this user, replacing any prior value.

    Parameters:
        preset_id: The preset id to persist. Must be a known preset id from
            the visual-tokens.v2 collection.
        path: Optional override for the preference file location. Defaults to
            :data:`DEFAULT_THEME_PREFERENCE_PATH`.

    Raises:
        ThemeResolverError: If preset_id is not a known preset, or the
            preference file cannot be written.
    """
    _validate_preset_id(preset_id)

    target_path = Path(path) if path is not None else DEFAULT_THEME_PREFERENCE_PATH
    target_dir = target_path.parent
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise ThemeResolverError(f"Cannot create preference directory {target_dir}: {err}") from err

    payload: dict[str, Any] = {"preset": preset_id}

    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".theme-", suffix=".tmp", dir=str(target_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            os.replace(tmp_name, target_path)
        except BaseException:
            # Clean up the temp file if the write or the atomic replace failed
            # partway through, so a crash never leaves a stray .theme-*.tmp
            # file behind.
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise
    except OSError as err:
        raise ThemeResolverError(f"Cannot write preference file {target_path}: {err}") from err


def clear_persisted_theme(path: str | Path | None = None) -> None:
    """Remove the persisted per-user theme preference, if one exists.

    A no-op if no preference file exists.

    Parameters:
        path: Optional override for the preference file location. Defaults to
            :data:`DEFAULT_THEME_PREFERENCE_PATH`.
    """
    target_path = Path(path) if path is not None else DEFAULT_THEME_PREFERENCE_PATH
    try:
        target_path.unlink(missing_ok=True)
    except OSError as err:
        raise ThemeResolverError(f"Cannot remove preference file {target_path}: {err}") from err


def resolve_theme(
    session_override: str | None = None,
    *,
    path: str | Path | None = None,
    presets_path: str | Path | None = None,
) -> str:
    """Resolve which preset id applies, given explicit precedence.

    Precedence (highest wins):
        1. ``session_override`` -- a command/session-scoped choice supplied by
           the caller (e.g. a ``--theme`` flag or an in-session
           ``cortxt theme use <preset>`` call). Not persisted by this
           function; call :func:`save_persisted_theme` explicitly to persist
           a choice the user wants to keep across invocations.
        2. The persisted per-user preference (see :func:`load_persisted_theme`).
        3. The default preset (``widget_contract.tokens.DEFAULT_PRESET_ID``,
           ``quiet-slate``).

    Parameters:
        session_override: Optional preset id scoped to this call/session.
            When provided it wins outright; when None or empty, resolution
            falls through to the persisted preference and then the default.
        path: Optional override for the persisted-preference file location.
            Defaults to :data:`DEFAULT_THEME_PREFERENCE_PATH`.
        presets_path: Optional override for the visual-tokens.v2 presets file
            used to validate preset ids. Defaults to
            ``widget_contract.tokens.DEFAULT_PRESETS_PATH``.

    Returns:
        The resolved preset id. Guaranteed to be a known preset id.

    Raises:
        ThemeResolverError: If session_override is provided but not a known
            preset id, or if the presets collection itself cannot be loaded.
    """
    if session_override:
        _validate_preset_id(session_override, presets_path=presets_path)
        return session_override

    persisted = load_persisted_theme(path)
    if persisted:
        try:
            _validate_preset_id(persisted, presets_path=presets_path)
        except ThemeResolverError:
            # A persisted preference that no longer names a known preset
            # (e.g. the presets collection changed) falls through to the
            # default rather than raising -- resolution should never fail
            # just because a stale preference file is sitting on disk.
            pass
        else:
            return persisted

    return DEFAULT_PRESET_ID
