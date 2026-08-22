"""Inert models produced by the widget contract loader."""

from dataclasses import dataclass
from typing import Any, Mapping, Tuple


@dataclass(frozen=True)
class Binding:
    read: str
    pointer: str
    type_id: str


@dataclass(frozen=True)
class DataRead:
    id: str
    source: str
    operation: str
    input: Mapping[str, Any]
    select: Tuple[str, ...]
    refresh: Mapping[str, Any]
    output_type: str
    on_error: str


@dataclass(frozen=True)
class RenderNode:
    primitive: str
    props: Mapping[str, Any]
    bindings: Mapping[str, Binding]
    children: Tuple["RenderNode", ...]
    when: Binding | None = None


@dataclass(frozen=True)
class Action:
    id: str
    port: str
    operation: str
    input: Mapping[str, Any]
    authorization: Mapping[str, str]
    confirm: Mapping[str, Any]
    result_type: str
    idempotency_key: str | None


@dataclass(frozen=True)
class Widget:
    contract_version: str
    id: str
    version: str
    title: str
    reads: Tuple[DataRead, ...]
    render: RenderNode
    actions: Tuple[Action, ...]
    capabilities: Tuple[str, ...]
    canonical_json: str
    document_hash: str


@dataclass(frozen=True)
class Connection:
    source_widget: str
    output: str
    target_widget: str
    input: str
    type_id: str


@dataclass(frozen=True)
class Composition:
    contract_version: str
    id: str
    version: str
    widgets: Tuple[Mapping[str, Any], ...]
    layout: Mapping[str, Any]
    connections: Tuple[Connection, ...]
    capabilities: Tuple[str, ...]
