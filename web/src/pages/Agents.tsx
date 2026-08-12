import { useState } from 'react';
import { profiles, receptionists } from '../data/systemData';
import {
  CheckCircle2, AlertTriangle, XCircle, Cpu,
  Search, Filter, Zap, Clock, DollarSign, Wrench
} from 'lucide-react';

const statusConfig = {
  verified: { icon: CheckCircle2, badge: 'badge-green', text: 'text-emerald-400', bg: 'bg-emerald-900/30' },
  experimental: { icon: AlertTriangle, badge: 'badge-amber', text: 'text-amber-400', bg: 'bg-amber-900/30' },
  blocked: { icon: XCircle, badge: 'badge-red', text: 'text-rose-400', bg: 'bg-rose-900/30' },
};

export default function Agents() {
  const [filter, setFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('All');

  const categories = ['All', ...Array.from(new Set(profiles.map(p => p.category)))];

  const filtered = profiles.filter(p => {
    const matchesSearch = p.name.toLowerCase().includes(filter.toLowerCase()) ||
      p.model.toLowerCase().includes(filter.toLowerCase()) ||
      p.skills.some(s => s.toLowerCase().includes(filter.toLowerCase()));
    const matchesCategory = categoryFilter === 'All' || p.category === categoryFilter;
    return matchesSearch && matchesCategory;
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Agenter & Profiler</h1>
        <p className="text-slate-400 max-w-3xl">
          Alla profiler i AI Workspace med modell, provider, cost tier, latency budget och tillhörande skills.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Sök profiler, modeller, skills..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                categoryFilter === cat
                  ? 'bg-brand-900/40 text-brand-300 border border-brand-700/30'
                  : 'bg-slate-800 text-slate-400 border border-slate-700 hover:text-white'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Profile cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filtered.map(profile => {
          const status = statusConfig[profile.status];
          const StatusIcon = status.icon;
          return (
            <div key={profile.id} className="card hover:border-slate-600 transition-colors">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${status.bg}`}>
                    <Cpu className={`w-5 h-5 ${status.text}`} />
                  </div>
                  <div>
                    <h3 className="text-white font-semibold">{profile.name}</h3>
                    <p className="text-xs text-slate-400">{profile.category}</p>
                  </div>
                </div>
                <span className={`badge ${status.badge} text-xs`}>
                  <StatusIcon className="w-3 h-3 mr-1" />
                  {profile.status}
                </span>
              </div>

              <p className="text-sm text-slate-400 mb-3">{profile.usage}</p>

              <div className="grid grid-cols-3 gap-3 mb-3">
                <div className="p-2 rounded-lg bg-slate-800/50">
                  <div className="flex items-center gap-1 text-xs text-slate-400 mb-0.5">
                    <Cpu className="w-3 h-3" /> Modell
                  </div>
                  <div className="text-sm text-white font-medium">{profile.model}</div>
                  <div className="text-xs text-slate-400">{profile.provider}</div>
                </div>
                <div className="p-2 rounded-lg bg-slate-800/50">
                  <div className="flex items-center gap-1 text-xs text-slate-400 mb-0.5">
                    <DollarSign className="w-3 h-3" /> Cost
                  </div>
                  <div className="text-sm text-white font-medium">{profile.costTier}</div>
                </div>
                <div className="p-2 rounded-lg bg-slate-800/50">
                  <div className="flex items-center gap-1 text-xs text-slate-400 mb-0.5">
                    <Clock className="w-3 h-3" /> Latency
                  </div>
                  <div className="text-sm text-white font-medium">{profile.latency}</div>
                </div>
              </div>

              <div className="flex items-center gap-1 text-xs text-slate-400 mb-1.5">
                <Wrench className="w-3 h-3" /> Skills ({profile.skills.length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {profile.skills.slice(0, 8).map(skill => (
                  <span key={skill} className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-300 text-xs border border-slate-700">
                    {skill}
                  </span>
                ))}
                {profile.skills.length > 8 && (
                  <span className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 text-xs">
                    +{profile.skills.length - 8}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Receptionists */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <Zap className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Receptionister</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {receptionists.map(r => (
            <div key={r.name} className="p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-white font-medium text-sm">{r.system}</h4>
                <span className={`badge text-xs ${r.status === 'verified' ? 'badge-green' : r.status === 'partial' ? 'badge-amber' : 'badge-red'}`}>
                  {r.status}
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {r.capabilities.map(c => (
                  <span key={c} className="text-xs text-slate-400 bg-slate-900/50 px-2 py-0.5 rounded">
                    {c}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
