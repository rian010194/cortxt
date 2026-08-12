import { describe, it, expect } from 'vitest';
import { NAV_ENTRIES } from '../navigation';

describe('navigation', () => {
  describe('NAV_ENTRIES', () => {
    it('contains exactly 9 entries', () => {
      expect(NAV_ENTRIES).toHaveLength(9);
    });

    it('has correct route paths', () => {
      const paths = NAV_ENTRIES.map((e) => e.to);
      expect(paths).toEqual([
        '/',
        '/flow',
        '/agents',
        '/skills',
        '/kanban',
        '/dispatch',
        '/verticals',
        '/assess',
        '/telemetry',
      ]);
    });

    it('has correct labels per current spec', () => {
      const labels = NAV_ENTRIES.map((e) => e.label);
      expect(labels).toEqual([
        'Översikt',
        'Flöde',
        'Agenter',
        'Capabilities',
        'Kanban',
        'Dispatch',
        'Verticals',
        'AI Act Bedömning',
        'Economics',
      ]);
    });

    it('each entry has to, label, and icon', () => {
      NAV_ENTRIES.forEach((entry) => {
        expect(entry).toHaveProperty('to');
        expect(entry).toHaveProperty('label');
        expect(entry).toHaveProperty('icon');
        expect(typeof entry.to).toBe('string');
        expect(typeof entry.label).toBe('string');
        // React ComponentType includes both function and class components
        expect(typeof entry.icon === 'object' || typeof entry.icon === 'function').toBe(true);
      });
    });

    it('routes match the 9 canonical paths', () => {
      const expected = [
        { path: '/', label: 'Översikt' },
        { path: '/flow', label: 'Flöde' },
        { path: '/agents', label: 'Agenter' },
        { path: '/skills', label: 'Capabilities' },
        { path: '/kanban', label: 'Kanban' },
        { path: '/dispatch', label: 'Dispatch' },
        { path: '/verticals', label: 'Verticals' },
        { path: '/assess', label: 'AI Act Bedömning' },
        { path: '/telemetry', label: 'Economics' },
      ];
      expected.forEach((exp, idx) => {
        expect(NAV_ENTRIES[idx].to).toBe(exp.path);
        expect(NAV_ENTRIES[idx].label).toBe(exp.label);
      });
    });
  });
});
