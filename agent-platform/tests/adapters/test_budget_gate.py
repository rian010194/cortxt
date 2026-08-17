"""Unit tests for BudgetGate (Fas 2A DM3 AC1 + CP1.1 P2-fix)."""

from __future__ import annotations

import pytest

from adapters.inference.budget_gate import BudgetExhausted, BudgetGate


def test_blocks_when_budget_zero(monkeypatch, tmp_path):
    monkeypatch.delenv("FAS2A_INFERENCE_BUDGET_MAX", raising=False)
    gate = BudgetGate(max_calls=0, db_path=tmp_path / "t.db")
    with pytest.raises(BudgetExhausted):
        gate(lambda: 1)


def test_success_consumes_budget(monkeypatch, tmp_path):
    gate = BudgetGate(max_calls=1, db_path=tmp_path / "t.db")
    assert gate(lambda: 42) == 42
    assert gate.remaining == 0
    with pytest.raises(BudgetExhausted):
        gate(lambda: 1)


def test_failed_call_still_counts_attempt(monkeypatch, tmp_path):
    """CP1.1 P2 + CP2.1 P2: a raised/failed call still consumes budget and logs a failure row."""
    import sqlite3

    db = tmp_path / "t.db"
    gate = BudgetGate(max_calls=1, db_path=db)

    def boom():
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        gate(boom)
    # The failed attempt consumed the single budget slot -> next call blocked.
    assert gate.remaining == 0
    with pytest.raises(BudgetExhausted):
        gate(lambda: 1)
    # The failure is observable: an attempt_started row + a failed row (CP2.1 P2).
    with sqlite3.connect(db) as conn:
        statuses = [
            r[0]
            for r in conn.execute("SELECT cost_status FROM fas2a_inference_spend").fetchall()
        ]
    assert "attempt_started" in statuses and "failed" in statuses


def test_attempt_started_row_uses_set_route_id(tmp_path):
    """Fas7 Beslut 6 route isolation: found via a live Fas B run, 2026-08-17 --
    the upfront attempt_started record() call didn't pass route_id, so every
    attempt row always showed the "l0-default" default regardless of
    set_route_id(), even though the later success/failed rows did it right.
    """
    import sqlite3

    db = tmp_path / "t.db"
    gate = BudgetGate(max_calls=1, db_path=db)
    gate.set_route_id("selfhosted-qwen3-8b-awq")
    gate(lambda: 42)
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT route_id FROM fas2a_inference_spend WHERE cost_status='attempt_started'"
        ).fetchall()
    assert all(r[0] == "selfhosted-qwen3-8b-awq" for r in rows)


def test_db_records_attempt_rows(monkeypatch, tmp_path):
    import sqlite3

    db = tmp_path / "t.db"
    gate = BudgetGate(max_calls=2, db_path=db)
    gate(lambda: 1)
    gate(lambda: 2)
    with sqlite3.connect(db) as conn:
        total = conn.execute("SELECT COUNT(*) FROM fas2a_inference_spend").fetchone()[0]
        units = conn.execute(
            "SELECT COUNT(*) FROM fas2a_inference_spend WHERE cost_status='attempt_started'"
        ).fetchone()[0]
        successes = conn.execute(
            "SELECT COUNT(*) FROM fas2a_inference_spend WHERE cost_status='success'"
        ).fetchone()[0]
    # 2 calls = 2 call-units (attempt_started) + 2 success outcome rows (CP3.1 P2), 4 rows total.
    assert units == 2
    assert successes == 2
    assert total == 4
