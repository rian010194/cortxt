"""S7 (#500): a runtime with no carrier on this host is refused before a claim.

Two approved dispatches were already spent on this defect -- #417's
`run-0654831c53104935a9d193ae286db1b2` and #485's Run 1, dead at the adapter
boundary in 3.3 seconds with no provider reached. `dsh` was reported
dispatchable because `_RUNTIME_ENV_REQUIREMENTS` covered `hermes-free` only and
therefore checked nothing.

The check asks the SDK's own resolver, never the platform: since A4
(`lab/finding-a4-dsh-carrier-on-win32.md`) the node carrier resolves and
completes a handshake on win32, so "win32 has no carrier" would be both
forbidden by #500's acceptance criteria and factually wrong.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import worker_adapters  # noqa: E402
from widget_contract.dispatch_request import build_dispatch_request_v1  # noqa: E402


@pytest.fixture
def carrier(monkeypatch):
    """Replace the dsh carrier preflight with a controllable one."""
    def _set(result):
        monkeypatch.setitem(worker_adapters._RUNTIME_PREFLIGHTS, "dsh", lambda: result)
    return _set


# --- the preflight predicate ----------------------------------------------

def test_unregistered_runtime_is_never_launchable():
    ok, reason = worker_adapters.runtime_launch_preflight("no-such-runtime")
    assert ok is False
    assert "no-such-runtime" in reason


def test_hermes_free_env_behaviour_is_unchanged(monkeypatch):
    """#500's acceptance criteria: hermes-free's existing behaviour must hold."""
    monkeypatch.delenv("CORTXT_FREE_MODEL", raising=False)
    monkeypatch.delenv("CORTXT_FREE_PROVIDER", raising=False)
    ok, reason = worker_adapters.runtime_launch_preflight("hermes-free")
    assert ok is False
    assert "CORTXT_FREE_MODEL" in reason
    assert worker_adapters.runtime_launch_config_ok("hermes-free") is False

    monkeypatch.setenv("CORTXT_FREE_MODEL", "upstage/solar-pro4:free")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "nous")
    assert worker_adapters.runtime_launch_preflight("hermes-free") == (True, None)
    assert worker_adapters.runtime_launch_config_ok("hermes-free") is True


def test_env_check_never_reports_a_credential_value(monkeypatch):
    """Presence only -- #500: never inspect or report credential values."""
    monkeypatch.setenv("CORTXT_FREE_MODEL", "sk-do-not-leak-me")
    monkeypatch.delenv("CORTXT_FREE_PROVIDER", raising=False)
    _ok, reason = worker_adapters.runtime_launch_preflight("hermes-free")
    assert "sk-do-not-leak-me" not in reason


def test_dsh_refused_when_no_carrier_resolves(carrier):
    carrier((False, "no dsh runtime carrier is available in 'exe' mode"))
    ok, reason = worker_adapters.runtime_launch_preflight("dsh")
    assert ok is False
    assert "carrier" in reason
    assert worker_adapters.runtime_launch_config_ok("dsh") is False


def test_dsh_launchable_when_a_carrier_resolves(carrier):
    carrier((True, None))
    assert worker_adapters.runtime_launch_preflight("dsh") == (True, None)
    assert worker_adapters.runtime_launch_config_ok("dsh") is True


def test_dsh_node_carrier_is_launchable_but_says_so(carrier):
    """Riding a dev-only source build must be visible, never silent.

    The SDK deliberately refuses to select the node carrier automatically so a
    production deployment cannot ride a source build without meaning to. The
    preflight permits it and reports it -- a reason on the SUCCESS path.
    """
    carrier((True, "dsh will run on the dev-only node carrier (DSH_RUNTIME_MODE=node), "
                   "not a production executable"))
    ok, reason = worker_adapters.runtime_launch_preflight("dsh")
    assert ok is True
    assert "node carrier" in reason


def test_preflight_does_not_hard_code_a_platform():
    """The predicate must decide from resolution, not from `sys.platform`.

    Checks the executable body only: the docstring names win32 deliberately,
    to record why the platform must NOT be tested, and that explanation is the
    opposite of the defect.
    """
    import ast
    import inspect
    body = ast.parse(inspect.getsource(worker_adapters._dsh_carrier_preflight)).body[0]
    if (body.body and isinstance(body.body[0], ast.Expr)
            and isinstance(body.body[0].value, ast.Constant)):
        del body.body[0]          # drop the docstring
    code = ast.unparse(body)

    assert "win32" not in code
    assert "platform" not in code.replace("resolve_bundled_launch_args", "")
    assert "resolve_bundled_launch_args" in code


def test_real_dsh_preflight_agrees_with_the_sdk():
    """Whatever this host's answer is, it is the SDK's answer, not a guess."""
    ok, reason = worker_adapters._dsh_carrier_preflight()
    assert isinstance(ok, bool)
    try:
        from deepseek_harness_runtime import resolve_bundled_launch_args
    except ImportError:
        assert ok is False
        assert "not installed" in reason
        return
    try:
        resolve_bundled_launch_args()
    except Exception:
        assert ok is False, "the SDK cannot resolve a carrier, so neither may we"
    else:
        assert ok is True


# --- the refusal reaching the projection ----------------------------------

def _issue():
    return {
        "number": 500, "title": "Carrier preflight", "labels": [{"name": "workflow:ready"}],
        "body": (
            "## Scope\n\nDo the thing.\n\n"
            "## Deterministic acceptance criteria\n\n1. It is done.\n\n"
            "## Worker role and limits\n\n"
            "- Workflow: work-launcher/v1\n- Worker role: builder\n"
            "- Max runtime: 600 seconds\n- Max cost: USD 1.00\n"
            "- Max parallel workers: 1\n- Delegation depth: 0\n\n"
            "## Engine policy\n\nEngine: dsh\nReliability: unverified\n\n"
            "## Approval status\n\nOperator approved this exact scope, route, and "
            "limits on 2026-09-07.\n"),
    }


class _Choice:
    engine_id = "dsh"
    reason = "cheapest match"


def _request(**kwargs):
    return build_dispatch_request_v1(_issue(), _Choice(), repo="owner/repo",
                                     routable_tags=["background-task"], **kwargs)


def test_missing_carrier_names_the_cause_not_the_symptom():
    request = _request(engine_registered=False,
                       engine_unavailable_reason="no dsh runtime carrier is available in 'exe' mode")

    assert request["eligible"] is False
    assert "engine_carrier_unavailable" in request["missing"]
    assert "engine_registered" not in request["missing"]
    entry = next(x for x in request["errors"] if x["code"] == "engine_carrier_unavailable")
    assert entry["category"] == "engine"
    assert "no dsh runtime carrier is available" in entry["recovery"]


def test_unregistered_engine_keeps_the_generic_code():
    """"No host can run this" and "this host cannot" stay distinguishable."""
    request = _request(engine_registered=False)

    assert "engine_registered" in request["missing"]
    assert "engine_carrier_unavailable" not in request["missing"]


def test_carrier_reason_does_not_change_the_request_digest():
    """A host-specific reason is environment-derived and must not invalidate
    an approved mandate -- `REQUEST_DIGEST_FIELDS` excludes it by design."""
    with_reason = _request(engine_registered=False, engine_unavailable_reason="no carrier here")
    without = _request(engine_registered=True)

    assert with_reason["request_id"] == without["request_id"]
