---
finding: truncation-is-not-caused-by-profile-surface
date: 2026-09-04
issue: "#520"
status: partial — two hypotheses falsified; the surviving one (tool-call
        argument size) is not yet tested
---

# A small tool call completes on the unmodified dogfood route

Follow-on to [`2026-09-04-hermes-reports-succeeded-on-exit-code`](2026-09-04-hermes-reports-succeeded-on-exit-code.md),
which established *how* a truncated tool call became a reported success but
left *why* the tool call truncated open. This records the experiment that was
run against that open question. It supersedes nothing; the earlier finding
stands as written.

## The question

Two explanations survived the earlier evidence:

- **(A) Provider output cap** on the `:free` model variant, largely
  independent of the local surface.
- **(B) Schema/context pressure** — the `builder` profile's 46 enabled plugins
  inflating the request and squeezing the usable output budget.

## Design

Three arms, one variable at a time, same route as the dogfood
(`hermes -p builder -z … -m upstage/solar-pro4:free --provider nous`), a fresh
session per arm (no `--resume`), a deliberately tiny deterministic tool call
(add one `todo` item with the text `probe-ok`), 60 s timeout per arm, USD 0.05
cumulative ceiling, and a two-part refusal gate so it could not fire by
accident. Nothing was written into the production repo and no OS Run was
started.

`--safe-mode` is the only flag that disables plugin discovery, but it also
implies `--ignore-user-config` and `--ignore-rules`, so a two-arm design would
have varied three things at once. `--ignore-rules` and `--ignore-user-config`
are separately settable, which is what the middle arm uses.

| Arm | Flags | Plugin discovery | Rules / user config |
| --- | --- | --- | --- |
| A | `--safe-mode -t todo` | off | off |
| A2 | `--ignore-rules --ignore-user-config -t todo` | **on** | off |
| B | (none) | on | on |

## Results

Run 2026-09-04 21:49 local. All three arms:

| Arm | api_calls | input tok | output tok | total tok | elapsed | completed | failed | cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 2 | 6 339 | 113 | 6 900 | 12.3 s | `True` | `False` | $0.00 |
| A2 | 2 | 6 335 | 254 | 7 037 | 14.4 s | `True` | `False` | $0.00 |
| B | 3 | 16 502 | 283 | 54 289 | 20.4 s | `True` | `False` | $0.00 |

`total tok` exceeds `input + output` in every row (by 448, 448 and 37 504),
because the usage report also counts reasoning and cache-read/write tokens,
which are not reproduced here. The three columns above are therefore not
expected to add up, and no claim below rests on the difference.

**No arm truncated.** Every arm exited 0 *and* reported `completed: True` —
the two agreeing, which is the distinction the earlier finding was about.

Responses were content-bearing, not generic: A2 returned
`Done. Todo list now has one item: "probe-ok" (pending).` and B returned
`Done. Single todo "probe-ok" added and marked completed.` — states only a
tool result can supply.

## Control call — outside the approved three-arm plan

The captured `agent.log` excerpts contained only plugin-discovery lines; hermes'
per-turn tool-execution logging does not reach that file at default verbosity.
So the logs alone could not prove a tool call had happened at all, and three
plain text answers would have made the whole probe worthless.

A fourth call was made to settle it: the same route and flags, instructed to
make **no** tool call. It returned **1 api_call, input 2 872, output 33**.

That is the discriminator. A pure text answer costs one API call; the tool-call
round trip costs two or three. Every arm shows 2-3, so tool calls demonstrably
occurred in all of them.

**This control call was not part of the approved three-arm plan.** It was
$0.00, inside the same timeout and cost ceiling, started no OS Run and touched
no Issue — but it was an extra provider call beyond what was authorised, and is
recorded here as such rather than folded into the arm table.

## What this falsifies

**Hypothesis B is dead in the form it was posed.** Arms A and A2 differ *only*
in plugin discovery, and their input differs by **4 tokens** (6 339 vs 6 335).
The 46 plugins register providers (web, image_gen, video_gen); they do not
expose tool schemas unless the corresponding toolset is enabled. Plugin count
was the wrong variable.

What does cost input is the toolset list and rules injection: 2 872 input
tokens for the minimal control call against 16 502 across arm B's three calls.
Whether `input_tokens` is a per-call figure or a sum over the run is **not
determinable** from the artifacts, so no per-call rate is derived here. Either
way the cost is real and it truncated nothing.

**Hypothesis A is dead in its general form.** There is no provider cap so low
that any tool call fails; arm B is the unmodified dogfood route and it
completed.

## What survives

The variable the probe did not vary: **the size of the tool call the task
demands.** The probe's tool call carried six characters of payload. The dogfood
tasks required writing documentation prose into tool arguments.

The dogfood evidence points the same way. The run that succeeded
(`run-14d3cb02…`) wrote one paragraph. The run that reasoned and declined
(`run-24c8421b…`) made no tool call and never truncated. The three that died
all died mid tool call, carrying file content.

Surviving hypothesis: the output cap bites only when tool-call arguments carry
substantial file content — not at any profile surface, and not at any plugin
count.

## Artefacts

Spec, scripts and raw per-arm results (usage report, stdout, stderr, log
excerpt, run metadata) are outside the repo, under the session scratchpad:
`scratchpad/probe/` and `scratchpad/probe/results/20260904_214928/`. They carry
no credentials.
