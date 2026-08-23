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


def read_docker_status_v1(projection_or_store: Any) -> dict[str, Any]:
    """Produce the safe docker-status projection and validate it."""
    if callable(projection_or_store):
        raw = projection_or_store()
    elif isinstance(projection_or_store, Mapping):
        raw = projection_or_store
    else:
        raise ReadAdapterError("docker-status store must be an object or callable")

    if not isinstance(raw, Mapping):
        raise ReadAdapterError("docker-status raw data must be an object")

    containers_raw = raw.get("containers")
    if not isinstance(containers_raw, list):
        raise ReadAdapterError("docker-status store must contain a containers array")

    safe_containers = []
    allowed_container_keys = ("id", "name", "image", "status")
    for container in containers_raw:
        if not isinstance(container, dict):
            raise ReadAdapterError("container must be an object")
        safe_containers.append({key: deepcopy(container[key]) for key in allowed_container_keys if key in container})

    images_raw = raw.get("images")
    if not isinstance(images_raw, list):
        raise ReadAdapterError("docker-status store must contain an images array")
    safe_images = []
    for img in images_raw:
        if not isinstance(img, str):
            raise ReadAdapterError("image must be a string")
        safe_images.append(img)

    engine_raw = raw.get("engine")
    if not isinstance(engine_raw, dict):
        raise ReadAdapterError("engine must be an object")

    total_containers = raw.get("total_containers")
    running_containers = raw.get("running_containers")

    result = {
        "schema_version": 1,
        "engine": deepcopy(engine_raw),
        "containers": safe_containers,
        "images": safe_images,
        "total_containers": total_containers,
        "running_containers": running_containers,
    }
    try:
        validate(result, TYPES["docker.status.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result

