"""Read-only renderer for validated widget render trees."""

from typing import Any, Mapping

from .models import Binding, RenderNode, Widget
from .primitives import render_primitive
from .registry import PRIMITIVES
from .registry import TYPES
from .validation import ValidationError, validate


class RenderError(ValueError):
    pass


_MISSING = object()


def resolve_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _bound(binding: Binding, data: Mapping[str, Any]) -> Any:
    if binding.read not in data:
        return _MISSING
    return resolve_pointer(data[binding.read], binding.pointer)


def _render(node: RenderNode, data: Mapping[str, Any], read_states: Mapping[str, str]) -> dict[str, Any] | None:
    if node.when is not None:
        condition = _bound(node.when, data)
        if condition is _MISSING or condition is not True:
            return None
    props = dict(node.props)
    state = "ready"
    entry = PRIMITIVES[node.primitive]
    for name, binding in node.bindings.items():
        value = _bound(binding, data)
        source_state = read_states.get(binding.read, "ready")
        if value is _MISSING:
            state = source_state if source_state in ("stale", "denied", "error") else entry.empty_state
        else:
            props[name] = value
            if source_state in ("stale", "denied", "error"):
                state = source_state
    children = []
    for child in node.children:
        rendered = _render(child, data, read_states)
        if rendered is not None:
            children.append(rendered)
    return render_primitive(node.primitive, props, children, state)


def render(widget: Widget, data: Mapping[str, Any], read_states: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Render only declared data into a plain JSON-compatible tree."""
    known_reads = {read.id for read in widget.reads}
    if set(data) - known_reads:
        raise RenderError("data contains an undeclared read")
    for read in widget.reads:
        if read.id in data:
            try:
                validate(data[read.id], TYPES[read.output_type].schema, f"$.data.{read.id}")
            except ValidationError as exc:
                raise RenderError(str(exc)) from exc
    tree = _render(widget.render, data, read_states or {})
    if tree is None:
        tree = render_primitive("empty-state", {"message": "hidden"}, [], "empty")
    return {"contract_version": widget.contract_version, "widget": {"id": widget.id, "version": widget.version}, "render": tree}
