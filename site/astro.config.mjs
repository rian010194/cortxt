import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import starlight from '@astrojs/starlight';
import mermaid from 'astro-mermaid';

export default defineConfig({
  site: 'https://cortxt.io',
  output: 'static',
  integrations: [
    mermaid({
      theme: 'dark',
      autoTheme: true,
      enableLog: false,
    }),
    react(),
    starlight({
      title: 'Cortxt',
      description: 'Provider-neutral control for long-running AI work under human mandate.',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/rian010194/cortxt' },
      ],
      customCss: ['./src/styles/custom.css'],
      // Applies the resolved widget theme preset to the docs chrome at
      // runtime (issue #376) -- see public/theme-tokens.js.
      head: [
        { tag: 'script', attrs: { src: '/theme-tokens.js' } },
      ],
      sidebar: [
        { label: 'Overview', items: [{ label: 'Documentation', link: '/docs/' }, { label: 'Current product vs. direction', link: '/docs/product-status/' }, { label: 'Quick start', link: '/docs/quick-start/' }, { label: 'Widgets', link: '/docs/widgets/' }] },
        { label: 'Architecture', items: [{ autogenerate: { directory: 'docs/architecture' } }] },
        { label: 'Operating model', items: [
            { label: 'Current operating model', link: '/docs/operating-model/' },
            { label: 'Verified dispatch path', link: '/docs/verified-dispatch-path/' },
        ] },
        { label: 'Decisions', items: [{ label: 'Accepted ADRs', link: '/docs/adrs/' }] },
        { label: 'Roadmap', items: [
            { label: 'Visual Atlas', link: '/atlas/' },
            { label: 'Widget prototypes', link: '/widgets/' },
            { label: 'Status and Atlas hook', link: '/docs/roadmap/' },
        ] },
      ],
    }),
  ],
});
