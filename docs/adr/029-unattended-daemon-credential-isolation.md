# ADR-029: Unattended daemon credential isolation — allowlisted subprocess env, shared launch-discipline helper, broker as read-only caller

**Status:** Proposed
**Date:** 2026-08-20
**Deciders:** Rikard Andersson (operator), with the six open questions resolved by Codex per operator direction
**Technical Story:** (internal design archive)

## Context

(internal design archive) designs
a long-running, largely unattended daemon that scans GitHub Issues, routes
them to an engine, and dispatches through `Coordinator` for hours at a
time. That spec explicitly deferred its own credential/security model as
"sub-project 2 of 3," pending knowledge of what the daemon actually needs
to access.

Two concrete facts were confirmed by reading the code this session,
sharpening the threat model beyond prior brainstorming:

1. `invoke_hermes()` and `CodexAdapter.invoke()` both call
   `subprocess.run(argv, ...)` with **no `env=` argument** — Python's
   default inherits the entire calling process's environment into every
   engine subprocess. Whatever the daemon process holds (a GitHub token,
   a Cortxt inference key, anything an operator's shell or a scheduled
   task happens to carry) is handed to every dispatch, unfiltered.
2. The Windows npm-shim shell-injection class fixed for `CodexAdapter`
   this session (`.cmd` executables routing argv through `cmd.exe`
   internally regardless of `shell=False`) generalizes to every future
   adapter (Buzz, Deepseek, Langchain per the roadmap) unless the fix is
   extracted into something every adapter is required to use, not left as
   a one-off patch inside `CodexAdapter`.

The threat model changes qualitatively once dispatch happens unattended:
a human operator today chooses to run one command with one prompt in one
terminal session; the daemon dispatches many times, unattended, against
issue content the operator has not read turn-by-turn. Any latent
credential-isolation gap is exercised far more often, with far less
chance a human notices something wrong before it happens.

## Decision

**R1 — Explicit allowlisted `env=` on every engine-adapter subprocess
call.** A shared helper, modeled on the existing
`subprocess_sandbox.child_env()` pattern, builds the child environment
from a deliberate allowlist — never `os.environ.copy()`, never Python's
default inherit-everything behavior. `invoke_hermes()` and
`CodexAdapter.invoke()` both gain an explicit `env=` argument built this
way; every future `EngineAdapter` implementation is required to do the
same. **LLM/engine API keys do not belong in this allowlist at all** —
Hermes and Codex each already manage their own credential lifecycle
independently of the daemon's process environment. v1 allowlist contents:
`PATH`, `SYSTEMROOT`, `WINDIR`, `COMSPEC`, `PATHEXT`, `TEMP`, `TMP`,
`USERPROFILE`, `HOME`, `LOCALAPPDATA`, `APPDATA`, plus `CODEX_HOME` for
Codex only and Hermes's own documented config-home variable for Hermes
only. Proxy, GitHub, cloud, and engine API-key variables stay excluded
unless a specific, tested task shape proves a concrete need.

**R2 — Shared subprocess-launch-discipline helper, required for every
adapter.** `CodexAdapter`'s shim-resolution fix (resolve past `.cmd`/
`.bat` to the real interpreter, `shell=False` unconditionally, argv list
never a joined string) is extracted into a shared, adapter-agnostic
helper every new `EngineAdapter` implementation must call rather than
reimplementing `subprocess.run(["enginename", ...])` directly. This
converts "found live, fixed once" into "structurally required" — unit
tests did not catch any of this session's three E2E bugs, including this
one; a shared, tested helper is a stronger guarantee than a per-adapter
memory of the incident.

**R3 — Daemon becomes a distinct `CredentialBroker` caller identity,
read-only.** If the daemon needs a broker-held credential, it calls
`CredentialBroker.inject()` with `requesting_runtime="daemon"` and an
explicit `purpose` string per call site — never a broad "give the daemon
everything" grant. `store()` remains categorically out of the daemon's
reach; `NotOperatorConfirmedError`'s existing invariant already prevents
the daemon from persisting a credential even if a future bug tried to.
For v1, the daemon's GitHub polling token is a **narrowly-scoped, raw
environment variable, excluded from the R1 engine-subprocess allowlist**
(visible to the daemon's own GitHub API calls, never forwarded to an
engine subprocess) — not yet brought under `CredentialBroker`, deferred
until rotation or broader GitHub scope is actually needed.

**R4 — Least-privilege scoping unit: `engine_id` × `task_shape`.** Reuses
`EngineManifest.task_shapes` × the selected engine's `engine_id`
(`routing/engine_manifest.py`) as the credential-scoping axis — the same
taxonomy the daemon's own Autonomy model already uses for its unattended-
mode unlock, so the two mechanisms stay coherent instead of drifting to
different units.

**Trust marker at the adapter boundary.** `EngineAdapter.invoke()`'s
protocol gains a trust classification (`trusted_operator` /
`untrusted_issue`, an enum rather than a bare boolean) threaded through
every call site, distinguishing an operator-typed interactive prompt from
daemon-sourced issue-body text. The Evidence Gate's downstream
self-report skepticism catches a false self-report *after* the fact; it
does not address prompt-driven tool misuse *during* execution, so it is
not sufficient on its own — this is ADR-026 protocol-shape territory,
implemented alongside R1/R2.

**DPAPI failure handling.** On a mid-run DPAPI decrypt failure (e.g. a
logout/relogin or locked-workstation transition invalidating the
session-bound key), the daemon **freezes only the affected track**, not
the whole loop — matching the Evidence Gate's existing
freeze-one-continue-others pattern. It emits an operator-visible error
and requires explicit operator action before retrying decryption.

**Deferred to v2:** full daemon-process hardening (separate OS account,
privilege separation, process sandboxing of the daemon itself). v1 stays
an operator-started process; R1 (explicit subprocess env), R3 (read-only
broker access), R4 (credential scoping), and auditable failure handling
are its hardening surface.

## Consequences

### Positive
- Closes a credential-leakage gap (T1) that already exists today in the
  interactively-invoked path, not just a hypothetical daemon risk —
  fixing `invoke_hermes()`/`CodexAdapter.invoke()`'s missing `env=`
  benefits every current call site, not only the future daemon.
- R2 converts a fixed-once bug class into a structurally-enforced
  discipline before the next npm/node-based adapter (Buzz, Deepseek,
  Langchain) ships, rather than after it repeats the same incident.
- R4 keeps credential scoping and autonomy-unlock scoping on the same
  taxonomy instead of two drifting concepts.

### Negative
- The daemon's GitHub token stays a raw environment variable in v1 —
  no audit trail or revocation-without-code-change until it is later
  migrated under `CredentialBroker`, a deliberately accepted gap.
- The `trusted_operator`/`untrusted_issue` marker changes
  `EngineAdapter.invoke()`'s protocol shape (ADR-026 territory) and must
  be threaded through every adapter and call site, not just the daemon's.

### Risks
- DPAPI's user-login-session-bound key means R3's broker-mediated
  injection stops working entirely if a future revision makes the daemon
  a background/service-account process (not auto-started at login/boot,
  no other account) — flagged, not yet re-examined, must be revisited
  before any such change ships.
- Full daemon-process hardening is explicitly deferred to v2 — a
  compromised v1 daemon process, while unable to leak allowlist-excluded
  secrets to engine subprocesses, can still act maliciously with whatever
  it does legitimately hold (its own GitHub token, its own process
  privileges) for the full multi-hour run.

## Alternatives Considered
1. **Give the daemon the same unrestricted env inheritance as today's
   interactive CLI path** — Rejected: qualitatively worse once dispatch
   is unattended and repeated many times against unreviewed issue
   content, per the threat-model discussion above.
2. **Route the daemon's GitHub token through `CredentialBroker` from
   v1** — Rejected for v1: makes the daemon the first production caller
   of `inject()`, a "first live user" risk worth taking deliberately
   later rather than by default now; a narrowly-scoped raw env var is
   sufficient for read-only polling.
3. **Full daemon-process hardening (separate OS account, privilege
   separation) in v1** — Rejected as premature: a larger change than this
   ADR's scope of "what credentials cross into engine subprocesses";
   deferred to v2 once R1/R3/R4 are proven.

## Validation
- [ ] Implementation matches decision — **not yet implemented**; this ADR
      formalizes a spec-only design, no code has shipped against it.
- [ ] Tests cover decision boundaries — pending implementation.

## Open Questions (deferred, not blocking this ADR)
- Concrete allowlist contents beyond v1's list, as further engines
  (Buzz, Deepseek, Langchain) are added — each needs its own "verified
  live" check of what it actually requires to launch.
- Whether the trust-marker enum needs more than two values as more
  untrusted input sources appear (e.g. a webhook payload, a third-party
  API response) beyond `trusted_operator`/`untrusted_issue`.
