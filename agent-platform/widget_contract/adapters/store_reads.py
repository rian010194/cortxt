"""Read and normalize injected operational stores."""

from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from ..registry import TYPES
from ..validation import validate
from ..run_authority import (
    correlate_run_summaries,
    run_summaries_projection,
    summaries_from_sessions,
)
from ..detail import build_workstream_detail_v1
from ..dispatch_request import build_dispatch_request_v1


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


def read_usage_cost_v1(projection_or_store: Any) -> dict[str, Any]:
    """Produce the safe content-free usage and cost projection and validate it."""
    if callable(projection_or_store):
        raw = projection_or_store()
    elif isinstance(projection_or_store, Mapping):
        raw = projection_or_store
    else:
        raise ReadAdapterError("usage-cost store must be an object or callable")

    if not isinstance(raw, Mapping):
        raise ReadAdapterError("usage-cost raw data must be an object")

    period = str(raw.get("period", "current"))
    runtimes_raw = raw.get("runtimes")
    if not isinstance(runtimes_raw, list):
        raise ReadAdapterError("usage-cost store must contain a runtimes array")

    safe_runtimes = []
    allowed_runtime_keys = ("id", "name", "tokens_in", "tokens_out", "cost_usd", "model", "tokens")
    for r in runtimes_raw:
        if not isinstance(r, Mapping):
            raise ReadAdapterError("runtime row must be an object")
        for req in ("id", "name", "tokens_in", "tokens_out", "cost_usd", "model"):
            if req not in r:
                raise ReadAdapterError(f"runtime row missing required field: {req}")
        t_in = r["tokens_in"]
        t_out = r["tokens_out"]
        cost = r["cost_usd"]
        if not isinstance(t_in, int) or isinstance(t_in, bool) or t_in < 0:
            raise ReadAdapterError("runtime tokens_in must be a non-negative integer")
        if not isinstance(t_out, int) or isinstance(t_out, bool) or t_out < 0:
            raise ReadAdapterError("runtime tokens_out must be a non-negative integer")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
            raise ReadAdapterError("runtime cost_usd must be a non-negative number")
        total_tok = r.get("tokens", t_in + t_out)
        if not isinstance(total_tok, int) or isinstance(total_tok, bool) or total_tok < 0:
            raise ReadAdapterError("runtime tokens must be a non-negative integer")
        row = {
            "id": str(r["id"]),
            "name": str(r["name"]),
            "tokens_in": t_in,
            "tokens_out": t_out,
            "cost_usd": float(cost),
            "model": str(r["model"]),
            "tokens": total_tok,
        }
        safe_runtimes.append(row)

    history_raw = raw.get("history")
    if not isinstance(history_raw, list):
        raise ReadAdapterError("usage-cost store must contain a history array")

    safe_history = []
    for h in history_raw:
        if not isinstance(h, Mapping):
            raise ReadAdapterError("history point must be an object")
        for req in ("at", "tokens", "cost_usd"):
            if req not in h:
                raise ReadAdapterError(f"history point missing required field: {req}")
        h_tok = h["tokens"]
        h_cost = h["cost_usd"]
        if not isinstance(h_tok, int) or isinstance(h_tok, bool) or h_tok < 0:
            raise ReadAdapterError("history tokens must be a non-negative integer")
        if not isinstance(h_cost, (int, float)) or isinstance(h_cost, bool) or h_cost < 0:
            raise ReadAdapterError("history cost_usd must be a non-negative number")
        safe_history.append({
            "at": str(h["at"]),
            "tokens": h_tok,
            "cost_usd": float(h_cost),
        })

    raw_total_tokens = raw.get("total_tokens")
    if raw_total_tokens is not None:
        if not isinstance(raw_total_tokens, int) or isinstance(raw_total_tokens, bool) or raw_total_tokens < 0:
            raise ReadAdapterError("total_tokens must be a non-negative integer")
        total_tokens = raw_total_tokens
    else:
        total_tokens = sum(r["tokens"] for r in safe_runtimes)

    raw_total_cost = raw.get("total_cost_usd")
    if raw_total_cost is not None:
        if not isinstance(raw_total_cost, (int, float)) or isinstance(raw_total_cost, bool) or raw_total_cost < 0:
            raise ReadAdapterError("total_cost_usd must be a non-negative number")
        total_cost_usd = float(raw_total_cost)
    else:
        total_cost_usd = sum(r["cost_usd"] for r in safe_runtimes)

    result = {
        "schema_version": 1,
        "period": period,
        "total_cost_usd": total_cost_usd,
        "total_tokens": total_tokens,
        "runtimes": safe_runtimes,
        "history": safe_history,
        "runtime_tokens": [r["tokens"] for r in safe_runtimes],
        "runtime_names": [r["name"] for r in safe_runtimes],
        "model_costs": [r["cost_usd"] for r in safe_runtimes],
        "model_names": [r["model"] for r in safe_runtimes],
        "history_tokens": [h["tokens"] for h in safe_history],
        "history_points": [h["at"] for h in safe_history],
        "history_costs": [h["cost_usd"] for h in safe_history],
    }

    try:
        validate(result, TYPES["usage-cost.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_session_agents_v1(projection_or_store: Any) -> dict[str, Any]:
    """Produce the safe session-agents projection and validate it."""
    if callable(projection_or_store):
        raw = projection_or_store()
    elif isinstance(projection_or_store, Mapping):
        raw = projection_or_store
    else:
        raise ReadAdapterError("session-agents store must be an object or callable")

    if not isinstance(raw, Mapping):
        raise ReadAdapterError("session-agents raw data must be an object")

    agents_raw = raw.get("agents")
    if not isinstance(agents_raw, list):
        raise ReadAdapterError("session-agents store must contain an agents array")

    safe_agents = []
    allowed_agent_keys = ("id", "name", "runtime", "status", "current_task", "tasks")
    allowed_task_keys = ("id", "title", "state", "progress")

    for agent in agents_raw:
        if not isinstance(agent, Mapping):
            raise ReadAdapterError("agent row must be an object")
        tasks_raw = agent.get("tasks")
        if not isinstance(tasks_raw, list):
            raise ReadAdapterError("agent tasks must be a list")
        safe_tasks = []
        for task in tasks_raw:
            if not isinstance(task, Mapping):
                raise ReadAdapterError("task item must be an object")
            safe_task = {k: deepcopy(task[k]) for k in allowed_task_keys if k in task}
            safe_tasks.append(safe_task)

        safe_agent = {k: deepcopy(agent[k]) for k in allowed_agent_keys if k in agent and k != "tasks"}
        safe_agent["tasks"] = safe_tasks
        safe_agents.append(safe_agent)

    result = {
        "schema_version": 1,
        "agents": safe_agents,
    }
    try:
        validate(result, TYPES["session-agents.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_workstream_summary_v1(store: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the safe Workstream summary projection and validate it."""
    if not isinstance(store, Mapping):
        raise ReadAdapterError("workstream-summary store must be an object")
    required = ("issue_id", "title", "outcome", "workflow", "pending_decision",
                "mandate", "gates", "run_continuity")
    for key in required:
        if key not in store:
            raise ReadAdapterError(f"workstream-summary store missing required field: {key}")
    mandate_raw = store["mandate"]
    if not isinstance(mandate_raw, Mapping):
        raise ReadAdapterError("workstream-summary mandate must be an object")
    mandate_allowed = ("mandate_id", "granted_by", "allowed_tools", "data_class_max",
                       "budget_usd_max", "max_runtime_seconds", "expires_at")
    for key in mandate_allowed:
        if key not in mandate_raw:
            raise ReadAdapterError(f"workstream-summary mandate missing required field: {key}")
    gates_raw = store["gates"]
    if not isinstance(gates_raw, list):
        raise ReadAdapterError("workstream-summary gates must be an array")
    gates = []
    for g in gates_raw:
        for key in ("domain", "status", "label", "detail"):
            if key not in g:
                raise ReadAdapterError(f"workstream-summary gate missing required field: {key}")
        gates.append({"domain": str(g["domain"]), "status": str(g["status"]),
                      "label": str(g["label"]), "detail": str(g["detail"])})
    continuity_raw = store["run_continuity"]
    if not isinstance(continuity_raw, Mapping) or "authority" not in continuity_raw or "current_run" not in continuity_raw:
        raise ReadAdapterError("workstream-summary run_continuity must have authority and current_run")
    authority_raw = continuity_raw["authority"]
    for key in ("mandate_id", "granted_by", "replacement_policy", "dispatched_by"):
        if key not in authority_raw:
            raise ReadAdapterError(f"workstream-summary run_continuity authority missing field: {key}")
    current_raw = continuity_raw["current_run"]
    previous_raw = continuity_raw.get("previous_run")
    result = {
        "issue_id": str(store["issue_id"]),
        "title": str(store["title"]),
        "outcome": str(store["outcome"]),
        "workflow": str(store["workflow"]),
        "pending_decision": bool(store["pending_decision"]),
        "mandate": {
            "mandate_id": str(mandate_raw["mandate_id"]),
            "granted_by": str(mandate_raw["granted_by"]),
            "allowed_tools": [str(t) for t in mandate_raw["allowed_tools"]],
            "data_class_max": str(mandate_raw["data_class_max"]),
            "budget_usd_max": float(mandate_raw["budget_usd_max"]),
            "max_runtime_seconds": int(mandate_raw["max_runtime_seconds"]),
            "expires_at": str(mandate_raw["expires_at"]),
        },
        "gates": gates,
        "run_continuity": {
            "authority": {
                "mandate_id": str(authority_raw["mandate_id"]),
                "granted_by": str(authority_raw["granted_by"]),
                "replacement_policy": str(authority_raw["replacement_policy"]),
                "dispatched_by": str(authority_raw["dispatched_by"]),
            },
            "current_run": {"run_id": str(current_raw["run_id"]), "engine": str(current_raw["engine"])},
            "previous_run": None if previous_raw is None else {
                "run_id": str(previous_raw["run_id"]), "engine": str(previous_raw["engine"]),
                "status": str(previous_raw.get("status", "")),
            },
        },
    }
    try:
        validate(result, TYPES["workstream.summary.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_attention_queue_v1(store: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the safe attention-queue projection and validate it."""
    if not isinstance(store, Mapping):
        raise ReadAdapterError("attention-queue store must be an object")
    if "items" not in store or not isinstance(store["items"], list):
        raise ReadAdapterError("attention-queue store missing items array")
    items = []
    for raw in store["items"]:
        if not isinstance(raw, Mapping):
            raise ReadAdapterError("attention-queue item must be an object")
        required = ("workstream_id", "kind", "summary", "issue_id")
        for key in required:
            if key not in raw:
                raise ReadAdapterError(f"attention-queue item missing required field: {key}")
        items.append({
            "workstream_id": str(raw["workstream_id"]),
            "kind": str(raw["kind"]),
            "summary": str(raw["summary"]),
            "issue_id": str(raw["issue_id"]),
        })
    result = {"items": items}
    try:
        validate(result, TYPES["attention.queue.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_evidence_comparison_v1(store: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the safe two-runs evidence-comparison projection and validate it."""
    if not isinstance(store, Mapping):
        raise ReadAdapterError("evidence-comparison store must be an object")
    if "issue_id" not in store:
        raise ReadAdapterError("evidence-comparison store missing required field: issue_id")
    runs_raw = store.get("runs")
    if not isinstance(runs_raw, list):
        raise ReadAdapterError("evidence-comparison store must contain a runs array")
    required_run_keys = ("run_id", "engine", "status", "evidence", "artifacts",
                         "artifacts_present", "artifacts_missing", "independently_reviewed", "accepted")
    safe_runs = []
    for run in runs_raw:
        if not isinstance(run, Mapping):
            raise ReadAdapterError("evidence run must be an object")
        for key in required_run_keys:
            if key not in run:
                raise ReadAdapterError(f"evidence run missing required field: {key}")
        safe_runs.append({
            "run_id": str(run["run_id"]),
            "engine": str(run["engine"]),
            "status": str(run["status"]),
            "evidence": [str(e) for e in run["evidence"]],
            "artifacts": [str(a) for a in run["artifacts"]],
            "artifacts_present": bool(run["artifacts_present"]),
            "artifacts_missing": [str(a) for a in run["artifacts_missing"]],
            "independently_reviewed": bool(run["independently_reviewed"]),
            "accepted": bool(run["accepted"]),
        })
    result = {"issue_id": str(store["issue_id"]), "runs": safe_runs}
    try:
        validate(result, TYPES["evidence.comparison.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_decision_pending_v1(store: Mapping[str, Any]) -> dict[str, Any]:
    """Produce the safe pending-decision projection and validate it."""
    if not isinstance(store, Mapping):
        raise ReadAdapterError("decision-pending store must be an object")
    required = ("issue_id", "workflow", "summary", "actionable")
    for key in required:
        if key not in store:
            raise ReadAdapterError(f"decision-pending store missing required field: {key}")
    result = {
        "issue_id": str(store["issue_id"]),
        "workflow": str(store["workflow"]),
        "summary": str(store["summary"]),
        "actionable": bool(store["actionable"]),
    }
    try:
        validate(result, TYPES["decision.pending.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_run_summaries_v1(issue_ref: str,
                          dispatcher_store: Mapping[str, Any] | None,
                          session_docs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Correlate Runs from the dispatcher runs.json and the session-event store.

    Provenance-preserving (S7a #470): conflicting statuses on the same run_id
    are rendered as a ``conflict`` record, never silently merged. Validates the
    result against ``run.summaries.v1``.
    """
    dispatcher_runs = dispatcher_store if isinstance(dispatcher_store, Mapping) else {}
    sessions = list(session_docs) if session_docs is not None else []
    summaries = correlate_run_summaries(
        issue_ref, dispatcher_runs, summaries_from_sessions(sessions, issue_ref))
    result = run_summaries_projection(issue_ref, summaries)
    try:
        validate(result, TYPES["run.summaries.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_workstream_detail_v1(issue: Mapping[str, Any],
                              runs: Sequence[Mapping[str, Any]],
                              *,
                              repo: str,
                              status: str = "fresh",
                              error: Mapping[str, Any] | None = None,
                              age_seconds: int = 0,
                              synthetic: bool = False) -> dict[str, Any]:
    """Build and validate the versioned Workstream detail projection."""
    result = build_workstream_detail_v1(
        issue, runs, repo=repo, status=status, error=error,
        age_seconds=age_seconds, synthetic=synthetic)
    try:
        validate(result, TYPES["workstream.detail.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result


def read_dispatch_request_v1(issue: Mapping[str, Any],
                             choice: Any,
                             *,
                             repo: str,
                             engine_registered: bool = True,
                             routable_tags: Sequence[str] | None = None) -> dict[str, Any]:
    """Build and validate the versioned dispatch-request projection."""
    result = build_dispatch_request_v1(
        issue, choice, repo=repo, engine_registered=engine_registered,
        routable_tags=routable_tags)
    try:
        validate(result, TYPES["dispatch.request.v1"].schema)
    except Exception as exc:
        raise ReadAdapterError(str(exc)) from exc
    return result

