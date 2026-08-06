import { vertical01, bvcs } from '../data/systemData';
import {
  Boxes, CheckCircle2, AlertTriangle, FileText,
  GitBranch, TestTube, Shield, BookOpen
} from 'lucide-react';

export default function Verticals() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Vertical Packages</h1>
        <p className="text-slate-400 max-w-3xl">
          Vertical packages deklarerar <strong>vad</strong> som ska göras utan att äga runtime-infrastruktur.
          Harness avgör <strong>hur</strong> arbetet körs säkert.
        </p>
      </div>

      {/* Vertical 01 AI Act */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <Boxes className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">{vertical01.name}</h2>
          <span className="badge badge-blue text-xs">v{vertical01.version}</span>
          <span className="badge badge-green text-xs">
            <CheckCircle2 className="w-3 h-3 mr-1" /> Active
          </span>
        </div>

        <p className="text-slate-400 text-sm mb-6">{vertical01.description}</p>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Workflows */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <GitBranch className="w-4 h-4 text-brand-400" />
              <h3 className="text-sm font-semibold text-white">Workflows</h3>
            </div>
            <div className="space-y-3">
              {vertical01.workflows.map(wf => (
                <div key={wf.name} className="p-3 rounded-lg bg-slate-800/50 border border-slate-700/50">
                  <div className="text-white font-medium text-sm mb-1">{wf.name}</div>
                  <div className="text-xs text-slate-400 mb-2">{wf.description}</div>
                  <div className="flex gap-2 text-xs">
                    <span className="text-slate-500">in: <span className="text-brand-400 font-mono">{wf.input}</span></span>
                    <span className="text-slate-600">→</span>
                    <span className="text-slate-500">out: <span className="text-emerald-400 font-mono">{wf.output}</span></span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Schemas */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <FileText className="w-4 h-4 text-brand-400" />
              <h3 className="text-sm font-semibold text-white">Schemas</h3>
            </div>
            <div className="space-y-2">
              {vertical01.schemas.map(schema => (
                <div key={schema} className="flex items-center gap-2 p-2 rounded-lg bg-slate-800/50 text-sm">
                  <FileText className="w-4 h-4 text-slate-500 shrink-0" />
                  <span className="text-slate-300 font-mono text-xs">{schema}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Evals */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <TestTube className="w-4 h-4 text-brand-400" />
              <h3 className="text-sm font-semibold text-white">Synthetic Evals</h3>
            </div>
            <div className="space-y-2">
              {Object.entries(vertical01.evals).map(([key, count]) => (
                <div key={key} className="flex items-center justify-between p-2 rounded-lg bg-slate-800/50">
                  <span className="text-sm text-slate-300 capitalize">{key} cases</span>
                  <span className="text-sm font-bold text-white">{count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Decision basis */}
        <div className="mt-6 p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
          <div className="flex items-center gap-2 mb-3">
            <BookOpen className="w-4 h-4 text-brand-400" />
            <h3 className="text-sm font-semibold text-white">Decision Basis</h3>
          </div>
          <div className="flex flex-wrap gap-2 mb-3">
            {vertical01.decisionBasis.map(item => (
              <span key={item} className="px-2 py-1 rounded-md bg-brand-900/30 text-brand-300 text-xs border border-brand-700/30">
                {item}
              </span>
            ))}
          </div>
          <div className="text-xs text-slate-500">
            Requirements (v0.1): {vertical01.requirements.join(', ')}
            <span className="mx-2">|</span>
            Deferred (v0.2): {vertical01.deferred.join(', ')}
          </div>
        </div>
      </div>

      {/* BVC Contracts */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <Shield className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Behaviour Validator Contracts (BVC)</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {bvcs.map(bvc => (
            <div key={bvc.name} className={`p-4 rounded-lg border ${
              bvc.severity === 'critical' ? 'bg-rose-900/10 border-rose-800/40' :
              bvc.severity === 'warning' ? 'bg-amber-900/10 border-amber-800/40' :
              'bg-blue-900/10 border-blue-800/40'
            }`}>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-white font-medium text-sm">{bvc.name}</h4>
                <span className={`badge text-xs ${
                  bvc.severity === 'critical' ? 'badge-red' :
                  bvc.severity === 'warning' ? 'badge-amber' : 'badge-blue'
                }`}>
                  {bvc.severity}
                </span>
              </div>
              <p className="text-xs text-slate-400 mb-2">{bvc.description}</p>
              <div className="text-xs font-mono text-slate-300">{bvc.threshold}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Package structure */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <Boxes className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Intended Package Shape</h2>
        </div>
        <pre className="bg-slate-900 rounded-lg p-4 overflow-x-auto text-xs text-slate-300 font-mono leading-relaxed">
{`verticals/<vertical-id>/
|-- vertical.yaml
|-- README.md
|-- workflows/
|-- schemas/
|-- instructions/
|-- evals/
|   \-- synthetic/
\-- templates/`}
        </pre>
        <div className="mt-4 p-3 rounded-lg bg-amber-900/20 border border-amber-800/40">
          <div className="flex items-center gap-2 text-amber-300 text-sm font-medium mb-1">
            <AlertTriangle className="w-4 h-4" /> Contract rule
          </div>
          <p className="text-sm text-slate-400">
            A vertical must not own: GitHub/n8n/Kanban dispatchers, Docker images, host mounts,
            provider API keys, hard-coded provider selection, platform-wide approval state machine,
            or real customer documents.
          </p>
        </div>
      </div>
    </div>
  );
}
