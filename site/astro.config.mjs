import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://cortxt.io',
  output: 'static',
  integrations: [
    react(),
    starlight({
      title: 'Cortxt',
      description: 'Provider-neutral control for long-running AI work under human mandate.',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/rian010194/cortxt' },
      ],
      customCss: ['./src/styles/custom.css'],
      sidebar: [
        { label: 'Overview', items: [{ label: 'Documentation', link: '/docs/' }, { label: 'Quick start', link: '/docs/quick-start/' }] },
        { label: 'Architecture', items: [{ autogenerate: { directory: 'architecture' } }] },
        { label: 'Operating model', items: [
            { label: 'Current operating model', link: '/docs/operating-model/' },
            { label: 'Verified dispatch path', link: '/docs/verified-dispatch-path/' },
        ] },
        { label: 'Decisions', items: [{ label: 'Accepted ADRs', link: '/docs/adrs/' }] },
        { label: 'Roadmap', items: [
            { label: 'Visual Atlas', link: '/atlas/' },
            { label: 'Status and Atlas hook', link: '/docs/roadmap/' },
        ] },
      ],
    }),
  ],
});
