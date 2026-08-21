import { describe, it, expect } from 'vitest';
import { calculateCost, estimateRunCost } from '../systemData';

// Exact known profiles (verified against systemData.ts):
//   researcher / model "kimi-k2.6" : costPer1MInput = 0.55, costPer1MOutput = 2.65
//   reviewer   / model "codex"     : costPer1MInput = 1.75, costPer1MOutput = 14.0
// 1_000_000 tokens => exact: input = costPer1MInput, output = costPer1MOutput,
// total = input + output. The variable is deterministic, no early return.

describe('calculateCost — exact sum (known) & null (unknown)', () => {
  it('returns amount null for an unknown model (no false 0)', () => {
    const r = calculateCost('does-not-exist', 5000, 2000);
    expect(r.amount).toBeNull();
    expect(r.currency).toBe('USD');
  });

  it('returns exact input/output/total for a known model at 1M tokens', () => {
    const r = calculateCost('kimi-k2.6', 1_000_000, 1_000_000);
    expect(r.amount).toBeCloseTo(3.2, 5); // 0.55 + 2.65
    expect(r.breakdown.input).toBeCloseTo(0.55, 5);
    expect(r.breakdown.output).toBeCloseTo(2.65, 5);
  });

  it('verifies exact sum for the reviewer (codex) model', () => {
    const r = calculateCost('codex', 1_000_000, 1_000_000);
    expect(r.breakdown.input).toBeCloseTo(1.75, 5);
    expect(r.breakdown.output).toBeCloseTo(14.0, 5);
    expect(r.amount).toBeCloseTo(15.75, 5);
  });
});

describe('estimateRunCost — exact sum (known) & null (unknown)', () => {
  it('returns amount null for an unknown worker role (no false 0)', () => {
    const r = estimateRunCost('does-not-exist', 5000, 2000);
    expect(r.amount).toBeNull();
  });

  it('returns exact input/output/total for researcher at 1M tokens', () => {
    const r = estimateRunCost('researcher', 1_000_000, 1_000_000);
    expect(r.profile).toBe('Researcher'); // estimateRunCost returns profile.name
    const est = (r.amount as number);
    // in 0.55 + out 2.65 = 3.20
    expect(est).toBeCloseTo(3.20, 5);
  });

  it('is deterministic across repeated calls', () => {
    const a = estimateRunCost('researcher', 5_000, 2_000);
    const b = estimateRunCost('researcher', 5_000, 2_000);
    expect(a.amount).toBe(b.amount);
    expect(a.amount).not.toBeNull();
  });
});
