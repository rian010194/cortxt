#!/usr/bin/env python3
"""Offline checks for the Docker status widget (#337).

Run: python scripts/test_widget_docker.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the docker-status render tree shape (engine key-values, running/total
metrics, containers table, images list), safe projection, strict spec loading,
CLI artifact path with injected fake reader, error-state artifact for failing
reader or malformed projection, manifest row, and read-only host boundary.
"""
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

from cli.unified_cli import _run_widget  # noqa: E402
from widget_contract.adapters.store_reads import ReadAdapterError, read_docker_status_v1  # noqa: E402
from widget_contract.loader import load_widget_file  # noqa: E402
from widget_contract.registry import READ_OPERATIONS, TYPES  # noqa: E402
from widget_contract.renderer import render  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def fake_snapshot(containers=None, images=None, engine=None):
    c_list = containers if containers is not None else [
        {"id": "c1a2b3c4d5e6", "name": "web-app", "image": "nginx:alpine", "status": "Up 2 hours"},
        {"id": "f7e8d9c0b1a2", "name": "db-redis", "image": "redis:7-alpine", "status": "Exited (0) 10 minutes ago"},
    ]
    i_list = images if images is not None else ["nginx:alpine", "redis:7-alpine", "python:3.11-slim"]
    e_dict = engine if engine is not None else {
        "server_version": "26.1.4",
        "os": "Linux",
        "architecture": "x86_64",
        "status": "running",
    }
    return {
        "schema_version": 1,
        "engine": e_dict,
        "containers": c_list,
        "images": i_list,
        "total_containers": len(c_list),
        "running_containers": sum(1 for c in c_list if c.get("status", "").startswith("Up")),
    }


def main() -> int:
    # 1. Spec strictly declares docker read, manual refresh, and no actions.
    spec = AP / "widget_contract" / "specs" / "docker-status-0.1.yaml"
    widget = load_widget_file(spec)
    check("spec declares docker-status identity and no actions",
          widget.id == "docker-status" and widget.version == "0.1" and widget.actions == ())
    check("spec declares exactly one read with read:docker capability",
          len(widget.reads) == 1 and set(widget.capabilities) == {"read:docker"})
    (read,) = widget.reads
    check("read is a store docker.status.v1 read with manual refresh",
          (read.id, read.source, read.operation, read.output_type, read.refresh["mode"]) ==
          ("docker", "store", "docker.status.v1", "docker.status.v1", "manual"))
    operation = READ_OPERATIONS.get("docker.status.v1")
    check("docker.status.v1 is registered in READ_OPERATIONS",
          operation is not None and operation.capability == "read:docker" and operation.source == "store")
    check("docker.status.v1 is registered in TYPES",
          "docker.status.v1" in TYPES and TYPES["docker.status.v1"].data_class == "operational")

    # 2. Render tree shape for populated fixture.
    data = fake_snapshot()
    tree = render(widget, {"docker": data}, {"docker": "fresh"})
    check("render tree primitive is stack", tree["render"]["primitive"] == "stack")
    children = tree["render"]["children"]
    check("engine renders as key-value",
          children[0]["primitive"] == "key-value"
          and children[0]["props"]["value"]["server_version"] == "26.1.4")
    check("running count renders as metric",
          children[1]["primitive"] == "metric"
          and children[1]["props"]["label"] == "Running"
          and children[1]["props"]["value"] == 1)
    check("total count renders as metric",
          children[2]["primitive"] == "metric"
          and children[2]["props"]["label"] == "Total"
          and children[2]["props"]["value"] == 2)
    check("containers render as table with columns and rows",
          children[3]["primitive"] == "table"
          and children[3]["props"]["label"] == "Containers"
          and children[3]["props"]["columns"] == ["id", "name", "image", "status"]
          and len(children[3]["props"]["rows"]) == 2
          and children[3]["props"]["rows"][0]["name"] == "web-app")
    check("images render as list with items",
          children[4]["primitive"] == "list"
          and children[4]["props"]["label"] == "Images"
          and children[4]["props"]["empty"] == "No images"
          and children[4]["props"]["items"] == ["nginx:alpine", "redis:7-alpine", "python:3.11-slim"])

    # 3. Safe projection strips undeclared container keys; malformed input fails closed.
    source = fake_snapshot(containers=[
        {"id": "c1", "name": "n1", "image": "i1", "status": "Up", "secret_env": "secret123", "command": "run.sh"}
    ])
    projection = read_docker_status_v1(source)
    check("safe projection strips undeclared container fields",
          "secret_env" not in projection["containers"][0]
          and "command" not in projection["containers"][0]
          and projection["containers"][0] == {"id": "c1", "name": "n1", "image": "i1", "status": "Up"})

    callable_projection = read_docker_status_v1(lambda: source)
    check("adapter accepts callable projection",
          callable_projection["containers"][0]["id"] == "c1")

    malformed_cases = [
        {"containers": "not_a_list"},
        {"containers": [], "images": "not_a_list"},
        {"containers": [], "images": [], "engine": "not_a_dict"},
        {"containers": [{"id": "c1"}], "images": [], "engine": {}},  # missing required container keys
        {"containers": [], "images": [123], "engine": {}},  # non-string image
    ]
    for idx, bad in enumerate(malformed_cases):
        failed_closed = False
        try:
            read_docker_status_v1(bad)
        except ReadAdapterError:
            failed_closed = True
        check(f"malformed input case {idx + 1} fails closed", failed_closed)

    # 4. CLI artifact path with injected fake reader: valid snapshot -> ready artifact.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        target = tmp_path / "docker-status.json"

        # Valid reader
        result = _run_widget(
            Namespace(widget_command=None, view="docker-status", repo=None, snapshot=target),
            docker_reader=lambda: fake_snapshot(),
        )
        check("CLI docker-status view succeeds with injected reader", result.status == "succeeded")
        artifact = json.loads(target.read_text(encoding="utf-8"))
        check("artifact has widget identity and no error",
              artifact["widget"] == {"id": "docker-status", "version": "0.1"} and artifact["error"] is None)
        check("artifact render state is ready", artifact["render"]["state"] == "ready")
        rendered_children = artifact["render"]["children"]
        check("artifact has all 5 declared render nodes",
              len(rendered_children) == 5
              and rendered_children[0]["primitive"] == "key-value"
              and rendered_children[1]["primitive"] == "metric"
              and rendered_children[2]["primitive"] == "metric"
              and rendered_children[3]["primitive"] == "table"
              and rendered_children[4]["primitive"] == "list")

        # Failing reader (OSError / subprocess failure) -> error-state artifact
        def broken_reader():
            raise OSError("docker daemon is not running")

        target_err = tmp_path / "docker-status-err.json"
        result_err = _run_widget(
            Namespace(widget_command=None, view="docker-status", repo=None, snapshot=target_err),
            docker_reader=broken_reader,
        )
        check("CLI docker-status view settles succeeded on reader error", result_err.status == "succeeded")
        artifact_err = json.loads(target_err.read_text(encoding="utf-8"))
        check("error artifact has kind docker_read",
              artifact_err["error"]["kind"] == "docker_read"
              and "docker daemon is not running" in artifact_err["error"]["message"])
        check("error artifact render primitive is error-state",
              artifact_err["render"]["primitive"] == "error-state"
              and artifact_err["render"]["state"] == "error")

        # Malformed reader output -> error-state artifact (never partial fresh data)
        def malformed_reader():
            return {"containers": "corrupted_non_list"}

        target_malformed = tmp_path / "docker-status-malformed.json"
        result_mal = _run_widget(
            Namespace(widget_command=None, view="docker-status", repo=None, snapshot=target_malformed),
            docker_reader=malformed_reader,
        )
        check("CLI settles succeeded on malformed reader output", result_mal.status == "succeeded")
        artifact_mal = json.loads(target_malformed.read_text(encoding="utf-8"))
        check("malformed artifact has kind docker_read and error-state primitive",
              artifact_mal["error"]["kind"] == "docker_read"
              and artifact_mal["render"]["primitive"] == "error-state")

    # 5. Manifest row + read-only host boundary.
    manifest = json.loads((AP / "widget" / "widgets.json").read_text(encoding="utf-8"))
    docker_row = next((w for w in manifest["widgets"] if w["id"] == "docker"), None)
    check("manifest contains docker row with correct spec and artifact",
          docker_row is not None
          and docker_row["title"] == "Docker"
          and docker_row["spec"] == "widget_contract/specs/docker-status-0.1.yaml"
          and docker_row["artifact"] == "docker-status.json"
          and docker_row["hint"] == "cortxt widget --view docker-status")

    serve = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("default serve.py stays read-only (no POST handler)", "do_POST" not in serve)

    # 6. Generic HTML shell covers used primitives.
    html = (AP / "widget" / "index.html").read_text(encoding="utf-8")
    check("generic shell handles stack primitive", 'node.primitive==="stack"' in html)
    check("generic shell handles key-value primitive", 'node.primitive==="key-value"' in html)
    check("generic shell handles metric primitive", 'node.primitive==="metric"' in html)
    check("generic shell handles table primitive", 'node.primitive==="table"' in html)
    check("generic shell handles list primitive", 'node.primitive==="list"' in html)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
