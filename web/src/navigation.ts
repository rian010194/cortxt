import {
  LayoutDashboard, GitBranch, Users, Wrench, KanbanSquare,
  Send, Boxes, Activity, Scale
} from 'lucide-react';

export type NavEntry = {
  to: string;
  label: string;
  icon: React.FC<{ className?: string }>;
};

export const NAV_ENTRIES: NavEntry[] = [
  { to: '/', label: 'Översikt', icon: LayoutDashboard },
  { to: '/flow', label: 'Flöde', icon: GitBranch },
  { to: '/agents', label: 'Agenter', icon: Users },
  { to: '/skills', label: 'Capabilities', icon: Wrench },
  { to: '/kanban', label: 'Kanban', icon: KanbanSquare },
  { to: '/dispatch', label: 'Dispatch', icon: Send },
  { to: '/verticals', label: 'Verticals', icon: Boxes },
  { to: '/assess', label: 'AI Act Bedömning', icon: Scale },
  { to: '/telemetry', label: 'Economics', icon: Activity },
];
