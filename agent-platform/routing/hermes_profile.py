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
- ``fallback``  -- the declared fallback chain: ``fallback_providers`` (the
  primary key) or the legacy ``fallback_model``; a single mapping is normalised
  to a one-entry list, and an undeclared chain resolves to ``[]`` ("no declared
  fallback"), not to an error -- an absent chain is a well-defined value, unlike
  an absent model/provider/base_url/api_mode.

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
_FALLBACK_KEYS = ("fallback_providers", "fallback_model")


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


def _declared_fallback(config: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    """The declared fallback chain, as a list of fresh entry mappings.

    ``fallback_providers`` wins over the legacy ``fallback_model``. A single
    declared mapping is normalised to a one-entry list; an undeclared chain is
    the empty list. A declared-but-malformed chain fails closed.
    """
    for key in _FALLBACK_KEYS:
        if key not in config:
            continue
        raw = config[key]
        entries = [raw] if isinstance(raw, Mapping) else raw
        if not isinstance(entries, list) or not entries:
            raise HermesProfileError(
                f"profile {name!r} declares a malformed {key!r}: expected an entry "
                "mapping or a non-empty list of entry mappings"
            )
        fallback: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise HermesProfileError(
                    f"profile {name!r} declares a malformed {key!r} entry: "
                    "expected a mapping"
                )
            fallback.append(dict(entry))
        return fallback
    return []


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
