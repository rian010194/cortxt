import { describe, it, expect, beforeAll } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Assess from '../../pages/Assess';

// #54 + P2-rework: applicability-badge is fully confidence-aware.
// uncertain / needs_more_info => warning-amber + AlertTriangle regardless of
// the boolean applicability result; safe positive => red, safe negative => green.
const FIXTURES: Record<string, { label: string; riskLabel: string; appliesText: string }> = {
  unc: { label: 'Sparse description (uncertainty)', riskLabel: 'Uncertain', appliesText: 'Not applicable' },
  bnd: { label: 'Crowd counting without identification (boundary)', riskLabel: 'Uncertain', appliesText: 'AI Act applies' },
  pos: { label: 'High-risk medical diagnosis (positive)', riskLabel: 'High risk', appliesText: 'AI Act applies' },
  neg: { label: 'Traditional accounting software (negative)', riskLabel: 'Minimal risk', appliesText: 'Not applicable' },
};

describe('Assess applicability badges — fully confidence-aware (#54 + P2)', () => {
  beforeAll(() => {
    if (!globalThis.crypto?.randomUUID) {
      Object.defineProperty(globalThis, 'crypto', {
        value: { ...(globalThis.crypto ?? {}), randomUUID: () => '00000000-0000-4000-8000-000000000000' },
        configurable: true,
      });
    }
  });

  function addFixture(label: string) {
    fireEvent.click(screen.getByRole('button', { name: new RegExp(label.slice(0, 12)) }));
  }

  it('negative + needs_more_info renders amber with AlertTriangle, never green/red', () => {
    render(<Assess />);
    addFixture(FIXTURES.unc.label);
    // applicability badge showing "Not applicable"
    const appBadge = Array.from(screen.getAllByText('Not applicable'))
      .map(n => n.closest('span'))
      .find(s => s && s.className.includes('badge')) as HTMLElement;
    expect(appBadge.className).toContain('badge-amber');
    expect(appBadge.className).not.toContain('badge-green');
    expect(appBadge.className).not.toContain('badge-red');
    // AlertTriangle icon present (a lucide svg inside the badge)
    const tri = appBadge.querySelector('svg');
    expect(tri).toBeTruthy();
    // risk-class "Uncertain" is amber too
    const risk = screen.getAllByText('Uncertain').map(n => n.closest('span')) as HTMLElement[];
    expect(risk.some(n => n?.className?.includes('badge-amber'))).toBe(true);
    expect(risk.some(n => n?.className?.includes('badge-green'))).toBe(false);
  });

  it('positive + uncertain renders amber with AlertTriangle, never green/red', () => {
    render(<Assess />);
    addFixture(FIXTURES.bnd.label);
    const appBadge = Array.from(screen.getAllByText('AI Act applies'))
      .map(n => n.closest('span'))
      .find(s => s && s.className.includes('badge')) as HTMLElement;
    expect(appBadge.className).toContain('badge-amber');
    expect(appBadge.className).not.toContain('badge-green');
    expect(appBadge.className).not.toContain('badge-red');
    expect(appBadge.querySelector('svg')).toBeTruthy();
  });

  it('safe positive (probable) stays red and safe negative (certain) stays green', () => {
    render(<Assess />);
    // safe positive
    addFixture(FIXTURES.pos.label);
    let app = Array.from(screen.getAllByText('AI Act applies'))
      .map(n => n.closest('span')).find(s => s && s.className.includes('badge')) as HTMLElement;
    expect(app.className).toContain('badge-red');
    expect(app.className).not.toContain('badge-amber');
    // safe negative
    addFixture(FIXTURES.neg.label);
    app = Array.from(screen.getAllByText('Not applicable'))
      .map(n => n.closest('span')).find(s => s && s.className.includes('badge') && s.className.includes('badge-green')) as HTMLElement;
    expect(app.className).toContain('badge-green');
  });
});
