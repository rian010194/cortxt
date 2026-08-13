import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Layout from '../Layout';

// P1 false-freshness: the static preview UI must NOT claim "last updated = today".
// The test is deterministic (fixed fake system time) and asserts rendered user
// behaviour, not the source text.
describe('Layout — false-freshness (static preview)', () => {
  const FAKE_NOW = new Date('2026-08-11T12:00:00Z');
  const fakeDateStr = '2026-08-11';

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FAKE_NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function renderLayout() {
    return render(
      <MemoryRouter>
        <Layout>{null}</Layout>
      </MemoryRouter>,
    );
  }

  it('shows the explicit "Preview / static data" banner', () => {
    renderLayout();
    expect(screen.getByText(/Preview \/ static data/)).toBeTruthy();
  });

  it('shows an honest unknown last-updated instead of the render date', () => {
    renderLayout();
    // Honest unknown timestamp is shown.
    expect(screen.getByText(/Senast uppdaterad: okänt/)).toBeTruthy();
    // The (fake) current date must NOT be rendered as the data's update time.
    expect(screen.queryByText(new RegExp(fakeDateStr))).toBeNull();
    // No accidental "Senast uppdaterad: <date>" pattern.
    expect(screen.queryByText(/Senast uppdaterad: \d{4}-\d{2}-\d{2}/)).toBeNull();
  });

  it('is independent of actual system time (does not read Date for freshness)', () => {
    // Change the fake time to a different day; output must be unchanged.
    vi.setSystemTime(new Date('2030-01-01T00:00:00Z'));
    renderLayout();
    expect(screen.getByText(/Senast uppdaterad: okänt/)).toBeTruthy();
    expect(screen.queryByText(/Senast uppdaterad: \d{4}-\d{2}-\d{2}/)).toBeNull();
    expect(screen.queryByText('2030-01-01')).toBeNull();
  });
});
