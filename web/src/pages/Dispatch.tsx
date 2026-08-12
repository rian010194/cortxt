import { useState } from 'react';
import { dispatchSchema, profiles, estimateRunCost, fallbackChains, rateLimitStatus } from '../data/systemData';
import { Send, CheckCircle2, AlertTriangle, FileJson, ArrowRight, DollarSign } from 'lucide-react';

export default function Dispatch() {
  const [activeTab, setActiveTab] = useState<'request' | 'envelope'>('request');
  const [formData, setFormData] = useState<Record<string, any>>({
    issue_id: 'rian010194/ai-workspace#9',
    workflow: 'vertical-01-ai-act/classify',
    worker_role: 'researcher',
    scope: 'Classify AI system under EU AI Act Articles 2-3, 5, 6',
    acceptance_criteria: ['Valid JSON output', 'All risk classes identified', 'Confidence scores included'],
    max_runtime_seconds: 3600,
    max_cost_usd: 10.00,
    max_parallel_workers: 2,
    delegation_depth: 1,
    artifact_policy: 'workspace_only',
    approval_ref: 'https://github.com/rian010194/ai-workspace/issues/9#issuecomment-123',
  });

  const [resultData] = useState({
    issue_id: 'rian010194/ai-workspace#9',
    run_id: 'run-2026-08-04-005',
    status: 'succeeded',
    runtime: 'hermes-kanban-gateway',
    worker_role: 'researcher',
    started_at: '2026-08-04T08:30:00Z',
    finished_at: '2026-08-04T08:36:00Z',
    model: 'kimi-k2.6',
    usage: { input_tokens: 4523, output_tokens: 1892, cache_tokens: 0, reasoning_tokens: 0 },
    cost: { amount: 0.12, confidence: 'actual' },
    artifacts: [
      { ref: 'workspace/output/assessment.json', hash: 'sha256:a1b2...', size: 4096 },
    ],
    evidence: ['Synthetic eval passed 6/6', 'Schema validation OK', 'No prohibited practices detected'],
  });

  const updateField = (name: string, value: any) => {
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Dispatch Contract</h1>
        <p className="text-slate-400 max-w-3xl">
          JSON Schema-validerad dispatch request och result envelope. Alla fält är obligatoriska.
          Secrets, customer content, prompts och model reasoning får ej embeddas.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => setActiveTab('request')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'request'
              ? 'bg-brand-900/40 text-brand-300 border border-brand-700/30'
              : 'bg-slate-800 text-slate-400 border border-slate-700 hover:text-white'
          }`}
        >
          <Send className="w-4 h-4 inline mr-2" />
          Dispatch Request
        </button>
        <button
          onClick={() => setActiveTab('envelope')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'envelope'
              ? 'bg-brand-900/40 text-brand-300 border border-brand-700/30'
              : 'bg-slate-800 text-slate-400 border border-slate-700 hover:text-white'
          }`}
        >
          <FileJson className="w-4 h-4 inline mr-2" />
          Result Envelope
        </button>
      </div>

      {activeTab === 'request' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <div className="card space-y-4">
            <div className="flex items-center gap-3 mb-2">
              <Send className="w-5 h-5 text-brand-400" />
              <h2 className="text-xl font-semibold text-white">Dispatch Request</h2>
              <span className="badge badge-blue text-xs">
                <CheckCircle2 className="w-3 h-3 mr-1" /> JSON Schema
              </span>
            </div>

            {dispatchSchema.fields.map(field => (
              <div key={field.name}>
                <label className="block text-xs font-medium text-slate-400 mb-1.5">
                  {field.name}
                  {dispatchSchema.required.includes(field.name) && (
                    <span className="text-rose-400 ml-1">*</span>
                  )}
                </label>
                {field.type === 'enum' ? (
                  <select
                    value={formData[field.name] || ''}
                    onChange={e => updateField(field.name, e.target.value)}
                    aria-label={field.name}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-brand-500"
                  >
                    {field.values?.map(v => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                ) : field.type === 'array' ? (
                  <textarea
                    value={Array.isArray(formData[field.name]) ? formData[field.name].join('\n') : ''}
                    onChange={e => updateField(field.name, e.target.value.split('\n').filter(Boolean))}
                    rows={3}
                    aria-label={field.name}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 font-mono"
                  />
                ) : field.type === 'integer' || field.type === 'number' ? (
                  <input
                    type="number"
                    value={formData[field.name] || ''}
                    onChange={e => updateField(field.name, field.type === 'integer' ? parseInt(e.target.value) : parseFloat(e.target.value))}
                    aria-label={field.name}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-brand-500 font-mono"
                  />
                ) : (
                  <input
                    type="text"
                    value={formData[field.name] || ''}
                    onChange={e => updateField(field.name, e.target.value)}
                    aria-label={field.name}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-brand-500 font-mono"
                  />
                )}
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-slate-400">{field.type}</span>
                  {field.pattern && <span className="text-xs text-slate-400">pattern: {field.pattern}</span>}
                  {field.min !== undefined && <span className="text-xs text-slate-400">min: {field.min}</span>}
                  {field.max !== undefined && <span className="text-xs text-slate-400">max: {field.max}</span>}
                </div>
              </div>
            ))}

            {/* Cost estimation */}
            <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
              <div className="flex items-center gap-2 text-sm font-medium text-white mb-2">
                <DollarSign className="w-4 h-4 text-emerald-400" />
                Kostnadsuppskattning
              </div>
              {(() => {
                const profile = profiles.find(p => p.id === formData.worker_role);
                const est = estimateRunCost(formData.worker_role, 5000, 2000);
                const estAmount = est.amount === null ? null : est.amount;
                return (
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between text-slate-400">
                      <span>Profil:</span>
                      <span className="text-white">{profile?.name || formData.worker_role}</span>
                    </div>
                    <div className="flex justify-between text-slate-400">
                      <span>Est. för 5k in + 2k out:</span>
                      <span className="text-emerald-300 font-mono">{estAmount === null ? '—' : `$${estAmount.toFixed(4)}`} {est.currency}</span>
                    </div>
                    <div className="flex justify-between text-slate-400">
                      <span>Max cost ceiling:</span>
                      <span className={`font-mono ${estAmount !== null && formData.max_cost_usd < estAmount * 10 ? 'text-amber-300' : 'text-white'}`}>
                        ${formData.max_cost_usd.toFixed(2)}
                      </span>
                    </div>
                    {estAmount !== null && formData.max_cost_usd < estAmount * 10 && (
                      <div className="flex items-center gap-2 text-amber-300 text-xs">
                        <AlertTriangle className="w-3 h-3" />
                        Low ceiling — ~10x est. körningar innan gräns.
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>

            {/* Fallback chain */}
            {(() => {
              const chain = fallbackChains[formData.worker_role as keyof typeof fallbackChains];
              if (!chain) return null;
              return (
                <div className="p-4 rounded-lg bg-blue-900/20 border border-blue-700/40">
                  <div className="flex items-center gap-2 text-sm font-medium text-white mb-2">
                    <ArrowRight className="w-4 h-4 text-blue-400" />
                    Fallback-kedja
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {chain.map((pid: string, i: number) => {
                      const p = profiles.find(pr => pr.id === pid);
                      const rl = rateLimitStatus[pid as keyof typeof rateLimitStatus];
                      const isFree = p?.dailyLimit !== undefined;
                      const isExhausted = rl && rl.limit !== Infinity && rl.used >= rl.limit;
                      return (
                        <div key={pid} className="flex items-center gap-2">
                          <span className={`px-2 py-1 rounded text-xs font-medium ${
                            isExhausted ? 'bg-rose-900/30 text-rose-300 border border-rose-700/30' :
                            isFree ? 'bg-emerald-900/30 text-emerald-300 border border-emerald-700/30' :
                            'bg-slate-800 text-slate-300 border border-slate-700'
                          }`}>
                            {p?.name || pid}
                            {isFree && rl && <span className="ml-1">({rl.used}/{rl.limit})</span>}
                            {isExhausted && <span className="ml-1 text-rose-400">✗</span>}
                          </span>
                          {i < chain.length - 1 && <ArrowRight className="w-3 h-3 text-slate-400" />}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}
          </div>

          <div className="card">
            <div className="flex items-center gap-3 mb-4">
              <FileJson className="w-5 h-5 text-emerald-400" />
              <h2 className="text-xl font-semibold text-white">Genererad JSON</h2>
            </div>
            <pre tabIndex={0} aria-label="Genererad JSON" className="bg-slate-900 rounded-lg p-4 overflow-x-auto text-xs text-emerald-300 font-mono leading-relaxed">
              {JSON.stringify(formData, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {activeTab === 'envelope' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <div className="card space-y-4">
            <div className="flex items-center gap-3 mb-2">
              <FileJson className="w-5 h-5 text-emerald-400" />
              <h2 className="text-xl font-semibold text-white">Result Envelope</h2>
              <span className="badge badge-green text-xs">
                <CheckCircle2 className="w-3 h-3 mr-1" /> {resultData.status}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg bg-slate-800/50">
                <div className="text-xs text-slate-400 mb-1">issue_id</div>
                <div className="text-sm text-white font-mono">{resultData.issue_id}</div>
              </div>
              <div className="p-3 rounded-lg bg-slate-800/50">
                <div className="text-xs text-slate-400 mb-1">run_id</div>
                <div className="text-sm text-brand-300 font-mono">{resultData.run_id}</div>
              </div>
              <div className="p-3 rounded-lg bg-slate-800/50">
                <div className="text-xs text-slate-400 mb-1">runtime</div>
                <div className="text-sm text-white">{resultData.runtime}</div>
              </div>
              <div className="p-3 rounded-lg bg-slate-800/50">
                <div className="text-xs text-slate-400 mb-1">model</div>
                <div className="text-sm text-white">{resultData.model}</div>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-slate-800/50">
              <div className="text-xs text-slate-400 mb-2">Status transitions</div>
              <div className="flex items-center gap-2 text-sm">
                <span className="badge badge-blue text-xs">Ready</span>
                <ArrowRight className="w-3 h-3 text-slate-400" />
                <span className="badge badge-amber text-xs">In progress</span>
                <ArrowRight className="w-3 h-3 text-slate-400" />
                <span className="badge badge-purple text-xs">Review</span>
                <ArrowRight className="w-3 h-3 text-slate-400" />
                <span className="badge badge-green text-xs">Done</span>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-slate-800/50">
              <div className="text-xs text-slate-400 mb-2">Usage</div>
              <div className="grid grid-cols-4 gap-2 text-center">
                <div>
                  <div className="text-lg font-bold text-white">{resultData.usage.input_tokens}</div>
                  <div className="text-xs text-slate-400">input</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-white">{resultData.usage.output_tokens}</div>
                  <div className="text-xs text-slate-400">output</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-white">{resultData.usage.cache_tokens}</div>
                  <div className="text-xs text-slate-400">cache</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-white">{resultData.usage.reasoning_tokens}</div>
                  <div className="text-xs text-slate-400">reasoning</div>
                </div>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-emerald-900/20 border border-emerald-800/40">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-400">Cost</span>
                <span className={`badge text-xs ${resultData.cost.confidence === 'actual' ? 'badge-green' : 'badge-amber'}`}>
                  {resultData.cost.confidence}
                </span>
              </div>
              <div className="text-2xl font-bold text-emerald-300">${resultData.cost.amount.toFixed(2)}</div>
            </div>

            <div className="p-3 rounded-lg bg-slate-800/50">
              <div className="text-xs text-slate-400 mb-2">Evidence</div>
              <ul className="space-y-1">
                {resultData.evidence.map((e, i) => (
                  <li key={i} className="text-sm text-slate-300 flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="card">
            <div className="flex items-center gap-3 mb-4">
              <FileJson className="w-5 h-5 text-emerald-400" />
              <h2 className="text-xl font-semibold text-white">Raw JSON</h2>
            </div>
            <pre tabIndex={0} aria-label="Raw JSON" className="bg-slate-900 rounded-lg p-4 overflow-x-auto text-xs text-emerald-300 font-mono leading-relaxed">
              {JSON.stringify(resultData, null, 2)}
            </pre>

            <div className="mt-4 p-3 rounded-lg bg-emerald-900/20 border border-emerald-800/40">
              <div className="flex items-center gap-2 text-emerald-300 text-sm font-medium mb-1">
                <CheckCircle2 className="w-4 h-4" /> Cost telemetry active
              </div>
              <p className="text-sm text-slate-400">
                Auto-kalkylation tokens → USD är nu aktiv via lookup-tabell per profil.
                Kostnader beräknas från <code>input_tokens</code> och <code>output_tokens</code>
                med provider-specifika priser (OpenRouter free, Moonshot, OpenAI).
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
