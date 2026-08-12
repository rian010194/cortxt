import { useState, useEffect, useRef, useCallback } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { NAV_ENTRIES } from '../navigation';
import {
  LayoutDashboard, GitBranch, Users, Wrench, KanbanSquare,
  Send, Boxes, Activity, Scale, X, Menu
} from 'lucide-react';

const ICON_MAP: Record<string, React.FC<{ className?: string }>> = {
  '/': LayoutDashboard,
  '/flow': GitBranch,
  '/agents': Users,
  '/skills': Wrench,
  '/kanban': KanbanSquare,
  '/dispatch': Send,
  '/verticals': Boxes,
  '/assess': Scale,
  '/telemetry': Activity,
};

type ShellProps = {
  children: ReactNode;
};

export default function AppShell({ children }: ShellProps) {
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  // Handle Escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && mobileMenuOpen) {
        setMobileMenuOpen(false);
        buttonRef.current?.focus();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [mobileMenuOpen]);

  // Focus management when menu opens
  useEffect(() => {
    if (mobileMenuOpen && menuRef.current) {
      const focusable = menuRef.current.querySelector<HTMLElement>(
        'button, a, input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      focusable?.focus();
    }
  }, [mobileMenuOpen]);

  // Backdrop click closes menu
  const handleBackdropClick = useCallback(() => {
    setMobileMenuOpen(false);
    buttonRef.current?.focus();
  }, []);

  const isActivePath = (to: string) => {
    if (to === '/') return location.pathname === '/';
    return location.pathname.startsWith(to);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 flex">
      {/* Mobile menu overlay/backdrop */}
      <div
        className={`fixed inset-0 bg-black/60 z-40 transition-opacity duration-200 ${
          mobileMenuOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        aria-hidden={!mobileMenuOpen}
        onClick={handleBackdropClick}
      />

      {/* Mobile menu modal */}
      <div
        ref={menuRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="mobile-menu-title"
        className={`fixed inset-y-0 left-0 w-64 bg-slate-900 z-50 transform transition-transform duration-200 ease-in-out border-r border-slate-800 ${
          mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
        data-focus-ro="mobile-menu"
      >
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <h2 id="mobile-menu-title" className="text-sm font-semibold text-white">
            Meny
          </h2>
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              buttonRef.current?.focus();
            }}
            className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-500 focus-visible:ring-offset-2"
            aria-label="Stäng meny"
            data-focus-ro="menu-close-btn"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <nav className="p-3 space-y-1" aria-label="Huvudmeny">
          {NAV_ENTRIES.map((item) => {
            const Icon = ICON_MAP[item.to] || LayoutDashboard;
            const active = isActivePath(item.to);
            return (
              <a
                key={item.to}
                href={item.to}
                onClick={() => {
                  // Only close on click, not navigation
                  if (item.to !== location.pathname) {
                    setMobileMenuOpen(false);
                  }
                }}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? 'bg-brand-900/40 text-brand-300 border border-brand-700/30'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
                data-focus-ro="mobile-nav-link"
                data-route={item.to.replace(/^\//, '') || 'overview'}
                aria-current={active ? 'page' : undefined}
              >
                <Icon className="w-5 h-5" />
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-slate-800 text-xs">
          <div className="p-2 rounded-md bg-amber-900/20 border border-amber-800/40 text-amber-200 mb-2">
            Preview / static data
          </div>
          <div className="text-slate-400">Senast uppdaterad: okänt</div>
          <div>Profile: coordinator</div>
          <div className="mt-2 text-slate-400">v0.1.0 prototype</div>
        </div>
      </div>

      {/* Skip link */}
      <a
        href="#main-content"
        className="skip-link sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 px-4 py-2 bg-brand-600 text-white rounded-lg shadow-lg focus:outline-none focus:ring-2 focus:ring-white focus-visible:ring-offset-2"
        data-focus-ro="skip-link"
      >
        Hoppa till huvudinnehåll
      </a>

      {/* Sidebar - visible on desktop (>=769px), hidden on mobile (<=768px) */}
      <aside
        className={`hidden md:flex flex-col w-64 bg-slate-900 border-r border-slate-800 fixed h-screen`}
        data-focus-ro="sidebar"
      >
        <div className="p-5 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <LayoutDashboard className="w-6 h-6 text-brand-400" />
            <div>
              <h1 className="text-lg font-bold text-white leading-tight">AI Workspace</h1>
              <p className="text-xs text-slate-400">Control Plane</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV_ENTRIES.map((item) => {
            const Icon = ICON_MAP[item.to] || LayoutDashboard;
            const active = isActivePath(item.to);
            return (
              <a
                key={item.to}
                href={item.to}
                className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? 'bg-brand-900/40 text-brand-300 border border-brand-700/30'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
                data-focus-ro="nav-link"
                data-route={item.to.replace(/^\//, '') || 'overview'}
                aria-current={active ? 'page' : undefined}
              >
                <Icon className="w-5 h-5" />
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="p-4 border-t border-slate-800 text-xs">
          <div className="p-2 rounded-md bg-amber-900/20 border border-amber-800/40 text-amber-200 mb-2">
            Preview / static data
          </div>
          <div className="text-slate-400">Senast uppdaterad: okänt</div>
          <div>Profile: coordinator</div>
          <div className="mt-2 text-slate-400">v0.1.0 prototype</div>
        </div>
      </aside>

      {/* Main content area */}
      <main
        id="main-content"
        className={`flex-1 min-w-0 md:ml-64 min-h-screen`}
        data-focus-ro="main-content"
      >
        {/* Mobile header */}
        <div className="md:hidden flex items-center justify-between p-4 border-b border-slate-800 bg-slate-900">
          <h1 className="text-lg font-bold text-white">AI Workspace</h1>
          <button
            ref={buttonRef}
            onClick={() => setMobileMenuOpen(true)}
            className="p-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-500 focus-visible:ring-offset-2"
            aria-label="Öppna meny"
            aria-expanded={mobileMenuOpen}
            aria-controls="mobile-menu-container"
            data-focus-ro="menu-toggle-btn"
            data-route={location.pathname.replace(/^\//, '') || 'overview'}
          >
            {mobileMenuOpen ? (
              <X className="w-6 h-6" />
            ) : (
              <Menu className="w-6 h-6" />
            )}
          </button>
        </div>

        {/* Mobile sidebar container (hidden, only used for aria-controls) */}
        <div id="mobile-menu-container" className="hidden" aria-hidden={!mobileMenuOpen} />

        {/* Routed content root */}
        <div
          className="max-w-7xl mx-auto p-4 md:p-8"
          data-route={location.pathname.replace(/^\//, '') || 'overview'}
          data-focus-ro="routed-content"
        >
          {children}
        </div>
      </main>
    </div>
  );
}
