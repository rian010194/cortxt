"""B-16: read-area discovery on the web action host.

Three things are pinned here and they are the unit's product rules.

1. **Discovery never gates anything.** A host with no read area starts
   normally, serves everything it served before, and answers
   GET /api/repositories with an explicit 503 ``read_area_unconfigured``
   rather than an empty success. "Cortxt was never told where to look" and
   "there is nothing there" are different answers, and only one has a fix.

2. **Read never becomes write.** The route is GET-only, no POST counterpart
   exists, and a configured read area changes nothing about the mutation
   route's guard set.

3. **Path alone is never reported.** Every repository comes back with its
   revision state and with the caveats that say what could not be
   established -- above all that ``origin_main_ref`` is a local, unverified
   ref.

HTTP tests run on a loopback ephemeral socket; every git call goes through an
injected fake runner, so nothing here shells out and nothing touches the
network.
"""
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from widget.action_host import (
    ActionHost, _make_handler, _ReusableThreadingHTTPServer, main as host_main,
)

SPEC_PATH = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "candidates-0.1.yaml"


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch):
    """Neither resolver may pick up the developer's own environment.

    `main()` resolves the data home before the read area, so an ambient
    CORTXT_DATA_HOME could refuse first and make a read-area test pass for
    the wrong reason.
    """
    monkeypatch.delenv("CORTXT_DATA_HOME", raising=False)
    monkeypatch.delenv("CORTXT_READ_AREA", raising=False)


def _host(**overrides):
    kwargs = {
        "spec_path": SPEC_PATH,
        "labels_reader": lambda issue_id: ["workflow:inbox"],
        "transition_writer": lambda issue_id: {"issue_id": issue_id, "status": "ok"},
        "token": "test-token",
    }
    kwargs.update(overrides)
    return ActionHost(**kwargs)


def _fake_git(argv, **kwargs):
    """A ``subprocess.run`` stand-in: a clean repo on a non-main branch."""
    if "--abbrev-ref" in argv:
        out = "feat/b16-read-area-discovery\n"
    elif "refs/remotes/origin/main" in argv:
        out = "b" * 40 + "\n"
    elif "remote" in argv:
        out = "https://github.com/rian010194/cortxt.git\n"
    elif "status" in argv:
        out = ""
    else:
        out = "a" * 40 + "\n"
    return SimpleNamespace(returncode=0, stdout=out, stderr="")


@pytest.fixture
def read_area(monkeypatch):
    """A real directory tree holding two repositories, with git faked."""
    import state.repo_discovery as repo_discovery
    monkeypatch.setattr(repo_discovery.subprocess, "run", _fake_git)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        for name in ("alpha", "bravo"):
            (root / "projects" / name / ".git").mkdir(parents=True)
        yield root


def _serve(host):
    httpd = _ReusableThreadingHTTPServer(("127.0.0.1", 0), _make_handler(host))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, f"http://127.0.0.1:{httpd.server_address[1]}"


def _stop(httpd, thread):
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture
def configured_server(read_area):
    httpd, thread, url = _serve(_host(read_area=(read_area,)))
    yield url
    _stop(httpd, thread)


@pytest.fixture
def unconfigured_server():
    httpd, thread, url = _serve(_host())  # no read area
    yield url
    _stop(httpd, thread)


def _get(server, path):
    request = urllib.request.Request(f"{server}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


# --- the constructor: strictly additive ---------------------------------


def test_the_read_area_defaults_to_empty_so_every_existing_construction_works():
    assert _host().read_area == ()


def test_a_configured_read_area_is_exposed_as_resolved_paths(read_area):
    host = _host(read_area=(read_area,))
    assert host.read_area == (read_area,)
    assert all(isinstance(root, Path) for root in host.read_area)


# --- the unconfigured answer --------------------------------------------


def test_unconfigured_repositories_route_answers_an_explicit_503(unconfigured_server):
    status, body = _get(unconfigured_server, "/api/repositories")
    assert status == 503
    payload = json.loads(body)
    assert payload["status"] == "unavailable"
    assert payload["error"]["kind"] == "read_area_unconfigured"


def test_the_unconfigured_envelope_matches_the_packaging_unavailable_shape(
        unconfigured_server):
    # Same envelope as the packaging read routes use when their store is not
    # configured. A consumer must not have to special-case this route.
    status, body = _get(unconfigured_server, "/api/repositories")
    payload = json.loads(body)
    assert set(payload) == {"schema_version", "status", "error"}
    assert payload["schema_version"] == 1
    assert set(payload["error"]) == {"kind", "message"}


def test_the_unconfigured_refusal_names_the_fix_not_only_the_fault(unconfigured_server):
    _, body = _get(unconfigured_server, "/api/repositories")
    message = json.loads(body)["error"]["message"]
    assert "--read-area" in message and "CORTXT_READ_AREA" in message


def test_an_unconfigured_read_area_is_never_an_empty_success(unconfigured_server):
    # The failure this route exists to avoid: "nothing found" read as fact.
    status, body = _get(unconfigured_server, "/api/repositories")
    assert status != 200
    assert "repositories" not in json.loads(body)


def test_an_unconfigured_read_area_does_not_disturb_the_other_routes(unconfigured_server):
    status, _ = _get(unconfigured_server, "/api/capabilities")
    assert status == 200


# --- the configured answer ------------------------------------------------


def test_the_route_reports_the_repositories_in_the_read_area(configured_server):
    status, body = _get(configured_server, "/api/repositories")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert [repo["name"] for repo in payload["repositories"]] == ["alpha", "bravo"]


def test_the_answer_names_the_read_area_it_was_derived_from(configured_server):
    payload = json.loads(_get(configured_server, "/api/repositories")[1])
    assert payload["read_area"] and all(isinstance(r, str) for r in payload["read_area"])


def test_every_repository_carries_its_revision_state(configured_server):
    payload = json.loads(_get(configured_server, "/api/repositories")[1])
    for repo in payload["repositories"]:
        assert set(repo) == {"path", "name", "origin_url", "branch", "head",
                             "dirty", "origin_main_ref", "caveats"}
        assert repo["branch"] == "feat/b16-read-area-discovery"
        assert repo["head"] == "a" * 40
        assert repo["dirty"] is False


def test_no_repository_is_reported_by_path_alone(configured_server):
    """The 2026-09-16 rule, pinned at the route.

    A result that named a repository without its revision state would
    reproduce the day on which four of five Cortxt checkouts disagreed with
    their remote and nothing in the answer said so.
    """
    payload = json.loads(_get(configured_server, "/api/repositories")[1])
    assert payload["repositories"]
    for repo in payload["repositories"]:
        assert repo["path"]
        assert repo["branch"] is not None or repo["head"] is not None
        assert repo["caveats"], "an observation with no caveats claims completeness"


def test_the_origin_main_caveat_crosses_the_route_intact(configured_server):
    payload = json.loads(_get(configured_server, "/api/repositories")[1])
    for repo in payload["repositories"]:
        text = " ".join(repo["caveats"])
        assert "LOCAL ref" in text
        assert "NOT been verified against the remote" in text


def test_caveats_serialize_as_a_json_list(configured_server):
    payload = json.loads(_get(configured_server, "/api/repositories")[1])
    assert all(isinstance(repo["caveats"], list) for repo in payload["repositories"])


def test_the_payload_is_json_serializable_without_path_objects(configured_server):
    payload = json.loads(_get(configured_server, "/api/repositories")[1])
    assert all(isinstance(repo["path"], str) for repo in payload["repositories"])


# --- read is not write ----------------------------------------------------


def test_the_route_has_no_post_counterpart(configured_server):
    request = urllib.request.Request(
        f"{configured_server}/api/repositories", method="POST",
        data=b"{}", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 404


def test_the_route_needs_no_session_token(configured_server):
    # It is a read, so it carries no operator gate -- and equally it grants
    # nothing that would require one.
    status, _ = _get(configured_server, "/api/repositories")
    assert status == 200


def test_a_configured_read_area_grants_no_write_target(read_area):
    host = _host(read_area=(read_area,))
    payload = host.repositories()
    # Nothing in the answer is a permission: no allowlist, no writable flag,
    # no write target of any kind.
    flat = json.dumps(payload)
    for word in ("allowlist", "writable", "write_target", "may_write", "permitted"):
        assert word not in flat


# --- main(): resolved and refused before the port is bound ----------------


def test_main_refuses_an_invalid_read_area_without_binding(capsys):
    code = host_main(port=0, read_area="relative-read-area")
    assert code == 1
    out = capsys.readouterr().out
    assert "refusing to start" in out and "read area" in out
    assert "not_absolute" in out


def test_the_refusal_names_which_input_carried_the_bad_value(capsys):
    host_main(port=0, read_area="relative-read-area")
    assert "--read-area" in capsys.readouterr().out


def test_main_refuses_a_read_area_from_the_environment_by_its_variable_name(
        monkeypatch, capsys):
    monkeypatch.setenv("CORTXT_READ_AREA", "relative-read-area")
    assert host_main(port=0) == 1
    assert "CORTXT_READ_AREA" in capsys.readouterr().out


def test_an_unconfigured_read_area_is_not_a_refusal(monkeypatch):
    # Nothing about a default start changes: the resolver returns () and the
    # host is constructed exactly as before this parameter existed.
    monkeypatch.delenv("CORTXT_READ_AREA", raising=False)
    from state.read_area import resolve_read_area
    assert resolve_read_area(None, env={}) == ()


def test_main_accepts_the_read_area_keyword_without_binding(monkeypatch, read_area):
    """The parameter reaches the constructor, proven without serving.

    ``main`` blocks in ``serve_forever``, so the host construction is
    intercepted instead: the assertion is that the resolved roots arrive as
    ``read_area``.
    """
    seen = {}

    class _Recorded(ActionHost):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop before serving")

    monkeypatch.setattr("widget.action_host.ActionHost", _Recorded)
    with pytest.raises(RuntimeError):
        host_main(port=0, read_area=str(read_area))
    assert seen["read_area"] == (read_area,)


def test_several_roots_reach_the_host_in_order(monkeypatch, read_area, tmp_path):
    second = tmp_path / "second-root"
    second.mkdir()
    seen = {}

    class _Recorded(ActionHost):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop before serving")

    monkeypatch.setattr("widget.action_host.ActionHost", _Recorded)
    with pytest.raises(RuntimeError):
        host_main(port=0, read_area=f"{read_area}{os.pathsep}{second}")
    assert seen["read_area"] == (read_area, second.resolve())


def test_a_missing_root_is_refused_before_anything_binds(capsys, tmp_path):
    # Nothing is left listening after a refusal: main returns 1 having never
    # constructed the server. An absolute path is used deliberately, so the
    # refusal under test is not_a_directory and not not_absolute.
    missing = tmp_path / "definitely-not-there"
    assert host_main(port=0, read_area=str(missing)) == 1
    assert "not_a_directory" in capsys.readouterr().out
