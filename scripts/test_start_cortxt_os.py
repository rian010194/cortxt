#!/usr/bin/env python3
"""Offline fake-injection tests for the documented Cortxt OS start path.

Every check here runs with `action_host.main` injected, so no test binds a
real server, imports the host, or touches the registry. The one real socket in
this file is the *listener the script must refuse*, not a host.
"""
import contextlib
import io
import os
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace

import start_cortxt_os as s

REPO_ROOT = Path(__file__).resolve().parents[1]

fail = []


def check(name, condition):
    print(f"  {'ok' if condition else 'FAIL':4} {name}")
    if not condition:
        fail.append(name)


def exploding_host(reason):
    """A host whose `main` must never be reached.

    A refusal that silently stopped firing would otherwise look identical to a
    refusal that fired: both end before the server starts.
    """
    def _boom(**kwargs):
        raise AssertionError(f"action_host.main was reached but {reason}")
    return SimpleNamespace(main=_boom, AGENT_PLATFORM_DIR=REPO_ROOT / "agent-platform")


def recording_host(exit_code=0, agent_platform_dir=None):
    calls = []

    def _main(**kwargs):
        calls.append(kwargs)
        return exit_code
    return SimpleNamespace(
        main=_main, calls=calls,
        AGENT_PLATFORM_DIR=agent_platform_dir or (REPO_ROOT / "agent-platform"))


@contextlib.contextmanager
def run_script(argv, *, cwd=REPO_ROOT, env=None, **kwargs):
    """Run `main(argv)` with a chosen cwd and environment, capturing output.

    Yields a namespace with `code`, `out` and `err`; both streams are captured
    because the secret check has to prove a sentinel appears in neither.
    """
    prior_cwd = Path.cwd()
    prior_env = dict(os.environ)
    out, err = io.StringIO(), io.StringIO()
    result = SimpleNamespace(code=None, out="", err="")
    try:
        os.chdir(cwd)
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result.code = s.main(argv, **kwargs)
        yield result
    finally:
        os.chdir(prior_cwd)
        os.environ.clear()
        os.environ.update(prior_env)
        result.out, result.err = out.getvalue(), err.getvalue()


def free_route_env(**extra):
    """A minimal environment with the free route complete."""
    env = {"PATH": os.environ.get("PATH", ""),
           "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "CORTXT_FREE_PROVIDER": "nous",
           "CORTXT_FREE_MODEL": "upstage/solar-pro4:free"}
    env.update(extra)
    return env


def test_refuses_when_port_already_bound():
    """The central refusal: exactly one listener.

    The listener is real and the probe is a real connect, because the thing
    being tested is precisely that the script does not infer occupancy from a
    bind failure -- `_ReusableThreadingHTTPServer` sets `allow_reuse_address`,
    so on win32 a bind against this very socket can succeed.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((s.LOOPBACK, 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with run_script([f"--port={port}", "--no-free-route"],
                        host=exploding_host("a listener was already bound")) as r:
            pass
    check("a bound port refuses with exit 2", r.code == 2)
    check("the refusal names the port", str(port) in r.out)
    check("the refusal is prefixed and says it is refusing",
          r.out.startswith(f"{s.PREFIX} refusing to start:"))
    check("the refusal says what to do, not only what is wrong",
          "Ctrl+C" in r.out)
    # The probe is per-port but the registry is not: it resolves from the host
    # module's location. Offering --port here would send the operator into the
    # two-hosts-one-registry state the message exists to prevent.
    check("the refusal does not offer another --port as the fix",
          "Do not simply move to another" in r.out and "runs.json" in r.out)


def test_refuses_outside_repo_root():
    with tempfile.TemporaryDirectory() as tmp:
        with run_script(["--no-free-route"], cwd=tmp,
                        host=exploding_host("cwd was not the repository root"),
                        connect=_never_connects) as r:
            pass
    check("a cwd that is not the repository root refuses with exit 2", r.code == 2)
    check("the refusal names the missing marker",
          "agent-platform/widget/action_host.py" in r.out)
    check("the refusal cross-references why cwd matters",
          "docs/agents/work-launcher.md" in r.out)


def test_refuses_without_free_route_env():
    env = free_route_env()
    del env["CORTXT_FREE_PROVIDER"]
    del env["CORTXT_FREE_MODEL"]
    with run_script([], env=env, host=exploding_host("the free route was incomplete"),
                    connect=_never_connects) as r:
        pass
    check("an incomplete free route refuses with exit 2", r.code == 2)
    check("the refusal names CORTXT_FREE_PROVIDER", "CORTXT_FREE_PROVIDER" in r.out)
    check("the refusal names CORTXT_FREE_MODEL", "CORTXT_FREE_MODEL" in r.out)
    check("the refusal offers the escape hatch", "--no-free-route" in r.out)
    check("the example is labelled an example, not a default",
          "not a default" in r.out)


def test_refuses_without_hermes_on_path():
    with run_script([], env=free_route_env(),
                    host=exploding_host("hermes was not on PATH"),
                    connect=_never_connects, which=lambda name: None) as r:
        pass
    check("a missing hermes refuses with exit 2", r.code == 2)
    check("the refusal names hermes", "hermes" in r.out)


def test_no_free_route_skips_env_refusal():
    env = free_route_env()
    del env["CORTXT_FREE_PROVIDER"]
    del env["CORTXT_FREE_MODEL"]
    host = recording_host()
    with run_script(["--no-free-route"], env=env, host=host, connect=_never_connects,
                    which=_no_hermes) as r:
        pass
    check("--no-free-route reaches the host with both variables unset", r.code == 0)
    check("--no-free-route skips the hermes check too", len(host.calls) == 1)
    # The flag skips two checks; it does not unmount POST /api/action, and
    # `action_host` has no flag that would. Help text that said "read-only"
    # would drop the caution the mutation route requires.
    flag_help = [a.help for a in s.build_parser()._actions if "--no-free-route" in a.option_strings]
    check("--no-free-route does not describe the host as read-only",
          len(flag_help) == 1 and "POST /api/action is mounted either way" in flag_help[0])
    check("the free-route line says it is disabled, and names the flag",
          "free route: disabled (--no-free-route)" in r.out)
    check("no unset variable is reported as a value",
          "provider=" not in r.out and "model=" not in r.out)


def test_never_prints_env_values_of_secrets():
    sentinel = "sk-do-not-print-me-4a91c7"
    env = free_route_env(CORTXT_FREE_API_KEY=sentinel, GITHUB_TOKEN=sentinel)
    with run_script([], env=env, host=recording_host(), connect=_never_connects,
                    which=_hermes_present) as r:
        pass
    check("the successful start path exits with the host's code", r.code == 0)
    check("the sentinel secret appears nowhere on stdout", sentinel not in r.out)
    check("the sentinel secret appears nowhere on stderr", sentinel not in r.err)
    check("provider and model -- routing configuration, not secrets -- are reported",
          "provider=nous" in r.out and "model=upstage/solar-pro4:free" in r.out)


def test_passes_port_and_flags_through():
    host = recording_host(exit_code=7)
    spec = REPO_ROOT / "agent-platform" / "widget_contract" / "specs" / "decisions-0.1.yaml"
    with run_script(["--port=9911", f"--spec={spec}", "--require-commit=abc123",
                     "--require-clean", "--no-free-route"],
                    host=host, connect=_never_connects) as r:
        pass
    check("the script returns action_host.main's exit code unchanged", r.code == 7)
    check("action_host.main was called exactly once", len(host.calls) == 1)
    call = host.calls[0] if host.calls else {}
    check("port is passed through", call.get("port") == 9911)
    check("spec_path is passed through", call.get("spec_path") == spec)
    check("require_commit is passed through", call.get("require_commit") == "abc123")
    check("require_clean is passed through", call.get("require_clean") is True)
    check("the url line reports the port actually passed to the host",
          "http://127.0.0.1:9911/index.html" in r.out)


def test_registry_line_reports_the_hosts_own_resolution_not_cwd():
    """Correction 3: cwd selects which module is imported, never where it reads.

    A registry line built from cwd would name a file the host never opens.
    Here the injected host resolves somewhere cwd does not point, and the
    printed path must follow the host.
    """
    with tempfile.TemporaryDirectory() as tmp:
        elsewhere = Path(tmp) / "some-other-agent-platform"
        host = recording_host(agent_platform_dir=elsewhere)
        with run_script(["--no-free-route"], host=host, connect=_never_connects) as r:
            pass
        expected = elsewhere / ".dispatch" / "runs.json"
    check("the registry line follows the host's AGENT_PLATFORM_DIR", str(expected) in r.out)
    check("the registry line does not name a cwd-relative path",
          str(REPO_ROOT / "agent-platform" / ".dispatch") not in r.out)
    check("a registry that is not there is reported as absent, not omitted",
          "(exists: no)" in r.out)


def test_success_lines_are_exactly_the_five_documented_ones():
    with run_script([], env=free_route_env(), host=recording_host(),
                    connect=_never_connects, which=_hermes_present) as r:
        pass
    lines = [line for line in r.out.splitlines() if line.strip()]
    check("exactly five lines are printed before the host takes over", len(lines) == 5)
    check("every line carries the prefix",
          all(line.startswith(f"{s.PREFIX} ") for line in lines))
    prefixes = ["repo root:", "commit:", "registry:", "free route:", "url ("]
    check("the lines are in the documented order",
          all(line.startswith(f"{s.PREFIX} {want}")
              for line, want in zip(lines, prefixes)) and len(lines) == len(prefixes))
    check("the commit line reports a branch alongside the commit",
          len(lines) > 1 and "branch:" in lines[1])


def test_git_metadata_is_unknown_rather_than_guessed():
    def _explodes(*args, **kwargs):
        raise OSError("git is not installed")
    check("an unavailable git yields 'unknown'",
          s._git("rev-parse", "HEAD", cwd=REPO_ROOT, run=_explodes) == "unknown")

    def _fails(*args, **kwargs):
        return SimpleNamespace(returncode=128, stdout="", stderr="not a repository")
    check("a non-zero git yields 'unknown'",
          s._git("rev-parse", "HEAD", cwd=REPO_ROOT, run=_fails) == "unknown")


def _never_connects(address, timeout=None):
    raise OSError("nothing is listening")


def _no_hermes(name):
    raise AssertionError("shutil.which was consulted despite --no-free-route")


def _hermes_present(name):
    return f"/usr/bin/{name}"


def main():
    for name, fn in sorted(globals().items()):
        # `test_all_checks_pass` is the pytest wrapper around this very
        # function; collecting it here would recurse.
        if name.startswith("test_") and name != "test_all_checks_pass" and callable(fn):
            print(name)
            fn()
    print(f"\n{len(fail)} failure(s)")
    raise SystemExit(1 if fail else 0)


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script."""
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0, f"{len(fail)} check(s) failed: {fail}"
    assert not fail, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    main()
