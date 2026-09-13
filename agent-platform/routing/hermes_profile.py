"""The shared Hermes profile resolver and its revision (M1 of explicit profile
selection, issue #555 / #594).

Cortxt should be able to start the right Hermes profile directly
(``hermes -p <profile>``) instead of reaching a profile only through the
``hermes-free`` route, which overrides the profile's model/provider with
``CORTXT_FREE_*``. The first independently useful step is a shared resolver any
entry point (CLI, MCP, OS) can reuse: resolve a *named* profile's declared
execution fields from its local ``config.yaml``, and bind exactly those fields
into a ``profile_revision`` the same way ``dispatch.request.v2`` (§2) binds an
``execution_profile_revision``.

Declared fields and where they live in ``config.yaml``:

- ``model``     -- ``model.default`` (Hermes also accepts ``model.model``)
- ``provider``  -- ``model.provider``
- ``base_url``  -- ``model.base_url``
- ``api_mode``  -- ``model.api_mode``
- ``fallback``  -- the declared fallback chain, read with the *same* merge
  semantics as Hermes' own ``get_fallback_chain``
  (``hermes_cli/fallback_config.py``): ``fallback_providers`` is the primary key
  and keeps its order, legacy ``fallback_model`` entries are appended after it,
  and an entry already present (same provider/model/normalised base_url, case-
  insensitive) is deduplicated. Each effective entry is then *projected onto an
  explicit non-secret routing allowlist* -- ``provider``, ``model``,
  ``base_url``, ``api_mode`` -- and every other key is dropped. That keeps an
  inline ``api_key`` / ``key_env`` out of both the returned dict and the
  revision (a credential rotation must never move an approved digest), and it
  keeps provider-local extras such as ``max_tokens`` out of the revision too,
  because a non-routing extra is not execution configuration. An undeclared
  chain and an explicitly empty one both resolve to ``[]`` ("no declared
  fallback"), not to an error -- an absent chain is a well-defined value, unlike
  an absent model/provider/base_url/api_mode. A chain of the wrong type, or an
  entry that is not a mapping or does not name both a provider and a model,
  fails closed rather than being silently skipped, because a fallback the
  operator declared but the resolver dropped would make ``profile_revision``
  blind to it.

Fail-closed: an unknown profile, an empty/non-string name, a name that would
escape the profiles root, a missing/unreadable/unparseable/empty config file,
or a missing/empty bound field raises :class:`HermesProfileError`. There is
never a silent fallback to ``default``.

No env read, no network call, and no model call: field resolution is a local
YAML read, and no credential value (``api_key`` and friends) is ever selected
or returned.

``profile_revision`` binds ``PROFILE_BOUND_FIELDS`` only -- deliberately NOT
tool rights / ``platform_toolsets``, ``delegation``, skills, display, kanban,
personality, or any secret. It reuses ``routing.execution_profile``'s
``canonical_json`` / ``sha256_digest``; no second digest mechanism is
introduced. The existing ``EXECUTION_PROFILE_FIELDS`` tuple is order-bearing
and bound to ``dispatch.request.v2`` §2 -- it is untouched here.

This module is purely additive (M1): nothing calls it yet, no existing runtime
is required to pass an explicit profile, and ``hermes-free`` / ``dsh`` /
``hermes-researcher`` / ``hermes-coordinator`` behaviour is unchanged. A
missing explicit profile fails only where a mandate requires one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from routing.execution_profile import canonical_json, sha256_digest

# The execution-profile fields the profile revision binds. Order is not
# load-bearing (``canonical_json`` sorts keys) but is kept in the spec's order.
PROFILE_BOUND_FIELDS = (
    "model",
    "provider",
    "base_url",
    "api_mode",
    "fallback",
)

# Bound fields that a profile MUST declare (and declare non-empty). ``fallback``
# is excluded: an undeclared chain is a well-defined empty chain.
_REQUIRED_DECLARED_FIELDS = ("model", "provider", "base_url", "api_mode")

# Default profiles root: the Hermes profiles directory on this host. Callers
# (CLI, MCP, OS) may override it; resolution never reads the environment.
DEFAULT_PROFILES_ROOT = Path("C:/Users/rikar/AppData/Local/hermes/profiles")

_CONFIG_FILENAME = "config.yaml"
_MODEL_BLOCK = "model"
_MODEL_NAME_KEYS = ("default", "model")
# Primary first, legacy appended -- the order Hermes' ``get_fallback_chain``
# merges in.
_FALLBACK_KEYS = ("fallback_providers", "fallback_model")
# The non-secret routing keys an effective fallback entry is projected onto.
# Everything else in a declared entry (``api_key``, ``key_env``, ``max_tokens``,
# provider-local extras) is dropped: it is neither routing configuration nor
# something the returned profile may carry.
_FALLBACK_ENTRY_FIELDS = ("provider", "model", "base_url", "api_mode")
_REQUIRED_FALLBACK_ENTRY_FIELDS = ("provider", "model")


class HermesProfileError(RuntimeError):
    """A named Hermes profile could not be resolved to its execution fields.

    Raised for an unknown or empty profile name, a name escaping the profiles
    root, a missing/unreadable/unparseable/empty ``config.yaml``, and a
    missing, empty, or malformed bound field. Never raised as a fallback to
    ``default`` -- this resolver has no default profile.
    """


def _validated_name(name: Any) -> str:
    """A profile name that is a single, non-empty directory name."""
    if not isinstance(name, str):
        raise HermesProfileError("profile name must be a non-empty string")
    stripped = name.strip()
    if not stripped:
        raise HermesProfileError("profile name must be a non-empty string")
    if stripped in {".", ".."} or "/" in stripped or "\\" in stripped:
        raise HermesProfileError(
            f"profile name {name!r} must be a single directory name under the profiles root"
        )
    return stripped


def _load_config(profile_dir: Path, name: str) -> Mapping[str, Any]:
    """The parsed ``config.yaml`` mapping for a resolved profile directory."""
    config_path = profile_dir / _CONFIG_FILENAME
    if not config_path.is_file():
        raise HermesProfileError(f"profile {name!r} has no {_CONFIG_FILENAME} at {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise HermesProfileError(
            f"profile {name!r} {_CONFIG_FILENAME} could not be read: {exc}"
        ) from exc
    if not isinstance(raw, Mapping) or not raw:
        raise HermesProfileError(
            f"profile {name!r} {_CONFIG_FILENAME} declares no execution fields"
        )
    return raw


def _bound_string(block: Mapping[str, Any], keys: tuple[str, ...], field: str, name: str) -> str:
    """A required, non-empty string bound field declared under ``keys``."""
    for key in keys:
        if key in block:
            value = block[key]
            if not isinstance(value, str) or not value.strip():
                raise HermesProfileError(
                    f"profile {name!r} declares an empty {field!r}"
                )
            return value.strip()
    raise HermesProfileError(f"profile {name!r} declares no {field!r}")


def _normalized_base_url(value: Any) -> str:
    """A base_url normalised the way Hermes normalises it for comparison."""
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("/")


def _project_fallback_entry(entry: Mapping[str, Any], key: str, name: str) -> dict[str, Any]:
    """Project a declared fallback entry onto the non-secret routing allowlist.

    Only :data:`_FALLBACK_ENTRY_FIELDS` can appear in the result. ``provider``
    and ``model`` must be declared and non-empty; ``base_url`` / ``api_mode``
    are optional but must be strings when present. A malformed entry fails
    closed -- an entry the operator declared but the resolver dropped would make
    ``profile_revision`` blind to a fallback the runtime would actually use.
    """
    projected: dict[str, Any] = {}
    for field in _REQUIRED_FALLBACK_ENTRY_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise HermesProfileError(
                f"profile {name!r} declares a malformed {key!r} entry: expected a "
                f"non-empty string {field!r}"
            )
        projected[field] = value.strip()
    for field in _FALLBACK_ENTRY_FIELDS:
        if field in _REQUIRED_FALLBACK_ENTRY_FIELDS or field not in entry:
            continue
        value = entry[field]
        if not isinstance(value, str):
            raise HermesProfileError(
                f"profile {name!r} declares a malformed {key!r} entry: expected "
                f"{field!r} to be a string"
            )
        normalized = value.strip().rstrip("/") if field == "base_url" else value.strip()
        if normalized:
            projected[field] = normalized
    return projected


def _fallback_entry_identity(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    """Dedup identity, identical to Hermes' ``_entry_identity``."""
    return (
        str(entry.get("provider") or "").strip().lower(),
        str(entry.get("model") or "").strip().lower(),
        _normalized_base_url(entry.get("base_url")).lower(),
    )


def _declared_fallback(config: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    """The effective fallback chain, mirroring Hermes' ``get_fallback_chain``.

    ``fallback_providers`` keeps its order and legacy ``fallback_model`` entries
    are appended, deduplicated on
    ``(provider.lower(), model.lower(), normalised base_url.lower())``. A single
    declared mapping is normalised to a one-entry list; an undeclared key, or an
    explicitly empty list, contributes no entries. Every effective entry is
    projected onto :data:`_FALLBACK_ENTRY_FIELDS`; anything the chain declares
    of the wrong shape fails closed.
    """
    chain: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for key in _FALLBACK_KEYS:
        if key not in config:
            continue
        raw = config[key]
        if raw is None:
            # A declared-but-null key is an explicitly empty chain, exactly as
            # Hermes' ``_iter_fallback_entries`` reads it.
            continue
        if isinstance(raw, Mapping):
            entries = [raw] if raw else []
        elif isinstance(raw, list):
            entries = raw
        else:
            entries = None
        if entries is None:
            raise HermesProfileError(
                f"profile {name!r} declares a malformed {key!r}: expected an entry "
                "mapping or a list of entry mappings"
            )
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise HermesProfileError(
                    f"profile {name!r} declares a malformed {key!r} entry: "
                    "expected a mapping"
                )
            projected = _project_fallback_entry(entry, key, name)
            identity = _fallback_entry_identity(projected)
            if identity in seen:
                continue
            seen.add(identity)
            chain.append(projected)
    return chain


def resolve_profile(name: str, *, profiles_root: Path | str | None = None) -> dict[str, Any]:
    """Resolve a named Hermes profile's declared execution fields.

    Returns exactly the fields in :data:`PROFILE_BOUND_FIELDS`
    (``model``, ``provider``, ``base_url``, ``api_mode``, ``fallback``) read
    from ``<profiles_root>/<name>/config.yaml``. No env read, no network call,
    no model call, and no credential value.

    Raises :class:`HermesProfileError` for an unknown or empty profile name, a
    name escaping the profiles root, a missing/unreadable/unparseable/empty
    config file, or a missing/empty bound field. There is no silent fallback to
    ``default``.
    """
    profile_name = _validated_name(name)
    root = DEFAULT_PROFILES_ROOT if profiles_root is None else Path(profiles_root)
    profile_dir = root / profile_name
    if not profile_dir.is_dir():
        raise HermesProfileError(
            f"unknown profile {profile_name!r}: no profile directory at {profile_dir}"
        )
    config = _load_config(profile_dir, profile_name)

    model_block = config.get(_MODEL_BLOCK)
    if not isinstance(model_block, Mapping):
        raise HermesProfileError(
            f"profile {profile_name!r} declares no {_MODEL_BLOCK!r} block"
        )

    resolved = {
        field: _bound_string(
            model_block,
            _MODEL_NAME_KEYS if field == "model" else (field,),
            field,
            profile_name,
        )
        for field in _REQUIRED_DECLARED_FIELDS
    }
    resolved["fallback"] = _declared_fallback(config, profile_name)
    return {field: resolved[field] for field in PROFILE_BOUND_FIELDS}


def hermes_profile_revision(profile: Mapping[str, Any]) -> str:
    """Deterministic revision of a resolved Hermes profile.

    Binds exactly :data:`PROFILE_BOUND_FIELDS` through the shared
    ``canonical_json`` / ``sha256_digest`` primitives, so a semantically
    identical config (same bound values, any key order in the file) yields the
    same revision, any change to a bound field yields a different one, and an
    unbound change (a skill, a delegation or display setting, a secret) yields
    the same one.
    """
    return sha256_digest(canonical_json(profile, PROFILE_BOUND_FIELDS))
