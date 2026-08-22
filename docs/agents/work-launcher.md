# Parallel work launcher

`cortxt work` is the CLI-primary surface for creating and observing multiple
contract-backed worker runs. GitHub Issues remain the scope and workflow source
of truth; the local run registry is only an execution ledger.

Use `cortxt work new scope.md --repo owner/repo --approve --max-cost-usd N`.
The approval flag is an explicit operator gate. The command creates an inbox
issue, transitions it to ready, claims it through `Dispatcher`, creates an
isolated worktree, generates a bounded worker handoff, and starts the configured
adapter asynchronously. It prints the generated run id.

`cortxt work list` reads active runs. `cortxt work resume` creates a fresh run
identity for a ready issue; retry never overwrites an earlier attempt. `cortxt
work submit` records a terminal result and moves the issue to independent
review. No launcher command approves, merges, closes, or cleans a worktree.

The worker handoff contains only approved scope, acceptance criteria, dispatch
limits, and artifact policy. Inputs containing prohibited diacritics are
rejected. Secrets, raw runtime output, full prompts, and model reasoning must
not be placed in durable artifacts.

The MCP equivalents are `cortxt_run_create`, `cortxt_run_resume`, and
`cortxt_run_submit_for_review`. They are Tier 1 tools and inherit mandate
verification in `call_tool`; handlers receive binding fields only from the
verified envelope. The MCP server does not hold a private signing key and does
not write GitHub state.
