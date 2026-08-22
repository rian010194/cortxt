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

TYPES = {
    "sessions.snapshot.v2": TypeEntry(SNAPSHOT_SCHEMA, "operational"),
    "dispatcher.active-runs.v1": TypeEntry(ACTIVE_RUNS_SCHEMA, "operational"),
    "issues.ready.list.v1": TypeEntry(ISSUES_SCHEMA, "public-metadata"),
    "issue.workflow.v1": TypeEntry({"type": "object"}, "public-metadata"),
    "core.string.v1": TypeEntry({"type": "string"}, "public-metadata"),
    "core.number.v1": TypeEntry({"type": "number"}, "public-metadata"),
    "core.boolean.v1": TypeEntry({"type": "boolean"}, "public-metadata"),
    "core.array.v1": TypeEntry({"type": "array"}, "public-metadata"),
    "core.object.v1": TypeEntry({"type": "object"}, "public-metadata"),
    "action.status.v1": TypeEntry({"type": "object"}, "operational"),
}

READ_OPERATIONS = {
    "sessions.snapshot.v2": ReadOperation("store", JSON_OBJECT, "sessions.snapshot.v2", "operational", 500, 60, 2, "read:sessions"),
    "dispatcher.active-runs.v1": ReadOperation("store", JSON_OBJECT, "dispatcher.active-runs.v1", "operational", 500, 60, 2, "read:active-runs"),
    "issues.ready.list.v1": ReadOperation("github", {"type": "object", "additionalProperties": False, "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}}, "issues.ready.list.v1", "public-metadata", 2000, 30, 30, "read:issues"),
    "issue.workflow.get.v1": ReadOperation("github", {"type": "object", "additionalProperties": False, "required": ["issue_number"], "properties": {"issue_number": {"type": "integer", "minimum": 1}}}, "issue.workflow.v1", "public-metadata", 2000, 30, 30, "read:issue-workflow", True),
}

_LAYOUT = ("stack", "row", "grid", "tabs", "panel")
PRIMITIVES = {name: PrimitiveEntry(frozenset({"label", "columns", "gap"}), {}, "empty", "error") for name in _LAYOUT}
PRIMITIVES.update({name: PrimitiveEntry(frozenset(), {}, "empty", "error") for name in ("divider", "spacer")})
for name, binding_type in (("text", "core.string.v1"), ("heading", "core.string.v1"), ("timestamp", "core.string.v1"), ("badge", "core.string.v1"), ("metric", "core.number.v1")):
    PRIMITIVES[name] = PrimitiveEntry(frozenset({"value", "label", "empty", "error"}), {"value": binding_type}, "empty", "error")
PRIMITIVES.update({
    "empty-state": PrimitiveEntry(frozenset({"message"}), {}, "empty", "error"),
    "error-state": PrimitiveEntry(frozenset({"message"}), {}, "empty", "error"),
    "list": PrimitiveEntry(frozenset({"items", "empty", "error"}), {"items": "core.array.v1"}, "empty", "error"),
    "table": PrimitiveEntry(frozenset({"rows", "columns", "empty", "error"}), {"rows": "core.array.v1"}, "empty", "error"),
    "key-value": PrimitiveEntry(frozenset({"value", "empty", "error"}), {"value": "core.object.v1"}, "empty", "error"),
    "button": PrimitiveEntry(frozenset({"label", "action"}), {}, "denied", "error", True),
    "choice": PrimitiveEntry(frozenset({"label", "action", "options"}), {}, "denied", "error", True),
})

TRANSFORMS: dict[str, Any] = {}
ACTIONS: dict[str, ActionEntry] = {}
DATA_CLASS_ORDER = {"public-metadata": 0, "operational": 1}
ALLOWED_CAPABILITIES = frozenset(op.capability for op in READ_OPERATIONS.values())
