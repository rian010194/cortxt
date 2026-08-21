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

  it('Dispatch estimate shows "—" for a real unknown cost, with no NaN / false $0.00 / low-ceiling warning', async () => {
    render(<MemoryRouter><Dispatch /></MemoryRouter>);
    // The worker_role select is the first combobox in the Dispatch form.
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThan(0);
    // Switch worker_role to the unknown profile value 'monitor' (a valid option,
    // but not a known profile) to force a null estimate in the rendered UI.
    fireEvent.change(selects[0], { target: { value: 'monitor' } });

    await waitFor(() => {
      // Locate the ESTIMATE line explicitly (not any "—" anywhere on the page):
      // the row labelled "Est. for 5k in + 2k out:" must contain "—".
      const label = screen.getByText(/Est\. for 5k in \+ 2k out:/);
      const row = label.closest('div');
      expect(row).toBeTruthy();
      const rowText = (row as HTMLElement).textContent;
      expect(rowText).toContain('—');
      // The estimate value renders "—" (not a numeral), so NaN / "$0.00" never
      // appear and the low-ceiling warning (bounded by est.amount) is absent.
      expect(rowText).not.toMatch(/NaN/);
      expect(rowText).not.toMatch(/\$0\.00/);
    });
    // Low-ceiling warning must not appear when the estimate is unknown.
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
