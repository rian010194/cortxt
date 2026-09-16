"""W-3 (#612): interactive TUI packaging lifecycle + both-client oracle tests.

The pin's TUI (``render_tui``) is rendering-only; ``PackagingTuiSession`` adds
a genuine lifecycle consuming the SAME shared ``PackagingOpsApi`` the web
action host routes use, driven by real Core-store state in temporary
directories. ``input_fn``/``output_fn`` are injected so tests drive the
interactive flows without a terminal. The oracle asserts the Packaging
Workstream (mandate/objective/scope/non-goals/repo-refs) is visible in BOTH
clients through one shared projection.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from state.core_store import CoreStore
from widget_contract.product_packaging.ops_api import (
    PACKAGING_WORKSTREAM,
    PackagingOpsApi,
)
from widget_contract.product_packaging.revision import build_revision
from widget_contract.tui import PackagingTuiSession


def _content() -> dict:
    return {"audience": "operator", "evidence_refs": [], "features": ["tui"],
            "outcome": "packaged", "problem": "unpackaged",
            "prior_binding_refs": [], "referenced_repositories": ["rian010194/cortxt"],
            "scope": ["tui scope"]}


class _ScriptedIO:
    """Scripted stdin/stdout for driving the interactive lifecycle."""

    def __init__(self, lines: list[str]) -> None:
        self._inputs = iter(lines)
        self.outputs: list[str] = []

    def input(self, _prompt: str = "") -> str:
        try:
            return next(self._inputs)
        except StopIteration:
            raise EOFError("script exhausted") from None

    def output(self, line: str) -> None:
        self.outputs.append(str(line))


def _session(api: PackagingOpsApi, script: list[str]) -> _ScriptedIO:
    io = _ScriptedIO(script)
    session = PackagingTuiSession(api, input_fn=io.input, output_fn=io.output)
    return session, io


class PackagingTuiLifecycleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = CoreStore(self._tmp.name)
        self.api = PackagingOpsApi(self.store)

    def _text(self, io: _ScriptedIO) -> str:
        return "\n".join(io.outputs)


class TestLifecycleCommands(PackagingTuiLifecycleTestCase):
    def test_requires_the_shared_ops_api_instance(self):
        try:
            PackagingTuiSession(object())
        except ValueError as exc:
            assert "PackagingOpsApi" in str(exc)
        else:
            self.fail("expected ValueError for a non-ops-API object")

    def test_help_and_unknown_command(self):
        io = _ScriptedIO(["bogus-command", "quit"])
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()
        text = self._text(io)
        assert "commands:" in text
        assert "[error] unknown command 'bogus-command'" in text

    def test_list_and_show_revision_over_real_store(self):
        self.api.create_revision(build_revision("cortxt-core", _content()))
        io = _ScriptedIO(["list revisions", "quit"])
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()
        text = self._text(io)
        assert "revisions: 1" in text
        identity = self.api.list_revisions()[0]["revision_identity"]
        io2 = _ScriptedIO([f"show revision {identity[:12]}", "quit"])
        session2 = PackagingTuiSession(self.api, input_fn=io2.input, output_fn=io2.output)
        session2.run()
        shown = self._text(io2)
        assert f"revision_identity: {identity}" in shown
        assert "cortxt-core" in shown

    def test_interactive_create_revision_with_confirmation(self):
        io = _ScriptedIO([
            "create-revision",
            "cortxt-core",          # package_id
            "",                     # parent (genesis)
            json.dumps(_content()), # content JSON
            "yes",                  # explicit confirmation
            "quit",
        ])
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()
        text = self._text(io)
        assert "about to append to the Core store:" in text
        assert "outcome: appended" in text
        assert "appended: true" in text
        # The store actually holds the revision now.
        assert len(self.api.list_revisions()) == 1

    def test_create_revision_aborted_without_confirmation(self):
        io = _ScriptedIO([
            "create-revision",
            "cortxt-core",
            "",
            json.dumps(_content()),
            "no",                   # refused: nothing may be appended
            "quit",
        ])
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()
        text = self._text(io)
        assert "aborted (not confirmed); nothing appended" in text
        assert self.api.list_revisions() == []

    def test_create_revision_invalid_json_fails_closed(self):
        io = _ScriptedIO([
            "create-revision",
            "cortxt-core",
            "",
            "{not json",
            "quit",
        ])
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()
        assert "content is not valid JSON" in self._text(io)
        assert self.api.list_revisions() == []

    def test_interactive_record_decision_flow(self):
        created = self.api.create_revision(build_revision("cortxt-core", _content()))
        digest = created["revision_identity"]
        io = _ScriptedIO([
            "record-decision",
            "cortxt-core",            # package_id
            digest,                   # revision digest
            "acceptance",             # scope
            "operator-rikard",        # operator
            "accepted",               # verdict
            "yes",                    # confirm
            "list decisions",
            "quit",
        ])
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()
        text = self._text(io)
        assert "outcome: appended" in text
        assert "decisions: 1" in text

    def test_decision_replay_renders_re_delivery(self):
        created = self.api.create_revision(build_revision("cortxt-core", _content()))
        digest = created["revision_identity"]
        self.api.record_decision(package_id="cortxt-core", revision_digest=digest,
                                 decision_scope="acceptance",
                                 operator="operator-rikard", verdict="accepted")
        io = _ScriptedIO([
            "record-decision",
            "cortxt-core", digest, "acceptance", "operator-rikard", "accepted",
            "yes",
            "quit",
        ])
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()
        assert "outcome: re-delivery" in self._text(io)

    def test_eof_terminates_session(self):
        class _ImmediateEOF:
            def __call__(self, _prompt: str = "") -> str:
                raise EOFError

        io = _ScriptedIO([])
        io._inputs = iter(())  # exhausted from the start
        session = PackagingTuiSession(self.api, input_fn=io.input, output_fn=io.output)
        session.run()  # must return, not raise
        assert "bye" in io.outputs


class TestBothClientVisibilityOracle(PackagingTuiLifecycleTestCase):
    """Kriterium-oracle: the Packaging Workstream is visible in BOTH clients."""

    ORACLE_FIELDS = ("mandate", "objective", "scope", "non_goals", "repo_refs")

    def _web_view(self) -> dict:
        # The web surface is the same ActionHost route the browser reads.
        from widget.action_host import ActionHost

        host = ActionHost(spec_path=Path(__file__).resolve().parents[2]
                          / "widget_contract" / "specs" / "candidates-0.1.yaml",
                          token="test-token", packaging_store=self._tmp.name)
        return host.packaging_workstream()

    def test_same_workstream_visible_in_both_clients(self):
        web = self._web_view()
        tui_session_io = _ScriptedIO(["workstream", "quit"])
        session = PackagingTuiSession(self.api, input_fn=tui_session_io.input,
                                      output_fn=tui_session_io.output)
        session.run()
        web = web["workstream"]
        for field in self.ORACLE_FIELDS:
            # Web client: the projection carries the field with content.
            assert web[field], f"web client missing {field}"
            # TUI client: the same field is rendered.
            rendered = self._text(tui_session_io)
            self.assertIn(web[field][0] if isinstance(web[field], list) else web[field][:40],
                          rendered, f"TUI missing {field}")
        # Both clients serve the SAME projection object.
        assert web["id"] == "WS-606"
        assert web["mandate"] == PACKAGING_WORKSTREAM["mandate"]
        assert web["repo_refs"] == PACKAGING_WORKSTREAM["repo_refs"]
        assert "=== Packaging Workstream ===" in self._text(tui_session_io)

    def test_web_route_projection_matches_api_projection(self):
        from widget.action_host import ActionHost

        host = ActionHost(token="test-token", packaging_store=self._tmp.name)
        assert host.packaging_workstream()["workstream"] == self.api.workstream()["workstream"]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
