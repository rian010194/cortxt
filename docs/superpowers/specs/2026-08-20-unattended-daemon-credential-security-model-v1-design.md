# Unattended daemon credential/security model v1 — design

Status: spec-only, open questions resolved (see Decisions section below,
Codex review directed by operator 2026-08-20); no implementation started —
this is sub-project 2 of the 2026-08-19 three-way split, deliberately
deferred until now
Date: 2026-08-20
Authority: architectural proposal for one bounded sub-project; does not
override `docs/security/credential-broker-threat-model.md` (Fas 1, the
threat model this design must satisfy) or ADR-026/027 (`EngineAdapter`
protocol, `EngineBroker`/`EngineContext`). Does not authorize implementation
— per this project's working rules, a credential/security model for an
unattended daemon requires a shown-and-approved plan before any code change.
Related:
- `docs/superpowers/specs/2026-08-19-supervisor-daemon-v1-design.md`
  (sub-project 1, its own Non-goals section explicitly defers this work here
  and names it "sub-project 2 of 3")
- `docs/security/credential-broker-threat-model.md` (Fas 1 threat model;
  `CredentialBroker` at `agent-platform/security/credential_broker.py`
  implements its §3.1/§3.2 recommendations already, per its own module
  docstring)
- `agent-platform/security/credential_broker.py`, `agent-platform/security/
  dpapi.py` (existing, implemented, unit-tested; **not yet called from any
  production code path** — confirmed by grep, only test files construct
  `CredentialBroker()`)
- `agent-platform/routing/hermes_invoker.py:invoke_hermes()` (confirmed live
  gap: its `subprocess.run(argv, ...)` call has no `env=` parameter at all,
  inheriting the entire calling process's environment for every dispatch)
- `agent-platform/runtime/adapters/codex_adapter.py` (this session's
  `.cmd`-shim shell-injection fix — same subprocess-launch-discipline class
  of bug this spec must prevent recurring in every future engine adapter)
- `agent-platform/runtime/execution/subprocess_sandbox.py` (`child_env()` —
  the allowlist-env pattern already proven for the Fas 3 coding-agent sandbox;
  this spec extends the same principle to engine-adapter subprocesses, not a
  new invention)
- `.hermes/dispatch/handoff-20260819b.md` (prior brainstorming pass on this
  exact sub-project — threat model already agreed there as "both least-
  privilege AND prompt-injection-from-issue-content, equally important";
  paused on a scope question this spec resolves, see Decisions below)

## Problem

`docs/superpowers/specs/2026-08-19-supervisor-daemon-v1-design.md` (sub-
project 1) designs a long-running, largely unattended daemon loop that scans
GitHub Issues, calls `route()` to select an engine, and dispatches work
through `Coordinator` — for hours at a time, with human review concentrated
at the start and end rather than every checkpoint. That spec explicitly
defers its own credential/security model as a Non-goal, naming it
"sub-project 2 of 3," because — correctly — its design depends on what the
daemon actually needs to access, which wasn't yet known.

The daemon is now designed (v1, sub-project 1, approved 2026-08-19). This
spec is that follow-on: what the daemon actually touches, the threat model
for an always-on unattended process making dispatch decisions without an
operator watching each one, and the isolation approach.

Two concrete facts, found this session, sharpen the threat model beyond what
the prior brainstorming pass (handoff-20260819b) had confirmed:

1. **The env-inheritance gap is real and already shipped.**
   `invoke_hermes()` calls `subprocess.run(argv, capture_output=True, ...)`
   with no `env=` argument — Python's default behavior inherits the entire
   parent process's environment into the Hermes subprocess. Whatever the
   daemon process holds in its own environment (a GitHub token to poll
   issues, a Cortxt inference key, any other secret an operator's shell or a
   scheduled-task definition happens to carry) is handed to every single
   Hermes dispatch, unfiltered. `CodexAdapter.invoke()` has the same
   property — its `subprocess.run(...)` call also passes no `env=`.
2. **The Windows shell-injection class fixed for `CodexAdapter` this session
   generalizes to every future engine adapter**, not just Codex. npm-shim
   (`.cmd`) executables on Windows route argv through `cmd.exe` internally
   regardless of `shell=False`; the fix (resolve past the shim to the real
   `node.exe`/interpreter pair) had to be adapter-specific this time because
   nothing enforces the pattern for adapters not yet written. The roadmap
   (`project_cortxt_multi_engine_roadmap` memory) names Buzz, Deepseek, and
   Langchain as future engines — several are npm/node-based tooling and will
   hit the identical shim-routing risk unless this spec's recommendation is
   applied before, not after, each one ships.

Both gaps predate the daemon: they exist today, in the interactively-invoked
CLI path (`cortxt orchestrator chat`). But the threat model changes
qualitatively once dispatch happens unattended: today a human operator
chose to run a specific command with a specific prompt in a specific
terminal session; the daemon will dispatch many times, unattended, against
issue content the operator has not read turn-by-turn. Any latent gap in
credential isolation is exercised far more often, with far less human
opportunity to notice something wrong before it happens.

## What the daemon actually needs (credential/secret inventory)

Working from the supervisor-daemon-v1-design.md data flow (GitHub Issues →
`route()` → `Coordinator` → engine dispatch → Evidence Gate → status file):

| Need | Currently held by | Notes |
|---|---|---|
| GitHub API access (poll `workflow:ready` issues, read issue body/labels) | Operator's environment today (e.g. `GH_TOKEN`), no daemon-specific identity | Daemon needs read (and minimally, claim/label-write) scope only — never full repo write |
| Hermes dispatch | Hermes's own credential system (`hermes secrets`, Bitwarden/1Password → `~/.hermes/.env`), invoked as a subprocess by `invoke_hermes()` | Per handoff-20260819b: "fullständigt miljö-arv till Hermes-subprocessen behövs sannolikt inte alls för LLM-nycklar" — Hermes already manages its own LLM keys; the daemon process's env has no legitimate reason to also carry them into the Hermes subprocess |
| Codex dispatch | Codex CLI's own account/login state (not inspected this session; likely a local credential file or OS keychain Codex manages itself) | Same principle: `CodexAdapter` should not need to forward daemon-process env into `codex exec` for Codex to authenticate itself |
| `CredentialBroker`-held credentials (future: any third-party bearer token the admin surface stores) | `agent-platform/security/credential_broker.py`, DPAPI-encrypted at rest, user-login-session-bound key | Not currently called from any production path — the daemon would be the *first* real consumer if it needs broker-mediated injection |
| Cortxt's own inference/session infra (whatever `CORTXT_INFERENCE_API_KEY`-shaped variables exist) | Operator's shell environment | Same inheritance-gap exposure as GitHub token |

The daemon itself is unattended; **the Evidence Gate escalation to a human,
and the write path of `CredentialBroker.store()`, are not** — both stay
attended by design (supervisor-daemon-v1-design.md's autonomy model;
`credential_broker.py`'s `NotOperatorConfirmedError` invariant). This spec
does not change either of those; it only closes the gap in what the daemon
process itself is allowed to hand downstream while it runs unattended.

## Threat model

Per handoff-20260819b, the prior brainstorming pass already fixed on two
threats of equal weight. This spec confirms both and adds a third found
this session.

### T1 — Least-privilege: daemon-process credential leakage to subprocesses

**Threat.** The daemon process's own environment — whatever secrets an
operator's launching shell, a scheduled task, or a `.env` file happen to
populate it with — is inherited wholesale by every engine subprocess it
spawns, because neither `invoke_hermes()` nor `CodexAdapter.invoke()` passes
an `env=` argument to `subprocess.run()`. A single credential (say, a
GitHub token with write access, or a Cortxt inference key) placed in the
daemon's environment for one legitimate purpose becomes visible to every
dispatched engine call for every issue, for the daemon's entire multi-hour
run. An engine's own logging, a crash dump, or a compromised/hijacked engine
CLI process now has a much larger blast radius than the one secret it
actually needed.

This is broader than bearer credentials alone (confirmed by Hermes review of
this draft): the same unfiltered inheritance also carries `PATH` (an engine
subprocess can be tricked into resolving a different binary than intended
if `PATH` is attacker-influenceable upstream), `NODE_PATH`/`PYTHONPATH`
(relevant given Codex's Node.js dependency and Hermes's own Python tooling —
either could load an unintended module), and `HTTP_PROXY`/`HTTPS_PROXY`
(silently redirecting an engine's outbound traffic through an unintended
proxy). R1's allowlist must be scoped by "what this engine CLI needs to
launch and find its own config," not just "no bearer secrets" — the two are
related but not identical, and the implementation plan should treat both.

This is exactly the class of bug `subprocess_sandbox.py`'s `child_env()`
already exists to prevent for the Fas 3 Docker sandbox path — but that
protection was never extended to the engine-adapter subprocess path, which
didn't exist yet when `child_env()` was written.

### T2 — Prompt injection from issue content

**Threat.** The daemon's own scan loop reads GitHub Issue title/body text
and, via `route()` → `Coordinator` → the selected engine adapter, feeds it
into an LLM prompt with no human review before dispatch (that's the entire
point of "unattended" per supervisor-daemon-v1-design.md). Issue content is
externally writable by anyone with issue-creation permission on the repo —
today the operator, but the daemon's design does not assume that stays true
forever, and even an operator's own issue text could unintentionally contain
something engine-hostile (a pasted error log with shell metacharacters, a
code block that looks like an instruction). An issue body could attempt to:

- instruct the invoked engine to read and echo back environment variables
  (compounding directly with T1 if it succeeds — the daemon's env leak
  becomes exfiltratable through the engine's own transcript/output),
- inject shell metacharacters intended to reach a subprocess shell layer
  (mitigated today by every existing adapter using `shell=False` with argv
  lists — the discipline must hold for every future adapter too, see T3),
  or
- instruct the engine to fabricate a false "completed" self-report — this is
  the #174/#175 failure mode supervisor-daemon-v1-design.md's Evidence Gate
  already targets structurally (no self-reported status without a complete
  `ResultEnvelope` and matching `artifact_policy`), so this spec does not
  redesign that mitigation, only confirms it also covers the injected-intent
  case, not just an honest engine's own mistake.

**What this spec does not yet operationalize (flagged by Hermes review of
this draft, correctly):** naming T2 as a threat is not the same as stating
the structural guard against it. The daemon's issue-body text becomes the
`prompt` argument to `invoke_hermes()`/`CodexAdapter.invoke()` verbatim —
both already pass it as a single argv element under `shell=False` (no shell
metacharacter risk at the OS-process boundary, that part is sound today),
but nothing today distinguishes "trusted operator-typed prompt" from
"untrusted issue-body text" at the call site itself; both flow through the
identical `invoke()` signature. Whether that distinction needs to be made
structural (e.g. a `trusted: bool` flag threaded through so an adapter or a
future policy layer can treat the two differently) or is adequately handled
by the Evidence Gate's downstream self-report skepticism (T2's third bullet)
is left as an explicit open question below (#6) rather than decided here —
this spec's R1–R4 close T1/T3, not T2.

### T3 — Subprocess launch discipline for future adapters (generalizing this session's `CodexAdapter` fix)

**Threat.** Any future `EngineAdapter` (Buzz, Deepseek, Langchain per the
roadmap) that is npm/node-based on Windows and is implemented by directly
calling `subprocess.run(["enginename", ...])` will silently route through
`cmd.exe`'s shim-resolution behavior exactly as `codex.cmd` did, exposing
prompt text (now issue-derived, unattended, and unreviewed per T2) to shell
metacharacter interpretation before the engine ever receives it. This was
found and fixed for Codex specifically this session; nothing currently
prevents the same bug shipping again for the next adapter, because the fix
lives inside `CodexAdapter._default_codex_launch_prefix()`, not in a shared
helper every adapter is required to use.

### T4 — Blast radius of a compromised long-running process

**Threat, named but only partially addressed by this spec.** A daemon that
runs unattended for 5–6 hours is a higher-value, longer-lived target than a
one-shot interactively-invoked CLI call: an attacker (or a bug) that
compromises the daemon process has a much longer window to act, across many
dispatches, than compromising one `cortxt orchestrator chat` invocation.
`docs/security/credential-broker-threat-model.md` §3.3 already requires
isolating the broker's trust from any component that consumes it and
failing closed on integrity doubt; this spec's contribution is scoping what
the daemon process is *structurally capable of leaking even if fully
compromised* (T1's fix bounds this — a compromised daemon with an empty
subprocess env allowlist cannot leak what it never receives in the first
place for that hop, though it can still act maliciously with whatever it
does legitimately hold). Full daemon-process hardening (privilege
separation, running as a distinct OS account, etc.) is flagged as an open
question below, not designed here — it is a larger change than this spec's
scope of "what credentials cross into subprocesses and how."

## Recommended isolation approach

This is a **minimal-change extension of patterns this codebase already
proved**, not a new component. Three of the four recommendations below
directly generalize code that already exists and is tested
(`subprocess_sandbox.child_env()`, `CodexAdapter`'s shim-bypass,
`CredentialBroker`'s purpose-bound `inject()`).

### R1 — Explicit allowlisted `env=` on every engine-adapter subprocess call

Add a shared helper (name TBD in the implementation plan, e.g.
`runtime/engine_subprocess_env.py:engine_child_env()`) modeled directly on
`subprocess_sandbox.child_env()`: build the child environment from a
deliberate allowlist, never `os.environ.copy()` and never Python's default
env-inherits-everything behavior. `invoke_hermes()` and
`CodexAdapter.invoke()` both gain an explicit `env=` argument using this
helper; any future adapter is required (by review convention, and ideally by
a shared base/test fixture) to do the same rather than each hand-rolling its
own `subprocess.run()` call. Stated as one discipline, not two: **every
`subprocess.run()` call inside an `EngineAdapter` implementation passes an
`env=` built from `engine_child_env()` (or an equivalent allowlist), with no
exceptions** — this closes T1 for both the currently-known adapters and any
future one in the same commit that adds the helper, rather than leaving a
per-adapter opt-in gap of the same shape T3 already found once.

The allowlist itself needs concrete content decided in the implementation
plan, but the guiding principle from handoff-20260819b's own finding
carries directly: **LLM/engine API keys do not belong in this allowlist at
all** — Hermes and Codex each already manage their own credential lifecycle
independently of the daemon's process environment (`hermes secrets`,
Codex's own login state). The allowlist should contain only what the engine
CLI genuinely needs to *run* (`PATH`, `SYSTEMROOT`/`COMSPEC` on Windows,
`HOME`/`USERPROFILE` so the engine can find its own config directory) —
the same minimal shape `_ENV_ALLOWLIST` already uses for the Docker sandbox
path, engine-specific config-path variables added only if a concrete engine
is proven (by the same "verified live" discipline ADR-022/026/027 already
require) to need one.

### R2 — Shared subprocess-launch-discipline helper, required for every adapter

Extract `CodexAdapter._default_codex_launch_prefix()`'s shim-resolution
pattern (resolve past `.cmd`/`.bat` to the real interpreter, `shell=False`
unconditionally, argv list never a joined string) into a shared,
adapter-agnostic helper any new `EngineAdapter` implementation calls rather
than reimplementing `subprocess.run(["enginename", ...])` directly. This
converts "found live, fixed once" into "structurally required," matching
this codebase's own stated lesson from this session's handoff: unit tests
did not catch any of the three E2E bugs found, including this one — a
shared, tested helper is a stronger guarantee than a per-adapter memory of
the incident.

### R3 — Daemon becomes a distinct `CredentialBroker` caller identity, read-only

If the daemon needs a broker-held credential at all (e.g. a GitHub token
scoped for issue polling, once brought under the broker rather than left in
raw process env — see Open questions, this is not decided here), it calls
`CredentialBroker.inject()` with `requesting_runtime="daemon"` and an
explicit `purpose` string per call site (e.g.
`purpose="github-issue-poll"`), never a broader "give the daemon everything
it might need" grant. This is already exactly what `inject()`'s existing
signature requires — no broker code change needed, only a decision to
route the daemon's credential need through it instead of a raw environment
variable. `store()` remains categorically out of the daemon's reach: nothing
in the daemon's design calls it, and `NotOperatorConfirmedError`'s existing
invariant (only an operator-facing path may set `operator_confirmed=True`)
already prevents the daemon from persisting a credential even if a future
bug tried to make it. Audit-log entries the broker already writes give a
distinct trail for daemon-initiated injects (`requesting_runtime="daemon"`)
versus operator-interactive ones, answering part of handoff-20260819b's
open "least-privilege unit" question at the *caller-identity* granularity;
per-dispatch granularity is addressed by R4.

### R4 — Least-privilege unit: `engine_id` × `task_shape`

Handoff-20260819b left this exact question open ("Fråga om enhet för
minsta-privilegium ... landade aldrig i ett bekräftat svar"). This spec's
concrete recommendation: reuse `EngineManifest.task_shapes` × the selected
engine's `engine_id` (`agent-platform/routing/engine_manifest.py`) as the
scoping unit for any future credential-scoping policy — the same taxonomy
`supervisor-daemon-v1-design.md`'s own Autonomy model already uses for its
unattended-mode unlock ("hermes engine, coding task_shape" earns its unlock
independently of "hermes engine, research task_shape"). This is not a new
invented axis; it is applying an axis this codebase already committed to
elsewhere in the same daemon design to the credential-scoping question too,
so the two mechanisms (autonomy unlock, credential scope) stay coherent
instead of drifting to different units. **Flagged for operator confirmation
below** — the prior brainstorming pass recommended this unit but never got
an explicit "yes" before the session reordered.

## Non-goals

- **Implementing any of R1–R4.** This document is spec-only per explicit
  instruction; no code changes accompany this commit.
- **Redesigning `CredentialBroker` or `dpapi.py`.** Both already satisfy the
  Fas 1 threat model's write-gating, purpose-binding, no-enumeration, and
  fail-closed requirements; this spec's R3 is a *new caller*, not a change
  to the broker's own interface or guarantees.
- **Full daemon-process hardening** (separate OS account, privilege
  separation, process sandboxing of the daemon itself) — named in T4 as a
  real but larger question, deliberately out of this spec's scope of
  "what credentials cross into engine subprocesses."
- **GitHub token acquisition/rotation mechanics** — whether/how a
  GitHub-scoped token becomes a `CredentialBroker` record at all is an open
  question below, not designed here.
- **Rebuilding the Evidence Gate's false-completion mitigation** (T2's third
  bullet) — supervisor-daemon-v1-design.md already designed it; this spec
  only confirms it also covers the injected-intent case.
- **Sub-project 3** (widget swimlane visualization) — unrelated, unaffected
  by this spec.

## Open questions (operator decision required)

1. **Confirm or reject R4's least-privilege unit** (`engine_id` ×
   `task_shape`) — the prior brainstorming pass proposed it but paused
   before a confirmed answer.
2. **Should the daemon's GitHub polling token be brought under
   `CredentialBroker` at all**, or is a narrowly-scoped, explicitly
   allowlisted environment variable (outside the engine-subprocess
   allowlist from R1, i.e. visible to the daemon's own GitHub API calls but
   never forwarded to an engine subprocess) sufficient for v1? Routing it
   through the broker gains audit trail and revocation-without-code-change;
   it also makes the daemon the first production caller of `inject()`,
   which is a real "first live user" risk worth doing deliberately rather
   than by default.
3. **DPAPI's user-login-session-bound key and unattended operation.**
   `dpapi.py`'s `CryptProtectData`/`CryptUnprotectData` derive their key
   from the current Windows user's login session (confirmed by reading the
   module). `supervisor-daemon-v1-design.md` already leans toward the
   daemon being explicitly started by the operator (not auto-started at
   login/boot, not run under a different service account) for v1, which
   likely keeps this compatible — but that decision was left open in that
   spec too (its own Open Question 2). **If a future revision makes the
   daemon a background/service-account process, R3's broker-mediated
   injection may not work at all** (DPAPI would fail to decrypt outside the
   originating user's session) and needs re-examination before that change
   ships, not after. **Operational failure mode, not yet decided:**
   `credential_broker.py`'s `inject()` already fails closed correctly (raises
   `IntegrityError` on a decrypt failure rather than serving a partial/stale
   value) — but this spec has not decided what the *daemon's loop* does when
   that happens mid-run (e.g. after a logout/relogin or a locked-workstation
   transition invalidates the DPAPI-derived key for a credential the daemon
   needs for its next dispatch). Candidates: halt the entire loop, freeze
   only the track needing that credential (consistent with the Evidence
   Gate's existing "freeze this track, continue others" pattern from
   sub-project 1), or surface-and-pause. This needs an explicit operator
   answer before R3 is implemented, not a default assumed silently.
4. **Concrete allowlist contents for R1** — this spec gives the guiding
   principle (no LLM/engine keys, only what the CLI needs to launch) but not
   a finalized list per engine; that belongs in the implementation plan,
   informed by what each engine's `--help`/docs actually require (the same
   "verified live" discipline this codebase already applies elsewhere).
5. **T4's fuller daemon-process hardening** — named, not designed. Worth an
   explicit operator decision on whether it's in scope for a v1 daemon or a
   deliberately deferred v2 concern, so it doesn't silently fall through the
   same way sub-project 2 itself briefly did.
6. **Does T2 need a structural trusted/untrusted distinction at the
   `invoke()` call site**, or is the Evidence Gate's downstream self-report
   skepticism sufficient on its own? Raised by Hermes's review of this
   draft: today `invoke_hermes()`/`CodexAdapter.invoke()` treat an
   operator-typed interactive prompt and daemon-sourced issue-body text
   identically — same signature, no trust marker. This spec deliberately
   leaves the answer open rather than picking one, since it changes the
   `EngineAdapter` protocol's shape (ADR-026 territory) and needs its own
   confirmed evidence for whether the Evidence Gate already covers it in
   practice.

## Decisions carried from the 2026-08-19 brainstorming pass

- Threat model scope confirmed: least-privilege (T1) and prompt-injection-
  from-issue-content (T2) are equally weighted, not one deprioritized —
  matches this spec's T1/T2 treatment.
- Scope question that paused the prior brainstorming ("is a Hermes-specific
  solution the wrong shape given the multi-engine vision?") is resolved by
  this spec building R1–R3 against the `EngineAdapter`/`EngineBroker`
  abstraction (ADR-026/027), not against `invoke_hermes()` specifically —
  `CodexAdapter` already exists as the second concrete adapter, confirming
  the abstraction is real, not speculative, so scoping this design to it is
  no longer premature the way it was when only Hermes had shipped.

## Decisions (Codex review, 2026-08-20, operator-directed)

The operator asked Codex to review the 6 open questions above and directed
that this spec proceed per Codex's recommendations. Answers below (verbatim
recommendation, condensed justification) resolve all 6 open questions;
implementation may now proceed against them without further sign-off on
these specific points.

1. **R4 confirmed.** Scope credentials by `engine_id x task_shape` — specific
   enough for least privilege, still operationally manageable.
2. **Daemon's GitHub token: raw env var for v1, not CredentialBroker.**
   Narrowly scoped, read-only-polling, excluded from the engine-subprocess
   allowlist (R1) so it never reaches an engine dispatch. Migrate to the
   broker later if rotation or broader GitHub scope is introduced.
3. **DPAPI decrypt failure mid-run: freeze only the affected track**, not
   the whole daemon loop — matches the Evidence Gate's existing
   freeze-one-continue-others pattern. Emit an operator-visible error;
   require explicit operator action before retrying decryption.
4. **R1 allowlist contents (v1, both engines):** `PATH`, `SYSTEMROOT`,
   `WINDIR`, `COMSPEC`, `PATHEXT`, `TEMP`, `TMP`, `USERPROFILE`, `HOME`,
   `LOCALAPPDATA`, `APPDATA`. Plus `CODEX_HOME` for Codex only, and Hermes's
   own documented config-home variable for Hermes only. Proxy, GitHub,
   cloud, and engine API-key variables stay excluded unless a specific,
   tested task shape proves a concrete need.
5. **Full daemon-process hardening (separate OS account, privilege
   separation): deferred to v2.** v1 stays an operator-started process,
   with T1's fix (explicit subprocess env), R3 (read-only broker access),
   R4 (credential scoping), and auditable failure handling as its
   hardening surface.
6. **T2 gets a structural trust marker.** Thread a trust classification
   through `EngineAdapter.invoke()` — an enum (`trusted_operator` /
   `untrusted_issue`) rather than a bare boolean. Evidence Gate skepticism
   catches a false self-report after the fact; it does not address
   prompt-driven tool misuse *during* execution, so it is not sufficient
   on its own. This changes the `EngineAdapter` protocol's shape (ADR-026
   territory) and belongs in the implementation plan, not this spec.

## Decomposition note (unchanged from sub-project 1's spec)

This spec covers sub-project 2 of 3 (agreed with the operator 2026-08-19):
1. Background orchestrator daemon —
   `docs/superpowers/specs/2026-08-19-supervisor-daemon-v1-design.md`, done.
2. **Security model for unattended credential access — this spec.**
3. Widget swimlane/pipeline visualization — independent, scoped whenever.
