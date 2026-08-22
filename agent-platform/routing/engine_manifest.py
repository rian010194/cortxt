"""Phase 3 v0.1: engine-agnostic capability manifest and deterministic routing.

ADR-022 (`docs/adr/022-fas3-capability-manifest-and-engine-selection-criteria.md`)
resolves ADR-019's open engine-selection-criteria item with a narrow, verifiable
slice: a manifest an engine declares itself with, and a deterministic
`route()` that picks among them. This is a deliberate bootstrap toward
target-architecture.md §29.5's Geometric Reasoning RLM successor (see that
ADR's Context note) -- not a competing permanent mechanism. When that engine
is ready, it replaces `route()`'s role; it does not extend it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

COST_ORDER = {"free": 0, "cheap": 1, "metered": 2}
VALID_COST_CLASSES = frozenset(COST_ORDER)
VALID_RELIABILITY_CLASSES = frozenset({"verified", "unverified", "degraded"})

DEFAULT_FALLBACK_ENGINE = "claude-direct"


class InvalidManifestError(ValueError):
    pass


@dataclass(frozen=True)
class EngineManifest:
    """One engine's self-declared capability, per ADR-022's manifest shape.

    `task_shapes` are free tags supplied by the caller, not inferred (same
    "typed from above, not a platform contract yet" stance as the Phase 3
    research doc's capability tags). `reliability_class` is set by hand --
    v0.1 has no learned/dynamic scoring, per ADR-022's explicit deferral.
    `checkpoint_required` defaults to `True` — an engine is only exempted once
    a proof step or track-specific evidence justifies unattended multi-step runs
    (none does yet, so nothing sets it to `False` today).
    """

    engine_id: str
    task_shapes: tuple[str, ...]
    cost_class: str
    reliability_class: str
    notes: str = ""
    checkpoint_required: bool = True

    def __post_init__(self) -> None:
        if not self.engine_id:
            raise InvalidManifestError("engine_id must be a non-empty string")
        if self.cost_class not in VALID_COST_CLASSES:
            raise InvalidManifestError(
                f"cost_class must be one of {sorted(VALID_COST_CLASSES)}, got {self.cost_class!r}"
            )
        if self.reliability_class not in VALID_RELIABILITY_CLASSES:
            raise InvalidManifestError(
                f"reliability_class must be one of {sorted(VALID_RELIABILITY_CLASSES)}, "
                f"got {self.reliability_class!r}"
            )


@dataclass(frozen=True)
class EngineChoice:
    """route()'s result: which engine, why, and who else was considered."""

    engine_id: str
    reason: str
    matched_tag: str | None = None
    excluded: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    checkpoint_required: bool = True


DEFAULT_MANIFESTS: tuple[EngineManifest, ...] = (
    EngineManifest(
        engine_id="claude-direct",
        task_shapes=("general", "review", "adr-drafting", "widget-ui", "cli", "security-sensitive"),
        cost_class="metered",
        reliability_class="verified",
        notes="Phase 2/ADR-022 bootstrap fallback: the only engine that finished "
        "Phase 2 (issue #166) without an off-track dispatch or a wasted iteration budget.",
    ),
    EngineManifest(
        engine_id="hermes",
        task_shapes=("research", "background-task", "parallel-dispatch"),
        cost_class="cheap",
        reliability_class="unverified",
        notes="Two Phase 2 dispatch attempts (issue #165, #166) missed the target -- "
        "one exhausted its iteration budget, the other wired the wrong widget surface "
        "and added an unjustified HTTP server despite an explicit issue describing "
        "exactly what to avoid. Reliable for research/background dispatch; not yet "
        "verified for specification-heavy build tasks. Reassess (see ADR-022 §Expiry).",
    ),
    EngineManifest(
        engine_id="hermes-free",
        task_shapes=("research", "background-task"),
        cost_class="free",
        reliability_class="unverified",
        notes="Free-tier route via Hermes CLI overrides (CORTXT_FREE_MODEL / CORTXT_FREE_PROVIDER); "
        "quota/availability varies by provider. Selected for research/background-task over dsh/hermes "
        "(free < cheap). Reassess once a live free-tier run has verified quality.",
    ),
    EngineManifest(
        engine_id="dsh",
        task_shapes=("research", "background-task"),
        cost_class="cheap",
        reliability_class="unverified",
        notes="DSH-integration experiment (lab/dsh-integration): the DeepSeek Harness "
        "Python-SDK adapter (routing.dsh_invoker + runtime/adapters/dsh_adapter) is "
        "registered and live-proved end-to-end (2026-08-21: invoke_dsh against "
        "nous/deepseek-v4-flash-0731 via the node runtime carrier, finish_reason=completed). "
        "Takes research/background-task over hermes on the cheap tie-break (engine_id "
        "'dsh' < 'hermes'); hermes keeps parallel-dispatch. Reassess once a real "
        "workflow:ready dispatch has run (see ADR-022 §Expiry).",
    ),
)


def route(
    task_tags: list[str],
    manifests: list[EngineManifest] | tuple[EngineManifest, ...],
    fallback: str = DEFAULT_FALLBACK_ENGINE,
) -> EngineChoice:
    """Pick an engine for a task tagged with `task_tags`.

    Candidates are manifests whose `task_shapes` intersect `task_tags` and
    whose `reliability_class` isn't `degraded`. Among candidates, cheapest
    `cost_class` wins; ties break on `engine_id` for determinism. A
    `degraded` engine that would otherwise have matched is reported in
    `excluded`, not silently dropped. No candidate -> deterministic fallback,
    reason logged rather than assumed.
    """
    if not task_tags:
        raise ValueError("task_tags must be non-empty")

    tag_set = set(task_tags)
    candidates: list[tuple[EngineManifest, str]] = []
    excluded: list[tuple[str, str]] = []

    for manifest in manifests:
        matched = tag_set & set(manifest.task_shapes)
        if not matched:
            continue
        if manifest.reliability_class == "degraded":
            excluded.append((manifest.engine_id, f"degraded (matched tag(s): {sorted(matched)})"))
            continue
        candidates.append((manifest, sorted(matched)[0]))

    if not candidates:
        return EngineChoice(
            engine_id=fallback,
            reason=f"no engine matched task_tags={sorted(tag_set)}; falling back to default",
            matched_tag=None,
            excluded=tuple(excluded),
            checkpoint_required=True,
        )

    candidates.sort(key=lambda pair: (COST_ORDER[pair[0].cost_class], pair[0].engine_id))
    winner, matched_tag = candidates[0]
    return EngineChoice(
        engine_id=winner.engine_id,
        reason=f"matched tag {matched_tag!r}, cheapest of {len(candidates)} candidate(s)",
        matched_tag=matched_tag,
        excluded=tuple(excluded),
        checkpoint_required=winner.checkpoint_required,
    )
