// Type definitions + synthetic-fixture presets for vertical-01-ai-act.
// Grounded in the package schemas (ai-act-assessment-input/output.schema.json)
// and the synthetic eval fixtures under verticals/vertical-01-ai-act/evals/synthetic/.
// NOTE: this is the UI prototype's local copy of 4 representative fixtures;
// the canonical fixtures live in the vertical package (verticals/.../evals/synthetic/).

export type OperatorType = 'deployer' | 'provider' | 'importer' | 'distributor';
export type RiskClass = 'prohibited' | 'high_risk' | 'limited_risk' | 'minimal_risk' | 'uncertain';
export type Confidence = 'certain' | 'probable' | 'uncertain' | 'needs_more_info';
export type QuestionFocus = 'Art2' | 'Art3' | 'Art5' | 'Art6' | 'Art9' | 'Art10' | 'Art11' | 'Art12';

export interface AssessmentInput {
  case_id: string;
  system_description: {
    name: string;
    purpose: string;
    intended_market: string;
    operator_type: OperatorType;
  };
  system_capabilities: string[];
  known_standards?: string[];
  jurisdiction_hints: string[];
  question_focus: QuestionFocus[];
}

export interface AssessmentObligation {
  article: string;
  applies: boolean;
  summary: string;
  evidence_refs: string[];
  primary_source_verified: boolean;
}

export interface AssessmentOutput {
  case_id: string;
  assessed_version: string;
  applicability: {
    ai_act_applies: boolean;
    confidence: Confidence;
    basis_articles: string[];
  };
  classification: {
    system_risk_class: RiskClass;
    basis_annex: string | null;
  };
  obligations_assessed: AssessmentObligation[];
  decision_brief: { language: 'sv'; text: string };
  uncertainties: { topic: string; reason: string; suggested_research: string }[];
  schema_validation_passed: boolean;
  // UI-only provenance, never part of the package schema:
  _provenance?: 'fixture_reference' | 'demo_placeholder';
}

export interface AssessFixture {
  fixture_id: string;
  label: string;
  category: 'positive' | 'negative' | 'boundary' | 'uncertainty';
  input: AssessmentInput;
  expected_output: AssessmentOutput;
}

export const assessFixtures: AssessFixture[] = [
  {
    fixture_id: 'v01-syn-pos-001',
    label: 'Högrisk medicinsk diagnos (positiv)',
    category: 'positive',
    input: {
      case_id: 'SYNTH-POS-001',
      system_description: {
        name: 'MedDiagnose AI',
        purpose: 'Analyse patient symptoms and suggest preliminary diagnoses for healthcare professionals.',
        intended_market: 'EU hospitals and clinics',
        operator_type: 'provider',
      },
      system_capabilities: ['natural-language medical intake', 'symptom-to-disease ranking', 'treatment recommendation suggestions'],
      known_standards: ['ISO 13485', 'MDR 2017/745'],
      jurisdiction_hints: ['EU'],
      question_focus: ['Art2', 'Art3', 'Art5', 'Art6', 'Art9', 'Art10', 'Art11', 'Art12'],
    },
    expected_output: {
      case_id: 'SYNTH-POS-001',
      assessed_version: '0.1.0',
      applicability: { ai_act_applies: true, confidence: 'probable', basis_articles: ['Art2', 'Art3', 'Art6'] },
      classification: { system_risk_class: 'high_risk', basis_annex: 'Annex III' },
      obligations_assessed: [
        { article: 'Art9', applies: true, summary: 'Risk management system required throughout lifecycle. Needs primary-source research for exact ISO 14971 alignment.', evidence_refs: ['EUR-Lex 32024R1689', 'ISO 14971:2019'], primary_source_verified: false },
        { article: 'Art10', applies: true, summary: 'Data governance obligations apply; training data quality must be documented. Needs primary-source research for post-deployment data scope.', evidence_refs: ['EUR-Lex 32024R1689'], primary_source_verified: false },
        { article: 'Art11', applies: true, summary: 'Technical documentation per Annex IV required. Needs primary-source research for component-level documentation.', evidence_refs: ['EUR-Lex 32024R1689', 'Annex IV'], primary_source_verified: false },
        { article: 'Art12', applies: true, summary: 'Automatic logging of operation events required. Needs primary-source research for retention period.', evidence_refs: ['EUR-Lex 32024R1689'], primary_source_verified: false },
      ],
      decision_brief: { language: 'sv', text: 'Systemet MedDiagnose AI sannolikt omfattas av AI-förordningen och klassas som högrisk enligt Annex III (hälsa). Artiklarna 9-12 är tillämpliga. Primärkällsverifiering krävs för samtliga skyldigheter.' },
      uncertainties: [
        { topic: 'Annex III point 1(a) medical device overlap', reason: 'MDR classification may affect AI Act risk class.', suggested_research: 'Verify MDR Article 51 classification against AI Act Annex III point 1(a).' },
      ],
      schema_validation_passed: true,
      _provenance: 'fixture_reference',
    },
  },
  {
    fixture_id: 'v01-syn-neg-001',
    label: 'Traditionell bokföringsprogramvara (negativ)',
    category: 'negative',
    input: {
      case_id: 'SYNTH-NEG-001',
      system_description: {
        name: 'LedgerPro Classic',
        purpose: 'Double-entry bookkeeping, invoicing, and VAT reporting for small businesses using deterministic rule-based logic.',
        intended_market: 'EU small and medium enterprises',
        operator_type: 'provider',
      },
      system_capabilities: ['automated ledger posting', 'VAT calculation', 'invoice generation'],
      known_standards: ['ISO 27001'],
      jurisdiction_hints: ['EU'],
      question_focus: ['Art2', 'Art3', 'Art5', 'Art6'],
    },
    expected_output: {
      case_id: 'SYNTH-NEG-001',
      assessed_version: '0.1.0',
      applicability: { ai_act_applies: false, confidence: 'certain', basis_articles: ['Art2', 'Art3'] },
      classification: { system_risk_class: 'minimal_risk', basis_annex: null },
      obligations_assessed: [],
      decision_brief: { language: 'sv', text: 'Systemet LedgerPro Classic omfattas inte av AI-förordningen eftersom det saknar självständigt inlärande och använder enbart deterministiska regler. Klassas som minimal risk.' },
      uncertainties: [],
      schema_validation_passed: true,
      _provenance: 'fixture_reference',
    },
  },
  {
    fixture_id: 'v01-syn-bnd-001',
    label: 'Crowd-räkning utan identifiering (gränsfall)',
    category: 'boundary',
    input: {
      case_id: 'SYNTH-BND-001',
      system_description: {
        name: 'CrowdCount AI',
        purpose: 'Estimate the number of people in a public space using overhead cameras and silhouette detection. Does not identify individuals or store facial data.',
        intended_market: 'EU retail and transport operators',
        operator_type: 'deployer',
      },
      system_capabilities: ['silhouette detection', 'crowd density estimation', 'no facial recognition'],
      known_standards: [],
      jurisdiction_hints: ['EU'],
      question_focus: ['Art2', 'Art3', 'Art5', 'Art6'],
    },
    expected_output: {
      case_id: 'SYNTH-BND-001',
      assessed_version: '0.1.0',
      applicability: { ai_act_applies: true, confidence: 'uncertain', basis_articles: ['Art2', 'Art3'] },
      classification: { system_risk_class: 'uncertain', basis_annex: null },
      obligations_assessed: [],
      decision_brief: { language: 'sv', text: 'Systemet CrowdCount AI kan omfattas av AI-förordningen, men riskklassificeringen är osäker. Avsaknaden av identifiering talar emot Annex III, medan biometrisk bearbetning talar för. Primärkällsverifiering krävs.' },
      uncertainties: [
        { topic: 'Annex III point 1(a) vs point 1(b) biometric boundary', reason: 'The system processes biometric data (silhouettes) but claims not to identify individuals. It is unclear whether pure counting falls under Annex III point 1(a) or 1(b).', suggested_research: 'Verify whether crowd-counting by silhouette is classified as biometric identification or categorisation under Annex III.' },
        { topic: 'Article 3(1) AI definition for silhouette detection', reason: 'The underlying model may use machine learning or traditional computer vision. The AI definition boundary is unclear without architecture details.', suggested_research: 'Confirm whether silhouette-detection models typically qualify as AI systems under Article 3(1).' },
      ],
      schema_validation_passed: true,
      _provenance: 'fixture_reference',
    },
  },
  {
    fixture_id: 'v01-syn-unc-001',
    label: 'Knapphändig beskrivning (osäkerhet)',
    category: 'uncertainty',
    input: {
      case_id: 'SYNTH-UNC-001',
      system_description: {
        name: 'Project X',
        purpose: 'AI system for internal use.',
        intended_market: 'Unknown',
        operator_type: 'provider',
      },
      system_capabilities: ['AI processing'],
      known_standards: [],
      jurisdiction_hints: ['EU'],
      question_focus: ['Art2', 'Art3', 'Art5', 'Art6'],
    },
    expected_output: {
      case_id: 'SYNTH-UNC-001',
      assessed_version: '0.1.0',
      applicability: { ai_act_applies: false, confidence: 'needs_more_info', basis_articles: ['Art2', 'Art3'] },
      classification: { system_risk_class: 'uncertain', basis_annex: null },
      obligations_assessed: [],
      decision_brief: { language: 'sv', text: 'Beskrivningen av Project X är för knapphändig för att göra en säker bedömning. Ytterligare information om syfte, marknad och teknisk arkitektur krävs.' },
      uncertainties: [
        { topic: 'Insufficient system description', reason: "The purpose is too vague ('internal use'), intended_market is 'Unknown', and capabilities list contains only a generic phrase.", suggested_research: 'Request detailed system description including specific use case, technical architecture, and intended deployers.' },
        { topic: 'Operator type unverified', reason: 'The operator_type is stated as provider, but the actual role in the value chain is unclear from the description.', suggested_research: 'Confirm whether the entity is a provider, deployer, importer, or distributor under Article 3.' },
      ],
      schema_validation_passed: true,
      _provenance: 'fixture_reference',
    },
  },
];

// Client-side validation mirroring the input schema's key rules (not a full
// JSON-Schema validator). Returns a list of message strings (empty = valid).
export function validateInput(input: AssessmentInput): string[] {
  const errors: string[] = [];
  if (!/^(SYNTH-|EXT-).+$/.test(input.case_id)) errors.push('case_id måste börja med SYNTH- eller EXT-');
  if (!input.system_description.name.trim()) errors.push('system_description.name krävs');
  if (!input.system_description.purpose.trim()) errors.push('system_description.purpose krävs');
  if (input.system_description.purpose.length > 2000) errors.push('purpose får vara max 2000 tecken');
  if (input.system_description.name.length > 200) errors.push('name får vara max 200 tecken');
  const ops = ['deployer', 'provider', 'importer', 'distributor'];
  if (!ops.includes(input.system_description.operator_type)) errors.push('operator_type måste vara deployer/provider/importer/distributor');
  if (input.system_capabilities.length === 0) errors.push('minst en system_capability krävs');
  if (input.jurisdiction_hints.length === 0) errors.push('minst en jurisdiction_hint krävs');
  return errors;
}
