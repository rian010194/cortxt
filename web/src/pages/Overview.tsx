import { useState } from 'react';
import { profiles, receptionists } from '../data/systemData';
import {
  Radio, CheckCircle2, AlertTriangle, XCircle,
  Zap, Shield, GitBranch, Box, ArrowRight
} from 'lucide-react';

const archNodes = [
  { id: 'buzz', label: 'Buzz', sub: 'Operator Dialog', color: 'bg-purple-600', border: 'border-purple-400' },
  { id: 'github', label: 'GitHub', sub: 'Source of Truth', color: 'bg-blue-600', border: 'border-blue-400' },
  { id: 'dispatch', label: 'Dispatch', sub: 'Claim & Run ID', color: 'bg-amber-600', border: 'border-amber-400' },
  { id: 'hermes', label: 'Hermes', sub: 'Coordinator / Researcher', color: 'bg-emerald-600', border: 'border-emerald-400' },
  { id: 'pi', label: 'Pi Builder', sub: 'Bounded Writes', color: 'bg-cyan-600', border: 'border-cyan-400' },
  { id: 'kanban', label: 'Kanban', sub: 'cortxt-cp', color: 'bg-indigo-600', border: 'border-indigo-400' },
  { id: 'result', label: 'Result', sub: 'Envelope', color: 'bg-pink-600', border: 'border-pink-400' },
  { id: 'codex', label: 'Codex', sub: 'Read-only Review', color: 'bg-rose-600', border: 'border-rose-400' },
  { id: 'approval', label: 'Operator', sub: 'Approval', color: 'bg-lime-600', border: 'border-lime-400' },
];

export default function Overview() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const verifiedCount = profiles.filter(p => p.status === 'verified').length;
  const experimentalCount = profiles.filter(p => p.status === 'experimental').length;
  const blockedCount = profiles.filter(p => p.status === 'blocked').length;
  const receptionistPartial = receptionists.filter(r => r.status === 'partial').length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">AI Workspace Control Plane</h1>
        <p className="text-slate-400 max-w-3xl">
          Interaktiv prototyp som visualiserar hela flödet från operator-dialog till godkänd leverans.
          GitHub Issues är source of truth. Hermes och Pi Builder är runtime. Codex är read-only review.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-emerald-900/30">
            <CheckCircle2 className="w-6 h-6 text-emerald-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{verifiedCount}</div>
            <div className="text-sm text-slate-400">Verifierade profiler</div>
          </div>
        </div>
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-amber-900/30">
            <AlertTriangle className="w-6 h-6 text-amber-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{experimentalCount}</div>
            <div className="text-sm text-slate-400">Experimentella profiler</div>
          </div>
        </div>
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-rose-900/30">
            <XCircle className="w-6 h-6 text-rose-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{blockedCount + receptionistPartial}</div>
            <div className="text-sm text-slate-400">Blockers / Partial</div>
          </div>
        </div>
        <div className="card flex items-center gap-4">
          <div className="p-3 rounded-lg bg-brand-900/30">
            <Radio className="w-6 h-6 text-brand-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-white">{profiles.length}</div>
            <div className="text-sm text-slate-400">Totala profiler</div>
          </div>
        </div>
      </div>

      {/* Architecture Diagram */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <GitBranch className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Arkitekturöversikt</h2>
        </div>
        <div className="overflow-x-auto">
          <div className="min-w-[800px] p-4">
            <div className="flex flex-wrap justify-center gap-4 mb-4">
              {archNodes.slice(0, 3).map(node => (
                <button
                  key={node.id}
                  onClick={() => setSelectedNode(selectedNode === node.id ? null : node.id)}
                  className={`relative p-4 rounded-xl border-2 min-w-[140px] text-center transition-all hover:scale-105 ${node.color} ${node.border} ${
                    selectedNode === node.id ? 'ring-2 ring-white ring-offset-2 ring-offset-slate-900' : ''
                  }`}
                >
                  <div className="text-white font-bold text-sm">{node.label}</div>
                  <div className="text-white/80 text-xs">{node.sub}</div>
                </button>
              ))}
            </div>
            <div className="flex justify-center mb-4">
              <ArrowRight className="w-5 h-5 text-slate-500 rotate-90" />
            </div>
            <div className="flex flex-wrap justify-center gap-4 mb-4">
              {archNodes.slice(3, 6).map(node => (
                <button
                  key={node.id}
                  onClick={() => setSelectedNode(selectedNode === node.id ? null : node.id)}
                  className={`relative p-4 rounded-xl border-2 min-w-[140px] text-center transition-all hover:scale-105 ${node.color} ${node.border} ${
                    selectedNode === node.id ? 'ring-2 ring-white ring-offset-2 ring-offset-slate-900' : ''
                  }`}
                >
                  <div className="text-white font-bold text-sm">{node.label}</div>
                  <div className="text-white/80 text-xs">{node.sub}</div>
                </button>
              ))}
            </div>
            <div className="flex justify-center mb-4">
              <ArrowRight className="w-5 h-5 text-slate-500 rotate-90" />
            </div>
            <div className="flex flex-wrap justify-center gap-4 mb-4">
              {archNodes.slice(6, 9).map(node => (
                <button
                  key={node.id}
                  onClick={() => setSelectedNode(selectedNode === node.id ? null : node.id)}
                  className={`relative p-4 rounded-xl border-2 min-w-[140px] text-center transition-all hover:scale-105 ${node.color} ${node.border} ${
                    selectedNode === node.id ? 'ring-2 ring-white ring-offset-2 ring-offset-slate-900' : ''
                  }`}
                >
                  <div className="text-white font-bold text-sm">{node.label}</div>
                  <div className="text-white/80 text-xs">{node.sub}</div>
                </button>
              ))}
            </div>
            <div className="flex justify-center">
              <ArrowRight className="w-5 h-5 text-slate-500 rotate-90" />
            </div>
            <div className="flex justify-center mt-4">
              <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700 text-center">
                <div className="text-xs text-slate-500">Feedback loop</div>
                <div className="text-sm text-slate-300">Approval → GitHub Done</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Key principles */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="card">
          <div className="flex items-center gap-3 mb-4">
            <Shield className="w-5 h-5 text-emerald-400" />
            <h2 className="text-xl font-semibold text-white">Kärnprinciper</h2>
          </div>
          <ul className="space-y-3 text-sm text-slate-300">
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
              <span>GitHub Issues/Projects är <strong>enda masterregistret</strong>. Ingen annan backlog får existera.</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
              <span>Ingen agent får godkänna sitt eget arbete. Operator approval är final gate.</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
              <span>Receptionist-pattern för alla externa systemintegrationer (Obsidian, Notion, Buzz, Hermes, Pi, Codex).</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
              <span>Skill framework med manifests, semver, error taxonomy, retry policy.</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
              <span>Dispatch contract med JSON Schema-validering för alla körningar.</span>
            </li>
          </ul>
        </div>

        <div className="card">
          <div className="flex items-center gap-3 mb-4">
            <Zap className="w-5 h-5 text-amber-400" />
            <h2 className="text-xl font-semibold text-white">Verifierade förmågor</h2>
          </div>
          <ul className="space-y-3 text-sm text-slate-300">
            <li className="flex items-start gap-2">
              <Box className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" />
              <span>Hermes routing till korrekt Researcher/Builder profiler</span>
            </li>
            <li className="flex items-start gap-2">
              <Box className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" />
              <span>Hermes Kanban gateway dispatch (scratch workspace, 36s)</span>
            </li>
            <li className="flex items-start gap-2">
              <Box className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" />
              <span>Swarm-mode: workers → verifier → synthesizer graf</span>
            </li>
            <li className="flex items-start gap-2">
              <Box className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" />
              <span>Kanban→GitHub mirror (cron var 10:e min)</span>
            </li>
            <li className="flex items-start gap-2">
              <Box className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" />
              <span>Pi Builder bounded writes + efterföljande Codex review</span>
            </li>
            <li className="flex items-start gap-2">
              <Box className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" />
              <span>Manuell dispatch med run_id, lease, result envelope</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
