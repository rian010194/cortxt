"""The immutable execution profile and its revision (``dispatch.request.v2``, §2).

The dispatch request must bind the *execution configuration* the operator is
approving, not just identifiers. Two requests may name the same engine id yet
run different providers, models, profiles, or isolation -- and each of those
differences changes what is actually executed and paid for. ``dispatch.request.v1``
covered the routing *decision* (engine, reason, engine policy, limits) but not
the resolved provider/model/profile the worker would run under, so an approved
digest could be re-launched against a different execution configuration without
the approval noticing.

``dispatch.request.v2`` closes that by binding an ``execution_profile_revision``:
an immutable digest over the resolved execution profile. The revision is derived
from the *semantic execution fields* -- route engine, worker profile, provider,
model, and isolation -- not from transient identifiers (run_id, request_id,
timestamps), so an identical execution configuration always yields the same
revision, and any change to a bound field yields a different one.

Canonicalisation rule (shared with the request digest):

- select exactly the bound keys, in a fixed order;
- serialise with ``json.dumps(..., sort_keys=True, separators=(",", ":"),
  default=str)`` so nested maps sort keys deterministically, ``None`` renders
  as ``null`` (a present-but-empty bound field is distinct from an absent one),
  and non-JSON values fall back to ``str``;
- the digest is ``"sha256:" + sha256(utf8(canonical)).hexdigest()``.

Nothing here reads credentials or env: the caller passes the already-resolved,
non-secret provider/model *identifiers* (the same class the routing manifest and
the launcher preflight treat as routing configuration, never credential values).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# The execution-profile fields the revision binds. Field order is load-bearing
# for the canonical serialisation; keep it fixed.
EXECUTION_PROFILE_FIELDS = (
    "engine_id",
    "worker_role",
    "provider",
    "model",
    "isolation",
)

DEFAULT_ISOLATION = "worktree"


def canonical_json(payload: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    """Deterministic JSON for the named ``fields`` of ``payload``.

    Two payloads with the same meaning for every bound field produce identical
    output (so identical digests); a change in any bound field changes it.
    Keys are selected and sorted, separators are compact, and non-JSON values
    fall back to ``str``.
    """
    return json.dumps(
        {key: payload.get(key) for key in fields},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_digest(canonical: str) -> str:
    """``sha256:``-prefixed hex digest of the canonical UTF-8 bytes."""
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execution_profile(
    *,
    engine_id: str,
    worker_role: str | None,
    provider: str | None = None,
    model: str | None = None,
    isolation: str = DEFAULT_ISOLATION,
) -> dict[str, Any]:
    """The canonical execution-profile projection for one dispatch.

    ``provider`` and ``model`` are resolved, non-secret execution identifiers
    (e.g. ``nous`` / ``deepseek-v4-flash-0731``); ``None`` means "not resolved
    at projection time" and is itself bound -- an execution profile whose model
    is unknown is a different (less constrained) approval than one that names a
    model. ``isolation`` mirrors the approved artifact policy's requirement.
    """
    return {
        "engine_id": engine_id,
        "worker_role": worker_role,
        "provider": provider,
        "model": model,
        "isolation": isolation,
    }


def execution_profile_revision(profile: Mapping[str, Any]) -> str:
    """Immutable revision of an execution profile (``dispatch.request.v2`` §2).

    Deterministic across identical execution configurations; any change to a
    bound execution field (route engine, worker profile, provider, model, or
    isolation) changes the revision. This is the value the request digest binds
    so an approval cannot silently ride a different execution configuration.
    """
    return sha256_digest(canonical_json(profile, EXECUTION_PROFILE_FIELDS))


# Non-secret routing environment variables that resolve the provider/model an
# engine will run under, read at the confirm/launch boundary (M2 #564) so the
# v2 digest can bind them. They are the same routing configuration the engine's
# own worker adapter reads at invocation (see runtime/adapters/dsh_adapter.py
# and hermes_free_adapter.py) -- identifiers, never credential values. An
# engine with no explicit env-resolved config (the platform provider gateway
# or an SDK/vendor default) has no entry here and resolves to (None, None),
# which the v2 digest binds as "not resolved at projection time".
_EXECUTION_CONFIG_ENV: dict[str, tuple[str, str]] = {
    "dsh": ("CORTXT_DSH_PROVIDER", "CORTXT_DSH_MODEL"),
    "hermes-free": ("CORTXT_FREE_PROVIDER", "CORTXT_FREE_MODEL"),
}


def resolve_execution_config(engine_id: str) -> tuple[str | None, str | None]:
    """Resolve the non-secret ``(provider, model)`` routing identifiers for an
    engine at the confirm/launch boundary (``dispatch.request.v2``, M2 #564).

    Returns exactly the identifiers ``build_dispatch_request_v2`` should bind
    via ``execution_profile_revision``: what the engine's worker adapter would
    actually read from the routing environment. A change to either value between
    confirmation and launch therefore changes the request digest and the launch
    is refused as stale (the confirmation no longer binds the configuration).

    An engine without an env-resolved config returns ``(None, None)``, which is
    itself bound as "not resolved". Never reads or reports credential values.
    """
    import os

    pair = _EXECUTION_CONFIG_ENV.get(engine_id)
    if pair is None:
        return None, None
    return os.environ.get(pair[0]), os.environ.get(pair[1])
