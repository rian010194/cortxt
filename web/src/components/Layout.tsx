import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, GitBranch, Users, Wrench, KanbanSquare,
  Send, Boxes, Activity, Radio, Scale
} from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Översikt' },
  { to: '/flow', icon: GitBranch, label: 'Flöde' },
  { to: '/agents', icon: Users, label: 'Agenter' },
  { to: '/skills', icon: Wrench, label: 'Skills' },
  { to: '/kanban', icon: KanbanSquare, label: 'Kanban' },
  { to: '/dispatch', icon: Send, label: 'Dispatch' },
  { to: '/verticals', icon: Boxes, label: 'Verticals' },
  { to: '/assess', icon: Scale, label: 'AI Act Bedömning' },
  { to: '/telemetry', icon: Activity, label: 'Telemetry' },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 flex">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col fixed h-screen">
        <div className="p-5 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <Radio className="w-6 h-6 text-brand-400" />
            <div>
              <h1 className="text-lg font-bold text-white leading-tight">AI Workspace</h1>
              <p className="text-xs text-slate-400">Control Plane</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `nav-link ${isActive ? 'active' : 'text-slate-400'}`
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-800 text-xs text-slate-500">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            Coordinator: kimi-k2.6
          </div>
          <div>Profile: coordinator</div>
          <div className="mt-2 text-slate-600">v0.1.0 prototype</div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 ml-64">
        <div className="max-w-7xl mx-auto p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
