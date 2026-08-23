import json
from pathlib import Path

import pytest

from widget_contract.adapters.store_reads import ReadAdapterError, read_docker_status_v1
from widget_contract.loader import load_widget_file
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.renderer import render
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "docker-status-0.1.yaml"


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


def test_docker_status_spec_loads_and_declares_docker_read():
    widget = load_widget_file(SPEC)
    assert widget.id == "docker-status" and widget.version == "0.1"
    assert widget.actions == ()
    (read,) = widget.reads
    assert (read.id, read.source, read.operation, read.output_type) == (
        "docker", "store", "docker.status.v1", "docker.status.v1")
    assert read.on_error == "stale"
    assert read.refresh["mode"] == "manual"
    operation = READ_OPERATIONS["docker.status.v1"]
    assert (operation.source, operation.capability) == ("store", "read:docker")
    assert set(widget.capabilities) == {"read:docker"}


def test_docker_status_render_produces_expected_tree():
    widget = load_widget_file(SPEC)
    data = fake_snapshot()
    tree = render(widget, {"docker": data}, {"docker": "fresh"})
    assert tree["render"]["primitive"] == "stack"
    children = tree["render"]["children"]
    assert children[0]["primitive"] == "key-value"
    assert children[0]["props"]["value"]["server_version"] == "26.1.4"
    assert children[1]["primitive"] == "metric"
    assert children[1]["props"]["label"] == "Running"
    assert children[1]["props"]["value"] == 1
    assert children[2]["primitive"] == "metric"
    assert children[2]["props"]["label"] == "Total"
    assert children[2]["props"]["value"] == 2
    assert children[3]["props"]["label"] == "Containers"
    assert children[3]["props"]["columns"] == ["id", "name", "image", "status"]
    assert children[3]["props"]["rows"][0]["name"] == "web-app"
    assert children[4]["props"]["label"] == "Images"
    assert children[4]["props"]["empty"] == "No images"
    assert children[4]["props"]["items"] == ["nginx:alpine", "redis:7-alpine", "python:3.11-slim"]


def test_docker_status_zero_state_and_schema_validation():
    widget = load_widget_file(SPEC)
    data = fake_snapshot(containers=[], images=[])
    tree = render(widget, {"docker": data}, {"docker": "fresh"})
    assert tree["render"]["children"][3]["props"]["rows"] == []
    assert tree["render"]["children"][4]["props"]["items"] == []
    validate(data, TYPES["docker.status.v1"].schema)
    malformed = {**data, "containers": "wrong"}
    with pytest.raises(ValidationError):
        validate(malformed, TYPES["docker.status.v1"].schema)


def test_read_docker_status_v1_is_safe_projection_and_rejects_type_mismatch():
    source = fake_snapshot(containers=[
        {"id": "c1", "name": "n1", "image": "i1", "status": "Up", "secret_env": "secret123", "command": "run.sh"}
    ])
    projection = read_docker_status_v1(source)
    assert "secret_env" not in projection["containers"][0]
    assert "command" not in projection["containers"][0]
    assert projection["containers"][0] == {"id": "c1", "name": "n1", "image": "i1", "status": "Up"}

    callable_projection = read_docker_status_v1(lambda: source)
    assert callable_projection["containers"][0]["id"] == "c1"

    with pytest.raises(ReadAdapterError):
        read_docker_status_v1({"containers": "wrong"})
    with pytest.raises(ReadAdapterError):
        read_docker_status_v1({"containers": [], "images": "wrong"})
    with pytest.raises(ReadAdapterError):
        read_docker_status_v1({"containers": [], "images": [], "engine": "wrong"})


def test_cli_docker_status_writes_artifact_and_error_state(capsys, tmp_path):
    from argparse import Namespace
    from cli.unified_cli import _run_widget

    target = tmp_path / "docker-status.json"
    result = _run_widget(
        Namespace(widget_command=None, view="docker-status", repo=None, snapshot=target),
        docker_reader=lambda: fake_snapshot(),
    )
    capsys.readouterr()
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "docker-status", "version": "0.1"}
    assert artifact["render"]["primitive"] == "stack"
    assert artifact["error"] is None
    tables = [c for c in artifact["render"]["children"] if c["primitive"] == "table"]
    assert tables[0]["props"]["label"] == "Containers"
    assert tables[0]["props"]["rows"][0]["name"] == "web-app"

    def failing_reader():
        raise OSError("docker daemon connection refused")

    target2 = tmp_path / "docker-status-err.json"
    result2 = _run_widget(
        Namespace(widget_command=None, view="docker-status", repo=None, snapshot=target2),
        docker_reader=failing_reader,
    )
    capsys.readouterr()
    assert result2.status == "succeeded"
    artifact2 = json.loads(target2.read_text(encoding="utf-8"))
    assert artifact2["error"]["kind"] == "docker_read"
    assert artifact2["render"]["primitive"] == "error-state"
    assert artifact2["render"]["state"] == "error"


def test_widget_has_docker_view_without_post():
    widget_dir = Path(__file__).resolve().parents[2] / "widget"
    html = (widget_dir / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((widget_dir / "widgets.json").read_text(encoding="utf-8"))
    assert any(w["id"] == "docker" and w["artifact"] == "docker-status.json" for w in manifest["widgets"])
    assert "renderGenericNode" in html
    assert "loadManifest" in html
    assert "do_POST" not in html
