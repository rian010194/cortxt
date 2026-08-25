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

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from widget_contract.tokens import (
    DEFAULT_PRESET_ID,
    DEFAULT_TOKENS_PATH,
    TokensError,
    load_preset_tokens,
    load_presets,
)


class ThemeResolverError(ValueError):
    """Raised when a theme preference cannot be read, written, or resolved."""
    pass


DEFAULT_THEME_PREFERENCE_PATH = Path.home() / ".cortxt" / "theme.json"


def _load_presets_envelope(presets_path: str | Path | None = None) -> dict[str, Any]:
    """Load the visual-tokens.v2 envelope, wrapping load failures as ThemeResolverError.

    Shared by every place that needs either the known preset ids or the
    collection's own ``default_preset`` -- keeping this as one helper means
    the fallback preset id in :func:`resolve_theme` is always read from the
    same envelope used to validate ids, never a separate/hardcoded source.
    """
    try:
        return load_presets(presets_path)
    except TokensError as err:
        raise ThemeResolverError(f"Cannot resolve theme: presets unavailable ({err})") from err


def _known_preset_ids(presets_path: str | Path | None = None) -> frozenset[str]:
    """The set of valid preset ids, sourced from the visual-tokens.v2 collection."""
    envelope = _load_presets_envelope(presets_path)
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


def save_persisted_theme(
    preset_id: str,
    path: str | Path | None = None,
    *,
    presets_path: str | Path | None = None,
) -> None:
    """Persist a theme preference for this user, replacing any prior value.

    Parameters:
        preset_id: The preset id to persist. Must be a known preset id from
            the visual-tokens.v2 collection.
        path: Optional override for the preference file location. Defaults to
            :data:`DEFAULT_THEME_PREFERENCE_PATH`.
        presets_path: Optional override for the visual-tokens.v2 presets file
            used to validate preset_id. Defaults to
            ``widget_contract.tokens.DEFAULT_PRESETS_PATH``. Pass the same
            value used with :func:`resolve_theme` when working against a
            non-default presets collection, so a preset id is never accepted
            here only to be rejected by a later :func:`resolve_theme` call
            against that same collection.

    Raises:
        ThemeResolverError: If preset_id is not a known preset in the
            presets collection at presets_path, or the preference file
            cannot be written.
    """
    _validate_preset_id(preset_id, presets_path=presets_path)

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
                handle.flush()
                os.fsync(handle.fileno())
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
        3. The presets collection's own ``default_preset`` field (this is
           ``widget_contract.tokens.DEFAULT_PRESET_ID``, i.e. ``quiet-slate``,
           for the shipped presets file, but a caller-supplied
           ``presets_path`` with a different ``default_preset`` is honored --
           never the hardcoded constant).

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
    session_override = (session_override or "").strip()
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

    return _load_presets_envelope(presets_path)["default_preset"]


class SyncResult:
    """Outcome of a :func:`sync_widget_tokens` call.

    Attributes:
        preset_id: The preset id resolved by :func:`resolve_theme`.
        written: True if `widget/tokens.json` was (over)written; False if the
            write was skipped because the file was hand-edited since the
            last sync (see :func:`sync_widget_tokens`'s clobber-guard docs).
        reason: None when ``written`` is True; a short human-readable
            explanation of why the write was skipped otherwise.
    """

    __slots__ = ("preset_id", "written", "reason")

    def __init__(self, preset_id: str, written: bool, reason: str | None = None) -> None:
        self.preset_id = preset_id
        self.written = written
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"SyncResult(preset_id={self.preset_id!r}, written={self.written!r}, reason={self.reason!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SyncResult):
            return NotImplemented
        return (self.preset_id, self.written, self.reason) == (other.preset_id, other.written, other.reason)


def _sync_marker_path(target_path: Path) -> Path:
    """Sidecar file path recording the hash of the last content sync_widget_tokens wrote.

    Kept alongside the tokens file itself (``tokens.json.sync-marker.json``)
    rather than folded into tokens.json's own fields, since tokens.json is a
    flat visual-tokens.v1 document consumed by the widget host and Widget
    Maker as-is -- adding bookkeeping fields to it would leak into that
    schema. The marker is purely an implementation detail of the clobber
    guard below.
    """
    return target_path.with_name(target_path.name + ".sync-marker.json")


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync_widget_tokens(
    session_override: str | None = None,
    *,
    path: str | Path | None = None,
    presets_path: str | Path | None = None,
    widget_tokens_path: str | Path | None = None,
    force: bool = False,
) -> SyncResult:
    """Resolve the applicable preset and write it to the widget host's live tokens file.

    `agent-platform/widget/tokens.json` is the flat visual-tokens.v1-shaped
    document the widget host's static server (`widget/serve.py`) actually
    serves, and what `index.html`/`maker.html` poll (issue #376: the widget
    host must apply the resolver's chosen preset, not invent its own
    palette). This is the one place that bridges the two: it resolves which
    preset applies via :func:`resolve_theme` and overwrites the widget
    host's tokens.json with that preset's flat token document, so a preset
    switch (`cortxt theme use <preset>`, issue #375) reflects in the widget
    host without requiring that surface to duplicate resolver precedence
    logic.

    Clobber guard: tokens.json is also the file the Widget Maker's Tokens
    tab hand-edits directly, so unconditionally overwriting it every time a
    preset switch happens would silently discard those edits. This function
    writes a sidecar marker (see :func:`_sync_marker_path`) recording the
    hash of the content it wrote, each time it writes. Before writing again,
    it checks the marker against the *current* on-disk file:

    - No marker yet (this function has never synced before) -- write is
      allowed unconditionally, since there is nothing of "ours" that could
      have been hand-edited over.
    - Marker present and its hash matches the current file's hash -- the
      file still holds exactly what a previous sync wrote (untouched since),
      so overwriting it with the newly resolved preset is safe.
    - Marker present but its hash does NOT match the current file's hash --
      someone (the Widget Maker, an operator) edited tokens.json by hand
      since the last sync. The write is skipped and ``SyncResult.written``
      is False, so a preset switch never silently destroys a hand edit.
      Pass ``force=True`` to override this and write anyway.

    Deliberately NOT wired into every `cortxt widget` invocation: call this
    explicitly (from a `theme use` command, or interactively) when applying
    a preset switch is actually intended.

    Parameters:
        session_override: Forwarded to :func:`resolve_theme` -- see there.
        path: Forwarded to :func:`resolve_theme` (persisted-preference file).
        presets_path: Forwarded to :func:`resolve_theme` and
            :func:`~widget_contract.tokens.load_preset_tokens`.
        widget_tokens_path: Optional override for the widget tokens.json
            destination. Defaults to
            ``widget_contract.tokens.DEFAULT_TOKENS_PATH``
            (``agent-platform/widget/tokens.json``).
        force: If True, skip the clobber guard and always overwrite.

    Returns:
        A :class:`SyncResult` describing the resolved preset id and whether
        the file was actually written.

    Raises:
        ThemeResolverError: If resolution fails, or the destination file
            cannot be written.
    """
    preset_id = resolve_theme(session_override, path=path, presets_path=presets_path)
    try:
        tokens = load_preset_tokens(preset_id, presets_path)
    except TokensError as err:
        raise ThemeResolverError(f"Cannot load resolved preset '{preset_id}': {err}") from err

    target_path = Path(widget_tokens_path) if widget_tokens_path is not None else DEFAULT_TOKENS_PATH
    marker_path = _sync_marker_path(target_path)
    content = json.dumps(tokens, indent=2) + "\n"
    content_bytes = content.encode("utf-8")
    new_hash = _hash_bytes(content_bytes)

    if not force and target_path.is_file():
        stored_hash: str | None = None
        if marker_path.is_file():
            try:
                marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
                if isinstance(marker_data, dict):
                    candidate = marker_data.get("hash")
                    if isinstance(candidate, str):
                        stored_hash = candidate
            except Exception:
                # An unreadable/corrupt marker is treated as "no prior sync
                # recorded" -- fall through to the unconditional-write path
                # rather than blocking every future sync on a broken marker.
                stored_hash = None

        if stored_hash is not None:
            try:
                current_hash = _hash_bytes(target_path.read_bytes())
            except OSError as err:
                raise ThemeResolverError(f"Cannot read widget tokens file {target_path}: {err}") from err

            if current_hash != stored_hash:
                return SyncResult(
                    preset_id,
                    False,
                    (
                        f"{target_path} was hand-edited since the last sync "
                        "(hash mismatch against the sync marker) -- skipped to "
                        "avoid clobbering a Widget Maker edit; pass force=True to override"
                    ),
                )

    target_dir = target_path.parent
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise ThemeResolverError(f"Cannot create widget tokens directory {target_dir}: {err}") from err

    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".tokens-", suffix=".tmp", dir=str(target_dir))
        try:
            # Binary mode, writing content_bytes verbatim: text mode would
            # translate "\n" to the platform line ending (e.g. "\r\n" on
            # Windows), so the bytes actually on disk would no longer match
            # content_bytes/new_hash and every subsequent sync would see a
            # false "hand-edited" mismatch against its own prior write.
            with os.fdopen(fd, "wb") as handle:
                handle.write(content_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target_path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise
    except OSError as err:
        raise ThemeResolverError(f"Cannot write widget tokens file {target_path}: {err}") from err

    try:
        marker_fd, marker_tmp = tempfile.mkstemp(prefix=".tokens-sync-", suffix=".tmp", dir=str(target_dir))
        try:
            with os.fdopen(marker_fd, "w", encoding="utf-8") as handle:
                json.dump({"hash": new_hash, "preset": preset_id}, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(marker_tmp, marker_path)
        except BaseException:
            if os.path.exists(marker_tmp):
                os.remove(marker_tmp)
            raise
    except OSError as err:
        raise ThemeResolverError(f"Cannot write widget tokens sync marker {marker_path}: {err}") from err

    return SyncResult(preset_id, True, None)
