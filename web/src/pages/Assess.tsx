import { useState } from 'react';
import { assessFixtures, validateInput, type AssessmentInput, type AssessmentOutput } from '../data/assessFixtures';
import {
  Send, CheckCircle2, AlertTriangle, FileJson, Scale, FlaskConical,
  ArrowRight, Loader2, BookOpen, ShieldAlert, FileText, CircleHelp
} from 'lucide-react';

const EMPTY: AssessmentInput = {
  case_id: 'EXT-',
  system_description: { name: '', purpose: '', intended_market: '', operator_type: 'provider' },
  system_capabilities: [],
  known_standards: [],
  jurisdiction_hints: ['EU'],
  question_focus: ['Art2', 'Art3', 'Art5', 'Art6'],
};

const riskStyles: Record<string, string> = {
  prohibited: 'badge-red',
  high_risk: 'badge-red',
  limited_risk: 'badge-amber',
  minimal_risk: 'badge-green',
  uncertain: 'badge-blue',
};

const confLabel: Record<string, string> = {
  certain: 'Säker', probable: 'Sannolik', uncertain: 'Osäker', needs_more_info: 'Kräver mer info',
};

function demoPlaceholder(input: AssessmentInput): AssessmentOutput {
  return {
    case_id: input.case_id,
    assessed_version: '0.1.0',
    applicability: { ai_act_applies: false, confidence: 'needs_more_info', basis_articles: ['Art2', 'Art3'] },
    classification: { system_risk_class: 'uncertain', basis_annex: null },
    obligations_assessed: [],
    decision_brief: {
      language: 'sv',
      text: `Detta är en DEMO-platshållare för "${input.system_description.name || 'okänt system'}". Bedömningen har inte körts mot en runtime. Anslut harness/dispatch (Phase 2 Session B) för att få en riktig klassificering och skyldigheter.`,
    },
    uncertainties: [
      { topic: 'Ingen runtime-anslutning', reason: 'Input accepteras av schemat men inget model/runtime-harness körs ännu i webb-UI:et.', suggested_research: 'Koppla webb-UI:et mot dispatch-manual.sh / harness och dispatcha ärendet som ett Ready GitHub-issue.' },
    ],
    schema_validation_passed: true,
    _provenance: 'demo_placeholder',
  };
}

export default function Assess() {
  const [input, setInput] = useState<AssessmentInput>(EMPTY);
  const [capsText, setCapsText] = useState('');
  const [result, setResult] = useState<AssessmentOutput | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [running, setRunning] = useState(false);

  const set = (patch: Partial<AssessmentInput>) => setInput(prev => ({ ...prev, ...patch }));

  function loadFixture(id: string) {
    const fx = assessFixtures.find(f => f.fixture_id === id);
    if (!fx) return;
    setInput(fx.input);
    setCapsText(fx.input.system_capabilities.join('\n'));
    setErrors([]);
    setResult(null);
  }

  function run() {
    const errs = validateInput(input);
    setErrors(errs);
    if (errs.length > 0) return;
    setRunning(true);
    // Simulated async step so the UI reads like a dispatch. No real model call:
    // fixture inputs return the package's approved reference output; any other
    // input returns an honest demo placeholder until the harness is wired.
    setTimeout(() => {
      const fx = assessFixtures.find(f => f.input.case_id === input.case_id);
      setResult(fx ? fx.expected_output : demoPlaceholder(input));
      setRunning(false);
    }, 400);
  }

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">AI Act Bedömning</h1>
          <p className="text-slate-400 max-w-3xl">
            Nya EU AI-förordningen (EU 2024/1689) — bedöm systembeskrivningen mot{' '}
            <code className="text-brand-300">vertical-01-ai-act</code> (Art 2-3, 5, 6, Annex I/III, skyldigheter 9-12).
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="badge badge-blue">vertical-01-ai-act v0.1.0</span>
          <span className="badge badge-amber"><AlertTriangle className="w-3 h-3 mr-1" /> Demo-UI</span>
        </div>
      </div>

      {/* Provenance / honesty banner */}
      <div className="p-3 rounded-lg bg-amber-900/20 border border-amber-800/40 text-sm text-amber-200">
        <div className="flex items-center gap-2 font-medium mb-1">
          <AlertTriangle className="w-4 h-4" /> Förhandsversion — inte en riktig modelkörning
        </div>
        <p className="text-slate-400">
          Laddar du en <em>syntetisk fixture</em> visas paketets godkända <strong>referensutfall</strong> (fixture
          <code> expected_output</code>). Fria indata returnerar en tydligt märkt platshållare tills webb-UI:et är
          kopplat till dispatcher/harness (Phase 2 Session B). Inget här är juridiskt bindande.
        </p>
      </div>

      {/* Fixture presets */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <FlaskConical className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Syntetiska fixtures (presets)</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {assessFixtures.map(fx => (
            <button
              key={fx.fixture_id}
              onClick={() => loadFixture(fx.fixture_id)}
              className={`px-3 py-2 rounded-lg text-xs font-medium border transition-colors ${
                input.case_id === fx.input.case_id
                  ? 'bg-brand-900/40 text-brand-300 border-brand-700/30'
                  : 'bg-slate-800 text-slate-300 border-slate-700 hover:border-brand-600 hover:text-white'
              }`}
            >
              {fx.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Input form */}
        <div className="card space-y-4">
          <div className="flex items-center gap-3 mb-2">
            <Send className="w-5 h-5 text-brand-400" />
            <h2 className="text-xl font-semibold text-white">Systembeskrivning (input)</h2>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">case_id <span className="text-rose-400">*</span></label>
              <input
                value={input.case_id}
                onChange={e => set({ case_id: e.target.value })}
                placeholder="EXT-… / SYNTH-…"
                className="inp font-mono"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">operator_type <span className="text-rose-400">*</span></label>
              <select value={input.system_description.operator_type} onChange={e => set({ system_description: { ...input.system_description, operator_type: e.target.value as any } })} className="inp">
                {['provider', 'deployer', 'importer', 'distributor'].map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Systemnamn <span className="text-rose-400">*</span></label>
            <input value={input.system_description.name} onChange={e => set({ system_description: { ...input.system_description, name: e.target.value } })} className="inp" />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Syfte <span className="text-rose-400">*</span></label>
            <textarea
              value={input.system_description.purpose}
              onChange={e => set({ system_description: { ...input.system_description, purpose: e.target.value } })}
              rows={3} className="inp"
              placeholder="Beskriv systemets syfte (max 2000 tecken)"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Avsedd marknad</label>
            <input value={input.system_description.intended_market} onChange={e => set({ system_description: { ...input.system_description, intended_market: e.target.value } })} className="inp" placeholder="t.ex. EU sjukhus och kliniker" />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Systemkapaciteter <span className="text-rose-400">*</span></label>
            <textarea
              value={capsText}
              onChange={e => {
                setCapsText(e.target.value);
                set({ system_capabilities: e.target.value.split('\n').filter(Boolean) });
              }}
              rows={3} className="inp font-mono" placeholder="En per rad (Annex III screening)"
            />
          </div>

          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-1.5 flex-wrap">
              {['Art2', 'Art3', 'Art5', 'Art6', 'Art9', 'Art10', 'Art11', 'Art12'].map(a => {
                const on = input.question_focus.includes(a as any);
                return (
                  <button
                    key={a}
                    onClick={() => set({
                      question_focus: on ? input.question_focus.filter(x => x !== a) : [...input.question_focus, a as any],
                    })}
                    className={`px-2 py-1 rounded text-xs font-mono border transition-colors ${
                      on ? 'bg-brand-900/40 text-brand-300 border-brand-700/40' : 'bg-slate-800 text-slate-500 border-slate-700'
                    }`}
                  >
                    {a}
                  </button>
                );
              })}
            </div>
            <span className="text-xs text-slate-500">question_focus</span>
          </div>

          {errors.length > 0 && (
            <div className="p-3 rounded-lg bg-rose-900/20 border border-rose-800/40 text-sm text-rose-200 space-y-1">
              {errors.map((e, i) => <div key={i} className="flex items-start gap-2"><AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {e}</div>)}
            </div>
          )}

          <button
            onClick={run}
            disabled={running}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-brand-600 hover:bg-brand-500 text-white font-semibold transition-colors disabled:opacity-50"
          >
            {running ? <Loader2 className="w-5 h-5 animate-spin" /> : <Scale className="w-5 h-5" />}
            {running ? 'Kör bedömning…' : 'Kör bedömning'}
          </button>
        </div>

        {/* Result */}
        <div className="card space-y-4">
          <div className="flex items-center gap-3">
            <FileJson className="w-5 h-5 text-emerald-400" />
            <h2 className="text-xl font-semibold text-white">Beslut</h2>
            {result && (
              <span className={`badge text-xs ${result._provenance === 'fixture_reference' ? 'badge-green' : 'badge-blue'}`}>
                {result._provenance === 'fixture_reference' ? 'Referens (fixture)' : 'Demo-platshållare'}
              </span>
            )}
          </div>

          {!result ? (
            <div className="p-8 text-center text-slate-500 text-sm border border-dashed border-slate-700 rounded-lg">
              <ShieldAlert className="w-8 h-8 mx-auto mb-2 opacity-40" />
              Fyll i input (eller ladda en preset) och kör bedömningen.
            </div>
          ) : (
            <>
              {/* Applicability */}
              <div className="p-3 rounded-lg bg-slate-800/50">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-500">Tillämplighet</span>
                  <span className={`badge text-xs ${result.applicability.ai_act_applies ? 'badge-red' : 'badge-green'}`}>
                    {result.applicability.ai_act_applies ? 'AI-förordningen tillämpas' : 'Tillämpas inte'}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-slate-400">Konfidens:</span>
                  <span className="text-white font-medium">{confLabel[result.applicability.confidence]}</span>
                  <span className="text-slate-600">·</span>
                  <span className="text-slate-400">Grund:</span>
                  <span className="text-white font-mono">{result.applicability.basis_articles.join(', ')}</span>
                </div>
              </div>

              {/* Classification */}
              <div className="p-3 rounded-lg bg-slate-800/50">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-500">Riskklassificering</span>
                  <span className={`badge text-xs ${riskStyles[result.classification.system_risk_class]}`}>
                    {result.classification.system_risk_class.replace(/_/g, ' ')}
                  </span>
                </div>
                {result.classification.basis_annex && (
                  <div className="text-sm text-slate-300">Grundlag: <span className="font-mono">{result.classification.basis_annex}</span></div>
                )}
              </div>

              {/* Decision brief (sv) */}
              {result.decision_brief.text && (
                <div className="p-3 rounded-lg bg-slate-800/50">
                  <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                    <BookOpen className="w-4 h-4" /> Beslutsunderlag ({result.decision_brief.language})
                  </div>
                  <p className="text-sm text-slate-200 leading-relaxed">{result.decision_brief.text}</p>
                </div>
              )}

              {/* Obligations */}
              {result.obligations_assessed.length > 0 && (
                <div className="p-3 rounded-lg bg-slate-800/50">
                  <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                    <FileText className="w-4 h-4" /> Tillämpliga skyldigheter
                  </div>
                  <div className="space-y-2">
                    {result.obligations_assessed.map((o, i) => (
                      <div key={i} className="flex items-start gap-2 text-sm">
                        <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                        <div>
                          <span className="text-white font-mono">{o.article}</span>
                          {!o.primary_source_verified && (
                            <span className="ml-2 badge badge-amber text-xs">Needs primary-source research</span>
                          )}
                          <p className="text-slate-400 text-xs mt-0.5">{o.summary}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Uncertainties */}
              {result.uncertainties.length > 0 && (
                <div className="p-3 rounded-lg bg-blue-900/20 border border-blue-800/40">
                  <div className="flex items-center gap-2 text-xs text-blue-300 mb-2">
                    <CircleHelp className="w-4 h-4" /> Osäkerheter & rekommendationer
                  </div>
                  <div className="space-y-2">
                    {result.uncertainties.map((u, i) => (
                      <div key={i} className="text-xs">
                        <div className="text-blue-200 font-medium">{u.topic}</div>
                        <div className="text-slate-400">{u.reason}</div>
                        <div className="text-slate-500 mt-0.5">Föreslagen forskning: {u.suggested_research}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.schema_validation_passed && (
                <div className="flex items-center gap-2 text-xs text-emerald-300">
                  <CheckCircle2 className="w-4 h-4" /> schema_validation_passed: true
                </div>
              )}

              {/* Raw JSON */}
              <div>
                <pre className="bg-slate-900 rounded-lg p-4 overflow-x-auto text-xs text-emerald-300 font-mono leading-relaxed max-h-72 overflow-y-auto">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </div>

              <div className="flex items-center gap-2 text-xs text-slate-500">
                <ArrowRight className="w-3 h-3" />
                Nästa steg i produktionsflödet: skicka som Ready-issue → dispatch → Review → din approval (Done).
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
