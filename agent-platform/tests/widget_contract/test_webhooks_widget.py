"""Webhooks / Cloudflare status view as a contract widget (issue #338)."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

import cli.unified_cli as unified_cli
from cli.unified_cli import _run_widget
from widget_contract.adapters.store_reads import (
    ReadAdapterError,
    read_pages_deploys_v1,
    read_webhooks_status_v1,
    redact_hook,
)
from widget_contract.loader import load_widget_file
from widget_contract.registry import (
    ALLOWED_CAPABILITIES,
    READ_OPERATIONS,
    TYPES,
)
from widget_contract.renderer import render
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "webhooks-0.1.yaml"


def fake_raw_hooks(secret_marker: str = "ghp_secret_webhook_key_999") -> list[dict]:
    return [
        {
            "id": 101,
            "url": "https://api.github.com/repos/rian010194/cortxt/hooks/101",
            "name": "web",
            "active": True,
            "events": ["push", "pull_request"],
            "config": {
                "url": "https://api.cloudflare.com/pages/deploy-hook/123",
                "content_type": "json",
                "secret": secret_marker,
            },
        },
        {
            "id": 102,
            "url": "https://api.github.com/repos/rian010194/cortxt/hooks/102",
            "name": "web",
            "active": False,
            "events": ["issues"],
            "config": {
                "url": "https://notify.example.com/events",
                "content_type": "json",
                "secret": secret_marker,
            },
        },
    ]


def fake_pages_data() -> dict:
    return {
        "schema_version": 1,
        "project": "cortxt",
        "account": "c7c04f119f81234dc3d851bf6ff2adfe",
        "latest": {
            "id": "dep-456",
            "environment": "production",
            "created_on": "2026-08-23T18:00:00Z",
            "stage": "deploy",
            "status": "success",
        },
        "deployments": [
            {
                "id": "dep-456",
                "environment": "production",
                "created_on": "2026-08-23T18:00:00Z",
                "stage": "deploy",
            },
            {
                "id": "dep-455",
                "environment": "preview",
                "created_on": "2026-08-23T17:00:00Z",
                "stage": "deploy",
            },
        ],
    }


def test_webhooks_types_and_reads_registered():
    assert "webhooks.status.v1" in TYPES
    assert TYPES["webhooks.status.v1"].data_class == "public-metadata"
    assert "pages.deploys.v1" in TYPES
    assert TYPES["pages.deploys.v1"].data_class == "operational"

    wh_op = READ_OPERATIONS["webhooks.status.v1"]
    assert (wh_op.source, wh_op.output_type, wh_op.capability) == (
        "store", "webhooks.status.v1", "read:webhooks"
    )
    pg_op = READ_OPERATIONS["pages.deploys.v1"]
    assert (pg_op.source, pg_op.output_type, pg_op.capability) == (
        "store", "pages.deploys.v1", "read:pages"
    )

    assert "read:webhooks" in ALLOWED_CAPABILITIES
    assert "read:pages" in ALLOWED_CAPABILITIES


def test_spec_loads_and_declares_two_reads():
    widget = load_widget_file(SPEC)
    assert widget.id == "webhooks" and widget.version == "0.1"
    assert widget.actions == ()
    assert len(widget.reads) == 2

    reads_by_id = {r.id: r for r in widget.reads}
    wh_read = reads_by_id["webhooks"]
    assert (wh_read.source, wh_read.operation, wh_read.output_type) == (
        "store", "webhooks.status.v1", "webhooks.status.v1"
    )
    assert wh_read.on_error == "stale"

    pg_read = reads_by_id["pages"]
    assert (pg_read.source, pg_read.operation, pg_read.output_type) == (
        "store", "pages.deploys.v1", "pages.deploys.v1"
    )
    assert pg_read.on_error == "stale"

    assert set(widget.capabilities) == {"read:webhooks", "read:pages"}


def test_redaction_helper_and_adapter_validation():
    secret_marker = "cfat_secret_token_12345"
    raw_hooks = fake_raw_hooks(secret_marker=secret_marker)
    redacted = redact_hook(raw_hooks[0])
    assert redacted["id"] == 101
    assert redacted["url"] == "https://api.cloudflare.com/pages/deploy-hook/123"
    assert redacted["events"] == ["push", "pull_request"]
    assert redacted["active"] is True
    assert "secret" not in redacted
    assert "config" not in redacted
    assert secret_marker not in str(redacted)

    wh_proj = read_webhooks_status_v1({
        "repo": "rian010194/cortxt",
        "total": 2,
        "active": 1,
        "hooks": raw_hooks,
    })
    assert wh_proj["schema_version"] == 1
    assert wh_proj["total"] == 2
    assert wh_proj["active"] == 1
    assert len(wh_proj["hooks"]) == 2
    assert secret_marker not in str(wh_proj)

    with pytest.raises(ReadAdapterError):
        read_webhooks_status_v1({"repo": 123, "hooks": []})
    with pytest.raises(ReadAdapterError):
        read_webhooks_status_v1({"repo": "owner/repo", "hooks": "invalid"})

    pages_raw = fake_pages_data()
    pg_proj = read_pages_deploys_v1(pages_raw)
    assert pg_proj["schema_version"] == 1
    assert pg_proj["latest"]["id"] == "dep-456"
    assert len(pg_proj["deployments"]) == 2

    with pytest.raises(ReadAdapterError):
        read_pages_deploys_v1({"project": "cortxt", "account": "c7c04f119f81234dc3d851bf6ff2adfe", "latest": "bad", "deployments": []})


def test_render_produces_expected_tree():
    widget = load_widget_file(SPEC)
    raw_hooks = fake_raw_hooks()
    wh_proj = read_webhooks_status_v1({
        "repo": "rian010194/cortxt",
        "total": 2,
        "active": 1,
        "hooks": raw_hooks,
    })
    pg_proj = read_pages_deploys_v1(fake_pages_data())

    tree = render(widget, {"webhooks": wh_proj, "pages": pg_proj}, {"webhooks": "fresh", "pages": "fresh"})
    assert tree["render"]["primitive"] == "stack"
    children = tree["render"]["children"]
    assert len(children) == 4

    metric = children[0]
    assert metric["primitive"] == "metric"
    assert metric["props"]["value"] == 1

    hooks_table = children[1]
    assert hooks_table["primitive"] == "table"
    assert hooks_table["props"]["label"] == "Hooks"
    assert len(hooks_table["props"]["rows"]) == 2

    latest_kv = children[2]
    assert latest_kv["primitive"] == "key-value"
    assert latest_kv["props"]["value"]["id"] == "dep-456"

    deploys_table = children[3]
    assert deploys_table["primitive"] == "table"
    assert deploys_table["props"]["label"] == "Deployments"
    assert len(deploys_table["props"]["rows"]) == 2


def test_cli_webhooks_view(monkeypatch, capsys, tmp_path):
    secret_marker = "cfat_test_secret_cli_999"
    monkeypatch.setattr(unified_cli, "_gh_webhooks_reader", lambda repo: fake_raw_hooks(secret_marker=secret_marker))
    monkeypatch.setattr(unified_cli, "_pages_deploys_reader", lambda *args, **kwargs: fake_pages_data())

    target = tmp_path / "webhooks.json"
    res = _run_widget(Namespace(widget_command=None, view="webhooks", repo="rian010194/cortxt",
                                snapshot=target, snapshot_input=None, plan_input=None))
    out = capsys.readouterr().out
    assert res.status == "succeeded"
    assert target.is_file()

    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["render"]["state"] == "ready"
    assert artifact.get("error") is None
    assert artifact.get("repo") == "rian010194/cortxt"
    assert len(artifact["render"]["children"][1]["props"]["rows"]) == 2
    assert secret_marker not in target.read_text(encoding="utf-8")
    assert secret_marker not in out

    # Test failure mode
    monkeypatch.setattr(unified_cli, "_gh_webhooks_reader", lambda repo: (_ for _ in ()).throw(RuntimeError("API error")))
    target_err = tmp_path / "webhooks-err.json"
    res_err = _run_widget(Namespace(widget_command=None, view="webhooks", repo="rian010194/cortxt",
                                    snapshot=target_err, snapshot_input=None, plan_input=None))
    assert res_err.status == "succeeded"
    err_artifact = json.loads(target_err.read_text(encoding="utf-8"))
    assert err_artifact["error"]["kind"] == "webhooks_read"
    assert err_artifact["render"]["state"] == "error"


def test_cli_pages_deploys_view(monkeypatch, capsys, tmp_path):
    fake_token = "cfat_cli_fake_token_abc123"
    monkeypatch.setattr(unified_cli, "_pages_deploys_reader", lambda *args, **kwargs: fake_pages_data())

    target = tmp_path / "pages-deploys.json"
    res = _run_widget(Namespace(widget_command=None, view="pages-deploys", repo=None,
                                snapshot=target, snapshot_input=None, plan_input=None))
    out = capsys.readouterr().out
    assert res.status == "succeeded"
    assert target.is_file()

    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["render"]["state"] == "ready"
    assert artifact.get("error") is None
    assert artifact["render"]["children"][2]["props"]["value"]["id"] == "dep-456"
    assert len(artifact["render"]["children"][3]["props"]["rows"]) == 2
    assert fake_token not in target.read_text(encoding="utf-8")
    assert fake_token not in out

    # Test failure mode
    monkeypatch.setattr(unified_cli, "_pages_deploys_reader", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(f"Fail with {fake_token}")))
    target_err = tmp_path / "pages-err.json"
    res_err = _run_widget(Namespace(widget_command=None, view="pages-deploys", repo=None,
                                    snapshot=target_err, snapshot_input=None, plan_input=None))
    assert res_err.status == "succeeded"
    err_artifact = json.loads(target_err.read_text(encoding="utf-8"))
    assert err_artifact["error"]["kind"] == "pages_read"
    assert err_artifact["render"]["state"] == "error"
    assert fake_token not in target_err.read_text(encoding="utf-8")
