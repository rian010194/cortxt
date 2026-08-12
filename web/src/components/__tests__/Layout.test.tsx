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
    // Use getAllByText since there are multiple occurrences (sidebar + mobile menu)
    const banners = screen.getAllByText(/Preview \/ static data/);
    expect(banners.length).toBeGreaterThan(0);
  });

  it('shows an honest unknown last-updated instead of the render date', () => {
    renderLayout();
    // Honest unknown timestamp is shown.
    const unknownDates = screen.getAllByText(/Senast uppdaterad: okänt/);
    expect(unknownDates.length).toBeGreaterThan(0);
    // The (fake) current date must NOT be rendered as the data's update time.
    const datePattern = screen.queryByText(new RegExp(fakeDateStr));
    expect(datePattern).toBeNull();
    // No accidental "Senast uppdaterad: <date>" pattern.
    const dateRegex = screen.queryByText(/Senast uppdaterad: \d{4}-\d{2}-\d{2}/);
    expect(dateRegex).toBeNull();
  });

  it('is independent of actual system time (does not read Date for freshness)', () => {
    // Change the fake time to a different day; output must be unchanged.
    vi.setSystemTime(new Date('2030-01-01T00:00:00Z'));
    renderLayout();
    const unknownDates = screen.getAllByText(/Senast uppdaterad: okänt/);
    expect(unknownDates.length).toBeGreaterThan(0);
    const dateRegex = screen.queryByText(/Senast uppdaterad: \d{4}-\d{2}-\d{2}/);
    expect(dateRegex).toBeNull();
    const date2030 = screen.queryByText('2030-01-01');
    expect(date2030).toBeNull();
  });

  it('includes the AI Workspace title', () => {
    renderLayout();
    // Use getAllByText since there are multiple elements with this text
    const titles = screen.getAllByText(/AI Workspace/i);
    expect(titles.length).toBe(2); // One in sidebar, one in mobile header
  });

  it('includes Control Plane subtitle', () => {
    renderLayout();
    // Control Plane appears in the sidebar
    const subtitles = screen.getAllByText(/Control Plane/i);
    expect(subtitles.length).toBe(1);
  });

  it('renders mobile menu button on small screens', () => {
    // Mock viewport
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 });
    renderLayout();
    const menuBtn = screen.getByRole('button', { name: /öppna meny/i });
    expect(menuBtn).toBeTruthy();
  });

  it('renders sidebar navigation on desktop', () => {
    // Mock viewport
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1280 });
    renderLayout();
    const nav = screen.getByRole('navigation', { name: 'Huvudmeny' });
    expect(nav).toBeTruthy();
  });

  it('renders skip link', () => {
    renderLayout();
    const skipLink = screen.getByRole('link', { name: /Hoppa till huvudinnehåll/i });
    expect(skipLink).toBeTruthy();
  });
});
