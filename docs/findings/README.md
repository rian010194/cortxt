# Findings

A **finding** records a mechanism that was established at a point in time:
what was observed, what was traced to a cause, and what was left open.

Findings are **registers**, not descriptions. They are never edited. They
assert nothing about the present, so they cannot go stale — a finding that
turns out wrong is superseded by a new one that sets `supersedes:` to it,
rather than being corrected in place. Anything that must stay true about the
system as it is now belongs in a description (most of `docs/agents/` and
`docs/architecture/`, a README) and must change in the same commit as the thing
it describes. Not everything in those directories is a description —
`docs/architecture/REVIEW_LOG.md` is itself append-only — so check the document,
not the directory.

A finding is not an ADR. An ADR records a decision and its alternatives; a
finding records what the system was actually doing and how that was proven.
When a finding leads to a decision, the ADR cites the finding.

## Form

```
---
finding: <short-kebab-slug>
date: <YYYY-MM-DD>
issue: "<#N, if one>"
status: <verified | partial — what remains open>
supersedes: <slug, if any>
---
```

`issue` is quoted because an unquoted `#` starts a YAML comment and would
silently empty the field.

The file is named `<date>-<finding>.md`, repeating both frontmatter fields, so
a directory listing reads chronologically and a `supersedes:` slug can be
resolved without opening anything.

Then: what was observed (raw evidence, quoted), the mechanism (with
`file:line` citations that can be re-checked), what was fixed, and — kept
explicitly separate — what is still hypothesis.

A `file:line` citation is only re-checkable against the commit it was read at,
so name that commit where the line number is load-bearing. Findings cite
evidence, never credentials: a token's lifetime is a fact worth recording, its
value never is.

The last section matters most. A finding that blurs the proven part into the
suspected part is worse than no finding, because it retires a question that is
still open.
