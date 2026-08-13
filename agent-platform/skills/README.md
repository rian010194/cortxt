# Skill Platform

Status: scaffold

Skills are versioned, composable capabilities that tell an agent how to perform
a recurring workflow. A skill may contain instructions, schemas, fixtures,
evaluations, examples, and reviewed executable helpers.

## Lifecycle

```text
observed -> candidate -> sandboxed -> evaluated -> approved -> active
                                                        -> deprecated
```

The platform will eventually provide:

- a skill registry and resolver;
- profile compatibility and dependency checks;
- trajectory-based pattern detection;
- candidate creation and refinement;
- regression and security evaluation;
- staged promotion and rollback;
- provenance and version history.

Agents may generate skill candidates. Activation depends on promotion policy.
New permissions, credentials, external effects, or policy changes always
require the appropriate operator decision.

The existing repository-level `skills/` directory remains the current skill
inventory. This package will contain platform code for managing skills; it does
not duplicate installed skill content.

