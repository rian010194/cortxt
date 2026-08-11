import { describe, it, expect, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Assess from '../../pages/Assess';

// #54 AC-2/AC-3: fixture v01-syn-unc-001 => uncertain risk-class badge is
// warning-amber (not green) AND applicability badge (needs_more_info) is
// warning-amber with AlertTriangle (never green).
describe('Assess badges — #54', () => {
  beforeAll(() => {
    // jsdom supports crypto.randomUUID in modern versions; ensure it exists.
    if (!globalThis.crypto?.randomUUID) {
      // minimal fallback for older jsdom
      Object.defineProperty(globalThis, 'crypto', {
        value: { ...(globalThis.crypto ?? {}), randomUUID: () => '00000000-0000-4000-8000-000000000000' },
        configurable: true,
      });
    }
  });

  it('renders amber badges for risk-class uncertain and applicability needs_more_info', async () => {
    render(<Assess />);
    // Add the synthetic fixture (result is set synchronously by addFixture).
    fireEvent.click(screen.getByRole('button', { name: /Knapphändig beskrivning/ }));

    await waitFor(() => {
      // Risk-class badge shows "Osäker" and is amber (not green). There may be
      // several nodes with "Osäker" (portfolio stat + badge); check the badge one.
      const osakerNodes = screen.getAllByText('Osäker');
      expect(osakerNodes.length).toBeGreaterThan(0);
      const amber = osakerNodes.some(n => n.className && n.className.includes('badge-amber'));
      expect(amber).toBe(true);
      const green = osakerNodes.some(n => n.className && n.className.includes('badge-green'));
      expect(green).toBe(false);

      // Applicability badge shows "Tillämpas inte" and is amber (not green).
      const appBadge = screen.getByText('Tillämpas inte');
      expect(appBadge.className).toContain('badge-amber');
      expect(appBadge.className).not.toContain('badge-green');
    });
  });
});
