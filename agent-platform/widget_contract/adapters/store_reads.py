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


def redact_hook(hook: Mapping[str, Any]) -> dict[str, Any]:
    """Return a safe projection of a GitHub hook row without secrets or extra config."""
    if not isinstance(hook, Mapping):
        raise ReadAdapterError("hook row must be an object")
    url = ""
    if "config" in hook and isinstance(hook["config"], Mapping):
        url = str(hook["config"].get("url") or "")
    if not url and "url" in hook:
        url = str(hook["url"] or "")
    events = hook.get("events", [])
    if not isinstance(events, list):
        raise ReadAdapterError("hook events must be a list")
    raw_id = hook.get("id")
    if not isinstance(raw_id, int) or isinstance(raw_id, bool):
        raise ReadAdapterError("hook id must be an integer")
    raw_active = hook.get("active")
    if not isinstance(raw_active, bool):
        raise ReadAdapterError("hook active must be a boolean")
    return {
        "id": raw_id,
        "url": url,
        "events": [str(e) for e in events],
        "active": raw_active,
    }


def read_webhooks_status_v1(store: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the safe content-free webhooks status projection and validate it."""
    if not isinstance(store, Mapping):
        raise ReadAdapterError("webhooks store must be an object")
    hooks_raw = store.get("hooks")
    if not isinstance(hooks_raw, list):
        raise ReadAdapterError("webhooks store must contain a hooks array")
    safe_hooks = [redact_hook(h) for h in hooks_raw]
    repo = store.get("repo", "")
    if not isinstance(repo, str):
        raise ReadAdapterError("webhooks store repo must be a string")
    total = store.get("total", len(safe_hooks))
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ReadAdapterError("webhooks store total must be a non-negative integer")
    active = store.get("active", sum(1 for h in safe_hooks if h.get("active")))
    if not isinstance(active, int) or isinstance(active, bool) or active < 0:
        raise ReadAdapterError("webhooks store active must be a non-negative integer")
    result = {
        "schema_version": 1,
        "repo": repo,
        "total": total,
        "active": active,
        "hooks": safe_hooks,
    }
    try:
        validate(result, TYPES["webhooks.status.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_pages_deploys_v1(store: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the safe content-free pages deploys projection and validate it."""
    if not isinstance(store, Mapping):
        raise ReadAdapterError("pages deploys store must be an object")
    project = store.get("project", "")
    if not isinstance(project, str):
        raise ReadAdapterError("pages deploys project must be a string")
    account = store.get("account", "")
    if not isinstance(account, str):
        raise ReadAdapterError("pages deploys account must be a string")
    latest_raw = store.get("latest")
    if not isinstance(latest_raw, Mapping):
        raise ReadAdapterError("pages deploys store must contain a latest object")
    latest = {
        "id": str(latest_raw.get("id", "")),
        "environment": str(latest_raw.get("environment", "")),
        "created_on": str(latest_raw.get("created_on", "")),
        "stage": str(latest_raw.get("stage", "")),
        "status": str(latest_raw.get("status", "")),
    }
    deployments_raw = store.get("deployments")
    if not isinstance(deployments_raw, list):
        raise ReadAdapterError("pages deploys store must contain a deployments array")
    safe_deployments = []
    for dep in deployments_raw:
        if not isinstance(dep, Mapping):
            raise ReadAdapterError("deployment row must be an object")
        safe_deployments.append({
            "id": str(dep.get("id", "")),
            "environment": str(dep.get("environment", "")),
            "created_on": str(dep.get("created_on", "")),
            "stage": str(dep.get("stage", "")),
        })
    result = {
        "schema_version": 1,
        "project": project,
        "account": account,
        "latest": latest,
        "deployments": safe_deployments,
    }
    try:
        validate(result, TYPES["pages.deploys.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result
