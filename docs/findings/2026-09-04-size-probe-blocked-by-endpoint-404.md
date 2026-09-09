---
finding: size-probe-blocked-by-endpoint-404
date: 2026-09-04
issue: "#520"
status: partial — no size measurement obtained; the free endpoint returned
        404 before any model exchange
---

# The size probe produced no measurement: the endpoint stopped serving

Follow-on to [`2026-09-04-truncation-is-not-caused-by-profile-surface`](2026-09-04-truncation-is-not-caused-by-profile-surface.md),
which falsified both the profile-surface and blanket-cap explanations and left
one hypothesis standing: that the output cap bites only when tool-call
arguments carry substantial file content. This records the attempt to measure
that boundary. It supersedes nothing.

Filed as its own post rather than appended to the previous one: registers are
not edited, and this is a separate experiment with a separate outcome.

## Design

Four measurement points on the dogfood route — `hermes -p builder -z … -m
upstage/solar-pro4:free --provider nous` — a fresh session per point, and the
same *kind* of tool call the truncated dogfood runs were making: `write_file`,
which carries the entire file content inside its JSON arguments. Not the `todo`
tool the previous probe used; that was the point.

Payloads 200, 800, 2 000 and 5 000 characters, each a repeated `ABCDEFGHIJ`
block cut to exactly the requested length, so a short write is visible
byte-for-byte. Writes went to a fresh temp directory outside every repo.
60 s per point, USD 0.05 cumulative ceiling, stop at the first truncation or
short write, and the same two-part refusal gate.

## Result: one point run, no measurement

| Requested | Status | rc | completed | failed | api_calls | tokens | File written |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 200 | exited | 0 | `false` | `true` | 7 | all null | none |

stdout, in full:

```
API call failed after 3 retries: HTTP 404: service failure: endpoint not found
```

The sweep stopped there by design and 800 / 2 000 / 5 000 were never attempted.

**This is not the dogfood signal.** No `Response truncated due to output length
limit` in stdout, no truncated-tool-call line in the agent log, no file, no
short write.

**It is not an auth failure either.** The credential refreshed *during* the
call — `expires_at` moved from `20:49:31Z` to `21:46:01Z` — and remained valid
for another 58 minutes afterwards.

## How far the call got

The usage report is the clearest evidence, by contrast with the three arms an
hour earlier:

| Field | three-arm probe | this run |
| --- | --- | --- |
| `model`, `provider`, `session_id` | populated | **null** |
| `input_tokens`, `output_tokens`, `total_tokens` | populated | **null** |
| `estimated_cost_usd`, `cost_status` | `0.0`, `estimated` | **null** |
| `api_calls` | 2 / 2 / 3 | 7 |
| `completed` / `failed` | `true` / `false` | `false` / `true` |

Every field that requires a model exchange is null, including the run's own
identity. No session was established. The call died at the transport layer
before any completion existed to be truncated. `api_calls` still advanced to 7,
so that counter increments at a lower request layer than the completion — the
exact decomposition of 7 against "3 retries" is **not determinable** from the
artifacts and is not claimed here.

The same route served three successful runs one hour earlier, so the endpoint
was serving and then was not.

## Defects in the probe itself

Found by independent review of the raw artifacts. Recorded because they bound
what this run can be read to mean.

1. **Infrastructure failure and truncation are not distinguished.**
   `is_failure()` collapses every non-success into one stop with a text reason.
   A 404 halts the sweep exactly as a genuine truncation would. The stop was
   *correct* here, but the probe cannot tell the two regimes apart on its own —
   which is the central distinction the experiment exists to make. It took
   manual inspection of stdout and the usage nulls to classify this run.

2. **No infra-retry path.** One transient endpoint error permanently ends the
   sweep and marks that size failed. A size that was never measured is recorded
   the same way as a size that failed to carry its payload.

3. **`output_tokens` is captured but never tested.** A run that truncates at
   the model layer while still writing a file of the exact requested length
   would pass as OK. For payloads small enough to fit, this masks the very
   phenomenon under study.

None of these invalidate the reading above — the artifacts settle this run
unambiguously — but a re-run should fix at least (1) and (3) before its results
are trusted as a boundary.

## What is still open

Unchanged from the previous finding: whether the output cap bites as tool-call
arguments grow is **not measured**. The surviving hypothesis is neither
supported nor weakened by this run.

Newly observed: **the free route's endpoint availability is itself unreliable**,
independent of payload size. That is a second, separate risk to any dogfood
attempt on this route, and it did not appear in the earlier evidence because
the earlier runs happened to be served.

## A note for #520

`completed: false, failed: true` covered both "the worker stopped short" and
"the endpoint was never reached". The classification fix would map this run to
`worker_incomplete` — correctly *not* `succeeded`, which is the improvement
that matters, but an imprecise name for an endpoint outage. Distinguishing
"worker ran and stopped short" from "no worker was ever reached" is a further
refinement, not made here.

## Artefacts

Outside the repo, under the session scratchpad: `scratchpad/probe/size_probe.py`
and `scratchpad/probe/size_results/20260904_224557/`. The isolated work area was
`%TEMP%\cortxt-size-probe-h31vdar7`, verified empty afterwards — nothing was
written anywhere. No credentials in any artefact.
