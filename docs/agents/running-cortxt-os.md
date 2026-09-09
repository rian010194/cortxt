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
and `--spec` change the listener and the served spec, and `--require-commit` /
`--require-clean` pass through to the host's opt-in source-integrity checks.

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
only `--port`, `--spec`, `--require-commit` and `--require-clean`, so running
it directly always mounts the mutation route. `cortxt widget --enable-actions`
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
