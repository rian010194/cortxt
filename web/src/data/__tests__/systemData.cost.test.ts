import { describe, it, expect } from 'vitest';
import { calculateCost, estimateRunCost, profiles } from '../systemData';

// A model/profile that does NOT exist in systemData => unknown -> null
describe('calculateCost', () => {
  it('returns amount null for an unknown model (no false 0)', () => {
    const r = calculateCost('does-not-exist', 5000, 2000);
    expect(r.amount).toBeNull();
    expect(r.currency).toBe('USD');
  });

  it('returns a numeric amount for a known model', () => {
    const known = profiles.find(p => p.costPer1MInput !== undefined && p.costPer1MOutput !== undefined && p.model);
    if (!known?.model) return; // no known model in this fixture set
    const r = calculateCost(known.model, 1_000_000, 0);
    expect(typeof r.amount).toBe('number');
    expect((r.amount as number)).toBe(known.costPer1MInput);
  });
});

describe('estimateRunCost', () => {
  it('returns amount null for an unknown worker role (no false 0)', () => {
    const r = estimateRunCost('does-not-exist', 5000, 2000);
    expect(r.amount).toBeNull();
  });

  it('returns a numeric amount for a known worker', () => {
    const known = profiles.find(p => p.costPer1MInput !== undefined);
    if (!known) return;
    const r = estimateRunCost(known.id, 1000, 1000);
    expect(typeof r.amount).toBe('number');
  });
});
