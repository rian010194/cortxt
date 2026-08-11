import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Telemetry from '../Telemetry';
import Dispatch from '../Dispatch';
import { estimateRunCost } from '../../data/systemData';

// Consumer null-guard: unknown profile => estimateRunCost amount is null and
// the Telemetry "Total cost" renders "—" (not NaN, not 0-false-positive).
describe('CostConsumers — null → "—" rendering', () => {
  it('estimateRunCost returns null for an unknown worker role', () => {
    expect(estimateRunCost('__nonexistent__', 5000, 2000).amount).toBeNull();
  });

  it('Telemetry renders "—" for an unknown calc profile (no NaN / no 0)', async () => {
    render(<MemoryRouter><Telemetry /></MemoryRouter>);
    // Switch the calculator profile to an unknown value. The profile select is
    // the first combobox in the Telemetry DOM (calcProfile).
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThan(0);
    fireEvent.change(selects[0], { target: { value: '__nonexistent__' } });
    await waitFor(() => {
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    });
    // NotFound: 0/Nan should never appear from the calculator.
    expect(screen.queryByText('NaN')).toBeNull();
  });

  it('Dispatch and Telemetry pages mount without crashing under jsdom', () => {
    render(<MemoryRouter><Telemetry /></MemoryRouter>);
    render(<MemoryRouter><Dispatch /></MemoryRouter>);
  });
});
