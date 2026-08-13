# Provider-resilient execution

Status: experimental vertical package

This vertical describes a bounded inference job that survives transient model
or provider failure without silently weakening policy. It exists because a
model may return a hard availability error, become rate limited, or exceed a
useful task deadline even when a basic smoke test succeeds.

The package owns the domain behavior and synthetic evaluation cases. It does
not own provider credentials, endpoint implementations, global routing policy,
or the dispatcher. A compatible harness supplies pre-approved route candidates
and executes attempts; the vertical requires an auditable result envelope.

## Workflow

`execute-with-fallback` accepts a task classification, data class, attempt
limits, and an ordered list of already policy-evaluated route candidates. It
must:

1. select the first eligible route;
2. enforce a per-attempt timeout;
3. classify failures without retrying permanent errors blindly;
4. retry only within the declared attempt budget;
5. open the route circuit when its threshold is reached;
6. fall back only to another eligible route;
7. never replay a non-idempotent tool action; and
8. return the complete attempt history and terminal decision.

## Synthetic evaluation

The six fixtures under `evals/synthetic/` cover success, unavailable model,
rate limiting, excessive latency, a stalled return channel, and a fallback
rejected by data-class policy. All provider and model names are synthetic.

Run the deterministic package checks from the repository root:

```text
python verticals/provider-resilient-execution/tests/test_package.py
```

## Non-goals

- real inference, credentials, SDKs, or network calls;
- choosing which providers satisfy a data class;
- implementing a global gateway or dispatcher;
- retrying partially completed non-idempotent actions;
- promising provider capacity, latency, or availability.
