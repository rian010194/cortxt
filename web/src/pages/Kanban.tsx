import { kanbanColumns, kanbanTasks, swarmGraph } from '../data/systemData';
import {
  KanbanSquare, GitBranch, CheckCircle2, Clock,
  Users, ArrowRight, Radio
} from 'lucide-react';

const columnColors: Record<string, string> = {
  backlog: 'border-slate-600',
  triage: 'border-yellow-600',
  ready: 'border-blue-600',
  'in-progress': 'border-amber-600',
  review: 'border-purple-600',
  blocked: 'border-rose-600',
  done: 'border-emerald-600',
};

const columnBg: Record<string, string> = {
  backlog: 'bg-slate-800/30',
  triage: 'bg-yellow-900/10',
  ready: 'bg-blue-900/10',
  'in-progress': 'bg-amber-900/10',
  review: 'bg-purple-900/10',
  blocked: 'bg-rose-900/10',
  done: 'bg-emerald-900/10',
};

export default function Kanban() {
  return (
    <div className="space-y-8 min-w-0">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Kanban & Swarm</h1>
        <p className="text-slate-400 max-w-3xl">
          Hermes Kanban board <code>cortxt-cp</code> är execution ledger. Swarm-mode skapar automatiska grafer
          med workers → verifier → synthesizer.
        </p>
      </div>

      {/* Kanban Board */}
      <div className="card max-w-full overflow-x-auto" tabIndex={0} aria-label="Kanban board">
        <div className="flex items-center gap-3 mb-5">
          <KanbanSquare className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">cortxt-cp Board</h2>
          <span className="badge badge-blue text-xs">
            <Radio className="w-3 h-3 mr-1" /> Gateway dispatch aktiv
          </span>
        </div>
        <div className="flex gap-4 overflow-x-auto" tabIndex={0} aria-label="Kanban columns">
          {kanbanColumns.map(col => {
            const tasks = kanbanTasks.filter(t => t.column === col.id);
            return (
              <div key={col.id} className={`shrink-0 w-72 rounded-xl border-t-4 ${columnColors[col.id]} ${columnBg[col.id]} p-3`}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-white">{col.name}</h3>
                  <span className="text-xs text-slate-400 bg-slate-800 px-2 py-0.5 rounded-full">{tasks.length}</span>
                </div>
                <div className="space-y-2">
                  {tasks.map(task => (
                    <div key={task.id} className="p-3 rounded-lg bg-slate-850 border border-slate-700/50 hover:border-slate-600 transition-colors">
                      <div className="text-sm text-white font-medium mb-2">{task.title}</div>
                      <div className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-400">{task.issue}</span>
                          {task.runId && (
                            <span className="text-brand-400 font-mono">{task.runId.slice(-6)}</span>
                          )}
                        </div>
                        <span className={`px-1.5 py-0.5 rounded text-xs ${
                          task.assignee === 'coordinator' ? 'bg-purple-900/30 text-purple-300' :
                          task.assignee === 'researcher' ? 'bg-blue-900/30 text-blue-300' :
                          task.assignee === 'builder' ? 'bg-emerald-900/30 text-emerald-300' :
                          task.assignee === 'monitor' ? 'bg-amber-900/30 text-amber-300' :
                          'bg-slate-800 text-slate-400'
                        }`}>
                          {task.assignee}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Swarm Graph */}
      <div className="card">
        <div className="flex items-center gap-3 mb-5">
          <GitBranch className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Swarm Graph</h2>
          <span className="badge badge-green text-xs">
            <CheckCircle2 className="w-3 h-3 mr-1" /> Demonstrerad
          </span>
        </div>

        <div className="w-full max-w-full overflow-x-auto flex flex-col items-center gap-6" tabIndex={0} aria-label="Swarm graph">
          {/* Workers row */}
          <div className="flex items-center gap-4">
            <Users className="w-4 h-4 text-slate-400 mr-2" />
            {swarmGraph.workers.map((w, i) => (
              <div key={w.id} className="flex items-center gap-4">
                <div className="p-4 rounded-xl bg-blue-900/20 border border-blue-700/40 text-center min-w-[140px]">
                  <div className="flex items-center justify-center gap-1 mb-1">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span className="text-sm font-semibold text-white">{w.name}</span>
                  </div>
                  <div className="text-xs text-blue-300">{w.task}</div>
                </div>
                {i < swarmGraph.workers.length - 1 && (
                  <span className="text-slate-400 text-xs">+</span>
                )}
              </div>
            ))}
          </div>

          {/* Arrow down */}
          <div className="flex items-center gap-2 text-slate-400">
            <ArrowRight className="w-4 h-4 rotate-90" />
            <span className="text-xs">Alla workers done → verifier aktiveras</span>
          </div>

          {/* Verifier */}
          <div className="p-4 rounded-xl bg-purple-900/20 border border-purple-700/40 text-center min-w-[180px]">
            <div className="flex items-center justify-center gap-1 mb-1">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-semibold text-white">{swarmGraph.verifier.name}</span>
            </div>
            <div className="text-xs text-purple-300">{swarmGraph.verifier.task}</div>
          </div>

          {/* Arrow down */}
          <div className="flex items-center gap-2 text-slate-400">
            <ArrowRight className="w-4 h-4 rotate-90" />
            <span className="text-xs">Verifier done → synthesizer aktiveras</span>
          </div>

          {/* Synthesizer */}
          <div className="p-4 rounded-xl bg-emerald-900/20 border border-emerald-700/40 text-center min-w-[180px]">
            <div className="flex items-center justify-center gap-1 mb-1">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-semibold text-white">{swarmGraph.synthesizer.name}</span>
            </div>
            <div className="text-xs text-emerald-300">{swarmGraph.synthesizer.task}</div>
          </div>
        </div>

        <div className="mt-6 p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
          <div className="flex items-center gap-2 text-amber-300 text-sm font-medium mb-2">
            <Clock className="w-4 h-4" /> Observed behaviour
          </div>
          <p className="text-sm text-slate-400">
            I ticket #9 swarm-demo auto-completades tre researcher workers, men verifier och synthesizer
            tasks stannade i <code>ready</code> tills de manuellt claimades. Gateway dispatch är bevisad för
            scratch-workspace profiler; terminal-lane profiler (coordinator för verification/synthesis)
            kräver manuell claim.
          </p>
        </div>
      </div>

      {/* Kanban → GitHub Mirror */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <GitBranch className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Kanban → GitHub Mirror</h2>
          <span className="badge badge-green text-xs">
            <CheckCircle2 className="w-3 h-3 mr-1" /> Operational
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
          <div className="p-4 rounded-lg bg-slate-800/50">
            <div className="text-slate-400 text-xs mb-1">Cron schedule</div>
            <div className="text-white font-mono">*/10 * * * *</div>
            <div className="text-slate-400 text-xs mt-1">Var 10:e minut</div>
          </div>
          <div className="p-4 rounded-lg bg-slate-800/50">
            <div className="text-slate-400 text-xs mb-1">Script</div>
            <div className="text-white font-mono text-sm">mirror-kanban-to-github.py</div>
            <div className="text-slate-400 text-xs mt-1">Poll done-tasks, post som kommentar</div>
          </div>
          <div className="p-4 rounded-lg bg-slate-800/50">
            <div className="text-slate-400 text-xs mb-1">Output</div>
            <div className="text-white text-sm">Resultat-envelope som issue-kommentar</div>
            <div className="text-slate-400 text-xs mt-1">Inkluderar status, artifacts, evidence</div>
          </div>
        </div>
      </div>
    </div>
  );
}
