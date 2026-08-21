import { useState } from 'react';
import { skills } from '../data/systemData';
import { Search, Filter, Wrench, CheckCircle2, AlertTriangle, Layers } from 'lucide-react';

const categories = ['All', ...Array.from(new Set(skills.map(s => s.category)))];

export default function Skills() {
  const [filter, setFilter] = useState('');
  const [catFilter, setCatFilter] = useState('All');
  const [maturityFilter, setMaturityFilter] = useState('All');

  const filtered = skills.filter(s => {
    const matchesSearch = s.name.toLowerCase().includes(filter.toLowerCase()) ||
      s.primaryProfile.toLowerCase().includes(filter.toLowerCase()) ||
      s.notes.toLowerCase().includes(filter.toLowerCase());
    const matchesCat = catFilter === 'All' || s.category === catFilter;
    const matchesMaturity = maturityFilter === 'All' || s.maturity === maturityFilter;
    return matchesSearch && matchesCat && matchesMaturity;
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Skill Registry</h1>
        <p className="text-slate-400 max-w-3xl">
          All skills with manifests, semver, error taxonomy, retry policy and profile mapping.
          {skills.length} skills registered.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-col lg:flex-row gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search skills, profiles..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500"
          />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="w-4 h-4 text-slate-500" />
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setCatFilter(cat)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                catFilter === cat
                  ? 'bg-brand-900/40 text-brand-300 border border-brand-700/30'
                  : 'bg-slate-800 text-slate-400 border border-slate-700 hover:text-white'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {(['All','stable','experimental','deprecated'] as const).map(m => (
            <button
              key={m}
              onClick={() => setMaturityFilter(m)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                maturityFilter === m
                  ? 'bg-purple-900/40 text-purple-300 border border-purple-700/30'
                  : 'bg-slate-800 text-slate-400 border border-slate-700 hover:text-white'
              }`}
            >
              {m === 'All' ? 'All maturities' : m}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-slate-800/80 text-slate-400 text-xs uppercase">
              <tr>
                <th className="px-5 py-3 font-medium">Skill</th>
                <th className="px-5 py-3 font-medium">Category</th>
                <th className="px-5 py-3 font-medium">Primary profile</th>
                <th className="px-5 py-3 font-medium">Load</th>
                <th className="px-5 py-3 font-medium">Maturity</th>
                <th className="px-5 py-3 font-medium">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {filtered.map(skill => (
                <tr key={skill.name} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <Wrench className="w-4 h-4 text-brand-400 shrink-0" />
                      <span className="text-white font-medium">{skill.name}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <span className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-300 text-xs border border-slate-700">
                      {skill.category}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-300">{skill.primaryProfile}</td>
                  <td className="px-5 py-3">
                    <span className={`badge text-xs ${
                      skill.loadStrategy === 'core' ? 'badge-blue' :
                      skill.loadStrategy === 'specialist' ? 'badge-purple' : 'badge-amber'
                    }`}>
                      <Layers className="w-3 h-3 mr-1" />
                      {skill.loadStrategy}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <span className={`badge text-xs ${
                      skill.maturity === 'stable' ? 'badge-green' :
                      skill.maturity === 'experimental' ? 'badge-amber' : 'badge-red'
                    }`}>
                      {skill.maturity === 'stable' ? <CheckCircle2 className="w-3 h-3 mr-1" /> :
                       skill.maturity === 'experimental' ? <AlertTriangle className="w-3 h-3 mr-1" /> : null}
                      {skill.maturity}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-400 max-w-xs truncate">{skill.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-5 py-3 border-t border-slate-700/50 text-xs text-slate-500">
          Showing {filtered.length} of {skills.length} skills
        </div>
      </div>
    </div>
  );
}
