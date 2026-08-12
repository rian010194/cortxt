import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AppShell from '../AppShell';

describe('AppShell — navigation', () => {
  beforeEach(() => {
    // Ensure consistent viewport
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1280 });
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: (query: string) => ({
        matches: query !== '(max-width: 768px)',
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  });

  function renderAppShell() {
    return render(
      <MemoryRouter>
        <AppShell>Test Content</AppShell>
      </MemoryRouter>,
    );
  }

  it('renders the skip link', () => {
    renderAppShell();
    const skipLink = screen.getByRole('link', { name: /Hoppa till huvudinnehåll/i });
    expect(skipLink).toBeTruthy();
  });

  it('renders all 9 navigation links in desktop sidebar', () => {
    renderAppShell();
    const links = screen.getAllByRole('link');
    // Expect more than 9 since AppShell has mobile menu links too
    expect(links.length).toBeGreaterThanOrEqual(9);
    // Verify labels exist (use getAllByText to handle duplicates from mobile + desktop)
    expect(screen.getAllByText('Översikt').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Flöde').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Agenter').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Capabilities').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Kanban').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Dispatch').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Verticals').length).toBeGreaterThan(0);
    expect(screen.getAllByText('AI Act Bedömning').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Economics').length).toBeGreaterThan(0);
  });

  it('highlights active navigation link', () => {
    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AppShell>Test Content</AppShell>
      </MemoryRouter>,
    );
    // Use getAllByText to handle duplicate links from mobile + desktop
    const allAgentsLinks = screen.getAllByText('Agenter');
    expect(allAgentsLinks.length).toBeGreaterThan(0);
    // At least one should have aria-current="page"
    const activeLink = allAgentsLinks.find((link) => (link as HTMLElement).getAttribute('aria-current') === 'page');
    expect(activeLink).toBeTruthy();
  });

  it('toggles mobile menu with hamburger button', () => {
    // Force mobile view
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 });

    renderAppShell();
    const hamburger = screen.getByRole('button', { name: /öppna meny/i });
    expect(hamburger).toBeTruthy();
    expect((hamburger as HTMLElement).getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(hamburger);
    expect((hamburger as HTMLElement).getAttribute('aria-expanded')).toBe('true');

    // Mobile menu should be visible
    const mobileMenu = screen.getByRole('dialog', { name: 'Meny' });
    expect(mobileMenu).toBeTruthy();
  });

  it('closes mobile menu on Escape key', async () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 });

    renderAppShell();
    const hamburger = screen.getByRole('button', { name: /öppna meny/i });
    fireEvent.click(hamburger);

    // Press Escape
    await waitFor(() => {
      fireEvent.keyDown(document.body, { key: 'Escape' });
    });

    // Menu should close
    expect((hamburger as HTMLElement).getAttribute('aria-expanded')).toBe('false');
  });

  it('closes mobile menu on route change', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 });

    render(
      <MemoryRouter initialEntries={['/']}>
        <AppShell>Test Content</AppShell>
      </MemoryRouter>,
    );

    // Open menu
    const hamburger = screen.getByRole('button', { name: /öppna meny/i });
    fireEvent.click(hamburger);

    // Navigate to different route - use getAllByText since there are multiple matches
    const allAgentsLinks = screen.getAllByText('Agenter');
    if (allAgentsLinks.length > 0) {
      fireEvent.click(allAgentsLinks[0]);
    }

    // Menu should close after navigation
    expect((hamburger as HTMLElement).getAttribute('aria-expanded')).toBe('false');
  });

  it('closes mobile menu when clicking backdrop', () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 });

    renderAppShell();
    const hamburger = screen.getByRole('button', { name: /öppna meny/i });
    fireEvent.click(hamburger);

    // Backdrop is the overlay div with bg-black/60
    // Find it by className pattern
    const backdropDivs = document.querySelectorAll('div');
    let backdrop: HTMLElement | null = null;
    for (const div of Array.from(backdropDivs)) {
      if (div.className.includes('bg-black/60') && div.className.includes('fixed inset-0')) {
        backdrop = div as HTMLElement;
        break;
      }
    }

    if (backdrop) {
      fireEvent.click(backdrop);
    } else {
      // Fallback: click outside the menu area
      const body = document.body;
      fireEvent.click(body, { clientX: 10, clientY: 10 });
    }

    expect((hamburger as HTMLElement).getAttribute('aria-expanded')).toBe('false');
  });
});
