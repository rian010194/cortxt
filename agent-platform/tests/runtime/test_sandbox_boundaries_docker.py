"""Container boundary proof (design spec decision 3 and decision 7's Network row).

THESE ARE THE TESTS THAT PROVE FAS 3'S CONTAINMENT CLAIM. They require a
running Docker daemon and are excluded from the default suite by the
docker_required marker. Fas 3 is NOT proven until this file has been seen green
in an environment with a live daemon — this machine with Docker Desktop
started, or GitHub Actions' hosted Ubuntu runner (see Task 13).

Each test drives the single allowlisted command (`run_pytest`) against a
purpose-built probe workspace: the probe IS a pytest test file. That keeps the
allowlist at exactly one entry — no test-only escape hatch is added to the
production allowlist.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from runtime.execution.subprocess_sandbox import ExecutionSandbox

pytestmark = pytest.mark.docker_required


def _probe(tmp_path: Path, body: str) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "test_probe.py").write_text(body, encoding="utf-8")
    return work


def test_a_passing_probe_exits_zero(tmp_path, sandbox_image):
    work = _probe(tmp_path, "def test_ok():\n    assert True\n")
    result = ExecutionSandbox(image=sandbox_image).run("run_pytest", work)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.timed_out is False


def test_a_failing_probe_exits_non_zero(tmp_path, sandbox_image):
    work = _probe(tmp_path, "def test_fails():\n    assert 1 == 2\n")
    result = ExecutionSandbox(image=sandbox_image).run("run_pytest", work)
    assert result.exit_code != 0


def test_outbound_tcp_connect_fails_at_the_os_level(tmp_path, sandbox_image):
    """The A4 proof: --network none means no network namespace access at all.

    This asserts the OS refused the connection, not merely that application
    code chose not to dial out.
    """
    work = _probe(tmp_path, (
        "import socket\n"
        "\n"
        "\n"
        "def test_outbound_connect_is_refused_by_the_os():\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    sock.settimeout(5)\n"
        "    try:\n"
        "        sock.connect(('1.1.1.1', 443))\n"
        "    except OSError as error:\n"
        "        assert True, error\n"
        "    else:\n"
        "        raise AssertionError('outbound TCP connect SUCCEEDED inside the sandbox')\n"
        "    finally:\n"
        "        sock.close()\n"
    ))
    result = ExecutionSandbox(image=sandbox_image).run("run_pytest", work)
    assert result.exit_code == 0, (
        "NETWORK ISOLATION BOUNDARY BROKEN — the probe reached the network:\n"
        + result.stdout + result.stderr
    )


def test_dns_resolution_fails_inside_the_sandbox(tmp_path, sandbox_image):
    work = _probe(tmp_path, (
        "import socket\n"
        "\n"
        "\n"
        "def test_dns_is_unavailable():\n"
        "    try:\n"
        "        socket.getaddrinfo('example.com', 443)\n"
        "    except OSError:\n"
        "        assert True\n"
        "    else:\n"
        "        raise AssertionError('DNS resolution SUCCEEDED inside the sandbox')\n"
    ))
    result = ExecutionSandbox(image=sandbox_image).run("run_pytest", work)
    assert result.exit_code == 0, result.stdout + result.stderr


def test_host_credentials_are_absent_from_the_child_environment(tmp_path, monkeypatch, sandbox_image):
    """Proving test for the "Credentials leak into the child process" row."""
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "canary-must-not-leak")
    monkeypatch.setenv("KIMI_API_KEY", "canary-must-not-leak")
    monkeypatch.setenv("GH_TOKEN", "canary-must-not-leak")
    work = _probe(tmp_path, (
        "import json\n"
        "import os\n"
        "\n"
        "\n"
        "def test_dump_env():\n"
        "    with open('/workspace/env.json', 'w', encoding='utf-8') as handle:\n"
        "        json.dump(dict(os.environ), handle)\n"
    ))
    result = ExecutionSandbox(image=sandbox_image).run("run_pytest", work)
    assert result.exit_code == 0, result.stdout + result.stderr
    dumped = (work / "env.json").read_text(encoding="utf-8")
    assert "canary-must-not-leak" not in dumped
    assert "CORTXT_INFERENCE_API_KEY" not in dumped
    assert "KIMI_API_KEY" not in dumped
    assert "GH_TOKEN" not in dumped


def test_a_probe_that_sleeps_past_the_timeout_is_killed(tmp_path, sandbox_image):
    work = _probe(tmp_path, "import time\n\n\ndef test_sleeps():\n    time.sleep(120)\n")
    sandbox = ExecutionSandbox(image=sandbox_image, timeout_seconds=10)
    result = sandbox.run("run_pytest", work)
    assert result.timed_out is True
    assert result.elapsed_ms < 60_000  # bounded, not 120 s


def test_output_over_the_cap_is_truncated_with_a_flag(tmp_path, sandbox_image):
    """JUDGMENT CALL beyond J2/J3, made during Step 5 execution: pytest's default
    capture mode buffers a passing test's stdout and only echoes it to the real
    fd on FAILURE (verified locally: a bare ``print('x' * 200000)`` in a passing
    test produces zero bytes of real subprocess stdout under ``-q``). The probe
    must therefore fail so its captured output is flushed to the real stdout the
    sandbox observes — this exercises the same truncation path, just via a
    failing probe instead of a passing one. The non-Docker unit test
    ``test_run_truncates_output_over_the_cap_and_flags_it`` already proves the
    truncation mechanism itself against a fake runner independent of this."""
    work = _probe(tmp_path, "def test_noisy():\n    print('x' * 200000)\n    assert False\n")
    result = ExecutionSandbox(image=sandbox_image, max_output_bytes=1024).run("run_pytest", work)
    assert result.truncated is True
    assert len(result.stdout) <= 1024


def test_the_workspace_is_the_only_writable_path_visible(tmp_path, sandbox_image):
    """The container sees /workspace and nothing from the host repo."""
    work = _probe(tmp_path, (
        "import os\n"
        "\n"
        "\n"
        "def test_repo_is_not_mounted():\n"
        "    assert sorted(os.listdir('/workspace')) == ['test_probe.py']\n"
        "    assert not os.path.exists('/workspace/agent-platform')\n"
    ))
    result = ExecutionSandbox(image=sandbox_image).run("run_pytest", work)
    assert result.exit_code == 0, result.stdout + result.stderr
