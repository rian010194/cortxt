# Verticals

Verticals are versioned domain packages loaded by the generic harness. They
own workflows, domain schemas, instructions, templates, and approved eval
fixtures. They do not own dispatch, containers, credentials, or the global
approval model.

Only synthetic or explicitly redistributable fixtures may be committed. Real
case material belongs in an ignored, isolated run workspace outside Git
history.

Start from [`_template/`](_template/) only after the first vertical experiment
has an approved scope.

See [Vertical package contract](../docs/architecture/vertical-package-contract.md).
