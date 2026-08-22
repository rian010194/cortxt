"""Read and normalize injected operational stores."""

from copy import deepcopy
from typing import Any, Callable, Mapping

from ..registry import TYPES
from ..validation import validate


class ReadAdapterError(ValueError):
    pass


_SNAPSHOT_FIELDS = ("schema_version", "generated_at", "orchestrator", "workstreams", "sessions", "activity")


def read_snapshot_v2(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the safe schema-v2 compatibility projection."""
    result = {key: deepcopy(snapshot[key]) for key in _SNAPSHOT_FIELDS if key in snapshot}
    try:
        validate(result, TYPES["sessions.snapshot.v2"].schema)
    except ValueError as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_active_runs_v1(store: Mapping[str, Any]) -> dict[str, Any]:
    runs = store.get("runs")
    if not isinstance(runs, list):
        raise ReadAdapterError("active-runs store must contain a runs array")
    safe_runs = []
    allowed = ("run_id", "issue_number", "status", "started_at", "updated_at")
    for run in runs:
        if not isinstance(run, dict):
            raise ReadAdapterError("run must be an object")
        safe_runs.append({key: deepcopy(run[key]) for key in allowed if key in run})
    result = {"schema_version": 1, "runs": safe_runs}
    validate(result, TYPES["dispatcher.active-runs.v1"].schema)
    return result


def read_execution_map_v1(plan: Callable[[Mapping[str, Any]], Mapping[str, Any]],
                          store: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the content-free execution-map projection and validate it.

    `plan` is the injected projection callable (e.g. scripts/execution_map.py's
    `plan_from_json`); the adapter keeps the widget contract independent of
    scripts/ and stays network-free and mutation-free.
    """
    result = plan(dict(store))
    if not isinstance(result, dict):
        raise ReadAdapterError("execution-map plan must produce an object")
    try:
        validate(result, TYPES["execution-map.plan.v1"].schema)
    except ValueError as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result
