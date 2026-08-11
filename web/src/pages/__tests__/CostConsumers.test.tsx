import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Telemetry from '../Telemetry';
import Dispatch from '../Dispatch';
import { estimateRunCost } from '../../data/systemData';

// Consumer null-guard: unknown profile => estimateRunCost amount is null and the
// consumers render "—" (not NaN, not a false $0.00, not a misleading low-ceiling
// warning).
describe('CostConsumers — null → "—" rendering', () => {
  it('estimateRunCost returns null for an unknown worker role', () => {
    // 'monitor' is a dispatchSchema worker_role value that is NOT a known profile
    // in systemData, so estimateRunCost resolves to null (a real unknown cost).
    expect(estimateRunCost('monitor', 5000, 2000).amount).toBeNull();
  });

  it('Dispatch renders "—" for a real unknown cost, with no NaN / false $0.00 / low-ceiling warning', async () => {
    render(<MemoryRouter><Dispatch /></MemoryRouter>);
    // The worker_role select is the first combobox in the Dispatch form.
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThan(0);
    // Request tab shows the live estimate; switch worker_role to the unknown
    // profile value 'monitor' to force a null estimate in the rendered UI.
    const roleSelect = selects[0];
    // Only switch if 'monitor' is a valid option (it is per dispatchSchema).
    fireEvent.change(roleSelect, { target: { value: 'monitor' } });

    await waitFor(() => {
      // The estimate line renders "—" (as part of "— <currency>") when amount null.
      expect(screen.getAllByText(/—/).length).toBeGreaterThan(0);
      // Never NaN, never a false $0.00, never a misleading low-ceiling warning.
      expect(screen.queryByText('NaN')).toBeNull();
      expect(screen.queryByText('$0.00')).toBeNull();
    });
    // Low-ceiling warning text must not appear when the estimate is unknown.
    expect(screen.queryByText(/Low ceiling/i)).toBeNull();
  });

  it('Telemetry renders "—" for an unknown calc profile (no NaN / no 0)', async () => {
    render(<MemoryRouter><Telemetry /></MemoryRouter>);
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThan(0);
    fireEvent.change(selects[0], { target: { value: '__nonexistent__' } });
    await waitFor(() => {
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    });
    expect(screen.queryByText('NaN')).toBeNull();
  });

  it('Dispatch and Telemetry pages mount without crashing under jsdom', () => {
    render(<MemoryRouter><Telemetry /></MemoryRouter>);
    render(<MemoryRouter><Dispatch /></MemoryRouter>);
  });
});
