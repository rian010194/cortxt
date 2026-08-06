import { useState } from 'react';
import { telemetryData, profiles, estimateRunCost, rateLimitStatus, fallbackChains } from '../data/systemData';
import {
  Activity, DollarSign, BarChart3, Cpu, Calculator,
  TrendingUp, TrendingDown, Minus, AlertTriangle, CheckCircle2,
  Shield, ArrowRight, Gift
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, BarChart, Bar, Legend
} from 'recharts';

export default function Telemetry() {
  const totalCost = telemetryData.reduce((sum, d) => sum + d.total, 0);
  const avgCost = totalCost / telemetryData.length;
  const peakCost = Math.max(...telemetryData.map(d => d.total));

  const profileCosts = profiles
    .filter(p => (p.costPer1MInput ?? 0) > 0)
    .map(p => ({
      name: p.name,
      inputCost: p.costPer1MInput!,
      outputCost: p.costPer1MOutput!,
      totalPer10k: ((p.costPer1MInput! + p.costPer1MOutput!) / 100),
    }));

  // Free tier profiles with daily limits
  const freeProfiles = profiles.filter(p => p.dailyLimit !== undefined);

  // Cost calculator state
  const [calcProfile, setCalcProfile] = useState('researcher');
  const [calcInput, setCalcInput] = useState(5000);
  const [calcOutput, setCalcOutput] = useState(2000);
  const calcResult = estimateRunCost(calcProfile, calcInput, calcOutput);
  const calcProfileData = profiles.find(p => p.id === calcProfile);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Telemetry & Cost</h1>
        <p className="text-slate-400 max-w-3xl">
          Kostnadsöversikt för AI Workspace-körningar. Auto-kalkylation tokens → USD är aktiv.
          Gratis-modeller (kimi-k2.6:free, qwen3-coder:free) med dagliga kvoter visas nedan.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-emerald-900/30">
            <DollarSign className="w-6 h-6 text-emerald-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">${totalCost.toFixed(2)}</div>
            <div className="text-sm text-slate-400">Total idag</div>
          </div>
        </div>
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-blue-900/30">
            <BarChart3 className="w-6 h-6 text-blue-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">${avgCost.toFixed(2)}</div>
            <div className="text-sm text-slate-400">Snitt/4h</div>
          </div>
        </div>
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-amber-900/30">
            <TrendingUp className="w-6 h-6 text-amber-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">${peakCost.toFixed(2)}</div>
            <div className="text-sm text-slate-400">Peak/4h</div>
          </div>
        </div>
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-purple-900/30">
            <Cpu className="w-6 h-6 text-purple-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{profiles.length}</div>
            <div className="text-sm text-slate-400">Profiler aktiva</div>
          </div>
        </div>
      </div>

      {/* Free Tier Quota Dashboard */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <Gift className="w-5 h-5 text-emerald-400" />
          <h2 className="text-xl font-semibold text-white">Gratis-kvoter idag</h2>
          <span className="badge badge-green text-xs">
            <CheckCircle2 className="w-3 h-3 mr-1" /> Auto-trackade
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {freeProfiles.map(p => {
            const status = rateLimitStatus[p.id as keyof typeof rateLimitStatus];
            if (!status || status.limit === Infinity) return null;
            const pct = (status.used / status.limit) * 100;
            const isLow = pct > 80;
            const isCritical = pct > 95;
            return (
              <div key={p.id} className={`p-4 rounded-lg border ${isCritical ? 'bg-rose-900/20 border-rose-700/40' : isLow ? 'bg-amber-900/20 border-amber-700/40' : 'bg-slate-800/50 border-slate-700/50'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-white">{p.name}</span>
                  <span className={`text-xs font-mono ${isCritical ? 'text-rose-400' : isLow ? 'text-amber-400' : 'text-emerald-400'}`}>
                    {status.used}/{status.limit}
                  </span>
                </div>
                <div className="w-full h-2 bg-slate-700 rounded-full mb-2">
                  <div
                    className={`h-2 rounded-full transition-all ${isCritical ? 'bg-rose-500' : isLow ? 'bg-amber-500' : 'bg-emerald-500'}`}
                    style={{ width: `${Math.min(pct, 100)}%` }}
                  />
                </div>
                <div className="text-xs text-slate-500">
                  {isCritical ? (
                    <span className="text-rose-400 flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3" /> Nästan slut — fallback aktiveras
                    </span>
                  ) : isLow ? (
                    <span className="text-amber-400 flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3" /> Låg kvot — spara för viktiga körningar
                    </span>
                  ) : (
                    <span className="text-emerald-400 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> {status.limit - status.used} kvar idag
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Fallback Chains */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <Shield className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Fallback-kedjor</h2>
          <span className="badge badge-blue text-xs">
            <ArrowRight className="w-3 h-3 mr-1" /> Dispatch-order
          </span>
        </div>
        <div className="space-y-4">
          {Object.entries(fallbackChains).map(([role, chain]) => (
            <div key={role} className="flex items-center gap-3 flex-wrap">
              <span className="text-sm font-medium text-white w-24 capitalize">{role}:</span>
              <div className="flex items-center gap-2">
                {chain.map((pid, i) => {
                  const p = profiles.find(pr => pr.id === pid);
                  const isFree = p?.dailyLimit !== undefined;
                  return (
                    <div key={pid} className="flex items-center gap-2">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${
                        isFree ? 'bg-emerald-900/30 text-emerald-300 border border-emerald-700/30' : 'bg-slate-800 text-slate-300 border border-slate-700'
                      }`}>
                        {p?.name || pid}
                        {isFree && <span className="ml-1 text-emerald-400">(∞)</span>}
                      </span>
                      {i < chain.length - 1 && <ArrowRight className="w-3 h-3 text-slate-600" />}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Cost Calculator */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <Calculator className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Cost Calculator</h2>
          <span className="badge badge-green text-xs">
            <CheckCircle2 className="w-3 h-3 mr-1" /> Live
          </span>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Profil</label>
              <select
                value={calcProfile}
                onChange={e => setCalcProfile(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-brand-500"
              >
                {profiles.map(p => (
                  <option key={p.id} value={p.id}>{p.name} ({p.model})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Input tokens</label>
              <input
                type="number"
                value={calcInput}
                onChange={e => setCalcInput(Number(e.target.value))}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-brand-500 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Output tokens</label>
              <input
                type="number"
                value={calcOutput}
                onChange={e => setCalcOutput(Number(e.target.value))}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-brand-500 font-mono"
              />
            </div>
          </div>

          <div className="lg:col-span-2">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
                <div className="text-xs text-slate-500 mb-1">Input cost</div>
                <div className="text-lg font-bold text-white">
                  ${((calcInput / 1_000_000) * (calcProfileData?.costPer1MInput ?? 0)).toFixed(4)}
                </div>
                <div className="text-xs text-slate-500">
                  ${calcProfileData?.costPer1MInput ?? 0}/1M tokens
                </div>
              </div>
              <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
                <div className="text-xs text-slate-500 mb-1">Output cost</div>
                <div className="text-lg font-bold text-white">
                  ${((calcOutput / 1_000_000) * (calcProfileData?.costPer1MOutput ?? 0)).toFixed(4)}
                </div>
                <div className="text-xs text-slate-500">
                  ${calcProfileData?.costPer1MOutput ?? 0}/1M tokens
                </div>
              </div>
              <div className="p-4 rounded-lg bg-emerald-900/20 border border-emerald-700/40">
                <div className="text-xs text-emerald-400 mb-1">Total cost</div>
                <div className="text-2xl font-bold text-emerald-300">${calcResult.amount.toFixed(4)}</div>
                <div className="text-xs text-emerald-500/70">{calcResult.currency}</div>
              </div>
            </div>
            {calcResult.amount > 5 && (
              <div className="p-3 rounded-lg bg-amber-900/20 border border-amber-700/40 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                <span className="text-sm text-amber-300">
                  Denna körning uppskattas kosta mer än $5. Överväg att använda nemotron-3-ultra (free tier) för planering/routing.
                </span>
              </div>
            )}
            {calcProfileData?.dailyLimit && (
              <div className="p-3 rounded-lg bg-blue-900/20 border border-blue-700/40 flex items-center gap-2">
                <Gift className="w-4 h-4 text-blue-400 shrink-0" />
                <span className="text-sm text-blue-300">
                  Denna profil har en daglig kvot på {calcProfileData.dailyLimit} requests.
                  När kvoten tar slut faller dispatch tillbaka till nästa profil i fallback-kedjan.
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Cost over time */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <Activity className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Kostnad över tid (24h)</h2>
        </div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={telemetryData}>
              <defs>
                <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#475569" fontSize={12} />
              <YAxis stroke="#475569" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px' }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Area type="monotone" dataKey="total" stroke="#3b82f6" fillOpacity={1} fill="url(#colorTotal)" name="Total USD" />
              <Area type="monotone" dataKey="coordinator" stroke="#a855f7" fill="none" name="Coordinator" />
              <Area type="monotone" dataKey="researcher" stroke="#3b82f6" fill="none" name="Researcher" />
              <Area type="monotone" dataKey="builder" stroke="#10b981" fill="none" name="Builder" />
              <Legend />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Profile cost comparison */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <div className="flex items-center gap-3 mb-5">
            <BarChart3 className="w-5 h-5 text-brand-400" />
            <h2 className="text-xl font-semibold text-white">Pris per profil (USD / 1M tokens)</h2>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={profileCosts} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis type="number" stroke="#475569" fontSize={12} />
                <YAxis dataKey="name" type="category" stroke="#475569" fontSize={12} width={120} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px' }}
                  labelStyle={{ color: '#94a3b8' }}
                />
                <Legend />
                <Bar dataKey="inputCost" fill="#3b82f6" name="Input" radius={[0, 4, 4, 0]} />
                <Bar dataKey="outputCost" fill="#10b981" name="Output" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="flex items-center gap-3 mb-5">
            <DollarSign className="w-5 h-5 text-brand-400" />
            <h2 className="text-xl font-semibold text-white">Kostnad per 10k tokens (in + out)</h2>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={profileCosts} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis type="number" stroke="#475569" fontSize={12} />
                <YAxis dataKey="name" type="category" stroke="#475569" fontSize={12} width={120} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px' }}
                  labelStyle={{ color: '#94a3b8' }}
                />
                <Bar dataKey="totalPer10k" fill="#f59e0b" name="USD / 10k tokens" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Model routing table with prices */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <Cpu className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Model Routing & Pricing</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-slate-800/80 text-slate-400 text-xs uppercase">
              <tr>
                <th className="px-5 py-3 font-medium">Profil</th>
                <th className="px-5 py-3 font-medium">Modell</th>
                <th className="px-5 py-3 font-medium">Provider</th>
                <th className="px-5 py-3 font-medium">Input/1M</th>
                <th className="px-5 py-3 font-medium">Output/1M</th>
                <th className="px-5 py-3 font-medium">Cost Tier</th>
                <th className="px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {profiles.map(p => (
                <tr key={p.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-5 py-3 text-white font-medium">{p.name}</td>
                  <td className="px-5 py-3 text-slate-300 font-mono text-xs">{p.model}</td>
                  <td className="px-5 py-3 text-slate-300">{p.provider}</td>
                  <td className="px-5 py-3 text-slate-300">
                    {p.costPer1MInput !== undefined ? `$${p.costPer1MInput.toFixed(2)}` : '—'}
                  </td>
                  <td className="px-5 py-3 text-slate-300">
                    {p.costPer1MOutput !== undefined ? `$${p.costPer1MOutput.toFixed(2)}` : '—'}
                  </td>
                  <td className="px-5 py-3">
                    <span className={`badge text-xs ${
                      p.costTier === 'free' ? 'badge-green' :
                      p.costTier === 'low' ? 'badge-blue' :
                      p.costTier === 'medium' ? 'badge-amber' : 'badge-red'
                    }`}>
                      {p.costTier === 'free' ? <TrendingDown className="w-3 h-3 mr-1" /> :
                       p.costTier === 'premium' ? <TrendingUp className="w-3 h-3 mr-1" /> :
                       <Minus className="w-3 h-3 mr-1" />}
                      {p.costTier}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <span className={`badge text-xs ${
                      p.status === 'verified' ? 'badge-green' :
                      p.status === 'experimental' ? 'badge-amber' : 'badge-red'
                    }`}>
                      {p.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
