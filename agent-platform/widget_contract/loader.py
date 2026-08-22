"""Strict canonical loader for widget and dashboard documents."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from .models import Action, Binding, Composition, Connection, DataRead, RenderNode, Widget
from .registry import ACTIONS, ALLOWED_CAPABILITIES, DATA_CLASS_ORDER, PRIMITIVES, READ_OPERATIONS, TRANSFORMS, TYPES
from .validation import ValidationError, validate

MAX_DOCUMENT_BYTES = 256_000
MAX_DEPTH = 32
_ID = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_FORBIDDEN_KEYS = re.compile(r"(?:command|executable|url|uri|header|environment|env|credential|secret|token|password|code|prompt|query|graphql|script|path|mount|docker|log)$", re.I)
_FORBIDDEN_VALUE = re.compile(r"(?:https?://|file://|\$\{|\$[A-Z_][A-Z0-9_]*|%[A-Z_][A-Z0-9_]*%|\.\.[/\\]|(?:^|\s)(?:sh|bash|cmd|powershell|python|node)(?:\.exe)?\s)", re.I)
_STANDARD_TAGS = {"tag:yaml.org,2002:null", "tag:yaml.org,2002:bool", "tag:yaml.org,2002:int", "tag:yaml.org,2002:float", "tag:yaml.org,2002:str", "tag:yaml.org,2002:seq", "tag:yaml.org,2002:map"}


class ContractError(ValueError):
    """The document is not a safe widget contract."""


def _json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ContractError("map keys must be strings")
        if key in result:
            raise ContractError(f"duplicate key: {key}")
        result[key] = value
    return result


def _yaml_node(node: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise ContractError("document nesting limit exceeded")
    if node.tag not in _STANDARD_TAGS:
        raise ContractError("custom YAML tags are forbidden")
    if isinstance(node, MappingNode):
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                raise ContractError("map keys must be strings")
            key = key_node.value
            if key in result:
                raise ContractError(f"duplicate key: {key}")
            result[key] = _yaml_node(value_node, depth + 1)
        return result
    if isinstance(node, SequenceNode):
        return [_yaml_node(item, depth + 1) for item in node.value]
    if isinstance(node, ScalarNode):
        if node.tag.endswith(":str"):
            return node.value
        if node.tag.endswith(":null"):
            return None
        if node.tag.endswith(":bool"):
            if node.value not in ("true", "false"):
                raise ContractError("implementation-specific YAML booleans are forbidden")
            return node.value == "true"
        if node.tag.endswith(":int"):
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", node.value):
                raise ContractError("non-JSON YAML integers are forbidden")
            return int(node.value)
        if node.tag.endswith(":float"):
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)\.[0-9]+", node.value):
                raise ContractError("non-JSON YAML floats are forbidden")
            return float(node.value)
    raise ContractError("unsupported YAML value")


def _parse(document: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(document, Mapping):
        value = dict(document)
    else:
        text = document.decode("utf-8") if isinstance(document, bytes) else document
        if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ContractError("document size limit exceeded")
        try:
            value = json.loads(text, object_pairs_hook=_json_object_pairs)
        except json.JSONDecodeError:
            try:
                if any(isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in yaml.scan(text)):
                    raise ContractError("YAML aliases, anchors, and custom tags are forbidden")
                node = yaml.compose(text, Loader=yaml.SafeLoader)
                if node is None:
                    raise ContractError("document is empty")
                value = _yaml_node(node)
            except ContractError:
                raise
            except yaml.YAMLError as exc:
                raise ContractError("invalid YAML") from exc
    if not isinstance(value, dict):
        raise ContractError("document root must be an object")
    _reject_forbidden(value)
    return value


def _reject_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("map keys must be strings")
            if _FORBIDDEN_KEYS.search(key):
                raise ContractError(f"{path}.{key}: forbidden field")
            _reject_forbidden(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden(item, f"{path}[{index}]")
    elif isinstance(value, str) and _FORBIDDEN_VALUE.search(value):
        raise ContractError(f"{path}: forbidden value")


def _closed(obj: Mapping[str, Any], required: set[str], optional: set[str], path: str) -> None:
    missing = required - set(obj)
    unknown = set(obj) - required - optional
    if missing:
        raise ContractError(f"{path}: missing {sorted(missing)[0]}")
    if unknown:
        raise ContractError(f"{path}: unknown field {sorted(unknown)[0]}")


def _binding(raw: Any, reads: Mapping[str, DataRead], expected: str, path: str) -> Binding:
    if not isinstance(raw, dict):
        raise ContractError(f"{path}: binding must be an object")
    _closed(raw, {"read", "pointer", "type"}, set(), path)
    if raw["read"] not in reads:
        raise ContractError(f"{path}: unknown read")
    if raw["type"] not in TYPES or raw["type"] != expected:
        raise ContractError(f"{path}: binding type mismatch")
    pointer = raw["pointer"]
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")) or ".." in pointer:
        raise ContractError(f"{path}: invalid JSON Pointer")
    return Binding(raw["read"], pointer, raw["type"])


def _render(raw: Any, reads: Mapping[str, DataRead], action_ids: set[str], path: str = "$.render") -> RenderNode:
    if not isinstance(raw, dict):
        raise ContractError(f"{path}: render node must be an object")
    _closed(raw, {"primitive"}, {"props", "bindings", "children", "when"}, path)
    primitive = PRIMITIVES.get(raw["primitive"])
    if primitive is None:
        raise ContractError(f"{path}: unregistered primitive")
    props = raw.get("props", {})
    bindings = raw.get("bindings", {})
    if not isinstance(props, dict) or set(props) - primitive.props:
        raise ContractError(f"{path}: invalid primitive properties")
    if not isinstance(bindings, dict) or set(bindings) - set(primitive.bindings):
        raise ContractError(f"{path}: invalid primitive bindings")
    typed = {name: _binding(item, reads, primitive.bindings[name], f"{path}.bindings.{name}") for name, item in bindings.items()}
    if primitive.input_primitive and props.get("action") not in action_ids:
        raise ContractError(f"{path}: input must name a declared action")
    when = _binding(raw["when"], reads, "core.boolean.v1", f"{path}.when") if "when" in raw else None
    children_raw = raw.get("children", [])
    if not isinstance(children_raw, list):
        raise ContractError(f"{path}.children: expected array")
    children = tuple(_render(item, reads, action_ids, f"{path}.children[{index}]") for index, item in enumerate(children_raw))
    return RenderNode(raw["primitive"], props, typed, children, when)


def load_widget(document: str | bytes | Mapping[str, Any], *, allowed_capabilities: set[str] | frozenset[str] = ALLOWED_CAPABILITIES) -> Widget:
    raw = _parse(document)
    _closed(raw, {"contract_version", "widget", "data", "render", "actions", "capabilities"}, set(), "$")
    if raw["contract_version"] != "0.1":
        raise ContractError("unsupported contract version")
    widget = raw["widget"]
    data = raw["data"]
    if not isinstance(widget, dict) or not isinstance(data, dict):
        raise ContractError("widget and data must be objects")
    _closed(widget, {"id", "version", "title"}, set(), "$.widget")
    _closed(data, {"reads"}, {"transforms"}, "$.data")
    if not isinstance(widget["id"], str) or not _ID.fullmatch(widget["id"]) or not isinstance(widget["version"], str) or not isinstance(widget["title"], str):
        raise ContractError("invalid widget identity")
    capabilities = raw["capabilities"]
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities) or len(set(capabilities)) != len(capabilities):
        raise ContractError("capabilities must be unique strings")
    if not set(capabilities) <= set(allowed_capabilities):
        raise ContractError("capability is not host allow-listed")
    if not isinstance(data["reads"], list) or not isinstance(raw["actions"], list):
        raise ContractError("reads and actions must be arrays")
    if data.get("transforms", []) not in ([], None):
        if not isinstance(data["transforms"], list):
            raise ContractError("transforms must be an array")
        for transform in data["transforms"]:
            if not isinstance(transform, dict) or transform.get("operation") not in TRANSFORMS:
                raise ContractError("unregistered transform")
    reads: dict[str, DataRead] = {}
    for index, item in enumerate(data["reads"]):
        path = f"$.data.reads[{index}]"
        if not isinstance(item, dict):
            raise ContractError(f"{path}: expected object")
        _closed(item, {"id", "source", "operation", "input", "select", "refresh", "output_type", "on_error"}, set(), path)
        operation = READ_OPERATIONS.get(item["operation"])
        if operation is None or operation.declared_only:
            raise ContractError(f"{path}: unavailable read operation")
        if item["source"] != operation.source or item["output_type"] != operation.output_type:
            raise ContractError(f"{path}: operation type or source mismatch")
        try:
            validate(item["input"], operation.input_schema, f"{path}.input")
        except ValidationError as exc:
            raise ContractError(str(exc)) from exc
        if operation.capability not in capabilities:
            raise ContractError(f"{path}: undeclared capability")
        refresh = item["refresh"]
        if not isinstance(refresh, dict):
            raise ContractError(f"{path}.refresh: expected object")
        _closed(refresh, {"mode"}, {"interval_seconds"}, f"{path}.refresh")
        if refresh["mode"] not in ("manual", "on_load", "poll") or (refresh["mode"] == "poll" and refresh.get("interval_seconds", 0) < 5):
            raise ContractError(f"{path}: invalid refresh")
        if item["on_error"] not in ("empty", "stale", "error") or not isinstance(item["select"], list) or any(not isinstance(pointer, str) or (pointer and not pointer.startswith("/")) or ".." in pointer for pointer in item["select"]):
            raise ContractError(f"{path}: invalid error or select policy")
        if item["id"] in reads or not _ID.fullmatch(item["id"]):
            raise ContractError(f"{path}: invalid or duplicate read id")
        reads[item["id"]] = DataRead(item["id"], item["source"], item["operation"], item["input"], tuple(item["select"]), refresh, item["output_type"], item["on_error"])
    actions: list[Action] = []
    action_ids: set[str] = set()
    for index, item in enumerate(raw["actions"]):
        path = f"$.actions[{index}]"
        if not isinstance(item, dict):
            raise ContractError(f"{path}: expected object")
        _closed(item, {"id", "port", "operation", "input", "authorization", "confirm", "result_type"}, {"idempotency_key"}, path)
        entry = ACTIONS.get(item["operation"])
        if entry is None or entry.port != item["port"] or entry.result_type != item["result_type"]:
            raise ContractError(f"{path}: unregistered or mismatched action")
        if entry.capability not in capabilities:
            raise ContractError(f"{path}: undeclared capability")
        if not isinstance(item["id"], str) or not _ID.fullmatch(item["id"]) or item["id"] in action_ids:
            raise ContractError(f"{path}: duplicate action id")
        authorization = item["authorization"]
        confirm = item["confirm"]
        _closed(authorization, {"mode", "reference"}, set(), f"{path}.authorization")
        _closed(confirm, {"summary", "effect_class", "required"}, set(), f"{path}.confirm")
        if authorization["mode"] not in entry.authorization_modes or not isinstance(authorization["reference"], str) or not authorization["reference"] or confirm["effect_class"] != entry.effect_class or not isinstance(confirm["summary"], str) or not isinstance(confirm["required"], bool):
            raise ContractError(f"{path}: invalid authorization or effect")
        try:
            validate(item["input"], entry.input_schema, f"{path}.input")
        except ValidationError as exc:
            raise ContractError(str(exc)) from exc
        if entry.retryable and not item.get("idempotency_key"):
            raise ContractError(f"{path}: idempotency key required")
        action_ids.add(item["id"])
        actions.append(Action(item["id"], item["port"], item["operation"], item["input"], authorization, confirm, item["result_type"], item.get("idempotency_key")))
    render = _render(raw["render"], reads, action_ids)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return Widget("0.1", widget["id"], widget["version"], widget["title"], tuple(reads.values()), render, tuple(actions), tuple(capabilities), canonical, hashlib.sha256(canonical.encode()).hexdigest())


def load_widget_file(path: str | Path, **kwargs: Any) -> Widget:
    return load_widget(Path(path).read_bytes(), **kwargs)


def load_composition(document: str | bytes | Mapping[str, Any], widgets: Mapping[tuple[str, str], Widget]) -> Composition:
    raw = _parse(document)
    _closed(raw, {"contract_version", "composition", "widgets", "layout", "connections", "capabilities"}, set(), "$")
    if raw["contract_version"] != "0.1":
        raise ContractError("unsupported contract version")
    meta = raw["composition"]
    _closed(meta, {"id", "version"}, set(), "$.composition")
    aliases: dict[str, Widget] = {}
    refs = []
    for ref in raw["widgets"]:
        _closed(ref, {"namespace", "widget_id", "version", "inputs", "outputs"}, {"data_class"}, "$.widgets[]")
        key = (ref["widget_id"], ref["version"])
        if key not in widgets or ref["namespace"] in aliases:
            raise ContractError("missing exact widget version or duplicate namespace")
        if ref.get("data_class", "operational") not in DATA_CLASS_ORDER:
            raise ContractError("unknown widget data class")
        aliases[ref["namespace"]] = widgets[key]
        refs.append(ref)
    declared_caps = set(raw["capabilities"])
    child_caps = set().union(*(set(widget.capabilities) for widget in aliases.values())) if aliases else set()
    if declared_caps != child_caps:
        raise ContractError("composition capabilities must exactly match child capabilities")
    connections = []
    graph = {name: set() for name in aliases}
    for item in raw["connections"]:
        _closed(item, {"from", "output", "to", "input", "type"}, set(), "$.connections[]")
        source, target = item["from"], item["to"]
        if source not in aliases or target not in aliases or source == target:
            raise ContractError("connection namespace is invalid")
        source_ref = next(ref for ref in refs if ref["namespace"] == source)
        target_ref = next(ref for ref in refs if ref["namespace"] == target)
        if source_ref["outputs"].get(item["output"]) != item["type"] or target_ref["inputs"].get(item["input"]) != item["type"] or item["type"] not in TYPES:
            raise ContractError("connection type mismatch")
        source_class = TYPES[item["type"]].data_class
        target_class = target_ref.get("data_class", "operational")
        if DATA_CLASS_ORDER[source_class] > DATA_CLASS_ORDER[target_class]:
            raise ContractError("connection exceeds target data class")
        graph[source].add(target)
        connections.append(Connection(source, item["output"], target, item["input"], item["type"]))
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            raise ContractError("composition connections are cyclic")
        if node in visited:
            return
        visiting.add(node)
        for target in graph[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)
    _validate_layout(raw["layout"], set(aliases))
    return Composition("0.1", meta["id"], meta["version"], tuple(refs), raw["layout"], tuple(connections), tuple(raw["capabilities"]))


def _validate_layout(node: Any, namespaces: set[str]) -> None:
    if not isinstance(node, dict):
        raise ContractError("layout node must be an object")
    _closed(node, {"primitive"}, {"children", "widget"}, "$.layout")
    if node["primitive"] not in {"stack", "row", "grid", "tabs", "panel"}:
        raise ContractError("composition layout primitive is not allowed")
    if "widget" in node and node["widget"] not in namespaces:
        raise ContractError("layout references an unknown namespace")
    for child in node.get("children", []):
        _validate_layout(child, namespaces)
