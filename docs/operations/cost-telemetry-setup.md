# Cost Telemetry Setup

Status: active operational
Authority: runtime operations
Last verified: 2026-08-11

## Purpose

Track and report model usage costs for every Hermes Kanban run. Prevent `unknown` cost from being treated as zero.

## Configuration

### 1. Show cost in CLI output

```bash
hermes config set display.show_cost true
```

This makes Hermes print token usage and estimated cost after each LLM call in the CLI.

### 2. Per-profile cost tracking

Each profile can have its own provider/model with different pricing. The Kanban run envelope already captures:

- `model` (provider/model identifier)
- `usage` (input/output/cache/reasoning tokens)
- `cost` (amount and confidence)

### 3. Kanban cost fields

When completing a Kanban task, always include cost in the result:

```bash
hermes kanban complete t_12345 \
  --result "Skills inventory skapat." \
  --summary "Cost: USD 0.23 (high confidence)" \
  --metadata '{"cost_usd":0.23,"cost_confidence":"high","input_tokens":4200,"output_tokens":1800}'
```

### 4. Gateway dispatcher cost tracking

The dispatcher does not yet auto-calculate cost. Workers must report observed cost in the result envelope.

### 5. Current status

| Component | Cost tracking |
|-----------|--------------|
| Hermes CLI (`display.show_cost`) | ✅ Enabled |
| Kanban result envelope | ✅ Worker-reported |
| Auto-calculation from tokens | ❌ Not yet implemented |
| Budget enforcement | ⚠️ Time-based only (`max-runtime`) |

## Next steps

- [ ] Build a cost calculator that maps provider+model+tokens → USD.
- [ ] Add `max_cost_usd` enforcement to the dispatcher (soft stop or warning).
- [ ] Store per-run cost in the Kanban DB for aggregation and reporting.
