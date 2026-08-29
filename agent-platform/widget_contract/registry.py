"""Closed registries for widget operations, types, primitives, and ports."""

from dataclasses import dataclass
from typing import Any, Mapping


JSON_OBJECT = {"type": "object", "additionalProperties": False, "properties": {}}


@dataclass(frozen=True)
class ReadOperation:
    source: str
    input_schema: Mapping[str, Any]
    output_type: str
    data_class: str
    timeout_ms: int
    rate_limit_per_minute: int
    cache_ttl_seconds: int
    capability: str
    declared_only: bool = False


@dataclass(frozen=True)
class TypeEntry:
    schema: Mapping[str, Any]
    data_class: str


@dataclass(frozen=True)
class PrimitiveEntry:
    props: frozenset[str]
    bindings: Mapping[str, str]
    empty_state: str
    error_state: str
    input_primitive: bool = False


@dataclass(frozen=True)
class ActionEntry:
    port: str
    input_schema: Mapping[str, Any]
    result_type: str
    effect_class: str
    authorization_modes: frozenset[str]
    capability: str
    retryable: bool = False


SNAPSHOT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "generated_at", "orchestrator", "workstreams", "sessions", "activity"],
    "properties": {"schema_version": {"const": 2}, "generated_at": {"type": "string"}, "orchestrator": {"type": "object"}, "workstreams": {"type": "array"}, "sessions": {"type": "array"}, "activity": {"type": "array"}},
}
ACTIVE_RUNS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "runs"], "properties": {"schema_version": {"const": 1}, "runs": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["run_id", "status"], "properties": {"run_id": {"type": "string"}, "issue_number": {"type": "integer"}, "status": {"type": "string"}, "started_at": {"type": "string"}, "updated_at": {"type": "string"}}}}}}
ISSUES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "issues"], "properties": {"schema_version": {"const": 1}, "issues": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["number", "title", "state", "workflow"], "properties": {"number": {"type": "integer"}, "title": {"type": "string"}, "state": {"type": "string"}, "workflow": {"type": "string"}}}}}}
ALL_OPEN_ISSUES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "complete", "issues"], "properties": {"schema_version": {"const": 1}, "complete": {"const": True}, "issues": {"type": "array"}}}
CANDIDATE_DEPENDENCY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["relation", "target", "target_status", "target_title"], "properties": {"relation": {"type": "string"}, "target": {"type": "integer"}, "target_status": {"type": "string"}, "target_title": {"type": ["string", "null"]}}}
CANDIDATE_ROW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["number", "title", "workflow", "area", "milestone", "url", "open_blocker_count", "dependencies", "violations"], "properties": {"number": {"type": "integer"}, "title": {"type": "string"}, "workflow": {"type": "string"}, "area": {"type": ["string", "null"]}, "milestone": {"type": ["string", "null"]}, "url": {"type": ["string", "null"]}, "open_blocker_count": {"type": "integer", "minimum": 0}, "dependencies": {"type": "array", "items": CANDIDATE_DEPENDENCY_SCHEMA}, "violations": {"type": "array", "items": {"type": "string"}}}}
CANDIDATES_VIEW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "source", "total", "groups", "handoffs"], "properties": {"schema_version": {"const": 1}, "source": {"type": "object", "additionalProperties": False, "required": ["complete", "status", "age_seconds", "error"], "properties": {"complete": {"type": "boolean"}, "status": {"enum": ["fresh", "stale", "error"]}, "age_seconds": {"type": "integer", "minimum": 0}, "error": {"type": ["object", "null"], "additionalProperties": False, "required": ["kind", "message"], "properties": {"kind": {"type": "string"}, "message": {"type": "string"}}}}}, "total": {"type": "integer", "minimum": 0}, "groups": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "count", "rows"], "properties": {"id": {"type": "string"}, "count": {"type": "integer", "minimum": 0}, "rows": {"type": "array", "items": CANDIDATE_ROW_SCHEMA}}}}, "handoffs": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "enabled", "reason"], "properties": {"id": {"type": "string"}, "enabled": {"type": "boolean"}, "reason": {"type": "string"}, "operation": {"type": "string"}, "port": {"type": "string"}, "effect_class": {"type": "string"}, "authorization": {"type": "object"}, "confirm": {"type": "object"}}}}}}
EXECUTION_MAP_ISSUE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "wave", "blockers", "drift_codes", "launchable"], "properties": {"id": {"type": "string"}, "wave": {"type": ["integer", "null"]}, "blockers": {"type": "array", "items": {"type": "string"}}, "drift_codes": {"type": "array", "items": {"type": "string"}}, "launchable": {"type": "boolean"}}}
EXECUTION_MAP_CLAIM_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["claim_id", "issue_id", "run_id", "state", "lease_expires_at", "driver_id"], "properties": {"claim_id": {"type": "string"}, "issue_id": {"type": "string"}, "run_id": {"type": "string"}, "state": {"type": "string"}, "lease_expires_at": {"type": ["number", "null"]}, "driver_id": {"type": "string"}}}
EXECUTION_MAP_PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["role", "issues", "waves", "claims", "collision_codes"], "properties": {"role": {"type": "string"}, "issues": {"type": "array", "items": EXECUTION_MAP_ISSUE_SCHEMA}, "waves": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}, "claims": {"type": "array", "items": EXECUTION_MAP_CLAIM_SCHEMA}, "collision_codes": {"type": "array", "items": {"type": "string"}}}}
DOCKER_CONTAINER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "name", "image", "status"], "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "image": {"type": "string"}, "status": {"type": "string"}}}
DOCKER_STATUS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "engine", "containers", "images", "total_containers", "running_containers"], "properties": {"schema_version": {"const": 1}, "engine": {"type": "object"}, "containers": {"type": "array", "items": DOCKER_CONTAINER_SCHEMA}, "images": {"type": "array", "items": {"type": "string"}}, "total_containers": {"type": "integer", "minimum": 0}, "running_containers": {"type": "integer", "minimum": 0}}}
WEBHOOKS_HOOK_ROW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "url", "events", "active"], "properties": {"id": {"type": "integer"}, "url": {"type": "string"}, "events": {"type": "array", "items": {"type": "string"}}, "active": {"type": "boolean"}}}
WEBHOOKS_STATUS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "repo", "total", "active", "hooks"], "properties": {"schema_version": {"const": 1}, "repo": {"type": "string"}, "total": {"type": "integer", "minimum": 0}, "active": {"type": "integer", "minimum": 0}, "hooks": {"type": "array", "items": WEBHOOKS_HOOK_ROW_SCHEMA}}}
PAGES_DEPLOYMENT_ROW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "environment", "created_on", "stage"], "properties": {"id": {"type": "string"}, "environment": {"type": "string"}, "created_on": {"type": "string"}, "stage": {"type": "string"}}}
PAGES_LATEST_DEPLOYMENT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "environment", "created_on", "stage", "status"], "properties": {"id": {"type": "string"}, "environment": {"type": "string"}, "created_on": {"type": "string"}, "stage": {"type": "string"}, "status": {"type": "string"}}}
PAGES_DEPLOYS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "project", "account", "latest", "deployments"], "properties": {"schema_version": {"const": 1}, "project": {"type": "string"}, "account": {"type": "string"}, "latest": PAGES_LATEST_DEPLOYMENT_SCHEMA, "deployments": {"type": "array", "items": PAGES_DEPLOYMENT_ROW_SCHEMA}}}
VISUAL_TOKENS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["colors", "typography", "spacing", "radius", "density"],
    "properties": {
        "schema_version": {"type": "integer"},
        "effects": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "glow_ok": {"type": "string"},
                "glow_warn": {"type": "string"},
                "glow_bad": {"type": "string"},
                "glow_accent": {"type": "string"},
                "sheen_top": {"type": "string"},
                "shadow_panel": {"type": "string"},
                "shadow_instrument": {"type": "string"},
                "shadow_lift": {"type": "string"},
                "bezel": {"type": "string"},
            },
        },
        "motion": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "duration_fast": {"type": ["string", "number"]},
                "duration_medium": {"type": ["string", "number"]},
                "duration_live": {"type": ["string", "number"]},
                "easing": {"type": "string"},
                "easing_pulse": {"type": "string"},
            },
        },
        "backdrop": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "grid": {"type": "string"},
                "grid_size": {"type": ["string", "number"]},
                "scanline": {"type": "string"},
                "vignette": {"type": "string"},
            },
        },
        "colors": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "background", "surface", "layer", "hover", "stroke", "strong",
                "text", "muted", "dim", "accent", "blue", "ok", "warn", "bad",
            ],
            "properties": {
                "background": {"type": "string"},
                "surface": {"type": "string"},
                "layer": {"type": "string"},
                "hover": {"type": "string"},
                "stroke": {"type": "string"},
                "strong": {"type": "string"},
                "text": {"type": "string"},
                "muted": {"type": "string"},
                "dim": {"type": "string"},
                "accent": {"type": "string"},
                "blue": {"type": "string"},
                "ok": {"type": "string"},
                "warn": {"type": "string"},
                "bad": {"type": "string"},
            },
        },
        "typography": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "sans", "mono", "size_base", "size_small", "size_heading",
                "weight_normal", "weight_bold",
            ],
            "properties": {
                "sans": {"type": "array", "items": {"type": "string"}},
                "mono": {"type": "array", "items": {"type": "string"}},
                "size_base": {"type": ["string", "number"]},
                "size_small": {"type": ["string", "number"]},
                "size_heading": {"type": ["string", "number"]},
                "weight_normal": {"type": ["string", "number"]},
                "weight_bold": {"type": ["string", "number"]},
            },
        },
        "spacing": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "unit", "gap_small", "gap_medium", "gap_large",
                "padding_small", "padding_medium",
            ],
            "properties": {
                "unit": {"type": ["string", "number"]},
                "gap_small": {"type": ["string", "number"]},
                "gap_medium": {"type": ["string", "number"]},
                "gap_large": {"type": ["string", "number"]},
                "padding_small": {"type": ["string", "number"]},
                "padding_medium": {"type": ["string", "number"]},
            },
        },
        "radius": {
            "type": "object",
            "additionalProperties": False,
            "required": ["small", "medium", "large"],
            "properties": {
                "small": {"type": ["string", "number"]},
                "medium": {"type": ["string", "number"]},
                "large": {"type": ["string", "number"]},
            },
        },
        "density": {
            "type": "object",
            "additionalProperties": False,
            "required": ["row_height", "card_max_height", "grid_min_card_width"],
            "properties": {
                "row_height": {"type": ["string", "number"]},
                "card_max_height": {"type": ["string", "number"]},
                "grid_min_card_width": {"type": ["string", "number"]},
            },
        },
    },
}

# Fixed preset ids, decided by the operator ahead of issue #373 (quiet-slate
# is the default). New presets are out of scope for this issue.
VISUAL_TOKENS_PRESET_IDS = ("quiet-slate", "graphite-ink", "soft-dusk")

# visual-tokens.v2: a versioned envelope carrying the fixed three-preset
# collection. Each preset value is a full visual-tokens.v1-shaped document
# (same VISUAL_TOKENS_SCHEMA), so any single preset can be handed to a v1
# caller unchanged. Role names never vary between presets, only values.
VISUAL_TOKENS_PRESETS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "default_preset", "presets"],
    "properties": {
        "schema_version": {"const": 2},
        "default_preset": {"enum": list(VISUAL_TOKENS_PRESET_IDS)},
        "presets": {
            "type": "object",
            "additionalProperties": False,
            "required": list(VISUAL_TOKENS_PRESET_IDS),
            "properties": {
                preset_id: VISUAL_TOKENS_SCHEMA for preset_id in VISUAL_TOKENS_PRESET_IDS
            },
        },
    },
}

RUNTIME_USAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "name", "tokens_in", "tokens_out", "cost_usd", "model"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "tokens_in": {"type": "integer", "minimum": 0},
        "tokens_out": {"type": "integer", "minimum": 0},
        "cost_usd": {"type": "number", "minimum": 0},
        "model": {"type": "string"},
        "tokens": {"type": "integer", "minimum": 0},
    },
}
HISTORY_USAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["at", "tokens", "cost_usd"],
    "properties": {
        "at": {"type": "string"},
        "tokens": {"type": "integer", "minimum": 0},
        "cost_usd": {"type": "number", "minimum": 0},
    },
}
USAGE_COST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "period", "total_cost_usd", "total_tokens", "runtimes", "history"],
    "properties": {
        "schema_version": {"const": 1},
        "period": {"type": "string"},
        "total_cost_usd": {"type": "number", "minimum": 0},
        "total_tokens": {"type": "integer", "minimum": 0},
        "runtimes": {"type": "array", "items": RUNTIME_USAGE_SCHEMA},
        "history": {"type": "array", "items": HISTORY_USAGE_SCHEMA},
        "runtime_tokens": {"type": "array", "items": {"type": "integer"}},
        "runtime_names": {"type": "array", "items": {"type": "string"}},
        "model_costs": {"type": "array", "items": {"type": "number"}},
        "model_names": {"type": "array", "items": {"type": "string"}},
        "history_tokens": {"type": "array", "items": {"type": "integer"}},
        "history_points": {"type": "array", "items": {"type": "string"}},
        "history_costs": {"type": "array", "items": {"type": "number"}},
    },
}
SESSION_AGENTS_TASK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "title", "state", "progress"], "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "state": {"type": "string"}, "progress": {"type": "integer", "minimum": 0, "maximum": 100}}}
SESSION_AGENTS_AGENT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "name", "runtime", "status", "current_task", "tasks"], "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "runtime": {"type": "string"}, "status": {"type": "string", "enum": ["running", "blocked", "done", "queued"]}, "current_task": {"type": ["string", "null"]}, "tasks": {"type": "array", "items": SESSION_AGENTS_TASK_SCHEMA}}}
SESSION_AGENTS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "agents"], "properties": {"schema_version": {"const": 1}, "agents": {"type": "array", "items": SESSION_AGENTS_AGENT_SCHEMA}}}
MANDATE_SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["mandate_id", "granted_by", "allowed_tools", "data_class_max", "budget_usd_max", "max_runtime_seconds", "expires_at"], "properties": {"mandate_id": {"type": "string"}, "granted_by": {"type": "string"}, "allowed_tools": {"type": "array", "items": {"type": "string"}}, "data_class_max": {"type": "string"}, "budget_usd_max": {"type": "number", "minimum": 0}, "max_runtime_seconds": {"type": "integer", "minimum": 0}, "expires_at": {"type": "string"}}}
GATE_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["domain", "status", "label", "detail"],
               "properties": {
                   "domain": {"type": "string", "enum": ["provider_data", "mandate", "evidence",
                                                          "human_decision", "execution", "budget"]},
                   "status": {"type": "string", "enum": ["good", "warn", "crit"]},
                   "label": {"type": "string"}, "detail": {"type": "string"}}}
AUTHORITY_SCHEMA = {"type": "object", "additionalProperties": False,
                     "required": ["mandate_id", "granted_by", "replacement_policy", "dispatched_by"],
                     "properties": {"mandate_id": {"type": "string"}, "granted_by": {"type": "string"},
                                    "replacement_policy": {"type": "string"}, "dispatched_by": {"type": "string"}}}
RUN_REF_SCHEMA = {"type": "object", "additionalProperties": False,
                   "required": ["run_id", "engine"],
                   "properties": {"run_id": {"type": "string"}, "engine": {"type": "string"},
                                  "status": {"type": "string"}}}
RUN_CONTINUITY_SCHEMA = {"type": "object", "additionalProperties": False,
                          "required": ["authority", "current_run", "previous_run"],
                          "properties": {"authority": AUTHORITY_SCHEMA, "current_run": RUN_REF_SCHEMA,
                                         "previous_run": {"anyOf": [RUN_REF_SCHEMA, {"type": "null"}]}}}
WORKSTREAM_SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False,
                             "required": ["issue_id", "title", "outcome", "workflow",
                                          "pending_decision", "mandate", "gates", "run_continuity"],
                             "properties": {"issue_id": {"type": "string"}, "title": {"type": "string"},
                                            "outcome": {"type": "string"}, "workflow": {"type": "string"},
                                            "pending_decision": {"type": "boolean"},
                                            "mandate": MANDATE_SUMMARY_SCHEMA,
                                            "gates": {"type": "array", "items": GATE_SCHEMA, "minItems": 6, "maxItems": 6},
                                            "run_continuity": RUN_CONTINUITY_SCHEMA}}
EVIDENCE_RUN_SCHEMA = {"type": "object", "additionalProperties": False,
                       "required": ["run_id", "engine", "status", "evidence", "artifacts",
                                    "artifacts_present", "artifacts_missing", "independently_reviewed", "accepted"],
                       "properties": {"run_id": {"type": "string"}, "engine": {"type": "string"}, "status": {"type": "string"},
                                      "evidence": {"type": "array", "items": {"type": "string"}},
                                      "artifacts": {"type": "array", "items": {"type": "string"}},
                                      "artifacts_present": {"type": "boolean"},
                                      "artifacts_missing": {"type": "array", "items": {"type": "string"}},
                                      "independently_reviewed": {"type": "boolean"},
                                      "accepted": {"type": "boolean"}}}
EVIDENCE_COMPARISON_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["issue_id", "runs"], "properties": {"issue_id": {"type": "string"}, "runs": {"type": "array", "items": EVIDENCE_RUN_SCHEMA}}}
DECISION_PENDING_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["issue_id", "workflow", "summary", "actionable"], "properties": {"issue_id": {"type": "string"}, "workflow": {"type": "string"}, "summary": {"type": "string"}, "actionable": {"type": "boolean"}}}
ATTENTION_ITEM_SCHEMA = {"type": "object", "additionalProperties": False,
                          "required": ["workstream_id", "kind", "summary", "issue_id"],
                          "properties": {"workstream_id": {"type": "string"},
                                         "kind": {"type": "string", "enum": ["decision", "mandate", "evidence", "execution"]},
                                         "summary": {"type": "string"},
                                         "issue_id": {"type": "string"}}}
ATTENTION_QUEUE_SCHEMA = {"type": "object", "additionalProperties": False,
                          "required": ["items"],
                          "properties": {"items": {"type": "array", "items": ATTENTION_ITEM_SCHEMA}}}

# --- workstream.detail.v1 (S7a, #470) ---------------------------------------
RUN_CONFLICT_SCHEMA = {"type": "object", "additionalProperties": False,
                       "required": ["field", "values"],
                       "properties": {"field": {"type": "string"},
                                      "values": {"type": "array", "items": {"type": "string"}}}}
RUN_SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False,
                      "required": ["run_id", "issue_ref", "status", "engine", "worker_role",
                                   "started_at", "finished_at", "sources", "conflict"],
                      "properties": {
                          "run_id": {"type": "string"},
                          "issue_ref": {"type": "string"},
                          "status": {"type": "string"},
                          "engine": {"type": ["string", "null"]},
                          "worker_role": {"type": ["string", "null"]},
                          "started_at": {"type": ["string", "null"]},
                          "finished_at": {"type": ["string", "null"]},
                          "sources": {"type": "array", "items": {"type": "string"}},
                          "conflict": {"type": ["object", "null"], "additionalProperties": False,
                                       "required": ["field", "values"],
                                       "properties": {"field": {"type": "string"},
                                                      "values": {"type": "array", "items": {"type": "string"}}}},
                      }}
ISSUE_DETAIL_SCHEMA = {"type": "object", "additionalProperties": False,
                        "required": ["issue_id", "number", "title", "state", "workflow",
                                     "workflow_labels", "url", "milestone"],
                        "properties": {
                            "issue_id": {"type": "string"},
                            "number": {"type": "integer", "minimum": 1},
                            "title": {"type": "string"},
                            "state": {"type": "string"},
                            "workflow": {"type": "string"},
                            "workflow_labels": {"type": "array", "items": {"type": "string"}},
                            "url": {"type": ["string", "null"]},
                            "milestone": {"type": ["string", "null"]},
                        }}
DISPATCH_LIMITS_SCHEMA = {"type": "object", "additionalProperties": False,
                           "properties": {
                               "worker_role": {"type": "string"},
                               "workflow": {"type": "string"},
                               "max_runtime_seconds": {"type": "integer", "minimum": 0},
                               "max_cost_usd": {"type": "number", "minimum": 0},
                               "max_parallel_workers": {"type": "integer", "minimum": 0},
                               "delegation_depth": {"type": "integer", "minimum": 0},
                           }}
MANDATE_DETAIL_SCHEMA = {"type": "object", "additionalProperties": False,
                          "required": ["outcome", "scope", "acceptance_criteria",
                                       "approval_reference", "dispatch_limits"],
                          "properties": {
                              "outcome": {"type": ["string", "null"]},
                              "scope": {"type": ["string", "null"]},
                              "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                              "approval_reference": {"type": ["string", "null"]},
                              "dispatch_limits": DISPATCH_LIMITS_SCHEMA,
                          }}
RELATION_SCHEMA = {"type": "object", "additionalProperties": False,
                   "required": ["relation", "target"],
                   "properties": {"relation": {"type": "string", "enum": ["part-of", "blocked-by"]},
                                  "target": {"type": "integer", "minimum": 1}}}
EVIDENCE_DETAIL_SCHEMA = {"type": "object", "additionalProperties": False,
                          "required": ["present", "summary", "review_state"],
                          "properties": {
                              "present": {"type": "boolean"},
                              "summary": {"type": ["string", "null"]},
                              "review_state": {"type": ["string", "null"]},
                          }}
SOURCE_STATE_SCHEMA = {"type": "object", "additionalProperties": False,
                        "required": ["status", "age_seconds", "complete", "error"],
                        "properties": {
                            "status": {"type": "string", "enum": ["fresh", "stale", "unavailable"]},
                            "age_seconds": {"type": "integer", "minimum": 0},
                            "complete": {"type": "boolean"},
                            "error": {"type": ["object", "null"], "additionalProperties": False,
                                      "required": ["kind", "message"],
                                      "properties": {"kind": {"type": "string"},
                                                     "message": {"type": "string"}}},
                        }}
WORKSTREAM_DETAIL_SCHEMA = {"type": "object", "additionalProperties": False,
                             "required": ["schema_version", "mode", "synthetic", "issue",
                                          "mandate", "relations", "runs", "evidence", "source"],
                             "properties": {
                                 "schema_version": {"const": 1},
                                 "mode": {"type": "string", "enum": ["local", "synthetic"]},
                                 "synthetic": {"type": "boolean"},
                                 "issue": ISSUE_DETAIL_SCHEMA,
                                 "mandate": MANDATE_DETAIL_SCHEMA,
                                 "relations": {"type": "array", "items": RELATION_SCHEMA},
                                 "runs": {"type": "array", "items": RUN_SUMMARY_SCHEMA},
                                 "evidence": EVIDENCE_DETAIL_SCHEMA,
                                 "source": SOURCE_STATE_SCHEMA,
                             }}
RUN_SUMMARIES_SCHEMA = {"type": "object", "additionalProperties": False,
                        "required": ["schema_version", "issue_ref", "runs"],
                        "properties": {"schema_version": {"const": 1},
                                       "issue_ref": {"type": "string"},
                                       "runs": {"type": "array", "items": RUN_SUMMARY_SCHEMA}}}

TYPES = {
    "sessions.snapshot.v2": TypeEntry(SNAPSHOT_SCHEMA, "operational"),
    "dispatcher.active-runs.v1": TypeEntry(ACTIVE_RUNS_SCHEMA, "operational"),
    "issues.ready.list.v1": TypeEntry(ISSUES_SCHEMA, "public-metadata"),
    "issues.all-open.list.v1": TypeEntry(ALL_OPEN_ISSUES_SCHEMA, "public-metadata"),
    "candidates.view.v1": TypeEntry(CANDIDATES_VIEW_SCHEMA, "public-metadata"),
    "execution-map.plan.v1": TypeEntry(EXECUTION_MAP_PLAN_SCHEMA, "operational"),
    "docker.status.v1": TypeEntry(DOCKER_STATUS_SCHEMA, "operational"),
    "webhooks.status.v1": TypeEntry(WEBHOOKS_STATUS_SCHEMA, "public-metadata"),
    "pages.deploys.v1": TypeEntry(PAGES_DEPLOYS_SCHEMA, "operational"),
    "visual-tokens.v1": TypeEntry(VISUAL_TOKENS_SCHEMA, "public-metadata"),
    "visual-tokens.v2": TypeEntry(VISUAL_TOKENS_PRESETS_SCHEMA, "public-metadata"),
    "usage-cost.v1": TypeEntry(USAGE_COST_SCHEMA, "operational"),
    "session-agents.v1": TypeEntry(SESSION_AGENTS_SCHEMA, "operational"),
    "workstream.summary.v1": TypeEntry(WORKSTREAM_SUMMARY_SCHEMA, "operational"),
    "evidence.comparison.v1": TypeEntry(EVIDENCE_COMPARISON_SCHEMA, "operational"),
    "decision.pending.v1": TypeEntry(DECISION_PENDING_SCHEMA, "operational"),
    "attention.queue.v1": TypeEntry(ATTENTION_QUEUE_SCHEMA, "operational"),
    "issue.workflow.v1": TypeEntry({"type": "object"}, "public-metadata"),
    "core.string.v1": TypeEntry({"type": "string"}, "public-metadata"),
    "core.number.v1": TypeEntry({"type": "number"}, "public-metadata"),
    "core.boolean.v1": TypeEntry({"type": "boolean"}, "public-metadata"),
    "core.array.v1": TypeEntry({"type": "array"}, "public-metadata"),
    "core.object.v1": TypeEntry({"type": "object"}, "public-metadata"),
    "action.status.v1": TypeEntry({"type": "object"}, "operational"),
    "workstream.detail.v1": TypeEntry(WORKSTREAM_DETAIL_SCHEMA, "public-metadata"),
    "run.summaries.v1": TypeEntry(RUN_SUMMARIES_SCHEMA, "operational"),
}

READ_OPERATIONS = {
    "sessions.snapshot.v2": ReadOperation("store", JSON_OBJECT, "sessions.snapshot.v2", "operational", 500, 60, 2, "read:sessions"),
    "dispatcher.active-runs.v1": ReadOperation("store", JSON_OBJECT, "dispatcher.active-runs.v1", "operational", 500, 60, 2, "read:active-runs"),
    "issues.ready.list.v1": ReadOperation("github", {"type": "object", "additionalProperties": False, "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}}, "issues.ready.list.v1", "public-metadata", 2000, 30, 30, "read:issues"),
    "issues.all_open.list.v1": ReadOperation("github", {"type": "object", "additionalProperties": False, "required": ["repo"], "properties": {"repo": {"type": "string"}}}, "issues.all-open.list.v1", "public-metadata", 30000, 30, 30, "read:issues"),
    "candidates.view.v1": ReadOperation("github", {"type": "object", "additionalProperties": False, "required": ["repo"], "properties": {"repo": {"type": "string"}}}, "candidates.view.v1", "public-metadata", 30000, 30, 30, "read:issues"),
    "execution-map.plan.v1": ReadOperation("store", JSON_OBJECT, "execution-map.plan.v1", "operational", 500, 60, 2, "read:execution-map"),
    "docker.status.v1": ReadOperation("store", JSON_OBJECT, "docker.status.v1", "operational", 500, 60, 2, "read:docker"),
    "webhooks.status.v1": ReadOperation("store", JSON_OBJECT, "webhooks.status.v1", "public-metadata", 500, 60, 2, "read:webhooks"),
    "pages.deploys.v1": ReadOperation("store", JSON_OBJECT, "pages.deploys.v1", "operational", 500, 60, 2, "read:pages"),
    "usage-cost.v1": ReadOperation("store", JSON_OBJECT, "usage-cost.v1", "operational", 500, 60, 2, "read:usage-cost"),
    "session-agents.v1": ReadOperation("store", JSON_OBJECT, "session-agents.v1", "operational", 500, 60, 2, "read:session-agents"),
    "workstream.summary.v1": ReadOperation("store", JSON_OBJECT, "workstream.summary.v1", "operational", 500, 60, 2, "read:workstream-summary"),
    "evidence.comparison.v1": ReadOperation("store", JSON_OBJECT, "evidence.comparison.v1", "operational", 500, 60, 2, "read:evidence-comparison"),
    "decision.pending.v1": ReadOperation("store", JSON_OBJECT, "decision.pending.v1", "operational", 500, 60, 2, "read:decision-pending"),
    "attention.queue.v1": ReadOperation("store", JSON_OBJECT, "attention.queue.v1", "operational", 500, 60, 2, "read:attention-queue"),
    "issue.workflow.get.v1": ReadOperation("github", {"type": "object", "additionalProperties": False, "required": ["issue_number"], "properties": {"issue_number": {"type": "integer", "minimum": 1}}}, "issue.workflow.v1", "public-metadata", 2000, 30, 30, "read:issue-workflow", True),
    "workstream.detail.v1": ReadOperation("github", {"type": "object", "additionalProperties": False, "required": ["repo", "issue_number"], "properties": {"repo": {"type": "string"}, "issue_number": {"type": "integer", "minimum": 1}}}, "workstream.detail.v1", "public-metadata", 5000, 30, 30, "read:workstream-detail"),
    "run.summaries.v1": ReadOperation("store", {"type": "object", "additionalProperties": False, "required": ["issue_ref"], "properties": {"issue_ref": {"type": "string"}}}, "run.summaries.v1", "operational", 500, 60, 2, "read:run-summaries"),
}

ISSUE_ID_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["issue_id"],
                   "properties": {"issue_id": {"type": "string"}}}
ACTIONS: dict[str, ActionEntry] = {
    "workflow.mark-ready.v1": ActionEntry("github-transition", ISSUE_ID_SCHEMA, "action.status.v1",
                                          "workflow-transition", frozenset({"operator"}), "act:mark-ready", True),
    "workflow.claim-run.v1": ActionEntry("cli", ISSUE_ID_SCHEMA, "action.status.v1",
                                         "run-dispatch", frozenset({"operator"}), "act:claim-run", True),
    "workflow.record-decision.v1": ActionEntry("github-transition", ISSUE_ID_SCHEMA, "action.status.v1",
                                                "workflow-transition", frozenset({"operator"}), "act:record-decision", True),
}

_LAYOUT = ("stack", "row", "grid", "tabs", "panel")
PRIMITIVES = {name: PrimitiveEntry(frozenset({"label", "columns", "gap"}), {}, "empty", "error") for name in _LAYOUT}
PRIMITIVES.update({name: PrimitiveEntry(frozenset(), {}, "empty", "error") for name in ("divider", "spacer")})
for name, binding_type in (("text", "core.string.v1"), ("heading", "core.string.v1"), ("timestamp", "core.string.v1"), ("badge", "core.string.v1"), ("metric", "core.number.v1")):
    PRIMITIVES[name] = PrimitiveEntry(frozenset({"value", "label", "empty", "error"}), {"value": binding_type}, "empty", "error")
PRIMITIVES.update({
    "empty-state": PrimitiveEntry(frozenset({"message"}), {}, "empty", "error"),
    "error-state": PrimitiveEntry(frozenset({"message"}), {}, "empty", "error"),
    "list": PrimitiveEntry(frozenset({"items", "label", "empty", "error"}), {"items": "core.array.v1"}, "empty", "error"),
    "table": PrimitiveEntry(frozenset({"rows", "columns", "label", "empty", "error"}), {"rows": "core.array.v1"}, "empty", "error"),
    "key-value": PrimitiveEntry(frozenset({"value", "empty", "error"}), {"value": "core.object.v1"}, "empty", "error"),
    "bar": PrimitiveEntry(frozenset({"label", "categories", "empty", "error"}), {"values": "core.array.v1"}, "empty", "error"),
    "line": PrimitiveEntry(frozenset({"label", "points", "empty", "error"}), {"series": "core.array.v1"}, "empty", "error"),
    "swimlane": PrimitiveEntry(frozenset({"label", "columns", "empty", "error"}), {"rows": "core.array.v1"}, "empty", "error"),
    "button": PrimitiveEntry(frozenset({"label", "action"}), {}, "denied", "error", True),
    "choice": PrimitiveEntry(frozenset({"label", "action", "options"}), {}, "denied", "error", True),
})

TRANSFORMS: dict[str, Any] = {}
DATA_CLASS_ORDER = {"public-metadata": 0, "operational": 1}
ALLOWED_CAPABILITIES = (frozenset(op.capability for op in READ_OPERATIONS.values())
                        | frozenset(op.capability for op in ACTIONS.values()))
