# Local capability-state ledger

This directory provides a standard-library-only, offline ledger for synthetic
Cortxt run state. It does not dispatch workers, call providers, or mutate
GitHub. Each run is stored below an explicitly selected state directory and has
a generated `run_id`, schema version, UTC event timestamps, and a canonical
SHA-256 event chain.

Creation fails closed unless it receives both an explicit finite, nonnegative
USD budget and provider evidence that the authoritative inference policy
evaluates as allowed. A caller-supplied decision is never trusted.
Append uses `--expected-sequence` as optimistic concurrency control. Writes use
a temporary file in the run directory followed by atomic replacement. The CLI
rejects traversal, malformed run identifiers, and symbolic links.

The store must be created explicitly before use. Existing path components are
resolved and checked for symlinks and Windows reparse points immediately around
file operations. This is a single-user safety boundary, not an adversarial
multi-user filesystem sandbox. File contents are synchronized before replace;
the containing directory is also synchronized where the platform supports it.
Python's standard library does not expose portable directory `fsync` on
Windows, so power-loss durability there remains filesystem-dependent.

Example (all data shown is synthetic):

```text
mkdir local-state
python state_cli.py create --store ./local-state --task-id synthetic-task-107 --data-class L0 --workflow foundation.state/v1 --max-cost-usd 0 --provider-evidence-file ./evidence.json
python state_cli.py append --store ./local-state --run-id run_<generated-id> --expected-sequence 0 --event-type run.started --payload-file ./payload.json
python state_cli.py show --store ./local-state --run-id run_<generated-id>
```

Provider evidence uses the schema owned by `../inference/provider_policy.py`.
For example, synthetic L0 evidence is:

```json
{"approved":true,"provider_id":"synthetic-provider"}
```

Successful output is the complete canonical ledger on standard output. Errors
are deterministic JSON on standard error and never include a traceback. Exit
codes are `2` usage, `3` invalid or unsafe input/policy denial, `4` not found,
`5` sequence/lock conflict, `6` integrity failure, `7` I/O failure, and `70` an
unexpected internal failure.

Run the offline end-to-end suite from this directory:

```text
python -m unittest -v test_state_cli.py
```

## Reproducible T1 synthetic journey

The committed `fixtures/t1-synthetic-journey.json` drives the complete T1
lifecycle without a provider call or customer data. Generated evidence belongs
in an untracked output directory (the example uses `build/`, which is ignored):

```text
python synthetic_journey.py start --scenario fixtures/t1-synthetic-journey.json --output build/t1-evidence
python synthetic_journey.py resume --output build/t1-evidence
python synthetic_journey.py verify --output build/t1-evidence
```

The three commands are intentionally separate processes. `start` records an
allowed authoritative policy decision, creates the run, and stops at a
recoverable synthetic interruption. `resume` records resumption plus a
terminal synthetic result. `verify` reloads the ledger and checks the complete
event order, hash-chain integrity, result evidence hash, and exact actual cost
against the approved budget. Repeating `resume`, tampering with the result, or
declaring an over-budget scenario fails closed.

Run both ledger and journey tests offline with:

```text
python -m unittest -v test_state_cli.py test_synthetic_journey.py
```
