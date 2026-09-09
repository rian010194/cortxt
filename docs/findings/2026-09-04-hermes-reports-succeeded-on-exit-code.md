---
finding: hermes-reports-succeeded-on-exit-code
date: 2026-09-04
issue: "#520"
status: partial — the classification defect is verified; the fix recorded here
        is the one written on the day and was not the one that shipped; why the
        provider truncated the tool call is still open
---

# A worker that refused to act was recorded as a success

## What was observed

Five Runs on `main` `7534301`, engine `hermes-free`, provider `nous`, model
`upstage/solar-pro4:free`. All five exited 0 and were reported `succeeded` by
the adapter. Three of them did nothing at all.

| Run | Issue | stdout | What actually happened |
| --- | --- | --- | --- |
| `run-14d3cb02c6314a3da6c7a36d2ecc66e1` | #497 | 2188 B | committed `90ba45d` |
| `run-24c8421b68124e35b4663c3e808762ec` | #497 | 2804 B | reasoned, then declined to act |
| `run-2fc4cbde63ca44dbb97a5b6e211e185e` | #519 | 83 B | did nothing |
| `run-bf29dd4f161f46e5a0f2de3e6d68a29b` | #497 | 83 B | did nothing |
| `run-bf4b62978de34b9083b6e31bb6838deb` | #497 | 83 B | did nothing |

The three 83-byte run logs are **byte-identical** (`md5 aa9a632d…`), stdout
only, stderr empty:

```
=== stdout ===
Response truncated due to output length limit

=== stderr ===
```

That is the whole of stdout. It is not a response that was cut off — it is a
complete diagnostic sentence emitted *instead of* a response.

## The mechanism

Four steps, each re-checkable.

1. **The sentence is hermes', not the provider's.** It is emitted by
   `agent/conversation_loop.py` in the local hermes install (three sites emit
   it; a fourth truncation branch handles the case in different words. The one
   that fires here is ~4607-4623). hermes finds an assistant message
   carrying a tool call whose JSON arguments do not end in `}` or `]`, judges
   it cut off mid-stream, and refuses to execute incomplete arguments. Its own
   comment names the confound: *"Routers sometimes rewrite finish_reason from
   'length' to 'tool_calls', hiding the truncation from the length handler
   above."* This branch returns immediately, with no retry.

2. **hermes reports the failure structurally.** It returns
   `completed: False`, `partial: True`, and `error` set to the same sentence.

3. **The CLI drops that on the floor.** `hermes_cli/oneshot.py:276` returns 2
   only when the run is partial **and** the response is empty. The truncation
   sentence is a non-empty response, so the guard is skipped and the process
   **exits 0**.

4. **The platform believed the exit code.** `routing/hermes_invoker.py:130`
   set `status = "succeeded" if proc.returncode == 0`. `HermesFreeAdapter`
   passed it through unchanged.

The Evidence Gate was then the only thing standing between a truncated
provider response and an accepted Run. It caught all three, fail-closed, and
recorded `commit_predates_run` — the symptom, because that is all the envelope
gave it to work with.

## The fix written on the day — proposed, not shipped

**This section records a proposal, not the state of `main`.** It was written on
branch `fix/hermes-completion-signal-520`, commit `35f303b` (on `7534301`), and
that branch was never merged. What reached `main` for #520 is a different
design, and this register is not the place to describe it — see "What actually
shipped" below for the pointer, and check `main` rather than this file for how
the platform behaves now.

The proposal rested on a channel hermes already offers: `--usage-file` writes a
JSON report carrying `completed` and `failed` (`hermes_cli/_parser.py:115-125`,
written even on failure by `oneshot.py:_write_usage_file`). The invoker would
ask for that report and read it, so that completion came from a structured
field rather than from matching the text of a response — the argument being that
matching the sentence breaks the moment its wording changes, and this is a claim
about whether work happened.

As written on `35f303b`:

- `status` was `succeeded` only when the process exited 0 **and** the run did
  not report itself unfinished.
- An absent, unreadable, malformed, non-dict or `completed`-less report was
  `unreported`: the exit code still decided and the envelope said the
  completion was not reported. Inventing a value there would replace one false
  claim with another.
- An unfinished run was `worker_incomplete`, not `worker_nonzero_exit` — the
  process did exit 0, and saying otherwise states a second untrue thing about a
  run that already lied once.
- Both hermes routes answered identically, through a shared
  `read_completion_report` rather than a second copy of the rule.

## What actually shipped

Recorded here only so this finding cannot be read as a description of `main`.
PR #523 (`dae6b53`, merged 2026-09-07) answered #520 with
`agent-platform/routing/worker_outcome.py`: a separate `outcome` field beside
`status`, with the values `completed` / `declined` / `no_result` /
`unattested`. It identifies a truncated run by matching the sentence
(`TRUNCATION_MARKERS`), which is the approach the proposal above argued
against, and it does not read the usage report at all. Neither
`read_completion_report` nor any `--usage-file` argument exists on `main`.

Why that design was chosen over this one is not established here, and this
finding does not claim the proposal was better. It records what was written on
2026-09-04 and what the evidence of that day supported.

Neither the proposal nor what shipped touched the Evidence Gate. Provider
status, Run status and gate verdict were three separate things throughout, and
the gate verified evidence independently of what any provider claimed.

## What is still open

**Why the tool-call JSON was cut off is not established.** Two explanations
survive the evidence:

- the provider's output cap on the `:free` model variant, or
- schema/context pressure — the `builder` profile has 46 plugins enabled
  (`profiles/builder/logs/agent.log`, recorded at each of the five run start
  times), so the tool-schema payload may be squeezing the output budget; a
  router rewriting `finish_reason` is consistent with both.

Separating them needs one live call per arm, which the expired nous credential
currently blocks. A three-arm probe is specified and unrun.

Two hypotheses were **excluded** by evidence, not by argument:

- *Session reuse.* The adapter never passes `--resume`; every Run is a fresh
  hermes session.
- *Token expiry.* The nous token has a one-hour life
  (`obtained_at` 14:26:03Z, `expires_at` 15:26:03Z). Every Run ran inside a
  valid window, and truncation began at 12:51Z — mid-token-life, not at an
  expiry boundary.

## Proposed status for #520

`bug`, **open**, and not closable by this work.

What either fix addresses is the platform's *classification*: a run that stops
short is no longer reported as a success, and the three response shapes the
issue names (completed, declined, truncated) become distinguishable at the
envelope. What the issue also asks for — that the platform not be surprised by a
truncated provider response in the first place — depends on the open root cause
above.

Closing #520 on the classification fix alone would retire a question that is
still live. It should stay open until the probe has run and the truncation
cause is either fixed or accepted as a known provider limit with a recorded
mitigation.
