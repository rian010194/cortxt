# Cortxt site

Astro + Starlight source for the Cortxt landing page and documentation.

## Local build

```bash
cd site
npm ci
npm run build
```

The static output is written to `site/dist/`.

## Vercel deployment

Use one Vercel project for both the landing page and docs:

1. Import `rian010194/cortxt` using direct Git integration and set the project root directory to `site`.
2. Keep the framework preset as Astro, build command as `npm run build`, and output directory as `dist` (also declared in `vercel.json`).
3. Enable production builds on pushes to `main` and keep Vercel's per-pull-request preview deployments enabled.
4. Add `cortxt.io` and `docs.cortxt.io` as custom domains on this same project. Domain import works with any registrar.
5. The operator completes the DNS records shown by Vercel and verifies both domains after propagation.

The host-aware redirect in `vercel.json` sends the root of `docs.cortxt.io` to
the `/docs/` Starlight entry point while `cortxt.io` keeps the landing page at
its root.

Vercel's direct Git integration is the deploy path. GitHub Actions CI may verify the build, but it does not deploy this site.
