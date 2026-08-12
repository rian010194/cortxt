import { flowSteps } from '../data/systemData';
import {
  CheckCircle2, AlertTriangle, ArrowRight, ArrowDown,
  MessageSquare, GitPullRequest, Send, Cpu, Eye, UserCheck
} from 'lucide-react';

const stepIcons: Record<string, React.ElementType> = {
  buzz: MessageSquare,
  github: GitPullRequest,
  dispatch: Send,
  runtime: Cpu,
  review: Eye,
  approval: UserCheck,
};

export default function Flow() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">End-to-End Flöde</h1>
        <p className="text-slate-400 max-w-3xl">
          Visualisering av hela flödet från Buzz-operator till färdig leverans.
          Varje steg visar verifierad status, blockers och outputs.
        </p>
      </div>

      <div className="relative">
        {/* Connector line */}
        <div className="absolute left-8 top-12 bottom-12 w-0.5 bg-slate-700 hidden md:block" />

        <div className="space-y-6">
          {flowSteps.map((step, idx) => {
            const Icon = stepIcons[step.id];
            const isLast = idx === flowSteps.length - 1;
            return (
              <div key={step.id} className="relative">
                <div className="card md:ml-16 relative">
                  {/* Step number */}
                  <div className="hidden md:flex absolute -left-[4.5rem] top-5 w-10 h-10 rounded-full bg-slate-800 border border-slate-600 items-center justify-center text-sm font-bold text-white z-10">
                    {idx + 1}
                  </div>

                  <div className="flex items-start gap-4">
                    <div className={`p-3 rounded-lg shrink-0 ${step.verified ? 'bg-emerald-900/30' : 'bg-amber-900/30'}`}>
                      <Icon className={`w-6 h-6 ${step.verified ? 'text-emerald-400' : 'text-amber-400'}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-3 mb-1">
                        <h3 className="text-lg font-semibold text-white">{step.title}</h3>
                        <span className="text-sm text-slate-400">{step.subtitle}</span>
                        {step.verified ? (
                          <span className="badge badge-green">
                            <CheckCircle2 className="w-3 h-3 mr-1" /> Verifierad
                          </span>
                        ) : (
                          <span className="badge badge-amber">
                            <AlertTriangle className="w-3 h-3 mr-1" /> Partial
                          </span>
                        )}
                      </div>
                      <p className="text-slate-400 text-sm mb-3">{step.description}</p>

                      {step.blockers.length > 0 && (
                        <div className="mb-3 p-3 rounded-lg bg-rose-900/20 border border-rose-800/40">
                          <div className="flex items-center gap-2 text-rose-300 text-sm font-medium mb-1">
                            <AlertTriangle className="w-4 h-4" /> Kända blockers
                          </div>
                          <ul className="space-y-1">
                            {step.blockers.map((b, i) => (
                              <li key={i} className="text-rose-200/80 text-sm flex items-start gap-2">
                                <span className="text-rose-400 mt-1">•</span> {b}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      <div className="flex flex-wrap gap-2">
                        {step.outputs.map((output, i) => (
                          <span key={i} className="badge badge-blue text-xs">
                            <ArrowRight className="w-3 h-3 mr-1" /> {output}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                {!isLast && (
                  <div className="flex justify-center py-3 md:hidden">
                    <ArrowDown className="w-5 h-5 text-slate-400" />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
