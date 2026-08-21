# Threat model: centralized credential broker for connected agent tools

**Status:** Proposed — clearing Phase 1 blocker for the v.02 wayfinder. Not implemented; this document clears Phase 4's prerequisite, it is not Phase 4 itself.  
**Issue:** [`rian010194/cortxt#158`](https://github.com/rian010194/cortxt/issues/158)  
**Cross-references:**  
- `docs/architecture/cortxt-agent-platform-target-architecture.md` §28 (operator retains mandate over irreversible decisions)  
- `docs/architecture/cortxt-agent-platform-target-architecture.md` §32.2 (`credential` effect class — "separate trust-boundary decision")  
- `docs/architecture/cortxt-agent-platform-target-architecture.md` §32.3 (an agent candidate can never grant itself new rights)  
- `docs/adr/021-reopen-adr-015-for-v02-admin-surface-and-widget-ui.md` (credential-storage security model explicitly deferred to Phase 1)  
- v.02 vision doc PR `#156`, §3 (centralized credential handling) and §6 (security-sensitive, not yet modeled)

## 1. What we are modeling

The v.02 admin/discovery surface (working name: Cortxt Control Surface) is
proposed to scan the operator's environment for known agent runtimes (Hermes,
Buzz, Claude Code, Codex, Pi, …), let the operator toggle each one on/off, and
centrally hold the API keys/tokens needed to wire them up — the "1-click
install" idea from vision doc §3.

The credential broker is therefore a **control-plane-owned store of
third-party bearer credentials** that the admin surface reads from and injects
into other systems' configuration on the operator's behalf.

This document does **not** design the broker. It enumerates the threats that
any such design must neutralize, and gives concrete, minimum-acceptable
recommendations so that Phase 4 (implementation) does not start from an open
question.

## 2. Trust boundaries we assume

- **Control Plane** is the trust anchor. It owns scope, policy, and operator
  mandate. The broker is a control-plane component, not an agent-owned store.
- **Agent/Runtime** is a *consumer* of broker-issued credentials, never a
  trustee of the store. The agent may request that a credential be injected
  somewhere, but it does not read the raw store directly.
- **Operator** is the only party authorized to persist a new third-party
  credential or to approve a broker-mediated grant of access to a new tool.
- **Addons** are externally contributed packages that may include executable
  logic shipped post-approval. They run with whatever permission the admin
  surface grants them; they do **not** get raw access to the credential store
  by default.
- **External runtimes** (Hermes, Claude, Codex, Buzz, Pi) each own their own
  credential lifecycle. The broker is the *injection path*, not the
  authority over the remote account.

## 3. Threats and recommendations

### 3.1 Encryption at rest for stored third-party API keys/tokens

**Threat.** The broker is a concentrated bearer-credential store. If its
on-disk representation is readable by any unintended party — another local user,
a compromised process, a backup that escapes the intended scope, a swapped/defective
disk, a developer laptop that leaves the operator's control — every connected
tool's credentials are exposed at once. Bearer tokens forgive no identity
boundary: possession is access.

**Concrete recommendations.**

1. **Encrypt at rest with a key the broker itself does not store in the same
   blob.** Use OS-level key storage where available (Windows DPAPI `/on-disk
   user-scope`, macOS Keychain, Linux `libsecret`/`kwallet`), or a dedicated
   local secrets backend, so the master key is bound to the operator's login
   session and not a static file next to the encrypted store. Do **not**
   use a single hardcoded or environment-variable key shared across installs.

2. **Encrypt individual records, not just the container.** If the broker ever
   backs up, replicates, or exports, each credential should still be opaque
   outside the intended runtime. A single-key container that loses its key
   exposes everything; per-record isolation at least limits a partial exposure.

3. **Define the confidentiality class of the store explicitly.** This is the
   highest-density secret collection Cortxt would hold. Treat it as at least
   `L1` (intern, non-public) in the ADR-016 data-class ladder, and require the
   broker to refuse to persist a credential whose owning runtime's own assurance
   level the broker cannot honor. Do not silently downgrade a credential's class
   because it is stored locally.

4. **Backups are in scope.** Backups that include the encrypted store must be
   encrypted with the same or stricter key management, time-boxed, and cleaned
   on the schedule the operator sets. A backup that is easier to steal than the
   live machine defeats the whole point.

5. **Memory hygiene.** Credentials should live in memory only for the duration
   of an injection operation, and should not be logged, echoed in status views,
   or embedded in error messages. The prototype admin surface's status views
   (`prototype-widget-v02.html`, `prototype-cli-v02.py`) must never print a
   real key — redact to `****` or a non-reversible reference even in fake-data
   prototypes, so the pattern does not survive into real code by accident.

### 3.2 Access control: what can read/write the store, and under what conditions

**Threat.** A credential store that is writable by anything other than an
explicit, auditable operator action becomes a self-service key distribution
point. An agent, an addon, a misconfigured tool adapter, or a runtime bug that
can call "store this key" or "read that key" turns the broker from a convenience
into a privilege escalator.

**Concrete recommendations.**

1. **Write path is operator-gated, always.** Persisting a new third-party
   credential, rotating an existing one, or deleting one is an *operator
   action* through the admin surface or the equivalent CLI. It is never the
   result of an agent request, an addon's install hook, or an automated sync.
   If the implementation wants "the agent can ask the operator to store a key,"
   that is an approval flow, not a store API the agent calls directly.

2. **Read path is runtime-bound and purpose-bound.** The broker hands a
   credential to a specific declared runtime for a specific declared purpose
   (e.g. "inject into Claude's config for this account"), not "here is the
   store, read whatever you need." The minimum acceptable model is:
   - caller identity (which runtime is receiving),
   - which credential (by explicit reference, not by enumeration),
   - why (the operation the admin surface is performing),
   - a bounded lifetime or one-shot delivery where the underlying runtime
     supports it.

3. **No credential enumeration.** The broker must not expose a list of all
   stored credentials to any caller that is not the operator in an explicit
   management view. Discovering "what keys exist" is itself sensitive: it tells
   an attacker which tools the operator has connected.

4. **Scope the writable surface.** The broker's own config and its encrypted
   store must live in a directory the operator controls and that is not world-
   readable, not on a path a run-workspace sandbox can reach, and not in any
   location that gets copied into an artifact or a workspace tarball. This is
   the same isolation principle as
   `docs/architecture/runtime-and-evaluation-harness.md` §5 (a run workspace
   must not expose the user's home directory). The credential store is *not*
   run-workspace data.

5. **Audit what was granted to whom, and when.** Every injection should leave
   a minimal, tamper-evident record: timestamp, operator action, target runtime,
   credential reference (not the credential), and result. This is what makes a
   later "which tool got which key and when" question answerable without
   replaying the broker's memory.

### 3.3 Blast radius if the admin surface itself is compromised

**Threat (explicitly called out in vision doc §6).** The admin surface is the
operating interface to the broker. If it is compromised — by a vulnerability in
the widget/CLI, by a malicious or flawed addon that has been approved and
installed, by a runtime escape in the local web stack if hosted, by a privileged
local attacker — the attacker is not attacking one tool. The broker's value
proposition *is* concentration, so the blast radius of a broker compromise is
*larger than a single-tool compromise*: a single successful attack can expose
every connected tool's credentials at once.

**Concrete recommendations.**

1. **Separate the broker's trust from the admin surface's code.** The admin
   surface is a UI/UX and orchestration layer. The broker's cryptographic and
   access-control core should be a distinct component with a narrow, reviewed
   interface. Compromising the widget's DOM, the CLI's rendering path, or an
   addon's UI hook should not immediately yield the broker's plaintext keys.
   The admin surface calls the broker; it is not the broker.

2. **Fail closed on integrity doubt.** If the broker detects that its store,
   its key material, or its own code integrity is suspect (tampered file,
   unexpected permission, key material that no longer decrypts cleanly), it
   must refuse to emit credentials rather than "try anyway." A broker that
   degrades gracefully into "I can't prove I'm intact" is safer than one that
   continues serving keys from a possibly-compromised store.

3. **Isolate the broker from the agent execution path.** Concretely: the broker
   is not on the writable-mount or tool-execution path of any run workspace. It
   is not reachable from a sandbox that an agent can influence. This matches the
   harness principle that a run workspace must not expose the user's home
   directory or control-plane credentials (`runtime-and-evaluation-harness.md`
   §5, `vertical-package-contract.md` §41).

4. **Assume the admin surface is the highest-value local target.** Because a
   broker compromise is a *portfolio* compromise, the admin surface gets the
   same scrutiny as any other control-plane component: reviewed code paths,
   minimal native/executable surface, pinned dependencies, and a clear
   rollback path if a widget/CLI version is found to be flawed. Do not treat the
   admin surface as "just a UI" for threat-modeling purposes.

5. **Be honest about hosted vs. local.** If the admin surface is ever hosted
   (vision doc §6 open question), the blast-radius analysis changes — the
   credential store moves from "the operator's machine" to "a server the
   operator trusts," and the threat model must include network exposure,
   multi-tenant isolation if applicable, and server-side compromise. This
   document's recommendations are written for a *local* broker; a hosted
   variant needs its own threat model before it is built, and the choice between
   hosted and local must not be deferred past the point where code assumes one.

### 3.4 Blast radius if an addon is malicious or compromised post-approval

**Threat.** The vision doc's addon model (Phase 5, separate from this task) allows
addons that can install *executable logic*, not just UI decorations. An addon
that is malicious at ship time, or that becomes compromised after approval
(supply-chain dependency rot, a compromised update, a legitimate addon whose
author's keys are stolen), now runs with whatever permission the admin surface
granted it. If that permission includes any indirect route to the broker — even
"call the broker's public API" — a malicious addon is no longer just a
compromised UI component; it is a potential credential consumer.

**Concrete recommendations.**

1. **Addons do not get raw broker access by default.** An addon's install-time
   permission set must be explicit and scoped to what it genuinely needs —
   ideally "can render UI", "can call these specific tool IDs", and so on. It
   does not get "read the credential store" or "enumerate connected runtimes."
   If an addon genuinely needs to trigger a credential injection, that is a
   *named, reviewed operation* with an operator-facing confirmation, not a
   general broker client.

2. **Treat addon approval as a trust decision, not a one-time checkbox.**
   Post-approval compromise is the real risk. The broker's access-control model
   must survive an addon turning bad *after* it was approved — which means the
   broker does not trust the addon's *identity* as a blanket credential
   authority; it trusts the *operation* the addon is performing, with the
   operator in the loop for anything that emits a credential.

3. **Pin and verify addon provenance.** If addons can update, the update path
   must be integrity-protected (signed or hash-pinned) so a compromised update
   server or a MITM does not silently replace an approved addon with a malicious
   one. This is a Phase 5 concern, but the broker's threat model must assume the
   update path exists and be hardened accordingly; the broker cannot be the
   component that catches a supply-chain failure it had no part in designing.

4. **Prefer one-shot, runtime-scoped injection over long-lived credential
   grants to addons.** If an addon's legitimate function requires touching a
   third-party credential, the broker should prefer to hand the credential to
   the *target runtime* directly, not store it in the addon's reach. The addon
   requests the operation; the broker performs it against the real runtime under
   the operator's existing grant. That limits an addon's window even if it is
   later compromised.

5. **Name the blast radius honestly in the addon model.** The addon review
   process (Phase 5) must state, explicitly, what a compromised or malicious
   addon *can and cannot* reach, with the credential broker named as one of the
   protected assets. A review that says "addons are sandboxed" without
   enumerating the broker as a boundary is not a completed threat model.

## 4. Cross-reference: operator mandate over irreversible decisions (§28)

The broker must not create a path for an agent to self-grant new tool access
without operator approval. This is not a feature request; it is a constraint
carried directly from `cortxt-agent-platform-target-architecture.md` §28:

> *The Control Plane owns the mandate; the agent does not own its own scope.*

and from §32.3:

> *A candidate can never grant itself new rights. New network targets,
> credentials, external mutations, and irreversible effects require explicit
> promotion per Control Plane policy.*

Concrete implications for the broker:

- **An agent may ask.** An agent may say "I need a key to talk to X." That is a
  proposal. It is not a grant.
- **The operator (or an explicit, pre-approved policy with the operator's
  mandate behind it) decides.** Storing the key, or injecting it, or extending
  an existing grant, is an operator action. The broker may facilitate the UI of
  that decision, but it may not collapse proposal and grant into one agent-controlled step.
- **No self-service credential expansion.** The broker must not expose any API
  that an agent profile, an addon, or a tool candidate can call to expand its
  own access without a corresponding operator-side approval record. This is the
  same "no self-approval" invariant that runs through §28, §31.1 (skill
  promotion), and §32.3 (tool evolution).

Put differently: the credential broker is a *control-plane instrument*, not an
*agent affordance*. Its existence is compatible with §28 only if every
credential lifecycle transition (store, rotate, inject, expand, revoke) remains
traceable to an operator or explicitly pre-approved policy decision.

## 5. Out of scope (stated explicitly)

- Implementing the broker — that is Phase 4, and this document clears its
  prerequisite, it does not do its work.
- Pricing, naming, and the addon review process — those are Phase 6 / Phase 5 and
  are flagged as open questions in vision doc §6 and in
  `docs/adr/021-reopen-adr-015-for-v02-admin-surface-and-widget-ui.md`.
- The hosted-vs-local decision for the admin surface — this document assumes
  local and flags the hosted case as requiring its own threat model.

## 6. Minimum acceptance before Phase 4 may start

Phase 4 may begin when the implementation plan for the broker can answer, for each
of the four areas above, "what is our concrete design, and how does it satisfy
the recommendation in this document." A broker design that hand-waves any of the
four areas — especially write-path operator gating, no credential enumeration,
and the §28 no-self-grant constraint — is not ready to implement.

## 7. Document status

Proposed, 2026-08-18. Written to clear the Phase 1 blocker in
`rian010194/cortxt#158` as part of the v.02 wayfinder. Not an ADR; not
implementation; not a substitute for the Phase 4 design doc or the Phase 5 addon
review process.
