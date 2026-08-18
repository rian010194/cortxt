from __future__ import annotations

from routing.discovery import RuntimeStatus, discover_installed_runtimes

KNOWN_RUNTIMES = {"hermes", "buzz", "claude-code", "codex", "pi"}


def test_discover_returns_a_status_for_every_known_runtime():
    statuses = discover_installed_runtimes(which=lambda _name: None)
    assert {s.runtime_id for s in statuses} == KNOWN_RUNTIMES


def test_discover_marks_runtime_installed_when_which_finds_it():
    def fake_which(name: str) -> str | None:
        return r"C:\fake\hermes.exe" if name == "hermes" else None

    statuses = discover_installed_runtimes(which=fake_which)
    by_id = {s.runtime_id: s for s in statuses}
    assert by_id["hermes"].installed is True
    assert by_id["hermes"].path == r"C:\fake\hermes.exe"
    assert by_id["buzz"].installed is False
    assert by_id["buzz"].path is None


def test_discover_never_touches_credentials_or_env_values():
    """Auto-discovery is read-only PATH detection, per the Fas 1 threat
    model's boundary between the broker (credentials) and discovery
    (presence only). A RuntimeStatus must never carry a raw env value."""
    statuses = discover_installed_runtimes(which=lambda _name: "/usr/bin/fake")
    for status in statuses:
        assert not hasattr(status, "env")
        assert not hasattr(status, "credential")
        assert not hasattr(status, "token")


def test_runtime_status_is_immutable():
    status = RuntimeStatus(runtime_id="hermes", installed=True, path="/x")
    with __import__("pytest").raises(Exception):
        status.installed = False  # type: ignore[misc]
