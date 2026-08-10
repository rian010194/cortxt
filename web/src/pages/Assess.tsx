import { useState } from 'react';
import {
  assessFixtures, capabilityPresets, validateInput,
  type AssessmentInput, type AssessmentOutput,
} from '../data/assessFixtures';
import {
  Send, CheckCircle2, AlertTriangle, FileJson, Scale, FlaskConical,
  ArrowRight, Loader2, BookOpen, FileText, CircleHelp,
  Plus, Trash2, Layers,
} from 'lucide-react';

const riskStyles: Record<string, string> = {
  prohibited: 'badge-red', high_risk: 'badge-red', limited_risk: 'badge-amber',
  minimal_risk: 'badge-green', uncertain: 'badge-blue',
};
const riskLabel: Record<string, string> = {
  prohibited: 'Förbjuden', high_risk: 'Hög risk', limited_risk: 'Begränsad risk',
  minimal_risk: 'Minimal risk', uncertain: 'Osäker',
};
const confLabel: Record<string, string> = {
  certain: 'Säker', probable: 'Sannolik', uncertain: 'Osäker', needs_more_info: 'Kräver mer info',
};

interface Entry {
  id: string;
  input: AssessmentInput;
  result: AssessmentOutput | null;
  errors: string[];
  running: boolean;
  fixture_id?: string;
}

const newEntry = (): Entry => ({
  id: crypto.randomUUID(),
  input: {
    case_id: 'EXT-',
    system_description: { name: '', purpose: '', intended_market: '', operator_type: 'provider' },
    system_capabilities: [], known_standards: [], jurisdiction_hints: ['EU'],
    question_focus: ['Art2', 'Art3', 'Art5', 'Art6'],
  },
  result: null, errors: [], running: false,
});

function demoPlaceholder(input: AssessmentInput): AssessmentOutput {
  return {
    case_id: input.case_id,
    assessed_version: '0.1.0',
    applicability: { ai_act_applies: false, confidence: 'needs_more_info', basis_articles: ['Art2', 'Art3'] },
    classification: { system_risk_class: 'uncertain', basis_annex: null },
    obligations_assessed: [],
    decision_brief: { language: 'sv', text: `Detta är en DEMO-platshållare för "${input.system_description.name || 'okänt system'}". Bedömningen har inte körts mot en runtime. Anslut harness/dispatch (Phase 2 Session B) för att få en riktig klassificering och skyldigheter.` },
    uncertainties: [{ topic: 'Ingen runtime-anslutning', reason: 'Input accepteras av schemat men inget model/runtime-harness körs ännu i webb-UI:et.', suggested_research: 'Koppla webb-UI:et mot dispatch-manual.sh / harness och dispatcha ärendet som ett Ready GitHub-issue.' }],
    schema_validation_passed: true,
    _provenance: 'demo_placeholder',
  };
}

function setEntry(entries: Entry[], id: string, patch: Partial<Entry>): Entry[] {
  return entries.map(e => e.id === id ? { ...e, ...patch } : e);
}

// ---- capability picker: curated Annex III chips + free text ----
function CapabilityPicker({ input, onCaps }: { input: AssessmentInput; onCaps: (caps: string[]) => void }) {
  const toggle = (label: string) => {
    onCaps(input.system_capabilities.includes(label)
      ? input.system_capabilities.filter(c => c !== label)
      : [...input.system_capabilities, label]);
  };
  const groups = Array.from(new Set(capabilityPresets.map(p => p.group)));
  return (
    <div className="space-y-2">
      {groups.map(g => (
        <div key={g}>
          <div className="text-xs text-slate-500 mb-1">{g}</div>
          <div className="flex flex-wrap gap-1.5">
            {capabilityPresets.filter(p => p.group === g).map(p => {
              const on = input.system_capabilities.includes(p.label);
              return (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => toggle(p.label)}
                  className={`px-2 py-1 rounded text-xs border transition-colors ${
                    on ? 'bg-brand-900/40 text-brand-300 border-brand-700/40'
                      : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white hover:border-slate-500'
                  }`}
                >
                  {on && <CheckCircle2 className="w-3 h-3 inline mr-1" />}{p.label}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {/* custom free-text capabilities not in presets */}
      {input.system_capabilities.filter(c => !capabilityPresets.some(p => p.label === c)).map(c => (
        <span key={c} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-emerald-900/40 text-emerald-300 border border-emerald-700/40">
          {c}
          <button type="button" onClick={() => toggle(c)} className="text-emerald-300 hover:text-white"><Trash2 className="w-3 h-3" /></button>
        </span>
      ))}
    </div>
  );
}

// ---- single system card ----
function EntryCard({ entry, onChange, onRun }: { entry: Entry; onChange: (e: Entry) => void; onRun: () => void }) {
  const { input } = entry;
  const set = (patch: Partial<AssessmentInput>) => onChange({ ...entry, input: { ...input, ...patch }, result: null });
  const setDesc = (patch: Partial<AssessmentInput['system_description']>) =>
    set({ system_description: { ...input.system_description, ...patch } });
  const r = entry.result;

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Scale className="w-5 h-5 text-brand-400" />
          <h3 className="text-lg font-semibold text-white">
            {input.system_description.name || 'Nytt system'}
          </h3>
          {r && (
            <span className={`badge text-xs ${r.classification.system_risk_class === 'prohibited' || r.classification.system_risk_class === 'high_risk' ? 'badge-red' : 'badge-green'}`}>
              {riskLabel[r.classification.system_risk_class]}
            </span>
          )}
        </div>
        <button type="button" onClick={() => onChange({ ...entry, id: '__delete__' })}
          className="p-2 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-900/20 transition-colors"
          title="Ta bort system">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">case_id <span className="text-rose-400">*</span></label>
          <input value={input.case_id} onChange={e => set({ case_id: e.target.value })} className="inp font-mono" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">operator_type <span className="text-rose-400">*</span></label>
          <select value={input.system_description.operator_type} onChange={e => setDesc({ operator_type: e.target.value as any })} className="inp">
            {['provider', 'deployer', 'importer', 'distributor'].map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Systemnamn <span className="text-rose-400">*</span></label>
        <input value={input.system_description.name} onChange={e => setDesc({ name: e.target.value })} className="inp" />
      </div>
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Syfte <span className="text-rose-400">*</span></label>
        <textarea value={input.system_description.purpose} onChange={e => setDesc({ purpose: e.target.value })} rows={2} className="inp" placeholder="Beskriv systemets syfte (max 2000 tecken)" />
      </div>
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Avsedd marknad</label>
        <input value={input.system_description.intended_market} onChange={e => setDesc({ intended_market: e.target.value })} className="inp" placeholder="t.ex. EU sjukhus och kliniker" />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Systemkapaciteter <span className="text-rose-400">*</span></label>
        <CapabilityPicker input={input} onCaps={(caps) => set({ system_capabilities: caps })} />
        <textarea
          value={input.system_capabilities.filter(c => !capabilityPresets.some(p => p.label === c)).join('\n')}
          onChange={e => {
            const custom = e.target.value.split('\n').filter(Boolean);
            const presets = input.system_capabilities.filter(c => capabilityPresets.some(p => p.label === c));
            set({ system_capabilities: [...presets, ...custom] });
          }}
          rows={2} className="inp font-mono mt-2" placeholder="eller lägg till egna kapaciteter (en per rad)"
        />
      </div>

      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {['Art2', 'Art3', 'Art5', 'Art6', 'Art9', 'Art10', 'Art11', 'Art12'].map(a => {
            const on = input.question_focus.includes(a as any);
            return (
              <button key={a} type="button"
                onClick={() => set({ question_focus: on ? input.question_focus.filter(x => x !== a) : [...input.question_focus, a as any] })}
                className={`px-2 py-1 rounded text-xs font-mono border transition-colors ${on ? 'bg-brand-900/40 text-brand-300 border-brand-700/40' : 'bg-slate-800 text-slate-500 border-slate-700'}`}>
                {a}
              </button>
            );
          })}
        </div>
        <span className="text-xs text-slate-500">question_focus</span>
      </div>

      {entry.errors.length > 0 && (
        <div className="p-3 rounded-lg bg-rose-900/20 border border-rose-800/40 text-sm text-rose-200 space-y-1">
          {entry.errors.map((e, i) => <div key={i} className="flex items-start gap-2"><AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {e}</div>)}
        </div>
      )}

      <button type="button" onClick={onRun} disabled={entry.running}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white font-semibold transition-colors disabled:opacity-50">
        {entry.running ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
        {entry.running ? 'Kör…' : 'Kör bedömning'}
      </button>

      {r && (
        <div className="space-y-3 pt-2 border-t border-slate-700/60">
          <div className="flex items-center gap-2">
            <FileJson className="w-4 h-4 text-emerald-400" />
            <span className="text-sm font-medium text-white">Resultat</span>
            <span className={`badge text-xs ${r._provenance === 'fixture_reference' ? 'badge-green' : 'badge-blue'}`}>
              {r._provenance === 'fixture_reference' ? 'Referens (fixture)' : 'Demo-platshållare'}
            </span>
          </div>

          <div className="p-3 rounded-lg bg-slate-800/50 flex items-center justify-between">
            <span className="text-xs text-slate-500">Tillämplighet</span>
            <div className="flex items-center gap-2">
              <span className={`badge text-xs ${r.applicability.ai_act_applies ? 'badge-red' : 'badge-green'}`}>
                {r.applicability.ai_act_applies ? 'AI-förordningen tillämpas' : 'Tillämpas inte'}
              </span>
              <span className="text-xs text-slate-400">Konfidens: <span className="text-white">{confLabel[r.applicability.confidence]}</span></span>
            </div>
          </div>

          <div className="p-3 rounded-lg bg-slate-800/50 flex items-center justify-between">
            <span className="text-xs text-slate-500">Riskklassificering</span>
            <span className={`badge text-xs ${riskStyles[r.classification.system_risk_class]}`}>
              {riskLabel[r.classification.system_risk_class]}{r.classification.basis_annex ? ` · ${r.classification.basis_annex}` : ''}
            </span>
          </div>

          {r.decision_brief.text && (
            <div className="p-3 rounded-lg bg-slate-800/50">
              <div className="flex items-center gap-2 text-xs text-slate-500 mb-1.5"><BookOpen className="w-4 h-4" /> Beslutsunderlag ({r.decision_brief.language})</div>
              <p className="text-sm text-slate-200 leading-relaxed">{r.decision_brief.text}</p>
            </div>
          )}

          {r.obligations_assessed.length > 0 && (
            <div className="p-3 rounded-lg bg-slate-800/50">
              <div className="flex items-center gap-2 text-xs text-slate-500 mb-1.5"><FileText className="w-4 h-4" /> Skyldigheter</div>
              <div className="space-y-1.5">
                {r.obligations_assessed.map((o, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                    <div>
                      <span className="text-white font-mono">{o.article}</span>
                      {!o.primary_source_verified && <span className="ml-2 badge badge-amber text-xs">Needs primary-source research</span>}
                      <p className="text-slate-400 text-xs mt-0.5">{o.summary}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {r.uncertainties.length > 0 && (
            <div className="p-3 rounded-lg bg-blue-900/20 border border-blue-800/40">
              <div className="flex items-center gap-2 text-xs text-blue-300 mb-1.5"><CircleHelp className="w-4 h-4" /> Osäkerheter</div>
              <div className="space-y-1.5">
                {r.uncertainties.map((u, i) => (
                  <div key={i} className="text-xs">
                    <div className="text-blue-200 font-medium">{u.topic}</div>
                    <div className="text-slate-400">{u.reason}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- portfolio page ----
export default function Assess() {
  const [entries, setEntries] = useState<Entry[]>([newEntry()]);

  const addEmpty = () => setEntries(es => [...es, newEntry()]);
  const addFixture = (id: string) => {
    const fx = assessFixtures.find(f => f.fixture_id === id);
    if (!fx) return;
    const e: Entry = { ...newEntry(), id: crypto.randomUUID(), input: fx.input, result: fx.expected_output, fixture_id: fx.fixture_id };
    setEntries(es => [...es, e]);
  };
  const remove = (id: string) => setEntries(es => es.filter(e => e.id !== id && e.id !== '__delete__'));

  const run = (id: string) => {
    const target = entries.find(e => e.id === id);
    if (!target) return;
    const errs = validateInput(target.input);
    setEntries(setEntry(entries, id, { errors: errs }));
    if (errs.length > 0) return;
    setEntries(setEntry(entries, id, { running: true }));
    setTimeout(() => {
      let result: AssessmentOutput;
      if (target.fixture_id) {
        const fx = assessFixtures.find(f => f.fixture_id === target.fixture_id);
        if (fx && JSON.stringify(fx.input) === JSON.stringify(target.input)) {
          result = fx.expected_output;
        } else {
          result = demoPlaceholder(target.input);
        }
      } else {
        const fx = assessFixtures.find(f => f.input.case_id === target.input.case_id);
        result = fx ? fx.expected_output : demoPlaceholder(target.input);
      }
      setEntries(es => setEntry(es, id, { running: false, result }));
    }, 400);
  };

  const countByRisk = (risk: string) => entries.filter(e => e.result?.classification.system_risk_class === risk).length;
  const assessed = entries.filter(e => e.result).length;
  const applicable = entries.filter(e => e.result?.applicability.ai_act_applies).length;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1">AI Act Bedömning</h1>
          <p className="text-slate-400 max-w-3xl">
            Portföljbedömning mot <code className="text-brand-300">vertical-01-ai-act</code> — Art 2-3, 5, 6, Annex I/III, skyldigheter 9-12.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="badge badge-blue">vertical-01-ai-act v0.1.0</span>
          <span className="badge badge-amber"><AlertTriangle className="w-3 h-3 mr-1" /> Demo-UI</span>
        </div>
      </div>

      <div className="p-3 rounded-lg bg-amber-900/20 border border-amber-800/40 text-sm text-amber-200">
        <div className="flex items-center gap-2 font-medium mb-1"><AlertTriangle className="w-4 h-4" /> Förhandsversion — inte en riktig modelkörning</div>
        <p className="text-slate-400">
          Laddar du en syntetisk fixture visas paketets godkända <strong>referensutfall</strong>; fria indata returnerar en tydligt märkt
          platshållare tills webb-UI:et kopplas till dispatcher/harness (Phase 2 Session B). Inget här är juridiskt bindande.
        </p>
      </div>

      {/* Portfolio aggregate */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <Layers className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-semibold text-white">Portfölj</h2>
          <span className="text-sm text-slate-400">{entries.length} system</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <Stat label="Bedömda" value={assessed} total={entries.length} />
          <Stat label="Omfattas av AIA" value={applicable} color={applicable > 0 ? 'text-rose-300' : 'text-slate-200'} />
          <Stat label="Hög risk / förbjuden" value={countByRisk('high_risk') + countByRisk('prohibited')} color="text-rose-300" />
          <Stat label="Osäkra" value={countByRisk('uncertain')} color="text-blue-300" />
        </div>
        <div className="flex flex-wrap gap-2 mt-4">
          <button type="button" onClick={addEmpty} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors">
            <Plus className="w-4 h-4" /> Lägg till system
          </button>
          <span className="text-xs text-slate-500 self-center mx-1">eller fyll från fixture:</span>
          {assessFixtures.map(fx => (
            <button key={fx.fixture_id} type="button" onClick={() => addFixture(fx.fixture_id)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 text-slate-300 border border-slate-700 text-xs hover:border-brand-600 hover:text-white transition-colors">
              <FlaskConical className="w-3.5 h-3.5" /> {fx.label}
            </button>
          ))}
        </div>
      </div>

      {entries.filter(e => e.id !== '__delete__').map(e => (
        <EntryCard
          key={e.id}
          entry={e}
          onChange={(ne) => ne.id === '__delete__' ? remove(e.id) : setEntries(es => setEntry(es, ne.id, ne))}
          onRun={() => run(e.id)}
        />
      ))}

      <div className="flex items-center gap-2 text-xs text-slate-500">
        <ArrowRight className="w-3 h-3" />
        Nästa steg i produktionsflödet: skicka som Ready-issue → dispatch → Review → din approval (Done).
      </div>
    </div>
  );
}

function Stat({ label, value, total, color }: { label: string; value: number; total?: number; color?: string }) {
  return (
    <div className="p-3 rounded-lg bg-slate-800/50">
      <div className={`text-2xl font-bold ${color || 'text-white'}`}>{value}{total !== undefined ? <span className="text-slate-500 text-base">/{total}</span> : null}</div>
      <div className="text-xs text-slate-400 mt-0.5">{label}</div>
    </div>
  );
}
