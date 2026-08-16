# Vertical 02: Code Fixture Package

> **Package:** `vertical-02-code-fixture`
> **Version:** `0.1.0`
> **Contract:** `0.1.0`

## Purpose

The smallest solvable code task that can falsify Fas 3's exit criterion:
one file, one off-by-one bug, one failing assertion, one obviously-correct fix.

The fixture is deliberately boring. A hard fixture would let a Fas 3 failure be
blamed on task difficulty; an easy one means a failure can only be the
*mechanism* — workspace containment, write policy, scope inspection, sandboxed
falsification — which is what is actually under test.

## Workflow: `fix-failing-test`

1. The platform copies `evals/synthetic/<case>/workspace/` into a disposable run
   workspace plus a pristine baseline copy.
2. The platform runs the test suite against the baseline. It must fail; if it
   passes there is no bug and the run terminates `blocked`.
3. The platform enumerates the workspace and assembles a prompt from
   `instructions/system-prompt-fix.md`, the workspace map, the failing-test
   output, the declared scope and the caps.
4. The model returns a `patch-proposal.schema.json`-shaped object.
5. The platform applies it, computes the diff itself, checks the diff against
   the declared scope, and re-runs the suite in a sandbox.

## What this package does NOT own

Per [vertical package contract](../../docs/architecture/vertical-package-contract.md):
sandbox policy, container images, mounts, timeouts, credentials, dispatch, and
the approval state machine all belong to the platform. `fixture.yaml` declares
`caps` and `declared_scope` because those are properties *of the task*; how they
are enforced is `agent-platform/runtime/execution/`'s business.

## Directory layout

```
verticals/vertical-02-code-fixture/
|-- vertical.yaml
|-- README.md
|-- schemas/
|   |-- patch-request.schema.json
|   `-- patch-proposal.schema.json
|-- instructions/
|   `-- system-prompt-fix.md
`-- evals/synthetic/
    `-- 001-off-by-one/
        |-- fixture.yaml
        `-- workspace/
            |-- ranges.py
            `-- test_ranges.py
```
