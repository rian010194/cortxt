import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://cortxt.io',
  output: 'static',
  integrations: [
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
        { label: 'Operating model', items: [{ label: 'Current operating model', link: '/docs/operating-model/' }] },
        { label: 'Decisions', items: [{ label: 'Accepted ADRs', link: '/docs/adrs/' }] },
        { label: 'Roadmap', items: [{ label: 'Status and Atlas hook', link: '/docs/roadmap/' }] },
      ],
    }),
  ],
});
