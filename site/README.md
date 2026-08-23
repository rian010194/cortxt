# Cortxt site

Astro + Starlight source for the Cortxt landing page and documentation.

## Local build

```bash
cd site
npm ci
npm run build
```

The static output is written to `site/dist/`.

## Diagrams

[Mermaid](https://mermaid.js.org/) diagrams render client-side. Write a
` ```mermaid ` fenced block in any docs page and it becomes an interactive
diagram (`site/astro.config.mjs` wires up `astro-mermaid`). The rendering is
theme-aware: it follows the Starlight `data-theme` attribute, so diagrams
match dark or light mode automatically.

## Docs currency (keep the docs from drifting)

Some published pages are *derived* from repository authority and must not be
hand-edited:

- `src/content/docs/docs/adrs.md` — the Accepted-only ADR index, generated
  from `docs/adr/` by `scripts/docs_currency.py`.

The repository root owns the regeneration script and the CI gate:

```bash
# From the repository root:
python scripts/docs_currency.py --check   # fail if any derived page drifted
python scripts/docs_currency.py --write   # regenerate derived pages in place
python scripts/test_docs_currency.py      # unit tests
```

CI runs `--check` on every pull request (`docs-site-currency` job): a PR that
changes an Accepted ADR without regenerating the site page fails the gate, so
docs can never silently drift behind the repository authority.

## Deployment

Deployment is handled by Cloudflare Pages from the `main` branch with the
project root set to `site` (build command `npm run build`, output `dist`).
`cortxt.io` serves the landing page; `docs.cortxt.io` serves the Starlight
docs, with the docs root redirected to `/docs/` by host-level routing
configured on the Pages project. GitHub Actions CI verifies the build but
does not deploy. See
[`docs/cf-pages-webhook.md`](../docs/cf-pages-webhook.md) for the
auto-deploy webhook runbook.

## Known toolchain note (Windows local builds)

As of Astro 7.2.4 / Vite 8, `astro build` can fail during config loading on
Windows with `require is not defined` coming from `source-map-js`
(`node_modules/source-map-js/lib/source-map-generator.js`). The root cause is
an upstream Vite module-runner CJS/ESM interop issue triggered by Starlight
shipping raw `.ts` entry points: Node 26 refuses to type-strip `node_modules`,
Astro falls back to the Vite module runner, and the runner inlines the CJS
`source-map-js` deep import as ESM. Linux CI is unaffected and builds cleanly;
Windows users can work around it with a Node version that loads the config
natively or by awaiting the upstream Vite fix.
