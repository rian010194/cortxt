# Running Cortxt OS

The action host (`agent-platform/widget/action_host.py`) is the loopback
surface that serves Cortxt OS and mounts the one operator-gated mutation route
the ADR-038 host boundary allows -- `POST /api/action`, token-bound,
closed-schema validated, rate-limited, and gated on an approval reference plus
an explicit confirm. It is not a service, not remotely reachable, and not
supervised: it binds `127.0.0.1` only, runs in the foreground, and blocks until
Ctrl+C.

## Start it

From the repository root, on win32:

```
set CORTXT_FREE_PROVIDER=nous
set CORTXT_FREE_MODEL=upstage/solar-pro4:free
python scripts/start_cortxt_os.py
```

Then open <http://127.0.0.1:8765/index.html>. Those two values are what the
2026-09-04 dogfood used -- an example, not a default. The script never sets
them, because choosing a model is an operator act. Add `--no-free-route` to
start without dispatch -- it skips the free-route checks and does **not** make
the host read-only, since `POST /api/action` is mounted either way. `--port`
and `--spec` change the listener and the served spec, `--data-home` chooses
where durable state lives (see below), `--read-area` chooses where Cortxt may
look (see below), and `--require-commit` / `--require-clean` pass through to
the host's opt-in source-integrity checks.

## The data home

`--data-home` (or `CORTXT_DATA_HOME`) names the durable Cortxt data home. The
Core store is served from `<data-home>/core`, and it is what the packaging
routes read and write. Without either, **no store is configured**: the host
still starts and `POST /api/action` is still mounted, but every packaging read
route answers `503 store_unavailable`. That is the default and it is reported
as such -- the start line reads `data home: not configured`.

The value must be an absolute directory **outside this checkout** and outside
the system temp directory. Durable state must not live in a tree that changes
branch, gets cleaned, or exists once per worktree; `state/core_store.py` names
`Temp/` explicitly as forbidden. A data home that is set but unusable is a
refusal, never a fallback to a guessed location: `action_host.main` prints the
refusal code and the input that carried the value, and returns 1 **before
binding the port**. The start script does not repeat that check -- one rule,
one authority.

The run registry and the Core store resolve from different roots today: the
registry still resolves from the host module's own location (see below), while
the Core store resolves from the data home. The start report names both,
adjacent, so the split is visible rather than assumed away.

## The read area

`--read-area` (or `CORTXT_READ_AREA`) names where Cortxt is allowed to
**look**: one or more absolute, existing directories separated by the
platform's path separator (`;` on Windows, `:` elsewhere), so the value
behaves the way `PATH` does. `GET /api/repositories` then reports the
repositories beneath those roots -- each with its branch, its commit, whether
the working copy is dirty, its origin URL, and its local `origin/main` ref.

**A read area grants no write access.** It bounds what discovery may read; it
is not an allowlist, and no write path anywhere is derived from it. Choosing
one is also never a prerequisite: discovery informs a proposal, it never gates
one. Without the flag and without the variable, no read area is configured,
the host starts exactly as before, and `GET /api/repositories` answers
`503 read_area_unconfigured` -- reported at start as `read area: not
configured`. That 503 is deliberate: "Cortxt was never told where to look" and
"there is nothing there" are different answers, and only one of them has a fix.

Every repository is reported **with its revision state and with caveats**,
never by path alone. The caveats say what could not be established, and the
one that matters most is on `origin_main_ref`: it is a *local* ref reflecting
the last fetch, never verified against the remote, which may be arbitrarily
far ahead. Discovery makes **no network calls** -- no `fetch`, no `ls-remote`
-- which is what keeps that caveat honest rather than something a network call
would appear to resolve. Any fact that could not be read comes back as `null`
with a caveat beside it, never as a guess or an empty string.

A read area that is set but unusable is a refusal, never a fallback: the roots
must be absolute, must already exist as directories, must contain no `..`
component, and must not repeat or nest inside one another. `action_host.main`
prints the refusal code and the input that carried the value and returns 1
**before binding the port**; the start script does not repeat the check --
one rule, one authority. Unlike the data home, a read area inside this
checkout is perfectly valid: a read area exists in order to contain
repository checkouts.

## Dialogue

The action host also mounts six local dialogue routes under
`/api/dialogue/` (ADR-051): `GET/POST /api/dialogue/sessions`,
`GET /api/dialogue/session`, and `POST /api/dialogue/connect`,
`/api/dialogue/turn`, `/api/dialogue/cancel`. They persist per-session
dialogue state under `<data-home>/dialogue` and drive an ACP agent process
the operator names at start.

Three options configure the dialogue agent, on both
`scripts/start_cortxt_os.py` and `action_host.py` directly (pass-through, same
style as `--data-home`):

- `--dialogue-agent-command <exe>` -- the executable the connect/turn routes
  spawn (e.g. `hermes`). **Without it, reads and session creation still work
  when a data home is configured, but connect and turn answer
  `503 agent_unavailable`** -- the absence is reported at start as
  `dialogue agent: not configured`.
- `--dialogue-agent-arg <arg>` -- one agent argument, repeatable
  (`--dialogue-agent-arg acp`).
- `--dialogue-agent-env <NAME>` -- the *name* of one environment variable
  copied into the agent's environment when present; values are never logged,
  only names.

Without `--data-home` (or `CORTXT_DATA_HOME`) there is no dialogue root:
every dialogue route answers `503 dialogue_unavailable`, reported at start
as `dialogue root: not configured`. Sessions live under
`<data-home>/dialogue/sessions`, per-session agent workspaces under
`<data-home>/dialogue/workspaces/<cortxt session id>` (never a checkout or
the data-home root), and agent stderr under
`<data-home>/dialogue/logs/<cortxt session id>.agent-stderr.log`.

A second host process pointed at the same data home becomes a **read-only
observer**: one OS-level writer lock per dialogue root means the second
host's reads work while its writes answer `409 dialogue_writer_busy`.

The 503 kinds an operator will see on the dialogue routes and what each
means: `dialogue_unavailable` (no data home -- pass `--data-home`),
`agent_unavailable` (no agent command configured, or the command did not
resolve on PATH), `acp_unavailable` (the agent SDK is unusable -- upgrade
`agent-client-protocol`), `agent_capacity` (the live-agent cap is reached),
`agent_protocol_error` (the agent answered null for session/load or spoke
off-protocol), and on writes `agent_connection_lost` (502; the connection
died mid-turn -- reopen the session). Not-configured kinds are reported at
start; the rest are runtime answers, never startup refusals.

The documented dialogue smoke start (free port in 18800-18899, never
8765/8791/8792/8793; `<dir>` an absolute directory outside every checkout and
outside the system temp directory; `--no-free-route` because the free-route
checks concern dispatch, not dialogue):

```
python scripts/start_cortxt_os.py --port <p> --data-home <dir> --no-free-route \
  --dialogue-agent-command hermes --dialogue-agent-arg acp
```

Expected report lines include `[start-cortxt-os] dialogue root:
<dir>/dialogue` and `dialogue agent: hermes acp (env names: none)`; the
host's serving line includes `dialogue=<dir>/dialogue` and
`dialogue_writer=held`.

## The four commands that start something, and when each applies

Three of them start the action host; the fourth starts the read-only server
instead. Only the first is the documented way.

| Command | Actions | Port/spec configurable |
| --- | --- | --- |
| `python scripts/start_cortxt_os.py` | yes | yes |
| `python agent-platform/widget/action_host.py` | **yes, always -- there is no flag to disable them** | yes, but see the caveat below |
| `cortxt widget --enable-actions` | yes | **no -- `--port`/`--spec` are not accepted on this command** |
| `cortxt widget` | no (read-only `serve.py`) | -- |

`--enable-actions` belongs to `cortxt widget`, which uses it to choose between
the action host and the read-only `serve.py`; the module's own parser accepts
only `--port`, `--spec`, `--require-commit`, `--require-clean`, `--data-home`
and `--read-area`, so running it directly always mounts the mutation route. `cortxt widget --enable-actions`
calls `action_host.main()` with neither port nor spec, so it always binds 8765
and always serves `widget_contract/specs/candidates-0.1.yaml`; a `--port` typed
on that command line is an argparse error and exits 2. Use the start script
when either needs to be chosen.

Running `action_host.py` directly also needs `widget_contract` on the import
path, which that command does not provide: it puts `agent-platform/widget` on
`sys.path[0]`, and the module imports `widget_contract.*` at module scope with
no bootstrap of its own. It resolves on a machine that has run `pip install -e
agent-platform/`, and dies with `ModuleNotFoundError: widget_contract` on a
checkout that has not (unless `PYTHONPATH=agent-platform` is set). The start
script inserts the path itself, which is why it works from a bare checkout.

## Refusals

Each refusal prints one line beginning `[start-cortxt-os] refusing to start:`
and exits 2. They are checked in this order, before anything binds.

| Refusal | Message says | Fix |
| --- | --- | --- |
| A host already answers on the port | a host is already listening, and why another `--port` is not the way around it | Stop the running host with Ctrl+C in its terminal |
| The working directory is not the repository root | which directory was used, and that `agent-platform/widget/action_host.py` was expected beneath it | `cd` to the repository root and run `python scripts/start_cortxt_os.py` from there |
| The free route is incomplete | which of `CORTXT_FREE_PROVIDER` and `CORTXT_FREE_MODEL` is unset or empty, with the dogfood values as an example | Set both, or pass `--no-free-route` |
| `hermes` is not on PATH | that the free route cannot dispatch without it | Install `hermes` and reopen the shell, or pass `--no-free-route` |

The first refusal is a pre-bind connect to `127.0.0.1:<port>`, not a caught
bind failure: the host serves through a socket with `SO_REUSEADDR` set, so on
win32 a second process can bind an address a first is already listening on
without any error at all.

That probe is per-port, and the registry is not: it resolves from the host
module's own location, so two hosts started on different ports still write the
same `runs.json` and still disagree about the same Runs. The check therefore
catches the common collision, not every second host -- which is why its message
says to stop the running host rather than to move to another `--port`. One host
at a time remains an operator discipline the script helps with; it does not
enforce it.

The free-route checks report presence only and never read, print or log the
value of a credential-bearing variable. `provider` and `model` are routing
configuration rather than secrets -- `worker_adapters` already reports both on
the run envelope -- so the success line names them.

## Why the working directory is checked

The registry the OS reads resolves from the host module's own location, not
from the process working directory -- see the registry-resolution paragraph in
[`work-launcher.md`](work-launcher.md), where a cwd-relative store is recorded
as how #485's Run records ended up in a second, unaudited registry root. The
working directory still decides which copy of the module gets imported, which
is why the start script refuses rather than documents it, and why the
`registry:` line it prints is the host's own resolved path.
